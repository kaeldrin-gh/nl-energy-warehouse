"""Today's prices must arrive: a check on which hours exist, not on fetch time.

On 10 Oct 2026 both price sources answered, so source freshness passed, but
no hour of 10 Oct was in the marts. Day-ahead prices for a day are published
on the day before, so all hours of today (Europe/Amsterdam) are always due.
"""

import shutil
import sys
from datetime import UTC, datetime, timedelta

import pandas as pd

from tests.conftest import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT))

from ingest import cli, db, report  # noqa: E402


def test_a_normal_day_has_24_due_hours():
    due = report.due_hours(datetime(2026, 10, 10, 18, 0, tzinfo=UTC))
    assert len(due) == 24
    assert due[0] == pd.Timestamp("2026-10-09 22:00")  # 00:00 CEST
    assert due[-1] == pd.Timestamp("2026-10-10 21:00")  # 23:00 CEST


def test_dst_change_days_have_23_and_25_due_hours():
    assert len(report.due_hours(datetime(2026, 3, 29, 12, tzinfo=UTC))) == 23
    assert len(report.due_hours(datetime(2026, 10, 25, 12, tzinfo=UTC))) == 25


def test_shortly_after_local_midnight_the_new_day_is_due():
    # 22:30 UTC on 10 Oct is 00:30 on 11 Oct in Amsterdam.
    due = report.due_hours(datetime(2026, 10, 10, 22, 30, tzinfo=UTC))
    assert due[0] == pd.Timestamp("2026-10-10 22:00")


def test_missing_due_hours_finds_a_whole_missing_day():
    # 10 Oct 2026: the marts ended at 9 Oct 21:00 UTC.
    now = datetime(2026, 10, 10, 18, 0, tzinfo=UTC)
    hourly = pd.DataFrame({"hour_utc": pd.date_range("2026-10-01", "2026-10-09 21:00", freq="h")})
    assert len(report.missing_due_hours(hourly, now)) == 24


def test_missing_due_hours_is_empty_when_today_is_complete():
    now = datetime(2026, 10, 10, 18, 0, tzinfo=UTC)
    hourly = pd.DataFrame({"hour_utc": pd.date_range("2026-10-01", "2026-10-10 21:00", freq="h")})
    assert report.missing_due_hours(hourly, now).empty


def test_check_due_passes_for_a_complete_day_and_fails_for_a_missing_one(
    built_sample_warehouse,
):
    # The sample covers the last 30 days up to one hour ago.
    yesterday = datetime.now(UTC) - timedelta(days=1)
    tomorrow = datetime.now(UTC) + timedelta(days=1)
    assert cli.check_due(built_sample_warehouse, now=yesterday) == []
    assert len(cli.check_due(built_sample_warehouse, now=tomorrow)) >= 23


def test_report_warns_only_for_a_live_warehouse(built_sample_warehouse, tmp_path):
    # The sample always ends one hour ago, so some of today is missing.
    sample_html = report.generate(
        out_path=tmp_path / "sample.html", duckdb_path=built_sample_warehouse
    ).read_text(encoding="utf-8")
    assert "Prices for today are missing." not in sample_html

    # Same file name: DuckDB views refer to the database by its file name.
    (tmp_path / "live").mkdir()
    live = tmp_path / "live" / built_sample_warehouse.name
    shutil.copy(built_sample_warehouse, live)
    conn = db.connect(live)
    conn.execute("INSERT INTO raw.ingest_log VALUES ('entsoe', now(), NULL, NULL, 0)")
    conn.close()

    html = report.generate(out_path=tmp_path / "live.html", duckdb_path=live).read_text(
        encoding="utf-8"
    )
    assert "Prices for today are missing." in html
    assert "Warning: prices for today are missing." in report.summary_markdown(live)
