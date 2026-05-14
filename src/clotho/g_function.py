"""Nolte G-function 的教学版时间公式。

这个文件只做一件事：

把停泵后的无量纲时间 Δ 转换为 Nolte G-time。

这里不处理压力，也不做闭合压力识别。

先把变量说清楚：

- elapsed time：停泵后的时间，单位通常是秒；
- tp：选定的泵注时间尺度，单位也通常是秒；
- Δ = elapsed time / tp，所以 Δ 没有单位；
- g(Δ, m)：Nolte G-function 的中间时间函数；
- G(Δ, m)：归一化后的 G-time。

本文件故意不实现：

- dP/dG 压力导数；
- G dP/dG；
- closure diagnostics 闭合诊断；
- Carter leakoff；
- PKN；
- 裂缝长度或体积反演。

原因：导数和闭合诊断会受到压力噪声、平滑方法和采样方式影响，
比纯时间公式更容易出错，后续需要单独审计。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from numpy.typing import ArrayLike

_TINY_NEGATIVE_DELTA = 1e-12


def _validate_m(m: float) -> float:
    """检查 m 的取值。

    这里先采用最保守的教学范围：0 < m <= 1。

    旧参考库只检查 m > 0，但它的解析分支主要对应 m=1/2 和 m=1。
    在论文解释清楚 m 的物理含义之前，先不允许 m > 1。
    """
    value = float(m)
    if not math.isfinite(value) or value <= 0.0 or value > 1.0:
        raise ValueError(f"m 必须满足 0 < m <= 1，当前 m={m!r}")
    return value


def _validate_delta(delta: ArrayLike) -> tuple[np.ndarray, bool]:
    """把 Δ 转成 NumPy 数组，并拒绝真实负值。

    Δ = 停泵后时间 / 泵注时间，所以正常情况下不应该是负数。

    为了避免浮点误差造成误报，像 -1e-13 这种极小负数会被当成 0。
    但 -0.1、-1 这类真实负值必须报错，不能像旧库那样静默夹到 0。
    """
    raw = np.asarray(delta, dtype=float)
    scalar_input = raw.ndim == 0

    if not np.all(np.isfinite(raw)):
        raise ValueError("delta 必须是有限数字")

    if np.any(raw < -_TINY_NEGATIVE_DELTA):
        raise ValueError("delta 不能为负数；Δ = elapsed_time / tp 应该 >= 0")

    return np.maximum(raw, 0.0), scalar_input


def _return_like_input(values: Any, *, scalar_input: bool) -> float | np.ndarray:
    """如果输入是单个数，就返回 float；如果输入是数组，就返回数组。"""
    array = np.asarray(values, dtype=float)
    if scalar_input:
        return float(array)
    return array


def _g_m_equals_1(delta: np.ndarray) -> np.ndarray:
    """m=1 时的解析公式。"""
    return 4.0 / 3.0 * ((1.0 + delta) ** 1.5 - delta**1.5 - 1.0)


def _g_m_equals_half(delta: np.ndarray) -> np.ndarray:
    """m=1/2 时的解析公式。"""
    return (
        (1.0 + delta) * np.arcsin((1.0 + delta) ** (-0.5))
        + np.sqrt(delta)
        - math.pi / 2.0
    )


def _g_by_quadrature(delta: np.ndarray, m: float, *, quad_pts: int) -> np.ndarray:
    """一般 m 用数值积分计算 g(Δ,m)。

    数学形式是：

        g(Δ,m) = ∫ 2 [sqrt(1+Δ-ξ^(1/m)) - sqrt(1-ξ^(1/m))] dξ

    积分范围是 ξ 从 0 到 1。

    为了让端点附近更平稳，这里用一个简单变量替换：

        ξ = 1 - (1-s)^2

    然后对 s 从 0 到 1 做梯形积分。
    """
    points = int(quad_pts)
    if points < 3:
        raise ValueError("quad_pts 至少为 3")

    s = np.linspace(0.0, 1.0, points)
    xi = 1.0 - (1.0 - s) ** 2
    jacobian = 2.0 * (1.0 - s)

    base = xi ** (1.0 / m)

    # delta[..., None] 可以让一维、二维甚至单个数都和积分网格自动广播。
    first = np.sqrt(np.maximum(1.0 + delta[..., None] - base, 0.0))
    second = np.sqrt(np.maximum(1.0 - base, 0.0))

    integrand = 2.0 * (first - second) * jacobian
    return np.trapezoid(integrand, s, axis=-1)


def g_function_time(delta: ArrayLike, m: float, *, quad_pts: int = 257) -> float | np.ndarray:
    """计算 Nolte G-function 的中间函数 g(Δ,m)。

    参数
    ----
    delta:
        无量纲时间 Δ。它等于“停泵后时间 / 泵注时间”。
    m:
        Nolte G-function 里的指数参数。当前教学版要求 0 < m <= 1。
    quad_pts:
        一般 m 数值积分时使用的网格点数。默认 257，和参考库保持一致。

    返回
    ----
    float 或 np.ndarray:
        如果输入 delta 是单个数，返回 float；如果输入是数组，返回数组。
    """
    delta_array, scalar_input = _validate_delta(delta)
    m_value = _validate_m(m)

    if math.isclose(m_value, 1.0, rel_tol=0.0, abs_tol=1e-12):
        result = _g_m_equals_1(delta_array)
    elif math.isclose(m_value, 0.5, rel_tol=0.0, abs_tol=1e-12):
        result = _g_m_equals_half(delta_array)
    else:
        result = _g_by_quadrature(delta_array, m_value, quad_pts=quad_pts)

    return _return_like_input(result, scalar_input=scalar_input)


def nolte_g_time(
    delta: ArrayLike,
    m: float,
    *,
    delta0: float = 0.0,
    quad_pts: int = 257,
) -> float | np.ndarray:
    """计算归一化后的 Nolte G-time。

    公式是：

        G(Δ,m;Δ0) = 4/π * [g(Δ,m) - g(Δ0,m)]

    delta0 的作用只是把某个 Δ0 位置平移成 G=0。
    常用情况下 delta0=0。
    """
    delta0_array, _ = _validate_delta(delta0)
    if delta0_array.ndim != 0:
        raise ValueError("delta0 必须是单个数字")

    g_delta = g_function_time(delta, m, quad_pts=quad_pts)
    g_delta0 = g_function_time(float(delta0_array), m, quad_pts=quad_pts)
    result = 4.0 / math.pi * (np.asarray(g_delta) - float(g_delta0))

    return _return_like_input(result, scalar_input=np.asarray(delta).ndim == 0)


__all__ = ["g_function_time", "nolte_g_time"]
