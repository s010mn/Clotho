from __future__ import annotations

import numpy as np
import pytest

from clotho.pressure_derivative import (
    derivative_value_summary,
    pressure_derivative_against_g_time,
    validate_pressure_derivative_inputs,
)


def test_pressure_derivative_against_g_time_handles_linear_pressure() -> None:
    g = np.array([0.0, 1.0, 2.0, 3.0])
    pressure = np.array([100.0, 98.0, 96.0, 94.0])

    dP_dG, G_dP_dG = pressure_derivative_against_g_time(g, pressure)

    assert np.allclose(dP_dG, [-2.0, -2.0, -2.0, -2.0])
    assert np.allclose(G_dP_dG, [0.0, -2.0, -4.0, -6.0])


def test_pressure_derivative_rejects_duplicate_g_time() -> None:
    g = [0.0, 1.0, 1.0, 2.0]
    pressure = [100.0, 99.0, 98.0, 97.0]

    with pytest.raises(ValueError, match="严格递增"):
        pressure_derivative_against_g_time(g, pressure)


def test_pressure_derivative_rejects_fewer_than_three_samples() -> None:
    with pytest.raises(ValueError, match="至少需要 3 个样点"):
        pressure_derivative_against_g_time([0.0, 1.0], [100.0, 99.0])


@pytest.mark.parametrize(
    ("g_time", "pressure"),
    [
        ([0.0, float("nan"), 2.0], [100.0, 99.0, 98.0]),
        ([0.0, 1.0, 2.0], [100.0, float("inf"), 98.0]),
    ],
)
def test_pressure_derivative_rejects_nan_or_inf(g_time, pressure) -> None:
    with pytest.raises(ValueError, match="NaN 或 inf"):
        pressure_derivative_against_g_time(g_time, pressure)


def test_validate_pressure_derivative_inputs_rejects_length_mismatch() -> None:
    with pytest.raises(ValueError, match="长度必须相同"):
        validate_pressure_derivative_inputs([0.0, 1.0, 2.0], [100.0, 99.0])


def test_validate_pressure_derivative_inputs_rejects_non_1d_input() -> None:
    with pytest.raises(ValueError, match="一维"):
        validate_pressure_derivative_inputs([[0.0, 1.0, 2.0]], [[100.0, 99.0, 98.0]])


def test_derivative_value_summary_counts_signs_and_finite_range() -> None:
    values = np.array([-2.0, 0.0, 3.0, np.nan, np.inf])

    summary = derivative_value_summary(values)

    assert summary["finite_count"] == 3
    assert summary["nan_or_inf_count"] == 2
    assert summary["positive_count"] == 1
    assert summary["negative_count"] == 1
    assert summary["zero_count"] == 1
    assert summary["min"] == -2.0
    assert summary["median"] == 0.0
    assert summary["max"] == 3.0
