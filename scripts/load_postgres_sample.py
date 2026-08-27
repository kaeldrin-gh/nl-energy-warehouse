"""Load deterministic sample data into a PostgreSQL raw schema.

Used by the validate-postgres CI job to prove the dbt models run on a second
engine without any local infrastructure. Creates the raw tables (same DDL as
ingest.db.SCHEMA_SQL, minus the ingest_log which models never read) and fills
them with the seeded sample frames.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text  # noqa: E402

from ingest import sample  # noqa: E402

RAW_DDL = [
    """create table if not exists raw.entsoe_prices (
        hour_utc timestamp not null,
        price_eur_mwh double precision,
        fetched_at timestamp not null,
        primary key (hour_utc)
    )""",
    """create table if not exists raw.energycharts_prices (
        hour_utc timestamp not null,
        price_eur_mwh double precision,
        fetched_at timestamp not null,
        primary key (hour_utc)
    )""",
    """create table if not exists raw.knmi_weather (
        station integer not null,
        interval_end_local timestamp not null,
        temp_c double precision,
        wind_ms double precision,
        radiation_jm2 double precision,
        fetched_at timestamp not null,
        primary key (station, interval_end_local)
    )""",
    """create table if not exists raw.openmeteo_weather (
        station integer not null,
        interval_end_local timestamp not null,
        temp_c double precision,
        wind_ms double precision,
        radiation_jm2 double precision,
        fetched_at timestamp not null,
        primary key (station, interval_end_local)
    )""",
]


def main() -> None:
    url = (
        f"postgresql+psycopg2://{os.environ['PGUSER']}:{os.environ['PGPASSWORD']}"
        f"@{os.environ['PGHOST']}:{os.environ.get('PGPORT', '5432')}/{os.environ['PGDATABASE']}"
    )
    engine = create_engine(url)

    with engine.begin() as conn:
        conn.execute(text("create schema if not exists raw"))
        for ddl in RAW_DDL:
            conn.execute(text(ddl))

    frames = sample.generate(sample_days=30)
    with engine.begin() as conn:
        for table, frame in frames.items():
            rows = frame.to_sql(table, conn, schema="raw", if_exists="append", index=False)
            print(f"raw.{table}: loaded {rows} rows")


if __name__ == "__main__":
    main()
