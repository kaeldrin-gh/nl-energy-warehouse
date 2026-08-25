import pandas as pd

from ingest import sample


def test_generation_is_deterministic():
    a = sample.generate(30)
    b = sample.generate(30)
    for table in a:
        pd.testing.assert_frame_equal(a[table].drop(columns=["fetched_at"]),
                                      b[table].drop(columns=["fetched_at"]))


def test_hourly_grain_and_alignment():
    frames = sample.generate(10)
    prices = frames["entsoe_prices"]
    weather = frames["knmi_weather"]

    assert len(prices) == 240
    assert prices["hour_utc"].is_unique

    assert weather["interval_end_local"].is_unique
    assert weather["temp_c"].between(-30, 40).all()
    assert (weather["radiation_jm2"] >= 0).all()


def test_negative_prices_present():
    prices = sample.generate(90)["entsoe_prices"]
    assert (prices["price_eur_mwh"] < 0).sum() >= 3


def test_cross_source_tracks_primary():
    frames = sample.generate(30)
    merged = frames["entsoe_prices"].merge(frames["energycharts_prices"], on="hour_utc",
                                           suffixes=("", "_cross"))
    diff = (merged["price_eur_mwh"] - merged["price_eur_mwh_cross"]).abs()
    assert diff.max() < 2.0
