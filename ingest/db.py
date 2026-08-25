from pathlib import Path

import duckdb

from .config import settings

SCHEMA_SQL = """
CREATE SCHEMA IF NOT EXISTS raw;

CREATE TABLE IF NOT EXISTS raw.entsoe_prices (
    hour_utc TIMESTAMP NOT NULL,
    price_eur_mwh DOUBLE,
    fetched_at TIMESTAMP NOT NULL,
    PRIMARY KEY (hour_utc)
);

CREATE TABLE IF NOT EXISTS raw.energycharts_prices (
    hour_utc TIMESTAMP NOT NULL,
    price_eur_mwh DOUBLE,
    fetched_at TIMESTAMP NOT NULL,
    PRIMARY KEY (hour_utc)
);

CREATE TABLE IF NOT EXISTS raw.knmi_weather (
    station INTEGER NOT NULL,
    interval_end_local TIMESTAMP NOT NULL,
    temp_c DOUBLE,
    wind_ms DOUBLE,
    radiation_jm2 DOUBLE,
    fetched_at TIMESTAMP NOT NULL,
    PRIMARY KEY (station, interval_end_local)
);

CREATE TABLE IF NOT EXISTS raw.ingest_log (
    source VARCHAR NOT NULL,
    run_at TIMESTAMP NOT NULL,
    window_start TIMESTAMP,
    window_end TIMESTAMP,
    rows_written BIGINT
);
"""


def connect() -> duckdb.DuckDBPyConnection:
    settings.duckdb_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(settings.duckdb_path))
    conn.execute("SET TimeZone='UTC'")
    conn.execute(SCHEMA_SQL)
    return conn


def upsert(conn: duckdb.DuckDBPyConnection, table: str, df) -> int:
    if df.empty:
        return 0
    conn.register("upsert_df", df)
    conn.execute(
        f"INSERT OR REPLACE INTO raw.{table} SELECT * FROM upsert_df"
    )
    n = conn.execute("SELECT count(*) FROM upsert_df").fetchone()[0]
    conn.unregister("upsert_df")
    return n


def log_run(conn: duckdb.DuckDBPyConnection, source: str, window_start, window_end, rows: int):
    conn.execute(
        "INSERT INTO raw.ingest_log VALUES (?, now(), ?, ?, ?)",
        [source, window_start, window_end, rows],
    )


def watermark(conn: duckdb.DuckDBPyConnection, source: str):
    row = conn.execute(
        "SELECT max(window_end) FROM raw.ingest_log WHERE source = ? AND window_end IS NOT NULL",
        [source],
    ).fetchone()
    return row[0]
