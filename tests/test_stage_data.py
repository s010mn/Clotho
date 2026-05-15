from __future__ import annotations

import pytest

from clotho.stage_data import (
    InjectionWindowPolicy,
    add_estimated_bottomhole_pressure,
    apply_elapsed_duplicate_policy,
    compare_injection_duration_policies,
    elapsed_seconds_after,
    falloff_window_after_shut_in,
    find_shut_in_index,
    find_time_index,
    picked_duration_seconds,
    rate_positive_duration_seconds,
    read_stage_curve,
    read_stage_params,
    volume_over_max_rate_duration_seconds,
)


def _write_teaching_curve(path) -> None:
    path.write_text(
        "time,wellhead_pressure,rate,stage_volume,total_volume\n"
        "09:00:00,95.0,10.0,0.0,1000.0\n"
        "09:01:00,96.0,10.0,10.0,1010.0\n"
        "09:03:00,97.0,0.0,30.0,1030.0\n",
        encoding="utf-8",
    )


def _write_reset_volume_curve(path) -> None:
    path.write_text(
        "time,wellhead_pressure,rate,stage_volume,total_volume\n"
        "09:00:00,95.0,10.0,0.0,1000.0\n"
        "09:01:00,96.0,10.0,10.0,1010.0\n"
        "09:02:00,96.5,10.0,0.0,1020.0\n"
        "09:03:00,97.0,0.0,5.0,1030.0\n",
        encoding="utf-8",
    )


def test_stage_data_module_has_chinese_docstring() -> None:
    import clotho.stage_data as stage_data

    assert stage_data.__doc__ is not None
    assert "压裂段参数表" in stage_data.__doc__
    assert "add_pressure" in stage_data.__doc__
    assert "sigma_min" in stage_data.__doc__
    assert "liquid_column_pressure_mpa" in stage_data.__doc__
    assert "estimated_bottomhole_pressure_mpa" in stage_data.__doc__


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
    assert info.liquid_column_pressure_mpa == 42.5
    assert info.microseismic_length_m == 299.0
    assert info.microseismic_height_m == 53.0
    assert info.electromagnetic_length_m == 294.0
    assert not hasattr(info, "pressure_shift_mpa")
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
    assert "estimated_bottomhole_pressure_mpa" not in curve.columns
    assert "bottomhole_pressure_mpa" not in curve.columns


def test_add_estimated_bottomhole_pressure_is_explicit(tmp_path) -> None:
    params = tmp_path / "stage_params.csv"
    params.write_text(
        "well,stage,file,shut_in,add_pressure\n"
        "synthetic,1,stage_data/stage_01.csv,09:00:00,42.5\n",
        encoding="utf-8",
    )
    curve_file = tmp_path / "stage_01.csv"
    curve_file.write_text(
        "time,wellhead_pressure,rate,stage_volume,total_volume\n"
        "09:00:00,95.0,0.0,1.0,1.0\n",
        encoding="utf-8",
    )

    stage = read_stage_params(params)[0]
    curve = read_stage_curve(curve_file)
    corrected = add_estimated_bottomhole_pressure(curve, stage)

    assert "estimated_bottomhole_pressure_mpa" not in curve.columns
    assert "estimated_bottomhole_pressure_mpa" in corrected.columns
    assert "bottomhole_pressure_mpa" not in corrected.columns
    assert corrected["estimated_bottomhole_pressure_mpa"].iloc[0] == 95.0 + 42.5


def test_missing_liquid_column_pressure_raises_value_error(tmp_path) -> None:
    params = tmp_path / "stage_params.csv"
    params.write_text(
        "well,stage,file,shut_in,add_pressure\n"
        "synthetic,1,stage_data/stage_01.csv,09:00:00,\n",
        encoding="utf-8",
    )
    curve_file = tmp_path / "stage_01.csv"
    curve_file.write_text(
        "time,wellhead_pressure,rate,stage_volume,total_volume\n"
        "09:00:00,95.0,0.0,1.0,1.0\n",
        encoding="utf-8",
    )

    stage = read_stage_params(params)[0]
    curve = read_stage_curve(curve_file)

    with pytest.raises(ValueError, match="liquid_column_pressure_mpa"):
        add_estimated_bottomhole_pressure(curve, stage)


def test_find_time_index_is_general_exact_match(tmp_path) -> None:
    path = tmp_path / "stage_01.csv"
    _write_teaching_curve(path)

    curve = read_stage_curve(path)

    assert find_time_index(curve, "09:01:00") == 1
    with pytest.raises(ValueError):
        find_time_index(curve, "09:02:00")


