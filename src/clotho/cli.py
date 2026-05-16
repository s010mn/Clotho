from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pandas as pd

from clotho import __version__
from clotho.batch import run_derivative_batch
from clotho.closure import (
    build_closure_g_time_efficiency_audit,
    build_fracture_initiation_tp_audit,
    build_tp_sensitivity_efficiency,
    build_tp_reachability_audit,
    run_efficiency_prior_closure_sweep,
    run_closure_batch,
    write_closure_batch_outputs,
)
from clotho.grid_search import (
    ALLOWED_COUPLING,
    ALLOWED_FLOW_ALLOCATION,
    ALLOWED_PARALLEL_BACKENDS,
    ALLOWED_PERF_MODES,
    ALLOWED_WINDOW_MODES,
    GridSearchConfig,
    PhysicalPlausibilityCriteria,
    parse_choice_grid,
    parse_float_grid,
    parse_int_grid,
    run_grid_search,
)
from clotho.g_function import nolte_g_time
from clotho.pressure_derivative import derivative_value_summary, pressure_derivative_against_g_time
from clotho.review import (
    build_derivative_context_table,
    build_derivative_review_table,
    format_top_review_rows,
    write_derivative_context_csv,
    write_derivative_review_csv,
)
from clotho.stage_data import (
    StageInfo,
    add_estimated_bottomhole_pressure,
    apply_elapsed_duplicate_policy,
    elapsed_seconds_after,
    falloff_window_after_shut_in,
    find_shut_in_index,
    picked_duration_seconds,
    rate_positive_duration_seconds,
    read_stage_curve,
    read_stage_params,
    volume_over_max_rate_duration_seconds,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clotho",
        description=(
            "Research command surface for shut-in pressure response, "
            "G-function/DFIT analysis, and fracture-network parameter evaluation."
        ),
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser(
        "version",
        help="Print the Clotho package version.",
    )

    window_audit = subparsers.add_parser(
        "window-audit",
        help="Audit injection-duration choices for one external well stage.",
    )
    window_audit.add_argument("--stage-params", required=True, type=Path, help="stage_params.csv path.")
    window_audit.add_argument("--well-root", required=True, type=Path, help="Well directory containing stage_data/.")
    window_audit.add_argument("--stage", required=True, type=int, help="Stage number to audit.")
    window_audit.add_argument("--well", default=None, help="Optional well name filter.")
    window_audit.add_argument("--volume-column", required=True, help="Cumulative volume column, e.g. total_volume.")
    window_audit.add_argument(
        "--max-sustained-rate",
        required=True,
        type=float,
        help="Human-picked or audited maximum sustained rate; not auto-detected.",
    )
    window_audit.add_argument("--rate-time-unit", required=True, help="Rate time unit, e.g. minute.")
    window_audit.add_argument("--min-rate", default=0.0, type=float, help="Rate threshold for rate-positive duration.")
    window_audit.add_argument(
        "--picked-start-time",
        default=None,
        help="Optional human-picked start time, such as fracture-opening time.",
    )
    window_audit.add_argument(
        "--g-time-m",
        default=None,
        type=float,
        help="Optional Nolte G-time m parameter. Omit it to keep the old window-audit output.",
    )
    window_audit.add_argument(
        "--g-time-count",
        default=8,
        type=int,
        help="Number of post-shut-in samples to print when --g-time-m is provided.",
    )
    window_audit.add_argument(
        "--derivative-readiness",
        action="store_true",
        help="Audit basic data conditions for a future dP/dG calculation; does not compute derivatives.",
    )
    window_audit.add_argument(
        "--valid-falloff-end-elapsed",
        default=None,
        type=float,
        help=(
            "Manual end elapsed seconds for the valid natural falloff window. "
            "Only valid with --derivative-readiness; this is not automatic bleedoff detection."
        ),
    )
    window_audit.add_argument(
        "--elapsed-duplicate-policy",
        choices=["none", "keep-first", "keep-last", "mean"],
        default="none",
        help=(
            "Explicit duplicate elapsed handling for derivative-readiness only. "
            "Default none means no silent deduplication."
        ),
    )
    window_audit.add_argument(
        "--pressure-derivative-preview",
        action="store_true",
        help=(
            "Preview dP/dG and G dP/dG on the manual falloff window. "
            "Requires --derivative-readiness and --valid-falloff-end-elapsed; does not compute closure."
        ),
    )
    window_audit.add_argument(
        "--pressure-derivative-count",
        default=8,
        type=int,
        help="Number of derivative preview samples to print when --pressure-derivative-preview is provided.",
    )
    window_audit.add_argument(
        "--pressure-derivative-output",
        default=None,
        type=Path,
        help="Optional CSV path for the full pressure derivative table. Requires --pressure-derivative-preview.",
    )

    derivative_batch = subparsers.add_parser(
        "derivative-batch",
        help="Run manifest-driven batch pressure derivative export for reproducible experiments.",
    )
    derivative_batch.add_argument("--stage-params", required=True, type=Path, help="stage_params.csv path.")
    derivative_batch.add_argument("--well-root", required=True, type=Path, help="Well directory containing stage_data/.")
    derivative_batch.add_argument("--manifest", required=True, type=Path, help="Manual derivative batch manifest CSV path.")
    derivative_batch.add_argument("--output-dir", required=True, type=Path, help="Existing output directory for CSV files.")
    derivative_batch.add_argument("--volume-column", required=True, help="Cumulative volume column, e.g. total_volume.")
    derivative_batch.add_argument("--rate-time-unit", required=True, help="Rate time unit, e.g. minute.")
    derivative_batch.add_argument("--g-time-m", required=True, type=float, help="Nolte G-time m parameter.")
    derivative_batch.add_argument("--well", default=None, help="Optional well name filter.")
    derivative_batch.add_argument("--min-rate", default=10.0, type=float, help="Rate threshold recorded in summary.")
    derivative_batch.add_argument(
        "--summary-name",
        default="derivative_batch_summary.csv",
        help="Summary CSV file name inside output-dir.",
    )

    derivative_review = subparsers.add_parser(
        "derivative-review",
        help="Build a manual review CSV from derivative-batch summary and derivative CSV files.",
    )
    derivative_review.add_argument("--summary", required=True, type=Path, help="derivative-batch summary CSV path.")
    derivative_review.add_argument("--output", required=True, type=Path, help="Review CSV output path.")
    derivative_review.add_argument(
        "--derivative-dir",
        default=None,
        type=Path,
        help="Directory containing per-stage derivative CSV files. Defaults to the summary CSV directory.",
    )
    derivative_review.add_argument(
        "--large-duplicate-removal-threshold",
        default=10,
        type=int,
        help="Rows removed by duplicate policy at or above this value are flagged for review.",
    )
    derivative_review.add_argument(
        "--large-abs-dpdg-threshold",
        default=None,
        type=float,
        help="Optional absolute dP/dG threshold for a medium-priority numerical-range flag.",
    )
    derivative_review.add_argument(
        "--positive-derivative-ratio-threshold",
        default=0.5,
        type=float,
        help="Positive dP/dG ratio at or above this value is flagged for review.",
    )
    derivative_review.add_argument(
        "--early-transient-window-seconds",
        default=None,
        type=float,
        help=(
            "Optional early-time transient / water-hammer plausibility audit window in seconds; "
            "manual review flag only, no inversion and no closure."
        ),
    )
    derivative_review.add_argument(
        "--early-transient-pressure-range-threshold",
        default=1.0,
        type=float,
        help="Early-window pressure range threshold in MPa for the optional transient risk flag.",
    )
    derivative_review.add_argument(
        "--print-top-n",
        default=0,
        type=int,
        help="Print top-N manual triage rows by dP/dG absolute max and positive ratio; does not compute closure.",
    )

    derivative_context = subparsers.add_parser(
        "derivative-context",
        help="Export dP/dG extreme rows and neighboring context for manual review; does not compute closure.",
    )
    derivative_context.add_argument("--review", required=True, type=Path, help="derivative-review CSV path.")
    derivative_context.add_argument("--output", required=True, type=Path, help="Context CSV output path.")
    derivative_context.add_argument(
        "--derivative-dir",
        default=None,
        type=Path,
        help="Directory containing per-stage derivative CSV files. Defaults to the review CSV directory.",
    )
    derivative_context.add_argument(
        "--stages",
        default=None,
        help="Optional comma-separated stage list, e.g. 5,21,7,8.",
    )
    derivative_context.add_argument(
        "--top-abs-dpdg-per-stage",
        default=3,
        type=int,
        help="Number of largest absolute dP/dG center rows to export per stage.",
    )
    derivative_context.add_argument(
        "--context-radius",
        default=2,
        type=int,
        help="Number of neighboring rows before and after each center row.",
    )

    closure_batch = subparsers.add_parser(
        "closure-batch",
        help="Run manifest-driven batch closure candidate analysis with volume balance and observation correlation.",
    )
    closure_batch.add_argument("--stage-params", required=True, type=Path, help="stage_params.csv path.")
    closure_batch.add_argument("--well-root", required=True, type=Path, help="Well directory containing stage_data/.")
    closure_batch.add_argument("--manifest", required=True, type=Path, help="Manual manifest CSV path (stage, max_sustained_rate, valid_falloff_end_elapsed).")
    closure_batch.add_argument("--observations", default=None, type=Path, help="Optional observations CSV for correlation (stage + metric columns).")
    closure_batch.add_argument("--output", required=True, type=Path, help="Per-stage closure-volume summary CSV output path.")
    closure_batch.add_argument("--correlation-output", default=None, type=Path, help="Optional correlation summary CSV output path.")
    closure_batch.add_argument("--cluster-output", default=None, type=Path, help="Optional per-cluster physical PKN audit CSV output path.")
    closure_batch.add_argument("--volume-column", default="total_volume", help="Cumulative volume column.")
    closure_batch.add_argument("--rate-time-unit", choices=["second", "minute"], default="minute", help="Rate time unit.")
    closure_batch.add_argument("--min-rate", default=10.0, type=float, help="Rate threshold for fracture initiation candidate.")
    closure_batch.add_argument("--g-time-m", default=0.8, type=float, help="Nolte G-time m parameter.")
    closure_batch.add_argument("--elapsed-duplicate-policy", choices=["none", "keep-first", "keep-last", "mean"], default="keep-last", help="Duplicate elapsed handling.")
    closure_batch.add_argument("--closure-min-elapsed-seconds", default=15.0, type=float, help="Minimum elapsed seconds before searching for closure candidates.")
    closure_batch.add_argument("--large-abs-dpdg-threshold", default=10000.0, type=float, help="Large absolute dP/dG threshold.")
    closure_batch.add_argument("--pressure-source", choices=["estimated-bottomhole", "wellhead"], default="estimated-bottomhole", help="Pressure column for analysis.")
    closure_batch.add_argument("--perforation-friction-mpa", default=0.0, type=float, help="Perforation friction pressure correction (MPa).")
    closure_batch.add_argument("--wellbore-storage-coeff-m3-per-mpa", default=0.0, type=float, help="Wellbore storage coefficient for volume correction.")
    closure_batch.add_argument("--method-preference", choices=["barree", "mcclure", "barree-then-mcclure", "mcclure-then-barree"], default="barree-then-mcclure", help="Closure candidate method preference.")
    closure_batch.add_argument("--well", default=None, help="Optional well name filter.")
    closure_batch.add_argument("--stress-shadow-alpha", default=1.0, type=float, help="Stress shadow coupling alpha (0=no shadow).")
    closure_batch.add_argument("--no-stress-shadow", "--no-stress-shadow-control", dest="no_stress_shadow", action="store_true", help="Disable stress shadow (alpha=0).")
    closure_batch.add_argument("--flow-allocation", choices=["stress-shadow", "uniform"], default="stress-shadow", help="Flow allocation method.")
    closure_batch.add_argument("--flow-allocation-exponent", default=1.0, type=float, help="Flow allocation exponent gamma (eta_i = xi_i^gamma / sum).")
    closure_batch.add_argument("--pkn-C-coupling", choices=["stage-constant", "shadow-scaled"], default="stage-constant", help="Per-cluster leakoff coupling. stage-constant: C_L_i = C_stage; shadow-scaled: C_L_i = xi_i * C_stage (legacy Phase 5D.4 coupling).")
    closure_batch.add_argument("--pkn-Hw-m", default=None, type=float, help="Explicit PKN fracture height H_w in meters. Omit to use the default 50 m.")

    closure_eff_audit = subparsers.add_parser(
        "closure-efficiency-audit",
        help="Build Phase 5H.1 closure G-time / tp / efficiency diagnostic CSVs from a closure-batch summary.",
    )
    closure_eff_audit.add_argument("--summary", required=True, type=Path, help="closure-batch summary CSV path.")
    closure_eff_audit.add_argument("--output-dir", required=True, type=Path, help="Existing or new /tmp output directory.")
    closure_eff_audit.add_argument("--g-time-m", default=0.8, type=float, help="Nolte G-time m parameter used for tp sensitivity.")
    closure_eff_audit.add_argument(
        "--tp-multipliers",
        default="0.5,0.7,0.85,1.0,1.15,1.3",
        help="Comma-separated tp multipliers for fixed-closure sensitivity.",
    )

    closure_eff_sweep = subparsers.add_parser(
        "closure-efficiency-sweep",
        help="Phase 5I efficiency-prior closure candidate sweep. CSV-only sensitivity; does not change default closure pick.",
    )
    closure_eff_sweep.add_argument("--stage-summary", default=None, type=Path, help="Optional existing selected closure summary; accepted for audit provenance.")
    closure_eff_sweep.add_argument("--stage-params", required=True, type=Path)
    closure_eff_sweep.add_argument("--well-root", required=True, type=Path)
    closure_eff_sweep.add_argument("--manifest", required=True, type=Path)
    closure_eff_sweep.add_argument("--observations", required=True, type=Path)
    closure_eff_sweep.add_argument("--output", required=True, type=Path)
    closure_eff_sweep.add_argument("--correlation-output", required=True, type=Path)
    closure_eff_sweep.add_argument("--availability-output", required=True, type=Path)
    closure_eff_sweep.add_argument("--g-time-scale-output", required=True, type=Path)
    closure_eff_sweep.add_argument("--efficiency-grid", default="0.10,0.15,0.20,0.30,0.40,0.60")
    closure_eff_sweep.add_argument("--closure-mode", choices=["selected", "efficiency-prior", "both"], default="both")
    closure_eff_sweep.add_argument("--volume-column", default="total_volume")
    closure_eff_sweep.add_argument("--rate-time-unit", choices=["second", "minute"], default="minute")
    closure_eff_sweep.add_argument("--min-rate", default=10.0, type=float)
    closure_eff_sweep.add_argument("--g-time-m", default=0.8, type=float)
    closure_eff_sweep.add_argument("--elapsed-duplicate-policy", choices=["none", "keep-first", "keep-last", "mean"], default="keep-last")
    closure_eff_sweep.add_argument("--pressure-source", choices=["estimated-bottomhole", "wellhead"], default="estimated-bottomhole")
    closure_eff_sweep.add_argument("--stress-shadow-alpha", default=1.0, type=float)
    closure_eff_sweep.add_argument("--flow-allocation", choices=["stress-shadow", "uniform"], default="stress-shadow")
    closure_eff_sweep.add_argument("--flow-allocation-exponent", default=1.0, type=float)
    closure_eff_sweep.add_argument("--pkn-C-coupling", choices=["stage-constant", "shadow-scaled"], default="stage-constant")
    closure_eff_sweep.add_argument("--pkn-Hw-m", default=None, type=float)
    closure_eff_sweep.add_argument("--well", default=None)

    tp_reachability = subparsers.add_parser(
        "closure-tp-reachability-audit",
        help="Phase 5J tp / valid-window reachability audit. CSV-only diagnostic; does not change default tp.",
    )
    tp_reachability.add_argument("--stage-summary", required=True, type=Path)
    tp_reachability.add_argument(
        "--efficiency-prior-stage-table",
        default=None,
        type=Path,
        help="Optional Phase 5I efficiency_prior_stage_table.csv used to supply per-stage max_available_Gc.",
    )
    tp_reachability.add_argument("--output", required=True, type=Path)
    tp_reachability.add_argument("--efficiency-grid", default="0.10,0.15,0.20,0.30,0.40")
    tp_reachability.add_argument("--g-time-m", default=0.8, type=float)
    tp_reachability.add_argument("--multiplier-min", default=0.05, type=float)
    tp_reachability.add_argument("--multiplier-max", default=2.0, type=float)

    initiation_audit = subparsers.add_parser(
        "fracture-initiation-audit",
        help="Phase 5K fracture initiation timing / tp rule audit. CSV-only diagnostic; does not change default tp.",
    )
    initiation_audit.add_argument("--stage-params", required=True, type=Path)
    initiation_audit.add_argument("--well-root", required=True, type=Path)
    initiation_audit.add_argument("--manifest", required=True, type=Path)
    initiation_audit.add_argument("--tp-reachability", required=True, type=Path)
    initiation_audit.add_argument("--output", required=True, type=Path)
    initiation_audit.add_argument("--summary-output", required=True, type=Path)
    initiation_audit.add_argument("--volume-column", default="total_volume")
    initiation_audit.add_argument("--rate-time-unit", choices=["second", "minute"], default="minute")
    initiation_audit.add_argument("--min-rate", default=10.0, type=float)
    initiation_audit.add_argument("--design-rate", default=18.0, type=float)
    initiation_audit.add_argument("--rate-step-fraction", default=0.8, type=float)
    initiation_audit.add_argument("--pressure-source", choices=["estimated-bottomhole", "wellhead"], default="estimated-bottomhole")
    initiation_audit.add_argument("--stable-pressure-window-points", default=20, type=int)
    initiation_audit.add_argument("--stable-pressure-slope-threshold", default=0.05, type=float)
    initiation_audit.add_argument("--well", default=None)

    grid = subparsers.add_parser(
        "pkn-grid-search",
        help="Phase 5F physically constrained PKN parameter grid search. Sensitivity/audit tool, not an inversion. Outputs go to /tmp; do not commit.",
    )
    grid.add_argument("--stage-params", required=True, type=Path)
    grid.add_argument("--well-root", required=True, type=Path)
    grid.add_argument("--manifest", required=True, type=Path)
    grid.add_argument("--observations", required=True, type=Path)
    grid.add_argument("--output-dir", required=True, type=Path)
    grid.add_argument("--volume-column", default="total_volume")
    grid.add_argument("--rate-time-unit", choices=["second", "minute"], default="minute")
    grid.add_argument("--min-rate", default=10.0, type=float)
    grid.add_argument("--g-time-m", default=0.8, type=float)
    grid.add_argument("--pressure-source", choices=["estimated-bottomhole", "wellhead"], default="estimated-bottomhole")
    grid.add_argument("--method-preference", choices=["barree", "mcclure", "barree-then-mcclure", "mcclure-then-barree"], default="barree-then-mcclure")
    grid.add_argument("--elapsed-duplicate-policy", choices=["none", "keep-first", "keep-last", "mean"], default="keep-last")
    grid.add_argument("--well", default=None)
    grid.add_argument("--max-cases", type=int, default=200000, help="Cap on total grid size; refuse to run if exceeded (no silent sampling).")
    grid.add_argument("--workers", type=int, default=1, help="Number of parallel grid cases to run. Default 1 preserves serial behavior.")
    grid.add_argument("--parallel-backend", choices=ALLOWED_PARALLEL_BACKENDS, default="thread", help="Parallel executor backend for --workers > 1.")
    grid.add_argument("--closure-min-elapsed-grid", default="15,30,60")
    grid.add_argument("--pkn-C-coupling-grid", default="stage-constant,shadow-scaled")
    grid.add_argument("--flow-allocation-grid", default="stress-shadow,uniform")
    grid.add_argument("--flow-allocation-exponent-grid", default="0,1,2")
    grid.add_argument("--stress-shadow-alpha-grid", default="0,0.5,1,2")
    grid.add_argument("--pkn-Hw-grid", dest="pkn_H_w_grid", default="50")
    grid.add_argument("--fleak-grid", default="0.25,0.5,0.75,1.0")
    grid.add_argument("--C-multiplier-grid", default="0.1,0.2,0.282,0.5,0.75,1.0,1.5,2.0")
    grid.add_argument("--effective-volume-factor-grid", default="0.25,0.5,0.75,1.0")
    grid.add_argument("--wellbore-storage-coeff-grid", default="0,0.1,0.5,1,2,5")
    grid.add_argument("--perforation-friction-mode-grid", default="none,constant,orifice,zero-after-shutin")
    grid.add_argument("--perforation-friction-mpa-grid", default="0,1,2,5")
    grid.add_argument("--perforation-diameter-mm-grid", default="8,10,12,14")
    grid.add_argument("--perforations-per-cluster-grid", default="4,6,8,10,12")
    grid.add_argument("--perforation-Cd-grid", default="0.55,0.7,0.85,0.95")
    grid.add_argument("--fluid-density-kg-m3-grid", default="1000,1050,1100")
    grid.add_argument("--stable-min-r2-grid", default="0.5,0.7,0.85")
    grid.add_argument("--stable-min-points-grid", default="6,8,12")
    grid.add_argument("--stable-window-mode-grid", default="best-r2,longest,early-best")
    grid.add_argument("--tp-multiplier-grid", default="0.7,0.85,1.0,1.15,1.3")
    grid.add_argument("--plausibility-min-n", type=int, default=20)
    grid.add_argument("--plausibility-max-placeholder", type=int, default=2)
    grid.add_argument("--plausibility-min-eff", type=float, default=0.10)
    grid.add_argument("--plausibility-max-eff", type=float, default=0.50)
    grid.add_argument("--plausibility-max-below-5pct", type=int, default=5)
    grid.add_argument("--plausibility-min-pkn-ok", type=int, default=25)
    grid.add_argument("--plausibility-min-r2", type=float, default=0.5)
    grid.add_argument("--plausibility-min-C-mult", type=float, default=0.1)
    grid.add_argument("--plausibility-max-C-mult", type=float, default=2.0)

    return parser


def _format_float_list(values) -> str:
    """把数字列表格式化成稳定、易读、易测试的一行。"""
    return "[" + ", ".join(f"{float(value):.12g}" for value in values) + "]"


def _bool_text(value: bool) -> str:
    """CLI 输出使用 True/False，方便肉眼阅读和测试。"""
    return "True" if value else "False"


def _format_optional_float(value: float) -> str:
    """把可能缺失的统计值格式化成稳定文本。"""
    if not np.isfinite(value):
        return "nan"
    return f"{float(value):.12g}"


def _sequence_step_summary(values) -> dict[str, bool | int]:
    """检查时间或 G-time 序列是否重复、倒退、严格递增。"""
    array = np.asarray(values, dtype=float)
    step = np.diff(array)
    if len(step) == 0:
        return {
            "duplicate_step_count": 0,
            "backward_step_count": 0,
            "strictly_increasing": True,
            "nondecreasing": True,
        }
    return {
        "duplicate_step_count": int(np.count_nonzero(step == 0.0)),
        "backward_step_count": int(np.count_nonzero(step < 0.0)),
        "strictly_increasing": bool(np.all(step > 0.0)),
        "nondecreasing": bool(np.all(step >= 0.0)),
    }


def _pressure_summary(values) -> dict[str, float | int]:
    """统计压力列的有限值、零值、非正值和基本范围。"""
    array = np.asarray(values, dtype=float)
    finite = array[np.isfinite(array)]
    summary: dict[str, float | int] = {
        "finite_count": int(len(finite)),
        "nan_or_inf_count": int(len(array) - len(finite)),
        "zero_count": int(np.count_nonzero(array == 0.0)),
        "nonpositive_count": int(np.count_nonzero(array <= 0.0)),
        "min": float("nan"),
        "median": float("nan"),
        "max": float("nan"),
    }
    if len(finite):
        summary["min"] = float(np.min(finite))
        summary["median"] = float(np.median(finite))
        summary["max"] = float(np.max(finite))
    return summary


def _format_blockers(blockers: list[str]) -> str:
    """把 readiness 阻断原因格式化为一行。"""
    if not blockers:
        return "none"
    return "; ".join(blockers)


# 输入：stage_params 读取结果、段号和可选井名。输出：唯一匹配的压裂段。
def _find_stage(stages: list[StageInfo], *, stage_number: int, well: str | None) -> StageInfo:
    matches = [stage for stage in stages if stage.stage == stage_number and (well is None or stage.well == well)]
    if not matches:
        raise ValueError(f"找不到 stage={stage_number} 的记录")
    if len(matches) > 1:
        raise ValueError(f"stage={stage_number} 匹配多行，请用 --well 指定井名")
    return matches[0]


def _print_pressure_summary(prefix: str, summary: dict[str, float | int]) -> None:
    """输出压力摘要；只描述数据质量，不做导数解释。"""
    print(f"{prefix}_finite_count={summary['finite_count']}")
    print(f"{prefix}_nan_or_inf_count={summary['nan_or_inf_count']}")
    print(f"{prefix}_zero_count={summary['zero_count']}")
    print(f"{prefix}_nonpositive_count={summary['nonpositive_count']}")
    print(f"{prefix}_min={_format_optional_float(float(summary['min']))}")
    print(f"{prefix}_median={_format_optional_float(float(summary['median']))}")
    print(f"{prefix}_max={_format_optional_float(float(summary['max']))}")


def _print_derivative_value_summary(prefix: str, summary: dict[str, float | int]) -> None:
    """输出导数数值摘要；只描述数值，不做 closure 解释。"""
    print(f"{prefix}_finite_count={summary['finite_count']}")
    print(f"{prefix}_nan_or_inf_count={summary['nan_or_inf_count']}")
    print(f"{prefix}_positive_count={summary['positive_count']}")
    print(f"{prefix}_negative_count={summary['negative_count']}")
    print(f"{prefix}_zero_count={summary['zero_count']}")
    print(f"{prefix}_min={_format_optional_float(float(summary['min']))}")
    print(f"{prefix}_median={_format_optional_float(float(summary['median']))}")
    print(f"{prefix}_max={_format_optional_float(float(summary['max']))}")


def _derivative_readiness_state(
    *,
    window,
    stage: StageInfo,
    elapsed_all,
    g_time_all,
    tp_seconds: float,
) -> dict[str, object]:
    """组装未来 dP/dG 的最基本数据前置条件；这里不计算导数。"""
    elapsed_summary = _sequence_step_summary(elapsed_all)
    g_time_summary = _sequence_step_summary(g_time_all)

    whp_post = window["wellhead_pressure_mpa"].to_numpy(dtype=float)
    pressure_column = "wellhead_pressure_mpa"
    estimated_available = stage.liquid_column_pressure_mpa is not None
    pressure_window = window
    pressure_post = whp_post

    if estimated_available:
        pressure_window = add_estimated_bottomhole_pressure(window, stage)
        pressure_column = "estimated_bottomhole_pressure_mpa"
        pressure_post = pressure_window[pressure_column].to_numpy(dtype=float)

    whp_summary = _pressure_summary(whp_post)
    pressure_summary = _pressure_summary(pressure_post)
    g_time_array = np.asarray(g_time_all, dtype=float)

    blockers: list[str] = []
    if len(g_time_array) < 3:
        blockers.append("post-shut-in samples fewer than 3")
    if not np.all(np.isfinite(g_time_array)):
        blockers.append("G-time contains NaN or inf")
    if int(pressure_summary["nan_or_inf_count"]) > 0:
        blockers.append("pressure column contains NaN or inf")
    if not bool(g_time_summary["strictly_increasing"]):
        blockers.append("G-time is not strictly increasing")

    return {
        "elapsed_summary": elapsed_summary,
        "g_time_summary": g_time_summary,
        "pressure_column": pressure_column,
        "estimated_available": estimated_available,
        "pressure_window": pressure_window,
        "pressure_values": pressure_post,
        "whp_summary": whp_summary,
        "pressure_summary": pressure_summary,
        "g_time_array": g_time_array,
        "tp_seconds": float(tp_seconds),
        "blockers": blockers,
    }


def _pressure_step_counts(pressure) -> dict[str, int]:
    """统计相邻压力差的正、负、零数量；只做数据摘要。"""
    step = np.diff(np.asarray(pressure, dtype=float))
    return {
        "positive": int(np.count_nonzero(step > 0.0)),
        "negative": int(np.count_nonzero(step < 0.0)),
        "zero": int(np.count_nonzero(step == 0.0)),
    }


def _write_pressure_derivative_csv(
    *,
    path: Path,
    readiness_state: dict[str, object],
    delta,
    g_time,
    pressure,
    dP_dG,
    G_dP_dG,
) -> None:
    """写出完整有效窗口导数表；这是 CSV 数据输出，不是 Excel/PNG reporting。"""
    output = Path(path)
    if not output.parent.exists():
        raise ValueError(f"parent directory does not exist: {output.parent}")

    pressure_window = readiness_state["pressure_window"]
    data: dict[str, object] = {
        "row_number": np.arange(len(g_time), dtype=int),
        "elapsed_seconds": pressure_window["elapsed_seconds"].to_numpy(dtype=float),
        "delta": np.asarray(delta, dtype=float),
        "nolte_g_time": np.asarray(g_time, dtype=float),
        "pressure_column": [str(readiness_state["pressure_column"])] * len(g_time),
        "pressure_mpa": np.asarray(pressure, dtype=float),
        "wellhead_pressure_mpa": pressure_window["wellhead_pressure_mpa"].to_numpy(dtype=float),
        "dP_dG_mpa": np.asarray(dP_dG, dtype=float),
        "G_dP_dG_mpa": np.asarray(G_dP_dG, dtype=float),
    }
    if "estimated_bottomhole_pressure_mpa" in pressure_window.columns:
        data["estimated_bottomhole_pressure_mpa"] = pressure_window[
            "estimated_bottomhole_pressure_mpa"
        ].to_numpy(dtype=float)
    if "time_text" in pressure_window.columns:
        data["time_text"] = pressure_window["time_text"].astype(str).to_numpy()

    pd.DataFrame(data).to_csv(output, index=False)


def _print_pressure_derivative_output_status(
    *,
    requested: bool,
    written: bool,
    output_path: Path | None,
) -> None:
    print(f"pressure_derivative_output_requested={_bool_text(requested)}")
    print(f"pressure_derivative_output_written={_bool_text(written)}")
    print(f"pressure_derivative_output_path={output_path if output_path is not None else 'none'}")


def _print_pressure_derivative_preview(
    *,
    readiness_state: dict[str, object],
    count: int,
    output_path: Path | None,
) -> bool:
    """在 readiness 通过时输出 dP/dG 预览；这里不做 closure。"""
    blockers = readiness_state["blockers"]
    output_requested = output_path is not None
    print("pressure_derivative_preview_requested=True")
    if blockers:
        print("pressure_derivative_was_computed=False")
        print(f"pressure_derivative_blockers={_format_blockers(blockers)}")
        _print_pressure_derivative_output_status(
            requested=output_requested,
            written=False,
            output_path=output_path,
        )
        print("closure_was_computed=False")
        return False

    g_time = np.asarray(readiness_state["g_time_array"], dtype=float)
    pressure = np.asarray(readiness_state["pressure_values"], dtype=float)
    elapsed = readiness_state["pressure_window"]["elapsed_seconds"].to_numpy(dtype=float)
    dP_dG, G_dP_dG = pressure_derivative_against_g_time(g_time, pressure)
    preview_count = min(int(count), len(g_time))
    delta = elapsed / float(readiness_state["tp_seconds"])

    print("pressure_derivative_was_computed=True")
    print("pressure_derivative_scope=falloff_window")
    print(f"pressure_derivative_pressure_column={readiness_state['pressure_column']}")
    print("pressure_derivative_method=numpy.gradient_edge_order_1")
    print(f"pressure_derivative_count_requested={count}")
    print(f"pressure_derivative_count_returned={preview_count}")
    print(f"pressure_derivative_g_time={_format_float_list(g_time[:preview_count])}")
    print(f"pressure_derivative_pressure_mpa={_format_float_list(pressure[:preview_count])}")
    print(f"pressure_derivative_dP_dG_mpa={_format_float_list(dP_dG[:preview_count])}")
    print(f"pressure_derivative_G_dP_dG_mpa={_format_float_list(G_dP_dG[:preview_count])}")
    _print_derivative_value_summary(
        "pressure_derivative_dP_dG",
        derivative_value_summary(dP_dG),
    )
    _print_derivative_value_summary(
        "pressure_derivative_G_dP_dG",
        derivative_value_summary(G_dP_dG),
    )
    pressure_steps = _pressure_step_counts(pressure)
    print(f"pressure_derivative_pressure_step_positive_count={pressure_steps['positive']}")
    print(f"pressure_derivative_pressure_step_negative_count={pressure_steps['negative']}")
    print(f"pressure_derivative_pressure_step_zero_count={pressure_steps['zero']}")

    output_written = False
    if output_requested:
        _write_pressure_derivative_csv(
            path=output_path,
            readiness_state=readiness_state,
            delta=delta,
            g_time=g_time,
            pressure=pressure,
            dP_dG=dP_dG,
            G_dP_dG=G_dP_dG,
        )
        output_written = True
    _print_pressure_derivative_output_status(
        requested=output_requested,
        written=output_written,
        output_path=output_path,
    )
    print("closure_was_computed=False")
    return True


def _print_derivative_readiness(state: dict[str, object], *, derivative_was_computed: bool) -> None:
    """输出未来 dP/dG 的最基本数据前置条件。"""
    elapsed_summary = state["elapsed_summary"]
    g_time_summary = state["g_time_summary"]
    g_time_array = state["g_time_array"]
    blockers = state["blockers"]

    print("derivative_readiness_scope=falloff_window")
    print("derivative_readiness_tp_source=volume_over_max_sustained_rate_seconds")
    print(f"derivative_readiness_pressure_column={state['pressure_column']}")
    print(f"derivative_readiness_post_shut_in_rows={len(g_time_array)}")
    print(f"derivative_readiness_elapsed_duplicate_step_count={elapsed_summary['duplicate_step_count']}")
    print(f"derivative_readiness_elapsed_backward_step_count={elapsed_summary['backward_step_count']}")
    print(f"derivative_readiness_elapsed_strictly_increasing={_bool_text(bool(elapsed_summary['strictly_increasing']))}")
    print(f"derivative_readiness_elapsed_nondecreasing={_bool_text(bool(elapsed_summary['nondecreasing']))}")
    print(f"derivative_readiness_g_time_duplicate_step_count={g_time_summary['duplicate_step_count']}")
    print(f"derivative_readiness_g_time_backward_step_count={g_time_summary['backward_step_count']}")
    print(f"derivative_readiness_g_time_strictly_increasing={_bool_text(bool(g_time_summary['strictly_increasing']))}")
    print(f"derivative_readiness_g_time_nondecreasing={_bool_text(bool(g_time_summary['nondecreasing']))}")
    _print_pressure_summary("derivative_readiness_wellhead_pressure", state["whp_summary"])
    print(f"derivative_readiness_estimated_bottomhole_pressure_available={_bool_text(bool(state['estimated_available']))}")
    _print_pressure_summary("derivative_readiness_estimated_bottomhole_pressure", state["pressure_summary"])
    print(f"derivative_readiness_ready={_bool_text(not blockers)}")
    print(f"derivative_readiness_blockers={_format_blockers(blockers)}")
    print(f"derivative_was_computed={_bool_text(derivative_was_computed)}")
    print("closure_was_computed=False")


def _parse_stage_list(text: str | None) -> list[int] | None:
    """解析逗号分隔 stage 列表；只用于人工审查筛选。"""
    if text is None:
        return None
    if text.strip() == "":
        raise ValueError("stages 不能为空")
    stages: list[int] = []
    for item in text.split(","):
        token = item.strip()
        if not token:
            raise ValueError("stages 不能包含空项")
        try:
            stage = int(token)
        except ValueError as exc:
            raise ValueError("stages 必须是逗号分隔的正整数") from exc
        if stage <= 0:
            raise ValueError("stages 必须是正整数")
        stages.append(stage)
    return stages


# 输入：derivative-context 命令参数。输出：退出码；导出极值行上下文，不判断 closure。
def _run_derivative_context(args: argparse.Namespace) -> int:
    if args.top_abs_dpdg_per_stage <= 0:
        raise ValueError("top_abs_dpdg_per_stage 必须 > 0")
    if args.context_radius < 0:
        raise ValueError("context_radius 必须 >= 0")
    stages = _parse_stage_list(args.stages)
    context = build_derivative_context_table(
        args.review,
        derivative_dir=args.derivative_dir,
        stages=stages,
        top_abs_dpdg_per_stage=args.top_abs_dpdg_per_stage,
        context_radius=args.context_radius,
    )
    output_path = write_derivative_context_csv(context, args.output)
    skipped_count = 0
    if "context_status" in context.columns and "stage" in context.columns:
        skipped_count = int(context.loc[context["context_status"] != "ok", "stage"].nunique())
    stage_count = int(context["stage"].nunique()) if "stage" in context.columns and len(context) else 0
    print(f"derivative_context_review_csv={args.review}")
    print(f"derivative_context_output={output_path}")
    print(f"derivative_context_stage_count={stage_count}")
    print(f"derivative_context_written_rows={len(context)}")
    print(f"derivative_context_skipped_stage_count={skipped_count}")
    print("closure_was_computed=False")
    return 0


# 输入：derivative-review 命令参数。输出：退出码；写人工审查清单，不判断 closure。
def _run_derivative_review(args: argparse.Namespace) -> int:
    if args.print_top_n < 0:
        raise ValueError("print_top_n 必须是 >= 0 的整数")
    if args.early_transient_window_seconds is not None:
        early_window = float(args.early_transient_window_seconds)
        if not np.isfinite(early_window) or early_window <= 0.0:
            raise ValueError("early_transient_window_seconds must be finite and > 0")
    if (
        not np.isfinite(float(args.early_transient_pressure_range_threshold))
        or float(args.early_transient_pressure_range_threshold) < 0.0
    ):
        raise ValueError("early_transient_pressure_range_threshold must be finite and >= 0")
    review = build_derivative_review_table(
        args.summary,
        derivative_dir=args.derivative_dir,
        large_duplicate_removal_threshold=args.large_duplicate_removal_threshold,
        positive_derivative_ratio_threshold=args.positive_derivative_ratio_threshold,
        large_abs_dpdg_threshold=args.large_abs_dpdg_threshold,
        early_transient_window_seconds=args.early_transient_window_seconds,
        early_transient_pressure_range_threshold=args.early_transient_pressure_range_threshold,
    )
    output_path = write_derivative_review_csv(review, args.output)
    priority_counts = review["manual_review_priority"].value_counts()
    print(f"review_stage_count={len(review)}")
    print(f"review_high_priority_count={int(priority_counts.get('high', 0))}")
    print(f"review_medium_priority_count={int(priority_counts.get('medium', 0))}")
    print(f"review_low_priority_count={int(priority_counts.get('low', 0))}")
    print(f"review_output_path={output_path}")
    early_enabled = args.early_transient_window_seconds is not None
    print(f"early_transient_audit_enabled={_bool_text(early_enabled)}")
    if early_enabled:
        risk_count = int(review["early_transient_risk"].astype(str).str.lower().isin(["true", "1", "yes", "y"]).sum())
        low_freq_count = int((review["water_hammer_plausibility_note"] == "plausible_low_frequency_only").sum())
        print(f"early_transient_window_seconds={_format_optional_float(float(args.early_transient_window_seconds))}")
        print(f"early_transient_risk_count={risk_count}")
        print(f"water_hammer_plausibility_low_frequency_count={low_freq_count}")
    for line in format_top_review_rows(
        review,
        column="dP_dG_abs_max",
        top_n=args.print_top_n,
        label="top_dP_dG_abs_max",
    ):
        print(line)
    for line in format_top_review_rows(
        review,
        column="dP_dG_positive_ratio",
        top_n=args.print_top_n,
        label="top_dP_dG_positive_ratio",
    ):
        print(line)
    print("closure_was_computed=False")
    return 0


# 输入：derivative-batch 命令参数。输出：退出码；写 CSV summary 和 ready stage 的导数表，不做 closure。
def _run_derivative_batch(args: argparse.Namespace) -> int:
    result = run_derivative_batch(
        stage_params_path=args.stage_params,
        well_root=args.well_root,
        manifest_path=args.manifest,
        output_dir=args.output_dir,
        volume_column=args.volume_column,
        rate_time_unit=args.rate_time_unit,
        g_time_m=args.g_time_m,
        well=args.well,
        min_rate=args.min_rate,
        summary_name=args.summary_name,
    )
    print(f"batch_stage_count={result['stage_count']}")
    print(f"batch_ready_stage_count={result['ready_stage_count']}")
    print(f"batch_not_ready_stage_count={result['not_ready_stage_count']}")
    print(f"batch_derivative_csv_written_count={result['derivative_csv_written_count']}")
    print(f"batch_summary_output_path={result['summary_path']}")
    print("closure_was_computed=False")
    return 0


# 输入：window-audit 命令参数。输出：退出码；只做窗口审计和可选 G-time/导数前置条件预览，不做导数、闭合或反演。
def _run_window_audit(args: argparse.Namespace) -> int:
    if args.g_time_m is not None and args.g_time_count <= 0:
        raise ValueError("g_time_count 必须大于 0")
    if args.derivative_readiness and args.g_time_m is None:
        raise ValueError("--derivative-readiness 需要同时传入 --g-time-m")
    if args.valid_falloff_end_elapsed is not None:
        valid_end = float(args.valid_falloff_end_elapsed)
        if not np.isfinite(valid_end) or valid_end < 0.0:
            raise ValueError("valid_falloff_end_elapsed 必须是有限且 >= 0 的数字")
        if not args.derivative_readiness:
            raise ValueError("--valid-falloff-end-elapsed 需要同时传入 --derivative-readiness")
    if args.elapsed_duplicate_policy != "none" and not args.derivative_readiness:
        raise ValueError("--elapsed-duplicate-policy 需要同时传入 --derivative-readiness")
    if args.pressure_derivative_count <= 0:
        raise ValueError("pressure_derivative_count 必须大于 0")
    if args.pressure_derivative_preview:
        if not args.derivative_readiness:
            raise ValueError("--pressure-derivative-preview 需要同时传入 --derivative-readiness")
        if args.g_time_m is None:
            raise ValueError("--pressure-derivative-preview 需要同时传入 --g-time-m")
        if args.valid_falloff_end_elapsed is None:
            raise ValueError("--pressure-derivative-preview 需要同时传入 --valid-falloff-end-elapsed")
    if args.pressure_derivative_output is not None and not args.pressure_derivative_preview:
        raise ValueError("--pressure-derivative-output 需要同时传入 --pressure-derivative-preview")
    if args.pressure_derivative_output is not None and not args.pressure_derivative_output.parent.exists():
        raise ValueError(f"parent directory does not exist: {args.pressure_derivative_output.parent}")

    stages = read_stage_params(args.stage_params)
    stage = _find_stage(stages, stage_number=args.stage, well=args.well)
    curve_file = args.well_root / stage.data_file
    curve = read_stage_curve(curve_file)
    shut_in_index = find_shut_in_index(curve, stage.shut_in_time)

    rate_positive_seconds = rate_positive_duration_seconds(
        curve,
        shut_in_index,
        min_rate=args.min_rate,
    )
    volume_rate_seconds = volume_over_max_rate_duration_seconds(
        curve,
        shut_in_index,
        max_sustained_rate=args.max_sustained_rate,
        rate_time_unit=args.rate_time_unit,
        volume_column=args.volume_column,
    )

    print(f"well={stage.well}")
    print(f"stage={stage.stage}")
    print(f"curve_file={curve_file}")
    print(f"shut_in_time={stage.shut_in_time}")
    print(f"shut_in_index={shut_in_index}")
    print(f"volume_column={args.volume_column}")
    print(f"min_rate={args.min_rate}")
    print(f"max_sustained_rate={args.max_sustained_rate}")
    print(f"rate_time_unit={args.rate_time_unit}")
    print(f"rate_positive_elapsed_seconds={rate_positive_seconds}")
    print(f"volume_over_max_sustained_rate_seconds={volume_rate_seconds}")

    if args.g_time_m is not None:
        elapsed_all = elapsed_seconds_after(curve, shut_in_index)
        delta_all = [seconds / volume_rate_seconds for seconds in elapsed_all]
        g_time_all = nolte_g_time(delta_all, args.g_time_m)

        elapsed_preview = elapsed_all[: args.g_time_count]
        delta_preview = delta_all[: args.g_time_count]
        g_time_preview = np.asarray(g_time_all, dtype=float)[: args.g_time_count]

        print("g_time_tp_source=volume_over_max_sustained_rate_seconds")
        print(f"g_time_m={args.g_time_m}")
        print(f"g_time_count_requested={args.g_time_count}")
        print(f"g_time_count_returned={len(elapsed_preview)}")
        print(f"g_time_elapsed_seconds={_format_float_list(elapsed_preview)}")
        print(f"g_time_delta={_format_float_list(delta_preview)}")
        print(f"nolte_g_time={_format_float_list(g_time_preview)}")

        if args.derivative_readiness:
            raw_window = falloff_window_after_shut_in(curve, shut_in_index)
            falloff_window = falloff_window_after_shut_in(
                curve,
                shut_in_index,
                end_elapsed_seconds=args.valid_falloff_end_elapsed,
            )
            readiness_window = apply_elapsed_duplicate_policy(
                falloff_window,
                policy=args.elapsed_duplicate_policy,
            )
            readiness_elapsed = readiness_window["elapsed_seconds"].to_numpy(dtype=float)
            readiness_delta = [seconds / volume_rate_seconds for seconds in readiness_elapsed]
            readiness_g_time = nolte_g_time(readiness_delta, args.g_time_m)

            print(
                "falloff_window_scope="
                + (
                    "manual_valid_end_elapsed"
                    if args.valid_falloff_end_elapsed is not None
                    else "full_post_shut_in"
                )
            )
            print(
                "falloff_window_end_elapsed_seconds="
                + (
                    _format_optional_float(float(args.valid_falloff_end_elapsed))
                    if args.valid_falloff_end_elapsed is not None
                    else "none"
                )
            )
            print(f"falloff_window_raw_rows={len(raw_window)}")
            print(f"falloff_window_rows_after_valid_end={len(falloff_window)}")
            print(f"falloff_window_rows_after_duplicate_policy={len(readiness_window)}")
            print(f"falloff_window_rows_removed_by_valid_end={len(raw_window) - len(falloff_window)}")
            print(
                "falloff_window_rows_removed_by_duplicate_policy="
                f"{len(falloff_window) - len(readiness_window)}"
            )
            if len(readiness_window):
                first_elapsed = float(readiness_window["elapsed_seconds"].iloc[0])
                last_elapsed = float(readiness_window["elapsed_seconds"].iloc[-1])
            else:
                first_elapsed = float("nan")
                last_elapsed = float("nan")
            print(f"falloff_window_first_elapsed_seconds={_format_optional_float(first_elapsed)}")
            print(f"falloff_window_last_elapsed_seconds={_format_optional_float(last_elapsed)}")
            print(f"elapsed_duplicate_policy={args.elapsed_duplicate_policy}")

            readiness_state = _derivative_readiness_state(
                window=readiness_window,
                stage=stage,
                elapsed_all=readiness_elapsed,
                g_time_all=readiness_g_time,
                tp_seconds=volume_rate_seconds,
            )
            derivative_was_computed = False
            if args.pressure_derivative_preview:
                derivative_was_computed = _print_pressure_derivative_preview(
                    readiness_state=readiness_state,
                    count=args.pressure_derivative_count,
                    output_path=args.pressure_derivative_output,
                )
            _print_derivative_readiness(
                readiness_state,
                derivative_was_computed=derivative_was_computed,
            )

    if args.picked_start_time is not None:
        picked_seconds = picked_duration_seconds(curve, args.picked_start_time, stage.shut_in_time)
        print(f"picked_start_time={args.picked_start_time}")
        print(f"picked_duration_seconds={picked_seconds}")

    return 0


def _run_closure_batch(args: argparse.Namespace) -> int:
    result = run_closure_batch(
        stage_params_path=args.stage_params,
        well_root=args.well_root,
        manifest_path=args.manifest,
        observations_path=args.observations,
        volume_column=args.volume_column,
        rate_time_unit=args.rate_time_unit,
        min_rate=args.min_rate,
        g_time_m=args.g_time_m,
        elapsed_duplicate_policy=args.elapsed_duplicate_policy,
        closure_min_elapsed_seconds=args.closure_min_elapsed_seconds,
        pressure_source=args.pressure_source,
        perforation_friction_mpa=args.perforation_friction_mpa,
        wellbore_storage_coeff_m3_per_mpa=args.wellbore_storage_coeff_m3_per_mpa,
        method_preference=args.method_preference,
        stress_shadow_alpha=0.0 if args.no_stress_shadow else args.stress_shadow_alpha,
        flow_allocation=args.flow_allocation,
        flow_allocation_exponent=args.flow_allocation_exponent,
        pkn_C_coupling=args.pkn_C_coupling,
        pkn_H_w_m=args.pkn_Hw_m,
        well=args.well,
    )
    paths = write_closure_batch_outputs(
        result,
        output_path=args.output,
        correlation_output_path=args.correlation_output,
        cluster_output_path=args.cluster_output,
    )
    summary = result["summary"]
    stage_count = result["stage_count"]
    closure_computed = int(summary["closure_was_computed"].sum()) if "closure_was_computed" in summary.columns else 0
    closure_found = 0
    if "selected_closure_status" in summary.columns:
        closure_found = int((summary["selected_closure_status"] == "ok").sum())

    print(f"closure_batch_stage_count={stage_count}")
    print(f"closure_batch_closure_computed_count={closure_computed}")
    print(f"closure_batch_closure_found_count={closure_found}")
    print(f"closure_batch_output_path={paths['output']}")
    if "correlation_output" in paths:
        print(f"closure_batch_correlation_output_path={paths['correlation_output']}")
    if "cluster_output" in paths:
        print(f"closure_batch_cluster_output_path={paths['cluster_output']}")
    if "selected_closure_method" in summary.columns:
        method_counts = summary["selected_closure_method"].value_counts()
        for method, count in method_counts.items():
            print(f"closure_batch_method_{method}_count={count}")
    if "pkn_volume_status" in summary.columns:
        pkn_counts = summary["pkn_volume_status"].value_counts()
        for status, count in pkn_counts.items():
            print(f"closure_batch_pkn_{status}_count={count}")
    print("closure_is_candidate=True")
    print("closure_is_final_interpretation=False")
    return 0


def _run_closure_efficiency_audit(args: argparse.Namespace) -> int:
    summary = pd.read_csv(args.summary)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    audit = build_closure_g_time_efficiency_audit(summary)
    audit_path = output_dir / "closure_g_time_efficiency_audit.csv"
    audit.to_csv(audit_path, index=False)

    tp_multipliers = parse_float_grid(args.tp_multipliers)
    tp_sensitivity = build_tp_sensitivity_efficiency(
        summary,
        tp_multipliers=tp_multipliers,
        g_time_m=args.g_time_m,
    )
    tp_path = output_dir / "tp_sensitivity_efficiency.csv"
    tp_sensitivity.to_csv(tp_path, index=False)

    print(f"closure_efficiency_audit_output_path={audit_path}")
    print(f"closure_efficiency_audit_tp_sensitivity_path={tp_path}")
    for col in [
        "selected_closure_g_time",
        "selected_closure_elapsed_seconds",
        "tp_corrected_seconds",
        "closure_elapsed_over_tp",
        "eta_G",
    ]:
        if col not in audit.columns:
            continue
        values = pd.to_numeric(audit[col], errors="coerce")
        finite = values[np.isfinite(values)]
        if len(finite) == 0:
            print(f"{col}_min=nan")
            print(f"{col}_median=nan")
            print(f"{col}_max=nan")
            continue
        print(f"{col}_min={float(np.nanmin(finite)):.12g}")
        print(f"{col}_median={float(np.nanmedian(finite)):.12g}")
        print(f"{col}_max={float(np.nanmax(finite)):.12g}")
    if "selected_closure_g_time" in audit.columns:
        g_c = pd.to_numeric(audit["selected_closure_g_time"], errors="coerce")
        print(f"count_Gc_lt_0p2={int((g_c < 0.2).sum())}")
        print(f"count_Gc_lt_0p5={int((g_c < 0.5).sum())}")
    if "eta_G" in audit.columns:
        eta = pd.to_numeric(audit["eta_G"], errors="coerce")
        print(f"count_eta_G_lt_0p1={int((eta < 0.1).sum())}")
        print(f"count_eta_G_lt_0p2={int((eta < 0.2).sum())}")
    if "selected_closure_method" in audit.columns:
        for method, count in audit["selected_closure_method"].astype(str).value_counts().items():
            print(f"closure_method_{method}_count={int(count)}")
    print("closure_efficiency_audit_formula_default_changed=False")
    print("closure_efficiency_audit_is_final_physical_conclusion=False")
    return 0


def _run_closure_efficiency_sweep(args: argparse.Namespace) -> int:
    for path in [
        args.output,
        args.correlation_output,
        args.availability_output,
        args.g_time_scale_output,
    ]:
        Path(path).parent.mkdir(parents=True, exist_ok=True)

    result = run_efficiency_prior_closure_sweep(
        stage_params_path=args.stage_params,
        well_root=args.well_root,
        manifest_path=args.manifest,
        observations_path=args.observations,
        efficiency_grid=parse_float_grid(args.efficiency_grid),
        volume_column=args.volume_column,
        rate_time_unit=args.rate_time_unit,
        min_rate=args.min_rate,
        g_time_m=args.g_time_m,
        elapsed_duplicate_policy=args.elapsed_duplicate_policy,
        pressure_source=args.pressure_source,
        stress_shadow_alpha=args.stress_shadow_alpha,
        flow_allocation=args.flow_allocation,
        flow_allocation_exponent=args.flow_allocation_exponent,
        pkn_C_coupling=args.pkn_C_coupling,
        pkn_H_w_m=args.pkn_Hw_m,
        closure_mode=args.closure_mode,
        well=args.well,
    )
    result["stage_table"].to_csv(args.output, index=False)
    result["correlations"].to_csv(args.correlation_output, index=False)
    result["availability"].to_csv(args.availability_output, index=False)
    result["g_time_scale"].to_csv(args.g_time_scale_output, index=False)

    print(f"closure_efficiency_sweep_output_path={args.output}")
    print(f"closure_efficiency_sweep_correlation_output_path={args.correlation_output}")
    print(f"closure_efficiency_sweep_availability_output_path={args.availability_output}")
    print(f"closure_efficiency_sweep_g_time_scale_output_path={args.g_time_scale_output}")
    print(f"closure_efficiency_sweep_stage_rows={len(result['stage_table'])}")
    if not result["availability"].empty:
        for _, row in result["availability"].iterrows():
            print(
                "closure_efficiency_sweep_target="
                f"{row['target_eta']}:ok={int(row['ok_stage_count'])},"
                f"beyond={int(row['beyond_valid_window_count'])},"
                f"missing={int(row['missing_stage_count'])}"
            )
    print("closure_efficiency_sweep_default_closure_pick_changed=False")
    print("closure_efficiency_sweep_formula_default_changed=False")
    print("closure_efficiency_sweep_I_F_changed=False")
    print("closure_efficiency_sweep_H_w_default_changed=False")
    print("closure_efficiency_sweep_is_final_physical_conclusion=False")
    return 0


def _run_closure_tp_reachability_audit(args: argparse.Namespace) -> int:
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    summary = pd.read_csv(args.stage_summary)
    phase5i_stage_table = args.efficiency_prior_stage_table
    if phase5i_stage_table is None:
        default_phase5i = Path("/tmp/gfunction-ref-audit-phase5i/efficiency_prior_stage_table.csv")
        if default_phase5i.exists():
            phase5i_stage_table = default_phase5i
    if (
        phase5i_stage_table is not None
        and Path(phase5i_stage_table).exists()
        and "max_available_Gc" not in summary.columns
    ):
        prior = pd.read_csv(phase5i_stage_table)
        if {"stage", "max_available_Gc"} <= set(prior.columns):
            max_g = (
                prior[["stage", "max_available_Gc"]]
                .dropna(subset=["max_available_Gc"])
                .groupby("stage", as_index=False)["max_available_Gc"]
                .max()
            )
            summary = summary.merge(max_g, on="stage", how="left")
    audit = build_tp_reachability_audit(
        summary,
        efficiency_grid=parse_float_grid(args.efficiency_grid),
        g_time_m=args.g_time_m,
        multiplier_min=args.multiplier_min,
        multiplier_max=args.multiplier_max,
    )
    audit.to_csv(args.output, index=False)

    print(f"closure_tp_reachability_audit_output_path={args.output}")
    print(f"closure_tp_reachability_audit_rows={len(audit)}")
    if not audit.empty:
        for eta, grp in audit.groupby("target_eta", dropna=False):
            status_counts = grp["reachability_status"].astype(str).value_counts()
            class_counts = grp["reachability_class"].astype(str).value_counts()
            status_text = ",".join(f"{k}={int(v)}" for k, v in status_counts.items())
            class_text = ",".join(f"{k}={int(v)}" for k, v in class_counts.items())
            print(f"closure_tp_reachability_target={eta}:status:{status_text}")
            print(f"closure_tp_reachability_target={eta}:class:{class_text}")
    print("closure_tp_reachability_default_tp_changed=False")
    print("closure_tp_reachability_formula_default_changed=False")
    print("closure_tp_reachability_is_final_physical_conclusion=False")
    return 0


def _run_fracture_initiation_audit(args: argparse.Namespace) -> int:
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.summary_output).parent.mkdir(parents=True, exist_ok=True)
    result = build_fracture_initiation_tp_audit(
        stage_params_path=args.stage_params,
        well_root=args.well_root,
        manifest_path=args.manifest,
        tp_reachability_path=args.tp_reachability,
        volume_column=args.volume_column,
        rate_time_unit=args.rate_time_unit,
        min_rate=args.min_rate,
        design_rate=args.design_rate,
        rate_step_fraction=args.rate_step_fraction,
        pressure_source=args.pressure_source,
        stable_pressure_window_points=args.stable_pressure_window_points,
        stable_pressure_slope_threshold=args.stable_pressure_slope_threshold,
        well=args.well,
    )
    result["audit"].to_csv(args.output, index=False)
    result["summary"].to_csv(args.summary_output, index=False)

    print(f"fracture_initiation_audit_output_path={args.output}")
    print(f"fracture_initiation_audit_summary_output_path={args.summary_output}")
    print(f"fracture_initiation_audit_rows={len(result['audit'])}")
    if "recommended_tp_review_priority" in result["audit"].columns:
        for priority, count in result["audit"]["recommended_tp_review_priority"].astype(str).value_counts().items():
            print(f"fracture_initiation_audit_priority_{priority}_count={int(count)}")
    print("fracture_initiation_audit_default_tp_changed=False")
    print("fracture_initiation_audit_formula_default_changed=False")
    print("fracture_initiation_audit_is_final_physical_conclusion=False")
    return 0


