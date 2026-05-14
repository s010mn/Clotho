"""压裂段参数表和停泵压力曲线的读取工具。

这个文件现在只处理两类表：

1. `stage_params.csv`：每一行是一段压裂段的基本参数，例如段号、停泵时间、
   `sigma_min`、`add_pressure`、微地震缝长等。
2. `stage_data/stage_XX.csv`：一段的施工曲线，例如时间、井口压力、排量、累计液量。

这个文件暂时不做 G-function、Carter 滤失、PKN 裂缝体积、闭合诊断、应力阴影、
裂缝反演、相关性分析，也不导出 Excel 或图片。这样做是为了先把“读了什么数据”
讲清楚，再讨论“怎么算”。

特别注意：`add_pressure` 是原始表中的旧字段名。根据人类说明，它表示液柱压力：
近似井底压力 = 井口压力 + 液柱压力。

因此代码中把它命名为 `liquid_column_pressure_mpa`。如果需要得到近似井底压力，
应显式调用 `add_estimated_bottomhole_pressure()`，得到
`estimated_bottomhole_pressure_mpa`。

这个值不是井下压力计实测 BHP，而是基于井口压力和液柱压力的估算值。

同样，`sigma_min` 这里只叫 `minimum_stress_prior_mpa`（最小应力先验值）。它是外部给定
或人工解释得到的先验信息，不是本文件从停泵曲线里自动识别出来的闭合压力。

本文件还提供教学版泵注时间 tp/window policy：只比较不同时间尺度的定义，
不判断哪一种一定正确，也不计算 G-function。
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
    liquid_column_pressure_mpa: float | None
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
    "liquid_column_pressure_mpa": [
        "add_pressure",
        "pressure_shift_mpa",
        "liquid_column_pressure_mpa",
        "hydrostatic_pressure_mpa",
    ],
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
                liquid_column_pressure_mpa=_optional_float(raw, "liquid_column_pressure_mpa"),
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


# 输入：井口压力曲线和段参数。输出：增加 estimated_bottomhole_pressure_mpa 的新表。
def add_estimated_bottomhole_pressure(curve: pd.DataFrame, stage: StageInfo) -> pd.DataFrame:
    """在曲线表中增加“近似井底压力”。

    近似井底压力 = 井口压力 + 液柱压力。

    注意：
    - 这里的液柱压力来自 stage_params.csv 里的 add_pressure；
    - 这不是井下压力计实测值；
    - 所以列名必须带 estimated，提醒读者这是估算值。
    """
    if stage.liquid_column_pressure_mpa is None:
        raise ValueError("缺少液柱压力 liquid_column_pressure_mpa，不能估算井底压力")

    result = curve.copy()
    result["estimated_bottomhole_pressure_mpa"] = (
        result["wellhead_pressure_mpa"] + stage.liquid_column_pressure_mpa
    )
    return result


# 输入：规范曲线表和任意时间字符串。输出：这个时间所在的唯一行号。
def find_time_index(curve: pd.DataFrame, time_text: str) -> int:
    """按原始时间字符串精确找行号。

    这个函数不猜测、不模糊匹配。找不到或找到多行都报错，避免停泵点选错。
    """
    matches = np.flatnonzero(curve["time_text"].astype(str).to_numpy() == str(time_text))
    if len(matches) == 0:
        raise ValueError(f"找不到时间 {time_text!r} 对应的行")
    if len(matches) > 1:
        raise ValueError(f"时间 {time_text!r} 对应多行，无法判断唯一行号")
    return int(matches[0])


# 输入：规范曲线表和停泵时刻字符串。输出：停泵时刻所在的唯一行号。
def find_shut_in_index(curve: pd.DataFrame, shut_in_time: str) -> int:
    return find_time_index(curve, shut_in_time)


# 输入：人工选定的开始和结束时间。输出：两个时间点之间的真实秒数。
def picked_duration_seconds(curve: pd.DataFrame, start_time: str, end_time: str) -> float:
    """人工选点法：把人工选定的时间段换算成秒。

    这个函数适合已经知道“裂缝开始打开的时间”和“停泵时间”的情况。
    它不自动判断裂缝什么时候打开，只负责把人工选定的时间段换算成秒。
    """
    start_index = find_time_index(curve, start_time)
    end_index = find_time_index(curve, end_time)
    if end_index < start_index:
        raise ValueError("end_time 不能早于 start_time")

    seconds = _continuous_seconds(curve)
    return float(seconds[end_index] - seconds[start_index])


# 输入：规范曲线表和停泵行号。输出：停泵前 rate 大于阈值的累计真实秒数。
def rate_positive_duration_seconds(
    curve: pd.DataFrame,
    shut_in_index: int,
    *,
    min_rate: float = 0.0,
) -> float:
    """rate > min_rate 累计法。

    这是一个简单对照策略：停泵前，如果某一行的排量大于阈值，就把这一行到下一行
    的真实时间间隔算入泵注时间。它简单，但不一定就是 G-function 推荐的 tp，
    因为它容易受预注入、阶梯降排量、排量噪声、时间同步误差影响。
    """
    _validate_row_index(curve, shut_in_index, "shut_in_index")
    if not np.isfinite(float(min_rate)):
        raise ValueError(f"min_rate 必须是有限数字，当前为 {min_rate!r}")

    seconds = _continuous_seconds(curve)
    rates = curve["rate"].to_numpy(dtype=float)
    duration = 0.0
    for index in range(shut_in_index):
        if rates[index] > min_rate:
            duration += float(seconds[index + 1] - seconds[index])
    return float(duration)


# 输入：停泵行、人工给定最大稳定排量和排量时间单位。输出：体积/排量法得到的秒数。
def volume_over_max_rate_duration_seconds(
    curve: pd.DataFrame,
    shut_in_index: int,
    *,
    max_sustained_rate: float,
    rate_time_unit: str,
    initial_stage_volume: float = 0.0,
) -> float:
    """体积 / 最大稳定排量法。

    对应 DFIT/G-function 实用解释资料里的建议：tp 不一定取字面泵注时长，
    也可以取“总注入量 / 最大稳定排量”。

    注意：最大稳定排量必须由调用者显式传入。本函数不从曲线里盲选最大值，
    因为单个峰值可能只是噪声或短暂瞬时排量，不一定代表稳定排量。
    """
    _validate_row_index(curve, shut_in_index, "shut_in_index")
    max_rate = float(max_sustained_rate)
    if not np.isfinite(max_rate) or max_rate <= 0.0:
        raise ValueError("max_sustained_rate 必须大于 0")

    initial_volume = float(initial_stage_volume)
    if not np.isfinite(initial_volume):
        raise ValueError("initial_stage_volume 必须是有限数字")

    stage_volume = float(curve["stage_volume"].iloc[shut_in_index])
    if not np.isfinite(stage_volume):
        raise ValueError("停泵行 stage_volume 不是有限数字")

    injected_volume = stage_volume - initial_volume
    if injected_volume < 0.0:
        raise ValueError("注入体积不能小于 0，请检查 initial_stage_volume")

    seconds_per_rate_unit = _seconds_per_rate_unit(rate_time_unit)
    return float(injected_volume / max_rate * seconds_per_rate_unit)


# 输入：曲线、停泵行和体积/排量法参数。输出：两个教学策略的 tp 对比。
def compare_injection_duration_policies(
    curve: pd.DataFrame,
    shut_in_index: int,
    *,
    max_sustained_rate: float,
    rate_time_unit: str,
    initial_stage_volume: float = 0.0,
    min_rate: float = 0.0,
) -> dict[str, float]:
    """对比两个不需要人工起点的 tp 策略。

    `human_picked` 需要 start_time 和 end_time，参数不同，所以用
    `picked_duration_seconds()` 单独计算。
    """
    return {
        InjectionWindowPolicy.RATE_POSITIVE_ELAPSED.value: rate_positive_duration_seconds(
            curve,
            shut_in_index,
            min_rate=min_rate,
        ),
        InjectionWindowPolicy.VOLUME_OVER_MAX_SUSTAINED_RATE.value: volume_over_max_rate_duration_seconds(
            curve,
            shut_in_index,
            max_sustained_rate=max_sustained_rate,
            rate_time_unit=rate_time_unit,
            initial_stage_volume=initial_stage_volume,
        ),
    }


# 输入：规范曲线表和停泵行号。输出：停泵后每一行距离停泵点的真实秒数。
def elapsed_seconds_after(curve: pd.DataFrame, shut_in_index: int) -> tuple[float, ...]:
    _validate_row_index(curve, shut_in_index, "shut_in_index")
    seconds = _continuous_seconds(curve)
    elapsed = seconds[shut_in_index:] - seconds[shut_in_index]
    return tuple(float(value) for value in elapsed)


# 输入：规范曲线表。输出：连续秒数；跨午夜时后一天自动加 86400 秒。
def _continuous_seconds(curve: pd.DataFrame) -> np.ndarray:
    seconds = curve["seconds_of_day"].to_numpy(dtype=float)
    if np.isnan(seconds).any():
        raise ValueError("seconds_of_day 含有 NaN，请先检查 time_text 是否都是 HH:MM:SS")
    if len(seconds) == 0:
        return seconds

    continuous = seconds.copy()
    day_offset = 0.0
    for index in range(1, len(seconds)):
        if seconds[index] < seconds[index - 1]:
            day_offset += 24 * 60 * 60
        continuous[index] = seconds[index] + day_offset
    return continuous


# 输入：曲线表、行号和名字。输出：无；行号无效时直接报错。
def _validate_row_index(curve: pd.DataFrame, index: int, name: str) -> None:
    if not 0 <= index < len(curve):
        raise ValueError(f"{name} 超出范围: {index}")


# 输入：排量时间单位。输出：这个单位对应多少秒。
def _seconds_per_rate_unit(rate_time_unit: str) -> float:
    unit = str(rate_time_unit).strip().lower()
    if unit in {"second", "s"}:
        return 1.0
    if unit in {"minute", "min"}:
        return 60.0
    if unit in {"hour", "h"}:
        return 3600.0
    raise ValueError(f"不认识的 rate_time_unit: {rate_time_unit!r}")


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
