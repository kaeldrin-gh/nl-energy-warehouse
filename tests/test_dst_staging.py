import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd

from conftest import REPO_ROOT
from ingest import db

SPRING_DATE = datetime(2026, 3, 29)
AUTUMN_DATE = datetime(2025, 10, 26)


def _run_dbt(duckdb_path: Path) -> None:
    env = os.environ.copy()
    env["DUCKDB_PATH"] = str(duckdb_path)
    dbt = (shutil.which("dbt")
           or str(REPO_ROOT / ".venv" / "Scripts" / "dbt.exe")
           or str(REPO_ROOT / ".venv" / "bin" / "dbt"))
    result = subprocess.run(
        [dbt, "build", "--project-dir", "dbt", "--profiles-dir", "dbt"],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, f"dbt build failed:\n{result.stdout}\n{result.stderr}"


def _insert_knmi_day(duckdb_path: Path, day: datetime, labels) -> None:
    conn = db.connect(duckdb_path)
    frame = pd.DataFrame({
        "station": [260] * len(labels),
        "interval_end_local": [day.replace(hour=h) if h < 24
                               else day.replace(hour=0) + pd.Timedelta(days=1)
                               for h in labels],
        "temp_c": [10.0] * len(labels),
        "wind_ms": [5.0] * len(labels),
        "radiation_jm2": [0.0] * len(labels),
        "fetched_at": [datetime(2026, 8, 25)] * len(labels),
    })
    db.upsert(conn, "knmi_weather", frame)
    conn.close()


def _staged_hours(duckdb_path: Path, day: datetime):
    conn = duckdb.connect(str(duckdb_path))
    rows = conn.execute(
        "select interval_start_utc from main.stg_knmi__hourly_weather "
        "where interval_start_utc >= ? - interval 25 hour "
        "and interval_start_utc < ? + interval 24 hour "
        "order by interval_start_utc",
        [day, day],
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def test_spring_gap_day_produces_no_duplicates(tmp_path):
    path = tmp_path / "dst.duckdb"
    _insert_knmi_day(path, SPRING_DATE, [1, 2] + list(range(4, 25)))
    _run_dbt(path)

    starts = _staged_hours(path, SPRING_DATE)
    assert len(starts) == 23
    assert len(set(starts)) == 23


def test_autumn_overlap_day_produces_no_duplicates(tmp_path):
    path = tmp_path / "dst.duckdb"
    _insert_knmi_day(path, AUTUMN_DATE, list(range(1, 25)))
    _run_dbt(path)

    starts = _staged_hours(path, AUTUMN_DATE)
    assert len(starts) == 24
    assert len(set(starts)) == 24