def test_rate_positive_duration_seconds_uses_real_time_gaps(tmp_path) -> None:
    path = tmp_path / "stage_01.csv"
    _write_teaching_curve(path)

    curve = read_stage_curve(path)
    shut_in_index = find_shut_in_index(curve, "09:03:00")

    assert rate_positive_duration_seconds(curve, shut_in_index) == 180.0


def test_volume_over_max_rate_duration_seconds_uses_explicit_total_volume(tmp_path) -> None:
    path = tmp_path / "stage_01.csv"
    _write_teaching_curve(path)

    curve = read_stage_curve(path)
    shut_in_index = find_shut_in_index(curve, "09:03:00")

    duration = volume_over_max_rate_duration_seconds(
        curve,
        shut_in_index,
        max_sustained_rate=10.0,
        rate_time_unit="minute",
        volume_column="total_volume",
    )

    assert duration == 180.0


def test_stage_volume_reset_raises_value_error(tmp_path) -> None:
    path = tmp_path / "stage_01.csv"
    _write_reset_volume_curve(path)

    curve = read_stage_curve(path)
    shut_in_index = find_shut_in_index(curve, "09:03:00")

    with pytest.raises(ValueError, match="stage_volume|回落|重置"):
        volume_over_max_rate_duration_seconds(
            curve,
            shut_in_index,
            max_sustained_rate=10.0,
            rate_time_unit="minute",
            volume_column="stage_volume",
        )


def test_total_volume_works_when_stage_volume_resets(tmp_path) -> None:
    path = tmp_path / "stage_01.csv"
    _write_reset_volume_curve(path)

    curve = read_stage_curve(path)
    shut_in_index = find_shut_in_index(curve, "09:03:00")

    duration = volume_over_max_rate_duration_seconds(
        curve,
        shut_in_index,
        max_sustained_rate=10.0,
        rate_time_unit="minute",
        volume_column="total_volume",
    )

    assert duration == 180.0


def test_bad_volume_column_raises_value_error(tmp_path) -> None:
    path = tmp_path / "stage_01.csv"
    _write_teaching_curve(path)

    curve = read_stage_curve(path)
    shut_in_index = find_shut_in_index(curve, "09:03:00")

    with pytest.raises(ValueError, match="bad_volume"):
        volume_over_max_rate_duration_seconds(
            curve,
            shut_in_index,
            max_sustained_rate=10.0,
            rate_time_unit="minute",
            volume_column="bad_volume",
        )


def test_volume_over_max_rate_duration_seconds_rejects_bad_inputs(tmp_path) -> None:
    path = tmp_path / "stage_01.csv"
    _write_teaching_curve(path)

    curve = read_stage_curve(path)
    shut_in_index = find_shut_in_index(curve, "09:03:00")

    with pytest.raises(ValueError):
        volume_over_max_rate_duration_seconds(
            curve,
            shut_in_index,
            max_sustained_rate=0.0,
            rate_time_unit="minute",
            volume_column="total_volume",
        )
    with pytest.raises(ValueError):
        volume_over_max_rate_duration_seconds(
            curve,
            shut_in_index,
            max_sustained_rate=10.0,
            rate_time_unit="bad_unit",
            volume_column="total_volume",
        )


def test_picked_duration_seconds_uses_human_selected_window(tmp_path) -> None:
    path = tmp_path / "stage_01.csv"
    _write_teaching_curve(path)

    curve = read_stage_curve(path)

    assert picked_duration_seconds(curve, "09:01:00", "09:03:00") == 120.0


def test_compare_injection_duration_policies_returns_two_teaching_strategies(tmp_path) -> None:
    path = tmp_path / "stage_01.csv"
    _write_teaching_curve(path)

    curve = read_stage_curve(path)
    shut_in_index = find_shut_in_index(curve, "09:03:00")
    durations = compare_injection_duration_policies(
        curve,
        shut_in_index,
        max_sustained_rate=10.0,
        rate_time_unit="minute",
        volume_column="total_volume",
    )

    assert durations == {
        "rate_positive_elapsed": 180.0,
        "volume_over_max_sustained_rate": 180.0,
    }


def test_rate_positive_duration_seconds_handles_midnight_crossing(tmp_path) -> None:
    path = tmp_path / "stage_01.csv"
    path.write_text(
        "time,wellhead_pressure,rate,stage_volume,total_volume\n"
        "23:59:00,95.0,10.0,0.0,1000.0\n"
        "00:00:00,96.0,10.0,10.0,1010.0\n"
        "00:02:00,97.0,0.0,30.0,1030.0\n",
        encoding="utf-8",
    )

    curve = read_stage_curve(path)
    shut_in_index = find_shut_in_index(curve, "00:02:00")

    assert rate_positive_duration_seconds(curve, shut_in_index) == 180.0


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


