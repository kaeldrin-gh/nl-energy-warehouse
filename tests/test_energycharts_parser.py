from datetime import datetime

from ingest import energycharts


def _payload(seconds, prices):
    return {"unix_seconds": seconds, "price": prices}


def test_parses_hourly_points():
    # 2026-08-24 00:00 and 01:00 UTC
    df = energycharts.parse_price_payload(_payload([1787529600, 1787533200], [52.31, -12.40]))

    assert list(df.columns) == ["hour_utc", "price_eur_mwh"]
    assert len(df) == 2
    assert df.loc[0, "hour_utc"] == datetime(2026, 8, 24, 0, 0)
    assert df.loc[1, "hour_utc"] == datetime(2026, 8, 24, 1, 0)
    assert df["price_eur_mwh"].tolist() == [52.31, -12.40]


def test_15_minute_points_average_into_their_hour():
    # Four quarter-slots of the same hour at 10, 20, 30, 40 EUR/MWh -> mean 25.
    base = 1787529600  # 2026-08-24 00:00 UTC
    quarter = 900
    df = energycharts.parse_price_payload(
        _payload([base + quarter * i for i in range(4)], [10.0, 20.0, 30.0, 40.0])
    )

    assert len(df) == 1
    assert df.loc[0, "hour_utc"] == datetime(2026, 8, 24, 0, 0)
    assert df.loc[0, "price_eur_mwh"] == 25.0


def test_drops_in_progress_hour_missing_last_quarter():
    # 3 of 4 quarters present (fetch happened mid-hour): mean over the survivors
    # biases the hour, so it is dropped (INC-007) and left to a later refetch.
    base = 1787529600  # 2026-08-24 00:00 UTC
    quarter = 900
    df = energycharts.parse_price_payload(
        _payload([base + quarter * i for i in range(3)], [10.0, 20.0, 30.0])
    )

    assert len(df) == 0


def test_single_point_hours_kept_only_in_hourly_era():
    # Hourly-era payload: lone :00 points surrounded by other lone points.
    base = 1787529600  # 2026-08-24 00:00 UTC
    hour = 3600
    df = energycharts.parse_price_payload(
        _payload([base, base + hour, base + 2 * hour], [10.0, 20.0, 30.0])
    )
    assert len(df) == 3

    # Quarter-era payload: an isolated single point is a partial hour -> dropped,
    # while its fully-covered neighbour survives.
    df = energycharts.parse_price_payload(
        _payload(
            [base, base + hour, base + hour + 900, base + hour + 1800, base + hour + 2700],
            [10.0, 20.0, 30.0, 40.0, 50.0],
        )
    )
    assert df["hour_utc"].tolist() == [datetime(2026, 8, 24, 1, 0)]
    assert df.loc[0, "price_eur_mwh"] == 35.0


def test_null_prices_are_dropped():
    # Hourly-era context (consecutive lone points); the null hour vanishes and
    # must not break its neighbours' completeness.
    base = 1787529600  # 2026-08-24 00:00 UTC
    hour = 3600
    df = energycharts.parse_price_payload(
        _payload([base, base + hour, base + 2 * hour], [52.31, None, -12.4])
    )

    assert len(df) == 2
    assert df["price_eur_mwh"].tolist() == [52.31, -12.4]


def test_empty_payload_yields_empty_frame():
    df = energycharts.parse_price_payload(_payload([], []))

    assert len(df) == 0
    assert list(df.columns) == ["hour_utc", "price_eur_mwh"]


def test_zone_map_translates_entsoe_eic_code():
    assert energycharts.ZONE_MAP["10YNL----------L"] == "NL"
