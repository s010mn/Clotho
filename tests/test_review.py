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



def _write_topn_review_inputs(tmp_path):
    summary = tmp_path / "topn_summary.csv"
    header = (
        "stage,derivative_readiness_ready,derivative_readiness_blockers,derivative_was_computed,"
        "closure_was_computed,pressure_derivative_output_written,pressure_derivative_output_path,"
        "falloff_window_rows_after_duplicate_policy,falloff_window_rows_removed_by_duplicate_policy,"
        "pressure_derivative_dP_dG_finite_count,pressure_derivative_dP_dG_positive_count,"
        "pressure_derivative_dP_dG_negative_count,pressure_derivative_dP_dG_zero_count,"
        "pressure_derivative_dP_dG_min,pressure_derivative_dP_dG_median,pressure_derivative_dP_dG_max,"
        "pressure_derivative_G_dP_dG_min,pressure_derivative_G_dP_dG_median,"
        "pressure_derivative_G_dP_dG_max,pressure_derivative_pressure_step_positive_count,"
        "pressure_derivative_pressure_step_negative_count,pressure_derivative_pressure_step_zero_count\n"
    )
    rows = [
        "8,True,none,True,False,True,stage_08_derivative.csv,100,0,100,20,80,0,-13693,0,10,-2,0,2,20,80,0\n",
        "7,True,none,True,False,True,stage_07_derivative.csv,100,0,100,25,75,0,-12998,0,10,-2,0,2,25,75,0\n",
        "3,True,none,True,False,True,stage_03_derivative.csv,100,0,100,80,20,0,-10,0,5,-2,0,2,80,20,0\n",
    ]
    summary.write_text(header + "".join(rows), encoding="utf-8")
    derivative_csv = "elapsed_seconds,dP_dG_mpa,G_dP_dG_mpa\n0,1,0\n1,2,2\n"
    for stage in [3, 7, 8]:
        (tmp_path / f"stage_{stage:02d}_derivative.csv").write_text(derivative_csv, encoding="utf-8")
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