def test_falloff_window_after_shut_in_uses_manual_end_elapsed(tmp_path) -> None:
    path = tmp_path / "stage_01.csv"
    path.write_text(
        "time,wellhead_pressure,rate,stage_volume,total_volume\n"
        "00:00:00,20,10,0,0\n"
        "00:00:01,21,10,0.3333333333,0.3333333333\n"
        "00:00:02,22,10,0.6666666667,0.6666666667\n"
        "00:00:03,23,0,1.0,1.0\n"
        "00:00:04,22,0,1.0,1.0\n"
        "00:00:05,21,0,1.0,1.0\n"
        "00:00:06,5,0,1.0,1.0\n"
        "00:00:07,0,0,1.0,1.0\n",
        encoding="utf-8",
    )
    curve = read_stage_curve(path)
    shut_in_index = find_shut_in_index(curve, "00:00:03")

    full_window = falloff_window_after_shut_in(curve, shut_in_index)
    clipped_window = falloff_window_after_shut_in(curve, shut_in_index, end_elapsed_seconds=2)

    assert list(full_window["elapsed_seconds"]) == [0.0, 1.0, 2.0, 3.0, 4.0]
    assert list(clipped_window["elapsed_seconds"]) == [0.0, 1.0, 2.0]
    assert list(clipped_window["wellhead_pressure_mpa"]) == [23, 22, 21]


@pytest.mark.parametrize("policy", ["none", "keep-first", "keep-last", "mean"])
def test_apply_elapsed_duplicate_policy_is_explicit(tmp_path, policy) -> None:
    path = tmp_path / "stage_01.csv"
    path.write_text(
        "time,wellhead_pressure,rate,stage_volume,total_volume\n"
        "00:00:03,23,0,1.0,1.0\n"
        "00:00:04,22,0,1.0,1.0\n"
        "00:00:04,20,0,1.0,1.0\n"
        "00:00:05,19,0,1.0,1.0\n",
        encoding="utf-8",
    )
    curve = read_stage_curve(path)
    window = falloff_window_after_shut_in(curve, 0)

    result = apply_elapsed_duplicate_policy(window, policy=policy)

    if policy == "none":
        assert list(result["elapsed_seconds"]) == [0.0, 1.0, 1.0, 2.0]
        assert list(result["wellhead_pressure_mpa"]) == [23, 22, 20, 19]
    elif policy == "keep-first":
        assert list(result["elapsed_seconds"]) == [0.0, 1.0, 2.0]
        assert list(result["wellhead_pressure_mpa"]) == [23, 22, 19]
    elif policy == "keep-last":
        assert list(result["elapsed_seconds"]) == [0.0, 1.0, 2.0]
        assert list(result["wellhead_pressure_mpa"]) == [23, 20, 19]
    else:
        assert list(result["elapsed_seconds"]) == [0.0, 1.0, 2.0]
        assert list(result["wellhead_pressure_mpa"]) == [23.0, 21.0, 19.0]


@pytest.mark.parametrize("bad_end", [-1, float("inf")])
def test_falloff_window_after_shut_in_rejects_bad_end_elapsed(tmp_path, bad_end) -> None:
    path = tmp_path / "stage_01.csv"
    _write_teaching_curve(path)
    curve = read_stage_curve(path)

    with pytest.raises(ValueError, match="end_elapsed_seconds"):
        falloff_window_after_shut_in(curve, 0, end_elapsed_seconds=bad_end)



def test_injection_window_policy_names_future_tp_choices() -> None:
    assert InjectionWindowPolicy.VOLUME_OVER_MAX_SUSTAINED_RATE.value == "volume_over_max_sustained_rate"


def test_read_stage_params_cluster_spacings_fleak_m(tmp_path) -> None:
    csv = tmp_path / "sp.csv"
    csv.write_text(
        "well,stage,file,shut_in,n,spacing,hw,e_gpa,nu,sigma_min,"
        "cluster_spacings,fleak,m\n"
        "W1,1,s1.csv,10:00:00,4,8.4,50.0,33.3,0.23,99.1,"
        "8.4;8.4;8.4,0.5,0.8\n"
        "W1,2,s2.csv,11:00:00,3,11.0,50.0,33.3,0.23,99.1,"
        ",0.25,\n",
        encoding="utf-8",
    )
    infos = read_stage_params(csv)
    assert len(infos) == 2

    s1 = infos[0]
    assert s1.cluster_spacings_list == [8.4, 8.4, 8.4]
    assert s1.fleak == 0.5
    assert s1.g_function_m == 0.8

    s2 = infos[1]
    assert s2.cluster_spacings_list is None
    assert s2.fleak == 0.25
    assert s2.g_function_m is None
