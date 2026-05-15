from __future__ import annotations

import pandas as pd
import pytest

from clotho import __version__
from clotho.cli import main
from clotho.g_function import nolte_g_time
from clotho.pressure_derivative import pressure_derivative_against_g_time


def test_package_has_version() -> None:
    assert isinstance(__version__, str)
    assert __version__


def test_cli_version(capsys) -> None:
    exit_code = main(["version"])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.out.strip() == __version__


def _write_window_audit_inputs(tmp_path) -> tuple[object, object]:
    stage_data_dir = tmp_path / "stage_data"
    stage_data_dir.mkdir()

    stage_params = tmp_path / "stage_params.csv"
    stage_params.write_text(
        "well,stage,file,shut_in,add_pressure\n"
        "synthetic,1,stage_data/stage_01.csv,09:03:00,42.5\n",
        encoding="utf-8",
    )

    curve_file = stage_data_dir / "stage_01.csv"
    curve_file.write_text(
        "time,wellhead_pressure,rate,stage_volume,total_volume\n"
        "09:00:00,95.0,10.0,0.0,1000.0\n"
        "09:01:00,96.0,10.0,10.0,1010.0\n"
        "09:03:00,97.0,0.0,30.0,1030.0\n",
        encoding="utf-8",
    )

    return stage_params, tmp_path


def _window_audit_args(stage_params, well_root) -> list[str]:
    return [
        "window-audit",
        "--stage-params",
        str(stage_params),
        "--well-root",
        str(well_root),
        "--stage",
        "1",
        "--volume-column",
        "total_volume",
        "--max-sustained-rate",
        "10.0",
        "--rate-time-unit",
        "minute",
    ]


def test_window_audit_cli_prints_duration_choices(tmp_path, capsys) -> None:
    stage_params, well_root = _write_window_audit_inputs(tmp_path)

    exit_code = main(_window_audit_args(stage_params, well_root) + ["--picked-start-time", "09:01:00"])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "well=synthetic" in captured.out
    assert "stage=1" in captured.out
    assert "volume_column=total_volume" in captured.out
    assert "min_rate=0.0" in captured.out
    assert "max_sustained_rate=10.0" in captured.out
    assert "rate_time_unit=minute" in captured.out
    assert "rate_positive_elapsed_seconds=180.0" in captured.out
    assert "volume_over_max_sustained_rate_seconds=180.0" in captured.out
    assert "picked_start_time=09:01:00" in captured.out
    assert "picked_duration_seconds=120.0" in captured.out


def test_window_audit_cli_omits_picked_duration_when_not_requested(tmp_path, capsys) -> None:
    stage_params, well_root = _write_window_audit_inputs(tmp_path)

    exit_code = main(_window_audit_args(stage_params, well_root))

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "min_rate=0.0" in captured.out
    assert "max_sustained_rate=10.0" in captured.out
    assert "rate_time_unit=minute" in captured.out
    assert "volume_over_max_sustained_rate_seconds=180.0" in captured.out
    assert "picked_start_time=" not in captured.out
    assert "picked_duration_seconds=" not in captured.out


def test_window_audit_cli_echoes_custom_min_rate(tmp_path, capsys) -> None:
    stage_params, well_root = _write_window_audit_inputs(tmp_path)

    exit_code = main(_window_audit_args(stage_params, well_root) + ["--min-rate", "10.0"])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "min_rate=10.0" in captured.out


def _write_g_time_window_audit_inputs(tmp_path) -> tuple[object, object]:
    stage_data_dir = tmp_path / "stage_data"
    stage_data_dir.mkdir()

    stage_params = tmp_path / "stage_params.csv"
    stage_params.write_text(
        "well,stage,file,shut_in,n,spacing,hw,e_gpa,nu,sigma_min,add_pressure\n"
        "demo,1,stage_data/stage_01.csv,00:00:03,1,10,50,30,0.25,90,5\n",
        encoding="utf-8",
    )

    curve_file = stage_data_dir / "stage_01.csv"
    curve_file.write_text(
        "time,wellhead_pressure,rate,stage_volume,total_volume\n"
        "00:00:00,20,10,0,0\n"
        "00:00:01,21,10,0.3333333333,0.3333333333\n"
        "00:00:02,22,10,0.6666666667,0.6666666667\n"
        "00:00:03,23,0,1.0,1.0\n"
        "00:00:04,22,0,1.0,1.0\n"
        "00:00:05,21,0,1.0,1.0\n",
        encoding="utf-8",
    )

    return stage_params, tmp_path


