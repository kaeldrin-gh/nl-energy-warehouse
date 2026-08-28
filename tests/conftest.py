import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


def load_fixture(name: str) -> bytes:
    return (REPO_ROOT / "tests" / "fixtures" / name).read_bytes()


def build_sample_warehouse(duckdb_path: Path) -> Path:
    """Generate seeded sample data and run a full dbt build against it."""
    import sys

    sys.path.insert(0, str(REPO_ROOT))
    from ingest import db, sample

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
    return duckdb_path


@pytest.fixture(scope="session")
def built_sample_warehouse(tmp_path_factory):
    return build_sample_warehouse(tmp_path_factory.mktemp("wh") / "sample.duckdb")
