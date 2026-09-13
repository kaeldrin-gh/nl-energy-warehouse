"""INC-010 retry: only a sole cross-source alignment failure gets a second pass."""

import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from ingest import cli


def write_run_results(path: Path, statuses: dict[str, str]) -> Path:
    payload = {
        "results": [{"unique_id": node, "status": status} for node, status in statuses.items()]
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def completed(returncode: int, stdout: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["dbt"], returncode=returncode, stdout=stdout)


def test_failed_node_ids_reads_fail_and_error(tmp_path):
    path = write_run_results(
        tmp_path / "run_results.json",
        {
            "test.nl_energy.assert_cross_source_alignment": "fail",
            "model.nl_energy.fct_hourly_price_weather": "success",
        },
    )
    assert cli.failed_node_ids(path) == ["test.nl_energy.assert_cross_source_alignment"]


def test_failed_node_ids_missing_file_is_empty(tmp_path):
    assert cli.failed_node_ids(tmp_path / "missing.json") == []


def test_retry_only_when_alignment_is_the_only_failure():
    assert cli.is_transient_alignment_failure(["test.nl_energy.assert_cross_source_alignment"])
    assert not cli.is_transient_alignment_failure(
        [
            "test.nl_energy.assert_cross_source_alignment",
            "test.nl_energy.assert_price_sanity",
        ]
    )
    assert not cli.is_transient_alignment_failure(["model.nl_energy.mart_daily_summary"])
    assert not cli.is_transient_alignment_failure([])


def test_retry_refetches_the_compared_window_and_succeeds(monkeypatch):
    builds = [completed(1), completed(0, "Done. PASS=32")]
    calls = []

    monkeypatch.setattr(cli, "_run_dbt_build", lambda: builds.pop(0))
    monkeypatch.setattr(
        cli,
        "failed_node_ids",
        lambda path=None: ["test.nl_energy.assert_cross_source_alignment"],
    )
    monkeypatch.setattr(
        cli,
        "load_live",
        lambda sources, backfill_start=None, backfill_end=None: (
            calls.append((sources, backfill_start)) or []
        ),
    )

    before = datetime.utcnow()
    cli.build_with_alignment_retry()
    after = datetime.utcnow()

    assert not builds
    assert len(calls) == 1
    sources, start = calls[0]
    assert sources == ["entsoe", "energycharts"]
    assert before - timedelta(days=32) <= start <= after - timedelta(days=30)


def test_model_error_is_fatal_without_refetch(monkeypatch):
    monkeypatch.setattr(cli, "_run_dbt_build", lambda: completed(1))
    monkeypatch.setattr(
        cli, "failed_node_ids", lambda path=None: ["model.nl_energy.mart_daily_summary"]
    )
    monkeypatch.setattr(cli, "load_live", lambda *args, **kwargs: pytest.fail("must not refetch"))

    with pytest.raises(SystemExit):
        cli.build_with_alignment_retry()


def test_second_alignment_failure_is_fatal(monkeypatch):
    builds = [completed(1), completed(1)]
    calls = []
    monkeypatch.setattr(cli, "_run_dbt_build", lambda: builds.pop(0))
    monkeypatch.setattr(
        cli,
        "failed_node_ids",
        lambda path=None: ["test.nl_energy.assert_cross_source_alignment"],
    )
    monkeypatch.setattr(cli, "load_live", lambda *args, **kwargs: calls.append(1) or [])

    with pytest.raises(SystemExit):
        cli.build_with_alignment_retry()
    assert calls
