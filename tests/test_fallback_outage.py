"""A fallback outage must not stop the marts, and the report must say so.

On 4 Oct 2026 energy-charts returned HTTP 503. ENTSO-E had 4 unpublished
hours in the last 14 days, so the hour-continuity test stopped the build and
no report was made. Now:

* gaps stay an error when both price sources loaded (a real problem),
* gaps are a warning when energy-charts did not load after ENTSO-E,
* the report and the run summary show the missing hours and their cause.
"""

import os
import subprocess
import sys
from datetime import datetime, timedelta

import pandas as pd
import pytest

from tests.conftest import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT))

from ingest import cli, db, report, sample  # noqa: E402


def test_hour_gaps_lists_each_run_of_missing_hours():
    hours = pd.date_range("2026-10-01 00:00", "2026-10-03 23:00", freq="h")
    missing = {pd.Timestamp("2026-10-02 05:00"), pd.Timestamp("2026-10-02 06:00")}
    missing.add(pd.Timestamp("2026-10-03 12:00"))
    hourly = pd.DataFrame({"hour_utc": [h for h in hours if h not in missing]})

    gaps = report.hour_gaps(hourly)

    assert list(gaps["missing_hours"]) == [2, 1]
    assert gaps.iloc[0]["first_missing"] == pd.Timestamp("2026-10-02 05:00")
    assert gaps.iloc[0]["last_missing"] == pd.Timestamp("2026-10-02 06:00")
    assert gaps.iloc[1]["first_missing"] == pd.Timestamp("2026-10-03 12:00")


def test_hour_gaps_is_empty_for_continuous_hours():
    hourly = pd.DataFrame({"hour_utc": pd.date_range("2026-10-01", periods=72, freq="h")})
    assert report.hour_gaps(hourly).empty


def _log(conn, source, run_at):
    conn.execute("INSERT INTO raw.ingest_log VALUES (?, ?, NULL, NULL, 0)", [source, run_at])


@pytest.mark.parametrize(
    ("entries", "expected"),
    [
        ([], False),  # sample or empty warehouse: no live load
        ([("entsoe", 1), ("energycharts", 2)], False),  # both loaded, in order
        ([("entsoe", 1)], True),  # energy-charts never loaded
        ([("energycharts", 1), ("entsoe", 2)], True),  # it failed in the latest run
        ([("energycharts", 1)], False),  # ENTSO-E failed: not a fallback outage
    ],
)
def test_fallback_degraded(tmp_path, entries, expected):
    conn = db.connect(tmp_path / "log.duckdb")
    start = datetime(2026, 10, 4, 18)
    for source, minute in entries:
        _log(conn, source, start + timedelta(minutes=minute))
    assert db.fallback_degraded(conn) is expected
    conn.close()


def _warehouse_with_gaps(path):
    """Sample data with 4 hours missing from both price sources."""
    frames = sample.generate(sample_days=30)
    last = frames["entsoe_prices"]["hour_utc"].max()
    gone = [last - pd.Timedelta(hours=h) for h in (30, 60, 90, 120)]
    conn = db.connect(path)
    for table, frame in frames.items():
        if table in ("entsoe_prices", "energycharts_prices"):
            frame = frame[~frame["hour_utc"].isin(gone)]
        db.upsert(conn, table, frame)
    return conn


def _build(path):
    env = os.environ.copy()
    env["DUCKDB_PATH"] = str(path)
    return subprocess.run(
        [sys.executable, "-m", "ingest.cli", "build"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )


def test_gaps_stop_the_build_when_both_sources_loaded(tmp_path):
    path = tmp_path / "both.duckdb"
    conn = _warehouse_with_gaps(path)
    _log(conn, "entsoe", datetime(2026, 10, 4, 18, 0))
    _log(conn, "energycharts", datetime(2026, 10, 4, 18, 1))
    conn.close()

    result = _build(path)

    assert result.returncode != 0
    assert "assert_hour_continuity_recent" in result.stdout + result.stderr


def test_fallback_outage_builds_the_marts_and_reports_the_gaps(tmp_path):
    path = tmp_path / "outage.duckdb"
    conn = _warehouse_with_gaps(path)
    _log(conn, "entsoe", datetime(2026, 10, 4, 18, 0))  # energy-charts: no row
    conn.close()

    result = _build(path)

    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
    assert "hour gaps are a warning" in result.stdout
    assert report.missing_marts(path) == []

    html = report.generate(out_path=tmp_path / "report.html", duckdb_path=path).read_text(
        encoding="utf-8"
    )
    assert "Missing data." in html
    assert "4 delivery hours" in html
    assert "energy-charts.info, the fallback source, was not available" in html

    summary = report.summary_markdown(path)
    assert "Warning: missing data." in summary
    assert "energy-charts.info, the fallback source" in summary


def test_report_without_gaps_has_no_warning(built_sample_warehouse, tmp_path):
    html = report.generate(
        out_path=tmp_path / "report.html", duckdb_path=built_sample_warehouse
    ).read_text(encoding="utf-8")
    assert 'class="data-warning"' not in html
    assert "Warning: missing data." not in report.summary_markdown(built_sample_warehouse)


def test_optional_energycharts_failure_does_not_fail_the_load(capsys):
    assert cli.blocking_failures(["energycharts"], ["energycharts"]) == []
    assert "::warning::energycharts failed" in capsys.readouterr().out


def test_a_failed_primary_source_still_fails_the_load():
    # The published report must never be built without ENTSO-E.
    assert cli.blocking_failures(["entsoe"], ["energycharts"]) == ["entsoe"]
    assert cli.blocking_failures(["entsoe", "energycharts"], ["energycharts"]) == ["entsoe"]


def test_without_optional_sources_every_failure_fails_the_load():
    # The ingest workflow passes no --optional-sources: its run stays red.
    assert cli.blocking_failures(["energycharts"], []) == ["energycharts"]
