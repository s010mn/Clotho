from __future__ import annotations

import pandas as pd
import pytest

from clotho.cli import main
from clotho.review import build_derivative_review_table


def _write_review_inputs(tmp_path):
    summary = tmp_path / "summary.csv"
    summary.write_text(
        "stage,derivative_readiness_ready,derivative_readiness_blockers,derivative_was_computed,"
        "closure_was_computed,pressure_derivative_output_written,pressure_derivative_output_path,"
        "falloff_window_rows_after_duplicate_policy,falloff_window_rows_removed_by_duplicate_policy,"
        "pressure_derivative_dP_dG_finite_count,pressure_derivative_dP_dG_positive_count,"
        "pressure_derivative_dP_dG_negative_count,pressure_derivative_dP_dG_zero_count,"
        "pressure_derivative_dP_dG_min,pressure_derivative_dP_dG_median,pressure_derivative_dP_dG_max,"
        "pressure_derivative_G_dP_dG_min,pressure_derivative_G_dP_dG_median,"
        "pressure_derivative_G_dP_dG_max,pressure_derivative_pressure_step_positive_count,"
        "pressure_derivative_pressure_step_negative_count,pressure_derivative_pressure_step_zero_count\n"
        "1,True,none,True,False,True,stage_01_derivative.csv,100,0,100,10,90,0,-5,-1,2,-3,-1,1,10,90,0\n"
        "2,True,none,True,False,True,stage_02_derivative.csv,100,68,100,80,20,0,-2,1,8,-1,2,5,80,20,0\n"
        "3,False,G-time is not strictly increasing,False,False,False,stage_03_derivative.csv,100,0,,,,,,,,,,,,\n",
        encoding="utf-8",
    )
    derivative_csv = "elapsed_seconds,dP_dG_mpa,G_dP_dG_mpa\n0,1,0\n1,2,2\n"
    (tmp_path / "stage_01_derivative.csv").write_text(derivative_csv, encoding="utf-8")
    (tmp_path / "stage_02_derivative.csv").write_text(derivative_csv, encoding="utf-8")
    return summary


def test_derivative_review_table_flags_high_priority_stages(tmp_path) -> None:
    summary = _write_review_inputs(tmp_path)

    review = build_derivative_review_table(summary)

    stage1 = review[review["stage"] == 1].iloc[0]
    stage2 = review[review["stage"] == 2].iloc[0]
    stage3 = review[review["stage"] == 3].iloc[0]

    assert stage1["manual_review_priority"] == "low"
    assert bool(stage2["duplicate_removal_large"])
    assert bool(stage2["positive_derivative_ratio_high"])
    assert stage2["manual_review_priority"] == "high"
    assert "large duplicate removal" in stage2["manual_review_reasons"]
    assert "high positive dP/dG ratio" in stage2["manual_review_reasons"]
    assert stage3["manual_review_priority"] == "high"
    assert stage3["manual_review_reasons"] == "not derivative-ready"


def test_derivative_review_cli_writes_review_csv(tmp_path, capsys) -> None:
    summary = _write_review_inputs(tmp_path)
    output = tmp_path / "review.csv"

    exit_code = main(["derivative-review", "--summary", str(summary), "--output", str(output)])

    captured = capsys.readouterr()
    review = pd.read_csv(output)

    assert exit_code == 0
    assert "review_stage_count=3" in captured.out
    assert "review_high_priority_count=2" in captured.out
    assert "review_output_path=" in captured.out
    assert "closure_was_computed=False" in captured.out
    assert output.exists()
    assert "manual_review_priority" in review.columns
    assert "manual_review_reasons" in review.columns


def test_derivative_review_missing_summary_errors(tmp_path, capsys) -> None:
    output = tmp_path / "review.csv"

    with pytest.raises(SystemExit) as exc_info:
        main(["derivative-review", "--summary", str(tmp_path / "missing.csv"), "--output", str(output)])

    captured = capsys.readouterr()
    assert exc_info.value.code == 2
    assert "summary" in captured.err


def test_derivative_review_missing_output_parent_errors(tmp_path, capsys) -> None:
    summary = _write_review_inputs(tmp_path)
    output = tmp_path / "missing" / "review.csv"

    with pytest.raises(SystemExit) as exc_info:
        main(["derivative-review", "--summary", str(summary), "--output", str(output)])

    captured = capsys.readouterr()
    assert exc_info.value.code == 2
    assert "output parent directory" in captured.err


def test_derivative_review_missing_derivative_dir_errors(tmp_path, capsys) -> None:
    summary = _write_review_inputs(tmp_path)
    output = tmp_path / "review.csv"

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "derivative-review",
                "--summary",
                str(summary),
                "--derivative-dir",
                str(tmp_path / "missing"),
                "--output",
                str(output),
            ]
        )

    captured = capsys.readouterr()
    assert exc_info.value.code == 2
    assert "derivative directory" in captured.err
