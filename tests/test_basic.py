from __future__ import annotations

from clotho import __version__
from clotho.cli import main


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
