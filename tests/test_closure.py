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