def test_derivative_review_default_does_not_print_topn(tmp_path, capsys) -> None:
    summary = _write_topn_review_inputs(tmp_path)
    output = tmp_path / "review.csv"

    exit_code = main(["derivative-review", "--summary", str(summary), "--output", str(output)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "top_dP_dG_abs_max" not in captured.out
    assert "top_dP_dG_positive_ratio" not in captured.out
    assert "closure_was_computed=False" in captured.out


def test_derivative_review_print_topn_orders_abs_max_and_positive_ratio(tmp_path, capsys) -> None:
    summary = _write_topn_review_inputs(tmp_path)
    output = tmp_path / "review.csv"

    exit_code = main(
        [
            "derivative-review",
            "--summary",
            str(summary),
            "--output",
            str(output),
            "--print-top-n",
            "2",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "top_dP_dG_abs_max:" in captured.out
    assert "top_dP_dG_positive_ratio:" in captured.out
    assert "rank=1" in captured.out
    assert "rank=2" in captured.out
    abs_block = captured.out.split("top_dP_dG_abs_max:", 1)[1].split("top_dP_dG_positive_ratio:", 1)[0]
    assert abs_block.index("rank=1 stage=8") < abs_block.index("rank=2 stage=7")
    ratio_block = captured.out.split("top_dP_dG_positive_ratio:", 1)[1]
    assert "rank=1 stage=3" in ratio_block
    assert "closure_was_computed=False" in captured.out


def test_derivative_review_print_topn_preserves_threshold_priority(tmp_path, capsys) -> None:
    summary = _write_topn_review_inputs(tmp_path)
    output = tmp_path / "review.csv"

    exit_code = main(
        [
            "derivative-review",
            "--summary",
            str(summary),
            "--output",
            str(output),
            "--large-abs-dpdg-threshold",
            "10000",
            "--print-top-n",
            "2",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    abs_block = captured.out.split("top_dP_dG_abs_max:", 1)[1].split("top_dP_dG_positive_ratio:", 1)[0]
    assert "rank=1 stage=8 priority=medium" in abs_block
    assert "rank=2 stage=7 priority=medium" in abs_block


def test_derivative_review_negative_print_topn_errors(tmp_path, capsys) -> None:
    summary = _write_topn_review_inputs(tmp_path)
    output = tmp_path / "review.csv"

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "derivative-review",
                "--summary",
                str(summary),
                "--output",
                str(output),
                "--print-top-n",
                "-1",
            ]
        )

    captured = capsys.readouterr()
    assert exc_info.value.code == 2
    assert "print_top_n" in captured.err



def _write_single_stage_summary(tmp_path, *, path_name="stage_01_derivative.csv", stage=1, rows_removed=0):
    summary = tmp_path / f"single_stage_{stage}_summary.csv"
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
        f"{stage},True,none,True,False,True,{path_name},100,{rows_removed},100,10,90,0,-12000,-1,8000,-3,-1,1,10,90,0\n",
        encoding="utf-8",
    )
    return summary


def _write_derivative_text(path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _run_review_with_early_window(tmp_path, derivative_text: str, extra_args=None):
    summary = _write_single_stage_summary(tmp_path)
    _write_derivative_text(tmp_path / "stage_01_derivative.csv", derivative_text)
    output = tmp_path / "review.csv"
    args = [
        "derivative-review",
        "--summary",
        str(summary),
        "--output",
        str(output),
        "--early-transient-window-seconds",
        "15",
    ]
    if extra_args:
        args.extend(extra_args)
    exit_code = main(args)
    return exit_code, pd.read_csv(output).iloc[0]


def test_derivative_review_default_early_transient_not_requested(tmp_path) -> None:
    summary = _write_review_inputs(tmp_path)
    output = tmp_path / "review.csv"

    exit_code = main(["derivative-review", "--summary", str(summary), "--output", str(output)])

    review = pd.read_csv(output)
    stage1 = review.loc[review["stage"] == 1].iloc[0]
    assert exit_code == 0
    assert stage1["early_transient_status"] == "not_requested"
    assert bool(stage1["early_transient_risk"]) is False
    assert stage1["water_hammer_plausibility_note"] == "not_requested"
    assert stage1["manual_review_priority"] == "low"
    assert bool(stage1["closure_was_computed"]) is False


def test_derivative_review_early_transient_flags_low_frequency_risk(tmp_path) -> None:
    derivative_text = (
        "elapsed_seconds,pressure_mpa,dP_dG_mpa,G_dP_dG_mpa\n"
        "0,100,1000,0\n"
        "1,95,-12000,-10\n"
        "2,99,8000,20\n"
        "3,94,-7000,-30\n"
        "4,98,5000,40\n"
        "20,93,100,50\n"
        "30,92,50,60\n"
    )

    exit_code, row = _run_review_with_early_window(
        tmp_path,
        derivative_text,
        ["--early-transient-pressure-range-threshold", "1.0"],
    )

    assert exit_code == 0
    assert row["early_transient_status"] == "ok"
    assert bool(row["early_transient_full_abs_dP_dG_inside_window"]) is True
    assert row["early_transient_early_abs_dP_dG_max"] == 12000
    assert row["early_transient_late_abs_dP_dG_max"] == 100
    assert row["early_transient_pressure_range_mpa"] >= 1.0
    assert row["early_transient_pressure_local_extrema_count"] >= 1
    assert row["early_transient_pressure_step_sign_changes"] >= 1
    assert row["early_transient_dP_dG_sign_changes"] >= 1
    assert bool(row["early_transient_risk"]) is True
    assert row["water_hammer_plausibility_note"] == "plausible_low_frequency_only"
    assert bool(row["closure_was_computed"]) is False


def test_derivative_review_early_transient_full_abs_outside_window_no_risk(tmp_path) -> None:
    derivative_text = (
        "elapsed_seconds,pressure_mpa,dP_dG_mpa,G_dP_dG_mpa\n"
        "0,100,100,0\n"
        "1,99,-100,0\n"
        "2,100,120,0\n"
        "20,95,-9000,0\n"
        "30,94,-10000,0\n"
    )

    exit_code, row = _run_review_with_early_window(tmp_path, derivative_text)

    assert exit_code == 0
    assert row["early_transient_status"] == "ok"
    assert bool(row["early_transient_full_abs_dP_dG_inside_window"]) is False
    assert bool(row["early_transient_risk"]) is False
    assert row["water_hammer_plausibility_note"] == "not_indicated_by_simple_low_frequency_rules"


def test_derivative_review_early_transient_missing_elapsed_seconds(tmp_path) -> None:
    exit_code, row = _run_review_with_early_window(
        tmp_path,
        "pressure_mpa,dP_dG_mpa,G_dP_dG_mpa\n100,1,0\n",
    )

    assert exit_code == 0
    assert row["early_transient_status"] == "missing_elapsed_seconds"
    assert bool(row["early_transient_risk"]) is False
    assert row["water_hammer_plausibility_note"] == "insufficient_data_for_assessment"
    assert row["manual_review_priority"] == "low"
    assert bool(row["closure_was_computed"]) is False


def test_derivative_review_early_transient_missing_pressure_mpa(tmp_path) -> None:
    exit_code, row = _run_review_with_early_window(
        tmp_path,
        "elapsed_seconds,dP_dG_mpa,G_dP_dG_mpa\n0,1,0\n",
    )

    assert exit_code == 0
    assert row["early_transient_status"] == "missing_pressure_mpa"
    assert bool(row["early_transient_risk"]) is False
    assert row["water_hammer_plausibility_note"] == "insufficient_data_for_assessment"


def test_derivative_review_early_transient_missing_dpdg_mpa(tmp_path) -> None:
    exit_code, row = _run_review_with_early_window(
        tmp_path,
        "elapsed_seconds,pressure_mpa,G_dP_dG_mpa\n0,100,0\n",
    )

    assert exit_code == 0
    assert row["early_transient_status"] == "missing_dP_dG_mpa"
    assert bool(row["early_transient_risk"]) is False
    assert row["water_hammer_plausibility_note"] == "insufficient_data_for_assessment"


def test_derivative_review_early_transient_no_finite_rows(tmp_path) -> None:
    exit_code, row = _run_review_with_early_window(
        tmp_path,
        "elapsed_seconds,pressure_mpa,dP_dG_mpa,G_dP_dG_mpa\nabc,def,ghi,0\n,, ,0\n",
    )

    assert exit_code == 0
    assert row["early_transient_status"] == "no_finite_rows"
    assert bool(row["early_transient_risk"]) is False
    assert row["water_hammer_plausibility_note"] == "insufficient_data_for_assessment"


def test_derivative_review_early_transient_no_rows_in_early_window(tmp_path) -> None:
    exit_code, row = _run_review_with_early_window(
        tmp_path,
        "elapsed_seconds,pressure_mpa,dP_dG_mpa,G_dP_dG_mpa\n20,100,1000,0\n30,99,-900,0\n",
    )

    assert exit_code == 0
    assert row["early_transient_status"] == "no_rows_in_early_window"
    assert bool(row["early_transient_risk"]) is False
    assert row["water_hammer_plausibility_note"] == "insufficient_data_for_assessment"


def test_derivative_review_invalid_early_transient_window_errors(tmp_path, capsys) -> None:
    summary = _write_review_inputs(tmp_path)
    output = tmp_path / "review.csv"

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "derivative-review",
                "--summary",
                str(summary),
                "--output",
                str(output),
                "--early-transient-window-seconds",
                "-1",
            ]
        )

    captured = capsys.readouterr()
    assert exc_info.value.code == 2
    assert "early_transient_window_seconds" in captured.err


def test_derivative_review_invalid_early_transient_threshold_errors(tmp_path, capsys) -> None:
    summary = _write_review_inputs(tmp_path)
    output = tmp_path / "review.csv"

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "derivative-review",
                "--summary",
                str(summary),
                "--output",
                str(output),
                "--early-transient-pressure-range-threshold",
                "-1",
            ]
        )

    captured = capsys.readouterr()
    assert exc_info.value.code == 2
    assert "early_transient_pressure_range_threshold" in captured.err


