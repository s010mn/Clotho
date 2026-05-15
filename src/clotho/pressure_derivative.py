"""压力对 G-time 的最小数值导数工具。

本文件只做一件事：在输入已经通过数据质量检查时，计算压力对 G-time 的数值导数。

它不做：
- pressure smoothing；
- 重采样；
- 重复 G-time 自动处理；
- closure picking；
- Carter / PKN / volume balance；
- 裂缝参数反演。

这些限制是故意的。压力导数对噪声、窗口和重复时间处理非常敏感，所以这里先把
最小数学边界写清楚，后续物理解释必须在更严格的审计和测试之后再做。
"""

from __future__ import annotations

import numpy as np


def validate_pressure_derivative_inputs(g_time, pressure_mpa) -> tuple[np.ndarray, np.ndarray]:
    """检查 dP/dG 的最基本输入条件。

    输入：
    - g_time：无量纲 G-time；
    - pressure_mpa：压力，单位 MPa。

    要求：
    - 两者都是一维；
    - 长度相同；
    - 样点数至少 3；
    - 都是有限数字；
    - G-time 必须严格递增。

    这里不做 smoothing，不做重采样，不做 closure，也不自动处理重复 G-time。
    """
    g = np.asarray(g_time, dtype=float)
    pressure = np.asarray(pressure_mpa, dtype=float)

    if g.ndim != 1 or pressure.ndim != 1:
        raise ValueError("G-time 和压力必须是一维数组")
    if len(g) != len(pressure):
        raise ValueError("G-time 和压力长度必须相同")
    if len(g) < 3:
        raise ValueError("至少需要 3 个样点")
    if not np.all(np.isfinite(g)):
        raise ValueError("G-time 含有 NaN 或 inf")
    if not np.all(np.isfinite(pressure)):
        raise ValueError("pressure_mpa 含有 NaN 或 inf")
    if not np.all(np.diff(g) > 0.0):
        raise ValueError("G-time 必须严格递增，不能有重复或倒退")

    return g, pressure


def pressure_derivative_against_g_time(g_time, pressure_mpa) -> tuple[np.ndarray, np.ndarray]:
    """计算压力对 G-time 的数值导数。

    返回：
    - dP_dG_mpa：dP/dG，单位 MPa，因为 G-time 无量纲；
    - G_dP_dG_mpa：G * dP/dG，单位 MPa。

    使用 ``numpy.gradient(P, G, edge_order=1)``。

    注意：这是数值导数预览；不做 smoothing，不判断 closure，不反演裂缝参数。
    """
    g, pressure = validate_pressure_derivative_inputs(g_time, pressure_mpa)
    dP_dG = np.gradient(pressure, g, edge_order=1)
    G_dP_dG = g * dP_dG
    return dP_dG, G_dP_dG
