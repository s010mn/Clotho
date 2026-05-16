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
from typing import Any, Sequence

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
G_FUNCTION_CLOSURE_EFFICIENCY_FORMULA = "eta_G = G_c / (G_c + 2)"
G_FUNCTION_CLOSURE_EFFICIENCY_SOURCE_NOTE = (
    "depends_on_G_function_convention_and_selected_closure_pick;"
    "calibration_cross_check_not_unique_truth"
)


def compute_g_function_closure_efficiency(selected_closure_g_time: float | None) -> dict[str, Any]:
    """用 selected closure 的 G-time 计算 G-function closure-derived efficiency。

    η_G = G_c / (G_c + 2)。这里的 G_c 是 selected_closure_g_time。
    这个效率用于 calibration / cross-check，不是唯一真值。
    """
    result: dict[str, Any] = {
        "g_function_closure_efficiency": np.nan,
        "g_function_closure_efficiency_formula": G_FUNCTION_CLOSURE_EFFICIENCY_FORMULA,
        "g_function_closure_efficiency_status": "invalid_closure_g_time",
        "g_function_closure_efficiency_source_note": G_FUNCTION_CLOSURE_EFFICIENCY_SOURCE_NOTE,
    }
    if selected_closure_g_time is None:
        return result
    try:
        g_c = float(selected_closure_g_time)
    except (TypeError, ValueError):
        return result
    if not np.isfinite(g_c) or g_c <= 0:
        return result
    result["g_function_closure_efficiency"] = float(g_c / (g_c + 2.0))
    result["g_function_closure_efficiency_status"] = "ok"
    return result


def g_time_for_fluid_efficiency(eta: float) -> float:
    """由 diagnostic fluid efficiency 反推目标 Gc。

    eta = Gc / (Gc + 2) 反解为 Gc = 2*eta/(1-eta)。
    该函数只用于 sensitivity prior，不表示 closure truth。
    """
    eta_value = float(eta)
    if not np.isfinite(eta_value) or eta_value <= 0.0 or eta_value >= 1.0:
        raise ValueError("eta must be finite and in (0, 1)")
    return float(2.0 * eta_value / (1.0 - eta_value))


def reconcile_fluid_efficiencies(
    pkn_shutin_fluid_efficiency: float | None,
    g_function_closure_efficiency: float | None,
) -> dict[str, Any]:
    """对照 PKN shut-in efficiency 和 G-function closure-derived efficiency。"""
    out: dict[str, Any] = {
        "efficiency_ratio_pkn_to_g_function": np.nan,
        "efficiency_difference_pkn_minus_g_function": np.nan,
        "efficiency_reconciliation_warning": "missing_efficiency_reference",
    }
    try:
        pkn_eff = float(pkn_shutin_fluid_efficiency)
        g_eff = float(g_function_closure_efficiency)
    except (TypeError, ValueError):
        return out
    if not (np.isfinite(pkn_eff) and np.isfinite(g_eff) and g_eff > 0):
        return out

    diff = pkn_eff - g_eff
    out["efficiency_ratio_pkn_to_g_function"] = float(pkn_eff / g_eff)
    out["efficiency_difference_pkn_minus_g_function"] = float(diff)

    if abs(diff) <= 0.1:
        warning = "efficiency_consistent_within_0p1"
    elif diff < -0.2:
        warning = "pkn_efficiency_much_lower_than_g_function_check_C"
    elif diff > 0.2:
        warning = "pkn_efficiency_much_higher_than_g_function_check_storage"
    else:
        warning = "efficiency_difference_between_0p1_and_0p2"
    out["efficiency_reconciliation_warning"] = warning
    return out


def classify_closure_g_time(selected_closure_g_time: float | None) -> str:
    """按 Gc 大小给闭合候选分档；只用于审计，不改变 closure pick。"""
    try:
        g_c = float(selected_closure_g_time)
    except (TypeError, ValueError):
        return "invalid_Gc"
    if not np.isfinite(g_c):
        return "invalid_Gc"
    if g_c < 0.2:
        return "very_low_Gc_lt_0p2"
    if g_c < 0.5:
        return "low_Gc_0p2_to_0p5"
    if g_c < 1.3333333333:
        return "moderate_Gc_0p5_to_1p33"
    return "high_Gc_ge_1p33"


def classify_closure_elapsed_seconds(selected_closure_elapsed_seconds: float | None) -> str:
    """按停泵后闭合候选时间分档；只用于早期瞬态风险审计。"""
    try:
        elapsed = float(selected_closure_elapsed_seconds)
    except (TypeError, ValueError):
        return "invalid_elapsed"
    if not np.isfinite(elapsed):
        return "invalid_elapsed"
    if elapsed < 30.0:
        return "very_early_lt_30s"
    if elapsed < 60.0:
        return "early_30_60s"
    if elapsed < 300.0:
        return "middle_60_300s"
    return "late_gt_300s"


def classify_closure_elapsed_over_tp(closure_elapsed_over_tp: float | None) -> str:
    """按 closure elapsed/tp 分档；用于判断 Gc 低是否主要来自 tp 很大。"""
    try:
        ratio = float(closure_elapsed_over_tp)
    except (TypeError, ValueError):
        return "invalid_elapsed_over_tp"
    if not np.isfinite(ratio):
        return "invalid_elapsed_over_tp"
    if ratio < 0.005:
        return "tiny_lt_0p005"
    if ratio < 0.02:
        return "small_0p005_to_0p02"
    if ratio < 0.1:
        return "moderate_0p02_to_0p1"
    return "large_ge_0p1"


def compute_tp_scaled_g_time(
    *,
    selected_closure_elapsed_seconds: float | None,
    tp_corrected_seconds: float | None,
    tp_multiplier: float,
    g_time_m: float,
) -> dict[str, float]:
    """只改变 tp 口径，重新计算同一 closure elapsed 对应的 G-time 和 eta_G。

    这用于 Phase 5H.1 sensitivity：不重新选 closure，不改变默认公式。
    """
    out = {
        "tp_seconds_scaled": np.nan,
        "selected_closure_delta_scaled": np.nan,
        "selected_closure_g_time_scaled": np.nan,
        "g_function_efficiency_scaled": np.nan,
    }
    try:
        elapsed = float(selected_closure_elapsed_seconds)
        tp = float(tp_corrected_seconds)
        multiplier = float(tp_multiplier)
        m = float(g_time_m)
    except (TypeError, ValueError):
        return out
    if not (
        np.isfinite(elapsed)
        and np.isfinite(tp)
        and np.isfinite(multiplier)
        and np.isfinite(m)
        and elapsed >= 0.0
        and tp > 0.0
        and multiplier > 0.0
    ):
        return out
    tp_scaled = tp * multiplier
    delta = elapsed / tp_scaled
    g_scaled = float(nolte_g_time(delta, m))
    out["tp_seconds_scaled"] = float(tp_scaled)
    out["selected_closure_delta_scaled"] = float(delta)
    out["selected_closure_g_time_scaled"] = float(g_scaled)
    out["g_function_efficiency_scaled"] = float(g_scaled / (g_scaled + 2.0)) if g_scaled > 0 else np.nan
    return out


def build_closure_g_time_efficiency_audit(summary: pd.DataFrame) -> pd.DataFrame:
    """从 closure-batch summary 派生 Phase 5H.1 Gc/tp/efficiency 审计表。"""
    out = summary.copy()
    for col in [
        "selected_closure_elapsed_seconds",
        "selected_closure_g_time",
        "g_function_closure_efficiency",
        "tp_corrected_seconds",
        "tp_legacy_volume_over_rate_seconds",
        "selected_closure_pressure_mpa",
        "pressure_at_shut_in_mpa",
        "pkn_shutin_fluid_efficiency",
        "efficiency_difference_pkn_minus_g_function",
        "pkn_C_stage",
        "stable_dP_dG_slope_mpa",
        "stable_dP_dG_r2",
        "stable_segment_start_elapsed_seconds",
        "stable_segment_end_elapsed_seconds",
    ]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
        else:
            out[col] = np.nan

    with np.errstate(divide="ignore", invalid="ignore"):
        out["closure_elapsed_over_tp"] = (
            out["selected_closure_elapsed_seconds"] / out["tp_corrected_seconds"]
        )
    out["closure_elapsed_over_tp"] = out["closure_elapsed_over_tp"].where(
        np.isfinite(out["closure_elapsed_over_tp"]), np.nan
    )
    if "tp_correction_ratio" in out.columns:
        out["tp_correction_ratio"] = pd.to_numeric(out["tp_correction_ratio"], errors="coerce")
    else:
        with np.errstate(divide="ignore", invalid="ignore"):
            out["tp_correction_ratio"] = (
                out["tp_corrected_seconds"] / out["tp_legacy_volume_over_rate_seconds"]
            )
        out["tp_correction_ratio"] = out["tp_correction_ratio"].where(
            np.isfinite(out["tp_correction_ratio"]), np.nan
        )
    out["Gc_implied_by_g_function_efficiency"] = out["selected_closure_g_time"]
    out["eta_G"] = out["g_function_closure_efficiency"]
    out["Gc_for_20pct_efficiency"] = 0.5
    out["Gc_for_40pct_efficiency"] = 1.3333333333
    out["closure_Gc_class"] = out["selected_closure_g_time"].map(classify_closure_g_time)
    out["closure_elapsed_class"] = out["selected_closure_elapsed_seconds"].map(
        classify_closure_elapsed_seconds
    )
    out["closure_elapsed_over_tp_class"] = out["closure_elapsed_over_tp"].map(
        classify_closure_elapsed_over_tp
    )

    # 有些历史 CSV 没有这些可选列；补空列让审计输出 schema 稳定。
    optional_defaults = {
        "early_transient_risk": False,
        "water_hammer_plausibility_note": "",
        "pkn_fluid_efficiency_warning": "",
        "efficiency_reconciliation_warning": "",
    }
    for col, default in optional_defaults.items():
        if col not in out.columns:
            out[col] = default

    columns = [
        "stage",
        "selected_closure_method",
        "selected_closure_status",
        "selected_closure_elapsed_seconds",
        "selected_closure_g_time",
        "g_function_closure_efficiency",
        "tp_corrected_seconds",
        "tp_legacy_volume_over_rate_seconds",
        "tp_correction_ratio",
        "closure_elapsed_over_tp",
        "selected_closure_pressure_mpa",
        "pressure_at_shut_in_mpa",
        "pkn_shutin_fluid_efficiency",
        "efficiency_difference_pkn_minus_g_function",
        "pkn_C_stage",
        "stable_dP_dG_slope_mpa",
        "stable_dP_dG_r2",
        "stable_segment_start_elapsed_seconds",
        "stable_segment_end_elapsed_seconds",
        "early_transient_risk",
        "water_hammer_plausibility_note",
        "pkn_fluid_efficiency_warning",
        "efficiency_reconciliation_warning",
        "Gc_implied_by_g_function_efficiency",
        "eta_G",
        "Gc_for_20pct_efficiency",
        "Gc_for_40pct_efficiency",
        "closure_Gc_class",
        "closure_elapsed_class",
        "closure_elapsed_over_tp_class",
    ]
    return out[[c for c in columns if c in out.columns]].copy()


def build_tp_sensitivity_efficiency(
    summary: pd.DataFrame,
    *,
    tp_multipliers: Sequence[float],
    g_time_m: float = 0.8,
) -> pd.DataFrame:
    """对固定 closure elapsed 做 tp multiplier sensitivity，不重新选 closure。"""
    rows: list[dict[str, Any]] = []
    for _, row in summary.iterrows():
        for multiplier in tp_multipliers:
            scaled = compute_tp_scaled_g_time(
                selected_closure_elapsed_seconds=row.get("selected_closure_elapsed_seconds"),
                tp_corrected_seconds=row.get("tp_corrected_seconds"),
                tp_multiplier=float(multiplier),
                g_time_m=g_time_m,
            )
            pkn_eff = row.get("pkn_shutin_fluid_efficiency", np.nan)
            try:
                pkn_eff_float = float(pkn_eff)
            except (TypeError, ValueError):
                pkn_eff_float = np.nan
            g_eff = scaled["g_function_efficiency_scaled"]
            rows.append({
                "stage": row.get("stage"),
                "tp_multiplier": float(multiplier),
                "selected_closure_elapsed_seconds": row.get(
                    "selected_closure_elapsed_seconds", np.nan
                ),
                "tp_seconds_scaled": scaled["tp_seconds_scaled"],
                "selected_closure_g_time_scaled": scaled["selected_closure_g_time_scaled"],
                "g_function_efficiency_scaled": g_eff,
                "pkn_shutin_fluid_efficiency": pkn_eff_float,
                "efficiency_difference_scaled": (
                    pkn_eff_float - g_eff
                    if np.isfinite(pkn_eff_float) and np.isfinite(g_eff)
                    else np.nan
                ),
            })
    return pd.DataFrame.from_records(rows)


def required_tp_multiplier_for_target_g(
    *,
    elapsed_seconds: float,
    tp_seconds: float,
    target_g_time: float,
    m: float,
    multiplier_min: float = 0.05,
    multiplier_max: float = 2.0,
) -> dict[str, Any]:
    """求让窗口末端达到 target Gc 所需的最大 tp multiplier。

    固定 elapsed 时，tp 越短，delta=elapsed/tp 越大，G-time 越大。返回的
    multiplier 是“最大仍可达”的 multiplier，也就是最少需要把 tp 缩短到
    当前值的多少倍。
    """
    result: dict[str, Any] = {
        "reachability_status": "missing_inputs",
        "required_tp_multiplier": np.nan,
        "current_max_available_Gc": np.nan,
        "g_time_at_multiplier_min": np.nan,
    }
    try:
        elapsed = float(elapsed_seconds)
        tp = float(tp_seconds)
        target = float(target_g_time)
        m_value = float(m)
        mult_min = float(multiplier_min)
        mult_max = float(multiplier_max)
    except (TypeError, ValueError):
        return result

    if (
        not np.isfinite(elapsed)
        or not np.isfinite(tp)
        or not np.isfinite(target)
        or not np.isfinite(m_value)
        or not np.isfinite(mult_min)
        or not np.isfinite(mult_max)
        or elapsed <= 0
        or tp <= 0
        or target <= 0
        or m_value <= 0
        or mult_min <= 0
        or mult_max <= mult_min
    ):
        return result

    def g_at(multiplier: float) -> float:
        return float(nolte_g_time(elapsed / (tp * multiplier), m_value))

    current_g = g_at(1.0)
    result["current_max_available_Gc"] = current_g
    if current_g >= target:
        result["reachability_status"] = "already_reachable"
        result["required_tp_multiplier"] = 1.0
        result["g_time_at_multiplier_min"] = g_at(mult_min)
        return result

    g_min = g_at(mult_min)
    result["g_time_at_multiplier_min"] = g_min
    if g_min < target:
        result["reachability_status"] = "unreachable_even_at_min_multiplier"
        return result

    lo = mult_min
    hi = min(1.0, mult_max)
    if g_at(hi) >= target:
        result["reachability_status"] = "ok"
        result["required_tp_multiplier"] = hi
        return result

    for _ in range(80):
        mid = (lo + hi) / 2.0
        if g_at(mid) >= target:
            lo = mid
        else:
            hi = mid

    result["reachability_status"] = "ok"
    result["required_tp_multiplier"] = float(lo)
    return result