def test_derivative_review_early_transient_risk_does_not_change_priority(tmp_path) -> None:
    derivative_text = (
        "elapsed_seconds,pressure_mpa,dP_dG_mpa,G_dP_dG_mpa\n"
        "0,100,1000,0\n"
        "1,95,-12000,-10\n"
        "2,99,8000,20\n"
        "3,94,-7000,-30\n"
        "20,93,100,50\n"
    )

    exit_code, row = _run_review_with_early_window(tmp_path, derivative_text)

    assert exit_code == 0
    assert bool(row["early_transient_risk"]) is True
    assert row["manual_review_priority"] == "low"


def _write_context_review(tmp_path, *, path_name="stage_07_derivative.csv", exists=True):
    review = tmp_path / "context_review.csv"
    review.write_text(
        "stage,pressure_derivative_output_path,derivative_csv_exists,manual_review_priority,manual_review_reasons\n"
        f"7,{path_name},{exists},medium,large absolute dP/dG\n",
        encoding="utf-8",
    )
    return review


def _write_context_derivative_csv(path):
    path.write_text(
        "row_number,elapsed_seconds,delta,nolte_g_time,pressure_column,pressure_mpa,"
        "wellhead_pressure_mpa,dP_dG_mpa,G_dP_dG_mpa\n"
        "0,0,0,0,wellhead_pressure_mpa,100,100,-1,0\n"
        "1,1,0.1,0.1,wellhead_pressure_mpa,99,99,-2,-0.2\n"
        "2,2,0.2,0.2,wellhead_pressure_mpa,80,80,-50,-10\n"
        "3,3,0.3,0.3,wellhead_pressure_mpa,79,79,-3,-0.9\n"
        "4,4,0.4,0.4,wellhead_pressure_mpa,78,78,-4,-1.6\n",
        encoding="utf-8",
    )


