"""Physical PKN parameter grid search (Phase 5F).

This module orchestrates a coarse grid search over the closure / volume / PKN
parameter space and records per-case statistics + correlations against external
observations (microseismic, EM area).

Important non-goals
-------------------
* This is a *sensitivity* / *audit* tool, not an inversion.
* No combination found here is a final physical interpretation. A high Pearson
  in one corner of the grid does not validate the model.
* Negative correlations and physically implausible cases are intentionally
  preserved in the output. The caller is expected to read the full table, not
  just the top candidate.

Conventions
-----------
* I_F and H_w are fixed at the project-required values (PHYSICAL_PKN_IF,
  PHYSICAL_PKN_HW_M) and are NOT search axes.
* Perforation friction can be supplied four ways:
    - none: ΔP_perf = 0 everywhere.
    - constant: ΔP_perf = a constant from the grid (legacy sensitivity).
    - orifice: ΔP_perf computed via Bernoulli/orifice from the manifest's
      max_sustained_rate, fluid density, perforation diameter / count / Cd.
      The mean across stages is passed as a scalar correction to net pressure;
      min/mean/max are recorded as audit fields.
    - zero-after-shutin: ΔP_perf applied to net pressure = 0 (because rate=0
      after shut-in), but the pumping-period orifice value is computed for
      audit. This is the physically defensible default for post-shut-in
      pressure correction.
* Wellbore storage volume is V_wb = C_wb * max(P_shutin - P_closure, 0). Only
  C_wb is varied here; we do not synthesize compressibility data.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

import numpy as np
import pandas as pd

from .closure import run_closure_batch

ALLOWED_PERF_MODES = ("none", "constant", "orifice", "zero-after-shutin")
ALLOWED_COUPLING = ("stage-constant", "shadow-scaled")
ALLOWED_FLOW_ALLOCATION = ("stress-shadow", "uniform")
ALLOWED_WINDOW_MODES = ("longest", "best-r2", "early-best")

# Targets used for correlation reporting. Built from observation column names
# the user supplies (typically microseismic_affected_volume,
# electromagnetic_affected_area_with_loss). Aliases below are used to choose
# which targets count as "microseismic" vs "EM" when reporting bests.
MICROSEISMIC_KEYWORDS = ("microseismic", "micro_seismic", "ms_")
EM_KEYWORDS = ("electromagnetic", "em_")

# Metric classes scanned per case for positive/robust positive candidates.
# Keep ordering stable so columns line up across CSVs.
METRIC_CLASSES = (
    "storage",          # pkn_fracture_volume_m3 / pkn_shutin_storage_volume_m3
    "leakoff_proxy",    # pkn_leakoff_volume_m3 / pkn_shutin_leakoff_before_closure_m3
    "nonstorage",       # pkn_nonstorage_volume_m3
    "raw_volume",       # raw_injected_volume_m3
    "effective_volume",  # effective_injected_volume_m3
    "legacy_mvp",       # legacy_mvp_pkn_fracture_volume_m3
)

# Metric column per class. Order matters: first match wins.
METRIC_COLUMNS: dict[str, tuple[str, ...]] = {
    "storage": (
        "pkn_fracture_volume_m3",
        "pkn_shutin_storage_volume_m3",
    ),
    "leakoff_proxy": (
        "pkn_leakoff_volume_m3",
        "pkn_shutin_leakoff_before_closure_m3",
    ),
    "nonstorage": (
        "pkn_nonstorage_volume_m3",
    ),
    "raw_volume": (
        "raw_injected_volume_m3",
    ),
    "effective_volume": (
        "effective_injected_volume_m3",
        "pkn_effective_injected_volume_m3",
    ),
    "legacy_mvp": (
        "legacy_mvp_pkn_fracture_volume_m3",
    ),
}


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def parse_float_grid(value: str) -> list[float]:
    """Parse a comma-separated float grid, preserving order and uniqueness."""
    if value is None:
        raise ValueError("float grid value is None")
    items = [v.strip() for v in value.split(",") if v.strip() != ""]
    if not items:
        raise ValueError("float grid is empty")
    out: list[float] = []
    seen: set[float] = set()
    for s in items:
        try:
            f = float(s)
        except ValueError as exc:
            raise ValueError(f"invalid float in grid: {s!r}") from exc
        if not np.isfinite(f):
            raise ValueError(f"non-finite float in grid: {s!r}")
        if f in seen:
            continue
        seen.add(f)
        out.append(f)
    return out


def parse_int_grid(value: str) -> list[int]:
    if value is None:
        raise ValueError("int grid value is None")
    items = [v.strip() for v in value.split(",") if v.strip() != ""]
    if not items:
        raise ValueError("int grid is empty")
    out: list[int] = []
    seen: set[int] = set()
    for s in items:
        try:
            i = int(s)
        except ValueError as exc:
            raise ValueError(f"invalid int in grid: {s!r}") from exc
        if i in seen:
            continue
        seen.add(i)
        out.append(i)
    return out


def parse_choice_grid(value: str, allowed: Sequence[str]) -> list[str]:
    if value is None:
        raise ValueError("choice grid value is None")
    items = [v.strip() for v in value.split(",") if v.strip() != ""]
    if not items:
        raise ValueError("choice grid is empty")
    allowed_set = set(allowed)
    out: list[str] = []
    seen: set[str] = set()
    for s in items:
        if s not in allowed_set:
            raise ValueError(
                f"unknown value {s!r} (allowed: {sorted(allowed_set)})"
            )
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


# ---------------------------------------------------------------------------
# Perforation friction
# ---------------------------------------------------------------------------


def perforation_friction_mpa(
    *,
    rate_m3_per_s: float,
    density_kg_m3: float,
    perforation_diameter_m: float,
    perforations_per_cluster: int,
    discharge_coefficient: float,
    flow_fraction: float = 1.0,
) -> float:
    """ΔP_perf = 0.5 ρ (q_i / (Cd · A_total))², returned in MPa.

    q_i = rate_m3_per_s * flow_fraction
    A_total = perforations_per_cluster * π d² / 4

    Raises ValueError for any invalid input. Returns 0 for q_i == 0.
    """
    if not np.isfinite(rate_m3_per_s) or rate_m3_per_s < 0:
        raise ValueError(f"rate_m3_per_s must be finite and >= 0, got {rate_m3_per_s}")
    if not np.isfinite(density_kg_m3) or density_kg_m3 <= 0:
        raise ValueError(f"density_kg_m3 must be finite and > 0, got {density_kg_m3}")
    if not np.isfinite(perforation_diameter_m) or perforation_diameter_m <= 0:
        raise ValueError(
            f"perforation_diameter_m must be finite and > 0, got {perforation_diameter_m}"
        )
    if perforations_per_cluster <= 0:
        raise ValueError(
            f"perforations_per_cluster must be > 0, got {perforations_per_cluster}"
        )
    if not np.isfinite(discharge_coefficient) or discharge_coefficient <= 0:
        raise ValueError(
            f"discharge_coefficient must be finite and > 0, got {discharge_coefficient}"
        )
    if not np.isfinite(flow_fraction) or flow_fraction < 0:
        raise ValueError(f"flow_fraction must be finite and >= 0, got {flow_fraction}")

    q_i = rate_m3_per_s * flow_fraction
    if q_i == 0.0:
        return 0.0

    a_perf = math.pi * perforation_diameter_m ** 2 / 4.0
    a_total = perforations_per_cluster * a_perf
    dp_pa = 0.5 * density_kg_m3 * (q_i / (discharge_coefficient * a_total)) ** 2
    return dp_pa / 1.0e6


def compute_orifice_stage_pressures(
    *,
    manifest: pd.DataFrame,
    stage_params: pd.DataFrame,
    rate_time_unit: str,
    perforation_diameter_mm: float,
    perforations_per_cluster: int,
    discharge_coefficient: float,
    fluid_density_kg_m3: float,
) -> dict[str, float | dict[int, float]]:
    """Compute orifice ΔP per stage using max_sustained_rate from manifest.

    Flow fraction is taken as uniform 1/num_clusters per cluster (single-cluster
    friction). Returned mean/min/max are across stages; per_stage maps stage→ΔP.

    The single scalar mean is the value the orchestrator passes to
    run_closure_batch as a stage-uniform pressure correction. Per-stage values
    are not yet propagated into closure-batch (it accepts one scalar).
    """
    if rate_time_unit not in ("second", "minute"):
        raise ValueError(f"rate_time_unit must be second/minute, got {rate_time_unit}")
    if perforation_diameter_mm <= 0:
        raise ValueError("perforation_diameter_mm must be > 0")

    diameter_m = perforation_diameter_mm * 1.0e-3
    per_stage: dict[int, float] = {}
    stage_to_clusters = {}
    for _, row in stage_params.iterrows():
        try:
            stage_to_clusters[int(row["stage"])] = int(row.get("num_clusters", 1) or 1)
        except (ValueError, TypeError):
            continue

    for _, mrow in manifest.iterrows():
        try:
            stage_num = int(mrow["stage"])
            msr = float(mrow["max_sustained_rate"])
        except (KeyError, ValueError, TypeError):
            continue
        if rate_time_unit == "minute":
            q_total = msr / 60.0
        else:
            q_total = msr
        if not np.isfinite(q_total) or q_total <= 0:
            per_stage[stage_num] = 0.0
            continue
        n_cl = max(1, int(stage_to_clusters.get(stage_num, 1) or 1))
        flow_fraction = 1.0 / n_cl
        try:
            dp = perforation_friction_mpa(
                rate_m3_per_s=q_total,
                density_kg_m3=fluid_density_kg_m3,
                perforation_diameter_m=diameter_m,
                perforations_per_cluster=perforations_per_cluster,
                discharge_coefficient=discharge_coefficient,
                flow_fraction=flow_fraction,
            )
        except ValueError:
            dp = float("nan")
        per_stage[stage_num] = dp

    finite_vals = [v for v in per_stage.values() if np.isfinite(v)]
    if not finite_vals:
        return {"mean": float("nan"), "min": float("nan"), "max": float("nan"), "per_stage": per_stage}
    return {
        "mean": float(np.mean(finite_vals)),
        "min": float(np.min(finite_vals)),
        "max": float(np.max(finite_vals)),
        "per_stage": per_stage,
    }


# ---------------------------------------------------------------------------
# Grid case enumeration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GridCase:
    case_id: int
    closure_min_elapsed_seconds: float
    pkn_C_coupling: str
    flow_allocation: str
    flow_allocation_exponent: float
    stress_shadow_alpha: float
    fleak: float
    C_multiplier: float
    effective_volume_factor: float
    wellbore_storage_coeff_m3_per_mpa: float
    perf_friction_mode: str
    perf_friction_constant_mpa: float  # used only when mode=constant
    perforation_diameter_mm: float     # used for orifice / zero-after-shutin
    perforations_per_cluster: int
    perforation_Cd: float
    fluid_density_kg_m3: float
    stable_min_r2: float
    stable_min_points: int
    stable_window_mode: str
    tp_multiplier: float


def count_grid_cases(
    *,
    closure_min_elapsed_seconds: Sequence[float],
    pkn_C_coupling: Sequence[str],
    flow_allocation: Sequence[str],
    flow_allocation_exponent: Sequence[float],
    stress_shadow_alpha: Sequence[float],
    fleak: Sequence[float],
    C_multiplier: Sequence[float],
    effective_volume_factor: Sequence[float],
    wellbore_storage_coeff_m3_per_mpa: Sequence[float],
    perf_friction_mode: Sequence[str],
    perf_friction_constant_mpa: Sequence[float],
    perforation_diameter_mm: Sequence[float],
    perforations_per_cluster: Sequence[int],
    perforation_Cd: Sequence[float],
    fluid_density_kg_m3: Sequence[float],
    stable_min_r2: Sequence[float],
    stable_min_points: Sequence[int],
    stable_window_mode: Sequence[str],
    tp_multiplier: Sequence[float],
) -> int:
    """Total Cartesian product size with mode-aware perforation expansion."""
    perf_count = 0
    for mode in perf_friction_mode:
        if mode == "none":
            perf_count += 1
        elif mode == "constant":
            perf_count += max(1, len(perf_friction_constant_mpa))
        else:  # orifice / zero-after-shutin
            perf_count += max(1, len(perforation_diameter_mm)) \
                * max(1, len(perforations_per_cluster)) \
                * max(1, len(perforation_Cd)) \
                * max(1, len(fluid_density_kg_m3))
    return (
        max(1, len(closure_min_elapsed_seconds))
        * max(1, len(pkn_C_coupling))
        * max(1, len(flow_allocation))
        * max(1, len(flow_allocation_exponent))
        * max(1, len(stress_shadow_alpha))
        * max(1, len(fleak))
        * max(1, len(C_multiplier))
        * max(1, len(effective_volume_factor))
        * max(1, len(wellbore_storage_coeff_m3_per_mpa))
        * perf_count
        * max(1, len(stable_min_r2))
        * max(1, len(stable_min_points))
        * max(1, len(stable_window_mode))
        * max(1, len(tp_multiplier))
    )


def enumerate_grid_cases(
    *,
    closure_min_elapsed_seconds: Sequence[float],
    pkn_C_coupling: Sequence[str],
    flow_allocation: Sequence[str],
    flow_allocation_exponent: Sequence[float],
    stress_shadow_alpha: Sequence[float],
    fleak: Sequence[float],
    C_multiplier: Sequence[float],
    effective_volume_factor: Sequence[float],
    wellbore_storage_coeff_m3_per_mpa: Sequence[float],
    perf_friction_mode: Sequence[str],
    perf_friction_constant_mpa: Sequence[float],
    perforation_diameter_mm: Sequence[float],
    perforations_per_cluster: Sequence[int],
    perforation_Cd: Sequence[float],
    fluid_density_kg_m3: Sequence[float],
    stable_min_r2: Sequence[float],
    stable_min_points: Sequence[int],
    stable_window_mode: Sequence[str],
    tp_multiplier: Sequence[float],
) -> Iterator[GridCase]:
    """Yield GridCase objects with mode-aware perforation expansion."""
    case_id = 0
    for cme in closure_min_elapsed_seconds:
        for cc in pkn_C_coupling:
            for fa in flow_allocation:
                for fae in flow_allocation_exponent:
                    for ssa in stress_shadow_alpha:
                        for fl in fleak:
                            for cm in C_multiplier:
                                for evf in effective_volume_factor:
                                    for wbs in wellbore_storage_coeff_m3_per_mpa:
                                        for mode in perf_friction_mode:
                                            if mode == "none":
                                                perf_iter: list[
                                                    tuple[float, float, int, float, float]
                                                ] = [(0.0, float("nan"), 0, float("nan"), float("nan"))]
                                            elif mode == "constant":
                                                perf_iter = [
                                                    (p, float("nan"), 0, float("nan"), float("nan"))
                                                    for p in perf_friction_constant_mpa
                                                ]
                                            else:
                                                perf_iter = [
                                                    (float("nan"), d, n, cd, rho)
                                                    for d in perforation_diameter_mm
                                                    for n in perforations_per_cluster
                                                    for cd in perforation_Cd
                                                    for rho in fluid_density_kg_m3
                                                ]
                                            for (pc, pd_mm, pn, pcd, prho) in perf_iter:
                                                for smr in stable_min_r2:
                                                    for smp in stable_min_points:
                                                        for swm in stable_window_mode:
                                                            for tpm in tp_multiplier:
                                                                yield GridCase(
                                                                    case_id=case_id,
                                                                    closure_min_elapsed_seconds=float(cme),
                                                                    pkn_C_coupling=str(cc),
                                                                    flow_allocation=str(fa),
                                                                    flow_allocation_exponent=float(fae),
                                                                    stress_shadow_alpha=float(ssa),
                                                                    fleak=float(fl),
                                                                    C_multiplier=float(cm),
                                                                    effective_volume_factor=float(evf),
                                                                    wellbore_storage_coeff_m3_per_mpa=float(wbs),
                                                                    perf_friction_mode=str(mode),
                                                                    perf_friction_constant_mpa=float(pc),
                                                                    perforation_diameter_mm=float(pd_mm),
                                                                    perforations_per_cluster=int(pn),
                                                                    perforation_Cd=float(pcd),
                                                                    fluid_density_kg_m3=float(prho),
                                                                    stable_min_r2=float(smr),
                                                                    stable_min_points=int(smp),
                                                                    stable_window_mode=str(swm),
                                                                    tp_multiplier=float(tpm),
                                                                )
                                                                case_id += 1


# ---------------------------------------------------------------------------
# Plausibility + candidate flagging
# ---------------------------------------------------------------------------


@dataclass
class PhysicalPlausibilityCriteria:
    min_n: int = 20
    max_placeholder_count: int = 2
    min_median_efficiency: float = 0.10
    max_median_efficiency: float = 0.40
    max_efficiency_below_5pct_count: int = 5
    min_pkn_ok_count: int = 25
    min_median_stable_r2: float = 0.5
    min_C_multiplier: float = 0.1
    max_C_multiplier: float = 2.0


def physical_plausibility_pass(
    stats: dict[str, Any],
    criteria: PhysicalPlausibilityCriteria,
) -> tuple[bool, list[str]]:
    """Return (pass, reasons-failed). Empty reasons => pass."""
    reasons: list[str] = []
    n = stats.get("n_stages_in_correlation", 0)
    if n < criteria.min_n:
        reasons.append(f"n_lt_{criteria.min_n}")
    if stats.get("placeholder_count", 0) > criteria.max_placeholder_count:
        reasons.append(f"placeholder_count_gt_{criteria.max_placeholder_count}")
    med_eff = stats.get("median_shutin_fluid_efficiency", float("nan"))
    if not np.isfinite(med_eff):
        reasons.append("median_efficiency_not_finite")
    else:
        if med_eff < criteria.min_median_efficiency:
            reasons.append("median_efficiency_below_min")
        if med_eff > criteria.max_median_efficiency:
            reasons.append("median_efficiency_above_max")
    if stats.get("count_efficiency_below_5pct", 0) > criteria.max_efficiency_below_5pct_count:
        reasons.append("too_many_below_5pct")
    if stats.get("pkn_volume_ok_count", 0) < criteria.min_pkn_ok_count:
        reasons.append("pkn_ok_count_below_min")
    med_r2 = stats.get("median_stable_dP_dG_r2", float("nan"))
    if not np.isfinite(med_r2) or med_r2 < criteria.min_median_stable_r2:
        reasons.append("median_stable_r2_below_min")
    cmult = stats.get("C_multiplier_applied", 1.0)
    if not np.isfinite(cmult) or cmult < criteria.min_C_multiplier or cmult > criteria.max_C_multiplier:
        reasons.append("C_multiplier_out_of_range")
    return (len(reasons) == 0, reasons)


def is_positive_candidate(pearson_r: float | None, n: int, min_n: int = 20) -> bool:
    if pearson_r is None or not np.isfinite(pearson_r):
        return False
    return pearson_r > 0.3 and n >= min_n


def is_robust_positive_candidate(
    pearson_r: float | None,
    spearman_r: float | None,
    n: int,
    physical_pass: bool,
    *,
    min_n: int = 20,
    min_pearson: float = 0.3,
    min_spearman: float = 0.2,
) -> bool:
    if pearson_r is None or not np.isfinite(pearson_r):
        return False
    if spearman_r is None or not np.isfinite(spearman_r):
        return False
    if n < min_n:
        return False
    return pearson_r > min_pearson and spearman_r > min_spearman and physical_pass


# ---------------------------------------------------------------------------
# Per-case evaluation
# ---------------------------------------------------------------------------


def _pearson_spearman(x: np.ndarray, y: np.ndarray) -> tuple[float, float, int]:
    """Return (pearson_r, spearman_r, n) on pairwise-finite entries."""
    mask = np.isfinite(x) & np.isfinite(y)
    n = int(mask.sum())
    if n < 3:
        return float("nan"), float("nan"), n
    x_clean = x[mask]
    y_clean = y[mask]
    if np.std(x_clean) == 0 or np.std(y_clean) == 0:
        return float("nan"), float("nan"), n
    pearson = float(np.corrcoef(x_clean, y_clean)[0, 1])
    # Manual Spearman via rank-pearson to avoid scipy dependency
    rx = pd.Series(x_clean).rank().to_numpy()
    ry = pd.Series(y_clean).rank().to_numpy()
    if np.std(rx) == 0 or np.std(ry) == 0:
        spearman = float("nan")
    else:
        spearman = float(np.corrcoef(rx, ry)[0, 1])
    return pearson, spearman, n


def _classify_target(name: str) -> str:
    n = name.lower()
    if any(k in n for k in MICROSEISMIC_KEYWORDS):
        return "microseismic"
    if any(k in n for k in EM_KEYWORDS):
        return "EM"
    return "other"


def evaluate_case_correlations(
    summary: pd.DataFrame,
    observation_columns: Sequence[str],
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    """Return (efficiency_stats, list_of_metric_target_correlation_rows).

    Metric-target row schema:
      metric_class, metric_column, target_column, target_class (microseismic/EM/other),
      pearson_r, spearman_r, n
    """
    pkn_ok_count = 0
    if "pkn_volume_status" in summary.columns:
        pkn_ok_count = int((summary["pkn_volume_status"] == "ok").sum())

    eff_col = "pkn_shutin_fluid_efficiency"
    if eff_col in summary.columns:
        eff = summary[eff_col].astype(float)
        median_eff = float(np.nanmedian(eff)) if eff.notna().any() else float("nan")
        min_eff = float(np.nanmin(eff)) if eff.notna().any() else float("nan")
        max_eff = float(np.nanmax(eff)) if eff.notna().any() else float("nan")
        below_5 = int((eff < 0.05).sum())
        in_band = int(((eff >= 0.10) & (eff <= 0.40)).sum())
    else:
        median_eff = min_eff = max_eff = float("nan")
        below_5 = 0
        in_band = 0

    if "stable_dP_dG_r2" in summary.columns:
        median_r2 = float(np.nanmedian(summary["stable_dP_dG_r2"].astype(float)))
    else:
        median_r2 = float("nan")

    if "pkn_C_multiplier_to_20pct_shutin_efficiency" in summary.columns:
        median_c_mult_to_20 = float(np.nanmedian(
            summary["pkn_C_multiplier_to_20pct_shutin_efficiency"].astype(float)
        ))
    else:
        median_c_mult_to_20 = float("nan")

    placeholder_count = 0
    if "missing_estimate_reason" in summary.columns:
        placeholder_count = int(
            (summary["missing_estimate_reason"] != "").sum()
        )

    failed_count = 0
    if "pkn_volume_status" in summary.columns:
        failed_count = int((summary["pkn_volume_status"] == "failed").sum())

    eff_stats: dict[str, float] = {
        "median_shutin_fluid_efficiency": median_eff,
        "min_shutin_fluid_efficiency": min_eff,
        "max_shutin_fluid_efficiency": max_eff,
        "count_efficiency_below_5pct": below_5,
        "count_efficiency_in_band_10_40pct": in_band,
        "median_stable_dP_dG_r2": median_r2,
        "median_C_multiplier_to_20pct": median_c_mult_to_20,
        "placeholder_count": placeholder_count,
        "pkn_volume_ok_count": pkn_ok_count,
        "pkn_volume_failed_count": failed_count,
    }

    # Build correlations metric × target
    corr_rows: list[dict[str, Any]] = []
    for cls in METRIC_CLASSES:
        for col in METRIC_COLUMNS.get(cls, ()):
            if col not in summary.columns:
                continue
            metric_vals = summary[col].astype(float).to_numpy()
            for tgt in observation_columns:
                if tgt not in summary.columns:
                    continue
                tgt_vals = summary[tgt].astype(float).to_numpy()
                pearson, spearman, n = _pearson_spearman(metric_vals, tgt_vals)
                corr_rows.append({
                    "metric_class": cls,
                    "metric_column": col,
                    "target_column": tgt,
                    "target_class": _classify_target(tgt),
                    "pearson_r": pearson,
                    "spearman_r": spearman,
                    "n": n,
                })
            # only take the first matching column per class (avoid double-counting)
            break

    eff_stats["n_stages_in_correlation"] = int(len(summary))
    return eff_stats, corr_rows


def _flatten_case_row(
    case: GridCase,
    eff_stats: dict[str, Any],
    corr_rows: list[dict[str, Any]],
    physical_pass: bool,
    physical_fail_reasons: list[str],
    perf_audit: dict[str, float],
    elapsed_seconds: float,
) -> dict[str, Any]:
    """Flatten case + stats + correlations into a single grid_cases row.

    Correlations are pivoted to columns named:
      {metric_class}_vs_{target_short}_pearson / _spearman / _n
    where target_short is microseismic / EM / target name fallback.
    """
    row: dict[str, Any] = asdict(case)
    row["n_stages_in_correlation"] = eff_stats.get("n_stages_in_correlation")
    for k, v in eff_stats.items():
        row.setdefault(k, v)
    row["physical_plausibility_pass"] = bool(physical_pass)
    row["physical_plausibility_reasons"] = ";".join(physical_fail_reasons)
    row["perf_friction_orifice_mean_mpa"] = perf_audit.get("mean", float("nan"))
    row["perf_friction_orifice_min_mpa"] = perf_audit.get("min", float("nan"))
    row["perf_friction_orifice_max_mpa"] = perf_audit.get("max", float("nan"))
    row["perf_friction_applied_mpa"] = perf_audit.get("applied", float("nan"))
    row["case_runtime_seconds"] = float(elapsed_seconds)

    for cr in corr_rows:
        cls = cr["metric_class"]
        tcls = cr["target_class"]
        suffix = tcls if tcls != "other" else cr["target_column"]
        base = f"{cls}_vs_{suffix}"
        row[f"{base}_pearson"] = cr["pearson_r"]
        row[f"{base}_spearman"] = cr["spearman_r"]
        row[f"{base}_n"] = cr["n"]
    return row


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


@dataclass
class GridSearchConfig:
    stage_params_path: Path
    well_root: Path
    manifest_path: Path
    observations_path: Path
    output_dir: Path
    volume_column: str = "total_volume"
    rate_time_unit: str = "minute"
    min_rate: float = 10.0
    g_time_m: float = 0.8
    pressure_source: str = "estimated-bottomhole"
    method_preference: str = "barree-then-mcclure"
    elapsed_duplicate_policy: str = "keep-last"
    well: str | None = None


def _build_perf_audit(
    case: GridCase,
    orifice_cache: dict[tuple, dict[str, float | dict[int, float]]],
    config: GridSearchConfig,
    manifest: pd.DataFrame,
    stage_params: pd.DataFrame,
) -> tuple[float, dict[str, float]]:
    """Resolve perforation_friction_mpa scalar + audit dict for this case.

    Returns (applied_mpa, audit_dict).
    """
    if case.perf_friction_mode == "none":
        return 0.0, {"mean": float("nan"), "min": float("nan"), "max": float("nan"), "applied": 0.0}
    if case.perf_friction_mode == "constant":
        applied = case.perf_friction_constant_mpa
        return applied, {
            "mean": float("nan"),
            "min": float("nan"),
            "max": float("nan"),
            "applied": float(applied),
        }
    # orifice / zero-after-shutin
    key = (
        case.perforation_diameter_mm,
        case.perforations_per_cluster,
        case.perforation_Cd,
        case.fluid_density_kg_m3,
    )
    if key not in orifice_cache:
        orifice_cache[key] = compute_orifice_stage_pressures(
            manifest=manifest,
            stage_params=stage_params,
            rate_time_unit=config.rate_time_unit,
            perforation_diameter_mm=case.perforation_diameter_mm,
            perforations_per_cluster=case.perforations_per_cluster,
            discharge_coefficient=case.perforation_Cd,
            fluid_density_kg_m3=case.fluid_density_kg_m3,
        )
    audit = orifice_cache[key]
    if case.perf_friction_mode == "orifice":
        applied = float(audit["mean"]) if np.isfinite(audit["mean"]) else 0.0
    else:  # zero-after-shutin
        applied = 0.0
    return applied, {
        "mean": float(audit["mean"]),
        "min": float(audit["min"]),
        "max": float(audit["max"]),
        "applied": float(applied),
    }


def _run_one_case(
    case: GridCase,
    config: GridSearchConfig,
    orifice_cache: dict[tuple, dict[str, float | dict[int, float]]],
    manifest: pd.DataFrame,
    stage_params: pd.DataFrame,
    observation_columns: Sequence[str],
    criteria: PhysicalPlausibilityCriteria,
) -> tuple[dict[str, Any], bool]:
    """Run a single grid case; return (flattened row, ok flag).

    ok=False means the case failed before producing summary (e.g., upstream
    exception). The row still contains the case params and the failure reason
    so the case is preserved in grid_failed_cases.csv.
    """
    start = time.perf_counter()
    perf_applied, perf_audit = _build_perf_audit(
        case=case,
        orifice_cache=orifice_cache,
        config=config,
        manifest=manifest,
        stage_params=stage_params,
    )
    try:
        result = run_closure_batch(
            stage_params_path=config.stage_params_path,
            well_root=config.well_root,
            manifest_path=config.manifest_path,
            observations_path=config.observations_path,
            volume_column=config.volume_column,
            rate_time_unit=config.rate_time_unit,
            min_rate=config.min_rate,
            g_time_m=config.g_time_m,
            elapsed_duplicate_policy=config.elapsed_duplicate_policy,
            closure_min_elapsed_seconds=case.closure_min_elapsed_seconds,
            pressure_source=config.pressure_source,
            perforation_friction_mpa=perf_applied,
            wellbore_storage_coeff_m3_per_mpa=case.wellbore_storage_coeff_m3_per_mpa,
            method_preference=config.method_preference,
            stress_shadow_alpha=case.stress_shadow_alpha,
            flow_allocation=case.flow_allocation,
            flow_allocation_exponent=case.flow_allocation_exponent,
            pkn_C_coupling=case.pkn_C_coupling,
            tp_multiplier=case.tp_multiplier,
            effective_volume_factor=case.effective_volume_factor,
            fleak_override=case.fleak,
            C_multiplier=case.C_multiplier,
            stable_min_elapsed_seconds=case.closure_min_elapsed_seconds,
            stable_min_points=case.stable_min_points,
            stable_min_r2=case.stable_min_r2,
            stable_window_mode=case.stable_window_mode,
            well=config.well,
        )
    except Exception as exc:  # noqa: BLE001
        elapsed = time.perf_counter() - start
        row = asdict(case)
        row.update({
            "n_stages_in_correlation": 0,
            "physical_plausibility_pass": False,
            "physical_plausibility_reasons": f"exception:{type(exc).__name__}",
            "perf_friction_applied_mpa": perf_applied,
            "case_runtime_seconds": float(elapsed),
            "error_message": str(exc),
        })
        return row, False

    summary: pd.DataFrame = result["summary"]
    eff_stats, corr_rows = evaluate_case_correlations(summary, observation_columns)
    stats_for_plausibility = dict(eff_stats)
    stats_for_plausibility["C_multiplier_applied"] = case.C_multiplier
    physical_pass, fail_reasons = physical_plausibility_pass(stats_for_plausibility, criteria)
    elapsed = time.perf_counter() - start
    row = _flatten_case_row(
        case=case,
        eff_stats=eff_stats,
        corr_rows=corr_rows,
        physical_pass=physical_pass,
        physical_fail_reasons=fail_reasons,
        perf_audit=perf_audit,
        elapsed_seconds=elapsed,
    )
    row["error_message"] = ""
    return row, True


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------


def split_outputs(
    cases_df: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """Build the family of output DataFrames from the master grid_cases table."""
    out: dict[str, pd.DataFrame] = {"grid_cases": cases_df}

    # Identify per-target metric pearson columns
    pearson_cols = [c for c in cases_df.columns if c.endswith("_pearson")]
    spearman_cols = [c for c in cases_df.columns if c.endswith("_spearman")]
    n_cols = [c for c in cases_df.columns if c.endswith("_n") and not c.endswith("_in_n")]

    # Long-form melt for filtering candidates
    records: list[dict[str, Any]] = []
    for _, row in cases_df.iterrows():
        case_id = row["case_id"]
        physical_pass = bool(row.get("physical_plausibility_pass", False))
        for pcol in pearson_cols:
            base = pcol[:-len("_pearson")]
            scol = base + "_spearman"
            ncol = base + "_n"
            pearson = row.get(pcol, float("nan"))
            spearman = row.get(scol, float("nan"))
            n_val = row.get(ncol, 0)
            n_int = int(n_val) if n_val is not None and not pd.isna(n_val) else 0
            if pd.isna(pearson):
                continue
            records.append({
                "case_id": case_id,
                "metric_vs_target": base,
                "pearson_r": float(pearson),
                "spearman_r": float(spearman) if not pd.isna(spearman) else float("nan"),
                "n": n_int,
                "physical_plausibility_pass": physical_pass,
            })
    long_df = pd.DataFrame.from_records(records)

    if not long_df.empty:
        pos_mask = long_df.apply(
            lambda r: is_positive_candidate(r["pearson_r"], int(r["n"])),
            axis=1,
        )
        positives = long_df[pos_mask].copy()
        positives = positives.sort_values("pearson_r", ascending=False, ignore_index=True)

        robust_mask = long_df.apply(
            lambda r: is_robust_positive_candidate(
                r["pearson_r"], r["spearman_r"], int(r["n"]),
                bool(r["physical_plausibility_pass"]),
            ),
            axis=1,
        )
        robust = long_df[robust_mask].copy()
        robust = robust.sort_values("pearson_r", ascending=False, ignore_index=True)

        # best per (metric_vs_target, physical_pass) and overall best
        best_rows: list[dict[str, Any]] = []
        for (target, pass_flag), grp in long_df.groupby(
            ["metric_vs_target", "physical_plausibility_pass"]
        ):
            best = grp.sort_values("pearson_r", ascending=False).head(1)
            for _, r in best.iterrows():
                best_rows.append({
                    "metric_vs_target": target,
                    "physical_plausibility_pass": bool(pass_flag),
                    "case_id": int(r["case_id"]),
                    "pearson_r": float(r["pearson_r"]),
                    "spearman_r": float(r["spearman_r"]),
                    "n": int(r["n"]),
                })
        best_df = pd.DataFrame.from_records(best_rows).sort_values(
            ["metric_vs_target", "physical_plausibility_pass"], ascending=[True, False],
            ignore_index=True,
        )
    else:
        positives = pd.DataFrame(columns=["case_id", "metric_vs_target", "pearson_r", "spearman_r", "n", "physical_plausibility_pass"])
        robust = positives.copy()
        best_df = pd.DataFrame(columns=["metric_vs_target", "physical_plausibility_pass", "case_id", "pearson_r", "spearman_r", "n"])

    out["grid_positive_candidates"] = positives
    out["grid_robust_positive_candidates"] = robust
    out["grid_best_by_target"] = best_df
    return out


def compute_parameter_importance(
    cases_df: pd.DataFrame,
    *,
    parameters: Sequence[str] = (
        "closure_min_elapsed_seconds",
        "pkn_C_coupling",
        "flow_allocation",
        "flow_allocation_exponent",
        "stress_shadow_alpha",
        "fleak",
        "C_multiplier",
        "effective_volume_factor",
        "wellbore_storage_coeff_m3_per_mpa",
        "perf_friction_mode",
        "stable_min_r2",
        "stable_min_points",
        "stable_window_mode",
        "tp_multiplier",
    ),
) -> pd.DataFrame:
    """For each (parameter, value), aggregate case_count + mean of key metrics."""
    if cases_df.empty:
        return pd.DataFrame(columns=["parameter", "value", "case_count"])

    # Pick a representative set of correlation columns (top by mean abs Pearson)
    pearson_cols = [c for c in cases_df.columns if c.endswith("_pearson")]
    summary_cols = list(pearson_cols)
    summary_cols += [c for c in ("median_shutin_fluid_efficiency", "median_stable_dP_dG_r2") if c in cases_df.columns]
    rows: list[dict[str, Any]] = []
    for p in parameters:
        if p not in cases_df.columns:
            continue
        grouped = cases_df.groupby(p, dropna=False)
        for value, grp in grouped:
            entry: dict[str, Any] = {
                "parameter": p,
                "value": value,
                "case_count": int(len(grp)),
                "physical_pass_rate": float(
                    grp.get("physical_plausibility_pass", pd.Series([False] * len(grp))).mean()
                ),
            }
            for col in summary_cols:
                if col in grp.columns:
                    entry[f"mean_{col}"] = float(grp[col].astype(float).mean(skipna=True))
            rows.append(entry)
    return pd.DataFrame.from_records(rows)


def write_outputs(
    output_dir: Path,
    cases_df: pd.DataFrame,
    failed_df: pd.DataFrame,
) -> dict[str, Path]:
    """Write the family of CSV outputs to output_dir. Returns paths."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}

    cases_path = output_dir / "grid_cases.csv"
    cases_df.to_csv(cases_path, index=False)
    paths["grid_cases"] = cases_path

    outputs = split_outputs(cases_df)
    pos_path = output_dir / "grid_positive_candidates.csv"
    outputs["grid_positive_candidates"].to_csv(pos_path, index=False)
    paths["grid_positive_candidates"] = pos_path

    robust_path = output_dir / "grid_robust_positive_candidates.csv"
    outputs["grid_robust_positive_candidates"].to_csv(robust_path, index=False)
    paths["grid_robust_positive_candidates"] = robust_path

    best_path = output_dir / "grid_best_by_target.csv"
    outputs["grid_best_by_target"].to_csv(best_path, index=False)
    paths["grid_best_by_target"] = best_path

    importance = compute_parameter_importance(cases_df)
    importance_path = output_dir / "grid_parameter_importance.csv"
    importance.to_csv(importance_path, index=False)
    paths["grid_parameter_importance"] = importance_path

    failed_path = output_dir / "grid_failed_cases.csv"
    failed_df.to_csv(failed_path, index=False)
    paths["grid_failed_cases"] = failed_path
    return paths


