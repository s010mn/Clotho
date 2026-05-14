from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from clotho import __version__
from clotho.stage_data import (
    StageInfo,
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

    return parser


# 输入：stage_params 读取结果、段号和可选井名。输出：唯一匹配的压裂段。
def _find_stage(stages: list[StageInfo], *, stage_number: int, well: str | None) -> StageInfo:
    matches = [stage for stage in stages if stage.stage == stage_number and (well is None or stage.well == well)]
    if not matches:
        raise ValueError(f"找不到 stage={stage_number} 的记录")
    if len(matches) > 1:
        raise ValueError(f"stage={stage_number} 匹配多行，请用 --well 指定井名")
    return matches[0]


# 输入：window-audit 命令参数。输出：退出码；只做窗口审计，不做 G-function。
def _run_window_audit(args: argparse.Namespace) -> int:
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