def _run_pkn_grid_search(args: argparse.Namespace) -> int:
    grid_kwargs = {
        "closure_min_elapsed_seconds": parse_float_grid(args.closure_min_elapsed_grid),
        "pkn_C_coupling": parse_choice_grid(args.pkn_C_coupling_grid, ALLOWED_COUPLING),
        "flow_allocation": parse_choice_grid(args.flow_allocation_grid, ALLOWED_FLOW_ALLOCATION),
        "flow_allocation_exponent": parse_float_grid(args.flow_allocation_exponent_grid),
        "stress_shadow_alpha": parse_float_grid(args.stress_shadow_alpha_grid),
        "pkn_H_w_m": parse_float_grid(args.pkn_H_w_grid),
        "fleak": parse_float_grid(args.fleak_grid),
        "C_multiplier": parse_float_grid(args.C_multiplier_grid),
        "effective_volume_factor": parse_float_grid(args.effective_volume_factor_grid),
        "wellbore_storage_coeff_m3_per_mpa": parse_float_grid(args.wellbore_storage_coeff_grid),
        "perf_friction_mode": parse_choice_grid(args.perforation_friction_mode_grid, ALLOWED_PERF_MODES),
        "perf_friction_constant_mpa": parse_float_grid(args.perforation_friction_mpa_grid),
        "perforation_diameter_mm": parse_float_grid(args.perforation_diameter_mm_grid),
        "perforations_per_cluster": parse_int_grid(args.perforations_per_cluster_grid),
        "perforation_Cd": parse_float_grid(args.perforation_Cd_grid),
        "fluid_density_kg_m3": parse_float_grid(args.fluid_density_kg_m3_grid),
        "stable_min_r2": parse_float_grid(args.stable_min_r2_grid),
        "stable_min_points": parse_int_grid(args.stable_min_points_grid),
        "stable_window_mode": parse_choice_grid(args.stable_window_mode_grid, ALLOWED_WINDOW_MODES),
        "tp_multiplier": parse_float_grid(args.tp_multiplier_grid),
    }
    criteria = PhysicalPlausibilityCriteria(
        min_n=args.plausibility_min_n,
        max_placeholder_count=args.plausibility_max_placeholder,
        min_median_efficiency=args.plausibility_min_eff,
        max_median_efficiency=args.plausibility_max_eff,
        max_efficiency_below_5pct_count=args.plausibility_max_below_5pct,
        min_pkn_ok_count=args.plausibility_min_pkn_ok,
        min_median_stable_r2=args.plausibility_min_r2,
        min_C_multiplier=args.plausibility_min_C_mult,
        max_C_multiplier=args.plausibility_max_C_mult,
    )
    config = GridSearchConfig(
        stage_params_path=args.stage_params,
        well_root=args.well_root,
        manifest_path=args.manifest,
        observations_path=args.observations,
        output_dir=args.output_dir,
        volume_column=args.volume_column,
        rate_time_unit=args.rate_time_unit,
        min_rate=args.min_rate,
        g_time_m=args.g_time_m,
        pressure_source=args.pressure_source,
        method_preference=args.method_preference,
        elapsed_duplicate_policy=args.elapsed_duplicate_policy,
        well=args.well,
    )

    def _progress(i: int, total: int, _row: dict) -> None:
        if i == 1 or i % 50 == 0 or i == total:
            print(f"pkn_grid_search_progress={i}/{total}")

    result = run_grid_search(
        config=config,
        grid_kwargs=grid_kwargs,
        max_cases=args.max_cases,
        criteria=criteria,
        workers=args.workers,
        parallel_backend=args.parallel_backend,
        progress_callback=_progress,
    )
    paths = result["output_paths"]
    print(f"pkn_grid_search_total_cases={result['total_cases']}")
    print(f"pkn_grid_search_cases_run={result['cases_run']}")
    print(f"pkn_grid_search_cases_ok={result['cases_ok']}")
    print(f"pkn_grid_search_cases_failed={result['cases_failed']}")
    for key, path in paths.items():
        print(f"pkn_grid_search_{key}_path={path}")
    print("pkn_grid_search_is_candidate=True")
    print("pkn_grid_search_is_final_interpretation=False")
    print("pkn_grid_search_I_F_changed=False")
    print("pkn_grid_search_H_w_default_m=50")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "version":
        print(__version__)
        return 0
    if args.command == "window-audit":
        try:
            return _run_window_audit(args)
        except ValueError as exc:
            parser.error(str(exc))
    if args.command == "derivative-batch":
        try:
            return _run_derivative_batch(args)
        except ValueError as exc:
            parser.error(str(exc))
    if args.command == "derivative-review":
        try:
            return _run_derivative_review(args)
        except ValueError as exc:
            parser.error(str(exc))
    if args.command == "derivative-context":
        try:
            return _run_derivative_context(args)
        except ValueError as exc:
            parser.error(str(exc))
    if args.command == "closure-batch":
        try:
            return _run_closure_batch(args)
        except ValueError as exc:
            parser.error(str(exc))
    if args.command == "closure-efficiency-audit":
        try:
            return _run_closure_efficiency_audit(args)
        except ValueError as exc:
            parser.error(str(exc))
    if args.command == "closure-efficiency-sweep":
        try:
            return _run_closure_efficiency_sweep(args)
        except ValueError as exc:
            parser.error(str(exc))
    if args.command == "closure-tp-reachability-audit":
        try:
            return _run_closure_tp_reachability_audit(args)
        except ValueError as exc:
            parser.error(str(exc))
    if args.command == "fracture-initiation-audit":
        try:
            return _run_fracture_initiation_audit(args)
        except ValueError as exc:
            parser.error(str(exc))
    if args.command == "pkn-grid-search":
        try:
            return _run_pkn_grid_search(args)
        except ValueError as exc:
            parser.error(str(exc))

    parser.print_help()
    return 0