def _format_expected_float_list(values) -> str:
    return "[" + ", ".join(f"{float(value):.12g}" for value in values) + "]"


def _g_time_window_audit_args(stage_params, well_root) -> list[str]:
    return [
        "window-audit",
        "--stage-params",
        str(stage_params),
        "--well-root",
        str(well_root),
        "--stage",
        "1",
        "--volume-column",
        "total_volume",
        "--max-sustained-rate",
        "10.0",
        "--rate-time-unit",
        "minute",
    ]


def test_window_audit_cli_does_not_print_g_time_by_default(tmp_path, capsys) -> None:
    stage_params, well_root = _write_g_time_window_audit_inputs(tmp_path)

    exit_code = main(_g_time_window_audit_args(stage_params, well_root))

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "volume_over_max_sustained_rate_seconds=6.0" in captured.out
    assert "g_time_tp_source" not in captured.out
    assert "nolte_g_time" not in captured.out
    assert "derivative_readiness_" not in captured.out
    assert "falloff_window_" not in captured.out
    assert "elapsed_duplicate_policy" not in captured.out
    assert "pressure_derivative_" not in captured.out
    assert "pressure_derivative_dP_dG_finite_count" not in captured.out
    assert "pressure_derivative_output_requested" not in captured.out


def test_window_audit_cli_prints_optional_g_time_preview(tmp_path, capsys) -> None:
    stage_params, well_root = _write_g_time_window_audit_inputs(tmp_path)

    exit_code = main(
        _g_time_window_audit_args(stage_params, well_root)
        + ["--g-time-m", "0.8", "--g-time-count", "3"]
    )

    captured = capsys.readouterr()
    expected_delta = [0.0, 1.0 / 6.0, 1.0 / 3.0]
    expected_g_time = nolte_g_time(expected_delta, 0.8)

    assert exit_code == 0
    assert "g_time_tp_source=volume_over_max_sustained_rate_seconds" in captured.out
    assert "g_time_m=0.8" in captured.out
    assert "g_time_count_requested=3" in captured.out
    assert "g_time_count_returned=3" in captured.out
    assert "g_time_elapsed_seconds=[0, 1, 2]" in captured.out
    assert f"g_time_delta={_format_expected_float_list(expected_delta)}" in captured.out
    assert f"nolte_g_time={_format_expected_float_list(expected_g_time)}" in captured.out


