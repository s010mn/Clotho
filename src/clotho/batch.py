"""批量压力导数复现实验入口的内部工具。

这里处理人工 manifest CSV，把多个 stage 依次转换为：

stage params + stage curve
→ 人工有效压降窗口
→ 显式重复 elapsed policy
→ derivative-readiness
→ ready 时导出 dP/dG 与 G dP/dG CSV
→ batch summary CSV

本文件不做 closure、不做 smoothing、不做自动主动放压识别、不做重采样、
不做 Carter/PKN/volume balance/裂缝反演。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from clotho.g_function import nolte_g_time
from clotho.pressure_derivative import derivative_value_summary, pressure_derivative_against_g_time
from clotho.stage_data import (
    StageInfo,
    add_estimated_bottomhole_pressure,
    apply_elapsed_duplicate_policy,
    falloff_window_after_shut_in,
    find_shut_in_index,
    read_stage_curve,
    read_stage_params,
    volume_over_max_rate_duration_seconds,
)

_ALLOWED_DUPLICATE_POLICIES = {"none", "keep-first", "keep-last", "mean"}
_REQUIRED_MANIFEST_COLUMNS = {"stage", "max_sustained_rate", "valid_falloff_end_elapsed"}
_SUMMARY_DERIVATIVE_FIELDS = [
    "pressure_derivative_dP_dG_finite_count",
    "pressure_derivative_dP_dG_positive_count",
    "pressure_derivative_dP_dG_negative_count",
    "pressure_derivative_dP_dG_zero_count",
    "pressure_derivative_dP_dG_min",
    "pressure_derivative_dP_dG_median",
    "pressure_derivative_dP_dG_max",
    "pressure_derivative_G_dP_dG_finite_count",
    "pressure_derivative_G_dP_dG_positive_count",
    "pressure_derivative_G_dP_dG_negative_count",
    "pressure_derivative_G_dP_dG_zero_count",
    "pressure_derivative_G_dP_dG_min",
    "pressure_derivative_G_dP_dG_median",
    "pressure_derivative_G_dP_dG_max",
]


def run_derivative_batch(
    *,
    stage_params_path: str | Path,
    well_root: str | Path,
    manifest_path: str | Path,
    output_dir: str | Path,
    volume_column: str,
    rate_time_unit: str,
    g_time_m: float,
    well: str | None = None,
    min_rate: float = 10.0,
    summary_name: str = "derivative_batch_summary.csv",
) -> dict[str, Any]:
    """运行批量压力导数复现实验。

    manifest 必须由人显式给出每段的 max_sustained_rate 和
    valid_falloff_end_elapsed。本函数不自动识别主动放压、不自动挑 closure。
    """
    output_root = Path(output_dir)
    if not output_root.exists() or not output_root.is_dir():
        raise ValueError(f"output directory does not exist: {output_root}")

    safe_summary_name = _safe_output_name(summary_name, field_name="summary_name")
    summary_path = output_root / safe_summary_name

    manifest = pd.read_csv(manifest_path, dtype=str, keep_default_na=False)
    missing = sorted(_REQUIRED_MANIFEST_COLUMNS - set(manifest.columns))
    if missing:
        raise ValueError(f"manifest 缺少必填列: {', '.join(missing)}")

    stages = read_stage_params(stage_params_path)
    rows: list[dict[str, Any]] = []
    written_count = 0

    for row_index, row in manifest.iterrows():
        config = _parse_manifest_row(row, row_index=row_index)
        stage_info = _find_stage(stages, stage_number=config["stage"], well=well)
        output_path = output_root / config["output_name"]
        result = _build_derivative_result_for_stage(
            stage=stage_info,
            well_root=Path(well_root),
            output_path=output_path,
            volume_column=volume_column,
            rate_time_unit=rate_time_unit,
            min_rate=float(min_rate),
            max_sustained_rate=config["max_sustained_rate"],
            valid_falloff_end_elapsed=config["valid_falloff_end_elapsed"],
            elapsed_duplicate_policy=config["elapsed_duplicate_policy"],
            g_time_m=float(g_time_m),
        )
        derivative_table = result.pop("derivative_table")
        summary_row = result["summary_row"]
        if derivative_table is not None:
            derivative_table.to_csv(output_path, index=False)
            summary_row["pressure_derivative_output_written"] = True
            written_count += 1
        rows.append(summary_row)

    summary = pd.DataFrame(rows)
    summary.to_csv(summary_path, index=False)

    ready_count = int(summary["derivative_readiness_ready"].sum()) if len(summary) else 0
    return {
        "stage_count": int(len(summary)),
        "ready_stage_count": ready_count,
        "not_ready_stage_count": int(len(summary) - ready_count),
        "derivative_csv_written_count": written_count,
        "summary_path": summary_path,
        "summary": summary,
    }


def _parse_manifest_row(row: pd.Series, *, row_index: int) -> dict[str, Any]:
    stage = _parse_int_cell(row, "stage", row_index=row_index)
    max_sustained_rate = _parse_float_cell(row, "max_sustained_rate", row_index=row_index)
    if max_sustained_rate <= 0.0:
        raise ValueError("max_sustained_rate 必须大于 0")

    valid_end = _parse_float_cell(row, "valid_falloff_end_elapsed", row_index=row_index)
    if valid_end < 0.0:
        raise ValueError("valid_falloff_end_elapsed 必须 >= 0")

    policy = str(row.get("elapsed_duplicate_policy", "")).strip() or "none"
    if policy not in _ALLOWED_DUPLICATE_POLICIES:
        raise ValueError("elapsed_duplicate_policy 必须是 none / keep-first / keep-last / mean")

    output_name = str(row.get("output_name", "")).strip() or f"stage_{stage:02d}_derivative.csv"
    output_name = _safe_output_name(output_name, field_name="output_name")

    return {
        "stage": stage,
        "max_sustained_rate": max_sustained_rate,
        "valid_falloff_end_elapsed": valid_end,
        "elapsed_duplicate_policy": policy,
        "output_name": output_name,
    }


def _parse_int_cell(row: pd.Series, column: str, *, row_index: int) -> int:
    text = str(row.get(column, "")).strip()
    if text == "":
        raise ValueError(f"manifest 第 {row_index + 1} 行缺少 {column}")
    try:
        return int(text)
    except ValueError as exc:
        raise ValueError(f"manifest 第 {row_index + 1} 行 {column} 必须是整数") from exc


def _parse_float_cell(row: pd.Series, column: str, *, row_index: int) -> float:
    text = str(row.get(column, "")).strip()
    if text == "":
        raise ValueError(f"manifest 第 {row_index + 1} 行缺少 {column}")
    try:
        value = float(text)
    except ValueError as exc:
        raise ValueError(f"manifest 第 {row_index + 1} 行 {column} 必须是数字") from exc
    if not np.isfinite(value):
        raise ValueError(f"manifest 第 {row_index + 1} 行 {column} 必须是有限数字")
    return value


def _safe_output_name(name: str, *, field_name: str) -> str:
    text = str(name).strip()
    if text == "" or text in {".", ".."} or "/" in text or "\\" in text or Path(text).is_absolute():
        raise ValueError(f"{field_name} 不能包含路径分隔符或写出 output-dir")
    return text


def _find_stage(stages: list[StageInfo], *, stage_number: int, well: str | None) -> StageInfo:
    matches = [stage for stage in stages if stage.stage == stage_number and (well is None or stage.well == well)]
    if not matches:
        raise ValueError(f"找不到 stage={stage_number} 的记录")
    if len(matches) > 1:
        raise ValueError(f"stage={stage_number} 匹配多行，请用 --well 指定井名")
    return matches[0]


def _build_derivative_result_for_stage(
    *,
    stage: StageInfo,
    well_root: Path,
    output_path: Path,
    volume_column: str,
    rate_time_unit: str,
    min_rate: float,
    max_sustained_rate: float,
    valid_falloff_end_elapsed: float,
    elapsed_duplicate_policy: str,
    g_time_m: float,
) -> dict[str, Any]:
    curve_file = well_root / stage.data_file
    curve = read_stage_curve(curve_file)
    shut_in_index = find_shut_in_index(curve, stage.shut_in_time)
    tp_seconds = volume_over_max_rate_duration_seconds(
        curve,
        shut_in_index,
        max_sustained_rate=max_sustained_rate,
        rate_time_unit=rate_time_unit,
        volume_column=volume_column,
    )

    raw_window = falloff_window_after_shut_in(curve, shut_in_index)
    falloff_window = falloff_window_after_shut_in(
        curve,
        shut_in_index,
        end_elapsed_seconds=valid_falloff_end_elapsed,
    )
    readiness_window = apply_elapsed_duplicate_policy(
        falloff_window,
        policy=elapsed_duplicate_policy,
    )

    elapsed = readiness_window["elapsed_seconds"].to_numpy(dtype=float)
    delta = elapsed / float(tp_seconds)
    g_time = np.asarray(nolte_g_time(delta, g_time_m), dtype=float)
    pressure_window, pressure_column, pressure_values = _pressure_window_and_values(readiness_window, stage)
    blockers = _readiness_blockers(g_time, pressure_values)
    ready = not blockers

    summary_row: dict[str, Any] = {
        "stage": stage.stage,
        "well": stage.well,
        "curve_file": str(curve_file),
        "shut_in_time": stage.shut_in_time,
        "shut_in_index": shut_in_index,
        "volume_column": volume_column,
        "rate_time_unit": rate_time_unit,
        "min_rate": float(min_rate),
        "max_sustained_rate": float(max_sustained_rate),
        "volume_over_max_sustained_rate_seconds": float(tp_seconds),
        "valid_falloff_end_elapsed": float(valid_falloff_end_elapsed),
        "elapsed_duplicate_policy": elapsed_duplicate_policy,
        "falloff_window_raw_rows": len(raw_window),
        "falloff_window_rows_after_valid_end": len(falloff_window),
        "falloff_window_rows_after_duplicate_policy": len(readiness_window),
        "falloff_window_rows_removed_by_valid_end": len(raw_window) - len(falloff_window),
        "falloff_window_rows_removed_by_duplicate_policy": len(falloff_window) - len(readiness_window),
        "derivative_readiness_ready": ready,
        "derivative_readiness_blockers": "none" if ready else "; ".join(blockers),
        "derivative_was_computed": False,
        "closure_was_computed": False,
        "pressure_derivative_output_written": False,
        "pressure_derivative_output_path": str(output_path),
        "pressure_derivative_pressure_column": pressure_column,
    }
    _fill_empty_derivative_summary(summary_row)

    derivative_table = None
    if ready:
        dP_dG, G_dP_dG = pressure_derivative_against_g_time(g_time, pressure_values)
        derivative_table = _derivative_table(
            pressure_window=pressure_window,
            delta=delta,
            g_time=g_time,
            pressure_column=pressure_column,
            pressure_values=pressure_values,
            dP_dG=dP_dG,
            G_dP_dG=G_dP_dG,
        )
        summary_row["derivative_was_computed"] = True
        _fill_derivative_summary(summary_row, "pressure_derivative_dP_dG", derivative_value_summary(dP_dG))
        _fill_derivative_summary(summary_row, "pressure_derivative_G_dP_dG", derivative_value_summary(G_dP_dG))

    return {"summary_row": summary_row, "derivative_table": derivative_table}


def _pressure_window_and_values(window: pd.DataFrame, stage: StageInfo) -> tuple[pd.DataFrame, str, np.ndarray]:
    if stage.liquid_column_pressure_mpa is not None:
        pressure_window = add_estimated_bottomhole_pressure(window, stage)
        pressure_column = "estimated_bottomhole_pressure_mpa"
    else:
        pressure_window = window.copy()
        pressure_column = "wellhead_pressure_mpa"
    pressure_values = pressure_window[pressure_column].to_numpy(dtype=float)
    return pressure_window, pressure_column, pressure_values


def _readiness_blockers(g_time: np.ndarray, pressure_values: np.ndarray) -> list[str]:
    blockers: list[str] = []
    if len(g_time) < 3:
        blockers.append("post-shut-in samples fewer than 3")
    if not np.all(np.isfinite(g_time)):
        blockers.append("G-time contains NaN or inf")
    if not np.all(np.isfinite(pressure_values)):
        blockers.append("pressure column contains NaN or inf")
    if len(g_time) < 2 or not np.all(np.diff(g_time) > 0.0):
        blockers.append("G-time is not strictly increasing")
    return blockers


def _fill_empty_derivative_summary(summary_row: dict[str, Any]) -> None:
    for field in _SUMMARY_DERIVATIVE_FIELDS:
        summary_row[field] = np.nan


def _fill_derivative_summary(summary_row: dict[str, Any], prefix: str, summary: dict[str, float | int]) -> None:
    for name in ["finite_count", "positive_count", "negative_count", "zero_count", "min", "median", "max"]:
        summary_row[f"{prefix}_{name}"] = summary[name]


def _derivative_table(
    *,
    pressure_window: pd.DataFrame,
    delta: np.ndarray,
    g_time: np.ndarray,
    pressure_column: str,
    pressure_values: np.ndarray,
    dP_dG: np.ndarray,
    G_dP_dG: np.ndarray,
) -> pd.DataFrame:
    data: dict[str, Any] = {
        "row_number": np.arange(len(g_time), dtype=int),
        "elapsed_seconds": pressure_window["elapsed_seconds"].to_numpy(dtype=float),
        "delta": np.asarray(delta, dtype=float),
        "nolte_g_time": np.asarray(g_time, dtype=float),
        "pressure_column": [pressure_column] * len(g_time),
        "pressure_mpa": np.asarray(pressure_values, dtype=float),
        "wellhead_pressure_mpa": pressure_window["wellhead_pressure_mpa"].to_numpy(dtype=float),
        "dP_dG_mpa": np.asarray(dP_dG, dtype=float),
        "G_dP_dG_mpa": np.asarray(G_dP_dG, dtype=float),
    }
    if "estimated_bottomhole_pressure_mpa" in pressure_window.columns:
        data["estimated_bottomhole_pressure_mpa"] = pressure_window[
            "estimated_bottomhole_pressure_mpa"
        ].to_numpy(dtype=float)
    if "time_text" in pressure_window.columns:
        data["time_text"] = pressure_window["time_text"].astype(str).to_numpy()
    return pd.DataFrame(data)