def test_derivative_context_exports_center_and_neighbor_rows(tmp_path, capsys) -> None:
    review = _write_context_review(tmp_path)
    _write_context_derivative_csv(tmp_path / "stage_07_derivative.csv")
    output = tmp_path / "context.csv"

    exit_code = main(
        [
            "derivative-context",
            "--review",
            str(review),
            "--derivative-dir",
            str(tmp_path),
            "--output",
            str(output),
            "--stages",
            "7",
            "--top-abs-dpdg-per-stage",
            "1",
            "--context-radius",
            "1",
        ]
    )

    captured = capsys.readouterr()
    context = pd.read_csv(output)

    assert exit_code == 0
    assert output.exists()
    assert len(context) == 3
    assert context["context_offset"].tolist() == [-1, 0, 1]
    assert context["is_center"].tolist() == [False, True, False]
    assert context["center_abs_dP_dG_mpa"].tolist() == [50.0, 50.0, 50.0]
    assert set(context["manual_review_priority"]) == {"medium"}
    assert set(context["closure_was_computed"]) == {False}
    assert "derivative_context_written_rows=3" in captured.out
    assert "closure_was_computed=False" in captured.out


def test_derivative_context_top_two_keeps_overlapping_contexts(tmp_path) -> None:
    review = _write_context_review(tmp_path)
    _write_context_derivative_csv(tmp_path / "stage_07_derivative.csv")
    output = tmp_path / "context.csv"

    exit_code = main(
        [
            "derivative-context",
            "--review",
            str(review),
            "--derivative-dir",
            str(tmp_path),
            "--output",
            str(output),
            "--top-abs-dpdg-per-stage",
            "2",
            "--context-radius",
            "1",
        ]
    )

    context = pd.read_csv(output)
    assert exit_code == 0
    assert len(context) == 5
    assert context["extreme_rank"].tolist() == [1, 1, 1, 2, 2]
    assert context.loc[context["is_center"] == True, "center_abs_dP_dG_mpa"].tolist() == [50.0, 4.0]


