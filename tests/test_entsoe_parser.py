from datetime import datetime

import pandas as pd

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
    df = entsoe.parse_price_xml(load_fixture("entsoe_prices_15min.xml"))

    assert len(df) == 4
    expected = [datetime(2026, 8, 24, 22, 0),
                datetime(2026, 8, 24, 22, 15),
                datetime(2026, 8, 24, 22, 30),
                datetime(2026, 8, 24, 22, 45)]
    assert df["hour_utc"].tolist() == expected


def test_output_is_naive_utc():
    df = entsoe.parse_price_xml(load_fixture("entsoe_prices.xml"))
    assert df["hour_utc"].dt.tz is None
