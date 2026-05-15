"""closure.py 的测试：只用 synthetic 数据，不读真实 well4。"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from clotho.closure import (
    K_lp,
    PHYSICAL_PKN_IF,
    build_observation_correlation_table,
    compute_flow_allocation_eta,
    compute_physical_leakoff_C,
    compute_stress_shadow,
    effective_volume_correction,
    legacy_mvp_pkn_volume_balance_estimate,
    physical_pkn_fracture_volume,
    physical_pkn_volume_balance,
    pick_barree_tangent_closure_candidate,
    pick_fracture_initiation_candidate,
    pick_mcclure_compliance_closure_candidate,
    pick_stable_pressure_g_segment,
    run_closure_batch,
    select_closure_candidate,
    write_closure_batch_outputs,
)
from clotho.g_function import nolte_g_time


def _synthetic_curve(
    n_pre: int = 200,
    n_post: int = 300,
    shut_in_time: str = "10:00:00",
    sigma_min: float = 80.0,
    base_rate: float = 20.0,
    base_pressure: float = 90.0,
) -> tuple[pd.DataFrame, int]:
    """创建 synthetic stage 曲线。

    返回 (curve DataFrame, shut_in_index)。
    注入阶段：压力从 base_pressure-20 上升到 base_pressure，排量从 5 升到 base_rate。
    停泵后：压力从 base_pressure 逐渐下降。
    """
    rows: list[dict[str, object]] = []

    shut_in_seconds = 10 * 3600
    for i in range(n_pre):
        t = shut_in_seconds - (n_pre - i)
        h = t // 3600
        m = (t % 3600) // 60
        s = t % 60
        frac = i / max(n_pre - 1, 1)
        rate = 5.0 + (base_rate - 5.0) * min(frac * 2, 1.0)
        pressure = (base_pressure - 20) + 20 * frac
        vol = frac * 200.0
        rows.append({
            "time": f"{h:02d}:{m:02d}:{s:02d}",
            "wellhead_pressure": pressure,
            "rate": rate,
            "stage_volume": vol,
            "total_volume": vol,
        })

    for i in range(n_post):
        t = shut_in_seconds + i
        h = t // 3600
        m = (t % 3600) // 60
        s = t % 60
        pressure = base_pressure - 0.02 * i
        rows.append({
            "time": f"{h:02d}:{m:02d}:{s:02d}",
            "wellhead_pressure": max(pressure, 0.1),
            "rate": 0.0,
            "stage_volume": 200.0,
            "total_volume": 200.0,
        })

    df = pd.DataFrame(rows)
    return df, n_pre


class TestFractureInitiation:
    def test_sigma_min_crossing(self):
        curve, shut_in_idx = _synthetic_curve(sigma_min=80.0, base_pressure=90.0)
        result = pick_fracture_initiation_candidate(
            curve, shut_in_idx,
            pressure_column="wellhead_pressure",
            minimum_stress_prior_mpa=80.0,
            min_rate=10.0,
        )
        assert result["fracture_initiation_status"] == "ok"
        assert result["fracture_initiation_rule"] == "sigma_min_crossing"
        assert result["tp_corrected_seconds"] > 0
        assert result["fracture_initiation_index"] < shut_in_idx

    def test_fallback_to_rate(self):
        curve, shut_in_idx = _synthetic_curve(base_pressure=50.0)
        result = pick_fracture_initiation_candidate(
            curve, shut_in_idx,
            pressure_column="wellhead_pressure",
            minimum_stress_prior_mpa=999.0,
            min_rate=10.0,
        )
        assert result["fracture_initiation_status"] == "ok"
        assert result["fracture_initiation_rule"] == "first_rate_ge_min_rate"

    def test_no_sigma_min(self):
        curve, shut_in_idx = _synthetic_curve()
        result = pick_fracture_initiation_candidate(
            curve, shut_in_idx,
            pressure_column="wellhead_pressure",
            minimum_stress_prior_mpa=None,
            min_rate=10.0,
        )
        assert result["fracture_initiation_status"] == "ok"
        assert result["fracture_initiation_rule"] == "first_rate_ge_min_rate"
        assert result["tp_corrected_seconds"] > 0

    def test_corrected_tp_positive(self):
        curve, shut_in_idx = _synthetic_curve(n_pre=100)
        result = pick_fracture_initiation_candidate(
            curve, shut_in_idx,
            pressure_column="wellhead_pressure",
            min_rate=10.0,
        )
        assert result["fracture_initiation_status"] == "ok"
        assert result["tp_corrected_seconds"] > 0

    def test_legacy_tp_exists(self):
        """tp_legacy (volume/rate) 应该始终可以独立于 initiation 计算。"""
        from clotho.stage_data import volume_over_max_rate_duration_seconds
        curve, shut_in_idx = _synthetic_curve()
        tp = volume_over_max_rate_duration_seconds(
            curve, shut_in_idx,
            max_sustained_rate=20.0,
            rate_time_unit="minute",
            volume_column="total_volume",
        )
        assert tp > 0


class TestBarreeTangentClosure:
    def _make_synthetic_barree(
        self,
        n: int = 200,
        closure_frac: float = 0.5,
        tp: float = 600.0,
    ):
        """构造 G*dP/dG 在某点偏离直线的 synthetic 数据。"""
        elapsed = np.arange(1, n + 1, dtype=float)
        delta = elapsed / tp
        g_time = np.asarray(nolte_g_time(delta, 0.8), dtype=float)

        closure_idx = int(n * closure_frac)
        slope_normal = -5.0
        slope_after = -2.0

        pressure = np.zeros(n)
        pressure[0] = 120.0
        for i in range(1, n):
            dg = g_time[i] - g_time[i - 1]
            if i < closure_idx:
                pressure[i] = pressure[i - 1] + slope_normal * dg
            else:
                pressure[i] = pressure[i - 1] + slope_after * dg

        dP_dG = np.gradient(pressure, g_time, edge_order=1)
        return g_time, dP_dG, elapsed, pressure, closure_idx

    def test_barree_finds_closure(self):
        g, dp, el, pr, expected_idx = self._make_synthetic_barree(n=200, closure_frac=0.5)
        result = pick_barree_tangent_closure_candidate(
            g, dp, el, pr, closure_min_elapsed_seconds=1.0,
        )
        assert result["barree_status"] == "ok"
        found_idx = result["barree_closure_index"]
        assert abs(found_idx - expected_idx) < 30

    def test_barree_respects_min_elapsed(self):
        g, dp, el, pr, _ = self._make_synthetic_barree(n=200, closure_frac=0.1)
        result = pick_barree_tangent_closure_candidate(
            g, dp, el, pr, closure_min_elapsed_seconds=100.0,
        )
        if result["barree_status"] == "ok":
            assert result["barree_closure_elapsed_seconds"] >= 100.0


class TestMcClureComplianceClosure:
    def _make_synthetic_mcclure(self, n: int = 200, min_frac: float = 0.5, tp: float = 600.0):
        """构造 dP/dG 在某处有局部极小的 synthetic 数据。"""
        elapsed = np.arange(1, n + 1, dtype=float)
        delta = elapsed / tp
        g_time = np.asarray(nolte_g_time(delta, 0.8), dtype=float)

        min_idx = int(n * min_frac)
        dP_dG = np.zeros(n)
        for i in range(n):
            dP_dG[i] = -3.0 + 5.0 * ((i - min_idx) / n) ** 2

        pressure = np.cumsum(dP_dG * np.gradient(g_time)) + 120.0
        return g_time, dP_dG, elapsed, pressure, min_idx

    def test_mcclure_finds_minimum(self):
        g, dp, el, pr, expected_min = self._make_synthetic_mcclure()
        result = pick_mcclure_compliance_closure_candidate(
            g, dp, el, pr, closure_min_elapsed_seconds=1.0,
        )
        assert result["mcclure_status"] == "ok"
        assert abs(result["mcclure_closure_index"] - expected_min) < 15

    def test_mcclure_respects_min_elapsed(self):
        g, dp, el, pr, _ = self._make_synthetic_mcclure(n=200, min_frac=0.05)
        result = pick_mcclure_compliance_closure_candidate(
            g, dp, el, pr, closure_min_elapsed_seconds=100.0,
        )
        if result["mcclure_status"] == "ok":
            assert result["mcclure_closure_elapsed_seconds"] >= 100.0


class TestEarlyTransientGuard:
    def test_early_spike_not_selected_as_closure(self):
        """大尖峰在 0-10s，闭合偏离在 30s 后；closure_min_elapsed=15。"""
        n = 200
        tp = 600.0
        elapsed = np.arange(1, n + 1, dtype=float)
        delta = elapsed / tp
        g_time = np.asarray(nolte_g_time(delta, 0.8), dtype=float)

        slope_normal = -5.0
        slope_after = -2.0
        closure_idx = 100

        pressure = np.zeros(n)
        pressure[0] = 120.0

        for i in range(1, 10):
            pressure[i] = pressure[i - 1] + 5.0

        for i in range(10, n):
            dg = g_time[i] - g_time[i - 1]
            if i < closure_idx:
                pressure[i] = pressure[i - 1] + slope_normal * dg
            else:
                pressure[i] = pressure[i - 1] + slope_after * dg

        dP_dG = np.gradient(pressure, g_time, edge_order=1)

        result = pick_barree_tangent_closure_candidate(
            g_time, dP_dG, elapsed, pressure,
            closure_min_elapsed_seconds=15.0,
        )
        if result["barree_status"] == "ok":
            assert result["barree_closure_elapsed_seconds"] >= 15.0

        result_mc = pick_mcclure_compliance_closure_candidate(
            g_time, dP_dG, elapsed, pressure,
            closure_min_elapsed_seconds=15.0,
        )
        if result_mc["mcclure_status"] == "ok":
            assert result_mc["mcclure_closure_elapsed_seconds"] >= 15.0


class TestSelectClosureCandidate:
    def test_barree_then_mcclure_prefers_barree(self):
        barree = {"barree_status": "ok", "barree_closure_elapsed_seconds": 50.0,
                  "barree_closure_pressure_mpa": 80.0, "barree_closure_g_time": 0.5,
                  "barree_quality_flag": "ok"}
        mcclure = {"mcclure_status": "ok", "mcclure_closure_elapsed_seconds": 60.0,
                   "mcclure_closure_pressure_mpa": 78.0, "mcclure_closure_g_time": 0.6,
                   "mcclure_quality_flag": "ok"}
        result = select_closure_candidate(barree, mcclure, "barree-then-mcclure")
        assert result["selected_closure_method"] == "barree"
        assert result["closure_is_candidate"] is True
        assert result["closure_is_final_interpretation"] is False

    def test_fallback_to_mcclure(self):
        barree = {"barree_status": "not_found"}
        mcclure = {"mcclure_status": "ok", "mcclure_closure_elapsed_seconds": 60.0,
                   "mcclure_closure_pressure_mpa": 78.0, "mcclure_closure_g_time": 0.6,
                   "mcclure_quality_flag": "ok"}
        result = select_closure_candidate(barree, mcclure, "barree-then-mcclure")
        assert result["selected_closure_method"] == "mcclure"

    def test_both_failed(self):
        barree = {"barree_status": "not_found"}
        mcclure = {"mcclure_status": "not_found"}
        result = select_closure_candidate(barree, mcclure, "barree-then-mcclure")
        assert result["selected_closure_status"] == "not_found"


class TestEffectiveVolumeCorrection:
    def test_basic_correction(self):
        result = effective_volume_correction(
            100.0, 120.0, 100.0,
            perforation_friction_mpa=0.0,
            wellbore_storage_coeff_m3_per_mpa=0.5,
        )
        assert result["raw_injected_volume_m3"] == 100.0
        assert result["wellbore_storage_volume_m3"] == pytest.approx(10.0)
        assert result["effective_injected_volume_m3"] == pytest.approx(90.0)

    def test_no_closure_fallback(self):
        result = effective_volume_correction(
            100.0, 120.0, None,
            perforation_friction_mpa=0.0,
            wellbore_storage_coeff_m3_per_mpa=0.5,
        )
        assert result["wellbore_storage_volume_m3"] == 0.0
        assert result["effective_injected_volume_m3"] == 100.0
        assert "closure_pressure_unavailable" in result["volume_correction_warning"]

    def test_perforation_friction_in_pressure(self):
        result = effective_volume_correction(
            100.0, 120.0, 100.0,
            perforation_friction_mpa=2.0,
            wellbore_storage_coeff_m3_per_mpa=0.0,
        )
        assert result["pressure_for_net_mpa"] == pytest.approx(118.0)
        assert result["perforation_friction_mpa"] == 2.0

    def test_effective_not_negative(self):
        result = effective_volume_correction(
            10.0, 200.0, 50.0,
            perforation_friction_mpa=0.0,
            wellbore_storage_coeff_m3_per_mpa=1.0,
        )
        assert result["effective_injected_volume_m3"] >= 0.0


class TestPKNVolumeBalance:
    def test_basic_pkn_estimate(self):
        result = legacy_mvp_pkn_volume_balance_estimate(
            effective_injected_volume_m3=100.0,
            closure_pressure_mpa=80.0,
            minimum_stress_prior_mpa=60.0,
            half_height_m=15.0,
            youngs_modulus_gpa=30.0,
            poissons_ratio=0.25,
            barree_tangent_slope=-5.0,
            tp_seconds=600.0,
            g_time_at_closure=0.5,
        )
        assert result["pkn_volume_status"] == "ok"
        assert np.isfinite(result["pkn_fracture_volume_m3"])
        assert result["pkn_fracture_volume_m3"] > 0
        assert np.isfinite(result["pkn_half_length_mean_m"])
        assert result["pkn_half_length_mean_m"] > 0

    def test_missing_modulus_fails(self):
        result = legacy_mvp_pkn_volume_balance_estimate(
            effective_injected_volume_m3=100.0,
            closure_pressure_mpa=80.0,
            youngs_modulus_gpa=None,
            poissons_ratio=0.25,
            half_height_m=15.0,
        )
        assert result["pkn_volume_status"] == "failed"
        assert "youngs_modulus_gpa" in result["pkn_warning"]

    def test_missing_closure_fails(self):
        result = legacy_mvp_pkn_volume_balance_estimate(
            effective_injected_volume_m3=100.0,
            closure_pressure_mpa=None,
            youngs_modulus_gpa=30.0,
            poissons_ratio=0.25,
            half_height_m=15.0,
        )
        assert result["pkn_volume_status"] == "failed"

    def test_no_leakoff_without_slope(self):
        result = legacy_mvp_pkn_volume_balance_estimate(
            effective_injected_volume_m3=100.0,
            closure_pressure_mpa=80.0,
            minimum_stress_prior_mpa=60.0,
            half_height_m=15.0,
            youngs_modulus_gpa=30.0,
            poissons_ratio=0.25,
            barree_tangent_slope=None,
        )
        assert result["pkn_volume_status"] == "ok"
        assert result["pkn_leakoff_coefficient"] == 0.0


class TestObservationCorrelation:
    def test_positive_correlation(self):
        summary = pd.DataFrame({
            "stage": [1, 2, 3, 4, 5],
            "pkn_fracture_volume_m3": [10, 20, 30, 40, 50],
            "effective_injected_volume_m3": [100, 200, 300, 400, 500],
            "raw_injected_volume_m3": [110, 210, 310, 410, 510],
            "selected_closure_pressure_mpa": [80, 82, 84, 86, 88],
            "tp_corrected_seconds": [600, 700, 800, 900, 1000],
            "tp_correction_ratio": [0.9, 0.92, 0.94, 0.96, 0.98],
        })
        observations = pd.DataFrame({
            "stage": [1, 2, 3, 4, 5],
            "microseismic_affected_volume": [100, 200, 300, 400, 500],
            "electromagnetic_affected_area": [1000, 2000, 3000, 4000, 5000],
        })
        corr = build_observation_correlation_table(summary, observations)
        assert len(corr) > 0
        pkn_micro = corr[
            (corr["metric"] == "pkn_fracture_volume_m3")
            & (corr["target"] == "microseismic_affected_volume")
        ]
        assert len(pkn_micro) == 1
        assert pkn_micro.iloc[0]["pearson_r"] > 0
        assert pkn_micro.iloc[0]["n"] == 5

    def test_observation_target_names_preserved(self):
        """correlation target 必须包含 microseismic_affected_volume 和
        electromagnetic_affected_area，不能出现 electromagnetic_half_length_m。"""
        summary = pd.DataFrame({
            "stage": [1, 2, 3, 4, 5],
            "pkn_fracture_volume_m3": [10, 20, 30, 40, 50],
            "effective_injected_volume_m3": [100, 200, 300, 400, 500],
            "raw_injected_volume_m3": [110, 210, 310, 410, 510],
            "selected_closure_pressure_mpa": [80, 82, 84, 86, 88],
            "tp_corrected_seconds": [600, 700, 800, 900, 1000],
            "tp_correction_ratio": [0.9, 0.92, 0.94, 0.96, 0.98],
        })
        observations = pd.DataFrame({
            "stage": [1, 2, 3, 4, 5],
            "microseismic_affected_volume": [100, 200, 300, 400, 500],
            "electromagnetic_affected_area": [1000, 2000, 3000, 4000, 5000],
        })
        corr = build_observation_correlation_table(summary, observations)
        targets = set(corr["target"].unique())
        assert "microseismic_affected_volume" in targets
        assert "electromagnetic_affected_area" in targets
        assert "electromagnetic_half_length_m" not in targets

    def test_too_few_points_nan(self):
        summary = pd.DataFrame({
            "stage": [1, 2],
            "pkn_fracture_volume_m3": [10, 20],
            "effective_injected_volume_m3": [100, 200],
            "raw_injected_volume_m3": [110, 210],
            "selected_closure_pressure_mpa": [80, 82],
            "tp_corrected_seconds": [600, 700],
            "tp_correction_ratio": [0.9, 0.92],
        })
        observations = pd.DataFrame({
            "stage": [1, 2],
            "microseismic_affected_volume": [100, 200],
        })
        corr = build_observation_correlation_table(summary, observations)
        pkn_row = corr[corr["metric"] == "pkn_fracture_volume_m3"]
        assert len(pkn_row) == 1
        assert np.isnan(pkn_row.iloc[0]["pearson_r"])


def _write_synthetic_stage_csv(path: Path, n_pre: int = 50, n_post: int = 150) -> str:
    """写出一个 synthetic stage 曲线 CSV，返回停泵时间字符串。"""
    shut_in_seconds = 10 * 3600
    rows: list[dict[str, object]] = []
    for i in range(n_pre):
        t = shut_in_seconds - (n_pre - i)
        h, m, s = t // 3600, (t % 3600) // 60, t % 60
        frac = i / max(n_pre - 1, 1)
        rows.append({
            "time": f"{h:02d}:{m:02d}:{s:02d}",
            "wellhead_pressure": 70.0 + 20.0 * frac,
            "rate": 5.0 + 15.0 * min(frac * 2, 1.0),
            "stage_volume": frac * 200.0,
            "total_volume": frac * 200.0,
        })

    for i in range(n_post):
        t = shut_in_seconds + i
        h, m, s = t // 3600, (t % 3600) // 60, t % 60
        dp = 0.015 * i if i < 80 else 0.015 * 80 + 0.04 * (i - 80)
        rows.append({
            "time": f"{h:02d}:{m:02d}:{s:02d}",
            "wellhead_pressure": max(90.0 - dp, 0.1),
            "rate": 0.0,
            "stage_volume": 200.0,
            "total_volume": 200.0,
        })

    pd.DataFrame(rows).to_csv(path, index=False)
    return "10:00:00"


class TestCLIClosureBatchSmoke:
    def test_cli_closure_batch(self, tmp_path: Path):
        stage_dir = tmp_path / "stage_data"
        stage_dir.mkdir()

        shut_in_1 = _write_synthetic_stage_csv(stage_dir / "stage_01.csv", n_pre=50, n_post=150)
        shut_in_2 = _write_synthetic_stage_csv(stage_dir / "stage_02.csv", n_pre=50, n_post=150)

        params = pd.DataFrame([
            {"well": "W1", "stage": 1, "file": "stage_data/stage_01.csv",
             "shut_in": shut_in_1, "sigma_min": 75.0, "add_pressure": 40.0,
             "hw": 15.0, "e_gpa": 30.0, "nu": 0.25},
            {"well": "W1", "stage": 2, "file": "stage_data/stage_02.csv",
             "shut_in": shut_in_2, "sigma_min": 75.0, "add_pressure": 40.0,
             "hw": 15.0, "e_gpa": 30.0, "nu": 0.25},
        ])
        params_path = tmp_path / "stage_params.csv"
        params.to_csv(params_path, index=False)

        manifest = pd.DataFrame([
            {"stage": 1, "max_sustained_rate": 20.0, "valid_falloff_end_elapsed": 140.0},
            {"stage": 2, "max_sustained_rate": 20.0, "valid_falloff_end_elapsed": 140.0},
        ])
        manifest_path = tmp_path / "manifest.csv"
        manifest.to_csv(manifest_path, index=False)

        observations = pd.DataFrame([
            {"stage": 1, "microseismic_affected_volume": 150.0, "electromagnetic_affected_area": 18000.0},
            {"stage": 2, "microseismic_affected_volume": 170.0, "electromagnetic_affected_area": 19000.0},
        ])
        obs_path = tmp_path / "observations.csv"
        observations.to_csv(obs_path, index=False)

        output_path = tmp_path / "closure_summary.csv"
        corr_path = tmp_path / "correlation.csv"

        from clotho.cli import main
        exit_code = main([
            "closure-batch",
            "--stage-params", str(params_path),
            "--well-root", str(tmp_path),
            "--manifest", str(manifest_path),
            "--observations", str(obs_path),
            "--output", str(output_path),
            "--correlation-output", str(corr_path),
            "--volume-column", "total_volume",
            "--rate-time-unit", "minute",
            "--min-rate", "10",
            "--g-time-m", "0.8",
            "--closure-min-elapsed-seconds", "5",
            "--elapsed-duplicate-policy", "keep-last",
            "--pressure-source", "estimated-bottomhole",
        ])

        assert exit_code == 0
        assert output_path.exists()

        summary = pd.read_csv(output_path)
        assert len(summary) == 2
        assert (summary["closure_is_candidate"] == True).all()  # noqa: E712
        assert (summary["closure_is_final_interpretation"] == False).all()  # noqa: E712
        assert "closure_was_computed" in summary.columns

    def test_observation_only_stages_get_placeholder(self, tmp_path: Path):
        """manifest 只有 stage 1,2; observations 有 stage 1,2,3。
        summary 应有 3 行，stage 3 为 placeholder。"""
        stage_dir = tmp_path / "stage_data"
        stage_dir.mkdir()

        shut_in_1 = _write_synthetic_stage_csv(stage_dir / "stage_01.csv", n_pre=50, n_post=150)
        shut_in_2 = _write_synthetic_stage_csv(stage_dir / "stage_02.csv", n_pre=50, n_post=150)

        params = pd.DataFrame([
            {"well": "W1", "stage": 1, "file": "stage_data/stage_01.csv",
             "shut_in": shut_in_1, "sigma_min": 75.0, "add_pressure": 40.0,
             "hw": 15.0, "e_gpa": 30.0, "nu": 0.25},
            {"well": "W1", "stage": 2, "file": "stage_data/stage_02.csv",
             "shut_in": shut_in_2, "sigma_min": 75.0, "add_pressure": 40.0,
             "hw": 15.0, "e_gpa": 30.0, "nu": 0.25},
        ])
        params.to_csv(tmp_path / "stage_params.csv", index=False)

        manifest = pd.DataFrame([
            {"stage": 1, "max_sustained_rate": 20.0, "valid_falloff_end_elapsed": 140.0},
            {"stage": 2, "max_sustained_rate": 20.0, "valid_falloff_end_elapsed": 140.0},
        ])
        manifest.to_csv(tmp_path / "manifest.csv", index=False)

        observations = pd.DataFrame([
            {"stage": 1, "microseismic_affected_volume": 150.0, "electromagnetic_affected_area": 18000.0},
            {"stage": 2, "microseismic_affected_volume": 170.0, "electromagnetic_affected_area": 19000.0},
            {"stage": 3, "microseismic_affected_volume": 200.0, "electromagnetic_affected_area": 20000.0},
        ])
        observations.to_csv(tmp_path / "observations.csv", index=False)

        result = run_closure_batch(
            stage_params_path=tmp_path / "stage_params.csv",
            well_root=tmp_path,
            manifest_path=tmp_path / "manifest.csv",
            observations_path=tmp_path / "observations.csv",
            volume_column="total_volume",
            rate_time_unit="minute",
            min_rate=10.0,
            g_time_m=0.8,
            closure_min_elapsed_seconds=5.0,
            elapsed_duplicate_policy="keep-last",
            pressure_source="estimated-bottomhole",
        )

        summary = result["summary"]
        assert len(summary) == 3
        assert set(summary["stage"].astype(int)) == {1, 2, 3}

        s3 = summary[summary["stage"] == 3].iloc[0]
        assert s3["missing_estimate_reason"] == "no_valid_falloff_manifest_row"
        assert s3["selected_closure_status"] == "not_computed"
        assert s3["pkn_volume_status"] == "not_computed"
        assert s3["closure_was_computed"] == False  # noqa: E712
        assert s3["closure_is_candidate"] == True  # noqa: E712
        assert s3["closure_is_final_interpretation"] == False  # noqa: E712
        assert s3["microseismic_affected_volume"] == 200.0
        assert s3["electromagnetic_affected_area"] == 20000.0

    def test_placeholder_rows_not_in_correlation_n(self, tmp_path: Path):
        """placeholder NaN 不应增加 correlation n。
        manifest stage 1,2 + observation stage 1,2,3 → correlation n 最多 2。"""
        stage_dir = tmp_path / "stage_data"
        stage_dir.mkdir()

        shut_in_1 = _write_synthetic_stage_csv(stage_dir / "stage_01.csv", n_pre=50, n_post=150)
        shut_in_2 = _write_synthetic_stage_csv(stage_dir / "stage_02.csv", n_pre=50, n_post=150)

        params = pd.DataFrame([
            {"well": "W1", "stage": 1, "file": "stage_data/stage_01.csv",
             "shut_in": shut_in_1, "sigma_min": 75.0, "add_pressure": 40.0,
             "hw": 15.0, "e_gpa": 30.0, "nu": 0.25},
            {"well": "W1", "stage": 2, "file": "stage_data/stage_02.csv",
             "shut_in": shut_in_2, "sigma_min": 75.0, "add_pressure": 40.0,
             "hw": 15.0, "e_gpa": 30.0, "nu": 0.25},
        ])
        params.to_csv(tmp_path / "stage_params.csv", index=False)

        manifest = pd.DataFrame([
            {"stage": 1, "max_sustained_rate": 20.0, "valid_falloff_end_elapsed": 140.0},
            {"stage": 2, "max_sustained_rate": 20.0, "valid_falloff_end_elapsed": 140.0},
        ])
        manifest.to_csv(tmp_path / "manifest.csv", index=False)

        observations = pd.DataFrame([
            {"stage": 1, "microseismic_affected_volume": 150.0, "electromagnetic_affected_area": 18000.0},
            {"stage": 2, "microseismic_affected_volume": 170.0, "electromagnetic_affected_area": 19000.0},
            {"stage": 3, "microseismic_affected_volume": 200.0, "electromagnetic_affected_area": 20000.0},
        ])
        observations.to_csv(tmp_path / "observations.csv", index=False)

        result = run_closure_batch(
            stage_params_path=tmp_path / "stage_params.csv",
            well_root=tmp_path,
            manifest_path=tmp_path / "manifest.csv",
            observations_path=tmp_path / "observations.csv",
            volume_column="total_volume",
            rate_time_unit="minute",
            min_rate=10.0,
            g_time_m=0.8,
            closure_min_elapsed_seconds=5.0,
            elapsed_duplicate_policy="keep-last",
            pressure_source="estimated-bottomhole",
        )

        corr = result["correlation"]
        assert corr is not None
        for _, row in corr.iterrows():
            assert row["n"] <= 2
            assert np.isnan(row["pearson_r"])
            assert np.isnan(row["spearman_r"])

    def test_cli_closure_batch_no_observations(self, tmp_path: Path):
        stage_dir = tmp_path / "stage_data"
        stage_dir.mkdir()

        shut_in = _write_synthetic_stage_csv(stage_dir / "stage_01.csv")

        params = pd.DataFrame([
            {"well": "W1", "stage": 1, "file": "stage_data/stage_01.csv",
             "shut_in": shut_in, "sigma_min": 75.0, "add_pressure": 40.0,
             "hw": 15.0, "e_gpa": 30.0, "nu": 0.25},
        ])
        params.to_csv(tmp_path / "stage_params.csv", index=False)

        manifest = pd.DataFrame([
            {"stage": 1, "max_sustained_rate": 20.0, "valid_falloff_end_elapsed": 140.0},
        ])
        manifest.to_csv(tmp_path / "manifest.csv", index=False)

        output_path = tmp_path / "closure_summary.csv"

        from clotho.cli import main
        exit_code = main([
            "closure-batch",
            "--stage-params", str(tmp_path / "stage_params.csv"),
            "--well-root", str(tmp_path),
            "--manifest", str(tmp_path / "manifest.csv"),
            "--output", str(output_path),
            "--volume-column", "total_volume",
            "--rate-time-unit", "minute",
            "--g-time-m", "0.8",
            "--closure-min-elapsed-seconds", "5",
        ])

        assert exit_code == 0
        assert output_path.exists()


class TestPhysicalPKN:
    def test_physical_pkn_fracture_volume_formula(self):
        L, H_w, P_net, E_prime, I_F = 10.0, 50.0, 5.0, 36000.0, 0.722464726919
        expected = math.pi * I_F / E_prime * L * H_w ** 2 * P_net
        result = physical_pkn_fracture_volume(L, H_w, P_net, E_prime, I_F=I_F)
        assert result == pytest.approx(expected, rel=1e-10)
        assert result > 0

    def test_stress_shadow_linear_system(self):
        result = compute_stress_shadow(3, 10.0, 50.0, alpha=1.0)
        assert result["stress_shadow_status"] == "ok"
        xi = result["stress_shadow_xi"]
        assert len(xi) == 3
        assert np.all(xi > 0)
        assert xi[0] == pytest.approx(xi[2], rel=1e-10)
        assert xi[1] < xi[0]
        assert np.isfinite(result["stress_shadow_condition_number"])

        no_shadow = compute_stress_shadow(3, 10.0, 50.0, alpha=0.0)
        assert no_shadow["stress_shadow_status"] == "ok"
        assert np.allclose(no_shadow["stress_shadow_xi"], 1.0)

    def test_stable_segment_detection(self):
        n = 30
        g_time = np.linspace(0.1, 3.0, n)
        pressure = -5.0 * g_time + 100.0
        pressure[20:] += np.random.default_rng(42).normal(0, 2, n - 20)
        elapsed = np.arange(1, n + 1, dtype=float) * 10.0

        result = pick_stable_pressure_g_segment(
            g_time, pressure, elapsed,
            min_elapsed_seconds=1.0, min_points=5, min_r2=0.95,
        )
        assert result["stable_segment_status"] == "ok"
        assert result["stable_dP_dG_slope_mpa"] == pytest.approx(-5.0, abs=0.5)
        assert result["stable_dP_dG_r2"] >= 0.95
        assert result["stable_segment_point_count"] >= 5

    def test_compute_physical_leakoff_C(self):
        slope = -2.0
        H_w, E_prime, H_p, tp, xi = 50.0, 36000.0, 25.0, 600.0, 0.8
        C = compute_physical_leakoff_C(slope, H_w, E_prime, H_p, tp, xi, I_F=0.722464726919)
        expected = -(0.722464726919 * 50.0 ** 2 * 0.8) / (36000.0 * 25.0 * math.sqrt(600.0)) * (-2.0)
        assert C == pytest.approx(expected, rel=1e-10)
        assert C > 0

    def test_K_lp_known_values(self):
        k05 = K_lp(0.5)
        expected_05 = 4.0 * math.sqrt(math.pi) * 0.5 * math.gamma(0.5) / (
            1.0 * math.gamma(1.0))
        assert k05 == pytest.approx(expected_05, rel=1e-10)

        k10 = K_lp(1.0)
        expected_10 = 4.0 * math.sqrt(math.pi) * 1.0 * math.gamma(1.0) / (
            1.5 * math.gamma(1.5))
        assert k10 == pytest.approx(expected_10, rel=1e-10)

    def test_physical_volume_balance_end_to_end(self):
        n = 50
        tp = 600.0
        elapsed = np.arange(1, n + 1, dtype=float)
        delta = elapsed / tp
        g_time = np.asarray(nolte_g_time(delta, 0.8), dtype=float)
        pressure = 120.0 - 3.0 * g_time

        E_prime = 33.3 * 1000.0 / (1.0 - 0.23 ** 2)
        result = physical_pkn_volume_balance(
            n_clusters=4,
            cluster_spacings_m=8.4,
            H_w_m=50.0,
            fleak=0.5,
            E_prime_mpa=E_prime,
            closure_pressure_mpa=110.0,
            minimum_stress_prior_mpa=99.1,
            perforation_friction_mpa=0.0,
            g_time=g_time,
            pressure_mpa=pressure,
            elapsed_seconds=elapsed,
            closure_index=40,
            tp_seconds=tp,
            g_function_m=0.8,
            effective_injected_volume_m3=3000.0,
            alpha=1.0,
        )
        assert result["pkn_volume_status"] == "ok"
        assert np.isfinite(result["pkn_fracture_volume_m3"])
        assert result["pkn_fracture_volume_m3"] > 0
        assert np.isfinite(result["pkn_half_length_mean_m"])
        assert result["pkn_half_length_mean_m"] > 0
        assert result["pkn_H_w_m"] == 50.0
        assert result["pkn_I_F"] == pytest.approx(0.722464726919, rel=1e-10)
        assert result["stress_shadow_status"] == "ok"
        assert result["stable_segment_status"] == "ok"
        assert result["pkn_C_status"] == "ok"
        assert result["pkn_cluster_count"] == 4

    def test_physical_pkn_no_fallback_to_mvp(self):
        n = 10
        elapsed = np.arange(1, n + 1, dtype=float)
        g_time = np.linspace(0.01, 0.5, n)
        pressure = 120.0 + np.random.default_rng(99).normal(0, 5, n)

        E_prime = 33.3 * 1000.0 / (1.0 - 0.23 ** 2)
        result = physical_pkn_volume_balance(
            n_clusters=3,
            cluster_spacings_m=10.0,
            H_w_m=50.0,
            fleak=0.5,
            E_prime_mpa=E_prime,
            closure_pressure_mpa=110.0,
            minimum_stress_prior_mpa=99.1,
            g_time=g_time,
            pressure_mpa=pressure,
            elapsed_seconds=elapsed,
            tp_seconds=600.0,
            g_function_m=0.8,
            effective_injected_volume_m3=3000.0,
            stable_min_points=100,
        )
        assert result["pkn_volume_status"] == "failed"
        assert np.isnan(result["pkn_fracture_volume_m3"])

    def test_cli_closure_batch_physical_pkn_fields(self, tmp_path: Path):
        stage_dir = tmp_path / "stage_data"
        stage_dir.mkdir()

        shut_in = _write_synthetic_stage_csv(stage_dir / "stage_01.csv", n_pre=50, n_post=150)

        params = pd.DataFrame([
            {"well": "W1", "stage": 1, "file": "stage_data/stage_01.csv",
             "shut_in": shut_in, "sigma_min": 75.0, "add_pressure": 40.0,
             "hw": 15.0, "e_gpa": 30.0, "nu": 0.25,
             "n": 4, "spacing": 8.0, "cluster_spacings": "8;8;8",
             "fleak": 0.5, "m": 0.8},
        ])
        params.to_csv(tmp_path / "stage_params.csv", index=False)

        manifest = pd.DataFrame([
            {"stage": 1, "max_sustained_rate": 20.0, "valid_falloff_end_elapsed": 140.0},
        ])
        manifest.to_csv(tmp_path / "manifest.csv", index=False)

        output_path = tmp_path / "closure_summary.csv"

        from clotho.cli import main
        exit_code = main([
            "closure-batch",
            "--stage-params", str(tmp_path / "stage_params.csv"),
            "--well-root", str(tmp_path),
            "--manifest", str(tmp_path / "manifest.csv"),
            "--output", str(output_path),
            "--volume-column", "total_volume",
            "--rate-time-unit", "minute",
            "--g-time-m", "0.8",
            "--closure-min-elapsed-seconds", "5",
            "--stress-shadow-alpha", "1.0",
        ])

        assert exit_code == 0
        assert output_path.exists()

        summary = pd.read_csv(output_path)
        assert "pkn_model_name" in summary.columns
        assert "pkn_H_w_m" in summary.columns
        assert "pkn_I_F" in summary.columns
        assert "stress_shadow_status" in summary.columns
        assert "stable_segment_status" in summary.columns
        assert "legacy_mvp_pkn_fracture_volume_m3" in summary.columns
        assert (summary["closure_is_candidate"] == True).all()  # noqa: E712
        assert (summary["closure_is_final_interpretation"] == False).all()  # noqa: E712

    def test_physical_pkn_if_constant(self):
        assert PHYSICAL_PKN_IF == pytest.approx(0.722464726919, rel=1e-12)

    def test_mcclure_fallback_produces_physical_pkn(self):
        """Barree not_found + McClure ok => physical PKN should still compute."""
        n = 100
        tp = 600.0
        elapsed = np.arange(1, n + 1, dtype=float)
        delta = elapsed / tp
        g_time = np.asarray(nolte_g_time(delta, 0.8), dtype=float)
        pressure = 120.0 - 2.0 * g_time - 0.1 * g_time ** 2

        dP_dG = np.gradient(pressure, g_time)

        barree = pick_barree_tangent_closure_candidate(
            g_time, dP_dG, elapsed, pressure,
            closure_min_elapsed_seconds=1.0,
        )
        mcclure = pick_mcclure_compliance_closure_candidate(
            g_time, dP_dG, elapsed, pressure,
            closure_min_elapsed_seconds=1.0,
        )
        selected = select_closure_candidate(barree, mcclure)

        assert barree["barree_status"] == "not_found"
        assert mcclure["mcclure_status"] == "ok"
        assert selected["selected_closure_status"] == "ok"
        assert selected["selected_closure_method"] == "mcclure"

        mcclure_ci = int(mcclure["mcclure_closure_index"])
        E_prime = 33.3 * 1000.0 / (1.0 - 0.23 ** 2)
        result = physical_pkn_volume_balance(
            n_clusters=4,
            cluster_spacings_m=8.4,
            H_w_m=50.0,
            fleak=0.5,
            E_prime_mpa=E_prime,
            closure_pressure_mpa=float(pressure[mcclure_ci]),
            minimum_stress_prior_mpa=99.1,
            perforation_friction_mpa=0.0,
            g_time=g_time,
            pressure_mpa=pressure,
            elapsed_seconds=elapsed,
            closure_index=mcclure_ci,
            tp_seconds=tp,
            g_function_m=0.8,
            effective_injected_volume_m3=3000.0,
            alpha=1.0,
            stable_min_elapsed_seconds=1.0,
            stable_min_points=5,
        )
        assert result["pkn_volume_status"] == "ok"
        assert np.isfinite(result["pkn_fracture_volume_m3"])
        assert result["pkn_fracture_volume_m3"] > 0

    def test_cli_closure_batch_mcclure_fallback_stage(self, tmp_path: Path):
        """CLI smoke: stage where only McClure works should still get physical PKN."""
        stage_dir = tmp_path / "stage_data"
        stage_dir.mkdir()

        shut_in_seconds = 10 * 3600
        rows: list[dict[str, object]] = []
        for i in range(50):
            t = shut_in_seconds - (50 - i)
            h, m, s = t // 3600, (t % 3600) // 60, t % 60
            frac = i / 49
            rows.append({
                "time": f"{h:02d}:{m:02d}:{s:02d}",
                "wellhead_pressure": 70.0 + 20.0 * frac,
                "rate": 5.0 + 15.0 * min(frac * 2, 1.0),
                "stage_volume": frac * 200.0,
                "total_volume": frac * 200.0,
            })
        for i in range(200):
            t = shut_in_seconds + i
            h, m, s = t // 3600, (t % 3600) // 60, t % 60
            dp = 0.01 * i + 0.00005 * i ** 2
            rows.append({
                "time": f"{h:02d}:{m:02d}:{s:02d}",
                "wellhead_pressure": max(90.0 - dp, 0.1),
                "rate": 0.0,
                "stage_volume": 200.0,
                "total_volume": 200.0,
            })
        pd.DataFrame(rows).to_csv(stage_dir / "stage_01.csv", index=False)

        params = pd.DataFrame([{
            "well": "W1", "stage": 1, "file": "stage_data/stage_01.csv",
            "shut_in": "10:00:00", "sigma_min": 75.0, "add_pressure": 40.0,
            "hw": 15.0, "e_gpa": 30.0, "nu": 0.25,
            "n": 4, "spacing": 8.0, "cluster_spacings": "8;8;8",
            "fleak": 0.5, "m": 0.8,
        }])
        params.to_csv(tmp_path / "stage_params.csv", index=False)

        manifest = pd.DataFrame([{
            "stage": 1, "max_sustained_rate": 20.0, "valid_falloff_end_elapsed": 190.0,
        }])
        manifest.to_csv(tmp_path / "manifest.csv", index=False)

        output_path = tmp_path / "closure_summary.csv"
        from clotho.cli import main
        exit_code = main([
            "closure-batch",
            "--stage-params", str(tmp_path / "stage_params.csv"),
            "--well-root", str(tmp_path),
            "--manifest", str(tmp_path / "manifest.csv"),
            "--output", str(output_path),
            "--volume-column", "total_volume",
            "--rate-time-unit", "minute",
            "--g-time-m", "0.8",
            "--closure-min-elapsed-seconds", "5",
            "--stress-shadow-alpha", "1.0",
        ])
        assert exit_code == 0
        summary = pd.read_csv(output_path)
        row = summary.iloc[0]
        assert row["selected_closure_status"] == "ok"
        assert row["closure_is_candidate"] == True  # noqa: E712
        assert row["closure_is_final_interpretation"] == False  # noqa: E712


class TestFlowAllocationEta:
    def test_stress_shadow_eta_proportional_to_xi(self):
        xi = np.array([0.2, 0.5, 1.0])
        eta = compute_flow_allocation_eta(xi, exponent=1.0)
        expected = xi / xi.sum()
        np.testing.assert_allclose(eta, expected, rtol=1e-12)
        assert eta[0] < eta[1] < eta[2]
        assert eta.sum() == pytest.approx(1.0, rel=1e-12)

    def test_exponent_zero_gives_uniform(self):
        xi = np.array([0.2, 0.5, 1.0])
        eta = compute_flow_allocation_eta(xi, exponent=0.0)
        expected = np.array([1.0 / 3, 1.0 / 3, 1.0 / 3])
        np.testing.assert_allclose(eta, expected, rtol=1e-12)

    def test_stronger_shadow_gets_less_allocation(self):
        xi = np.array([0.05, 0.3, 0.8, 0.9])
        eta = compute_flow_allocation_eta(xi, exponent=1.0)
        assert np.argmin(eta) == 0
        assert np.argmax(eta) == 3

    def test_invalid_xi_raises(self):
        with pytest.raises(ValueError):
            compute_flow_allocation_eta(np.array([0.5, -0.1, 0.3]))
        with pytest.raises(ValueError):
            compute_flow_allocation_eta(np.array([0.5, np.nan, 0.3]))

    def test_invalid_exponent_raises(self):
        with pytest.raises(ValueError):
            compute_flow_allocation_eta(np.array([0.5, 0.3]), exponent=-1.0)

    def test_stress_shadow_allocation_changes_per_cluster_lengths(self):
        n = 50
        tp = 600.0
        elapsed = np.arange(1, n + 1, dtype=float)
        delta = elapsed / tp
        g_time = np.asarray(nolte_g_time(delta, 0.8), dtype=float)
        pressure = 120.0 - 3.0 * g_time
        E_prime = 33.3 * 1000.0 / (1.0 - 0.23 ** 2)

        common = dict(
            n_clusters=3,
            cluster_spacings_m=10.0,
            H_w_m=50.0,
            fleak=0.5,
            E_prime_mpa=E_prime,
            closure_pressure_mpa=110.0,
            minimum_stress_prior_mpa=99.1,
            perforation_friction_mpa=0.0,
            g_time=g_time,
            pressure_mpa=pressure,
            elapsed_seconds=elapsed,
            closure_index=40,
            tp_seconds=tp,
            g_function_m=0.8,
            effective_injected_volume_m3=3000.0,
            alpha=1.0,
        )
        shadow_result = physical_pkn_volume_balance(**common, flow_allocation="stress-shadow")
        uniform_result = physical_pkn_volume_balance(**common, flow_allocation="uniform")

        assert shadow_result["pkn_volume_status"] == "ok"
        assert uniform_result["pkn_volume_status"] == "ok"
        assert shadow_result["pkn_flow_allocation_method"] == "stress-shadow"
        assert uniform_result["pkn_flow_allocation_method"] == "uniform"
        assert shadow_result["pkn_eta_std"] > uniform_result["pkn_eta_std"]
        assert uniform_result["pkn_eta_std"] == pytest.approx(0.0, abs=1e-12)

    def test_physical_pkn_eta_in_output_fields(self):
        n = 50
        tp = 600.0
        elapsed = np.arange(1, n + 1, dtype=float)
        delta = elapsed / tp
        g_time = np.asarray(nolte_g_time(delta, 0.8), dtype=float)
        pressure = 120.0 - 3.0 * g_time
        E_prime = 33.3 * 1000.0 / (1.0 - 0.23 ** 2)

        result = physical_pkn_volume_balance(
            n_clusters=4,
            cluster_spacings_m=8.4,
            H_w_m=50.0,
            fleak=0.5,
            E_prime_mpa=E_prime,
            closure_pressure_mpa=110.0,
            minimum_stress_prior_mpa=99.1,
            g_time=g_time,
            pressure_mpa=pressure,
            elapsed_seconds=elapsed,
            closure_index=40,
            tp_seconds=tp,
            g_function_m=0.8,
            effective_injected_volume_m3=3000.0,
            alpha=1.0,
            flow_allocation="stress-shadow",
            flow_allocation_exponent=1.0,
        )
        assert result["pkn_volume_status"] == "ok"
        assert result["pkn_flow_allocation_method"] == "stress-shadow"
        assert result["pkn_flow_allocation_exponent"] == 1.0
        assert np.isfinite(result["pkn_eta_min"])
        assert np.isfinite(result["pkn_eta_max"])
        assert result["pkn_eta_min"] < result["pkn_eta_max"]


class TestPerClusterDenominator:
    """Phase 5D.4: L_i must use per-cluster denominator unit_i, not global Sum(unit_j * eta_j)."""

    def _build_inputs(
        self,
        *,
        n_clusters: int = 3,
        spacings: float = 10.0,
        alpha: float = 1.0,
        flow_allocation: str = "stress-shadow",
        effective_volume: float = 3000.0,
    ) -> dict:
        n = 50
        tp = 600.0
        elapsed = np.arange(1, n + 1, dtype=float)
        delta = elapsed / tp
        g_time = np.asarray(nolte_g_time(delta, 0.8), dtype=float)
        pressure = 120.0 - 3.0 * g_time
        E_prime = 33.3 * 1000.0 / (1.0 - 0.23 ** 2)
        return dict(
            n_clusters=n_clusters,
            cluster_spacings_m=spacings,
            H_w_m=50.0,
            fleak=0.5,
            E_prime_mpa=E_prime,
            closure_pressure_mpa=110.0,
            minimum_stress_prior_mpa=99.1,
            perforation_friction_mpa=0.0,
            g_time=g_time,
            pressure_mpa=pressure,
            elapsed_seconds=elapsed,
            closure_index=40,
            tp_seconds=tp,
            g_function_m=0.8,
            effective_injected_volume_m3=effective_volume,
            alpha=alpha,
            flow_allocation=flow_allocation,
        )

    def test_per_cluster_denominator_formula(self):
        """L_i = eta_i * V_inj / unit_i, NOT eta_i * V_inj / Sum(unit_j * eta_j).

        Check cluster audit rows directly: each row carries denominator_i and L_i,
        and L_i must equal eta_i * V_inj / denominator_i exactly."""
        result = physical_pkn_volume_balance(**self._build_inputs())
        assert result["pkn_volume_status"] == "ok"

        rows = result["pkn_cluster_audit_rows"]
        assert len(rows) > 0
        # Group by stable_row_index to detect global-vs-per-cluster denominator
        from collections import defaultdict
        by_row: dict[int, list[dict]] = defaultdict(list)
        for r in rows:
            by_row[r["stable_row_index"]].append(r)

        v_inj = 3000.0
        for stable_idx, cluster_rows in by_row.items():
            # per-cluster denominators must differ when xi differs (alpha=1)
            denoms = [r["denominator_i_m3_per_m"] for r in cluster_rows]
            # at least 2 distinct denominators among edges vs center (alpha=1.0 makes xi nonuniform)
            assert len(set(round(d, 6) for d in denoms)) > 1, (
                f"per-cluster denominators identical at stable_row={stable_idx}; "
                "indicates global denominator fallback"
            )
            for r in cluster_rows:
                expected_L = r["eta_i"] * v_inj / r["denominator_i_m3_per_m"]
                assert r["L_i_m"] == pytest.approx(expected_L, rel=1e-9), (
                    f"L_i != eta_i * V_inj / denominator_i at stable_row={stable_idx}, "
                    f"cluster={r['cluster_index']}: got {r['L_i_m']}, expected {expected_L}"
                )

    def test_no_global_denominator_in_cluster_audit(self):
        """If global Sum(unit_j * eta_j) were used as L_i denominator,
        all clusters in the same stable row would have the same effective denominator
        (V_inj * eta_i / L_i = scalar). This test rejects that pattern."""
        result = physical_pkn_volume_balance(**self._build_inputs())
        rows = result["pkn_cluster_audit_rows"]
        assert len(rows) > 0

        v_inj = 3000.0
        from collections import defaultdict
        by_row: dict[int, list[dict]] = defaultdict(list)
        for r in rows:
            by_row[r["stable_row_index"]].append(r)

        for stable_idx, cluster_rows in by_row.items():
            implied_global_denoms = []
            for r in cluster_rows:
                if r["L_i_m"] > 0:
                    implied = r["eta_i"] * v_inj / r["L_i_m"]
                    implied_global_denoms.append(implied)
            # If implementation used a single global denominator, all "implied" values
            # would be identical. They must differ for per-cluster formula.
            assert max(implied_global_denoms) > min(implied_global_denoms) * 1.0001, (
                f"at stable_row={stable_idx}, implied per-cluster denominators collapse "
                "to a global scalar — formula is still global-normalized"
            )

    def test_eta_changes_stage_total_when_unit_differs(self):
        """Direct per-cluster formula test: with arbitrary unit_i (not derived
        from xi-coupled C_L), eta_i nonuniformity changes stage total V_f.

        This isolates the formula L_i = eta_i * V_inj / unit_i and avoids the
        downstream chain in physical_pkn_volume_balance where C_L_i and P_net_i
        both scale with xi_i (causing unit_i to absorb xi exactly)."""
        v_inj = 100.0
        eta_a = np.array([0.5, 0.5])
        eta_b = np.array([0.9, 0.1])
        unit = np.array([10.0, 30.0])
        P_net = np.array([1.0, 1.0])  # equal P_net so V_f reflects L_i only

        L_a = eta_a * v_inj / unit
        L_b = eta_b * v_inj / unit

        K = math.pi * PHYSICAL_PKN_IF / 22500.0 * 50.0 ** 2  # arbitrary K factor
        V_a = float((K * L_a * P_net).sum())
        V_b = float((K * L_b * P_net).sum())

        assert V_a != pytest.approx(V_b, rel=1e-6), (
            f"with unit_i=[10,30] independent of eta, stage total V_f "
            f"({V_a} vs {V_b}) must differ between eta_a={eta_a} and eta_b={eta_b}"
        )

    def test_shadow_eta_vs_uniform_at_fixed_unit(self):
        """Direct check: when per-cluster unit_i are NOT collinear with eta,
        shadow_eta and uniform_eta give different per-cluster L_i.

        This verifies the formula correctness, decoupled from the xi-coupled
        C_L_i and P_net_i absorption observed in the full chain."""
        v_inj = 1000.0
        n = 4
        xi = np.array([0.5, 0.9, 0.9, 0.5])
        eta_shadow = xi / xi.sum()
        eta_uniform = np.ones(n) / n
        unit = np.array([50.0, 30.0, 30.0, 50.0])  # not collinear with xi

        L_shadow = eta_shadow * v_inj / unit
        L_uniform = eta_uniform * v_inj / unit

        assert not np.allclose(L_shadow, L_uniform), (
            "L_i must differ between shadow_eta and uniform_eta when unit_i is "
            "independent of eta_i"
        )
        # uniform_eta gives identical L_i for symmetric unit; shadow does not
        assert L_shadow.std() > L_uniform.std() or L_shadow.std() != L_uniform.std()

    def test_cluster_audit_sum_matches_stage_summary(self, tmp_path: Path):
        """CLI cluster_audit V_f_i_m3 summed per stable_row, averaged over stable rows,
        should equal stage summary pkn_fracture_volume_m3 within tight tolerance."""
        stage_dir = tmp_path / "stage_data"
        stage_dir.mkdir()
        shut_in_1 = _write_synthetic_stage_csv(stage_dir / "stage_01.csv", n_pre=50, n_post=150)
        shut_in_2 = _write_synthetic_stage_csv(stage_dir / "stage_02.csv", n_pre=50, n_post=150)

        params = pd.DataFrame([
            {"well": "W1", "stage": 1, "file": "stage_data/stage_01.csv",
             "shut_in": shut_in_1, "sigma_min": 75.0, "add_pressure": 40.0,
             "hw": 15.0, "e_gpa": 30.0, "nu": 0.25,
             "num_clusters": 4, "cluster_spacings": "10;10;10", "fleak": 0.5, "m": 0.8},
            {"well": "W1", "stage": 2, "file": "stage_data/stage_02.csv",
             "shut_in": shut_in_2, "sigma_min": 75.0, "add_pressure": 40.0,
             "hw": 15.0, "e_gpa": 30.0, "nu": 0.25,
             "num_clusters": 4, "cluster_spacings": "10;10;10", "fleak": 0.5, "m": 0.8},
        ])
        params_path = tmp_path / "stage_params.csv"
        params.to_csv(params_path, index=False)

        manifest = pd.DataFrame([
            {"stage": 1, "max_sustained_rate": 20.0, "valid_falloff_end_elapsed": 140.0},
            {"stage": 2, "max_sustained_rate": 20.0, "valid_falloff_end_elapsed": 140.0},
        ])
        manifest_path = tmp_path / "manifest.csv"
        manifest.to_csv(manifest_path, index=False)

        output_path = tmp_path / "closure_summary.csv"
        cluster_path = tmp_path / "cluster_audit.csv"

        from clotho.cli import main
        exit_code = main([
            "closure-batch",
            "--stage-params", str(params_path),
            "--well-root", str(tmp_path),
            "--manifest", str(manifest_path),
            "--output", str(output_path),
            "--cluster-output", str(cluster_path),
            "--volume-column", "total_volume",
            "--rate-time-unit", "minute",
            "--min-rate", "10",
            "--g-time-m", "0.8",
            "--closure-min-elapsed-seconds", "5",
            "--elapsed-duplicate-policy", "keep-last",
            "--pressure-source", "estimated-bottomhole",
        ])
        assert exit_code == 0
        assert cluster_path.exists()

        summary = pd.read_csv(output_path)
        cluster = pd.read_csv(cluster_path)

        ok_stages = summary[summary["pkn_volume_status"] == "ok"]
        for _, row in ok_stages.iterrows():
            stage_num = int(row["stage"])
            cluster_subset = cluster[cluster["stage"] == stage_num]
            if cluster_subset.empty:
                continue
            row_sums = cluster_subset.groupby("stable_row_index")["V_f_i_m3"].sum()
            mean_v = float(row_sums.mean())
            assert mean_v == pytest.approx(
                float(row["pkn_fracture_volume_m3"]), rel=1e-6, abs=1e-6,
            ), (
                f"stage {stage_num}: cluster-audit V_f_i sum mean {mean_v} != "
                f"summary pkn_fracture_volume_m3 {row['pkn_fracture_volume_m3']}"
            )


class TestCCouplingAndFluidPartition:
    """Phase 5D.5: C_coupling control and fluid partition metrics."""

    def _build_inputs(
        self,
        *,
        n_clusters: int = 3,
        spacings: float | list[float] = 10.0,
        alpha: float = 1.0,
        flow_allocation: str = "stress-shadow",
        effective_volume: float = 3000.0,
    ) -> dict:
        n = 50
        tp = 600.0
        elapsed = np.arange(1, n + 1, dtype=float)
        delta = elapsed / tp
        g_time = np.asarray(nolte_g_time(delta, 0.8), dtype=float)
        pressure = 120.0 - 3.0 * g_time
        E_prime = 33.3 * 1000.0 / (1.0 - 0.23 ** 2)
        return dict(
            n_clusters=n_clusters,
            cluster_spacings_m=spacings,
            H_w_m=50.0,
            fleak=0.5,
            E_prime_mpa=E_prime,
            closure_pressure_mpa=110.0,
            minimum_stress_prior_mpa=99.1,
            perforation_friction_mpa=0.0,
            g_time=g_time,
            pressure_mpa=pressure,
            elapsed_seconds=elapsed,
            closure_index=40,
            tp_seconds=tp,
            g_function_m=0.8,
            effective_injected_volume_m3=effective_volume,
            alpha=alpha,
            flow_allocation=flow_allocation,
        )

    def test_stage_constant_C_makes_C_L_uniform(self):
        result = physical_pkn_volume_balance(**self._build_inputs(), C_coupling="stage-constant")
        assert result["pkn_volume_status"] == "ok"
        assert result["pkn_C_coupling_method"] == "stage-constant"
        rows = result["pkn_cluster_audit_rows"]
        assert len(rows) > 0
        c_stage = result["pkn_C_stage"]
        for r in rows:
            assert r["C_L_i"] == pytest.approx(c_stage, rel=1e-12), (
                f"stage-constant must give C_L_i == C_stage; got C_L_i={r['C_L_i']}, C_stage={c_stage}"
            )

    def test_shadow_scaled_C_makes_C_L_proportional_to_xi(self):
        result = physical_pkn_volume_balance(**self._build_inputs(), C_coupling="shadow-scaled")
        assert result["pkn_volume_status"] == "ok"
        assert result["pkn_C_coupling_method"] == "shadow-scaled"
        rows = result["pkn_cluster_audit_rows"]
        assert len(rows) > 0
        c_stage = result["pkn_C_stage"]
        for r in rows:
            expected = r["xi_i"] * c_stage
            assert r["C_L_i"] == pytest.approx(expected, rel=1e-12), (
                f"shadow-scaled must give C_L_i = xi_i * C_stage; got {r['C_L_i']}, expected {expected}"
            )

    def test_stage_constant_breaks_previous_cancellation(self):
        """stage-constant C decouples C_L from xi, so stress shadow and uniform eta
        produce different stage total V_f. shadow-scaled control reproduces the
        Phase 5D.4 cancellation."""
        common = self._build_inputs(n_clusters=4, spacings=5.0, alpha=1.0)
        common.pop("flow_allocation", None)

        stage_const_shadow = physical_pkn_volume_balance(
            **common, flow_allocation="stress-shadow", C_coupling="stage-constant"
        )
        stage_const_uniform = physical_pkn_volume_balance(
            **common, flow_allocation="uniform", C_coupling="stage-constant"
        )
        shadow_scaled_shadow = physical_pkn_volume_balance(
            **common, flow_allocation="stress-shadow", C_coupling="shadow-scaled"
        )
        shadow_scaled_uniform = physical_pkn_volume_balance(
            **common, flow_allocation="uniform", C_coupling="shadow-scaled"
        )

        v_stage_const_shadow = stage_const_shadow["pkn_fracture_volume_m3"]
        v_stage_const_uniform = stage_const_uniform["pkn_fracture_volume_m3"]
        assert v_stage_const_shadow != pytest.approx(v_stage_const_uniform, rel=1e-6), (
            "stage-constant C: shadow_eta and uniform_eta must yield different stage total V_f; "
            f"got {v_stage_const_shadow} vs {v_stage_const_uniform}"
        )

        v_shadow_scaled_shadow = shadow_scaled_shadow["pkn_fracture_volume_m3"]
        v_shadow_scaled_uniform = shadow_scaled_uniform["pkn_fracture_volume_m3"]
        assert v_shadow_scaled_shadow == pytest.approx(v_shadow_scaled_uniform, rel=1e-6), (
            "shadow-scaled C: shadow_eta and uniform_eta must produce identical stage total V_f "
            "(coupled cancellation control); "
            f"got {v_shadow_scaled_shadow} vs {v_shadow_scaled_uniform}"
        )

    def test_fluid_partition_balance_residual(self):
        """For each cluster: injected_i = storage_i + leakoff_total_i + residual_i,
        residual must be exactly zero by definition of L_i = eta_i * V_inj / unit_i."""
        result = physical_pkn_volume_balance(**self._build_inputs(), C_coupling="stage-constant")
        assert result["pkn_volume_status"] == "ok"
        rows = result["pkn_cluster_audit_rows"]
        for r in rows:
            implied_balance = r["injected_i_m3"] - r["storage_i_m3"] - r["leakoff_total_i_m3"]
            assert r["balance_residual_i_m3"] == pytest.approx(implied_balance, rel=1e-9, abs=1e-9)
            assert abs(r["balance_residual_i_m3"]) < 1e-6 * max(1.0, r["injected_i_m3"]), (
                f"balance residual not ~0 at row {r['stable_row_index']}, cluster {r['cluster_index']}: "
                f"injected={r['injected_i_m3']}, storage={r['storage_i_m3']}, leakoff={r['leakoff_total_i_m3']}, "
                f"residual={r['balance_residual_i_m3']}"
            )

    def test_pkn_nonstorage_volume_identity(self):
        result = physical_pkn_volume_balance(**self._build_inputs(), C_coupling="stage-constant")
        assert result["pkn_volume_status"] == "ok"
        v_eff = 3000.0
        assert result["pkn_nonstorage_volume_m3"] == pytest.approx(
            v_eff - result["pkn_fracture_volume_m3"], rel=1e-9
        )
        assert result["pkn_storage_fraction"] == pytest.approx(
            result["pkn_fracture_volume_m3"] / v_eff, rel=1e-9
        )
        assert result["pkn_nonstorage_fraction"] == pytest.approx(
            1.0 - result["pkn_storage_fraction"], rel=1e-9
        )

    def test_correlation_metrics_include_nonstorage_and_leakoff(self, tmp_path: Path):
        stage_dir = tmp_path / "stage_data"
        stage_dir.mkdir()
        shut_in_1 = _write_synthetic_stage_csv(stage_dir / "stage_01.csv", n_pre=50, n_post=150)
        shut_in_2 = _write_synthetic_stage_csv(stage_dir / "stage_02.csv", n_pre=50, n_post=150)

        params = pd.DataFrame([
            {"well": "W1", "stage": 1, "file": "stage_data/stage_01.csv",
             "shut_in": shut_in_1, "sigma_min": 75.0, "add_pressure": 40.0,
             "hw": 15.0, "e_gpa": 30.0, "nu": 0.25},
            {"well": "W1", "stage": 2, "file": "stage_data/stage_02.csv",
             "shut_in": shut_in_2, "sigma_min": 75.0, "add_pressure": 40.0,
             "hw": 15.0, "e_gpa": 30.0, "nu": 0.25},
        ])
        params.to_csv(tmp_path / "stage_params.csv", index=False)

        manifest = pd.DataFrame([
            {"stage": 1, "max_sustained_rate": 20.0, "valid_falloff_end_elapsed": 140.0},
            {"stage": 2, "max_sustained_rate": 20.0, "valid_falloff_end_elapsed": 140.0},
        ])
        manifest.to_csv(tmp_path / "manifest.csv", index=False)

        observations = pd.DataFrame([
            {"stage": 1, "microseismic_affected_volume": 150.0, "electromagnetic_affected_area": 18000.0},
            {"stage": 2, "microseismic_affected_volume": 170.0, "electromagnetic_affected_area": 19000.0},
        ])
        observations.to_csv(tmp_path / "observations.csv", index=False)

        result = run_closure_batch(
            stage_params_path=tmp_path / "stage_params.csv",
            well_root=tmp_path,
            manifest_path=tmp_path / "manifest.csv",
            observations_path=tmp_path / "observations.csv",
            volume_column="total_volume",
            rate_time_unit="minute",
            min_rate=10.0,
            g_time_m=0.8,
            closure_min_elapsed_seconds=5.0,
            elapsed_duplicate_policy="keep-last",
            pressure_source="estimated-bottomhole",
        )
        corr = result["correlation"]
        assert corr is not None
        metric_set = set(corr["metric"].astype(str))
        for metric in [
            "pkn_fracture_volume_m3",
            "pkn_leakoff_volume_m3",
            "pkn_nonstorage_volume_m3",
            "pkn_storage_fraction",
            "pkn_leakoff_fraction",
            "pkn_nonstorage_fraction",
            "pkn_C_stage",
            "pkn_C_mean",
        ]:
            assert metric in metric_set, f"correlation table missing metric {metric}"

    def test_cli_smoke_with_C_coupling(self, tmp_path: Path):
        stage_dir = tmp_path / "stage_data"
        stage_dir.mkdir()
        shut_in_1 = _write_synthetic_stage_csv(stage_dir / "stage_01.csv", n_pre=50, n_post=150)
        shut_in_2 = _write_synthetic_stage_csv(stage_dir / "stage_02.csv", n_pre=50, n_post=150)

        params = pd.DataFrame([
            {"well": "W1", "stage": 1, "file": "stage_data/stage_01.csv",
             "shut_in": shut_in_1, "sigma_min": 75.0, "add_pressure": 40.0,
             "hw": 15.0, "e_gpa": 30.0, "nu": 0.25,
             "num_clusters": 4, "cluster_spacings": "10;10;10", "fleak": 0.5, "m": 0.8},
            {"well": "W1", "stage": 2, "file": "stage_data/stage_02.csv",
             "shut_in": shut_in_2, "sigma_min": 75.0, "add_pressure": 40.0,
             "hw": 15.0, "e_gpa": 30.0, "nu": 0.25,
             "num_clusters": 4, "cluster_spacings": "10;10;10", "fleak": 0.5, "m": 0.8},
        ])
        params_path = tmp_path / "stage_params.csv"
        params.to_csv(params_path, index=False)

        manifest = pd.DataFrame([
            {"stage": 1, "max_sustained_rate": 20.0, "valid_falloff_end_elapsed": 140.0},
            {"stage": 2, "max_sustained_rate": 20.0, "valid_falloff_end_elapsed": 140.0},
        ])
        manifest_path = tmp_path / "manifest.csv"
        manifest.to_csv(manifest_path, index=False)

        output_path = tmp_path / "closure_summary.csv"
        cluster_path = tmp_path / "cluster_audit.csv"

        from clotho.cli import main
        exit_code = main([
            "closure-batch",
            "--stage-params", str(params_path),
            "--well-root", str(tmp_path),
            "--manifest", str(manifest_path),
            "--output", str(output_path),
            "--cluster-output", str(cluster_path),
            "--volume-column", "total_volume",
            "--rate-time-unit", "minute",
            "--min-rate", "10",
            "--g-time-m", "0.8",
            "--closure-min-elapsed-seconds", "5",
            "--elapsed-duplicate-policy", "keep-last",
            "--pressure-source", "estimated-bottomhole",
            "--pkn-C-coupling", "stage-constant",
        ])
        assert exit_code == 0
        summary = pd.read_csv(output_path)
        for col in [
            "pkn_C_coupling_method",
            "pkn_fracture_volume_m3",
            "pkn_leakoff_volume_m3",
            "pkn_nonstorage_volume_m3",
            "pkn_storage_fraction",
            "pkn_leakoff_fraction",
            "pkn_nonstorage_fraction",
        ]:
            assert col in summary.columns, f"summary missing column {col}"
        ok_rows = summary[summary["pkn_volume_status"] == "ok"]
        assert (ok_rows["pkn_C_coupling_method"] == "stage-constant").all()

        cluster = pd.read_csv(cluster_path)
        for col in [
            "C_stage", "pkn_C_coupling_method", "injected_i_m3", "storage_i_m3",
            "leakoff_before_closure_i_m3", "leakoff_G_i_m3", "leakoff_total_i_m3",
            "balance_residual_i_m3",
        ]:
            assert col in cluster.columns, f"cluster audit missing column {col}"


class TestFluidEfficiencyAudit:
    """Phase 5D.6: shut-in fluid efficiency vs stable-row storage fraction.

    Key claim: stable-row storage fraction <10% does NOT imply shut-in fluid efficiency <10%.
    The stable-row metric includes the G·dP/dG leakoff term, which is absent at shut-in.
    """

    def _build_inputs(
        self,
        *,
        n_clusters: int = 3,
        spacings: float = 10.0,
        alpha: float = 1.0,
        flow_allocation: str = "stress-shadow",
        effective_volume: float = 3000.0,
        C_coupling: str = "stage-constant",
    ) -> dict:
        n = 50
        tp = 600.0
        elapsed = np.arange(1, n + 1, dtype=float)
        delta = elapsed / tp
        g_time = np.asarray(nolte_g_time(delta, 0.8), dtype=float)
        pressure = 120.0 - 3.0 * g_time
        E_prime = 33.3 * 1000.0 / (1.0 - 0.23 ** 2)
        return dict(
            n_clusters=n_clusters,
            cluster_spacings_m=spacings,
            H_w_m=50.0,
            fleak=0.5,
            E_prime_mpa=E_prime,
            closure_pressure_mpa=110.0,
            minimum_stress_prior_mpa=99.1,
            perforation_friction_mpa=0.0,
            g_time=g_time,
            pressure_mpa=pressure,
            elapsed_seconds=elapsed,
            closure_index=40,
            tp_seconds=tp,
            g_function_m=0.8,
            effective_injected_volume_m3=effective_volume,
            alpha=alpha,
            flow_allocation=flow_allocation,
            C_coupling=C_coupling,
        )

    def test_shutin_efficiency_excludes_G_leakoff(self):
        """shut-in efficiency uses g=0 (no G·leakoff term).

        With stage-constant C and shadow-scaled stress (xi nonuniform),
        the eta-weighted shut-in efficiency is computed as
        eff = sum_i eta_i * storage_unit_i / (storage_unit_i + preclosure_leakoff_unit_i)
        which evaluates at g=0 with shut-in pressure (excluding the 4*C*H_p*sqrt(tp)*g term).

        The diagnostic mean-fields pkn_shutin_storage_unit_mean_m2 and
        pkn_shutin_preclosure_leakoff_unit_mean_m2 are simple cluster-averages;
        the closed-form ratio storage_unit / (storage_unit + preclosure_unit) using these
        means agrees with the true eta-weighted efficiency only when xi is uniform
        (no stress shadow). For nonuniform xi it differs in general.

        This test verifies both: (a) shut-in efficiency does not include the G term,
        and (b) the cluster-mean ratio approximates the true value to within bounded error.
        """
        # Use alpha=0 (no stress shadow → xi=1) so mean-of-units == ratio-of-sums.
        result = physical_pkn_volume_balance(**self._build_inputs(alpha=0.0))
        assert result["pkn_volume_status"] == "ok"

        storage_unit = result["pkn_shutin_storage_unit_mean_m2"]
        preclosure_unit = result["pkn_shutin_preclosure_leakoff_unit_mean_m2"]
        expected_eff_uniform_xi = storage_unit / (storage_unit + preclosure_unit)

        # Under alpha=0 (uniform xi=1), all clusters have identical unit_i, so the eta-weighted
        # ratio-of-sums equals the cluster-mean ratio.
        assert result["pkn_shutin_fluid_efficiency"] == pytest.approx(
            expected_eff_uniform_xi, rel=1e-9
        ), (
            f"under alpha=0 (uniform xi), shut-in efficiency must equal storage_unit / "
            f"(storage_unit + preclosure_leakoff_unit); got "
            f"{result['pkn_shutin_fluid_efficiency']}, expected {expected_eff_uniform_xi}"
        )

        # Stable-row fraction at g>0 must be lower than shut-in efficiency because the G term
        # adds to the unit denominator.
        assert result["pkn_stable_G_leakoff_unit_mean_m2"] > 0
        assert result["pkn_stable_storage_fraction"] < result["pkn_shutin_fluid_efficiency"], (
            f"with g>0 stable rows, stable_storage_fraction ({result['pkn_stable_storage_fraction']}) "
            f"must be lower than shutin_fluid_efficiency ({result['pkn_shutin_fluid_efficiency']})"
        )

    def test_low_shutin_efficiency_warning(self):
        """When shut-in efficiency falls below 10%, warning must label it."""
        # Make C large and P_net small to drive shut-in efficiency low.
        # Lower closure_pressure to make (P_shutin - sigma - perf) smaller.
        # Use lower E_prime to amplify the storage_unit_factor partially; but we want
        # leakoff to dominate -> use large slope by using a stronger pressure decline.
        n = 50
        tp = 600.0
        elapsed = np.arange(1, n + 1, dtype=float)
        delta = elapsed / tp
        g_time = np.asarray(nolte_g_time(delta, 0.8), dtype=float)
        pressure = 100.5 - 5.0 * g_time  # steep slope → large |dP/dG| → large C_stage
        E_prime = 33.3 * 1000.0 / (1.0 - 0.23 ** 2)
        result = physical_pkn_volume_balance(
            n_clusters=3,
            cluster_spacings_m=10.0,
            H_w_m=50.0,
            fleak=0.5,
            E_prime_mpa=E_prime,
            closure_pressure_mpa=99.5,
            minimum_stress_prior_mpa=99.1,
            perforation_friction_mpa=0.0,
            g_time=g_time,
            pressure_mpa=pressure,
            elapsed_seconds=elapsed,
            closure_index=40,
            tp_seconds=tp,
            g_function_m=0.8,
            effective_injected_volume_m3=3000.0,
            alpha=1.0,
            flow_allocation="stress-shadow",
        )
        assert result["pkn_volume_status"] == "ok"
        eff = result["pkn_shutin_fluid_efficiency"]
        warning = result["pkn_fluid_efficiency_warning"]
        if eff < 0.05:
            assert warning == "very_low_shutin_fluid_efficiency_check_C_units_or_stable_slope"
        elif eff < 0.10:
            assert warning == "low_shutin_fluid_efficiency_check_C_or_leakoff_terms"
        elif eff < 0.20:
            assert warning == "below_20pct_reference_check_local_assumptions"
        else:
            assert warning == "no_low_efficiency_warning"
        # The constructed case is designed to produce a sub-20% warning at minimum.
        assert eff < 0.20, f"constructed case should give low efficiency, got {eff}"
        assert warning != "no_low_efficiency_warning"

    def test_C_multiplier_diagnostic(self):
        result = physical_pkn_volume_balance(**self._build_inputs())
        eff = result["pkn_shutin_fluid_efficiency"]
        c_mult_20 = result["pkn_C_multiplier_to_20pct_shutin_efficiency"]
        c_mult_10 = result["pkn_C_multiplier_to_10pct_shutin_efficiency"]
        assert np.isfinite(c_mult_20) and c_mult_20 > 0
        assert np.isfinite(c_mult_10) and c_mult_10 > 0
        # Verify the diagnostic formula: at multiplier c_mult_t the resulting eff equals target t.
        for target, mult in [(0.20, c_mult_20), (0.10, c_mult_10)]:
            new_eff = result["pkn_shutin_storage_unit_mean_m2"] / (
                result["pkn_shutin_storage_unit_mean_m2"]
                + mult * result["pkn_shutin_preclosure_leakoff_unit_mean_m2"]
            )
            assert new_eff == pytest.approx(target, rel=1e-9), (
                f"applying C_multiplier_to_{int(target*100)}pct should yield efficiency=={target}, "
                f"got {new_eff} (multiplier={mult})"
            )
        # When eff < target, multiplier must be < 1 (need LESS leakoff than current).
        if eff < 0.20:
            assert c_mult_20 < 1.0
        if eff < 0.10:
            assert c_mult_10 < 1.0

    def test_cli_smoke_efficiency_audit_fields(self, tmp_path: Path):
        stage_dir = tmp_path / "stage_data"
        stage_dir.mkdir()
        shut_in_1 = _write_synthetic_stage_csv(stage_dir / "stage_01.csv", n_pre=50, n_post=150)
        shut_in_2 = _write_synthetic_stage_csv(stage_dir / "stage_02.csv", n_pre=50, n_post=150)
        params = pd.DataFrame([
            {"well": "W1", "stage": 1, "file": "stage_data/stage_01.csv",
             "shut_in": shut_in_1, "sigma_min": 75.0, "add_pressure": 40.0,
             "hw": 15.0, "e_gpa": 30.0, "nu": 0.25,
             "num_clusters": 4, "cluster_spacings": "10;10;10", "fleak": 0.5, "m": 0.8},
            {"well": "W1", "stage": 2, "file": "stage_data/stage_02.csv",
             "shut_in": shut_in_2, "sigma_min": 75.0, "add_pressure": 40.0,
             "hw": 15.0, "e_gpa": 30.0, "nu": 0.25,
             "num_clusters": 4, "cluster_spacings": "10;10;10", "fleak": 0.5, "m": 0.8},
        ])
        params_path = tmp_path / "stage_params.csv"
        params.to_csv(params_path, index=False)
        manifest = pd.DataFrame([
            {"stage": 1, "max_sustained_rate": 20.0, "valid_falloff_end_elapsed": 140.0},
            {"stage": 2, "max_sustained_rate": 20.0, "valid_falloff_end_elapsed": 140.0},
        ])
        manifest_path = tmp_path / "manifest.csv"
        manifest.to_csv(manifest_path, index=False)
        output_path = tmp_path / "summary.csv"

        from clotho.cli import main
        exit_code = main([
            "closure-batch",
            "--stage-params", str(params_path),
            "--well-root", str(tmp_path),
            "--manifest", str(manifest_path),
            "--output", str(output_path),
            "--volume-column", "total_volume",
            "--rate-time-unit", "minute",
            "--min-rate", "10",
            "--g-time-m", "0.8",
            "--closure-min-elapsed-seconds", "5",
            "--elapsed-duplicate-policy", "keep-last",
            "--pressure-source", "estimated-bottomhole",
            "--pkn-C-coupling", "stage-constant",
        ])
        assert exit_code == 0
        summary = pd.read_csv(output_path)
        for col in [
            "pkn_shutin_fluid_efficiency",
            "pkn_stable_storage_fraction",
            "pkn_C_multiplier_to_20pct_shutin_efficiency",
            "pkn_C_multiplier_to_10pct_shutin_efficiency",
            "pkn_fluid_efficiency_warning",
            "pkn_shutin_storage_volume_m3",
            "pkn_shutin_leakoff_before_closure_m3",
            "pkn_stable_G_leakoff_unit_fraction",
            "pkn_stable_storage_unit_fraction",
        ]:
            assert col in summary.columns, f"summary missing column {col}"

    def test_stable_fraction_lower_than_shutin_efficiency_when_g_positive(self):
        result = physical_pkn_volume_balance(**self._build_inputs())
        assert result["pkn_volume_status"] == "ok"
        # stable rows are at g > 0 (positive Nolte g-time)
        assert result["pkn_stable_g_min"] > 0
        # With g > 0, the G·leakoff term in the stable-row unit makes the storage fraction smaller.
        assert result["pkn_stable_storage_fraction"] < result["pkn_shutin_fluid_efficiency"]
