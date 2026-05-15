from __future__ import annotations

import pandas as pd
import pytest

from clotho.cli import main


def _write_batch_inputs(tmp_path, *, stage2_policy: str = "none", missing_required: bool = False, bad_output_name: str | None = None):
    stage_data_dir = tmp_path / "stage_data"
    stage_data_dir.mkdir()

    stage_params = tmp_path / "stage_params.csv"
    stage_params.write_text(
        "well,stage,file,shut_in,add_pressure\n"
        "demo,1,stage_data/stage_01.csv,00:00:03,5\n"
        "demo,2,stage_data/stage_02.csv,00:00:03,5\n",
        encoding="utf-8",
    )

    ready_curve = (
        "time,wellhead_pressure,rate,stage_volume,total_volume\n"
        "00:00:00,20,10,0,0\n"
        "00:00:01,21,10,0.3333333333,0.3333333333\n"
        "00:00:02,22,10,0.6666666667,0.6666666667\n"
        "00:00:03,23,0,1.0,1.0\n"
        "00:00:04,22,0,1.0,1.0\n"
        "00:00:05,21,0,1.0,1.0\n"
        "00:00:06,5,0,1.0,1.0\n"
        "00:00:07,0,0,1.0,1.0\n"
    )
    duplicate_curve = (
        "time,wellhead_pressure,rate,stage_volume,total_volume\n"
        "00:00:00,20,10,0,0\n"
        "00:00:01,21,10,0.3333333333,0.3333333333\n"
        "00:00:02,22,10,0.6666666667,0.6666666667\n"
        "00:00:03,23,0,1.0,1.0\n"
        "00:00:04,22,0,1.0,1.0\n"
        "00:00:04,21,0,1.0,1.0\n"
        "00:00:05,20,0,1.0,1.0\n"
    )
    (stage_data_dir / "stage_01.csv").write_text(ready_curve, encoding="utf-8")
    (stage_data_dir / "stage_02.csv").write_text(duplicate_curve, encoding="utf-8")

    manifest = tmp_path / "manifest.csv"
    output2 = bad_output_name if bad_output_name is not None else "stage_02_derivative.csv"
    if missing_required:
        manifest.write_text(
            "stage,max_sustained_rate,elapsed_duplicate_policy,output_name\n"
            "1,10,none,stage_01_derivative.csv\n",
            encoding="utf-8",
        )
    else:
        manifest.write_text(
            "stage,max_sustained_rate,valid_falloff_end_elapsed,elapsed_duplicate_policy,output_name\n"
            "1,10,2,none,stage_01_derivative.csv\n"
            f"2,10,2,{stage2_policy},{output2}\n",
            encoding="utf-8",
        )

    output_dir = tmp_path / "output"
    output_dir.mkdir()
    return stage_params, manifest, output_dir


def _batch_args(stage_params, manifest, output_dir) -> list[str]:
    return [
        "derivative-batch",
        "--stage-params",
        str(stage_params),
        "--well-root",
        str(stage_params.parent),
        "--manifest",
        str(manifest),
        "--output-dir",
        str(output_dir),
        "--volume-column",
        "total_volume",
        "--rate-time-unit",
        "minute",
        "--g-time-m",
        "0.8",
    ]


def test_derivative_batch_writes_ready_stage_and_summarizes_blocked_stage(tmp_path, capsys) -> None:
    stage_params, manifest, output_dir = _write_batch_inputs(tmp_path)

    exit_code = main(_batch_args(stage_params, manifest, output_dir))

    captured = capsys.readouterr()
    summary_path = output_dir / "derivative_batch_summary.csv"
    summary = pd.read_csv(summary_path)

    assert exit_code == 0
    assert "batch_stage_count=2" in captured.out
    assert "batch_ready_stage_count=1" in captured.out
    assert "batch_not_ready_stage_count=1" in captured.out
    assert "batch_derivative_csv_written_count=1" in captured.out
    assert "closure_was_computed=False" in captured.out
    assert summary_path.exists()
    assert (output_dir / "stage_01_derivative.csv").exists()
    assert not (output_dir / "stage_02_derivative.csv").exists()
    assert len(summary) == 2

    stage1 = summary[summary["stage"] == 1].iloc[0]
    stage2 = summary[summary["stage"] == 2].iloc[0]
    assert bool(stage1["derivative_was_computed"])
    assert bool(stage1["pressure_derivative_output_written"])
    assert not bool(stage2["derivative_was_computed"])
    assert not bool(stage2["pressure_derivative_output_written"])
    assert stage2["derivative_readiness_blockers"] == "G-time is not strictly increasing"


def test_derivative_batch_keep_last_policy_can_make_duplicate_stage_ready(tmp_path, capsys) -> None:
    stage_params, manifest, output_dir = _write_batch_inputs(tmp_path, stage2_policy="keep-last")

    exit_code = main(_batch_args(stage_params, manifest, output_dir))

    captured = capsys.readouterr()
    summary = pd.read_csv(output_dir / "derivative_batch_summary.csv")
    stage2 = summary[summary["stage"] == 2].iloc[0]

    assert exit_code == 0
    assert "batch_ready_stage_count=2" in captured.out
    assert (output_dir / "stage_02_derivative.csv").exists()
    assert bool(stage2["derivative_readiness_ready"])
    assert bool(stage2["derivative_was_computed"])
    assert bool(stage2["pressure_derivative_output_written"])


def test_derivative_batch_manifest_missing_required_column_errors(tmp_path, capsys) -> None:
    stage_params, manifest, output_dir = _write_batch_inputs(tmp_path, missing_required=True)

    with pytest.raises(SystemExit) as exc_info:
        main(_batch_args(stage_params, manifest, output_dir))

    captured = capsys.readouterr()
    assert exc_info.value.code == 2
    assert "valid_falloff_end_elapsed" in captured.err


def test_derivative_batch_missing_output_dir_errors(tmp_path, capsys) -> None:
    stage_params, manifest, output_dir = _write_batch_inputs(tmp_path)
    missing_dir = output_dir / "missing"

    with pytest.raises(SystemExit) as exc_info:
        main(_batch_args(stage_params, manifest, missing_dir))

    captured = capsys.readouterr()
    assert exc_info.value.code == 2
    assert "output directory" in captured.err


def test_derivative_batch_rejects_output_name_path_traversal(tmp_path, capsys) -> None:
    stage_params, manifest, output_dir = _write_batch_inputs(tmp_path, bad_output_name="../bad.csv")

    with pytest.raises(SystemExit) as exc_info:
        main(_batch_args(stage_params, manifest, output_dir))

    captured = capsys.readouterr()
    assert exc_info.value.code == 2
    assert "output_name" in captured.err
