"""Contract test: the exported Parquet schema is Power BI's ingestion contract.

If a column changes name or type, this fails before a dashboard silently breaks.
"""
import os
import subprocess
import sys

import pandas as pd
import pytest
from conftest import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT))

from ingest import cli, db, sample  # noqa: E402

EXPECTED = {
    "fct_hourly_price_weather": {
        "hour_utc": "datetime64[us]",
        "hour_local": "datetime64[us]",
        "price_eur_mwh": "float64",
        "price_eur_mwh_cross_source": "float64",
        "price_diff_eur": "float64",
        "price_source": "str",
        "has_weather_match": "bool",
        "temp_c": "float64",
        "wind_ms": "float64",
        "radiation_jm2": "float64",
        "hour_local_label": "Int64",
        "is_negative_price": "bool",
    },
    "mart_daily_summary": {
        "local_date": "datetime64[us]",
        "hours_in_day": "int64",
        "avg_price_eur_mwh": "float64",
        "min_price_eur_mwh": "float64",
        "max_price_eur_mwh": "float64",
        "negative_price_hours": "int64",
        "avg_temp_c": "float64",
        "max_wind_ms": "float64",
        "total_radiation_mj_m2": "float64",
    },
}


@pytest.fixture()
def sample_export(tmp_path):
    duckdb_path = tmp_path / "contract.duckdb"
    frames = sample.generate(sample_days=30)
    conn = db.connect(duckdb_path)
    for table, frame in frames.items():
        db.upsert(conn, table, frame)
    conn.close()

    env = os.environ.copy()
    env["DUCKDB_PATH"] = str(duckdb_path)
    result = subprocess.run(
        ["dbt", "build", "--project-dir", "dbt", "--profiles-dir", "dbt"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, f"dbt build failed:\n{result.stdout[-2000:]}"

    out = tmp_path / "exports"
    cli.export_marts(out, duckdb_path)
    return out


@pytest.mark.parametrize("table", list(EXPECTED))
def test_export_schema_contract(sample_export, table):
    df = pd.read_parquet(sample_export / f"{table}.parquet")

    assert list(df.columns) == list(EXPECTED[table]), (
        f"{table}: column set/order drifted from the BI contract"
    )
    for column, expected_type in EXPECTED[table].items():
        assert str(df[column].dtype) == expected_type, (
            f"{table}.{column}: dtype {df[column].dtype} != contract {expected_type}"
        )


def test_export_has_no_all_null_required_columns(sample_export):
    df = pd.read_parquet(sample_export / "fct_hourly_price_weather.parquet")
    for column in ("hour_utc", "price_eur_mwh", "price_source", "is_negative_price"):
        assert df[column].notna().all(), f"{column} must never be null in the export"
