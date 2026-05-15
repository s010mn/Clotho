"""deadline closure-volume MVP：自动闭合候选、裂缝体积估算与观测相关性对照。

这是组会可汇报版本，不是最终论文级模型。

所有闭合压力结果都是 candidate，不是最终解释：
- closure_is_candidate = True
- closure_is_final_interpretation = False

Barree tangent candidate 是 G·dP/dG 偏离 normal leakoff 直线的候选，
不是唯一确定的闭合压力。

McClure-style compliance candidate 是 dP/dG 局部极小 / compliance change screening，
不是完整 nonlinear compliance inversion。

Phase 4N1 已发现 very early transient / water-hammer plausibility，
所以 closure search 默认从 15 s 后开始。

PKN / volume-balance MVP 是简化体积估算，不是校准模型。

相关性输出只是统计相关，不是因果验证。
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from clotho.g_function import nolte_g_time
from clotho.pressure_derivative import pressure_derivative_against_g_time
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

_REQUIRED_MANIFEST_COLUMNS = {"stage", "max_sustained_rate", "valid_falloff_end_elapsed"}


def _curve_continuous_seconds(curve: pd.DataFrame) -> np.ndarray:
    """从曲线的 seconds_of_day 列计算连续秒数，跨午夜自动加 86400。"""
    if "seconds_of_day" in curve.columns:
        seconds = curve["seconds_of_day"].to_numpy(dtype=float)
    else:
        time_col = "time_text" if "time_text" in curve.columns else "time"
        parts = curve[time_col].astype(str).str.split(":", expand=True).astype(float)
        seconds = (parts[0] * 3600 + parts[1] * 60 + parts[2]).to_numpy(dtype=float)
    continuous = seconds.copy()
    day_offset = 0.0
    for i in range(1, len(seconds)):
        if seconds[i] < seconds[i - 1]:
            day_offset += 86400.0
        continuous[i] = seconds[i] + day_offset
    return continuous


def pick_fracture_initiation_candidate(
    curve: pd.DataFrame,
    shut_in_index: int,
    *,
    pressure_column: str,
    minimum_stress_prior_mpa: float | None = None,
    min_rate: float = 10.0,
    sustained_points: int = 3,
) -> dict[str, Any]:
    """自动识别裂缝起裂候选点，并用它修正 tp。

    在停泵前搜索第一个满足条件的点：
    - 如果有 sigma_min：rate >= min_rate 且 pressure >= sigma_min，且之后
      sustained_points 个点的 rate 仍 >= min_rate；
    - 如果没有 sigma_min 或找不到：fallback 到第一个 rate >= min_rate 的点。

    corrected_tp = 停泵时刻 - 起裂时刻（秒）。
    """
    rates = curve["rate"].to_numpy(dtype=float)
    pressures = curve[pressure_column].to_numpy(dtype=float)
    continuous = _curve_continuous_seconds(curve)

    result: dict[str, Any] = {
        "fracture_initiation_status": "failed",
        "fracture_initiation_rule": "",
        "fracture_initiation_index": np.nan,
        "fracture_initiation_time_text": "",
        "fracture_initiation_pressure_mpa": np.nan,
        "tp_corrected_seconds": np.nan,
    }

    found_index: int | None = None
    rule = ""

    if minimum_stress_prior_mpa is not None and np.isfinite(minimum_stress_prior_mpa):
        sigma = float(minimum_stress_prior_mpa)
        for i in range(shut_in_index):
            if rates[i] >= min_rate and pressures[i] >= sigma:
                sustained = True
                for j in range(1, sustained_points + 1):
                    if i + j >= shut_in_index or rates[i + j] < min_rate:
                        sustained = False
                        break
                if sustained:
                    found_index = i
                    rule = "sigma_min_crossing"
                    break

    if found_index is None:
        for i in range(shut_in_index):
            if rates[i] >= min_rate:
                found_index = i
                rule = "first_rate_ge_min_rate"
                break

    if found_index is None:
        return result

    tp_corrected = continuous[shut_in_index] - continuous[found_index]
    if tp_corrected <= 0:
        return result

    time_col = "time_text" if "time_text" in curve.columns else "time"
    time_texts = curve[time_col].astype(str).to_numpy()

    result.update({
        "fracture_initiation_status": "ok",
        "fracture_initiation_rule": rule,
        "fracture_initiation_index": int(found_index),
        "fracture_initiation_time_text": str(time_texts[found_index]),
        "fracture_initiation_pressure_mpa": float(pressures[found_index]),
        "tp_corrected_seconds": float(tp_corrected),
    })
    return result


def pick_barree_tangent_closure_candidate(
    g_time: np.ndarray,
    dP_dG: np.ndarray,
    elapsed_seconds: np.ndarray,
    pressure_mpa: np.ndarray,
    *,
    closure_min_elapsed_seconds: float = 15.0,
    fit_fraction: float = 0.30,
    residual_sigma_factor: float = 2.0,
) -> dict[str, Any]:
    """在 G·dP/dG 上拟合 normal leakoff 直线，寻找偏离点。

    Barree tangent closure candidate 是 G·dP/dG 偏离 normal leakoff 直线的候选。
    偏离指的是 G·dP/dG 变得比正常泄失直线更正（向上偏离），
    说明裂缝开始闭合、刚度增大。

    简化规则：
    - G 必须严格递增；
    - 只在 elapsed >= closure_min_elapsed_seconds 后搜索；
    - 用前 fit_fraction 比例的有效点拟合正常泄失直线；
    - 连续两个点的残差超过阈值时取第一个点为候选；
    - 不 smoothing，不 resampling。
    """
    failed: dict[str, Any] = {
        "barree_status": "not_found",
        "barree_closure_index": np.nan,
        "barree_closure_elapsed_seconds": np.nan,
        "barree_closure_g_time": np.nan,
        "barree_closure_pressure_mpa": np.nan,
        "barree_tangent_slope": np.nan,
        "barree_residual_at_closure": np.nan,
        "barree_quality_flag": "not_found",
    }

    mask = elapsed_seconds >= closure_min_elapsed_seconds
    if mask.sum() < 5:
        return failed

    valid_idx = np.where(mask)[0]
    G_dP_dG = g_time * dP_dG

    n_fit = max(3, int(len(valid_idx) * fit_fraction))
    fit_idx = valid_idx[:n_fit]

    G_fit = g_time[fit_idx]
    GdPdG_fit = G_dP_dG[fit_idx]

    if len(np.unique(G_fit)) < 2:
        return failed

    coeffs = np.polyfit(G_fit, GdPdG_fit, 1)
    slope, intercept = float(coeffs[0]), float(coeffs[1])

    predicted = slope * g_time[valid_idx] + intercept
    actual = G_dP_dG[valid_idx]
    residuals = actual - predicted

    fit_residuals = residuals[:n_fit]
    fit_std = float(np.std(fit_residuals))
    if fit_std < 1e-12:
        fit_std = abs(slope) * 0.01 if abs(slope) > 0 else 1e-6
    threshold = residual_sigma_factor * fit_std

    for i in range(n_fit, len(valid_idx) - 1):
        if residuals[i] > threshold and residuals[i + 1] > threshold:
            ci = valid_idx[i]
            return {
                "barree_status": "ok",
                "barree_closure_index": int(ci),
                "barree_closure_elapsed_seconds": float(elapsed_seconds[ci]),
                "barree_closure_g_time": float(g_time[ci]),
                "barree_closure_pressure_mpa": float(pressure_mpa[ci]),
                "barree_tangent_slope": slope,
                "barree_residual_at_closure": float(residuals[i]),
                "barree_quality_flag": "ok",
            }

    return failed


def pick_mcclure_compliance_closure_candidate(
    g_time: np.ndarray,
    dP_dG: np.ndarray,
    elapsed_seconds: np.ndarray,
    pressure_mpa: np.ndarray,
    *,
    closure_min_elapsed_seconds: float = 15.0,
    boundary_fraction: float = 0.05,
) -> dict[str, Any]:
    """McClure-style compliance change screening：寻找 dP/dG 局部极小。

    这不是完整 McClure nonlinear fracture-compliance inversion。
    只在 dP/dG 序列中寻找局部极小（最负值），作为 compliance change 候选点。

    简化规则：
    - 只在 elapsed >= closure_min_elapsed_seconds 后搜索；
    - 排除首尾 boundary_fraction 范围；
    - 无局部极小则 status=not_found。
    """
    failed: dict[str, Any] = {
        "mcclure_status": "not_found",
        "mcclure_closure_index": np.nan,
        "mcclure_closure_elapsed_seconds": np.nan,
        "mcclure_closure_g_time": np.nan,
        "mcclure_closure_pressure_mpa": np.nan,
        "mcclure_quality_flag": "not_found",
    }

    mask = elapsed_seconds >= closure_min_elapsed_seconds
    if mask.sum() < 5:
        return failed

    valid_idx = np.where(mask)[0]
    n_valid = len(valid_idx)

    boundary_n = max(1, int(n_valid * boundary_fraction))
    interior_idx = valid_idx[boundary_n: n_valid - boundary_n]
    if len(interior_idx) < 3:
        return failed

    dP_dG_interior = dP_dG[interior_idx]
    argmin_local = int(np.argmin(dP_dG_interior))
    min_idx = interior_idx[argmin_local]

    quality = "ok"
    pos_in_valid = int(np.searchsorted(valid_idx, min_idx))
    if pos_in_valid < boundary_n * 2 or pos_in_valid > n_valid - boundary_n * 2:
        quality = "boundary_low_confidence"

    return {
        "mcclure_status": "ok",
        "mcclure_closure_index": int(min_idx),
        "mcclure_closure_elapsed_seconds": float(elapsed_seconds[min_idx]),
        "mcclure_closure_g_time": float(g_time[min_idx]),
        "mcclure_closure_pressure_mpa": float(pressure_mpa[min_idx]),
        "mcclure_quality_flag": quality,
    }


def select_closure_candidate(
    barree: dict[str, Any],
    mcclure: dict[str, Any],
    preference: str = "barree-then-mcclure",
) -> dict[str, Any]:
    """根据偏好从 Barree 和 McClure 候选中选择闭合候选。

    默认 barree-then-mcclure：Barree ok 就用 Barree，否则用 McClure。
    所有输出都标记为 candidate，不是最终解释。
    """
    not_found: dict[str, Any] = {
        "selected_closure_method": "none",
        "selected_closure_elapsed_seconds": np.nan,
        "selected_closure_pressure_mpa": np.nan,
        "selected_closure_g_time": np.nan,
        "selected_closure_quality_flag": "not_found",
        "selected_closure_status": "not_found",
        "closure_is_candidate": True,
        "closure_is_final_interpretation": False,
    }

    barree_ok = barree.get("barree_status") == "ok"
    mcclure_ok = mcclure.get("mcclure_status") == "ok"

    def _from_barree() -> dict[str, Any]:
        return {
            "selected_closure_method": "barree",
            "selected_closure_elapsed_seconds": barree["barree_closure_elapsed_seconds"],
            "selected_closure_pressure_mpa": barree["barree_closure_pressure_mpa"],
            "selected_closure_g_time": barree["barree_closure_g_time"],
            "selected_closure_quality_flag": barree["barree_quality_flag"],
            "selected_closure_status": "ok",
            "closure_is_candidate": True,
            "closure_is_final_interpretation": False,
        }

    def _from_mcclure() -> dict[str, Any]:
        return {
            "selected_closure_method": "mcclure",
            "selected_closure_elapsed_seconds": mcclure["mcclure_closure_elapsed_seconds"],
            "selected_closure_pressure_mpa": mcclure["mcclure_closure_pressure_mpa"],
            "selected_closure_g_time": mcclure["mcclure_closure_g_time"],
            "selected_closure_quality_flag": mcclure["mcclure_quality_flag"],
            "selected_closure_status": "ok",
            "closure_is_candidate": True,
            "closure_is_final_interpretation": False,
        }

    if preference == "barree-then-mcclure":
        if barree_ok:
            return _from_barree()
        if mcclure_ok:
            return _from_mcclure()
        return not_found
    if preference == "mcclure-then-barree":
        if mcclure_ok:
            return _from_mcclure()
        if barree_ok:
            return _from_barree()
        return not_found
    if preference == "barree":
        return _from_barree() if barree_ok else not_found
    if preference == "mcclure":
        return _from_mcclure() if mcclure_ok else not_found
    return not_found


def effective_volume_correction(
    raw_injected_volume_m3: float,
    pressure_at_shut_in_mpa: float,
    closure_pressure_mpa: float | None,
    *,
    perforation_friction_mpa: float = 0.0,
    wellbore_storage_coeff_m3_per_mpa: float = 0.0,
) -> dict[str, Any]:
    """有效进缝液量修正。

    raw_injected_volume_m3：从起裂候选到停泵的累计注入体积。
    perforation_friction_mpa：作为压力修正，不直接扣体积。
    wellbore_storage_coeff_m3_per_mpa：井筒存储系数，V_storage = C_wb * max(P_shut - P_closure, 0)。
    """
    pressure_for_net = pressure_at_shut_in_mpa - perforation_friction_mpa

    if closure_pressure_mpa is not None and np.isfinite(closure_pressure_mpa):
        dp = max(pressure_at_shut_in_mpa - closure_pressure_mpa, 0.0)
        storage_volume = wellbore_storage_coeff_m3_per_mpa * dp
        warning = ""
    else:
        storage_volume = 0.0
        warning = "closure_pressure_unavailable_storage_set_zero"

    effective = max(raw_injected_volume_m3 - storage_volume, 0.0)

    return {
        "raw_injected_volume_m3": float(raw_injected_volume_m3),
        "perforation_friction_mpa": float(perforation_friction_mpa),
        "pressure_at_shut_in_mpa": float(pressure_at_shut_in_mpa),
        "pressure_for_net_mpa": float(pressure_for_net),
        "wellbore_storage_coeff_m3_per_mpa": float(wellbore_storage_coeff_m3_per_mpa),
        "wellbore_storage_volume_m3": float(storage_volume),
        "effective_injected_volume_m3": float(effective),
        "volume_correction_warning": warning,
    }


def pkn_volume_balance_estimate(
    effective_injected_volume_m3: float,
    closure_pressure_mpa: float | None,
    *,
    minimum_stress_prior_mpa: float | None = None,
    half_height_m: float | None = None,
    youngs_modulus_gpa: float | None = None,
    poissons_ratio: float | None = None,
    barree_tangent_slope: float | None = None,
    tp_seconds: float | None = None,
    g_time_at_closure: float | None = None,
    perforation_friction_mpa: float = 0.0,
) -> dict[str, Any]:
    """PKN / volume-balance MVP 裂缝体积估算。

    这是 MVP，不是最终校准模型。
    使用简化 Sneddon 平面应变裂缝宽度和 Carter 泄失近似。
    Carter、stress-shadow、cluster allocation 的严谨化见 TODO.md。

    物理结构：
    - E' = E_GPa * 1000 / (1 - nu^2)
    - net_pressure = max(P_closure - perforation_friction - sigma_min, 0)
    - PKN 平均宽度 w_avg = net_p * h_f / (2 * E')
    - 泄失系数 C_L 从 Barree tangent slope 粗估
    - 半缝长 x_f 从体积平衡求解
    - 裂缝体积 V_f = w_avg * h_f * 2 * x_f
    """
    failed: dict[str, Any] = {
        "pkn_volume_status": "failed",
        "pkn_half_length_mean_m": np.nan,
        "pkn_half_length_std_m": np.nan,
        "pkn_fracture_volume_m3": np.nan,
        "pkn_leakoff_coefficient": np.nan,
        "pkn_segment_start": np.nan,
        "pkn_segment_end": np.nan,
        "pkn_warning": "",
    }

    missing: list[str] = []
    if half_height_m is None or not np.isfinite(half_height_m) or half_height_m <= 0:
        missing.append("half_height_m")
    if youngs_modulus_gpa is None or not np.isfinite(youngs_modulus_gpa) or youngs_modulus_gpa <= 0:
        missing.append("youngs_modulus_gpa")
    if poissons_ratio is None or not np.isfinite(poissons_ratio):
        missing.append("poissons_ratio")
    if closure_pressure_mpa is None or not np.isfinite(closure_pressure_mpa):
        missing.append("closure_pressure_mpa")
    if not np.isfinite(effective_injected_volume_m3) or effective_injected_volume_m3 <= 0:
        missing.append("effective_injected_volume_m3")

    if missing:
        failed["pkn_warning"] = f"missing_or_invalid: {', '.join(missing)}"
        return failed

    assert half_height_m is not None
    assert youngs_modulus_gpa is not None
    assert poissons_ratio is not None
    assert closure_pressure_mpa is not None

    E_prime_mpa = youngs_modulus_gpa * 1000.0 / (1.0 - poissons_ratio ** 2)
    h_f = 2.0 * half_height_m

    if minimum_stress_prior_mpa is not None and np.isfinite(minimum_stress_prior_mpa):
        net_p = max(closure_pressure_mpa - perforation_friction_mpa - minimum_stress_prior_mpa, 0.0)
    else:
        net_p = max(closure_pressure_mpa - perforation_friction_mpa, 0.0)

    if net_p <= 0 or E_prime_mpa <= 0:
        failed["pkn_warning"] = "net_pressure_or_modulus_nonpositive"
        return failed

    w_avg = net_p * h_f / (2.0 * E_prime_mpa)

    C_L = 0.0
    leakoff_term = 0.0
    if (
        barree_tangent_slope is not None
        and np.isfinite(barree_tangent_slope)
        and tp_seconds is not None
        and np.isfinite(tp_seconds)
        and tp_seconds > 0
        and g_time_at_closure is not None
        and np.isfinite(g_time_at_closure)
        and g_time_at_closure > 0
    ):
        C_L = abs(barree_tangent_slope) * h_f / (4.0 * E_prime_mpa * math.sqrt(tp_seconds))
        leakoff_term = 2.0 * C_L * math.sqrt(tp_seconds) * g_time_at_closure

    denom = 2.0 * h_f * (w_avg + leakoff_term)
    if denom <= 0:
        failed["pkn_warning"] = "volume_balance_denominator_nonpositive"
        return failed

    x_f = effective_injected_volume_m3 / denom
    V_f = w_avg * h_f * 2.0 * x_f

    segment_start = np.nan
    segment_end = np.nan

    return {
        "pkn_volume_status": "ok",
        "pkn_half_length_mean_m": float(x_f),
        "pkn_half_length_std_m": np.nan,
        "pkn_fracture_volume_m3": float(V_f),
        "pkn_leakoff_coefficient": float(C_L),
        "pkn_segment_start": segment_start,
        "pkn_segment_end": segment_end,
        "pkn_warning": "",
    }


def build_observation_correlation_table(
    summary: pd.DataFrame,
    observations: pd.DataFrame,
) -> pd.DataFrame:
    """构建 per-stage 闭合/体积指标与观测数据的相关性表。

    这只是统计相关性，不是因果验证。
    finite n < 3 时 pearson_r 和 spearman_r 返回 NaN。
    """
    merged = summary.merge(observations, on="stage", how="inner", suffixes=("", "_obs"))

    metrics = [
        "pkn_fracture_volume_m3",
        "effective_injected_volume_m3",
        "raw_injected_volume_m3",
        "selected_closure_pressure_mpa",
        "tp_corrected_seconds",
        "tp_correction_ratio",
    ]
    targets = [c for c in observations.columns if c != "stage"]

    rows: list[dict[str, Any]] = []
    for metric in metrics:
        if metric not in merged.columns:
            for target in targets:
                rows.append({
                    "metric": metric,
                    "target": target,
                    "n": 0,
                    "pearson_r": np.nan,
                    "spearman_r": np.nan,
                })
            continue

        m_vals = pd.to_numeric(merged[metric], errors="coerce")
        for target in targets:
            t_col = target if target in merged.columns else f"{target}_obs"
            if t_col not in merged.columns:
                rows.append({
                    "metric": metric,
                    "target": target,
                    "n": 0,
                    "pearson_r": np.nan,
                    "spearman_r": np.nan,
                })
                continue

            t_vals = pd.to_numeric(merged[t_col], errors="coerce")
            pair = pd.DataFrame({"m": m_vals, "t": t_vals}).dropna()
            n = len(pair)
            if n < 3:
                rows.append({
                    "metric": metric,
                    "target": target,
                    "n": n,
                    "pearson_r": np.nan,
                    "spearman_r": np.nan,
                })
                continue

            pearson = float(pair["m"].corr(pair["t"], method="pearson"))
            spearman = float(pair["m"].rank().corr(pair["t"].rank()))
            rows.append({
                "metric": metric,
                "target": target,
                "n": n,
                "pearson_r": pearson,
                "spearman_r": spearman,
            })

    return pd.DataFrame(rows)


def _find_stage(stages: list[StageInfo], stage_number: int, well: str | None) -> StageInfo:
    matches = [s for s in stages if s.stage == stage_number and (well is None or s.well == well)]
    if not matches:
        raise ValueError(f"找不到 stage={stage_number}")
    if len(matches) > 1:
        raise ValueError(f"stage={stage_number} 匹配多行")
    return matches[0]


def _get_pressure_column_and_values(
    window: pd.DataFrame,
    stage: StageInfo,
    pressure_source: str,
) -> tuple[pd.DataFrame, str, np.ndarray]:
    if pressure_source == "estimated-bottomhole" and stage.liquid_column_pressure_mpa is not None:
        pw = add_estimated_bottomhole_pressure(window, stage)
        col = "estimated_bottomhole_pressure_mpa"
    else:
        pw = window.copy()
        col = "wellhead_pressure_mpa"
    return pw, col, pw[col].to_numpy(dtype=float)


def _compute_raw_injected_volume(
    curve: pd.DataFrame,
    initiation_index: int | None,
    shut_in_index: int,
    volume_column: str,
) -> float:
    """从起裂到停泵的累计注入体积。"""
    volumes = curve[volume_column].to_numpy(dtype=float)
    start = 0 if initiation_index is None else initiation_index
    v_start = volumes[start] if np.isfinite(volumes[start]) else 0.0
    v_end = volumes[shut_in_index] if np.isfinite(volumes[shut_in_index]) else 0.0
    return max(v_end - v_start, 0.0)


def _compute_early_transient_risk(
    dP_dG: np.ndarray,
    elapsed_seconds: np.ndarray,
    closure_min_elapsed_seconds: float,
) -> bool:
    if len(dP_dG) == 0:
        return False
    abs_dpdg = np.abs(dP_dG)
    finite_mask = np.isfinite(abs_dpdg)
    if not finite_mask.any():
        return False
    max_idx = int(np.argmax(np.where(finite_mask, abs_dpdg, -np.inf)))
    return bool(elapsed_seconds[max_idx] < closure_min_elapsed_seconds)


def _process_stage(
    *,
    stage_info: StageInfo,
    well_root: Path,
    max_sustained_rate: float,
    valid_falloff_end_elapsed: float,
    volume_column: str,
    rate_time_unit: str,
    min_rate: float,
    g_time_m: float,
    elapsed_duplicate_policy: str,
    closure_min_elapsed_seconds: float,
    pressure_source: str,
    perforation_friction_mpa: float,
    wellbore_storage_coeff_m3_per_mpa: float,
    method_preference: str,
) -> dict[str, Any]:
    """处理单个 stage 的闭合候选分析。"""
    row: dict[str, Any] = {"stage": stage_info.stage}

    curve_file = well_root / stage_info.data_file
    curve = read_stage_curve(curve_file)
    shut_in_index = find_shut_in_index(curve, stage_info.shut_in_time)

    tp_legacy = volume_over_max_rate_duration_seconds(
        curve,
        shut_in_index,
        max_sustained_rate=max_sustained_rate,
        rate_time_unit=rate_time_unit,
        volume_column=volume_column,
    )
    row["tp_legacy_volume_over_rate_seconds"] = float(tp_legacy)

    pressure_col_pre = "wellhead_pressure_mpa"
    if pressure_source == "estimated-bottomhole" and stage_info.liquid_column_pressure_mpa is not None:
        curve_with_bhp = add_estimated_bottomhole_pressure(curve, stage_info)
        pressure_col_pre = "estimated_bottomhole_pressure_mpa"
    else:
        curve_with_bhp = curve

    initiation = pick_fracture_initiation_candidate(
        curve_with_bhp,
        shut_in_index,
        pressure_column=pressure_col_pre,
        minimum_stress_prior_mpa=stage_info.minimum_stress_prior_mpa,
        min_rate=min_rate,
    )
    row.update(initiation)

    init_ok = initiation["fracture_initiation_status"] == "ok"
    tp_corrected = initiation["tp_corrected_seconds"] if init_ok else tp_legacy
    tp_for_g = tp_corrected if init_ok and np.isfinite(tp_corrected) and tp_corrected > 0 else tp_legacy
    row["tp_correction_ratio"] = float(tp_corrected / tp_legacy) if tp_legacy > 0 else np.nan

    init_idx = int(initiation["fracture_initiation_index"]) if init_ok else None
    raw_vol = _compute_raw_injected_volume(curve, init_idx, shut_in_index, volume_column)

    falloff = falloff_window_after_shut_in(
        curve, shut_in_index, end_elapsed_seconds=valid_falloff_end_elapsed,
    )
    readiness_window = apply_elapsed_duplicate_policy(falloff, policy=elapsed_duplicate_policy)

    elapsed = readiness_window["elapsed_seconds"].to_numpy(dtype=float)

    if len(elapsed) < 3 or tp_for_g <= 0:
        row.update(_empty_closure_fields())
        vol_result = effective_volume_correction(raw_vol, np.nan, None,
            perforation_friction_mpa=perforation_friction_mpa,
            wellbore_storage_coeff_m3_per_mpa=wellbore_storage_coeff_m3_per_mpa)
        row.update(vol_result)
        row.update(_empty_pkn_fields())
        row["early_transient_risk"] = False
        row["closure_was_computed"] = False
        return row

    delta = elapsed / tp_for_g
    g_time_arr = np.asarray(nolte_g_time(delta, g_time_m), dtype=float)

    if not np.all(np.diff(g_time_arr) > 0):
        row.update(_empty_closure_fields())
        vol_result = effective_volume_correction(raw_vol, np.nan, None,
            perforation_friction_mpa=perforation_friction_mpa,
            wellbore_storage_coeff_m3_per_mpa=wellbore_storage_coeff_m3_per_mpa)
        row.update(vol_result)
        row.update(_empty_pkn_fields())
        row["early_transient_risk"] = False
        row["closure_was_computed"] = False
        return row

    pw, p_col, p_vals = _get_pressure_column_and_values(readiness_window, stage_info, pressure_source)

    if not np.all(np.isfinite(p_vals)):
        row.update(_empty_closure_fields())
        vol_result = effective_volume_correction(raw_vol, np.nan, None,
            perforation_friction_mpa=perforation_friction_mpa,
            wellbore_storage_coeff_m3_per_mpa=wellbore_storage_coeff_m3_per_mpa)
        row.update(vol_result)
        row.update(_empty_pkn_fields())
        row["early_transient_risk"] = False
        row["closure_was_computed"] = False
        return row

    dP_dG, G_dP_dG = pressure_derivative_against_g_time(g_time_arr, p_vals)

    row["early_transient_risk"] = _compute_early_transient_risk(
        dP_dG, elapsed, closure_min_elapsed_seconds,
    )
    row["closure_was_computed"] = True

    barree = pick_barree_tangent_closure_candidate(
        g_time_arr, dP_dG, elapsed, p_vals,
        closure_min_elapsed_seconds=closure_min_elapsed_seconds,
    )
    row.update(barree)

    mcclure = pick_mcclure_compliance_closure_candidate(
        g_time_arr, dP_dG, elapsed, p_vals,
        closure_min_elapsed_seconds=closure_min_elapsed_seconds,
    )
    row.update(mcclure)

    selected = select_closure_candidate(barree, mcclure, preference=method_preference)
    row.update(selected)

    p_shut_in = float(p_vals[0]) if len(p_vals) > 0 else np.nan
    closure_p = selected.get("selected_closure_pressure_mpa")
    closure_p_val = float(closure_p) if closure_p is not None and np.isfinite(closure_p) else None

    vol_result = effective_volume_correction(
        raw_vol,
        p_shut_in,
        closure_p_val,
        perforation_friction_mpa=perforation_friction_mpa,
        wellbore_storage_coeff_m3_per_mpa=wellbore_storage_coeff_m3_per_mpa,
    )
    row.update(vol_result)

    closure_g = selected.get("selected_closure_g_time")
    closure_g_val = float(closure_g) if closure_g is not None and np.isfinite(closure_g) else None

    pkn = pkn_volume_balance_estimate(
        vol_result["effective_injected_volume_m3"],
        closure_p_val,
        minimum_stress_prior_mpa=stage_info.minimum_stress_prior_mpa,
        half_height_m=stage_info.fracture_half_height_m,
        youngs_modulus_gpa=stage_info.youngs_modulus_gpa,
        poissons_ratio=stage_info.poissons_ratio,
        barree_tangent_slope=barree.get("barree_tangent_slope"),
        tp_seconds=tp_for_g,
        g_time_at_closure=closure_g_val,
        perforation_friction_mpa=perforation_friction_mpa,
    )
    row.update(pkn)

    return row


def _empty_closure_fields() -> dict[str, Any]:
    return {
        "barree_status": "not_computed",
        "barree_closure_index": np.nan,
        "barree_closure_elapsed_seconds": np.nan,
        "barree_closure_g_time": np.nan,
        "barree_closure_pressure_mpa": np.nan,
        "barree_tangent_slope": np.nan,
        "barree_residual_at_closure": np.nan,
        "barree_quality_flag": "not_computed",
        "mcclure_status": "not_computed",
        "mcclure_closure_index": np.nan,
        "mcclure_closure_elapsed_seconds": np.nan,
        "mcclure_closure_g_time": np.nan,
        "mcclure_closure_pressure_mpa": np.nan,
        "mcclure_quality_flag": "not_computed",
        "selected_closure_method": "none",
        "selected_closure_elapsed_seconds": np.nan,
        "selected_closure_pressure_mpa": np.nan,
        "selected_closure_g_time": np.nan,
        "selected_closure_quality_flag": "not_computed",
        "selected_closure_status": "not_computed",
        "closure_is_candidate": True,
        "closure_is_final_interpretation": False,
    }


def _empty_pkn_fields() -> dict[str, Any]:
    return {
        "pkn_volume_status": "not_computed",
        "pkn_half_length_mean_m": np.nan,
        "pkn_half_length_std_m": np.nan,
        "pkn_fracture_volume_m3": np.nan,
        "pkn_leakoff_coefficient": np.nan,
        "pkn_segment_start": np.nan,
        "pkn_segment_end": np.nan,
        "pkn_warning": "derivatives_not_available",
    }


def run_closure_batch(
    *,
    stage_params_path: str | Path,
    well_root: str | Path,
    manifest_path: str | Path,
    observations_path: str | Path | None = None,
    volume_column: str = "total_volume",
    rate_time_unit: str = "minute",
    min_rate: float = 10.0,
    g_time_m: float = 0.8,
    elapsed_duplicate_policy: str = "keep-last",
    closure_min_elapsed_seconds: float = 15.0,
    pressure_source: str = "estimated-bottomhole",
    perforation_friction_mpa: float = 0.0,
    wellbore_storage_coeff_m3_per_mpa: float = 0.0,
    method_preference: str = "barree-then-mcclure",
    well: str | None = None,
) -> dict[str, Any]:
    """运行 closure-batch 批量闭合候选分析。

    读取 stage_params、stage 曲线、manifest 和可选 observations，
    输出 per-stage closure-volume summary 和 correlation summary。

    所有闭合结果都是 candidate，不是最终解释。
    """
    stages_info = read_stage_params(stage_params_path)
    manifest = pd.read_csv(manifest_path, dtype=str, keep_default_na=False)

    missing_cols = sorted(_REQUIRED_MANIFEST_COLUMNS - set(manifest.columns))
    if missing_cols:
        raise ValueError(f"manifest 缺少必填列: {', '.join(missing_cols)}")

    observations: pd.DataFrame | None = None
    if observations_path is not None:
        observations = pd.read_csv(observations_path)
        observations["stage"] = observations["stage"].astype(int)

    stage_rows: list[dict[str, Any]] = []
    for _, mrow in manifest.iterrows():
        stage_num = int(mrow["stage"])
        msr = float(mrow["max_sustained_rate"])
        vfee = float(mrow["valid_falloff_end_elapsed"])

        stage_info = _find_stage(stages_info, stage_num, well)

        result = _process_stage(
            stage_info=stage_info,
            well_root=Path(well_root),
            max_sustained_rate=msr,
            valid_falloff_end_elapsed=vfee,
            volume_column=volume_column,
            rate_time_unit=rate_time_unit,
            min_rate=min_rate,
            g_time_m=g_time_m,
            elapsed_duplicate_policy=elapsed_duplicate_policy,
            closure_min_elapsed_seconds=closure_min_elapsed_seconds,
            pressure_source=pressure_source,
            perforation_friction_mpa=perforation_friction_mpa,
            wellbore_storage_coeff_m3_per_mpa=wellbore_storage_coeff_m3_per_mpa,
            method_preference=method_preference,
        )

        if observations is not None:
            obs_match = observations[observations["stage"] == stage_num]
            if not obs_match.empty:
                for col in observations.columns:
                    if col != "stage":
                        result[col] = float(obs_match.iloc[0][col])
            else:
                for col in observations.columns:
                    if col != "stage":
                        result[col] = np.nan

        result["missing_estimate_reason"] = ""
        stage_rows.append(result)

    manifest_stages = {int(mrow["stage"]) for _, mrow in manifest.iterrows()}

    if observations is not None:
        for _, orow in observations.iterrows():
            obs_stage = int(orow["stage"])
            if obs_stage in manifest_stages:
                continue
            placeholder: dict[str, Any] = {
                "stage": obs_stage,
                "missing_estimate_reason": "no_valid_falloff_manifest_row",
                "fracture_initiation_status": "not_computed",
                "tp_corrected_seconds": np.nan,
                "tp_legacy_volume_over_rate_seconds": np.nan,
                "tp_correction_ratio": np.nan,
                "closure_was_computed": False,
                "early_transient_risk": False,
            }
            placeholder.update(_empty_closure_fields())
            placeholder.update(_empty_pkn_fields())
            placeholder.update({
                "raw_injected_volume_m3": np.nan,
                "effective_injected_volume_m3": np.nan,
                "perforation_friction_mpa": np.nan,
                "pressure_at_shut_in_mpa": np.nan,
                "pressure_for_net_mpa": np.nan,
                "wellbore_storage_coeff_m3_per_mpa": np.nan,
                "wellbore_storage_volume_m3": np.nan,
                "volume_correction_warning": "no_valid_falloff_manifest_row",
            })
            for col in observations.columns:
                if col != "stage":
                    placeholder[col] = float(orow[col])
            stage_rows.append(placeholder)

    summary = pd.DataFrame(stage_rows)
    summary = summary.sort_values("stage", ignore_index=True)

    correlation: pd.DataFrame | None = None
    if observations is not None and len(summary) > 0:
        correlation = build_observation_correlation_table(summary, observations)

    return {
        "summary": summary,
        "correlation": correlation,
        "stage_count": len(summary),
    }


def write_closure_batch_outputs(
    result: dict[str, Any],
    *,
    output_path: str | Path,
    correlation_output_path: str | Path | None = None,
) -> dict[str, Path]:
    """写出 closure-batch CSV 输出。parent directory 必须已存在。"""
    out = Path(output_path)
    if not out.parent.exists():
        raise ValueError(f"output parent directory does not exist: {out.parent}")

    summary: pd.DataFrame = result["summary"]
    summary.to_csv(out, index=False)
    paths: dict[str, Path] = {"output": out}

    if correlation_output_path is not None:
        corr_out = Path(correlation_output_path)
        if not corr_out.parent.exists():
            raise ValueError(f"correlation output parent directory does not exist: {corr_out.parent}")
        correlation: pd.DataFrame | None = result.get("correlation")
        if correlation is not None:
            correlation.to_csv(corr_out, index=False)
            paths["correlation_output"] = corr_out

    return paths