# ---------------------------------------------------------------------------
# Top-level entrypoint
# ---------------------------------------------------------------------------


def run_grid_search(
    *,
    config: GridSearchConfig,
    grid_kwargs: dict[str, Any],
    max_cases: int,
    criteria: PhysicalPlausibilityCriteria | None = None,
    progress_callback=None,
) -> dict[str, Any]:
    """Run the full grid search.

    Errors with a clear message if the case count exceeds max_cases.
    Returns a dict with case rows and the output paths once written.
    """
    if criteria is None:
        criteria = PhysicalPlausibilityCriteria()
    total = count_grid_cases(**grid_kwargs)
    if total > max_cases:
        raise ValueError(
            f"grid case count {total} exceeds --max-cases {max_cases}; "
            "reduce one or more grids or raise --max-cases (no silent sampling)"
        )

    manifest = pd.read_csv(config.manifest_path, dtype=str, keep_default_na=False)
    stage_params = pd.read_csv(config.stage_params_path)
    observations = pd.read_csv(config.observations_path)
    observation_columns = [c for c in observations.columns if c != "stage"]

    orifice_cache: dict[tuple, dict[str, float | dict[int, float]]] = {}

    case_rows: list[dict[str, Any]] = []
    failed_rows: list[dict[str, Any]] = []

    for i, case in enumerate(enumerate_grid_cases(**grid_kwargs)):
        row, ok = _run_one_case(
            case=case,
            config=config,
            orifice_cache=orifice_cache,
            manifest=manifest,
            stage_params=stage_params,
            observation_columns=observation_columns,
            criteria=criteria,
        )
        if ok:
            case_rows.append(row)
        else:
            failed_rows.append(row)
        if progress_callback is not None:
            progress_callback(i + 1, total, row)

    cases_df = pd.DataFrame.from_records(case_rows) if case_rows else pd.DataFrame()
    failed_df = pd.DataFrame.from_records(failed_rows) if failed_rows else pd.DataFrame()
    paths = write_outputs(config.output_dir, cases_df, failed_df)
    return {
        "total_cases": int(total),
        "cases_run": int(len(case_rows) + len(failed_rows)),
        "cases_ok": int(len(case_rows)),
        "cases_failed": int(len(failed_rows)),
        "output_paths": paths,
        "cases_df": cases_df,
        "failed_df": failed_df,
    }
