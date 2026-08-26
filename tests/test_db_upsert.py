from datetime import datetime

import pandas as pd

from ingest import db


def _price_frame(prices, fetched_at):
    hours = pd.date_range("2026-08-24", periods=len(prices), freq="h")
    return pd.DataFrame(
        {
            "hour_utc": hours,
            "price_eur_mwh": prices,
            "fetched_at": fetched_at,
        }
    )


def test_upsert_is_idempotent(tmp_path):
    conn = db.connect(tmp_path / "t.duckdb")
    df = _price_frame([10.0, 11.0, 12.0], datetime(2026, 8, 25, 12, 0))

    assert db.upsert(conn, "entsoe_prices", df) == 3
    db.upsert(conn, "entsoe_prices", df)

    count = conn.execute("select count(*) from raw.entsoe_prices").fetchone()[0]
    assert count == 3


def test_revision_overwrites_stale_value(tmp_path):
    conn = db.connect(tmp_path / "t.duckdb")
    db.upsert(conn, "entsoe_prices", _price_frame([10.0, 11.0, 12.0], datetime(2026, 8, 25, 12, 0)))

    revised = _price_frame([99.0, 11.0, 12.0], datetime(2026, 8, 25, 18, 0))
    db.upsert(conn, "entsoe_prices", revised)

    row = conn.execute(
        "select price_eur_mwh, fetched_at from raw.entsoe_prices "
        "where hour_utc = '2026-08-24 00:00:00'"
    ).fetchone()
    assert row[0] == 99.0
    assert row[1] == datetime(2026, 8, 25, 18, 0)


def test_empty_frame_writes_nothing(tmp_path):
    conn = db.connect(tmp_path / "t.duckdb")
    empty = pd.DataFrame(
        {
            "hour_utc": pd.Series([], dtype="datetime64[ns]"),
            "price_eur_mwh": pd.Series([], dtype="float64"),
            "fetched_at": pd.Series([], dtype="datetime64[ns]"),
        }
    )
    assert db.upsert(conn, "entsoe_prices", empty) == 0
