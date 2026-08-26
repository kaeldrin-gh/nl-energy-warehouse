from datetime import datetime

from conftest import load_fixture

from ingest import entsoe


def test_parses_hourly_points():
    df = entsoe.parse_price_xml(load_fixture("entsoe_prices.xml"))

    assert len(df) == 3
    assert list(df.columns) == ["hour_utc", "price_eur_mwh"]
    assert df.loc[0, "hour_utc"] == datetime(2026, 8, 24, 0, 0)
    assert df.loc[1, "hour_utc"] == datetime(2026, 8, 24, 1, 0)
    assert df.loc[2, "hour_utc"] == datetime(2026, 8, 24, 2, 0)
    assert df["price_eur_mwh"].tolist() == [52.31, 48.75, -12.40]


def test_negative_prices_survive_parsing():
    df = entsoe.parse_price_xml(load_fixture("entsoe_prices.xml"))
    assert (df["price_eur_mwh"] < 0).any()


def test_parses_15_minute_resolution():
    # 15-minute market time units average into their containing hour (INC-004)
    df = entsoe.parse_price_xml(load_fixture("entsoe_prices_15min.xml"))

    assert len(df) == 1
    assert df.loc[0, "hour_utc"] == datetime(2026, 8, 24, 22, 0)
    assert df.loc[0, "price_eur_mwh"] == (70.00 + 71.25 + 69.50 + 73.10) / 4


def test_output_is_naive_utc():
    df = entsoe.parse_price_xml(load_fixture("entsoe_prices.xml"))
    assert df["hour_utc"].dt.tz is None
