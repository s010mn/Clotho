"""导数 CSV 人工审查清单工具。

本模块读取 `clotho derivative-batch` 生成的 summary CSV 和 per-stage
pressure derivative CSV，输出一个面向人工审查的 CSV 表。

这里不做 closure、不挑闭合点、不解释导数曲线形态、不做 smoothing 或重采样。
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def build_derivative_review_table(
    summary_csv: str | Path,
    *,
    derivative_dir: str | Path | None = None,
    large_duplicate_removal_threshold: int = 10,
    positive_derivative_ratio_threshold: float = 0.5,
    large_abs_dpdg_threshold: float | None = None,
) -> pd.DataFrame:
    """从 batch summary 和导数 CSV 生成人工审查清单。

    这里只做数据质量和数值范围摘要；不判断 closure，不解释导数形态，
    不做 smoothing 或重采样。
    """
    summary_path = Path(summary_csv)
    if not summary_path.exists():
        raise ValueError(f"summary does not exist: {summary_path}")

    derivative_root = Path(derivative_dir) if derivative_dir is not None else summary_path.parent
    if not derivative_root.exists() or not derivative_root.is_dir():
        raise ValueError(f"derivative directory does not exist: {derivative_root}")

    if large_duplicate_removal_threshold < 0:
        raise ValueError("large_duplicate_removal_threshold must be >= 0")
    if not np.isfinite(positive_derivative_ratio_threshold):
        raise ValueError("positive_derivative_ratio_threshold must be finite")
    if large_abs_dpdg_threshold is not None:
        if not np.isfinite(large_abs_dpdg_threshold) or large_abs_dpdg_threshold < 0.0:
            raise ValueError("large_abs_dpdg_threshold must be finite and >= 0")

    summary = pd.read_csv(summary_path)
    rows: list[dict[str, Any]] = []
    for _, row in summary.iterrows():
        review_row = _review_row(
            row,
            derivative_root=derivative_root,
            large_duplicate_removal_threshold=int(large_duplicate_removal_threshold),
            positive_derivative_ratio_threshold=float(positive_derivative_ratio_threshold),
            large_abs_dpdg_threshold=large_abs_dpdg_threshold,
        )
        rows.append(review_row)
    return pd.DataFrame(rows)


def write_derivative_review_csv(
    review: pd.DataFrame,
    output: str | Path,
) -> Path:
    """写出人工审查 CSV。parent directory 必须已经存在。"""
    output_path = Path(output)
    if not output_path.parent.exists():
        raise ValueError(f"output parent directory does not exist: {output_path.parent}")
    review.to_csv(output_path, index=False)
    return output_path


def build_derivative_context_table(
    review_csv: str | Path,
    *,
    derivative_dir: str | Path | None = None,
    stages: Sequence[int] | None = None,
    top_abs_dpdg_per_stage: int = 3,
    context_radius: int = 2,
) -> pd.DataFrame:
    """导出 dP/dG 极值行及其上下文。

    这是人工审查辅助：只看数值导数 CSV 中极值点附近的行；
    不做 closure，不挑闭合压力，不解释导数曲线形态，不做 smoothing 或 resampling。
    """
    review_path = Path(review_csv)
    if not review_path.exists():
        raise ValueError(f"review does not exist: {review_path}")
    if top_abs_dpdg_per_stage <= 0:
        raise ValueError("top_abs_dpdg_per_stage must be > 0")
    if context_radius < 0:
        raise ValueError("context_radius must be >= 0")

    derivative_root = Path(derivative_dir) if derivative_dir is not None else review_path.parent
    if not derivative_root.exists() or not derivative_root.is_dir():
        raise ValueError(f"derivative directory does not exist: {derivative_root}")

    review = pd.read_csv(review_path)
    selected = review.copy()
    if stages is not None:
        wanted = {int(stage) for stage in stages}
        selected = selected[selected["stage"].astype(int).isin(wanted)]

    rows: list[dict[str, Any]] = []
    for _, row in selected.iterrows():
        rows.extend(
            _context_rows_for_stage(
                row,
                derivative_root=derivative_root,
                top_abs_dpdg_per_stage=int(top_abs_dpdg_per_stage),
                context_radius=int(context_radius),
            )
        )
    return pd.DataFrame(rows, columns=_DERIVATIVE_CONTEXT_COLUMNS)


def write_derivative_context_csv(context: pd.DataFrame, output: str | Path) -> Path:
    """写出极值上下文 CSV。parent directory 必须已经存在。"""
    output_path = Path(output)
    if not output_path.parent.exists():
        raise ValueError(f"output parent directory does not exist: {output_path.parent}")
    context.to_csv(output_path, index=False)
    return output_path


_DERIVATIVE_CONTEXT_COLUMNS = [
    "stage",
    "manual_review_priority",
    "manual_review_reasons",
    "derivative_csv_path",
    "context_status",
    "extreme_rank",
    "center_row_number",
    "center_abs_dP_dG_mpa",
    "center_position_index",
    "center_position_fraction",
    "center_near_boundary",
    "context_offset",
    "is_center",
    "source_position_index",
    "source_row_number",
    "elapsed_seconds",
    "delta",
    "nolte_g_time",
    "pressure_column",
    "pressure_mpa",
    "wellhead_pressure_mpa",
    "estimated_bottomhole_pressure_mpa",
    "dP_dG_mpa",
    "G_dP_dG_mpa",
    "time_text",
    "closure_was_computed",
]


def _context_rows_for_stage(
    row: pd.Series,
    *,
    derivative_root: Path,
    top_abs_dpdg_per_stage: int,
    context_radius: int,
) -> list[dict[str, Any]]:
    stage = _maybe_int(row.get("stage"))
    priority = _text(row.get("manual_review_priority", ""))
    reasons = _text(row.get("manual_review_reasons", ""))
    path = _resolve_derivative_path(row.get("pressure_derivative_output_path", ""), derivative_root)

    if path is None or not path.exists():
        return [_placeholder_context_row(stage, priority, reasons, path, "missing_derivative_csv")]

    derivative = pd.read_csv(path)
    if "dP_dG_mpa" not in derivative.columns:
        return [_placeholder_context_row(stage, priority, reasons, path, "missing_dP_dG_mpa")]

    dP_dG = pd.to_numeric(derivative["dP_dG_mpa"], errors="coerce")
    finite = dP_dG[np.isfinite(dP_dG.to_numpy(dtype=float))]
    if finite.empty:
        return [_placeholder_context_row(stage, priority, reasons, path, "no_finite_dP_dG_mpa")]

    abs_dP_dG = dP_dG.abs()
    center_indices = (
        abs_dP_dG[np.isfinite(abs_dP_dG.to_numpy(dtype=float))]
        .sort_values(ascending=False)
        .head(top_abs_dpdg_per_stage)
        .index.tolist()
    )

    output_rows: list[dict[str, Any]] = []
    csv_row_count = len(derivative)
    for extreme_rank, center_index in enumerate(center_indices, start=1):
        center_abs = float(abs_dP_dG.loc[center_index])
        center_row_number = _source_row_number(derivative, center_index)
        center_fraction = float("nan") if csv_row_count <= 1 else float(center_index / (csv_row_count - 1))
        center_near_boundary = bool(
            center_index < context_radius or center_index > csv_row_count - 1 - context_radius
        )
        start = max(0, center_index - context_radius)
        stop = min(csv_row_count - 1, center_index + context_radius)
        for source_index in range(start, stop + 1):
            output_rows.append(
                _context_data_row(
                    derivative,
                    source_index=source_index,
                    stage=stage,
                    priority=priority,
                    reasons=reasons,
                    path=path,
                    extreme_rank=extreme_rank,
                    center_index=center_index,
                    center_row_number=center_row_number,
                    center_abs=center_abs,
                    center_fraction=center_fraction,
                    center_near_boundary=center_near_boundary,
                )
            )
    return output_rows


def _placeholder_context_row(
    stage: int | float,
    priority: str,
    reasons: str,
    path: Path | None,
    status: str,
) -> dict[str, Any]:
    row = {column: np.nan for column in _DERIVATIVE_CONTEXT_COLUMNS}
    row.update(
        {
            "stage": stage,
            "manual_review_priority": priority,
            "manual_review_reasons": reasons,
            "derivative_csv_path": str(path) if path is not None else "",
            "context_status": status,
            "closure_was_computed": False,
        }
    )
    return row


def _context_data_row(
    derivative: pd.DataFrame,
    *,
    source_index: int,
    stage: int | float,
    priority: str,
    reasons: str,
    path: Path,
    extreme_rank: int,
    center_index: int,
    center_row_number: int | float,
    center_abs: float,
    center_fraction: float,
    center_near_boundary: bool,
) -> dict[str, Any]:
    source = derivative.iloc[source_index]
    return {
        "stage": stage,
        "manual_review_priority": priority,
        "manual_review_reasons": reasons,
        "derivative_csv_path": str(path),
        "context_status": "ok",
        "extreme_rank": int(extreme_rank),
        "center_row_number": center_row_number,
        "center_abs_dP_dG_mpa": center_abs,
        "center_position_index": int(center_index),
        "center_position_fraction": center_fraction,
        "center_near_boundary": center_near_boundary,
        "context_offset": int(source_index - center_index),
        "is_center": bool(source_index == center_index),
        "source_position_index": int(source_index),
        "source_row_number": _source_row_number(derivative, source_index),
        "elapsed_seconds": _number(source.get("elapsed_seconds"), default=np.nan),
        "delta": _number(source.get("delta"), default=np.nan),
        "nolte_g_time": _number(source.get("nolte_g_time"), default=np.nan),
        "pressure_column": _text(source.get("pressure_column", "")),
        "pressure_mpa": _number(source.get("pressure_mpa"), default=np.nan),
        "wellhead_pressure_mpa": _number(source.get("wellhead_pressure_mpa"), default=np.nan),
        "estimated_bottomhole_pressure_mpa": _number(
            source.get("estimated_bottomhole_pressure_mpa"), default=np.nan
        ),
        "dP_dG_mpa": _number(source.get("dP_dG_mpa"), default=np.nan),
        "G_dP_dG_mpa": _number(source.get("G_dP_dG_mpa"), default=np.nan),
        "time_text": _text(source.get("time_text", "")),
        "closure_was_computed": False,
    }


def _source_row_number(derivative: pd.DataFrame, source_index: int) -> int | float:
    if "row_number" not in derivative.columns:
        return int(source_index)
    return _maybe_int(derivative.iloc[source_index].get("row_number"))


def format_top_review_rows(
    review_df: pd.DataFrame,
    *,
    column: str,
    top_n: int,
    label: str,
) -> list[str]:
    """格式化人工审查排序；这是人工分诊辅助，不是物理解释或 closure。"""
    if top_n <= 0:
        return []
    lines = [f"{label}:"]
    if column not in review_df.columns:
        lines.append(f"{label}_no_finite_values=True reason=missing_column column={column}")
        return lines

    ranked = review_df.copy()
    ranked[column] = pd.to_numeric(ranked[column], errors="coerce")
    ranked = ranked[np.isfinite(ranked[column].to_numpy(dtype=float))]
    if ranked.empty:
        lines.append(f"{label}_no_finite_values=True column={column}")
        return lines

    ranked = ranked.sort_values(column, ascending=False).head(int(top_n))
    for rank, (_, row) in enumerate(ranked.iterrows(), start=1):
        lines.append(
            " ".join(
                [
                    f"rank={rank}",
                    f"stage={_format_rank_stage(row.get('stage'))}",
                    f"priority={_text(row.get('manual_review_priority', ''))}",
                    f"reasons={_format_rank_reasons(row.get('manual_review_reasons', ''))}",
                    f"dP_dG_abs_max={_format_rank_float(row.get('dP_dG_abs_max'))}",
                    f"dP_dG_positive_ratio={_format_rank_float(row.get('dP_dG_positive_ratio'))}",
                    "rows_removed="
                    + _format_rank_int(row.get("falloff_window_rows_removed_by_duplicate_policy")),
                    f"csv_rows={_format_rank_int(row.get('derivative_csv_rows'))}",
                ]
            )
        )
    return lines


def _review_row(
    row: pd.Series,
    *,
    derivative_root: Path,
    large_duplicate_removal_threshold: int,
    positive_derivative_ratio_threshold: float,
    large_abs_dpdg_threshold: float | None,
) -> dict[str, Any]:
    output_path = _resolve_derivative_path(row.get("pressure_derivative_output_path", ""), derivative_root)
    output_written = _as_bool(row.get("pressure_derivative_output_written", False))
    derivative_csv_exists = bool(output_written and output_path is not None and output_path.exists())
    derivative_csv_rows = _csv_row_count(output_path) if derivative_csv_exists and output_path is not None else 0

    finite_count = _number(row.get("pressure_derivative_dP_dG_finite_count"), default=np.nan)
    positive_count = _number(row.get("pressure_derivative_dP_dG_positive_count"), default=np.nan)
    dP_dG_positive_ratio = _safe_ratio(positive_count, finite_count)

    dP_dG_min = _number(row.get("pressure_derivative_dP_dG_min"), default=np.nan)
    dP_dG_median = _number(row.get("pressure_derivative_dP_dG_median"), default=np.nan)
    dP_dG_max = _number(row.get("pressure_derivative_dP_dG_max"), default=np.nan)
    dP_dG_abs_max = _abs_max(dP_dG_min, dP_dG_max)

    G_dP_dG_min = _number(row.get("pressure_derivative_G_dP_dG_min"), default=np.nan)
    G_dP_dG_median = _number(row.get("pressure_derivative_G_dP_dG_median"), default=np.nan)
    G_dP_dG_max = _number(row.get("pressure_derivative_G_dP_dG_max"), default=np.nan)
    G_dP_dG_abs_max = _abs_max(G_dP_dG_min, G_dP_dG_max)

    rows_removed = _number(row.get("falloff_window_rows_removed_by_duplicate_policy"), default=0.0)
    duplicate_removal_large = bool(rows_removed >= large_duplicate_removal_threshold)
    positive_derivative_ratio_high = bool(
        np.isfinite(dP_dG_positive_ratio)
        and dP_dG_positive_ratio >= positive_derivative_ratio_threshold
    )
    large_abs_dpdg = bool(
        large_abs_dpdg_threshold is not None
        and np.isfinite(dP_dG_abs_max)
        and dP_dG_abs_max >= large_abs_dpdg_threshold
    )

    derivative_was_computed = _as_bool(row.get("derivative_was_computed", False))
    priority, reasons = _priority_and_reasons(
        derivative_was_computed=derivative_was_computed,
        output_written=output_written,
        derivative_csv_exists=derivative_csv_exists,
        duplicate_removal_large=duplicate_removal_large,
        positive_derivative_ratio_high=positive_derivative_ratio_high,
        rows_removed=rows_removed,
        large_abs_dpdg=large_abs_dpdg,
    )

    return {
        "stage": _maybe_int(row.get("stage")),
        "derivative_readiness_ready": _as_bool(row.get("derivative_readiness_ready", False)),
        "derivative_was_computed": derivative_was_computed,
        "pressure_derivative_output_written": output_written,
        "pressure_derivative_output_path": str(output_path) if output_path is not None else "",
        "derivative_csv_exists": derivative_csv_exists,
        "derivative_csv_rows": int(derivative_csv_rows),
        "derivative_readiness_blockers": _text(row.get("derivative_readiness_blockers", "")),
        "falloff_window_rows_after_duplicate_policy": _maybe_int(
            row.get("falloff_window_rows_after_duplicate_policy")
        ),
        "falloff_window_rows_removed_by_duplicate_policy": _maybe_int(rows_removed),
        "duplicate_removal_large": duplicate_removal_large,
        "dP_dG_positive_count": _maybe_int(row.get("pressure_derivative_dP_dG_positive_count")),
        "dP_dG_negative_count": _maybe_int(row.get("pressure_derivative_dP_dG_negative_count")),
        "dP_dG_zero_count": _maybe_int(row.get("pressure_derivative_dP_dG_zero_count")),
        "dP_dG_finite_count": _maybe_int(row.get("pressure_derivative_dP_dG_finite_count")),
        "dP_dG_positive_ratio": dP_dG_positive_ratio,
        "dP_dG_min": dP_dG_min,
        "dP_dG_median": dP_dG_median,
        "dP_dG_max": dP_dG_max,
        "dP_dG_abs_max": dP_dG_abs_max,
        "G_dP_dG_min": G_dP_dG_min,
        "G_dP_dG_median": G_dP_dG_median,
        "G_dP_dG_max": G_dP_dG_max,
        "G_dP_dG_abs_max": G_dP_dG_abs_max,
        "pressure_step_positive_count": _maybe_int(
            row.get("pressure_derivative_pressure_step_positive_count")
        ),
        "pressure_step_negative_count": _maybe_int(
            row.get("pressure_derivative_pressure_step_negative_count")
        ),
        "pressure_step_zero_count": _maybe_int(row.get("pressure_derivative_pressure_step_zero_count")),
        "positive_derivative_ratio_high": positive_derivative_ratio_high,
        "manual_review_priority": priority,
        "manual_review_reasons": reasons,
        "closure_was_computed": False,
    }


def _resolve_derivative_path(value: Any, derivative_root: Path) -> Path | None:
    text = _text(value).strip()
    if not text or text.lower() == "nan":
        return None
    path = Path(text)
    if path.is_absolute():
        return path
    return derivative_root / path


def _csv_row_count(path: Path) -> int:
    return int(len(pd.read_csv(path)))


def _priority_and_reasons(
    *,
    derivative_was_computed: bool,
    output_written: bool,
    derivative_csv_exists: bool,
    duplicate_removal_large: bool,
    positive_derivative_ratio_high: bool,
    rows_removed: float,
    large_abs_dpdg: bool,
) -> tuple[str, str]:
    reasons: list[str] = []
    high = False
    medium = False

    if not derivative_was_computed:
        reasons.append("not derivative-ready")
        high = True
    if output_written and not derivative_csv_exists:
        reasons.append("derivative CSV missing")
        high = True
    if duplicate_removal_large:
        reasons.append("large duplicate removal")
        high = True
    if positive_derivative_ratio_high:
        reasons.append("high positive dP/dG ratio")
        high = True
    if large_abs_dpdg:
        reasons.append("large absolute dP/dG")
        medium = True
    if derivative_was_computed and rows_removed > 0 and not duplicate_removal_large:
        reasons.append("some duplicate removal")
        medium = True

    if high:
        priority = "high"
    elif medium:
        priority = "medium"
    else:
        priority = "low"
        if not reasons:
            reasons.append("no review flags")
    return priority, "; ".join(reasons)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if pd.isna(value):
        return False
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n", ""}:
        return False
    return bool(value)


def _number(value: Any, *, default: float) -> float:
    if value is None or pd.isna(value):
        return float(default)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    return number


def _maybe_int(value: Any) -> int | float:
    number = _number(value, default=np.nan)
    if not np.isfinite(number):
        return float("nan")
    return int(number)


def _safe_ratio(numerator: float, denominator: float) -> float:
    if not np.isfinite(numerator) or not np.isfinite(denominator) or denominator <= 0.0:
        return float("nan")
    return float(numerator / denominator)


def _abs_max(min_value: float, max_value: float) -> float:
    values = [abs(value) for value in [min_value, max_value] if np.isfinite(value)]
    if not values:
        return float("nan")
    return float(max(values))


def _format_rank_stage(value: Any) -> str:
    number = _number(value, default=np.nan)
    if not np.isfinite(number):
        return "nan"
    return str(int(number))


def _format_rank_int(value: Any) -> str:
    number = _number(value, default=np.nan)
    if not np.isfinite(number):
        return "nan"
    return str(int(number))


def _format_rank_float(value: Any) -> str:
    number = _number(value, default=np.nan)
    if not np.isfinite(number):
        return "nan"
    return f"{float(number):.6f}"


def _format_rank_reasons(value: Any) -> str:
    text = _text(value).strip()
    if not text:
        return "none"
    return text.replace(" ", "_").replace(";_", ";")


def _text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value)