def classify_tp_reachability(
    required_multiplier: float | None,
    *,
    status: str,
) -> str:
    """把 required tp multiplier 分成便于人工审查的等级。"""
    if status == "already_reachable":
        return "current_reachable"
    if status == "unreachable_even_at_min_multiplier":
        return "unreachable_even_at_0p05"
    if status == "missing_inputs":
        return "missing_inputs"
    try:
        multiplier = float(required_multiplier)
    except (TypeError, ValueError):
        return "missing_inputs"
    if not np.isfinite(multiplier):
        return "missing_inputs"
    if multiplier >= 0.6:
        return "plausible_tp_correction_0p6_to_1p0"
    if multiplier >= 0.3:
        return "aggressive_tp_correction_0p3_to_0p6"
    return "extreme_tp_correction_lt_0p3"


def interpret_tp_reachability(reachability_class: str) -> str:
    if reachability_class == "current_reachable":
        return "current_valid_window_already_reaches_target_Gc"
    if reachability_class == "plausible_tp_correction_0p6_to_1p0":
        return "possibly_explainable_by_fracture_initiation_timing_review_stage1_old_ppt_reference_0p67"
    if reachability_class == "aggressive_tp_correction_0p3_to_0p6":
        return "requires_aggressive_tp_shortening_manual_initiation_review"
    if reachability_class == "extreme_tp_correction_lt_0p3":
        return "unlikely_explained_by_initiation_timing_alone"
    if reachability_class == "unreachable_even_at_0p05":
        return "not_reachable_even_if_tp_is_shortened_to_5pct"
    return "missing_inputs_or_not_computed"


def _delta_for_g_time(target_g_time: float, m: float) -> float:
    """反解 G(delta,m)=target_G_time，仅用于从 Phase 5I max G 推回窗口长度。"""
    target = float(target_g_time)
    m_value = float(m)
    if not np.isfinite(target) or target <= 0 or not np.isfinite(m_value) or m_value <= 0:
        return np.nan
    lo = 0.0
    hi = 1.0
    while float(nolte_g_time(hi, m_value)) < target:
        hi *= 2.0
        if hi > 1e12:
            return np.nan
    for _ in range(80):
        mid = (lo + hi) / 2.0
        if float(nolte_g_time(mid, m_value)) >= target:
            hi = mid
        else:
            lo = mid
    return float(hi)


def build_tp_reachability_audit(
    summary: pd.DataFrame,
    *,
    efficiency_grid: Sequence[float],
    g_time_m: float = 0.8,
    multiplier_min: float = 0.05,
    multiplier_max: float = 2.0,
) -> pd.DataFrame:
    """构建 target Gc 在当前 valid window 下所需 tp multiplier 的审计表。"""
    rows: list[dict[str, Any]] = []
    columns = [
        "stage",
        "target_eta",
        "target_Gc",
        "tp_corrected_seconds",
        "valid_falloff_end_elapsed",
        "current_max_available_Gc",
        "required_tp_multiplier",
        "required_tp_seconds",
        "tp_reduction_fraction",
        "reachability_status",
        "reachability_class",
        "tp_reachability_interpretation",
    ]
    if summary.empty:
        return pd.DataFrame(columns=columns)

    target_pairs = [(float(eta), g_time_for_fluid_efficiency(float(eta))) for eta in efficiency_grid]
    for _, row in summary.iterrows():
        stage = row.get("stage", np.nan)
        tp = pd.to_numeric(pd.Series([row.get("tp_corrected_seconds")]), errors="coerce").iloc[0]
        elapsed = pd.to_numeric(pd.Series([
            row.get("valid_falloff_end_elapsed", row.get("valid_falloff_end_elapsed_seconds", np.nan))
        ]), errors="coerce").iloc[0]
        provided_max_g = pd.to_numeric(pd.Series([
            row.get("current_max_available_Gc", row.get("max_available_Gc", np.nan))
        ]), errors="coerce").iloc[0]
        m_value = pd.to_numeric(pd.Series([row.get("g_time_m", g_time_m)]), errors="coerce").iloc[0]
        if not np.isfinite(m_value) or m_value <= 0:
            m_value = float(g_time_m)

        inferred_elapsed = np.nan
        if (not np.isfinite(elapsed) or elapsed <= 0) and np.isfinite(provided_max_g) and np.isfinite(tp) and tp > 0:
            delta = _delta_for_g_time(float(provided_max_g), float(m_value))
            if np.isfinite(delta):
                inferred_elapsed = float(delta * tp)
                elapsed = inferred_elapsed

        for eta, target_g in target_pairs:
            result = required_tp_multiplier_for_target_g(
                elapsed_seconds=elapsed,
                tp_seconds=tp,
                target_g_time=target_g,
                m=float(m_value),
                multiplier_min=multiplier_min,
                multiplier_max=multiplier_max,
            )
            status = str(result["reachability_status"])
            required_multiplier = result["required_tp_multiplier"]
            reachability_class = classify_tp_reachability(
                required_multiplier,
                status=status,
            )
            required_tp_seconds = (
                float(tp) * float(required_multiplier)
                if np.isfinite(tp) and np.isfinite(required_multiplier)
                else np.nan
            )
            rows.append({
                "stage": stage,
                "target_eta": eta,
                "target_Gc": target_g,
                "tp_corrected_seconds": float(tp) if np.isfinite(tp) else np.nan,
                "valid_falloff_end_elapsed": float(elapsed) if np.isfinite(elapsed) else np.nan,
                "valid_falloff_end_elapsed_source": (
                    "inferred_from_current_max_available_Gc"
                    if np.isfinite(inferred_elapsed)
                    else "stage_summary_or_manifest"
                    if np.isfinite(elapsed)
                    else "missing"
                ),
                "current_max_available_Gc": (
                    float(provided_max_g)
                    if np.isfinite(provided_max_g)
                    else result["current_max_available_Gc"]
                ),
                "required_tp_multiplier": required_multiplier,
                "required_tp_seconds": required_tp_seconds,
                "tp_reduction_fraction": (
                    float(1.0 - required_multiplier)
                    if np.isfinite(required_multiplier)
                    else np.nan
                ),
                "reachability_status": status,
                "reachability_class": reachability_class,
                "tp_reachability_interpretation": interpret_tp_reachability(reachability_class),
            })
    return pd.DataFrame.from_records(rows)


def _continuous_seconds_for_curve(curve: pd.DataFrame) -> np.ndarray:
    seconds_of_day = curve["seconds_of_day"].to_numpy(dtype=float)
    continuous = seconds_of_day.copy()
    offset = 0.0
    for i in range(1, len(continuous)):
        if seconds_of_day[i] + offset < continuous[i - 1]:
            offset += 24.0 * 3600.0
        continuous[i] = seconds_of_day[i] + offset
    return continuous


def _failed_breakdown_peak(status: str) -> dict[str, Any]:
    return {
        "tp_rule_breakdown_peak_seconds": np.nan,
        "tp_multiplier_breakdown_peak": np.nan,
        "initiation_index_breakdown_peak": np.nan,
        "initiation_time_breakdown_peak": "",
        "initiation_pressure_breakdown_peak_mpa": np.nan,
        "initiation_rule_breakdown_peak_status": status,
    }


def _failed_extension_stable(status: str) -> dict[str, Any]:
    return {
        "tp_rule_extension_stable_seconds": np.nan,
        "tp_multiplier_extension_stable": np.nan,
        "initiation_index_extension_stable": np.nan,
        "initiation_time_extension_stable": "",
        "initiation_pressure_extension_stable_mpa": np.nan,
        "extension_stable_window_slope": np.nan,
        "extension_stable_window_r2": np.nan,
        "initiation_rule_extension_stable_status": status,
    }


def _failed_rate_step(status: str) -> dict[str, Any]:
    return {
        "tp_rule_rate_step_seconds": np.nan,
        "tp_multiplier_rate_step": np.nan,
        "initiation_index_rate_step": np.nan,
        "initiation_time_rate_step": "",
        "rate_at_rate_step": np.nan,
        "initiation_rule_rate_step_status": status,
    }


def compute_rule_tp_multiplier(
    *,
    rule_tp_seconds: float | None,
    current_tp_seconds: float | None,
) -> float:
    try:
        rule_tp = float(rule_tp_seconds)
        current_tp = float(current_tp_seconds)
    except (TypeError, ValueError):
        return np.nan
    if not np.isfinite(rule_tp) or not np.isfinite(current_tp) or rule_tp <= 0 or current_tp <= 0:
        return np.nan
    return float(rule_tp / current_tp)


def pick_breakdown_pressure_peak_initiation(
    curve: pd.DataFrame,
    *,
    shut_in_index: int,
    pressure_column: str,
    min_rate: float,
) -> dict[str, Any]:
    """规则 A：停泵前 rate>=min_rate 泵注段的压力峰值。"""
    if pressure_column not in curve.columns:
        return _failed_breakdown_peak("pressure_column_missing")
    pumping = curve.iloc[:shut_in_index].copy()
    mask = (
        pd.to_numeric(pumping["rate"], errors="coerce").to_numpy(dtype=float) >= float(min_rate)
    )
    pressure = pd.to_numeric(pumping[pressure_column], errors="coerce").to_numpy(dtype=float)
    mask = mask & np.isfinite(pressure)
    if not mask.any():
        return _failed_breakdown_peak("not_found")
    local_idx = int(np.argmax(np.where(mask, pressure, -np.inf)))
    return {
        "tp_rule_breakdown_peak_seconds": np.nan,
        "tp_multiplier_breakdown_peak": np.nan,
        "initiation_index_breakdown_peak": local_idx,
        "initiation_time_breakdown_peak": str(curve.iloc[local_idx]["time_text"]),
        "initiation_pressure_breakdown_peak_mpa": float(pressure[local_idx]),
        "initiation_rule_breakdown_peak_status": "ok",
    }


