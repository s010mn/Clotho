from __future__ import annotations

import pytest

from clotho.stage_data import (
    InjectionWindowPolicy,
    elapsed_seconds_after,
    find_shut_in_index,
    read_stage_curve,
    read_stage_params,
)


def test_stage_data_module_has_chinese_docstring() -> None:
    import clotho.stage_data as stage_data

    assert stage_data.__doc__ is not None
    assert "压裂段参数表" in stage_data.__doc__
    assert "add_pressure" in stage_data.__doc__
    assert "sigma_min" in stage_data.__doc__


def test_read_stage_params_keeps_pressure_and_stress_meaning(tmp_path) -> None:
    path = tmp_path / "stage_params.csv"
    path.write_text(
        "well,stage,file,shut_in,n,spacing,hw,e_gpa,nu,sigma_min,add_pressure,微地震缝长,微地震缝高,广域电磁缝长\n"
        "synthetic,1,stage_data/stage_01.csv,09:00:02,3,8.4,50.0,33.3,0.23,99.1,42.5,299,53,294\n",
        encoding="utf-8",
    )

    info = read_stage_params(path)[0]

    assert info.well == "synthetic"
    assert info.stage == 1
    assert info.minimum_stress_prior_mpa == 99.1
    assert info.pressure_shift_mpa == 42.5
    assert info.microseismic_length_m == 299.0
    assert info.microseismic_height_m == 53.0
    assert info.electromagnetic_length_m == 294.0
    assert not hasattr(info, "bottomhole_pressure")


def test_missing_required_stage_param_text_raises_value_error(tmp_path) -> None:
    path = tmp_path / "stage_params.csv"
    path.write_text(
        "well,stage,file\n"
        "synthetic,1,stage_data/stage_01.csv\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="shut_in_time|必要文本字段"):
        read_stage_params(path)


def test_stage_curve_uses_real_elapsed_seconds_after_shut_in(tmp_path) -> None:
    path = tmp_path / "stage_01.csv"
    path.write_text(
        "time,wellhead_pressure,rate,stage_volume,total_volume\n"
        "09:00:00,95.0,12.0,1.0,1.0\n"
        "09:00:02,96.0,0.0,1.2,1.2\n"
        "09:00:05,95.5,0.0,1.2,1.2\n",
        encoding="utf-8",
    )

    curve = read_stage_curve(path)
    shut_in_index = find_shut_in_index(curve, "09:00:02")
    elapsed = elapsed_seconds_after(curve, shut_in_index)

    assert list(curve["time_text"]) == ["09:00:00", "09:00:02", "09:00:05"]
    assert shut_in_index == 1
    assert elapsed == (0.0, 3.0)
    assert "bottomhole_pressure" not in curve.columns


def test_missing_shut_in_time_raises_value_error(tmp_path) -> None:
    path = tmp_path / "stage_01.csv"
    path.write_text(
        "time,wellhead_pressure,rate,stage_volume,total_volume\n"
        "09:00:00,95.0,12.0,1.0,1.0\n"
        "09:00:02,96.0,0.0,1.2,1.2\n",
        encoding="utf-8",
    )

    curve = read_stage_curve(path)

    with pytest.raises(ValueError):
        find_shut_in_index(curve, "09:00:05")


def test_duplicate_shut_in_time_raises_value_error(tmp_path) -> None:
    path = tmp_path / "stage_01.csv"
    path.write_text(
        "time,wellhead_pressure,rate,stage_volume,total_volume\n"
        "09:00:02,96.0,0.0,1.2,1.2\n"
        "09:00:02,95.9,0.0,1.2,1.2\n",
        encoding="utf-8",
    )

    curve = read_stage_curve(path)

    with pytest.raises(ValueError):
        find_shut_in_index(curve, "09:00:02")


def test_elapsed_seconds_handles_midnight_crossing(tmp_path) -> None:
    path = tmp_path / "stage_01.csv"
    path.write_text(
        "time,wellhead_pressure,rate,stage_volume,total_volume\n"
        "23:59:59,96.0,0.0,1.2,1.2\n"
        "00:00:02,95.9,0.0,1.2,1.2\n",
        encoding="utf-8",
    )

    curve = read_stage_curve(path)
    shut_in_index = find_shut_in_index(curve, "23:59:59")

    assert elapsed_seconds_after(curve, shut_in_index) == (0.0, 3.0)


def test_bad_numeric_pressure_raises_value_error(tmp_path) -> None:
    path = tmp_path / "stage_01.csv"
    path.write_text(
        "time,wellhead_pressure,rate,stage_volume,total_volume\n"
        "09:00:00,bad_pressure,12.0,1.0,1.0\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="wellhead_pressure_mpa|bad_pressure"):
        read_stage_curve(path)


def test_injection_window_policy_names_future_tp_choices() -> None:
    assert InjectionWindowPolicy.VOLUME_OVER_MAX_SUSTAINED_RATE.value == "volume_over_max_sustained_rate"
