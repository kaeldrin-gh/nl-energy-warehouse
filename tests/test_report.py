"""Report generation tests: sections present, weekly math consistent."""

import sys

import pytest
from conftest import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT))

from ingest import report  # noqa: E402


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
        "data:image/png",
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