def _linear_slope_r2(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    if len(x) < 2 or len(y) < 2:
        return np.nan, np.nan
    if not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
        return np.nan, np.nan
    if np.nanmax(x) <= np.nanmin(x):
        return np.nan, np.nan
    slope, intercept = np.polyfit(x, y, deg=1)
    pred = slope * x + intercept
    ss_res = float(np.sum((y - pred) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan
    return float(slope), float(r2)


def pick_extension_stable_initiation(
    curve: pd.DataFrame,
    *,
    shut_in_index: int,
    pressure_column: str,
    min_rate: float,
    window_points: int = 20,
    slope_threshold: float = 0.05,
) -> dict[str, Any]:
    """规则 B：压力峰值后进入扩展压力平台的第一个稳定窗口。"""
    if pressure_column not in curve.columns:
        return _failed_extension_stable("pressure_column_missing")
    if window_points < 2:
        raise ValueError("stable pressure window points must be >= 2")
    peak = pick_breakdown_pressure_peak_initiation(
        curve,
        shut_in_index=shut_in_index,
        pressure_column=pressure_column,
        min_rate=min_rate,
    )
    if peak["initiation_rule_breakdown_peak_status"] != "ok":
        return _failed_extension_stable("pressure_peak_not_found")
    peak_idx = int(peak["initiation_index_breakdown_peak"])
    pressure = pd.to_numeric(curve[pressure_column], errors="coerce").to_numpy(dtype=float)
    rate = pd.to_numeric(curve["rate"], errors="coerce").to_numpy(dtype=float)
    seconds = _continuous_seconds_for_curve(curve)
    last_start = shut_in_index - int(window_points)
    if last_start <= peak_idx:
        return _failed_extension_stable("not_found")
    for start in range(peak_idx + 1, last_start + 1):
        end = start + int(window_points)
        p = pressure[start:end]
        t = seconds[start:end]
        r = rate[start:end]
        if len(p) < window_points:
            continue
        if not np.all(np.isfinite(p)) or not np.all(np.isfinite(t)) or not np.all(np.isfinite(r)):
            continue
        if not np.all(r >= float(min_rate)):
            continue
        slope, r2 = _linear_slope_r2(t - t[0], p)
        if not np.isfinite(slope):
            continue
        max_step = float(np.nanmax(np.abs(np.diff(p)))) if len(p) > 1 else np.nan
        if abs(slope) <= float(slope_threshold) and max_step <= float(slope_threshold):
            return {
                "tp_rule_extension_stable_seconds": np.nan,
                "tp_multiplier_extension_stable": np.nan,
                "initiation_index_extension_stable": int(start),
                "initiation_time_extension_stable": str(curve.iloc[start]["time_text"]),
                "initiation_pressure_extension_stable_mpa": float(pressure[start]),
                "extension_stable_window_slope": float(slope),
                "extension_stable_window_r2": float(r2) if np.isfinite(r2) else np.nan,
                "initiation_rule_extension_stable_status": "ok",
            }
    return _failed_extension_stable("not_found")


def pick_rate_step_initiation(
    curve: pd.DataFrame,
    *,
    shut_in_index: int,
    design_rate: float,
    rate_step_fraction: float = 0.8,
) -> dict[str, Any]:
    """规则 C：达到设计排量比例的第一个点。"""
    try:
        threshold = float(design_rate) * float(rate_step_fraction)
    except (TypeError, ValueError):
        return _failed_rate_step("invalid_design_rate")
    if not np.isfinite(threshold) or threshold <= 0:
        return _failed_rate_step("invalid_design_rate")
    rate = pd.to_numeric(curve["rate"], errors="coerce").to_numpy(dtype=float)
    mask = np.isfinite(rate[:shut_in_index]) & (rate[:shut_in_index] >= threshold)
    if not mask.any():
        return _failed_rate_step("not_found")
    idx = int(np.flatnonzero(mask)[0])
    return {
        "tp_rule_rate_step_seconds": np.nan,
        "tp_multiplier_rate_step": np.nan,
        "initiation_index_rate_step": idx,
        "initiation_time_rate_step": str(curve.iloc[idx]["time_text"]),
        "rate_at_rate_step": float(rate[idx]),
        "initiation_rule_rate_step_status": "ok",
    }


def compute_fracture_initiation_rule_reachability(
    *,
    rule_multiplier: float | None,
    required_multiplier: float | None,
) -> str:
    try:
        rule = float(rule_multiplier)
    except (TypeError, ValueError):
        return "rule_missing"
    try:
        required = float(required_multiplier)
    except (TypeError, ValueError):
        return "target_missing"
    if not np.isfinite(required):
        return "target_missing"
    if not np.isfinite(rule):
        return "rule_missing"
    if rule <= required:
        if rule >= 0.6:
            return "reaches_target_with_plausible_rule"
        return "reaches_target_but_rule_extreme"
    return "does_not_reach_target"


def _rule_multiplier_class(rule_multiplier: float | None) -> str:
    try:
        value = float(rule_multiplier)
    except (TypeError, ValueError):
        return "missing"
    if not np.isfinite(value):
        return "missing"
    if value >= 0.6:
        return "plausible"
    if value >= 0.3:
        return "aggressive"
    return "extreme"


def recommend_tp_review_priority(row: pd.Series) -> str:
    multipliers = pd.to_numeric(pd.Series([
        row.get("tp_multiplier_breakdown_peak"),
        row.get("tp_multiplier_extension_stable"),
        row.get("tp_multiplier_rate_step"),
    ]), errors="coerce").dropna()
    if len(multipliers) == 0:
        return "high"
    if len(multipliers) >= 2 and float(multipliers.max() - multipliers.min()) > 0.4:
        return "high"
    eta20_cols = [
        "target_0p20_reached_by_breakdown_peak",
        "target_0p20_reached_by_extension_stable",
        "target_0p20_reached_by_rate_step",
    ]
    eta20_reach = [str(row.get(col, "")) for col in eta20_cols]
    if any(value.startswith("reaches_target") for value in eta20_reach):
        reaching = []
        for rule in ["breakdown_peak", "extension_stable", "rate_step"]:
            if str(row.get(f"target_0p20_reached_by_{rule}", "")).startswith("reaches_target"):
                reaching.append(row.get(f"tp_multiplier_{rule}"))
        if reaching and all(_rule_multiplier_class(value) == "extreme" for value in reaching):
            return "high"
    eta10_cols = [
        "target_0p10_reached_by_breakdown_peak",
        "target_0p10_reached_by_extension_stable",
        "target_0p10_reached_by_rate_step",
    ]
    eta10_values = [str(row.get(col, "")) for col in eta10_cols]
    eta10_plausible = any(value == "reaches_target_with_plausible_rule" for value in eta10_values)
    eta20_reached = any(value.startswith("reaches_target") for value in eta20_reach)
    b = row.get("tp_multiplier_breakdown_peak")
    e = row.get("tp_multiplier_extension_stable")
    if np.isfinite(pd.to_numeric(pd.Series([b]), errors="coerce").iloc[0]) and np.isfinite(
        pd.to_numeric(pd.Series([e]), errors="coerce").iloc[0]
    ):
        if abs(float(b) - float(e)) > 0.2:
            return "medium"
    if eta10_plausible and not eta20_reached:
        return "medium"
    if eta10_plausible:
        return "low"
    return "medium"


def _apply_rule_tp(
    rule: dict[str, Any],
    *,
    rule_name: str,
    curve: pd.DataFrame,
    shut_in_index: int,
    current_tp_seconds: float,
) -> dict[str, Any]:
    index_key = f"initiation_index_{rule_name}"
    tp_key = f"tp_rule_{rule_name}_seconds"
    mult_key = f"tp_multiplier_{rule_name}"
    status_key = f"initiation_rule_{rule_name}_status"
    if rule.get(status_key) != "ok":
        return rule
    idx = int(rule[index_key])
    seconds = _continuous_seconds_for_curve(curve)
    tp_rule = float(seconds[shut_in_index] - seconds[idx])
    if not np.isfinite(tp_rule) or tp_rule <= 0:
        rule[status_key] = "failed"
        rule[tp_key] = np.nan
        rule[mult_key] = np.nan
        return rule
    rule[tp_key] = tp_rule
    rule[mult_key] = compute_rule_tp_multiplier(
        rule_tp_seconds=tp_rule,
        current_tp_seconds=current_tp_seconds,
    )
    return rule


def _required_multiplier_lookup(tp_reachability: pd.DataFrame) -> dict[tuple[int, str], float]:
    lookup: dict[tuple[int, str], float] = {}
    if tp_reachability.empty:
        return lookup
    for _, row in tp_reachability.iterrows():
        try:
            stage = int(row["stage"])
            eta = float(row["target_eta"])
            required = float(row["required_tp_multiplier"])
        except (KeyError, TypeError, ValueError):
            continue
        lookup[(stage, f"{eta:.2f}")] = required
    return lookup


def _target_col_suffix(eta: float) -> str:
    return f"{eta:.2f}".replace(".", "p")


def _build_initiation_summary(audit: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for rule in ["breakdown_peak", "extension_stable", "rate_step"]:
        mult_col = f"tp_multiplier_{rule}"
        values = pd.to_numeric(audit.get(mult_col, pd.Series(dtype=float)), errors="coerce")
        finite = values.dropna()
        row: dict[str, Any] = {
            "rule": rule,
            "valid_stage_count": int(len(finite)),
            "multiplier_min": float(finite.min()) if len(finite) else np.nan,
            "multiplier_median": float(finite.median()) if len(finite) else np.nan,
            "multiplier_max": float(finite.max()) if len(finite) else np.nan,
            "eta_0p10_reachable_count": int(
                audit.get(f"target_0p10_reached_by_{rule}", pd.Series(dtype=str))
                .astype(str)
                .str.startswith("reaches_target")
                .sum()
            ),
            "eta_0p20_reachable_count": int(
                audit.get(f"target_0p20_reached_by_{rule}", pd.Series(dtype=str))
                .astype(str)
                .str.startswith("reaches_target")
                .sum()
            ),
            "plausible_count": int((finite >= 0.6).sum()),
            "aggressive_count": int(((finite >= 0.3) & (finite < 0.6)).sum()),
            "extreme_count": int((finite < 0.3).sum()),
        }
        rows.append(row)
    return pd.DataFrame.from_records(rows)


def build_fracture_initiation_tp_audit(
    *,
    stage_params_path: str | Path,
    well_root: str | Path,
    manifest_path: str | Path,
    tp_reachability_path: str | Path,
    volume_column: str = "total_volume",
    rate_time_unit: str = "minute",
    min_rate: float = 10.0,
    design_rate: float | None = 18.0,
    rate_step_fraction: float = 0.8,
    pressure_source: str = "estimated-bottomhole",
    stable_pressure_window_points: int = 20,
    stable_pressure_slope_threshold: float = 0.05,
    well: str | None = None,
) -> dict[str, pd.DataFrame]:
    """运行三套起裂候选规则的 tp 审计；不改变默认 tp。"""
    stages_info = read_stage_params(stage_params_path)
    manifest = pd.read_csv(manifest_path, dtype=str, keep_default_na=False)
    missing_cols = sorted(_REQUIRED_MANIFEST_COLUMNS - set(manifest.columns))
    if missing_cols:
        raise ValueError(f"manifest 缺少必填列: {', '.join(missing_cols)}")
    tp_reachability = pd.read_csv(tp_reachability_path)
    required_lookup = _required_multiplier_lookup(tp_reachability)

    rows: list[dict[str, Any]] = []
    for _, mrow in manifest.iterrows():
        stage_num = int(mrow["stage"])
        stage_info = _find_stage(stages_info, stage_num, well)
        curve = read_stage_curve(Path(well_root) / stage_info.data_file)
        shut_in_index = find_shut_in_index(curve, stage_info.shut_in_time)
        tp_legacy = volume_over_max_rate_duration_seconds(
            curve,
            shut_in_index,
            max_sustained_rate=float(mrow["max_sustained_rate"]),
            rate_time_unit=rate_time_unit,
            volume_column=volume_column,
        )
        pressure_col = "wellhead_pressure_mpa"
        curve_for_pressure = curve
        if pressure_source == "estimated-bottomhole" and stage_info.liquid_column_pressure_mpa is not None:
            curve_for_pressure = add_estimated_bottomhole_pressure(curve, stage_info)
            pressure_col = "estimated_bottomhole_pressure_mpa"

        initiation = pick_fracture_initiation_candidate(
            curve_for_pressure,
            shut_in_index,
            pressure_column=pressure_col,
            minimum_stress_prior_mpa=stage_info.minimum_stress_prior_mpa,
            min_rate=min_rate,
        )
        current_tp = (
            float(initiation["tp_corrected_seconds"])
            if initiation["fracture_initiation_status"] == "ok"
            and np.isfinite(initiation["tp_corrected_seconds"])
            and initiation["tp_corrected_seconds"] > 0
            else float(tp_legacy)
        )
        stage_design_rate = (
            float(design_rate)
            if design_rate is not None and np.isfinite(float(design_rate))
            else float(mrow["max_sustained_rate"])
        )

        breakdown = _apply_rule_tp(
            pick_breakdown_pressure_peak_initiation(
                curve_for_pressure,
                shut_in_index=shut_in_index,
                pressure_column=pressure_col,
                min_rate=min_rate,
            ),
            rule_name="breakdown_peak",
            curve=curve_for_pressure,
            shut_in_index=shut_in_index,
            current_tp_seconds=current_tp,
        )
        extension = _apply_rule_tp(
            pick_extension_stable_initiation(
                curve_for_pressure,
                shut_in_index=shut_in_index,
                pressure_column=pressure_col,
                min_rate=min_rate,
                window_points=stable_pressure_window_points,
                slope_threshold=stable_pressure_slope_threshold,
            ),
            rule_name="extension_stable",
            curve=curve_for_pressure,
            shut_in_index=shut_in_index,
            current_tp_seconds=current_tp,
        )
        rate_step = _apply_rule_tp(
            pick_rate_step_initiation(
                curve_for_pressure,
                shut_in_index=shut_in_index,
                design_rate=stage_design_rate,
                rate_step_fraction=rate_step_fraction,
            ),
            rule_name="rate_step",
            curve=curve_for_pressure,
            shut_in_index=shut_in_index,
            current_tp_seconds=current_tp,
        )

        out: dict[str, Any] = {
            "stage": stage_num,
            "shut_in_time": stage_info.shut_in_time,
            "tp_current_seconds": current_tp,
            "tp_legacy_volume_over_rate_seconds": float(tp_legacy),
            **breakdown,
            **extension,
            **rate_step,
        }
        for eta in [0.10, 0.15, 0.20]:
            suffix = _target_col_suffix(eta)
            required = required_lookup.get((stage_num, f"{eta:.2f}"), np.nan)
            out[f"required_tp_multiplier_eta_{suffix}"] = required
            for rule in ["breakdown_peak", "extension_stable", "rate_step"]:
                out[f"target_{suffix}_reached_by_{rule}"] = compute_fracture_initiation_rule_reachability(
                    rule_multiplier=out.get(f"tp_multiplier_{rule}"),
                    required_multiplier=required,
                )
        out["recommended_tp_review_priority"] = recommend_tp_review_priority(pd.Series(out))
        rows.append(out)

    audit = pd.DataFrame.from_records(rows)
    summary = _build_initiation_summary(audit)
    return {"audit": audit, "summary": summary}


def select_target_g_time_row(
    *,
    g_time: np.ndarray,
    elapsed_seconds: np.ndarray,
    pressure_mpa: np.ndarray,
    target_g_time: float,
) -> dict[str, Any]:
    """在有效 falloff window 中选择最接近 target Gc 的行。

    若距离相同，`np.argmin` 会选择更早出现的行，使规则稳定可测试。
    """
    g = np.asarray(g_time, dtype=float)
    elapsed = np.asarray(elapsed_seconds, dtype=float)
    pressure = np.asarray(pressure_mpa, dtype=float)
    result: dict[str, Any] = {
        "target_status": "target_not_computed",
        "target_row_index": np.nan,
        "target_elapsed_seconds": np.nan,
        "target_nolte_g_time": np.nan,
        "target_pressure_mpa": np.nan,
        "max_available_Gc": np.nan,
        "target_inside_valid_window": False,
    }
    try:
        target = float(target_g_time)
    except (TypeError, ValueError):
        result["target_status"] = "target_Gc_invalid"
        return result
    finite_g = g[np.isfinite(g)]
    if len(finite_g) == 0 or not np.isfinite(target):
        result["target_status"] = "target_Gc_invalid"
        return result
    max_g = float(np.max(finite_g))
    result["max_available_Gc"] = max_g
    if target > max_g:
        result["target_status"] = "target_Gc_beyond_valid_window"
        return result

    valid_position = np.isfinite(g) & np.isfinite(elapsed)
    if not valid_position.any():
        result["target_status"] = "target_pressure_missing"
        return result
    valid_idx = np.where(valid_position)[0]
    nearest_pos = int(np.argmin(np.abs(g[valid_idx] - target)))
    idx = int(valid_idx[nearest_pos])
    result.update({
        "target_row_index": idx,
        "target_elapsed_seconds": float(elapsed[idx]),
        "target_nolte_g_time": float(g[idx]),
    })
    if not np.isfinite(pressure[idx]):
        result["target_status"] = "target_pressure_missing"
        result["target_pressure_mpa"] = np.nan
        return result
    result.update({
        "target_status": "ok",
        "target_pressure_mpa": float(pressure[idx]),
        "target_inside_valid_window": True,
    })
    return result


EFFICIENCY_PRIOR_METRICS = (
    "pkn_fracture_volume_m3",
    "pkn_leakoff_volume_m3",
    "pkn_nonstorage_volume_m3",
    "pkn_shutin_fluid_efficiency",
    "target_pressure_mpa",
    "target_elapsed_seconds",
)

EFFICIENCY_PRIOR_TARGETS = (
    "microseismic_affected_volume",
    "electromagnetic_affected_area",
)


def _pearson_spearman_series(metric_values: pd.Series, target_values: pd.Series) -> tuple[float, float, int]:
    pair = pd.DataFrame({
        "metric": pd.to_numeric(metric_values, errors="coerce"),
        "target": pd.to_numeric(target_values, errors="coerce"),
    }).dropna()
    n = int(len(pair))
    if n < 3:
        return np.nan, np.nan, n
    pearson = float(pair["metric"].corr(pair["target"], method="pearson"))
    spearman = float(pair["metric"].rank().corr(pair["target"].rank()))
    return pearson, spearman, n


def build_target_Gc_availability(stage_table: pd.DataFrame) -> pd.DataFrame:
    """汇总每个 target eta/Gc 是否在有效窗口内可达。"""
    if stage_table.empty:
        return pd.DataFrame(columns=[
            "target_eta",
            "target_Gc",
            "ok_stage_count",
            "beyond_valid_window_count",
            "missing_stage_count",
            "median_target_elapsed_seconds",
            "median_target_minus_selected_elapsed_seconds",
            "median_target_pressure_mpa",
            "median_selected_closure_g_time",
            "median_target_Gc",
            "median_max_available_Gc",
        ])
    rows: list[dict[str, Any]] = []
    grouped = stage_table.groupby("target_fluid_efficiency", dropna=False)
    for eta, grp in grouped:
        status = grp["target_status"].astype(str)
        rows.append({
            "target_eta": eta,
            "target_Gc": float(pd.to_numeric(grp["target_Gc"], errors="coerce").median()),
            "ok_stage_count": int((status == "ok").sum()),
            "beyond_valid_window_count": int((status == "target_Gc_beyond_valid_window").sum()),
            "missing_stage_count": int((status != "ok").sum() - (status == "target_Gc_beyond_valid_window").sum()),
            "median_target_elapsed_seconds": float(pd.to_numeric(
                grp["target_elapsed_seconds"], errors="coerce"
            ).median()),
            "median_target_minus_selected_elapsed_seconds": float(pd.to_numeric(
                grp["target_minus_selected_elapsed_seconds"], errors="coerce"
            ).median()),
            "median_target_pressure_mpa": float(pd.to_numeric(
                grp["target_pressure_mpa"], errors="coerce"
            ).median()),
            "median_selected_closure_g_time": float(pd.to_numeric(
                grp["selected_closure_g_time"], errors="coerce"
            ).median()),
            "median_target_Gc": float(pd.to_numeric(grp["target_Gc"], errors="coerce").median()),
            "median_max_available_Gc": float(pd.to_numeric(
                grp["max_available_Gc"], errors="coerce"
            ).median()),
        })
    return pd.DataFrame.from_records(rows)


def build_efficiency_prior_correlation_table(
    stage_table: pd.DataFrame,
    selected_summary: pd.DataFrame,
) -> pd.DataFrame:
    """构建 selected baseline 和 efficiency-prior target rows 的相关性表。"""
    rows: list[dict[str, Any]] = []

    if not selected_summary.empty:
        selected = selected_summary.copy()
        selected["target_fluid_efficiency"] = "selected"
        selected["target_Gc"] = "selected"
        selected["target_status"] = np.where(
            selected.get("selected_closure_status", "") == "ok", "ok", "missing_selected_closure"
        )
        selected["target_pressure_mpa"] = selected.get("selected_closure_pressure_mpa", np.nan)
        selected["target_elapsed_seconds"] = selected.get("selected_closure_elapsed_seconds", np.nan)
        groups: list[tuple[Any, pd.DataFrame]] = [("selected", selected)]
    else:
        groups = []

    for eta, grp in stage_table.groupby("target_fluid_efficiency", dropna=False):
        groups.append((eta, grp))

    for eta, grp in groups:
        target_g = "selected"
        if eta != "selected" and "target_Gc" in grp.columns:
            numeric_g = pd.to_numeric(grp["target_Gc"], errors="coerce")
            target_g = float(numeric_g.median()) if numeric_g.notna().any() else np.nan
        status = grp.get("target_status", pd.Series([""] * len(grp))).astype(str)
        ok_count = int((status == "ok").sum())
        beyond_count = int((status == "target_Gc_beyond_valid_window").sum())
        missing_count = int(len(status) - ok_count - beyond_count)
        if eta == "selected":
            note = "selected_closure_baseline_candidate_not_final_truth"
        elif ok_count == 0:
            note = "target_prior_unavailable_in_valid_window_or_missing"
        else:
            note = "efficiency_prior_sensitivity_not_final_closure_pick"

        for metric in EFFICIENCY_PRIOR_METRICS:
            metric_col = metric
            if eta == "selected" and metric == "target_pressure_mpa":
                metric_col = "selected_closure_pressure_mpa"
            if eta == "selected" and metric == "target_elapsed_seconds":
                metric_col = "selected_closure_elapsed_seconds"
            for target in EFFICIENCY_PRIOR_TARGETS:
                if metric_col not in grp.columns or target not in grp.columns:
                    pearson = spearman = np.nan
                    n = 0
                else:
                    pearson, spearman, n = _pearson_spearman_series(
                        grp[metric_col], grp[target]
                    )
                rows.append({
                    "target_fluid_efficiency": eta,
                    "target_Gc": target_g,
                    "metric": metric,
                    "target": target,
                    "n": n,
                    "pearson_r": pearson,
                    "spearman_r": spearman,
                    "ok_stage_count": ok_count,
                    "beyond_window_count": beyond_count,
                    "missing_stage_count": missing_count,
                    "physical_plausibility_note": note,
                })
    return pd.DataFrame.from_records(rows)


def build_g_time_scale_efficiency_diagnostic(
    selected_summary: pd.DataFrame,
    *,
    scales: Sequence[tuple[float, str]] | None = None,
) -> pd.DataFrame:
    """只对 selected Gc 做 G-time scale compatibility sensitivity。"""
    if scales is None:
        scales = [
            (1.0, "identity_current_definition"),
            (math.pi / 4.0, "pi_over_4_convention_check"),
            (4.0 / math.pi, "4_over_pi_convention_check"),
            (2.0, "scale_2_convention_check"),
            (4.0, "scale_4_convention_check"),
        ]
    rows: list[dict[str, Any]] = []
    for _, row in selected_summary.iterrows():
        g_c = pd.to_numeric(pd.Series([row.get("selected_closure_g_time")]), errors="coerce").iloc[0]
        for scale, note in scales:
            eta_scaled = np.nan
            if np.isfinite(g_c) and g_c > 0 and np.isfinite(scale) and scale > 0:
                scaled_g = scale * float(g_c)
                eta_scaled = scaled_g / (scaled_g + 2.0)
            rows.append({
                "stage": row.get("stage"),
                "scale": float(scale),
                "selected_closure_g_time": g_c,
                "eta_G_scaled": float(eta_scaled) if np.isfinite(eta_scaled) else np.nan,
                "scale_note": note,
            })
    return pd.DataFrame.from_records(rows)


def _find_target_stage_row(selected_summary: pd.DataFrame, stage_num: int) -> pd.Series:
    matches = selected_summary[selected_summary["stage"].astype(int) == int(stage_num)]
    if matches.empty:
        return pd.Series(dtype=object)
    return matches.iloc[0]


def _empty_efficiency_prior_row(
    *,
    stage: int,
    target_eta: float,
    target_Gc: float,
    status: str,
    max_available_Gc: float = np.nan,
    selected_row: pd.Series | None = None,
    observations: pd.Series | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "stage": int(stage),
        "target_fluid_efficiency": float(target_eta),
        "target_Gc": float(target_Gc),
        "target_status": status,
        "target_elapsed_seconds": np.nan,
        "target_nolte_g_time": np.nan,
        "target_pressure_mpa": np.nan,
        "max_available_Gc": max_available_Gc,
        "selected_closure_g_time": np.nan,
        "selected_closure_elapsed_seconds": np.nan,
        "selected_g_function_efficiency": np.nan,
        "target_minus_selected_Gc": np.nan,
        "target_minus_selected_elapsed_seconds": np.nan,
        "target_inside_valid_window": False,
        "pkn_fracture_volume_m3": np.nan,
        "pkn_leakoff_volume_m3": np.nan,
        "pkn_nonstorage_volume_m3": np.nan,
        "pkn_shutin_fluid_efficiency": np.nan,
        "pkn_stable_storage_fraction": np.nan,
        "microseismic_affected_volume": np.nan,
        "electromagnetic_affected_area": np.nan,
    }
    if selected_row is not None and not selected_row.empty:
        row["selected_closure_g_time"] = selected_row.get("selected_closure_g_time", np.nan)
        row["selected_closure_elapsed_seconds"] = selected_row.get(
            "selected_closure_elapsed_seconds", np.nan
        )
        row["selected_g_function_efficiency"] = selected_row.get(
            "g_function_closure_efficiency", np.nan
        )
    if observations is not None and not observations.empty:
        for col in EFFICIENCY_PRIOR_TARGETS:
            if col in observations:
                row[col] = observations.get(col, np.nan)
    return row


def run_efficiency_prior_closure_sweep(
    *,
    stage_params_path: str | Path,
    well_root: str | Path,
    manifest_path: str | Path,
    observations_path: str | Path | None = None,
    efficiency_grid: Sequence[float] = (0.10, 0.15, 0.20, 0.30, 0.40, 0.60),
    volume_column: str = "total_volume",
    rate_time_unit: str = "minute",
    min_rate: float = 10.0,
    g_time_m: float = 0.8,
    elapsed_duplicate_policy: str = "keep-last",
    pressure_source: str = "estimated-bottomhole",
    stress_shadow_alpha: float = 1.0,
    flow_allocation: str = "stress-shadow",
    flow_allocation_exponent: float = 1.0,
    pkn_C_coupling: str = "stage-constant",
    pkn_H_w_m: float | None = None,
    closure_mode: str = "both",
    wellbore_storage_coeff_m3_per_mpa: float = 0.0,
    perforation_friction_mpa: float = 0.0,
    method_preference: str = "barree-then-mcclure",
    well: str | None = None,
    stable_min_elapsed_seconds: float = 15.0,
    stable_min_points: int = 8,
    stable_min_r2: float = 0.8,
    stable_window_mode: str = "longest",
) -> dict[str, pd.DataFrame]:
    """运行 efficiency-prior closure candidate sweep。

    默认 closure pick 不改变；selected baseline 由原 closure-batch 产生。
    target eta 只作为 prior sensitivity：把 eta 映射成 target Gc，再找有效窗口中
    最近的一行作为候选行，传入现有 physical PKN 计算。
    """
    if closure_mode not in ("selected", "efficiency-prior", "both"):
        raise ValueError(f"unknown closure_mode: {closure_mode}")

    selected_result = run_closure_batch(
        stage_params_path=stage_params_path,
        well_root=well_root,
        manifest_path=manifest_path,
        observations_path=observations_path,
        volume_column=volume_column,
        rate_time_unit=rate_time_unit,
        min_rate=min_rate,
        g_time_m=g_time_m,
        elapsed_duplicate_policy=elapsed_duplicate_policy,
        closure_min_elapsed_seconds=stable_min_elapsed_seconds,
        pressure_source=pressure_source,
        perforation_friction_mpa=perforation_friction_mpa,
        wellbore_storage_coeff_m3_per_mpa=wellbore_storage_coeff_m3_per_mpa,
        method_preference=method_preference,
        stress_shadow_alpha=stress_shadow_alpha,
        flow_allocation=flow_allocation,
        flow_allocation_exponent=flow_allocation_exponent,
        pkn_C_coupling=pkn_C_coupling,
        pkn_H_w_m=pkn_H_w_m,
        stable_min_elapsed_seconds=stable_min_elapsed_seconds,
        stable_min_points=stable_min_points,
        stable_min_r2=stable_min_r2,
        stable_window_mode=stable_window_mode,
        well=well,
    )
    selected_summary: pd.DataFrame = selected_result["summary"]

    if closure_mode == "selected":
        empty_stage_table = pd.DataFrame(columns=[
            "stage",
            "target_fluid_efficiency",
            "target_Gc",
            "target_status",
            "target_elapsed_seconds",
            "target_nolte_g_time",
            "target_pressure_mpa",
            "max_available_Gc",
            "selected_closure_g_time",
            "selected_closure_elapsed_seconds",
            "selected_g_function_efficiency",
            "target_minus_selected_Gc",
            "target_minus_selected_elapsed_seconds",
            "target_inside_valid_window",
            "pkn_fracture_volume_m3",
            "pkn_leakoff_volume_m3",
            "pkn_nonstorage_volume_m3",
            "pkn_shutin_fluid_efficiency",
            "pkn_stable_storage_fraction",
            "microseismic_affected_volume",
            "electromagnetic_affected_area",
        ])
        return {
            "stage_table": empty_stage_table,
            "correlations": build_efficiency_prior_correlation_table(
                empty_stage_table, selected_summary
            ),
            "availability": build_target_Gc_availability(empty_stage_table),
            "g_time_scale": build_g_time_scale_efficiency_diagnostic(selected_summary),
            "selected_summary": selected_summary,
        }

    observations: pd.DataFrame | None = None
    if observations_path is not None:
        observations = pd.read_csv(observations_path)
        observations["stage"] = observations["stage"].astype(int)

    stages_info = read_stage_params(stage_params_path)
    manifest = pd.read_csv(manifest_path, dtype=str, keep_default_na=False)
    missing_cols = sorted(_REQUIRED_MANIFEST_COLUMNS - set(manifest.columns))
    if missing_cols:
        raise ValueError(f"manifest 缺少必填列: {', '.join(missing_cols)}")

    target_rows: list[dict[str, Any]] = []
    target_pairs = [(float(eta), g_time_for_fluid_efficiency(float(eta))) for eta in efficiency_grid]

    for _, mrow in manifest.iterrows():
        stage_num = int(mrow["stage"])
        selected_row = _find_target_stage_row(selected_summary, stage_num)
        obs_row = pd.Series(dtype=object)
        if observations is not None:
            obs_match = observations[observations["stage"] == stage_num]
            if not obs_match.empty:
                obs_row = obs_match.iloc[0]

        stage_info = _find_stage(stages_info, stage_num, well)
        curve = read_stage_curve(Path(well_root) / stage_info.data_file)
        shut_in_index = find_shut_in_index(curve, stage_info.shut_in_time)

        tp_legacy = volume_over_max_rate_duration_seconds(
            curve,
            shut_in_index,
            max_sustained_rate=float(mrow["max_sustained_rate"]),
            rate_time_unit=rate_time_unit,
            volume_column=volume_column,
        )
        pressure_col_pre = "wellhead_pressure_mpa"
        if pressure_source == "estimated-bottomhole" and stage_info.liquid_column_pressure_mpa is not None:
            curve_for_init = add_estimated_bottomhole_pressure(curve, stage_info)
            pressure_col_pre = "estimated_bottomhole_pressure_mpa"
        else:
            curve_for_init = curve
        initiation = pick_fracture_initiation_candidate(
            curve_for_init,
            shut_in_index,
            pressure_column=pressure_col_pre,
            minimum_stress_prior_mpa=stage_info.minimum_stress_prior_mpa,
            min_rate=min_rate,
        )
        init_ok = initiation["fracture_initiation_status"] == "ok"
        tp_corrected = initiation["tp_corrected_seconds"] if init_ok else tp_legacy
        tp_for_g = tp_corrected if np.isfinite(tp_corrected) and tp_corrected > 0 else tp_legacy
        init_idx = int(initiation["fracture_initiation_index"]) if init_ok else None
        raw_vol = _compute_raw_injected_volume(curve, init_idx, shut_in_index, volume_column)

        falloff = falloff_window_after_shut_in(
            curve,
            shut_in_index,
            end_elapsed_seconds=float(mrow["valid_falloff_end_elapsed"]),
        )
        readiness_window = apply_elapsed_duplicate_policy(
            falloff, policy=elapsed_duplicate_policy
        )
        elapsed = readiness_window["elapsed_seconds"].to_numpy(dtype=float)
        if len(elapsed) < 3 or not np.isfinite(tp_for_g) or tp_for_g <= 0:
            for eta, target_Gc in target_pairs:
                target_rows.append(_empty_efficiency_prior_row(
                    stage=stage_num,
                    target_eta=eta,
                    target_Gc=target_Gc,
                    status="stage_window_not_ready",
                    selected_row=selected_row,
                    observations=obs_row,
                ))
            continue

        g_time_arr = np.asarray(nolte_g_time(elapsed / tp_for_g, g_time_m), dtype=float)
        pw, _p_col, p_vals = _get_pressure_column_and_values(
            readiness_window, stage_info, pressure_source
        )
        if not np.all(np.isfinite(g_time_arr)) or not np.all(np.diff(g_time_arr) > 0):
            for eta, target_Gc in target_pairs:
                target_rows.append(_empty_efficiency_prior_row(
                    stage=stage_num,
                    target_eta=eta,
                    target_Gc=target_Gc,
                    status="g_time_not_strictly_increasing",
                    max_available_Gc=float(np.nanmax(g_time_arr)) if len(g_time_arr) else np.nan,
                    selected_row=selected_row,
                    observations=obs_row,
                ))
            continue

        p_shut_in = float(p_vals[0]) if len(p_vals) else np.nan
        E_prime = stage_info.youngs_modulus_gpa * 1000.0 / (1.0 - stage_info.poissons_ratio ** 2) if (
            stage_info.youngs_modulus_gpa is not None
            and stage_info.poissons_ratio is not None
            and np.isfinite(stage_info.youngs_modulus_gpa)
            and np.isfinite(stage_info.poissons_ratio)
        ) else np.nan
        n_cl = stage_info.num_clusters if stage_info.num_clusters is not None else 0
        spacings: list[float] | float = stage_info.cluster_spacings_list if stage_info.cluster_spacings_list else (
            stage_info.cluster_spacing_m if stage_info.cluster_spacing_m is not None else 10.0
        )
        fleak_for_pkn = stage_info.fleak

        for eta, target_Gc in target_pairs:
            target = select_target_g_time_row(
                g_time=g_time_arr,
                elapsed_seconds=elapsed,
                pressure_mpa=p_vals,
                target_g_time=target_Gc,
            )
            base_row = _empty_efficiency_prior_row(
                stage=stage_num,
                target_eta=eta,
                target_Gc=target_Gc,
                status=target["target_status"],
                max_available_Gc=target["max_available_Gc"],
                selected_row=selected_row,
                observations=obs_row,
            )
            base_row.update({
                "target_elapsed_seconds": target["target_elapsed_seconds"],
                "target_nolte_g_time": target["target_nolte_g_time"],
                "target_pressure_mpa": target["target_pressure_mpa"],
                "target_inside_valid_window": target["target_inside_valid_window"],
            })
            if np.isfinite(base_row["selected_closure_g_time"]):
                base_row["target_minus_selected_Gc"] = (
                    target_Gc - float(base_row["selected_closure_g_time"])
                )
            if (
                np.isfinite(base_row["target_elapsed_seconds"])
                and np.isfinite(base_row["selected_closure_elapsed_seconds"])
            ):
                base_row["target_minus_selected_elapsed_seconds"] = (
                    float(base_row["target_elapsed_seconds"])
                    - float(base_row["selected_closure_elapsed_seconds"])
                )

            if target["target_status"] != "ok":
                target_rows.append(base_row)
                continue

            target_idx = int(target["target_row_index"])
            vol_result = effective_volume_correction(
                raw_vol,
                p_shut_in,
                float(target["target_pressure_mpa"]),
                perforation_friction_mpa=perforation_friction_mpa,
                wellbore_storage_coeff_m3_per_mpa=wellbore_storage_coeff_m3_per_mpa,
            )
            pkn_result = physical_pkn_volume_balance(
                n_clusters=n_cl,
                cluster_spacings_m=spacings,
                H_w_m=pkn_H_w_m,
                fleak=fleak_for_pkn,
                E_prime_mpa=E_prime,
                closure_pressure_mpa=float(target["target_pressure_mpa"]),
                minimum_stress_prior_mpa=stage_info.minimum_stress_prior_mpa,
                perforation_friction_mpa=perforation_friction_mpa,
                g_time=g_time_arr,
                pressure_mpa=p_vals,
                elapsed_seconds=elapsed,
                closure_index=target_idx,
                tp_seconds=tp_for_g,
                g_function_m=stage_info.g_function_m if stage_info.g_function_m is not None else g_time_m,
                effective_injected_volume_m3=vol_result["effective_injected_volume_m3"],
                alpha=stress_shadow_alpha,
                flow_allocation=flow_allocation,
                flow_allocation_exponent=flow_allocation_exponent,
                C_coupling=pkn_C_coupling,
                stable_min_elapsed_seconds=stable_min_elapsed_seconds,
                stable_min_points=stable_min_points,
                stable_min_r2=stable_min_r2,
                stable_window_mode=stable_window_mode,
            )
            base_row.update({
                "pkn_fracture_volume_m3": pkn_result.get("pkn_fracture_volume_m3", np.nan),
                "pkn_leakoff_volume_m3": pkn_result.get("pkn_leakoff_volume_m3", np.nan),
                "pkn_nonstorage_volume_m3": pkn_result.get("pkn_nonstorage_volume_m3", np.nan),
                "pkn_shutin_fluid_efficiency": pkn_result.get("pkn_shutin_fluid_efficiency", np.nan),
                "pkn_stable_storage_fraction": pkn_result.get("pkn_stable_storage_fraction", np.nan),
            })
            target_rows.append(base_row)

    stage_table = pd.DataFrame.from_records(target_rows)
    selected_for_correlation = (
        selected_summary if closure_mode == "both" else pd.DataFrame()
    )
    correlations = build_efficiency_prior_correlation_table(
        stage_table, selected_for_correlation
    )
    availability = build_target_Gc_availability(stage_table)
    scale_diagnostic = build_g_time_scale_efficiency_diagnostic(selected_summary)
    return {
        "stage_table": stage_table,
        "correlations": correlations,
        "availability": availability,
        "g_time_scale": scale_diagnostic,
        "selected_summary": selected_summary,
    }


def compute_C_multiplier_to_fluid_efficiency(
    *,
    storage_unit: float | None,
    leakoff_unit: float | None,
    target_efficiency: float | None,
) -> float:
    """求把当前 leakoff unit 调到目标 fluid efficiency 所需的 C multiplier。

    target_eff = S / (S + L_target)
    L_target = S * (1 / target_eff - 1)
    C_multiplier = L_target / L_current
    """
    try:
        storage = float(storage_unit)
        leakoff = float(leakoff_unit)
        target = float(target_efficiency)
    except (TypeError, ValueError):
        return float("nan")
    if not (
        np.isfinite(storage)
        and np.isfinite(leakoff)
        and np.isfinite(target)
        and storage > 0
        and leakoff > 0
        and 0 < target < 1
    ):
        return float("nan")
    leakoff_unit_target = storage * (1.0 / target - 1.0)
    return float(leakoff_unit_target / leakoff)


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


def legacy_mvp_pkn_volume_balance_estimate(
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


PHYSICAL_PKN_IF = 0.722464726919
PHYSICAL_PKN_HW_M = 50.0


def _pkn_height_value_and_source(H_w_m: float | None) -> tuple[float, str]:
    """返回 PKN 裂缝高度和来源标签。

    H_w_m 为 None 表示使用项目默认值 50 m；CLI 或网格显式传入数值时，
    即使数值也是 50，也标记为 cli_or_grid，方便审计参数是否真正接入。
    """
    if H_w_m is None:
        return PHYSICAL_PKN_HW_M, "default_50m"
    H_w_value = float(H_w_m)
    return H_w_value, "cli_or_grid"


def physical_pkn_fracture_volume(
    L_m: float,
    H_w_m: float,
    P_net_mpa: float,
    E_prime_mpa: float,
    *,
    I_F: float = PHYSICAL_PKN_IF,
) -> float:
    """V_f = pi * I_F / E' * L * H_w^2 * P_net [m^3]."""
    if L_m <= 0 or H_w_m <= 0 or P_net_mpa <= 0 or E_prime_mpa <= 0:
        return 0.0
    return math.pi * I_F / E_prime_mpa * L_m * H_w_m ** 2 * P_net_mpa


def compute_stress_shadow(
    n: int,
    cluster_spacings_m: list[float] | float,
    H_w_m: float,
    *,
    alpha: float = 1.0,
) -> dict[str, Any]:
    """Sneddon stress shadow: (I + alpha * F) * xi = 1."""
    result: dict[str, Any] = {
        "stress_shadow_status": "failed",
        "stress_shadow_alpha": float(alpha),
        "stress_shadow_kernel": "sneddon",
        "stress_shadow_condition_number": np.nan,
        "stress_shadow_xi": np.ones(max(n, 1)),
        "stress_shadow_xi_min": np.nan,
        "stress_shadow_xi_max": np.nan,
        "stress_shadow_xi_mean": np.nan,
        "stress_shadow_xi_sum": np.nan,
    }

    if n <= 0:
        result["stress_shadow_status"] = "failed"
        return result

    if n == 1 or alpha == 0.0:
        xi = np.ones(n)
        result.update({
            "stress_shadow_status": "ok",
            "stress_shadow_condition_number": 1.0,
            "stress_shadow_xi": xi,
            "stress_shadow_xi_min": 1.0,
            "stress_shadow_xi_max": 1.0,
            "stress_shadow_xi_mean": 1.0,
            "stress_shadow_xi_sum": float(n),
        })
        return result

    if isinstance(cluster_spacings_m, (int, float)):
        spacings = [float(cluster_spacings_m)] * (n - 1)
    else:
        spacings = [float(s) for s in cluster_spacings_m]

    if len(spacings) == n - 1:
        positions = np.concatenate(([0.0], np.cumsum(spacings)))
    elif len(spacings) == n:
        positions = np.array(spacings, dtype=float)
    else:
        positions = np.arange(n, dtype=float) * (spacings[0] if spacings else 10.0)

    a = H_w_m / 2.0
    dist = np.abs(positions[:, None] - positions[None, :])
    F = 1.0 - dist / np.sqrt(dist ** 2 + a ** 2)
    np.fill_diagonal(F, 0.0)

    A = np.eye(n) + alpha * F
    cond = float(np.linalg.cond(A))

    if cond > 1e12:
        result["stress_shadow_condition_number"] = cond
        return result

    xi = np.linalg.solve(A, np.ones(n))

    result.update({
        "stress_shadow_status": "ok",
        "stress_shadow_condition_number": cond,
        "stress_shadow_xi": xi,
        "stress_shadow_xi_min": float(np.min(xi)),
        "stress_shadow_xi_max": float(np.max(xi)),
        "stress_shadow_xi_mean": float(np.mean(xi)),
        "stress_shadow_xi_sum": float(np.sum(xi)),
    })
    return result


def _prefix_linear_fit_stats(
    prefix_x: np.ndarray,
    prefix_y: np.ndarray,
    prefix_x2: np.ndarray,
    prefix_y2: np.ndarray,
    prefix_xy: np.ndarray,
    start: int,
    end: int,
) -> tuple[float, float, float] | None:
    """Return slope/intercept/r2 for compact arrays[start:end], end exclusive."""
    n = end - start
    if n < 2:
        return None

    sx = float(prefix_x[end] - prefix_x[start])
    sy = float(prefix_y[end] - prefix_y[start])
    sx2 = float(prefix_x2[end] - prefix_x2[start])
    sy2 = float(prefix_y2[end] - prefix_y2[start])
    sxy = float(prefix_xy[end] - prefix_xy[start])

    sxx = sx2 - sx * sx / n
    syy = sy2 - sy * sy / n
    if sxx <= 0 or syy <= 0:
        return None

    sxy_centered = sxy - sx * sy / n
    slope = sxy_centered / sxx
    intercept = sy / n - slope * sx / n
    r2 = (sxy_centered * sxy_centered) / (sxx * syy)
    return float(slope), float(intercept), float(min(max(r2, 0.0), 1.0))


def pick_stable_pressure_g_segment(
    g_time: np.ndarray,
    pressure_mpa: np.ndarray,
    elapsed_seconds: np.ndarray,
    *,
    closure_index: int | None = None,
    min_elapsed_seconds: float = 15.0,
    min_points: int = 8,
    min_r2: float = 0.8,
    window_mode: str = "longest",
) -> dict[str, Any]:
    """Find a linear P-vs-G segment before closure.

    window_mode controls how the segment is chosen among candidate windows that
    satisfy slope<0 and R^2>=min_r2:
      - "longest" (default, legacy): pick the longest qualifying window.
      - "best-r2": pick the window with the highest R^2 regardless of length.
      - "early-best": prefer windows starting in the earlier half of valid_idx;
        among those pick the highest R^2. Falls back to the overall best-R^2
        candidate if no early window qualifies.
    """
    failed: dict[str, Any] = {
        "stable_segment_status": "not_found",
        "stable_dP_dG_slope_mpa": np.nan,
        "stable_dP_dG_intercept_mpa": np.nan,
        "stable_dP_dG_r2": np.nan,
        "stable_segment_start_index": np.nan,
        "stable_segment_end_index": np.nan,
        "stable_segment_start_elapsed_seconds": np.nan,
        "stable_segment_end_elapsed_seconds": np.nan,
        "stable_segment_point_count": 0,
    }

    if window_mode not in ("longest", "best-r2", "early-best"):
        raise ValueError(f"unknown window_mode: {window_mode}")

    mask = elapsed_seconds >= min_elapsed_seconds
    if closure_index is not None:
        idx_mask = np.arange(len(elapsed_seconds)) <= closure_index
        mask = mask & idx_mask

    valid_idx = np.where(mask)[0]
    if len(valid_idx) < min_points:
        return failed

    g_valid = g_time[valid_idx].astype(float)
    p_valid = pressure_mpa[valid_idx].astype(float)
    prefix_x = np.concatenate(([0.0], np.cumsum(g_valid)))
    prefix_y = np.concatenate(([0.0], np.cumsum(p_valid)))
    prefix_x2 = np.concatenate(([0.0], np.cumsum(g_valid * g_valid)))
    prefix_y2 = np.concatenate(([0.0], np.cumsum(p_valid * p_valid)))
    prefix_xy = np.concatenate(([0.0], np.cumsum(g_valid * p_valid)))

    if window_mode == "longest":
        best_start = -1
        best_end = -1
        best_n = 0
        best_r2 = -1.0
        best_slope = np.nan
        best_intercept = np.nan

        for window_len in range(len(valid_idx), min_points - 1, -1):
            for start_pos in range(len(valid_idx) - window_len + 1):
                stats = _prefix_linear_fit_stats(
                    prefix_x,
                    prefix_y,
                    prefix_x2,
                    prefix_y2,
                    prefix_xy,
                    start_pos,
                    start_pos + window_len,
                )
                if stats is None:
                    continue
                slope, intercept, r2 = stats

                if r2 >= min_r2 and window_len > best_n:
                    best_start = int(valid_idx[start_pos])
                    best_end = int(valid_idx[start_pos + window_len - 1])
                    best_n = window_len
                    best_r2 = r2
                    best_slope = slope
                    best_intercept = intercept
                    break
            if best_n >= window_len:
                break

        if best_n < min_points or best_slope >= 0:
            return failed

        return {
            "stable_segment_status": "ok",
            "stable_dP_dG_slope_mpa": best_slope,
            "stable_dP_dG_intercept_mpa": best_intercept,
            "stable_dP_dG_r2": best_r2,
            "stable_segment_start_index": best_start,
            "stable_segment_end_index": best_end,
            "stable_segment_start_elapsed_seconds": float(elapsed_seconds[best_start]),
            "stable_segment_end_elapsed_seconds": float(elapsed_seconds[best_end]),
            "stable_segment_point_count": best_n,
        }

    # best-r2 / early-best: enumerate qualifying windows using prefix-sum
    # regression, then keep only the best all-window and early-window candidate.
    best_all: tuple[int, int, int, float, float, float] | None = None
    best_early: tuple[int, int, int, float, float, float] | None = None
    early_cutoff = int(valid_idx[len(valid_idx) // 2])
    for window_len in range(min_points, len(valid_idx) + 1):
        for start_pos in range(len(valid_idx) - window_len + 1):
            stats = _prefix_linear_fit_stats(
                prefix_x,
                prefix_y,
                prefix_x2,
                prefix_y2,
                prefix_xy,
                start_pos,
                start_pos + window_len,
            )
            if stats is None:
                continue
            slope, intercept, r2 = stats
            if slope >= 0:
                continue
            if r2 < min_r2:
                continue
            candidate = (
                int(valid_idx[start_pos]),
                int(valid_idx[start_pos + window_len - 1]),
                window_len,
                r2,
                slope,
                intercept,
            )
            if best_all is None or r2 > best_all[3]:
                best_all = candidate
            if candidate[0] <= early_cutoff and (best_early is None or r2 > best_early[3]):
                best_early = candidate

    if best_all is None:
        return failed

    if window_mode == "best-r2":
        best = best_all
    else:  # early-best
        best = best_early if best_early is not None else best_all

    best_start, best_end, best_n, best_r2, best_slope, best_intercept = best
    return {
        "stable_segment_status": "ok",
        "stable_dP_dG_slope_mpa": float(best_slope),
        "stable_dP_dG_intercept_mpa": float(best_intercept),
        "stable_dP_dG_r2": float(best_r2),
        "stable_segment_start_index": int(best_start),
        "stable_segment_end_index": int(best_end),
        "stable_segment_start_elapsed_seconds": float(elapsed_seconds[best_start]),
        "stable_segment_end_elapsed_seconds": float(elapsed_seconds[best_end]),
        "stable_segment_point_count": int(best_n),
    }


def compute_physical_leakoff_C(
    dP_dG_slope: float,
    H_w_m: float,
    E_prime_mpa: float,
    H_p_m: float,
    tp_seconds: float,
    xi: float,
    *,
    I_F: float = PHYSICAL_PKN_IF,
) -> float:
    """C = -(I_F * H_w^2 * xi) / (E' * H_p * sqrt(tp)) * dP/dG."""
    if E_prime_mpa <= 0 or H_p_m <= 0 or tp_seconds <= 0:
        return 0.0
    return -(I_F * H_w_m ** 2 * xi) / (E_prime_mpa * H_p_m * math.sqrt(tp_seconds)) * dP_dG_slope


def K_lp(m: float) -> float:
    """K_lp(m) = 4*sqrt(pi) * m * Gamma(m) / ((m+0.5) * Gamma(m+0.5))."""
    if m <= 0:
        return 0.0
    return 4.0 * math.sqrt(math.pi) * m * math.gamma(m) / (
        (m + 0.5) * math.gamma(m + 0.5)
    )


def compute_flow_allocation_eta(
    xi: np.ndarray,
    *,
    exponent: float = 1.0,
) -> np.ndarray:
    """eta_i = xi_i^gamma / sum(xi_j^gamma). exponent=0 gives uniform."""
    if not np.all(np.isfinite(xi)) or np.any(xi <= 0):
        raise ValueError("xi must be finite and positive for flow allocation")
    if not np.isfinite(exponent) or exponent < 0:
        raise ValueError(f"flow_allocation_exponent must be finite and >= 0, got {exponent}")
    weights = xi ** exponent
    return weights / weights.sum()


def physical_pkn_volume_balance(
    *,
    n_clusters: int,
    cluster_spacings_m: list[float] | float,
    H_w_m: float | None = None,
    fleak: float | None = None,
    E_prime_mpa: float,
    closure_pressure_mpa: float | None,
    minimum_stress_prior_mpa: float | None,
    perforation_friction_mpa: float = 0.0,
    g_time: np.ndarray,
    pressure_mpa: np.ndarray,
    elapsed_seconds: np.ndarray,
    closure_index: int | None = None,
    tp_seconds: float,
    g_function_m: float = 0.8,
    effective_injected_volume_m3: float,
    alpha: float = 1.0,
    I_F: float = PHYSICAL_PKN_IF,
    stable_min_elapsed_seconds: float = 15.0,
    stable_min_points: int = 8,
    stable_min_r2: float = 0.8,
    stable_window_mode: str = "longest",
    flow_allocation: str = "stress-shadow",
    flow_allocation_exponent: float = 1.0,
    C_coupling: str = "stage-constant",
    C_multiplier: float = 1.0,
) -> dict[str, Any]:
    """Physical PKN storage volume balance with stress shadow and stable-segment C.

    C_coupling controls how the stage-level leakoff coefficient C_stage is mapped
    to per-cluster C_L_i:
      - "stage-constant" (default): C_L_i = C_stage for all i.
      - "shadow-scaled":  C_L_i = xi_i * C_stage (legacy Phase 5D.4 coupling).

    stable_window_mode is forwarded to pick_stable_pressure_g_segment. The default
    "longest" preserves legacy behaviour; "best-r2" / "early-best" are for
    grid-search sensitivity, not production interpretation.

    C_multiplier is a Phase 5F sensitivity knob: C_stage is computed from the
    stable-segment slope, then multiplied by C_multiplier before any per-cluster
    coupling. The default 1.0 preserves legacy behaviour. The raw value and the
    applied multiplier are recorded in the output for audit.
    """
    H_w_value, H_w_source = _pkn_height_value_and_source(H_w_m)

    base: dict[str, Any] = {
        "pkn_model_name": "physical_pkn_storage",
        "pkn_model_version": "phase5d",
        "pkn_H_w_m": float(H_w_value),
        "pkn_H_w_source": H_w_source,
        "pkn_I_F": float(I_F),
        "pkn_I_F_source": "human_required_constant",
        "pkn_E_prime_mpa": float(E_prime_mpa),
    }

    def _fail(reason: str) -> dict[str, Any]:
        out = dict(base)
        out.update({
            "pkn_volume_status": "failed",
            "pkn_fracture_volume_m3": np.nan,
            "pkn_fracture_volume_std_m3": np.nan,
            "pkn_half_length_mean_m": np.nan,
            "pkn_half_length_std_m": np.nan,
            "pkn_net_pressure_min_mpa": np.nan,
            "pkn_net_pressure_max_mpa": np.nan,
            "pkn_net_pressure_mean_mpa": np.nan,
            "pkn_cluster_count": n_clusters,
            "pkn_cluster_length_min_m": np.nan,
            "pkn_cluster_length_max_m": np.nan,
            "pkn_cluster_length_mean_m": np.nan,
            "pkn_cluster_length_std_m": np.nan,
            "pkn_stable_row_count": 0,
            "pkn_leakoff_coefficient": np.nan,
            "pkn_segment_start": np.nan,
            "pkn_segment_end": np.nan,
            "pkn_K_lp": np.nan,
            "pkn_C_status": "failed",
            "pkn_C_coupling_method": C_coupling,
            "pkn_C_stage": np.nan,
            "pkn_C_stage_raw": np.nan,
            "pkn_C_multiplier_applied": float(C_multiplier),
            "pkn_C_min": np.nan,
            "pkn_C_max": np.nan,
            "pkn_C_mean": np.nan,
            "pkn_H_p_m": np.nan,
            "pkn_fleak": np.nan,
            "pkn_warning": reason,
            "stress_shadow_status": "failed",
            "stress_shadow_alpha": float(alpha),
            "stress_shadow_kernel": "sneddon",
            "stress_shadow_condition_number": np.nan,
            "stress_shadow_xi_min": np.nan,
            "stress_shadow_xi_max": np.nan,
            "stress_shadow_xi_mean": np.nan,
            "stable_segment_status": "not_found",
            "stable_dP_dG_slope_mpa": np.nan,
            "stable_dP_dG_r2": np.nan,
            "stable_segment_start_index": np.nan,
            "stable_segment_end_index": np.nan,
            "stable_segment_start_elapsed_seconds": np.nan,
            "stable_segment_end_elapsed_seconds": np.nan,
            "stable_segment_point_count": 0,
            "pkn_flow_allocation_method": flow_allocation,
            "pkn_flow_allocation_exponent": float(flow_allocation_exponent),
            "pkn_eta_min": np.nan,
            "pkn_eta_max": np.nan,
            "pkn_eta_mean": np.nan,
            "pkn_eta_std": np.nan,
            "pkn_leakoff_volume_m3": np.nan,
            "pkn_leakoff_volume_std_m3": np.nan,
            "pkn_nonstorage_volume_m3": np.nan,
            "pkn_storage_fraction": np.nan,
            "pkn_leakoff_fraction": np.nan,
            "pkn_nonstorage_fraction": np.nan,
            "pkn_balance_residual_mean_m3": np.nan,
            "pkn_balance_residual_abs_max_m3": np.nan,
            "pkn_stable_storage_fraction": np.nan,
            "pkn_stable_leakoff_fraction": np.nan,
            "pkn_stable_nonstorage_fraction": np.nan,
            "pkn_stable_g_min": np.nan,
            "pkn_stable_g_mean": np.nan,
            "pkn_stable_g_max": np.nan,
            "pkn_stable_storage_unit_mean_m2": np.nan,
            "pkn_stable_preclosure_leakoff_unit_mean_m2": np.nan,
            "pkn_stable_G_leakoff_unit_mean_m2": np.nan,
            "pkn_stable_storage_unit_fraction": np.nan,
            "pkn_stable_G_leakoff_unit_fraction": np.nan,
            "pkn_shutin_storage_volume_m3": np.nan,
            "pkn_shutin_leakoff_before_closure_m3": np.nan,
            "pkn_shutin_fluid_efficiency": np.nan,
            "pkn_shutin_leakoff_fraction": np.nan,
            "pkn_shutin_storage_unit_mean_m2": np.nan,
            "pkn_shutin_preclosure_leakoff_unit_mean_m2": np.nan,
            "pkn_shutin_storage_unit_fraction": np.nan,
            "pkn_shutin_preclosure_leakoff_unit_fraction": np.nan,
            "pkn_C_multiplier_to_20pct_shutin_efficiency": np.nan,
            "pkn_C_multiplier_to_10pct_shutin_efficiency": np.nan,
            "pkn_C_multiplier_to_g_function_efficiency": np.nan,
            "pkn_fluid_efficiency_warning": "",
            "pkn_C_stage_units_assumed": "",
            "pkn_tp_seconds": np.nan,
            "pkn_sqrt_tp_seconds": np.nan,
        })
        return out

    if C_coupling not in ("stage-constant", "shadow-scaled"):
        return _fail(f"unknown_pkn_C_coupling:{C_coupling}")
    if not np.isfinite(H_w_value) or H_w_value <= 0:
        return _fail(f"invalid_pkn_H_w_m:{H_w_m}")
    if n_clusters < 1:
        return _fail("n_clusters_invalid")
    if not np.isfinite(E_prime_mpa) or E_prime_mpa <= 0:
        return _fail("E_prime_invalid")
    if not np.isfinite(effective_injected_volume_m3) or effective_injected_volume_m3 <= 0:
        return _fail("effective_volume_invalid")
    if not np.isfinite(tp_seconds) or tp_seconds <= 0:
        return _fail("tp_invalid")

    shadow = compute_stress_shadow(n_clusters, cluster_spacings_m, H_w_value, alpha=alpha)
    if shadow["stress_shadow_status"] != "ok":
        out = _fail("stress_shadow_linear_system_failed")
        out.update({k: v for k, v in shadow.items() if k != "stress_shadow_xi"})
        return out

    xi = shadow["stress_shadow_xi"]

    seg = pick_stable_pressure_g_segment(
        g_time, pressure_mpa, elapsed_seconds,
        closure_index=closure_index,
        min_elapsed_seconds=stable_min_elapsed_seconds,
        min_points=stable_min_points,
        min_r2=stable_min_r2,
        window_mode=stable_window_mode,
    )
    if seg["stable_segment_status"] != "ok":
        out = _fail("no_stable_pressure_g_segment")
        out.update({k: v for k, v in shadow.items() if k != "stress_shadow_xi"})
        out.update(seg)
        return out

    fleak_val = fleak if fleak is not None and np.isfinite(fleak) and fleak > 0 else 0.5
    fleak_warning = "" if (fleak is not None and np.isfinite(fleak) and fleak > 0) else "fleak_default_0p5"
    H_p_m = fleak_val * H_w_value

    slope = seg["stable_dP_dG_slope_mpa"]
    # C_stage: stage-level leakoff coefficient computed from stable dP/dG with xi=1.
    # Phase 5D.5 lets C_L_i either equal C_stage (stage-constant) or scale by xi (shadow-scaled).
    # Phase 5F adds a multiplier knob for grid-search sensitivity; the raw value is preserved.
    C_stage_raw = compute_physical_leakoff_C(slope, H_w_value, E_prime_mpa, H_p_m, tp_seconds, 1.0, I_F=I_F)
    if not np.isfinite(C_multiplier) or C_multiplier <= 0:
        out = _fail(f"invalid_C_multiplier:{C_multiplier}")
        out.update({k: v for k, v in shadow.items() if k != "stress_shadow_xi"})
        out.update(seg)
        return out
    C_stage = C_stage_raw * float(C_multiplier)
    if not np.isfinite(C_stage) or C_stage < 0:
        out = _fail("invalid_C_from_stable_dP_dG")
        out.update({k: v for k, v in shadow.items() if k != "stress_shadow_xi"})
        out.update(seg)
        out["pkn_C_status"] = "failed"
        return out

    if C_coupling == "stage-constant":
        C_arr = np.full(n_clusters, C_stage)
    else:
        C_arr = xi * C_stage

    if not np.all(np.isfinite(C_arr)) or np.any(C_arr < 0):
        out = _fail("invalid_C_per_cluster")
        out.update({k: v for k, v in shadow.items() if k != "stress_shadow_xi"})
        out.update(seg)
        out["pkn_C_status"] = "failed"
        return out

    k_lp_val = K_lp(g_function_m)

    if flow_allocation == "uniform":
        eta = np.ones(n_clusters) / n_clusters
    else:
        eta = compute_flow_allocation_eta(xi, exponent=flow_allocation_exponent)

    sigma = float(minimum_stress_prior_mpa) if minimum_stress_prior_mpa is not None and np.isfinite(minimum_stress_prior_mpa) else 0.0
    perf = float(perforation_friction_mpa)

    seg_start = int(seg["stable_segment_start_index"])
    seg_end = int(seg["stable_segment_end_index"])
    stable_indices = list(range(seg_start, seg_end + 1))

    all_V_total: list[float] = []
    all_L: list[np.ndarray] = []
    all_Pnet: list[np.ndarray] = []
    all_leakoff_total: list[float] = []
    all_injected_total: list[float] = []
    all_balance_residual: list[float] = []
    all_storage_unit: list[np.ndarray] = []
    all_preclosure_leakoff_unit: list[np.ndarray] = []
    all_G_leakoff_unit: list[np.ndarray] = []
    all_g_time: list[float] = []
    cluster_audit_rows: list[dict[str, Any]] = []

    sqrt_tp = math.sqrt(tp_seconds)
    storage_unit_factor = math.pi * I_F / E_prime_mpa * H_w_value ** 2  # multiplies P_net_i
    leakoff_unit_factor = H_p_m * sqrt_tp  # multiplies C_L_i (then K_lp or 4*g)

    for idx in stable_indices:
        p_idx = float(pressure_mpa[idx])
        P_net_arr = xi * max(p_idx - perf - sigma, 0.0)

        if np.all(P_net_arr <= 0):
            continue

        g_val = float(g_time[idx])
        # per-cluster denominator unit_i (Phase 5D.4 direct formula):
        # unit_i = storage_unit_i + preclosure_leakoff_unit_i + G_leakoff_unit_i
        # storage_unit_i           = (pi * I_F / E') * H_w^2 * P_net_i
        # preclosure_leakoff_unit_i = K_lp * C_L_i * H_p * sqrt(tp)
        # G_leakoff_unit_i          = 4 * C_L_i * H_p * sqrt(tp) * g
        # L_i = eta_i * V_inj / unit_i (no global Sum(unit_j * eta_j))
        storage_unit_arr = storage_unit_factor * P_net_arr
        preclosure_leakoff_unit_arr = k_lp_val * C_arr * leakoff_unit_factor
        G_leakoff_unit_arr = 4.0 * C_arr * leakoff_unit_factor * g_val
        unit = storage_unit_arr + preclosure_leakoff_unit_arr + G_leakoff_unit_arr

        if np.all(unit <= 0):
            continue

        with np.errstate(divide="ignore", invalid="ignore"):
            L_arr = np.where(
                unit > 0,
                effective_injected_volume_m3 * eta / unit,
                0.0,
            )
        V_f_arr = np.array([
            physical_pkn_fracture_volume(float(L_arr[i]), H_w_value, float(P_net_arr[i]), E_prime_mpa, I_F=I_F)
            for i in range(n_clusters)
        ])

        # Phase 5D.5 fluid partition per cluster:
        # leakoff_before_closure_i = L_i * K_lp * C_L_i * H_p * sqrt(tp)
        # leakoff_G_i              = L_i * 4 * C_L_i * H_p * sqrt(tp) * g
        # injected_i               = eta_i * V_inj
        leakoff_before_arr = L_arr * preclosure_leakoff_unit_arr
        leakoff_G_arr = L_arr * G_leakoff_unit_arr
        leakoff_total_arr = leakoff_before_arr + leakoff_G_arr
        injected_arr = eta * effective_injected_volume_m3
        balance_residual_arr = injected_arr - V_f_arr - leakoff_total_arr

        for ci in range(n_clusters):
            cluster_audit_rows.append({
                "stable_row_index": int(idx),
                "cluster_index": int(ci),
                "eta_i": float(eta[ci]),
                "xi_i": float(xi[ci]),
                "P_net_i_mpa": float(P_net_arr[ci]),
                "C_L_i": float(C_arr[ci]),
                "C_stage": float(C_stage),
                "pkn_C_coupling_method": C_coupling,
                "denominator_i_m3_per_m": float(unit[ci]),
                "L_i_m": float(L_arr[ci]),
                "V_f_i_m3": float(V_f_arr[ci]),
                "injected_i_m3": float(injected_arr[ci]),
                "storage_i_m3": float(V_f_arr[ci]),
                "leakoff_before_closure_i_m3": float(leakoff_before_arr[ci]),
                "leakoff_G_i_m3": float(leakoff_G_arr[ci]),
                "leakoff_total_i_m3": float(leakoff_total_arr[ci]),
                "balance_residual_i_m3": float(balance_residual_arr[ci]),
                "g_time": g_val,
                "elapsed_seconds": float(elapsed_seconds[idx]),
            })

        all_V_total.append(float(np.sum(V_f_arr)))
        all_L.append(L_arr)
        all_Pnet.append(P_net_arr)
        all_leakoff_total.append(float(np.sum(leakoff_total_arr)))
        all_injected_total.append(float(np.sum(injected_arr)))
        all_balance_residual.append(float(np.sum(balance_residual_arr)))
        all_storage_unit.append(storage_unit_arr.copy())
        all_preclosure_leakoff_unit.append(preclosure_leakoff_unit_arr.copy())
        all_G_leakoff_unit.append(G_leakoff_unit_arr.copy())
        all_g_time.append(g_val)

    if len(all_V_total) == 0:
        out = _fail("net_pressure_nonpositive")
        out.update({k: v for k, v in shadow.items() if k != "stress_shadow_xi"})
        out.update(seg)
        out["pkn_C_status"] = "ok"
        out["pkn_C_coupling_method"] = C_coupling
        out["pkn_C_stage"] = float(C_stage)
        out["pkn_C_stage_raw"] = float(C_stage_raw)
        out["pkn_C_multiplier_applied"] = float(C_multiplier)
        out["pkn_C_min"] = float(np.min(C_arr))
        out["pkn_C_max"] = float(np.max(C_arr))
        out["pkn_C_mean"] = float(np.mean(C_arr))
        return out

    V_arr = np.array(all_V_total)
    L_all = np.concatenate(all_L)
    Pnet_all = np.concatenate(all_Pnet)
    leakoff_total_rows = np.array(all_leakoff_total)
    balance_residual_rows = np.array(all_balance_residual)
    storage_unit_all = np.concatenate(all_storage_unit)
    preclosure_leakoff_unit_all = np.concatenate(all_preclosure_leakoff_unit)
    G_leakoff_unit_all = np.concatenate(all_G_leakoff_unit)
    g_time_rows = np.array(all_g_time)

    storage_mean = float(np.mean(V_arr))
    leakoff_mean = float(np.mean(leakoff_total_rows))
    nonstorage_mean = effective_injected_volume_m3 - storage_mean

    # Stable-row unit-component audit (means across cluster x stable-row points)
    stable_storage_unit_mean = float(np.mean(storage_unit_all))
    stable_preclosure_leakoff_unit_mean = float(np.mean(preclosure_leakoff_unit_all))
    stable_G_leakoff_unit_mean = float(np.mean(G_leakoff_unit_all))
    stable_total_unit_mean = (
        stable_storage_unit_mean
        + stable_preclosure_leakoff_unit_mean
        + stable_G_leakoff_unit_mean
    )
    if stable_total_unit_mean > 0:
        stable_storage_unit_fraction = stable_storage_unit_mean / stable_total_unit_mean
        stable_G_leakoff_unit_fraction = stable_G_leakoff_unit_mean / stable_total_unit_mean
    else:
        stable_storage_unit_fraction = np.nan
        stable_G_leakoff_unit_fraction = np.nan

    # Phase 5D.6 shut-in fluid efficiency:
    # Re-evaluate the per-cluster direct formula at g=0 using shut-in pressure
    # (pressure_mpa[0] is the first row of the readiness window, i.e. the shut-in pressure).
    # shut-in efficiency must NOT include the G leakoff term.
    p_shutin = float(pressure_mpa[0])
    P_net_shutin_arr = xi * max(p_shutin - perf - sigma, 0.0)
    if np.any(P_net_shutin_arr > 0):
        storage_unit_shutin_arr = storage_unit_factor * P_net_shutin_arr
        preclosure_leakoff_unit_shutin_arr = k_lp_val * C_arr * leakoff_unit_factor
        unit_shutin_arr = storage_unit_shutin_arr + preclosure_leakoff_unit_shutin_arr

        with np.errstate(divide="ignore", invalid="ignore"):
            L_shutin_arr = np.where(
                unit_shutin_arr > 0,
                effective_injected_volume_m3 * eta / unit_shutin_arr,
                0.0,
            )
        storage_i_shutin_arr = (
            storage_unit_factor * L_shutin_arr * P_net_shutin_arr
        )
        leakoff_before_i_shutin_arr = L_shutin_arr * preclosure_leakoff_unit_shutin_arr

        shutin_storage_total = float(np.sum(storage_i_shutin_arr))
        shutin_leakoff_before_total = float(np.sum(leakoff_before_i_shutin_arr))

        shutin_storage_unit_mean = float(np.mean(storage_unit_shutin_arr))
        shutin_preclosure_leakoff_unit_mean = float(np.mean(preclosure_leakoff_unit_shutin_arr))
        shutin_total_unit_mean = (
            shutin_storage_unit_mean + shutin_preclosure_leakoff_unit_mean
        )
        if shutin_total_unit_mean > 0:
            shutin_storage_unit_fraction = (
                shutin_storage_unit_mean / shutin_total_unit_mean
            )
            shutin_preclosure_leakoff_unit_fraction = (
                shutin_preclosure_leakoff_unit_mean / shutin_total_unit_mean
            )
        else:
            shutin_storage_unit_fraction = np.nan
            shutin_preclosure_leakoff_unit_fraction = np.nan

        shutin_fluid_efficiency = (
            shutin_storage_total / effective_injected_volume_m3
        )
        shutin_leakoff_fraction = (
            shutin_leakoff_before_total / effective_injected_volume_m3
        )
    else:
        shutin_storage_total = np.nan
        shutin_leakoff_before_total = np.nan
        shutin_storage_unit_mean = np.nan
        shutin_preclosure_leakoff_unit_mean = np.nan
        shutin_storage_unit_fraction = np.nan
        shutin_preclosure_leakoff_unit_fraction = np.nan
        shutin_fluid_efficiency = np.nan
        shutin_leakoff_fraction = np.nan

    # Phase 5D.6 C-multiplier diagnostic:
    # If target_eff = storage_unit / (storage_unit + leakoff_unit_target),
    # then leakoff_unit_target = storage_unit * (1/target_eff - 1),
    # and C_multiplier = leakoff_unit_target / current_leakoff_unit (since leakoff_unit_i ∝ C_stage).
    c_mult_20 = compute_C_multiplier_to_fluid_efficiency(
        storage_unit=shutin_storage_unit_mean,
        leakoff_unit=shutin_preclosure_leakoff_unit_mean,
        target_efficiency=0.20,
    )
    c_mult_10 = compute_C_multiplier_to_fluid_efficiency(
        storage_unit=shutin_storage_unit_mean,
        leakoff_unit=shutin_preclosure_leakoff_unit_mean,
        target_efficiency=0.10,
    )

    # Phase 5D.6 efficiency warning (sanity check label, not a physical conclusion)
    if not np.isfinite(shutin_fluid_efficiency):
        efficiency_warning = "shutin_efficiency_not_finite"
    elif shutin_fluid_efficiency < 0.05:
        efficiency_warning = "very_low_shutin_fluid_efficiency_check_C_units_or_stable_slope"
    elif shutin_fluid_efficiency < 0.10:
        efficiency_warning = "low_shutin_fluid_efficiency_check_C_or_leakoff_terms"
    elif shutin_fluid_efficiency < 0.20:
        efficiency_warning = "below_20pct_reference_check_local_assumptions"
    else:
        efficiency_warning = "no_low_efficiency_warning"

    stable_fraction_val = storage_mean / effective_injected_volume_m3

    result = dict(base)
    result.update({
        "pkn_volume_status": "ok",
        "pkn_fracture_volume_m3": storage_mean,
        "pkn_fracture_volume_std_m3": float(np.std(V_arr)) if len(V_arr) > 1 else 0.0,
        "pkn_half_length_mean_m": float(np.mean(L_all)),
        "pkn_half_length_std_m": float(np.std(L_all)) if len(L_all) > 1 else 0.0,
        "pkn_net_pressure_min_mpa": float(np.min(Pnet_all[Pnet_all > 0])) if np.any(Pnet_all > 0) else np.nan,
        "pkn_net_pressure_max_mpa": float(np.max(Pnet_all)),
        "pkn_net_pressure_mean_mpa": float(np.mean(Pnet_all[Pnet_all > 0])) if np.any(Pnet_all > 0) else np.nan,
        "pkn_cluster_count": n_clusters,
        "pkn_cluster_length_min_m": float(np.min(L_all)),
        "pkn_cluster_length_max_m": float(np.max(L_all)),
        "pkn_cluster_length_mean_m": float(np.mean(L_all)),
        "pkn_cluster_length_std_m": float(np.std(L_all)) if len(L_all) > 1 else 0.0,
        "pkn_stable_row_count": len(all_V_total),
        "pkn_leakoff_coefficient": float(np.mean(C_arr)),
        "pkn_segment_start": seg_start,
        "pkn_segment_end": seg_end,
        "pkn_K_lp": float(k_lp_val),
        "pkn_C_status": "ok",
        "pkn_C_coupling_method": C_coupling,
        "pkn_C_stage": float(C_stage),
        "pkn_C_stage_raw": float(C_stage_raw),
        "pkn_C_multiplier_applied": float(C_multiplier),
        "pkn_C_stage_units_assumed": "m_per_sqrt_second",
        "pkn_C_min": float(np.min(C_arr)),
        "pkn_C_max": float(np.max(C_arr)),
        "pkn_C_mean": float(np.mean(C_arr)),
        "pkn_H_p_m": float(H_p_m),
        "pkn_fleak": float(fleak_val),
        "pkn_warning": fleak_warning,
        "pkn_flow_allocation_method": flow_allocation,
        "pkn_flow_allocation_exponent": float(flow_allocation_exponent),
        "pkn_eta_min": float(np.min(eta)),
        "pkn_eta_max": float(np.max(eta)),
        "pkn_eta_mean": float(np.mean(eta)),
        "pkn_eta_std": float(np.std(eta)) if n_clusters > 1 else 0.0,
        "pkn_leakoff_volume_m3": leakoff_mean,
        "pkn_leakoff_volume_std_m3": float(np.std(leakoff_total_rows)) if len(leakoff_total_rows) > 1 else 0.0,
        "pkn_nonstorage_volume_m3": float(nonstorage_mean),
        "pkn_storage_fraction": float(stable_fraction_val),
        "pkn_stable_storage_fraction": float(stable_fraction_val),
        "pkn_stable_leakoff_fraction": float(leakoff_mean / effective_injected_volume_m3),
        "pkn_stable_nonstorage_fraction": float(nonstorage_mean / effective_injected_volume_m3),
        "pkn_leakoff_fraction": float(leakoff_mean / effective_injected_volume_m3),
        "pkn_nonstorage_fraction": float(nonstorage_mean / effective_injected_volume_m3),
        "pkn_balance_residual_mean_m3": float(np.mean(balance_residual_rows)),
        "pkn_balance_residual_abs_max_m3": float(np.max(np.abs(balance_residual_rows))),
        "pkn_stable_g_min": float(np.min(g_time_rows)),
        "pkn_stable_g_mean": float(np.mean(g_time_rows)),
        "pkn_stable_g_max": float(np.max(g_time_rows)),
        "pkn_stable_storage_unit_mean_m2": stable_storage_unit_mean,
        "pkn_stable_preclosure_leakoff_unit_mean_m2": stable_preclosure_leakoff_unit_mean,
        "pkn_stable_G_leakoff_unit_mean_m2": stable_G_leakoff_unit_mean,
        "pkn_stable_storage_unit_fraction": float(stable_storage_unit_fraction)
            if np.isfinite(stable_storage_unit_fraction) else np.nan,
        "pkn_stable_G_leakoff_unit_fraction": float(stable_G_leakoff_unit_fraction)
            if np.isfinite(stable_G_leakoff_unit_fraction) else np.nan,
        "pkn_shutin_storage_volume_m3": float(shutin_storage_total)
            if np.isfinite(shutin_storage_total) else np.nan,
        "pkn_shutin_leakoff_before_closure_m3": float(shutin_leakoff_before_total)
            if np.isfinite(shutin_leakoff_before_total) else np.nan,
        "pkn_shutin_fluid_efficiency": float(shutin_fluid_efficiency)
            if np.isfinite(shutin_fluid_efficiency) else np.nan,
        "pkn_shutin_leakoff_fraction": float(shutin_leakoff_fraction)
            if np.isfinite(shutin_leakoff_fraction) else np.nan,
        "pkn_shutin_storage_unit_mean_m2": float(shutin_storage_unit_mean)
            if np.isfinite(shutin_storage_unit_mean) else np.nan,
        "pkn_shutin_preclosure_leakoff_unit_mean_m2": float(shutin_preclosure_leakoff_unit_mean)
            if np.isfinite(shutin_preclosure_leakoff_unit_mean) else np.nan,
        "pkn_shutin_storage_unit_fraction": float(shutin_storage_unit_fraction)
            if np.isfinite(shutin_storage_unit_fraction) else np.nan,
        "pkn_shutin_preclosure_leakoff_unit_fraction": float(shutin_preclosure_leakoff_unit_fraction)
            if np.isfinite(shutin_preclosure_leakoff_unit_fraction) else np.nan,
        "pkn_C_multiplier_to_20pct_shutin_efficiency": c_mult_20,
        "pkn_C_multiplier_to_10pct_shutin_efficiency": c_mult_10,
        "pkn_C_multiplier_to_g_function_efficiency": np.nan,
        "pkn_fluid_efficiency_warning": efficiency_warning,
        "pkn_tp_seconds": float(tp_seconds),
        "pkn_sqrt_tp_seconds": float(sqrt_tp),
    })
    result.update({k: v for k, v in shadow.items() if k != "stress_shadow_xi"})
    result.update(seg)
    result["pkn_cluster_audit_rows"] = cluster_audit_rows
    return result


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
        "pkn_leakoff_volume_m3",
        "pkn_nonstorage_volume_m3",
        "pkn_storage_fraction",
        "pkn_leakoff_fraction",
        "pkn_nonstorage_fraction",
        "pkn_stable_storage_fraction",
        "pkn_shutin_fluid_efficiency",
        "pkn_shutin_storage_volume_m3",
        "pkn_shutin_leakoff_before_closure_m3",
        "pkn_C_stage",
        "pkn_C_mean",
        "legacy_mvp_pkn_fracture_volume_m3",
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
    stress_shadow_alpha: float = 1.0,
    flow_allocation: str = "stress-shadow",
    flow_allocation_exponent: float = 1.0,
    pkn_C_coupling: str = "stage-constant",
    tp_multiplier: float = 1.0,
    effective_volume_factor: float = 1.0,
    fleak_override: float | None = None,
    pkn_H_w_m: float | None = None,
    C_multiplier: float = 1.0,
    stable_min_elapsed_seconds: float = 15.0,
    stable_min_points: int = 8,
    stable_min_r2: float = 0.8,
    stable_window_mode: str = "longest",
) -> dict[str, Any]:
    """处理单个 stage 的闭合候选分析。"""
    row: dict[str, Any] = {"stage": stage_info.stage}
    # Phase 5F audit fields (must appear in every return path for schema consistency)
    row["tp_multiplier_applied"] = float(tp_multiplier)
    row["effective_volume_factor_applied"] = float(effective_volume_factor)
    row["pkn_fleak_override_applied"] = (
        float(fleak_override) if fleak_override is not None else np.nan
    )
    row["pkn_H_w_override_applied"] = (
        float(pkn_H_w_m) if pkn_H_w_m is not None else np.nan
    )
    row["pkn_effective_injected_volume_m3"] = np.nan
    row["tp_for_g_seconds"] = np.nan

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
    tp_base = tp_corrected if init_ok and np.isfinite(tp_corrected) and tp_corrected > 0 else tp_legacy
    if not np.isfinite(tp_multiplier) or tp_multiplier <= 0:
        raise ValueError(f"tp_multiplier must be finite and > 0, got {tp_multiplier}")
    tp_for_g = tp_base * float(tp_multiplier)
    row["tp_correction_ratio"] = float(tp_corrected / tp_legacy) if tp_legacy > 0 else np.nan
    row["tp_for_g_seconds"] = float(tp_for_g) if np.isfinite(tp_for_g) else np.nan

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
        row["_pkn_cluster_audit_rows"] = []
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
        row["_pkn_cluster_audit_rows"] = []
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
        row["_pkn_cluster_audit_rows"] = []
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
    g_function_efficiency = compute_g_function_closure_efficiency(
        selected.get("selected_closure_g_time")
    )
    row.update(g_function_efficiency)

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

    legacy_pkn = legacy_mvp_pkn_volume_balance_estimate(
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
    row["legacy_mvp_pkn_fracture_volume_m3"] = legacy_pkn.get("pkn_fracture_volume_m3", np.nan)
    row["legacy_mvp_pkn_half_length_mean_m"] = legacy_pkn.get("pkn_half_length_mean_m", np.nan)
    row["legacy_mvp_pkn_volume_status"] = legacy_pkn.get("pkn_volume_status", "failed")

    E_prime = stage_info.youngs_modulus_gpa * 1000.0 / (1.0 - stage_info.poissons_ratio ** 2) if (
        stage_info.youngs_modulus_gpa is not None and stage_info.poissons_ratio is not None
        and np.isfinite(stage_info.youngs_modulus_gpa) and np.isfinite(stage_info.poissons_ratio)
    ) else np.nan

    closure_idx_for_seg = None
    barree_ci = barree.get("barree_closure_index")
    mcclure_ci = mcclure.get("mcclure_closure_index")
    if selected.get("selected_closure_method") == "barree" and barree_ci is not None and np.isfinite(barree_ci):
        closure_idx_for_seg = int(barree_ci)
    elif selected.get("selected_closure_method") == "mcclure" and mcclure_ci is not None and np.isfinite(mcclure_ci):
        closure_idx_for_seg = int(mcclure_ci)

    n_cl = stage_info.num_clusters if stage_info.num_clusters is not None else 0
    spacings: list[float] | float = stage_info.cluster_spacings_list if stage_info.cluster_spacings_list else (
        stage_info.cluster_spacing_m if stage_info.cluster_spacing_m is not None else 10.0
    )

    if not np.isfinite(effective_volume_factor) or effective_volume_factor <= 0:
        raise ValueError(f"effective_volume_factor must be finite and > 0, got {effective_volume_factor}")
    pkn_effective_volume = vol_result["effective_injected_volume_m3"] * float(effective_volume_factor)
    row["pkn_effective_injected_volume_m3"] = float(pkn_effective_volume)
    fleak_for_pkn = fleak_override if fleak_override is not None else stage_info.fleak

    physical_pkn = physical_pkn_volume_balance(
        n_clusters=n_cl,
        cluster_spacings_m=spacings,
        H_w_m=pkn_H_w_m,
        fleak=fleak_for_pkn,
        E_prime_mpa=E_prime,
        closure_pressure_mpa=closure_p_val,
        minimum_stress_prior_mpa=stage_info.minimum_stress_prior_mpa,
        perforation_friction_mpa=perforation_friction_mpa,
        g_time=g_time_arr,
        pressure_mpa=p_vals,
        elapsed_seconds=elapsed,
        closure_index=closure_idx_for_seg,
        tp_seconds=tp_for_g,
        g_function_m=stage_info.g_function_m if stage_info.g_function_m is not None else g_time_m,
        effective_injected_volume_m3=pkn_effective_volume,
        alpha=stress_shadow_alpha,
        flow_allocation=flow_allocation,
        flow_allocation_exponent=flow_allocation_exponent,
        C_coupling=pkn_C_coupling,
        C_multiplier=C_multiplier,
        stable_min_elapsed_seconds=stable_min_elapsed_seconds,
        stable_min_points=stable_min_points,
        stable_min_r2=stable_min_r2,
        stable_window_mode=stable_window_mode,
    )
    physical_pkn["pkn_C_multiplier_to_g_function_efficiency"] = (
        compute_C_multiplier_to_fluid_efficiency(
            storage_unit=physical_pkn.get("pkn_shutin_storage_unit_mean_m2"),
            leakoff_unit=physical_pkn.get("pkn_shutin_preclosure_leakoff_unit_mean_m2"),
            target_efficiency=g_function_efficiency.get("g_function_closure_efficiency"),
        )
    )
    cluster_audit_rows = physical_pkn.pop("pkn_cluster_audit_rows", [])
    row.update(physical_pkn)
    row.update(reconcile_fluid_efficiencies(
        row.get("pkn_shutin_fluid_efficiency"),
        row.get("g_function_closure_efficiency"),
    ))
    row["_pkn_cluster_audit_rows"] = cluster_audit_rows

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
        **compute_g_function_closure_efficiency(np.nan),
        **reconcile_fluid_efficiencies(np.nan, np.nan),
    }


def _empty_pkn_fields() -> dict[str, Any]:
    return {
        "pkn_model_name": "physical_pkn_storage",
        "pkn_model_version": "phase5d",
        "pkn_volume_status": "not_computed",
        "pkn_half_length_mean_m": np.nan,
        "pkn_half_length_std_m": np.nan,
        "pkn_fracture_volume_m3": np.nan,
        "pkn_fracture_volume_std_m3": np.nan,
        "pkn_H_w_m": np.nan,
        "pkn_H_w_source": "",
        "pkn_I_F": np.nan,
        "pkn_I_F_source": "",
        "pkn_E_prime_mpa": np.nan,
        "pkn_net_pressure_min_mpa": np.nan,
        "pkn_net_pressure_max_mpa": np.nan,
        "pkn_net_pressure_mean_mpa": np.nan,
        "pkn_cluster_count": np.nan,
        "pkn_cluster_length_min_m": np.nan,
        "pkn_cluster_length_max_m": np.nan,
        "pkn_cluster_length_mean_m": np.nan,
        "pkn_cluster_length_std_m": np.nan,
        "pkn_stable_row_count": 0,
        "pkn_leakoff_coefficient": np.nan,
        "pkn_segment_start": np.nan,
        "pkn_segment_end": np.nan,
        "pkn_K_lp": np.nan,
        "pkn_C_status": "not_computed",
        "pkn_C_coupling_method": "",
        "pkn_C_stage": np.nan,
        "pkn_C_stage_raw": np.nan,
        "pkn_C_multiplier_applied": np.nan,
        "pkn_C_min": np.nan,
        "pkn_C_max": np.nan,
        "pkn_C_mean": np.nan,
        "pkn_H_p_m": np.nan,
        "pkn_fleak": np.nan,
        "pkn_warning": "derivatives_not_available",
        "stress_shadow_status": "not_computed",
        "stress_shadow_alpha": np.nan,
        "stress_shadow_kernel": "",
        "stress_shadow_condition_number": np.nan,
        "stress_shadow_xi_min": np.nan,
        "stress_shadow_xi_max": np.nan,
        "stress_shadow_xi_mean": np.nan,
        "stable_segment_status": "not_computed",
        "stable_dP_dG_slope_mpa": np.nan,
        "stable_dP_dG_r2": np.nan,
        "stable_segment_start_index": np.nan,
        "stable_segment_end_index": np.nan,
        "stable_segment_start_elapsed_seconds": np.nan,
        "stable_segment_end_elapsed_seconds": np.nan,
        "stable_segment_point_count": 0,
        "pkn_flow_allocation_method": "",
        "pkn_flow_allocation_exponent": np.nan,
        "pkn_eta_min": np.nan,
        "pkn_eta_max": np.nan,
        "pkn_eta_mean": np.nan,
        "pkn_eta_std": np.nan,
        "pkn_leakoff_volume_m3": np.nan,
        "pkn_leakoff_volume_std_m3": np.nan,
        "pkn_nonstorage_volume_m3": np.nan,
        "pkn_storage_fraction": np.nan,
        "pkn_leakoff_fraction": np.nan,
        "pkn_nonstorage_fraction": np.nan,
        "pkn_balance_residual_mean_m3": np.nan,
        "pkn_balance_residual_abs_max_m3": np.nan,
        "pkn_stable_storage_fraction": np.nan,
        "pkn_stable_leakoff_fraction": np.nan,
        "pkn_stable_nonstorage_fraction": np.nan,
        "pkn_stable_g_min": np.nan,
        "pkn_stable_g_mean": np.nan,
        "pkn_stable_g_max": np.nan,
        "pkn_stable_storage_unit_mean_m2": np.nan,
        "pkn_stable_preclosure_leakoff_unit_mean_m2": np.nan,
        "pkn_stable_G_leakoff_unit_mean_m2": np.nan,
        "pkn_stable_storage_unit_fraction": np.nan,
        "pkn_stable_G_leakoff_unit_fraction": np.nan,
        "pkn_shutin_storage_volume_m3": np.nan,
        "pkn_shutin_leakoff_before_closure_m3": np.nan,
        "pkn_shutin_fluid_efficiency": np.nan,
        "pkn_shutin_leakoff_fraction": np.nan,
        "pkn_shutin_storage_unit_mean_m2": np.nan,
        "pkn_shutin_preclosure_leakoff_unit_mean_m2": np.nan,
        "pkn_shutin_storage_unit_fraction": np.nan,
        "pkn_shutin_preclosure_leakoff_unit_fraction": np.nan,
        "pkn_C_multiplier_to_20pct_shutin_efficiency": np.nan,
        "pkn_C_multiplier_to_10pct_shutin_efficiency": np.nan,
        "pkn_C_multiplier_to_g_function_efficiency": np.nan,
        "pkn_fluid_efficiency_warning": "",
        "pkn_C_stage_units_assumed": "",
        "pkn_tp_seconds": np.nan,
        "pkn_sqrt_tp_seconds": np.nan,
        "legacy_mvp_pkn_fracture_volume_m3": np.nan,
        "legacy_mvp_pkn_half_length_mean_m": np.nan,
        "legacy_mvp_pkn_volume_status": "not_computed",
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
    stress_shadow_alpha: float = 1.0,
    flow_allocation: str = "stress-shadow",
    flow_allocation_exponent: float = 1.0,
    pkn_C_coupling: str = "stage-constant",
    tp_multiplier: float = 1.0,
    effective_volume_factor: float = 1.0,
    fleak_override: float | None = None,
    pkn_H_w_m: float | None = None,
    C_multiplier: float = 1.0,
    stable_min_elapsed_seconds: float = 15.0,
    stable_min_points: int = 8,
    stable_min_r2: float = 0.8,
    stable_window_mode: str = "longest",
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
    cluster_rows: list[dict[str, Any]] = []
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
            stress_shadow_alpha=stress_shadow_alpha,
            flow_allocation=flow_allocation,
            flow_allocation_exponent=flow_allocation_exponent,
            pkn_C_coupling=pkn_C_coupling,
            tp_multiplier=tp_multiplier,
            effective_volume_factor=effective_volume_factor,
            fleak_override=fleak_override,
            pkn_H_w_m=pkn_H_w_m,
            C_multiplier=C_multiplier,
            stable_min_elapsed_seconds=stable_min_elapsed_seconds,
            stable_min_points=stable_min_points,
            stable_min_r2=stable_min_r2,
            stable_window_mode=stable_window_mode,
        )

        stage_cluster_rows = result.pop("_pkn_cluster_audit_rows", [])
        for cr in stage_cluster_rows:
            cluster_rows.append({"stage": stage_num, **cr})

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
                "tp_multiplier_applied": float(tp_multiplier),
                "tp_for_g_seconds": np.nan,
                "effective_volume_factor_applied": float(effective_volume_factor),
                "pkn_fleak_override_applied": float(fleak_override) if fleak_override is not None else np.nan,
                "pkn_H_w_override_applied": float(pkn_H_w_m) if pkn_H_w_m is not None else np.nan,
                "pkn_effective_injected_volume_m3": np.nan,
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

    if cluster_rows:
        cluster_audit = pd.DataFrame(cluster_rows).sort_values(
            ["stage", "stable_row_index", "cluster_index"], ignore_index=True,
        )
    else:
        cluster_audit = pd.DataFrame(
            columns=[
                "stage", "stable_row_index", "cluster_index",
                "eta_i", "xi_i", "P_net_i_mpa", "C_L_i", "C_stage",
                "pkn_C_coupling_method",
                "denominator_i_m3_per_m", "L_i_m", "V_f_i_m3",
                "injected_i_m3", "storage_i_m3",
                "leakoff_before_closure_i_m3", "leakoff_G_i_m3",
                "leakoff_total_i_m3", "balance_residual_i_m3",
                "g_time", "elapsed_seconds",
            ]
        )

    correlation: pd.DataFrame | None = None
    if observations is not None and len(summary) > 0:
        correlation = build_observation_correlation_table(summary, observations)

    return {
        "summary": summary,
        "correlation": correlation,
        "cluster_audit": cluster_audit,
        "stage_count": len(summary),
    }


def write_closure_batch_outputs(
    result: dict[str, Any],
    *,
    output_path: str | Path,
    correlation_output_path: str | Path | None = None,
    cluster_output_path: str | Path | None = None,
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

    if cluster_output_path is not None:
        cluster_out = Path(cluster_output_path)
        if not cluster_out.parent.exists():
            raise ValueError(f"cluster output parent directory does not exist: {cluster_out.parent}")
        cluster_audit: pd.DataFrame | None = result.get("cluster_audit")
        if cluster_audit is not None:
            cluster_audit.to_csv(cluster_out, index=False)
            paths["cluster_output"] = cluster_out

    return paths
