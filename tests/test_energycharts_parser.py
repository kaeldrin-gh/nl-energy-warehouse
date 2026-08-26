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


def test_null_prices_are_dropped():
    df = energycharts.parse_price_payload(_payload([1787529600, 1787533200], [52.31, None]))

    assert len(df) == 1
    assert df.loc[0, "hour_utc"] == datetime(2026, 8, 24, 0, 0)


def test_empty_payload_yields_empty_frame():
    df = energycharts.parse_price_payload(_payload([], []))

    assert len(df) == 0
    assert list(df.columns) == ["hour_utc", "price_eur_mwh"]


def test_zone_map_translates_entsoe_eic_code():
    assert energycharts.ZONE_MAP["10YNL----------L"] == "NL"