def test_derivative_context_missing_derivative_csv_placeholder(tmp_path) -> None:
    review = _write_context_review(tmp_path, path_name="missing.csv", exists=False)
    output = tmp_path / "context.csv"

    exit_code = main(["derivative-context", "--review", str(review), "--output", str(output), "--stages", "7"])

    context = pd.read_csv(output)
    assert exit_code == 0
    assert len(context) == 1
    assert context.iloc[0]["context_status"] == "missing_derivative_csv"
    assert bool(context.iloc[0]["closure_was_computed"]) is False


def test_derivative_context_missing_dpdg_column_placeholder(tmp_path) -> None:
    review = _write_context_review(tmp_path)
    (tmp_path / "stage_07_derivative.csv").write_text("row_number,elapsed_seconds\n0,0\n", encoding="utf-8")
    output = tmp_path / "context.csv"

    exit_code = main(["derivative-context", "--review", str(review), "--output", str(output)])

    context = pd.read_csv(output)
    assert exit_code == 0
    assert context.iloc[0]["context_status"] == "missing_dP_dG_mpa"


def test_derivative_context_no_finite_dpdg_placeholder(tmp_path) -> None:
    review = _write_context_review(tmp_path)
    (tmp_path / "stage_07_derivative.csv").write_text(
        "row_number,elapsed_seconds,dP_dG_mpa\n0,0,\n1,1,\n",
        encoding="utf-8",
    )
    output = tmp_path / "context.csv"

    exit_code = main(["derivative-context", "--review", str(review), "--output", str(output)])

    context = pd.read_csv(output)
    assert exit_code == 0
    assert context.iloc[0]["context_status"] == "no_finite_dP_dG_mpa"


def test_derivative_context_invalid_top_abs_dpdg_errors(tmp_path, capsys) -> None:
    review = _write_context_review(tmp_path)
    output = tmp_path / "context.csv"

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "derivative-context",
                "--review",
                str(review),
                "--output",
                str(output),
                "--top-abs-dpdg-per-stage",
                "0",
            ]
        )

    captured = capsys.readouterr()
    assert exc_info.value.code == 2
    assert "top_abs_dpdg_per_stage" in captured.err


def test_derivative_context_invalid_radius_errors(tmp_path, capsys) -> None:
    review = _write_context_review(tmp_path)
    output = tmp_path / "context.csv"

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "derivative-context",
                "--review",
                str(review),
                "--output",
                str(output),
                "--context-radius",
                "-1",
            ]
        )

    captured = capsys.readouterr()
    assert exc_info.value.code == 2
    assert "context_radius" in captured.err


