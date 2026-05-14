from __future__ import annotations

import numpy as np
import pytest

from clotho.g_function import g_function_time, nolte_g_time


DELTA = np.array([0.0, 0.01, 0.1, 1.0, 10.0])


def test_g_function_time_matches_phase3a_sanity_values() -> None:
    """这些数值来自 Phase 3A 对参考库的公式审计。

    这里不是证明公式一定正确，而是保证 Clotho 第一版教学实现
    与已经审计过的参考行为一致。
    """
    expected = {
        0.5: np.array([0.0, 0.01504262, 0.13640229, 1.0, 4.96053239]),
        0.8: np.array([0.0, 0.01735553, 0.15316905, 1.06765339, 5.08226671]),
        1.0: np.array([0.0, 0.01871658, 0.16275594, 1.1045695, 5.14679479]),
    }

    for m, values in expected.items():
        assert np.allclose(g_function_time(DELTA, m), values, rtol=1e-5, atol=1e-8)


def test_nolte_g_time_matches_phase3a_sanity_values() -> None:
    expected = {
        0.5: np.array([0.0, 0.01915286, 0.17367279, 1.27323954, 6.31594601]),
        0.8: np.array([0.0, 0.02209774, 0.19502089, 1.35937852, 6.47094296]),
        1.0: np.array([0.0, 0.02383069, 0.2072273, 1.40638157, 6.55310265]),
    }

    for m, values in expected.items():
        assert np.allclose(nolte_g_time(DELTA, m), values, rtol=1e-5, atol=1e-8)


def test_zero_and_monotonicity() -> None:
    for m in [0.5, 0.8, 1.0]:
        g_values = g_function_time(DELTA, m)
        g_time = nolte_g_time(DELTA, m)

        assert g_values[0] == pytest.approx(0.0)
        assert g_time[0] == pytest.approx(0.0)
        assert np.all(np.diff(g_time) >= -1e-12)


def test_delta0_normalization() -> None:
    values = nolte_g_time(np.array([0.1, 1.0, 10.0]), 0.8, delta0=0.1)

    assert values[0] == pytest.approx(0.0)
    assert np.allclose(values, np.array([0.0, 1.16435763, 6.27592207]), rtol=1e-5)


def test_scalar_input_returns_float() -> None:
    assert isinstance(g_function_time(0.1, 0.8), float)
    assert isinstance(nolte_g_time(0.1, 0.8), float)


def test_rejects_real_negative_delta() -> None:
    with pytest.raises(ValueError, match="delta"):
        g_function_time([-1.0], 0.8)

    with pytest.raises(ValueError, match="delta"):
        nolte_g_time([-1.0], 0.8)


def test_allows_tiny_negative_delta_from_roundoff() -> None:
    values = g_function_time(np.array([-1e-13, 0.0]), 0.8)

    assert np.allclose(values, np.array([0.0, 0.0]))


def test_rejects_invalid_m() -> None:
    for bad_m in [0.0, -1.0, 1.1, float("inf")]:
        with pytest.raises(ValueError, match="m"):
            g_function_time(0.1, bad_m)


def test_rejects_invalid_delta0() -> None:
    with pytest.raises(ValueError, match="delta"):
        nolte_g_time(0.1, 0.8, delta0=-1.0)


def test_rejects_too_few_quadrature_points() -> None:
    with pytest.raises(ValueError, match="quad_pts"):
        g_function_time(0.1, 0.8, quad_pts=2)
