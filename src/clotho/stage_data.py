"""压裂段参数表和停泵压力曲线的读取工具。

这个文件现在只处理两类表：

1. `stage_params.csv`：每一行是一段压裂段的基本参数，例如段号、停泵时间、
   `sigma_min`、`add_pressure`、微地震缝长等。
2. `stage_data/stage_XX.csv`：一段的施工曲线，例如时间、井口压力、排量、累计液量。

这个文件暂时不做 G-function、Carter 滤失、PKN 裂缝体积、闭合诊断、应力阴影、
裂缝反演、相关性分析，也不导出 Excel 或图片。这样做是为了先把“读了什么数据”
讲清楚，再讨论“怎么算”。

特别注意：`add_pressure` 这里只叫 `pressure_shift_mpa`（压力平移量），不能直接叫
BHP 或井底压力。因为真正的井底压力换算需要井深、液柱密度、摩阻等信息；简单地把
井口压力加一个常数，只能说是“经过平移的压力”，不能说已经严格变成井底压力。

同样，`sigma_min` 这里只叫 `minimum_stress_prior_mpa`（最小应力先验值）。它是外部给定
或人工解释得到的先验信息，不是本文件从停泵曲线里自动识别出来的闭合压力。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


class InjectionWindowPolicy(str, Enum):
    """泵注时间 tp 的候选定义；这里只列选项，暂时不计算 tp。"""

    RATE_POSITIVE_ELAPSED = "rate_positive_elapsed"
    VOLUME_OVER_MAX_SUSTAINED_RATE = "volume_over_max_sustained_rate"
    HUMAN_PICKED = "human_picked"


@dataclass(frozen=True)
class StageInfo:
    """一段压裂段的基本信息；字段名尽量写清楚单位和物理含义。"""

    well: str
    stage: int
    data_file: str
    shut_in_time: str
    num_clusters: int | None
    cluster_spacing_m: float | None
    fracture_half_height_m: float | None
    youngs_modulus_gpa: float | None
    poissons_ratio: float | None
    minimum_stress_prior_mpa: float | None
    pressure_shift_mpa: float | None
    microseismic_length_m: float | None
    microseismic_height_m: float | None
    electromagnetic_length_m: float | None
    raw: dict[str, str]


_STAGE_PARAM_ALIASES = {
    "well": ["well", "井名"],
    "stage": ["stage", "段号"],
    "data_file": ["file", "data_file", "stage_file"],
    "shut_in_time": ["shut_in", "shut_in_time", "停泵时间"],
    "num_clusters": ["n", "num_clusters"],
    "cluster_spacing_m": ["spacing", "cluster_spacing_m"],
    "fracture_half_height_m": ["hw", "half_height_m", "fracture_half_height_m"],
    "youngs_modulus_gpa": ["e_gpa", "youngs_modulus_gpa"],
    "poissons_ratio": ["nu", "poissons_ratio"],
    "minimum_stress_prior_mpa": ["sigma_min", "minimum_stress_prior_mpa"],
    "pressure_shift_mpa": ["add_pressure", "pressure_shift_mpa"],
    "microseismic_length_m": ["微地震缝长", "microseismic_length_m"],
    "microseismic_height_m": ["微地震缝高", "microseismic_height_m"],
    "electromagnetic_length_m": ["广域电磁缝长", "electromagnetic_length_m", "em_length_m"],
}

_STAGE_CURVE_ALIASES = {
    "time_text": ["time", "time_text", "时间"],
    "wellhead_pressure_mpa": ["wellhead_pressure", "wellhead_pressure_mpa", "井口压力"],
    "rate": ["rate", "排量"],
    "stage_volume": ["stage_volume", "段液量"],
    "total_volume": ["total_volume", "总液量"],
}


# 输入：stage_params.csv 路径。输出：每个压裂段一个 StageInfo。
def read_stage_params(path: str | Path) -> list[StageInfo]:
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    infos: list[StageInfo] = []

    for _, row in df.iterrows():
        raw = {str(key): str(value) for key, value in row.items()}
        infos.append(
            StageInfo(
                well=_required_text(raw, "well"),
                stage=_required_int(raw, "stage"),
                data_file=_required_text(raw, "data_file"),
                shut_in_time=_required_text(raw, "shut_in_time"),
                num_clusters=_optional_int(raw, "num_clusters"),
                cluster_spacing_m=_optional_float(raw, "cluster_spacing_m"),
                fracture_half_height_m=_optional_float(raw, "fracture_half_height_m"),
                youngs_modulus_gpa=_optional_float(raw, "youngs_modulus_gpa"),
                poissons_ratio=_optional_float(raw, "poissons_ratio"),
                minimum_stress_prior_mpa=_optional_float(raw, "minimum_stress_prior_mpa"),
                pressure_shift_mpa=_optional_float(raw, "pressure_shift_mpa"),
                microseismic_length_m=_optional_float(raw, "microseismic_length_m"),
                microseismic_height_m=_optional_float(raw, "microseismic_height_m"),
                electromagnetic_length_m=_optional_float(raw, "electromagnetic_length_m"),
                raw=raw,
            )
        )

    return infos


# 输入：单段施工曲线 CSV 路径。输出：列名统一后的 pandas DataFrame。
def read_stage_curve(path: str | Path) -> pd.DataFrame:
    raw = pd.read_csv(path, dtype=str, keep_default_na=False)
    curve = pd.DataFrame()

    curve["time_text"] = _column(raw, "time_text")
    curve["seconds_of_day"] = _seconds_of_day(curve["time_text"])
    for name in ["wellhead_pressure_mpa", "rate", "stage_volume", "total_volume"]:
        curve[name] = _numeric_column(raw, name)

    return curve


# 输入：规范曲线表和停泵时刻字符串。输出：停泵时刻所在的唯一行号。
def find_shut_in_index(curve: pd.DataFrame, shut_in_time: str) -> int:
    matches = np.flatnonzero(curve["time_text"].astype(str).to_numpy() == str(shut_in_time))
    if len(matches) == 0:
        raise ValueError(f"找不到停泵时间 {shut_in_time!r} 对应的行")
    if len(matches) > 1:
        raise ValueError(f"停泵时间 {shut_in_time!r} 对应多行，无法判断唯一停泵点")
    return int(matches[0])


# 输入：规范曲线表和停泵行号。输出：停泵后每一行距离停泵点的真实秒数。
def elapsed_seconds_after(curve: pd.DataFrame, shut_in_index: int) -> tuple[float, ...]:
    seconds = curve["seconds_of_day"].to_numpy(dtype=float)
    if np.isnan(seconds).any():
        raise ValueError("seconds_of_day 含有 NaN，请先检查 time_text 是否都是 HH:MM:SS")
    if not 0 <= shut_in_index < len(seconds):
        raise ValueError(f"shut_in_index 超出范围: {shut_in_index}")

    after = seconds[shut_in_index:].copy()
    for index in range(1, len(after)):
        if after[index] < after[index - 1]:
            after[index:] += 24 * 60 * 60

    elapsed = after - after[0]
    return tuple(float(value) for value in elapsed)


# 输入：原始 DataFrame 和规范字段名。输出：对应原始列；找不到就报错。
def _column(df: pd.DataFrame, name: str) -> pd.Series:
    for alias in _STAGE_CURVE_ALIASES[name]:
        if alias in df.columns:
            return df[alias]
    raise ValueError(f"缺少必要列 {name!r}，可接受列名: {_STAGE_CURVE_ALIASES[name]}")


# 输入：原始 DataFrame 和规范字段名。输出：数字列；非空坏数据会报错。
def _numeric_column(raw: pd.DataFrame, name: str) -> pd.Series:
    text = _column(raw, name)
    values = pd.to_numeric(text, errors="coerce")
    bad = values.isna() & text.astype(str).str.strip().ne("")
    if bad.any():
        examples = text[bad].head(3).tolist()
        raise ValueError(f"字段 {name!r} 含有不能转成数字的值，例如: {examples}")
    return values


# 输入：HH:MM:SS 字符串序列。输出：一天内秒数；解析失败为 NaN。
def _seconds_of_day(time_text: pd.Series) -> pd.Series:
    delta = pd.to_timedelta(time_text, errors="coerce")
    return delta.dt.total_seconds()


# 输入：一行原始字段和规范字段名。输出：必填字符串。
def _required_text(raw: dict[str, str], name: str) -> str:
    value = _lookup(raw, name)
    if value is None or str(value).strip() == "":
        raise ValueError(f"缺少必要文本字段: {name}")
    return str(value).strip()


# 输入：一行原始字段和规范字段名。输出：必填整数。
def _required_int(raw: dict[str, str], name: str) -> int:
    value = _lookup(raw, name)
    if value is None or str(value).strip() == "":
        raise ValueError(f"缺少必要整数字段: {name}")
    return int(value)


# 输入：一行原始字段和规范字段名。输出：可空整数。
def _optional_int(raw: dict[str, str], name: str) -> int | None:
    value = _lookup(raw, name)
    return None if value is None or str(value).strip() == "" else int(value)


# 输入：一行原始字段和规范字段名。输出：可空浮点数。
def _optional_float(raw: dict[str, str], name: str) -> float | None:
    value = _lookup(raw, name)
    return None if value is None or str(value).strip() == "" else float(value)


# 输入：一行原始字段和规范字段名。输出：按 alias 找到的原始值。
def _lookup(raw: dict[str, str], name: str) -> Any:
    for alias in _STAGE_PARAM_ALIASES[name]:
        if alias in raw:
            return raw[alias]
    return None