def test_derivative_context_invalid_stages_errors(tmp_path, capsys) -> None:
    review = _write_context_review(tmp_path)
    output = tmp_path / "context.csv"

    with pytest.raises(SystemExit) as exc_info:
        main(["derivative-context", "--review", str(review), "--output", str(output), "--stages", "abc"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 2
    assert "stages" in captured.err


def test_derivative_context_missing_output_parent_errors(tmp_path, capsys) -> None:
    review = _write_context_review(tmp_path)
    output = tmp_path / "missing" / "context.csv"

    with pytest.raises(SystemExit) as exc_info:
        main(["derivative-context", "--review", str(review), "--output", str(output)])

    captured = capsys.readouterr()
    assert exc_info.value.code == 2
    assert "output parent directory does not exist" in captured.err


def test_derivative_context_default_stages_processes_all_existing_csvs(tmp_path) -> None:
    review = tmp_path / "context_review.csv"
    review.write_text(
        "stage,pressure_derivative_output_path,derivative_csv_exists,manual_review_priority,manual_review_reasons\n"
        "7,stage_07_derivative.csv,True,medium,large absolute dP/dG\n"
        "8,stage_08_derivative.csv,True,medium,large absolute dP/dG\n",
        encoding="utf-8",
    )
    _write_context_derivative_csv(tmp_path / "stage_07_derivative.csv")
    _write_context_derivative_csv(tmp_path / "stage_08_derivative.csv")
    output = tmp_path / "context.csv"

    exit_code = main(
        [
            "derivative-context",
            "--review",
            str(review),
            "--output",
            str(output),
            "--top-abs-dpdg-per-stage",
            "1",
            "--context-radius",
            "0",
        ]
    )

    context = pd.read_csv(output)
    assert exit_code == 0
    assert sorted(context["stage"].astype(int).tolist()) == [7, 8]
    assert len(context) == 2


def test_derivative_context_default_filters_to_existing_derivative_csv_rows(tmp_path, capsys) -> None:
    review = tmp_path / "context_review.csv"
    review.write_text(
        "stage,pressure_derivative_output_path,derivative_csv_exists,manual_review_priority,manual_review_reasons\n"
        "7,stage_07_derivative.csv,True,medium,large absolute dP/dG\n"
        "9,stage_09_derivative.csv,False,high,not ready\n",
        encoding="utf-8",
    )
    _write_context_derivative_csv(tmp_path / "stage_07_derivative.csv")
    output = tmp_path / "context.csv"

    exit_code = main(
        [
            "derivative-context",
            "--review",
            str(review),
            "--derivative-dir",
            str(tmp_path),
            "--output",
            str(output),
            "--top-abs-dpdg-per-stage",
            "1",
            "--context-radius",
            "0",
        ]
    )

    captured = capsys.readouterr()
    context = pd.read_csv(output)
    assert exit_code == 0
    assert context["stage"].astype(int).tolist() == [7]
    assert "derivative_context_stage_count=1" in captured.out
    assert "closure_was_computed=False" in captured.out


def test_derivative_context_explicit_stage_ignores_derivative_csv_exists_filter(tmp_path) -> None:
    review = tmp_path / "context_review.csv"
    review.write_text(
        "stage,pressure_derivative_output_path,derivative_csv_exists,manual_review_priority,manual_review_reasons\n"
        "9,stage_09_derivative.csv,False,high,not ready\n",
        encoding="utf-8",
    )
    output = tmp_path / "context.csv"

    exit_code = main(
        [
            "derivative-context",
            "--review",
            str(review),
            "--derivative-dir",
            str(tmp_path),
            "--output",
            str(output),
            "--stages",
            "9",
            "--top-abs-dpdg-per-stage",
            "1",
            "--context-radius",
            "0",
        ]
    )

    context = pd.read_csv(output)
    assert exit_code == 0
    assert context["stage"].astype(int).tolist() == [9]
    assert context.iloc[0]["context_status"] == "missing_derivative_csv"
    assert bool(context.iloc[0]["closure_was_computed"]) is False


def test_derivative_context_derivative_csv_exists_string_compatibility(tmp_path) -> None:
    review = tmp_path / "context_review.csv"
    review.write_text(
        "stage,pressure_derivative_output_path,derivative_csv_exists,manual_review_priority,manual_review_reasons\n"
        "1,stage_01_derivative.csv,TRUE,low,ok\n"
        "2,stage_02_derivative.csv,true,low,ok\n"
        "3,stage_03_derivative.csv,1,low,ok\n"
        "4,stage_04_derivative.csv,yes,low,ok\n"
        "5,stage_05_derivative.csv,Y,low,ok\n"
        "6,stage_06_derivative.csv,False,high,skip\n"
        "7,stage_07_derivative.csv,false,high,skip\n"
        "8,stage_08_derivative.csv,0,high,skip\n"
        "9,stage_09_derivative.csv,no,high,skip\n",
        encoding="utf-8",
    )
    for stage in [1, 2, 3, 4, 5]:
        _write_context_derivative_csv(tmp_path / f"stage_{stage:02d}_derivative.csv")
    output = tmp_path / "context.csv"

    exit_code = main(
        [
            "derivative-context",
            "--review",
            str(review),
            "--derivative-dir",
            str(tmp_path),
            "--output",
            str(output),
            "--top-abs-dpdg-per-stage",
            "1",
            "--context-radius",
            "0",
        ]
    )

    context = pd.read_csv(output)
    assert exit_code == 0
    assert sorted(context["stage"].astype(int).tolist()) == [1, 2, 3, 4, 5]
