"""Report generation tests: sections present, weekly math consistent."""

import json
import re
import sys

import pandas as pd
import pytest
from conftest import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT))

from ingest import db, report  # noqa: E402


@pytest.fixture()
def report_path(built_sample_warehouse, tmp_path):
    return report.generate(out_path=tmp_path / "report.html", duckdb_path=built_sample_warehouse)


def test_report_contains_all_sections(report_path):
    html = report_path.read_text(encoding="utf-8")

    for fragment in (
        "This week in the market",
        "Pipeline health",
        "Headline stats",
        "Market calendar",
        "generated",
        "Price fingerprint",
        'id="report-data"',
        "@observablehq/plot",
        "Part of a three-project portfolio",
        "databricks-energy-quality",
    ):
        assert fragment in html, f"report is missing section: {fragment}"


def test_report_week_metrics_consistent(built_sample_warehouse):
    daily, hourly, _ = report._load_data(built_sample_warehouse)
    metrics, this_week, hours_this, prev = report._week_metrics(daily, hourly)

    assert len(this_week) == metrics["days_covered"]
    assert 0 < metrics["days_covered"] <= 7
    assert metrics["avg_this"] > 0
    assert metrics["neg_hours_this"] >= 0
    assert metrics["min_hourly"] <= metrics["avg_this"] <= metrics["max_hourly"]
    # the cheapest and priciest hours must come from inside this week's window
    assert hours_this["hour_local"].min() <= metrics["min_when"] <= hours_this["hour_local"].max()
    assert metrics["min_hourly"] <= metrics["max_hourly"]


def test_summary_markdown_handles_missing_marts(tmp_path):
    md = report.summary_markdown(tmp_path / "empty.duckdb")

    assert "Marts are not built" in md


def test_summary_markdown_has_windows_and_quality(built_sample_warehouse):
    md = report.summary_markdown(built_sample_warehouse)

    assert md.startswith("## NL energy warehouse")
    for fragment in ("| Last 24 h |", "| Last 7 days |", "| Last 30 days |"):
        assert fragment in md
    assert "Max cross-source diff" in md
    assert "| Source | Last run |" in md


def test_summary_and_report_include_news_when_present(built_sample_warehouse, tmp_path):
    conn = db.connect(built_sample_warehouse)
    conn.execute(
        "insert into raw.news_headlines values "
        "('example.nl', 'https://x/1', 'Windpark op zee', '2026-09-19 08:00:00', "
        "'policy', 0.9, 'm', '2026-09-20 08:00:00')"
    )
    conn.close()

    summary = report.summary_markdown(built_sample_warehouse)
    assert "### News context" in summary
    assert "| Energy topic (latest 1 headlines) | Headlines |" in summary
    assert "| policy | 1 |" in summary
    assert "0 of 1 headlines were general news and filtered out." in summary

    html = report.generate(out_path=tmp_path / "report.html", duckdb_path=built_sample_warehouse)
    assert "News context" in html.read_text(encoding="utf-8")


def test_report_tables_are_formatted_for_readers(built_sample_warehouse, tmp_path):
    """No raw pandas output on the public page: NaT, microseconds, float counts."""
    conn = db.connect(built_sample_warehouse)
    # A news run logs no data window; a live run logs microsecond timestamps.
    conn.execute(
        "insert into raw.ingest_log values ('news', '2026-09-26 17:56:58.940525', null, null, 100)"
    )
    conn.close()

    out = report.generate(out_path=tmp_path / "report.html", duckdb_path=built_sample_warehouse)
    health = out.read_text(encoding="utf-8").split("<h2>Pipeline health</h2>")[1]
    health = health.split("</table>")[0]

    assert "<td>news</td><td>2026-09-26 17:56</td><td>–</td><td>100</td><td>1</td>" in health

    assert "NaT" not in health and "None" not in health
    assert not re.search(r"\d{2}:\d{2}:\d{2}\.\d+", health), "timestamps carry microseconds"
    assert not re.search(r"<td>\d[\d,]*\.0</td>", health), "counts rendered as floats"


def test_timestamp_cells_drop_microseconds_and_show_a_dash_when_missing():
    assert report._ts(pd.Timestamp("2026-09-26 17:56:51.422406")) == "2026-09-26 17:56"
    assert report._ts(pd.NaT) == "–"
    assert report._ts(None) == "–"


def test_report_month_heading_matches_rows(report_path):
    html = report_path.read_text(encoding="utf-8")
    heading = re.search(r"Market calendar \(last (\d+) months\)", html)
    table = html.split(heading.group(0))[1].split("</table>")[0]

    assert int(heading.group(1)) == table.count("<tr>") - 1


def _embedded_data(html: str) -> dict:
    raw = html.split('<script type="application/json" id="report-data">')[1].split("</script>")[0]
    return json.loads(raw)


def test_embedded_chart_data_matches_the_marts(built_sample_warehouse, report_path):
    """The browser draws from this JSON, so it has to agree with the tables beside it."""
    data = _embedded_data(report_path.read_text(encoding="utf-8"))
    daily, hourly, _ = report._load_data(built_sample_warehouse)

    assert len(data["fingerprint"]["rows"]) == len(hourly)
    assert {hour for _, hour, _ in data["fingerprint"]["rows"]} <= set(range(24))
    assert len(data["week"]["rows"]) == 168
    assert sum(r["current"] is not None for r in data["week"]["rows"]) > 0
    assert sum(m["negative_hours"] for m in data["monthly"]) == daily["negative_price_hours"].sum()
    assert {p["kind"] for p in data["profile"]} <= {"weekday", "weekend"}
    assert all(set(r) == {"date", "price", "wind"} for r in data["wind"]["rows"])


def test_embedded_json_cannot_close_the_script_tag():
    assert "</" not in report._json_script({"title": "</script><b>x</b>"})
    assert json.loads(report._json_script({"t": "</script>"})) == {"t": "</script>"}


def test_money_and_missing_weather_are_formatted_for_readers():
    assert report._eur(-0.04) == "−€0.04"
    assert report._eur(163.931) == "€163.93"
    assert report._one_decimal(float("nan")) == "–"
    assert report._one_decimal(15.24) == "15.2"


def test_missing_marts_is_empty_after_a_full_build(built_sample_warehouse):
    assert report.missing_marts(built_sample_warehouse) == []


def test_missing_marts_names_the_marts_a_failed_build_skipped(tmp_path):
    # A warehouse with only the raw schema: what a run sees when dbt skipped
    # the marts after a failed test.
    assert report.missing_marts(tmp_path / "raw_only.duckdb") == [
        "mart_daily_summary",
        "fct_hourly_price_weather",
    ]
