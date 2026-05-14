from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from clotho import __version__
from clotho.g_function import nolte_g_time
from clotho.stage_data import (
    StageInfo,
    add_estimated_bottomhole_pressure,
    elapsed_seconds_after,
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


def _print_derivative_readiness(
    *,
    curve,
    stage: StageInfo,
    shut_in_index: int,
    elapsed_all,
    g_time_all,
) -> None:
    """输出未来 dP/dG 的最基本数据前置条件；这里不计算导数。"""
    elapsed_summary = _sequence_step_summary(elapsed_all)
    g_time_summary = _sequence_step_summary(g_time_all)

    whp_post = curve["wellhead_pressure_mpa"].iloc[shut_in_index:].to_numpy(dtype=float)
    pressure_column = "wellhead_pressure_mpa"
    estimated_available = stage.liquid_column_pressure_mpa is not None
    pressure_post = whp_post

    if estimated_available:
        estimated_curve = add_estimated_bottomhole_pressure(curve, stage)
        pressure_column = "estimated_bottomhole_pressure_mpa"
        pressure_post = estimated_curve[pressure_column].iloc[shut_in_index:].to_numpy(dtype=float)

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

    print("derivative_readiness_tp_source=volume_over_max_sustained_rate_seconds")
    print(f"derivative_readiness_pressure_column={pressure_column}")
    print(f"derivative_readiness_post_shut_in_rows={len(g_time_array)}")
    print(f"derivative_readiness_elapsed_duplicate_step_count={elapsed_summary['duplicate_step_count']}")
    print(f"derivative_readiness_elapsed_backward_step_count={elapsed_summary['backward_step_count']}")
    print(f"derivative_readiness_elapsed_strictly_increasing={_bool_text(bool(elapsed_summary['strictly_increasing']))}")
    print(f"derivative_readiness_elapsed_nondecreasing={_bool_text(bool(elapsed_summary['nondecreasing']))}")
    print(f"derivative_readiness_g_time_duplicate_step_count={g_time_summary['duplicate_step_count']}")
    print(f"derivative_readiness_g_time_backward_step_count={g_time_summary['backward_step_count']}")
    print(f"derivative_readiness_g_time_strictly_increasing={_bool_text(bool(g_time_summary['strictly_increasing']))}")
    print(f"derivative_readiness_g_time_nondecreasing={_bool_text(bool(g_time_summary['nondecreasing']))}")
    _print_pressure_summary("derivative_readiness_wellhead_pressure", whp_summary)
    print(f"derivative_readiness_estimated_bottomhole_pressure_available={_bool_text(estimated_available)}")
    _print_pressure_summary("derivative_readiness_estimated_bottomhole_pressure", pressure_summary)
    print(f"derivative_readiness_ready={_bool_text(not blockers)}")
    print(f"derivative_readiness_blockers={_format_blockers(blockers)}")
    print("derivative_was_computed=False")
    print("closure_was_computed=False")


# 输入：window-audit 命令参数。输出：退出码；只做窗口审计和可选 G-time/导数前置条件预览，不做导数、闭合或反演。
def _run_window_audit(args: argparse.Namespace) -> int:
    if args.g_time_m is not None and args.g_time_count <= 0:
        raise ValueError("g_time_count 必须大于 0")
    if args.derivative_readiness and args.g_time_m is None:
        raise ValueError("--derivative-readiness 需要同时传入 --g-time-m")

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
            _print_derivative_readiness(
                curve=curve,
                stage=stage,
                shut_in_index=shut_in_index,
                elapsed_all=elapsed_all,
                g_time_all=g_time_all,
            )

    if args.picked_start_time is not None:
        picked_seconds = picked_duration_seconds(curve, args.picked_start_time, stage.shut_in_time)
        print(f"picked_start_time={args.picked_start_time}")
        print(f"picked_duration_seconds={picked_seconds}")

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

    parser.print_help()
    return 0
