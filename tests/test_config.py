"""DUCKDB_PATH means the same warehouse to the loader, dbt and the API.

Regression: the loader ignored the variable, so `DUCKDB_PATH=scratch.duckdb
python -m ingest.cli load --sample` overwrote the real warehouse with synthetic
prices while dbt built the scratch file (and the Docker image, which sets
DUCKDB_PATH=/data/energy.duckdb, loaded into a path dbt never read).
"""

import os
import subprocess
import sys
from pathlib import Path

import duckdb
from conftest import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT))

from ingest import config  # noqa: E402


def test_settings_follow_duckdb_path(monkeypatch, tmp_path):
    target = tmp_path / "elsewhere.duckdb"
    monkeypatch.setenv("DUCKDB_PATH", str(target))

    assert config.Settings().duckdb_path == target


def test_settings_default_to_the_repo_warehouse(monkeypatch):
    monkeypatch.delenv("DUCKDB_PATH", raising=False)

    assert config.Settings().duckdb_path == REPO_ROOT / "warehouse" / "energy.duckdb"


def test_sample_load_writes_only_where_duckdb_path_points(tmp_path):
    target = tmp_path / "scratch.duckdb"
    env = {**os.environ, "DUCKDB_PATH": str(target)}

    result = subprocess.run(
        [sys.executable, "-m", "ingest.cli", "load", "--sample"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )

    assert result.returncode == 0, result.stderr[-2000:]
    conn = duckdb.connect(str(target), read_only=True)
    assert conn.execute("select count(*) from raw.entsoe_prices").fetchone()[0] > 0
    conn.close()
    assert Path(target).stat().st_size > 0
