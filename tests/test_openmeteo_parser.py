from datetime import datetime

from ingest import openmeteo


def _payload(times, temps, winds, rads):
    return {
        "hourly": {
            "time": times,
            "temperature_2m": temps,
            "wind_speed_10m": winds,
            "shortwave_radiation": rads,
        }
    }


def test_converts_units_to_warehouse_contract():
    df = openmeteo.parse_hourly_payload(_payload(["2026-08-24T00:00"], [18.5], [18.0], [500.0]))

    assert len(df) == 1
    # wind 18 km/h -> 5.0 m/s; 500 W/m2 sustained for the hour -> 1.8e6 J/m2
    assert df.loc[0, "wind_ms"] == 5.0
    assert df.loc[0, "radiation_jm2"] == 1800000.0
    assert df.loc[0, "temp_c"] == 18.5


def test_hour_labels_are_amsterdam_hour_ends():
    # UTC hour 22:00-23:00 (CEST, UTC+2) ends at 01:00 Amsterdam label next day
    df = openmeteo.parse_hourly_payload(_payload(["2026-08-24T22:00"], [18.5], [18.0], [500.0]))

    assert df.loc[0, "interval_end_local"] == datetime(2026, 8, 25, 1, 0)

    # Winter (CET, UTC+1): UTC hour 22:00-23:00 ends at 00:00 Amsterdam next day
    df = openmeteo.parse_hourly_payload(_payload(["2026-01-15T22:00"], [3.0], [18.0], [0.0]))
    assert df.loc[0, "interval_end_local"] == datetime(2026, 1, 16, 0, 0)


def test_fully_null_hours_are_skipped():
    df = openmeteo.parse_hourly_payload(
        _payload(
            ["2026-08-24T00:00", "2026-08-24T01:00"],
            [18.5, None],
            [18.0, None],
            [500.0, None],
        )
    )

    assert len(df) == 1
    assert df.loc[0, "temp_c"] == 18.5


def test_partially_null_row_keeps_available_fields():
    df = openmeteo.parse_hourly_payload(_payload(["2026-08-24T00:00"], [18.5], [None], [500.0]))

    assert len(df) == 1
    assert df.loc[0, "temp_c"] == 18.5
    assert df.loc[0, "wind_ms"] is None
    assert df.loc[0, "radiation_jm2"] == 1800000.0
