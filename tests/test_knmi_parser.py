from datetime import datetime

import math

from conftest import load_fixture
from ingest import knmi


def test_parses_units_and_hour_24_label():
    df = knmi.parse_uurgeg_text(load_fixture("knmi_uurgeg.txt").decode("utf-8"))

    assert len(df) == 4
    first = df.iloc[0]
    assert first["station"] == 260
    assert first["interval_end_local"] == datetime(2026, 1, 2, 0, 0)
    assert first["temp_c"] == 5.0
    assert first["wind_ms"] == 10.0
    assert first["radiation_jm2"] == 200_000.0


def test_trace_radiation_flag_clamped_to_zero():
    df = knmi.parse_uurgeg_text(load_fixture("knmi_uurgeg.txt").decode("utf-8"))
    assert df.iloc[2]["radiation_jm2"] == 0.0


def test_missing_values_become_nan():
    df = knmi.parse_uurgeg_text(load_fixture("knmi_uurgeg.txt").decode("utf-8"))
    row = df.iloc[3]
    assert row["interval_end_local"] == datetime(2026, 1, 2, 3, 0)
    assert math.isnan(row["temp_c"])
    assert math.isnan(row["wind_ms"])
    assert row["radiation_jm2"] == 0.0


def test_hour_labels_map_to_interval_end():
    df = knmi.parse_uurgeg_text(load_fixture("knmi_uurgeg.txt").decode("utf-8"))
    assert df.iloc[1]["interval_end_local"] == datetime(2026, 1, 2, 1, 0)
    assert df.iloc[2]["interval_end_local"] == datetime(2026, 1, 2, 2, 0)
