"""Synthetic-only tests for Phase 5F PKN grid search."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from clotho.grid_search import (
    ALLOWED_COUPLING,
    ALLOWED_PERF_MODES,
    ALLOWED_WINDOW_MODES,
    GridCase,
    GridSearchConfig,
    PhysicalPlausibilityCriteria,
    compute_orifice_stage_pressures,
    compute_parameter_importance,
    count_grid_cases,
    enumerate_grid_cases,
    evaluate_case_correlations,
    is_positive_candidate,
    is_robust_positive_candidate,
    parse_choice_grid,
    parse_float_grid,
    parse_int_grid,
    perforation_friction_mpa,
    physical_plausibility_pass,
    split_outputs,
    write_outputs,
)


# ---------------------------------------------------------------------------
# 1. parse_float_grid
# ---------------------------------------------------------------------------


def test_parse_float_grid_basic():
    assert parse_float_grid("0,0.1,1") == [0.0, 0.1, 1.0]


def test_parse_float_grid_strips_and_dedups():
    assert parse_float_grid("0.5, 0.5, 1.0 ,2") == [0.5, 1.0, 2.0]


def test_parse_float_grid_rejects_non_finite():
    with pytest.raises(ValueError):
        parse_float_grid("0,inf,1")


def test_parse_float_grid_rejects_empty():
    with pytest.raises(ValueError):
        parse_float_grid("")


def test_parse_int_grid_basic():
    assert parse_int_grid("4,6,8") == [4, 6, 8]


# ---------------------------------------------------------------------------
# 2. parse_choice_grid
# ---------------------------------------------------------------------------


def test_parse_choice_grid_basic():
    assert parse_choice_grid("stage-constant,shadow-scaled", ALLOWED_COUPLING) == [
        "stage-constant", "shadow-scaled"
    ]


def test_parse_choice_grid_rejects_unknown():
    with pytest.raises(ValueError):
        parse_choice_grid("invalid-mode", ALLOWED_COUPLING)


def test_parse_choice_grid_dedups_preserve_order():
    assert parse_choice_grid("longest,best-r2,longest", ALLOWED_WINDOW_MODES) == [
        "longest", "best-r2"
    ]


# ---------------------------------------------------------------------------
# 3. perforation_friction formula (manual reference)
# ---------------------------------------------------------------------------


def test_perforation_friction_manual_reference():
    """rate=1 m3/s, rho=1000, d=0.01 m, N=10, Cd=1, fraction=1.

    A_perf = pi * 0.01^2 / 4 = 7.853981...e-5 m^2
    A_total = 10 * A_perf = 7.853981...e-4 m^2
    q_i = 1
    dp_pa = 0.5 * 1000 * (1 / (1 * 7.853981e-4))^2
          = 500 * (1273.2395)^2
          = 500 * 1.621138e6
          ≈ 8.1057e8 Pa  → ≈ 810.57 MPa
    """
    expected_mpa = 0.5 * 1000.0 * (1.0 / (1.0 * math.pi * 0.01 ** 2 / 4.0 * 10)) ** 2 / 1.0e6
    actual = perforation_friction_mpa(
        rate_m3_per_s=1.0,
        density_kg_m3=1000.0,
        perforation_diameter_m=0.01,
        perforations_per_cluster=10,
        discharge_coefficient=1.0,
        flow_fraction=1.0,
    )
    assert actual == pytest.approx(expected_mpa, rel=1e-9)
    # Sanity bound: very large because of unrealistic input
    assert actual > 800.0
    assert actual < 820.0


def test_perforation_friction_zero_when_rate_zero():
    assert perforation_friction_mpa(
        rate_m3_per_s=0.0,
        density_kg_m3=1050.0,
        perforation_diameter_m=0.012,
        perforations_per_cluster=8,
        discharge_coefficient=0.85,
        flow_fraction=1.0,
    ) == 0.0


def test_perforation_friction_zero_when_flow_fraction_zero():
    assert perforation_friction_mpa(
        rate_m3_per_s=0.1,
        density_kg_m3=1050.0,
        perforation_diameter_m=0.012,
        perforations_per_cluster=8,
        discharge_coefficient=0.85,
        flow_fraction=0.0,
    ) == 0.0


def test_perforation_friction_invalid_rate_negative():
    with pytest.raises(ValueError):
        perforation_friction_mpa(
            rate_m3_per_s=-0.1,
            density_kg_m3=1000,
            perforation_diameter_m=0.012,
            perforations_per_cluster=8,
            discharge_coefficient=0.85,
        )


def test_perforation_friction_invalid_density():
    with pytest.raises(ValueError):
        perforation_friction_mpa(
            rate_m3_per_s=0.1,
            density_kg_m3=0,
            perforation_diameter_m=0.012,
            perforations_per_cluster=8,
            discharge_coefficient=0.85,
        )


def test_perforation_friction_invalid_diameter():
    with pytest.raises(ValueError):
        perforation_friction_mpa(
            rate_m3_per_s=0.1,
            density_kg_m3=1000,
            perforation_diameter_m=0,
            perforations_per_cluster=8,
            discharge_coefficient=0.85,
        )


def test_perforation_friction_invalid_perf_count():
    with pytest.raises(ValueError):
        perforation_friction_mpa(
            rate_m3_per_s=0.1,
            density_kg_m3=1000,
            perforation_diameter_m=0.012,
            perforations_per_cluster=0,
            discharge_coefficient=0.85,
        )


def test_perforation_friction_invalid_Cd():
    with pytest.raises(ValueError):
        perforation_friction_mpa(
            rate_m3_per_s=0.1,
            density_kg_m3=1000,
            perforation_diameter_m=0.012,
            perforations_per_cluster=8,
            discharge_coefficient=0,
        )


# ---------------------------------------------------------------------------
# 4. compute_orifice_stage_pressures (mini synthetic manifest)
# ---------------------------------------------------------------------------


def test_compute_orifice_stage_pressures_smoke():
    manifest = pd.DataFrame(
        {"stage": ["1", "2"], "max_sustained_rate": ["6.0", "12.0"], "valid_falloff_end_elapsed": ["600", "600"]}
    )
    stage_params = pd.DataFrame({"stage": [1, 2], "num_clusters": [4, 8]})
    audit = compute_orifice_stage_pressures(
        manifest=manifest,
        stage_params=stage_params,
        rate_time_unit="minute",
        perforation_diameter_mm=12.0,
        perforations_per_cluster=8,
        discharge_coefficient=0.85,
        fluid_density_kg_m3=1050.0,
    )
    assert "per_stage" in audit
    assert set(audit["per_stage"].keys()) == {1, 2}
    assert audit["min"] <= audit["mean"] <= audit["max"]
    assert audit["min"] >= 0


# ---------------------------------------------------------------------------
# 5. physical_plausibility_pass
# ---------------------------------------------------------------------------


def _baseline_stats(**overrides):
    base = {
        "n_stages_in_correlation": 28,
        "placeholder_count": 0,
        "median_shutin_fluid_efficiency": 0.20,
        "count_efficiency_below_5pct": 1,
        "pkn_volume_ok_count": 28,
        "median_stable_dP_dG_r2": 0.7,
        "C_multiplier_applied": 1.0,
    }
    base.update(overrides)
    return base


def test_physical_plausibility_pass_baseline():
    ok, reasons = physical_plausibility_pass(_baseline_stats(), PhysicalPlausibilityCriteria())
    assert ok is True
    assert reasons == []


def test_physical_plausibility_pass_fails_low_efficiency():
    ok, reasons = physical_plausibility_pass(
        _baseline_stats(median_shutin_fluid_efficiency=0.02),
        PhysicalPlausibilityCriteria(),
    )
    assert ok is False
    assert "median_efficiency_below_min" in reasons


def test_physical_plausibility_pass_fails_low_n():
    ok, reasons = physical_plausibility_pass(
        _baseline_stats(n_stages_in_correlation=10),
        PhysicalPlausibilityCriteria(),
    )
    assert ok is False
    assert any("n_lt_" in r for r in reasons)


def test_physical_plausibility_pass_fails_high_C_multiplier():
    ok, reasons = physical_plausibility_pass(
        _baseline_stats(C_multiplier_applied=5.0),
        PhysicalPlausibilityCriteria(),
    )
    assert ok is False
    assert "C_multiplier_out_of_range" in reasons


# ---------------------------------------------------------------------------
# 6. positive_candidate / robust_positive_candidate flags
# ---------------------------------------------------------------------------


def test_positive_candidate_above_threshold():
    assert is_positive_candidate(0.4, 28) is True


def test_positive_candidate_below_threshold():
    assert is_positive_candidate(0.25, 28) is False


def test_positive_candidate_low_n():
    assert is_positive_candidate(0.5, 5) is False


def test_positive_candidate_nan():
    assert is_positive_candidate(float("nan"), 28) is False


def test_robust_positive_full_criteria():
    assert is_robust_positive_candidate(0.4, 0.25, 28, True) is True


def test_robust_positive_low_spearman():
    assert is_robust_positive_candidate(0.4, 0.05, 28, True) is False


def test_robust_positive_low_n():
    assert is_robust_positive_candidate(0.4, 0.25, 5, True) is False


def test_robust_positive_physical_fail():
    assert is_robust_positive_candidate(0.4, 0.25, 28, False) is False


# ---------------------------------------------------------------------------
# 7. count_grid_cases + enumerate_grid_cases
# ---------------------------------------------------------------------------


def _trivial_grid(**overrides):
    base = dict(
        closure_min_elapsed_seconds=[15.0],
        pkn_C_coupling=["stage-constant"],
        flow_allocation=["stress-shadow"],
        flow_allocation_exponent=[1.0],
        stress_shadow_alpha=[1.0],
        fleak=[0.5],
        C_multiplier=[1.0],
        effective_volume_factor=[1.0],
        wellbore_storage_coeff_m3_per_mpa=[0.0],
        perf_friction_mode=["none"],
        perf_friction_constant_mpa=[0.0],
        perforation_diameter_mm=[12.0],
        perforations_per_cluster=[8],
        perforation_Cd=[0.85],
        fluid_density_kg_m3=[1050.0],
        stable_min_r2=[0.5],
        stable_min_points=[8],
        stable_window_mode=["longest"],
        tp_multiplier=[1.0],
    )
    base.update(overrides)
    return base


def test_count_trivial_grid_is_one():
    assert count_grid_cases(**_trivial_grid()) == 1


def test_count_perf_modes_expand_correctly():
    grid = _trivial_grid(
        perf_friction_mode=["none", "constant", "orifice"],
        perf_friction_constant_mpa=[1.0, 2.0],
        perforation_diameter_mm=[10.0, 12.0],
        perforations_per_cluster=[4, 8],
        perforation_Cd=[0.85],
        fluid_density_kg_m3=[1050.0],
    )
    # none: 1, constant: 2, orifice: 2*2*1*1 = 4 → total 7
    assert count_grid_cases(**grid) == 7


def test_enumerate_yields_count_cases():
    grid = _trivial_grid(
        C_multiplier=[0.5, 1.0],
        fleak=[0.5, 1.0],
    )
    total = count_grid_cases(**grid)
    cases = list(enumerate_grid_cases(**grid))
    assert len(cases) == total == 4
    assert {c.C_multiplier for c in cases} == {0.5, 1.0}
    assert {c.fleak for c in cases} == {0.5, 1.0}


# ---------------------------------------------------------------------------
# 8. evaluate_case_correlations + write_outputs (smoke on synthetic summary)
# ---------------------------------------------------------------------------


def _fake_summary(n_stages: int = 8) -> pd.DataFrame:
    rng = np.random.default_rng(seed=42)
    stages = np.arange(1, n_stages + 1)
    storage = rng.normal(50, 5, n_stages)
    leakoff = rng.normal(200, 20, n_stages)
    nonstorage = leakoff * 0.5
    raw_vol = rng.normal(800, 50, n_stages)
    eff_vol = raw_vol * 0.95
    eff = rng.uniform(0.1, 0.4, n_stages)
    r2 = rng.uniform(0.6, 0.9, n_stages)
    ms = storage * 1.2 + rng.normal(0, 10, n_stages)
    em = leakoff * 0.8 + rng.normal(0, 30, n_stages)
    return pd.DataFrame({
        "stage": stages,
        "pkn_fracture_volume_m3": storage,
        "pkn_leakoff_volume_m3": leakoff,
        "pkn_nonstorage_volume_m3": nonstorage,
        "raw_injected_volume_m3": raw_vol,
        "effective_injected_volume_m3": eff_vol,
        "pkn_shutin_fluid_efficiency": eff,
        "stable_dP_dG_r2": r2,
        "pkn_volume_status": ["ok"] * n_stages,
        "missing_estimate_reason": [""] * n_stages,
        "pkn_C_multiplier_to_20pct_shutin_efficiency": rng.uniform(0.1, 1.0, n_stages),
        "microseismic_affected_volume": ms,
        "electromagnetic_affected_area_with_loss": em,
    })


def test_evaluate_case_correlations_smoke():
    summary = _fake_summary()
    obs_cols = ["microseismic_affected_volume", "electromagnetic_affected_area_with_loss"]
    eff_stats, corr_rows = evaluate_case_correlations(summary, obs_cols)
    assert eff_stats["pkn_volume_ok_count"] == len(summary)
    assert eff_stats["placeholder_count"] == 0
    assert np.isfinite(eff_stats["median_shutin_fluid_efficiency"])
    # corr rows: 6 metric classes × 2 targets = 12 expected (or fewer if some classes missing)
    assert len(corr_rows) > 0
    # Storage should correlate strongly with microseismic in the fixture
    storage_ms = [r for r in corr_rows if r["metric_class"] == "storage" and r["target_class"] == "microseismic"]
    assert len(storage_ms) == 1
    assert storage_ms[0]["pearson_r"] > 0.5


def test_write_outputs_smoke(tmp_path):
    cases_df = pd.DataFrame.from_records([
        {
            "case_id": 0,
            "closure_min_elapsed_seconds": 15.0,
            "pkn_C_coupling": "stage-constant",
            "flow_allocation": "stress-shadow",
            "flow_allocation_exponent": 1.0,
            "stress_shadow_alpha": 1.0,
            "fleak": 0.5,
            "C_multiplier": 1.0,
            "effective_volume_factor": 1.0,
            "wellbore_storage_coeff_m3_per_mpa": 0.0,
            "perf_friction_mode": "none",
            "perf_friction_constant_mpa": 0.0,
            "perforation_diameter_mm": float("nan"),
            "perforations_per_cluster": 0,
            "perforation_Cd": float("nan"),
            "fluid_density_kg_m3": float("nan"),
            "stable_min_r2": 0.5,
            "stable_min_points": 8,
            "stable_window_mode": "longest",
            "tp_multiplier": 1.0,
            "n_stages_in_correlation": 28,
            "median_shutin_fluid_efficiency": 0.2,
            "physical_plausibility_pass": True,
            "storage_vs_microseismic_pearson": 0.45,
            "storage_vs_microseismic_spearman": 0.30,
            "storage_vs_microseismic_n": 28,
        }
    ])
    failed_df = pd.DataFrame()
    paths = write_outputs(tmp_path, cases_df, failed_df)
    for key in ("grid_cases", "grid_positive_candidates", "grid_robust_positive_candidates",
                "grid_best_by_target", "grid_parameter_importance", "grid_failed_cases"):
        assert paths[key].exists(), f"missing output {key}"
    pos = pd.read_csv(paths["grid_positive_candidates"])
    assert len(pos) == 1  # the single Pearson=0.45 row qualifies
    rob = pd.read_csv(paths["grid_robust_positive_candidates"])
    assert len(rob) == 1
    best = pd.read_csv(paths["grid_best_by_target"])
    assert not best.empty
    importance = pd.read_csv(paths["grid_parameter_importance"])
    assert "parameter" in importance.columns


def test_split_outputs_filters_low_pearson(tmp_path):
    cases_df = pd.DataFrame.from_records([
        {
            "case_id": 0,
            "physical_plausibility_pass": True,
            "storage_vs_microseismic_pearson": 0.1,
            "storage_vs_microseismic_spearman": 0.0,
            "storage_vs_microseismic_n": 28,
        },
        {
            "case_id": 1,
            "physical_plausibility_pass": False,
            "storage_vs_microseismic_pearson": 0.6,
            "storage_vs_microseismic_spearman": 0.4,
            "storage_vs_microseismic_n": 28,
        },
    ])
    outs = split_outputs(cases_df)
    pos = outs["grid_positive_candidates"]
    rob = outs["grid_robust_positive_candidates"]
    # case 1 has pearson > 0.3 so it qualifies as positive
    assert (pos["case_id"] == 1).any()
    # but physical_plausibility_pass=False so it's NOT a robust candidate
    assert (rob["case_id"] == 1).any() is False or rob.empty