def test_window_audit_cli_rejects_nonpositive_g_time_count(tmp_path, capsys) -> None:
    stage_params, well_root = _write_g_time_window_audit_inputs(tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        main(
            _g_time_window_audit_args(stage_params, well_root)
            + ["--g-time-m", "0.8", "--g-time-count", "0"]
        )

    captured = capsys.readouterr()

    assert exc_info.value.code == 2
    assert "g_time_count" in captured.err
    assert "well=demo" not in captured.out


def _write_duplicate_elapsed_window_audit_inputs(tmp_path) -> tuple[object, object]:
    stage_params, well_root = _write_g_time_window_audit_inputs(tmp_path)

    curve_file = tmp_path / "stage_data" / "stage_01.csv"
    curve_file.write_text(
        "time,wellhead_pressure,rate,stage_volume,total_volume\n"
        "00:00:00,20,10,0,0\n"
        "00:00:01,21,10,0.3333333333,0.3333333333\n"
        "00:00:02,22,10,0.6666666667,0.6666666667\n"
        "00:00:03,23,0,1.0,1.0\n"
        "00:00:04,22,0,1.0,1.0\n"
        "00:00:04,0,0,1.0,1.0\n"
        "00:00:05,21,0,1.0,1.0\n",
        encoding="utf-8",
    )

    return stage_params, well_root


def _write_manual_falloff_window_audit_inputs(tmp_path, *, duplicate_elapsed: bool = False) -> tuple[object, object]:
    stage_data_dir = tmp_path / "stage_data"
    stage_data_dir.mkdir()

    stage_params = tmp_path / "stage_params.csv"
    stage_params.write_text(
        "well,stage,file,shut_in,n,spacing,hw,e_gpa,nu,sigma_min,add_pressure\n"
        "demo,1,stage_data/stage_01.csv,00:00:03,1,10,50,30,0.25,90,5\n",
        encoding="utf-8",
    )

    rows = [
        "00:00:00,20,10,0,0",
        "00:00:01,21,10,0.3333333333,0.3333333333",
        "00:00:02,22,10,0.6666666667,0.6666666667",
        "00:00:03,23,0,1.0,1.0",
        "00:00:04,22,0,1.0,1.0",
    ]
    if duplicate_elapsed:
        rows.append("00:00:04,21,0,1.0,1.0")
    rows.extend(
        [
            "00:00:05,21,0,1.0,1.0" if not duplicate_elapsed else "00:00:05,20,0,1.0,1.0",
            "00:00:06,5,0,1.0,1.0",
            "00:00:07,0,0,1.0,1.0",
        ]
    )

    curve_file = stage_data_dir / "stage_01.csv"
    curve_file.write_text(
        "time,wellhead_pressure,rate,stage_volume,total_volume\n" + "\n".join(rows) + "\n",
        encoding="utf-8",
    )

    return stage_params, tmp_path


def test_window_audit_cli_reports_clean_derivative_readiness(tmp_path, capsys) -> None:
    stage_params, well_root = _write_g_time_window_audit_inputs(tmp_path)

    exit_code = main(
        _g_time_window_audit_args(stage_params, well_root)
        + ["--g-time-m", "0.8", "--derivative-readiness"]
    )

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "derivative_readiness_tp_source=volume_over_max_sustained_rate_seconds" in captured.out
    assert "derivative_readiness_pressure_column=estimated_bottomhole_pressure_mpa" in captured.out
    assert "derivative_readiness_post_shut_in_rows=3" in captured.out
    assert "derivative_readiness_elapsed_duplicate_step_count=0" in captured.out
    assert "derivative_readiness_elapsed_backward_step_count=0" in captured.out
    assert "derivative_readiness_elapsed_strictly_increasing=True" in captured.out
    assert "derivative_readiness_elapsed_nondecreasing=True" in captured.out
    assert "derivative_readiness_g_time_duplicate_step_count=0" in captured.out
    assert "derivative_readiness_g_time_backward_step_count=0" in captured.out
    assert "derivative_readiness_g_time_strictly_increasing=True" in captured.out
    assert "derivative_readiness_g_time_nondecreasing=True" in captured.out
    assert "derivative_readiness_wellhead_pressure_zero_count=0" in captured.out
    assert "derivative_readiness_estimated_bottomhole_pressure_available=True" in captured.out
    assert "derivative_readiness_ready=True" in captured.out
    assert "derivative_readiness_blockers=none" in captured.out
    assert "derivative_was_computed=False" in captured.out
    assert "closure_was_computed=False" in captured.out


def test_window_audit_cli_reports_duplicate_elapsed_readiness_blocker(tmp_path, capsys) -> None:
    stage_params, well_root = _write_duplicate_elapsed_window_audit_inputs(tmp_path)

    exit_code = main(
        _g_time_window_audit_args(stage_params, well_root)
        + ["--g-time-m", "0.8", "--derivative-readiness"]
    )

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "derivative_readiness_post_shut_in_rows=4" in captured.out
    assert "derivative_readiness_elapsed_duplicate_step_count=1" in captured.out
    assert "derivative_readiness_elapsed_backward_step_count=0" in captured.out
    assert "derivative_readiness_elapsed_strictly_increasing=False" in captured.out
    assert "derivative_readiness_elapsed_nondecreasing=True" in captured.out
    assert "derivative_readiness_g_time_duplicate_step_count=1" in captured.out
    assert "derivative_readiness_g_time_backward_step_count=0" in captured.out
    assert "derivative_readiness_g_time_strictly_increasing=False" in captured.out
    assert "derivative_readiness_g_time_nondecreasing=True" in captured.out
    assert "derivative_readiness_wellhead_pressure_zero_count=1" in captured.out
    assert "derivative_readiness_ready=False" in captured.out
    assert "derivative_readiness_blockers=G-time is not strictly increasing" in captured.out
    assert "derivative_was_computed=False" in captured.out
    assert "closure_was_computed=False" in captured.out


def test_window_audit_cli_manual_valid_falloff_end_trims_tail(tmp_path, capsys) -> None:
    stage_params, well_root = _write_manual_falloff_window_audit_inputs(tmp_path)

    exit_code = main(
        _g_time_window_audit_args(stage_params, well_root)
        + ["--g-time-m", "0.8", "--derivative-readiness", "--valid-falloff-end-elapsed", "2"]
    )

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "falloff_window_scope=manual_valid_end_elapsed" in captured.out
    assert "falloff_window_end_elapsed_seconds=2" in captured.out
    assert "falloff_window_raw_rows=5" in captured.out
    assert "falloff_window_rows_after_valid_end=3" in captured.out
    assert "falloff_window_rows_removed_by_valid_end=2" in captured.out
    assert "falloff_window_rows_after_duplicate_policy=3" in captured.out
    assert "falloff_window_rows_removed_by_duplicate_policy=0" in captured.out
    assert "falloff_window_first_elapsed_seconds=0" in captured.out
    assert "falloff_window_last_elapsed_seconds=2" in captured.out
    assert "elapsed_duplicate_policy=none" in captured.out
    assert "derivative_readiness_scope=falloff_window" in captured.out
    assert "derivative_readiness_post_shut_in_rows=3" in captured.out
    assert "derivative_readiness_ready=True" in captured.out
    assert "derivative_was_computed=False" in captured.out
    assert "closure_was_computed=False" in captured.out


def test_window_audit_cli_valid_window_does_not_silently_deduplicate(tmp_path, capsys) -> None:
    stage_params, well_root = _write_manual_falloff_window_audit_inputs(tmp_path, duplicate_elapsed=True)

    exit_code = main(
        _g_time_window_audit_args(stage_params, well_root)
        + [
            "--g-time-m",
            "0.8",
            "--derivative-readiness",
            "--valid-falloff-end-elapsed",
            "2",
            "--elapsed-duplicate-policy",
            "none",
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "elapsed_duplicate_policy=none" in captured.out
    assert "falloff_window_rows_after_valid_end=4" in captured.out
    assert "falloff_window_rows_after_duplicate_policy=4" in captured.out
    assert "falloff_window_rows_removed_by_duplicate_policy=0" in captured.out
    assert "derivative_readiness_elapsed_duplicate_step_count=1" in captured.out
    assert "derivative_readiness_g_time_duplicate_step_count=1" in captured.out
    assert "derivative_readiness_ready=False" in captured.out
    assert "derivative_readiness_blockers=G-time is not strictly increasing" in captured.out


def test_window_audit_cli_explicit_keep_last_duplicate_policy_can_improve_readiness(tmp_path, capsys) -> None:
    stage_params, well_root = _write_manual_falloff_window_audit_inputs(tmp_path, duplicate_elapsed=True)

    exit_code = main(
        _g_time_window_audit_args(stage_params, well_root)
        + [
            "--g-time-m",
            "0.8",
            "--derivative-readiness",
            "--valid-falloff-end-elapsed",
            "2",
            "--elapsed-duplicate-policy",
            "keep-last",
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "elapsed_duplicate_policy=keep-last" in captured.out
    assert "falloff_window_rows_after_valid_end=4" in captured.out
    assert "falloff_window_rows_after_duplicate_policy=3" in captured.out
    assert "falloff_window_rows_removed_by_duplicate_policy=1" in captured.out
    assert "derivative_readiness_elapsed_duplicate_step_count=0" in captured.out
    assert "derivative_readiness_g_time_duplicate_step_count=0" in captured.out
    assert "derivative_readiness_ready=True" in captured.out
    assert "derivative_was_computed=False" in captured.out
    assert "closure_was_computed=False" in captured.out


def test_window_audit_cli_pressure_derivative_preview_computes_when_readiness_passes(tmp_path, capsys) -> None:
    stage_params, well_root = _write_manual_falloff_window_audit_inputs(tmp_path)

    exit_code = main(
        _g_time_window_audit_args(stage_params, well_root)
        + [
            "--g-time-m",
            "0.8",
            "--derivative-readiness",
            "--valid-falloff-end-elapsed",
            "2",
            "--elapsed-duplicate-policy",
            "none",
            "--pressure-derivative-preview",
            "--pressure-derivative-count",
            "3",
        ]
    )

    captured = capsys.readouterr()
    g_time = nolte_g_time([0.0, 1.0 / 6.0, 1.0 / 3.0], 0.8)
    pressure = [28.0, 27.0, 26.0]
    dP_dG, G_dP_dG = pressure_derivative_against_g_time(g_time, pressure)

    assert exit_code == 0
    assert "pressure_derivative_preview_requested=True" in captured.out
    assert "pressure_derivative_was_computed=True" in captured.out
    assert "pressure_derivative_scope=falloff_window" in captured.out
    assert "pressure_derivative_pressure_column=estimated_bottomhole_pressure_mpa" in captured.out
    assert "pressure_derivative_method=numpy.gradient_edge_order_1" in captured.out
    assert "pressure_derivative_count_requested=3" in captured.out
    assert "pressure_derivative_count_returned=3" in captured.out
    assert f"pressure_derivative_g_time={_format_expected_float_list(g_time)}" in captured.out
    assert "pressure_derivative_pressure_mpa=[28, 27, 26]" in captured.out
    assert f"pressure_derivative_dP_dG_mpa={_format_expected_float_list(dP_dG)}" in captured.out
    assert f"pressure_derivative_G_dP_dG_mpa={_format_expected_float_list(G_dP_dG)}" in captured.out
    assert "pressure_derivative_dP_dG_finite_count=3" in captured.out
    assert "pressure_derivative_dP_dG_nan_or_inf_count=0" in captured.out
    assert "pressure_derivative_dP_dG_min=" in captured.out
    assert "pressure_derivative_dP_dG_median=" in captured.out
    assert "pressure_derivative_dP_dG_max=" in captured.out
    assert "pressure_derivative_G_dP_dG_finite_count=3" in captured.out
    assert "pressure_derivative_pressure_step_negative_count=2" in captured.out
    assert "pressure_derivative_output_requested=False" in captured.out
    assert "pressure_derivative_output_written=False" in captured.out
    assert "pressure_derivative_output_path=none" in captured.out
    assert "derivative_was_computed=True" in captured.out
    assert "closure_was_computed=False" in captured.out


def test_window_audit_cli_pressure_derivative_output_writes_csv_when_derivative_succeeds(tmp_path, capsys) -> None:
    stage_params, well_root = _write_manual_falloff_window_audit_inputs(tmp_path)
    output_path = tmp_path / "derivative.csv"

    exit_code = main(
        _g_time_window_audit_args(stage_params, well_root)
        + [
            "--g-time-m",
            "0.8",
            "--derivative-readiness",
            "--valid-falloff-end-elapsed",
            "2",
            "--elapsed-duplicate-policy",
            "none",
            "--pressure-derivative-preview",
            "--pressure-derivative-count",
            "3",
            "--pressure-derivative-output",
            str(output_path),
        ]
    )

    captured = capsys.readouterr()
    df = pd.read_csv(output_path)

    assert exit_code == 0
    assert "pressure_derivative_output_requested=True" in captured.out
    assert "pressure_derivative_output_written=True" in captured.out
    assert f"pressure_derivative_output_path={output_path}" in captured.out
    assert len(df) == 3
    assert {
        "elapsed_seconds",
        "delta",
        "nolte_g_time",
        "pressure_column",
        "pressure_mpa",
        "wellhead_pressure_mpa",
        "dP_dG_mpa",
        "G_dP_dG_mpa",
    }.issubset(df.columns)
    assert set(df["pressure_column"]) == {"estimated_bottomhole_pressure_mpa"}
    assert df["pressure_mpa"].tolist() == [28.0, 27.0, 26.0]


def test_window_audit_cli_pressure_derivative_preview_skips_when_readiness_fails(tmp_path, capsys) -> None:
    stage_params, well_root = _write_manual_falloff_window_audit_inputs(tmp_path, duplicate_elapsed=True)

    exit_code = main(
        _g_time_window_audit_args(stage_params, well_root)
        + [
            "--g-time-m",
            "0.8",
            "--derivative-readiness",
            "--valid-falloff-end-elapsed",
            "2",
            "--elapsed-duplicate-policy",
            "none",
            "--pressure-derivative-preview",
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "derivative_readiness_ready=False" in captured.out
    assert "derivative_readiness_blockers=G-time is not strictly increasing" in captured.out
    assert "pressure_derivative_preview_requested=True" in captured.out
    assert "pressure_derivative_was_computed=False" in captured.out
    assert "pressure_derivative_blockers=G-time is not strictly increasing" in captured.out
    assert "pressure_derivative_output_requested=False" in captured.out
    assert "pressure_derivative_output_written=False" in captured.out
    assert "pressure_derivative_output_path=none" in captured.out
    assert "derivative_was_computed=False" in captured.out
    assert "closure_was_computed=False" in captured.out


def test_window_audit_cli_pressure_derivative_output_not_written_when_readiness_fails(tmp_path, capsys) -> None:
    stage_params, well_root = _write_manual_falloff_window_audit_inputs(tmp_path, duplicate_elapsed=True)
    output_path = tmp_path / "blocked.csv"

    exit_code = main(
        _g_time_window_audit_args(stage_params, well_root)
        + [
            "--g-time-m",
            "0.8",
            "--derivative-readiness",
            "--valid-falloff-end-elapsed",
            "2",
            "--elapsed-duplicate-policy",
            "none",
            "--pressure-derivative-preview",
            "--pressure-derivative-output",
            str(output_path),
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "derivative_readiness_ready=False" in captured.out
    assert "pressure_derivative_was_computed=False" in captured.out
    assert "pressure_derivative_output_requested=True" in captured.out
    assert "pressure_derivative_output_written=False" in captured.out
    assert not output_path.exists()
    assert "closure_was_computed=False" in captured.out


def test_window_audit_cli_pressure_derivative_preview_works_after_keep_last_policy(tmp_path, capsys) -> None:
    stage_params, well_root = _write_manual_falloff_window_audit_inputs(tmp_path, duplicate_elapsed=True)

    exit_code = main(
        _g_time_window_audit_args(stage_params, well_root)
        + [
            "--g-time-m",
            "0.8",
            "--derivative-readiness",
            "--valid-falloff-end-elapsed",
            "2",
            "--elapsed-duplicate-policy",
            "keep-last",
            "--pressure-derivative-preview",
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "elapsed_duplicate_policy=keep-last" in captured.out
    assert "derivative_readiness_ready=True" in captured.out
    assert "pressure_derivative_was_computed=True" in captured.out
    assert "derivative_was_computed=True" in captured.out
    assert "closure_was_computed=False" in captured.out


def test_window_audit_cli_rejects_pressure_derivative_output_without_preview(tmp_path, capsys) -> None:
    stage_params, well_root = _write_manual_falloff_window_audit_inputs(tmp_path)
    output_path = tmp_path / "derivative.csv"

    with pytest.raises(SystemExit) as exc_info:
        main(_g_time_window_audit_args(stage_params, well_root) + ["--pressure-derivative-output", str(output_path)])

    captured = capsys.readouterr()

    assert exc_info.value.code == 2
    assert "--pressure-derivative-preview" in captured.err
    assert "well=demo" not in captured.out


def test_window_audit_cli_rejects_pressure_derivative_output_missing_parent(tmp_path, capsys) -> None:
    stage_params, well_root = _write_manual_falloff_window_audit_inputs(tmp_path)
    output_path = tmp_path / "missing_dir" / "derivative.csv"

    with pytest.raises(SystemExit) as exc_info:
        main(
            _g_time_window_audit_args(stage_params, well_root)
            + [
                "--g-time-m",
                "0.8",
                "--derivative-readiness",
                "--valid-falloff-end-elapsed",
                "2",
                "--pressure-derivative-preview",
                "--pressure-derivative-output",
                str(output_path),
            ]
        )

    captured = capsys.readouterr()

    assert exc_info.value.code == 2
    assert "parent directory" in captured.err
    assert "well=demo" not in captured.out


def test_window_audit_cli_rejects_pressure_derivative_preview_without_derivative_readiness(tmp_path, capsys) -> None:
    stage_params, well_root = _write_manual_falloff_window_audit_inputs(tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        main(_g_time_window_audit_args(stage_params, well_root) + ["--pressure-derivative-preview"])

    captured = capsys.readouterr()

    assert exc_info.value.code == 2
    assert "--derivative-readiness" in captured.err
    assert "well=demo" not in captured.out


def test_window_audit_cli_rejects_pressure_derivative_preview_without_valid_end(tmp_path, capsys) -> None:
    stage_params, well_root = _write_manual_falloff_window_audit_inputs(tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        main(
            _g_time_window_audit_args(stage_params, well_root)
            + ["--g-time-m", "0.8", "--derivative-readiness", "--pressure-derivative-preview"]
        )

    captured = capsys.readouterr()

    assert exc_info.value.code == 2
    assert "--valid-falloff-end-elapsed" in captured.err
    assert "well=demo" not in captured.out


def test_window_audit_cli_rejects_nonpositive_pressure_derivative_count(tmp_path, capsys) -> None:
    stage_params, well_root = _write_manual_falloff_window_audit_inputs(tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        main(
            _g_time_window_audit_args(stage_params, well_root)
            + [
                "--g-time-m",
                "0.8",
                "--derivative-readiness",
                "--valid-falloff-end-elapsed",
                "2",
                "--pressure-derivative-preview",
                "--pressure-derivative-count",
                "0",
            ]
        )

    captured = capsys.readouterr()

    assert exc_info.value.code == 2
    assert "pressure_derivative_count" in captured.err
    assert "well=demo" not in captured.out


def test_window_audit_cli_rejects_negative_valid_falloff_end_elapsed(tmp_path, capsys) -> None:
    stage_params, well_root = _write_manual_falloff_window_audit_inputs(tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        main(
            _g_time_window_audit_args(stage_params, well_root)
            + ["--g-time-m", "0.8", "--derivative-readiness", "--valid-falloff-end-elapsed", "-1"]
        )

    captured = capsys.readouterr()

    assert exc_info.value.code == 2
    assert "valid_falloff_end_elapsed" in captured.err
    assert "well=demo" not in captured.out


def test_window_audit_cli_rejects_valid_falloff_end_without_derivative_readiness(tmp_path, capsys) -> None:
    stage_params, well_root = _write_manual_falloff_window_audit_inputs(tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        main(_g_time_window_audit_args(stage_params, well_root) + ["--valid-falloff-end-elapsed", "2"])

    captured = capsys.readouterr()

    assert exc_info.value.code == 2
    assert "--derivative-readiness" in captured.err
    assert "well=demo" not in captured.out


def test_window_audit_cli_rejects_duplicate_policy_without_derivative_readiness(tmp_path, capsys) -> None:
    stage_params, well_root = _write_manual_falloff_window_audit_inputs(tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        main(_g_time_window_audit_args(stage_params, well_root) + ["--elapsed-duplicate-policy", "keep-last"])

    captured = capsys.readouterr()

    assert exc_info.value.code == 2
    assert "--derivative-readiness" in captured.err
    assert "well=demo" not in captured.out


def test_window_audit_cli_derivative_readiness_requires_g_time_m(tmp_path, capsys) -> None:
    stage_params, well_root = _write_g_time_window_audit_inputs(tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        main(_g_time_window_audit_args(stage_params, well_root) + ["--derivative-readiness"])

    captured = capsys.readouterr()

    assert exc_info.value.code == 2
    assert "--g-time-m" in captured.err
    assert "well=demo" not in captured.out
