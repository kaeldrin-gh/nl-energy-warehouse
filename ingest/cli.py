import argparse
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from . import bi_queries, db, energycharts, entsoe, knmi, openmeteo, report, sample
from .config import settings

BACKFILL_CHUNK_DAYS = 30
BACKFILL_PAUSE_SECONDS = 5.0


def load_sample() -> None:
    conn = db.connect()
    frames = sample.generate(settings.sample_days)
    for table, df in frames.items():
        n = db.upsert(conn, table, df)
        db.log_run(conn, f"sample:{table}", None, None, n)
        print(f"sample:{table}: wrote {n} rows")
    conn.close()


def _load_entsoe_window(conn, start: datetime, end: datetime) -> None:
    df = entsoe.fetch_day_ahead_prices(
        settings.entsoe_token,
        settings.nl_bidding_zone,
        start,
        end,
        timeout=settings.request_timeout,
    )
    if not df.empty:
        df["fetched_at"] = datetime.utcnow()
    n = db.upsert(conn, "entsoe_prices", df)
    db.log_run(conn, "entsoe", start, end, n)
    print(f"entsoe: wrote {n} rows for {start:%Y-%m-%d} .. {end:%Y-%m-%d}")


def _load_energycharts_window(conn, start: datetime, end: datetime) -> None:
    df = energycharts.fetch_day_ahead_prices(
        settings.nl_bidding_zone, start, end, timeout=settings.request_timeout
    )
    if not df.empty:
        df["fetched_at"] = datetime.utcnow()
    n = db.upsert(conn, "energycharts_prices", df)
    db.log_run(conn, "energycharts", start, end, n)
    print(f"energycharts: wrote {n} rows for {start:%Y-%m-%d} .. {end:%Y-%m-%d}")


def _load_openmeteo(conn, start: datetime, end: datetime) -> None:
    df = openmeteo.fetch_hourly(
        start_date=start.strftime("%Y-%m-%d"),
        end_date=end.strftime("%Y-%m-%d"),
        timeout=settings.request_timeout,
    )
    n = db.upsert(conn, "openmeteo_weather", df)
    db.log_run(
        conn,
        "openmeteo",
        df["interval_end_local"].min() if n else None,
        df["interval_end_local"].max() if n else None,
        n,
    )
    print(f"openmeteo: wrote {n} rows for {start:%Y-%m-%d} .. {end:%Y-%m-%d}")


def _load_knmi(conn, start: datetime, end: datetime) -> None:
    df = knmi.fetch_hourly(
        station=260, start_year=start.year, end_year=end.year, timeout=settings.request_timeout
    )
    df = df[
        (df["interval_end_local"] >= start - timedelta(days=1))
        & (df["interval_end_local"] <= end + timedelta(days=1))
    ]
    n = db.upsert(conn, "knmi_weather", df)
    db.log_run(
        conn,
        "knmi",
        df["interval_end_local"].min() if n else None,
        df["interval_end_local"].max() if n else None,
        n,
    )
    print(f"knmi: wrote {n} rows")


def load_live(
    sources: list[str], backfill_start: datetime | None = None, backfill_end: datetime | None = None
) -> list[str]:
    """Load the requested live sources. Returns the names of sources that failed.

    Sources are isolated: one source being down (503s, timeouts) must not stop
    the others, and must not prevent the downstream build/export from shipping
    whatever data *was* available (provenance flags mark the gaps). Callers
    decide whether failures are fatal - the cron treats them as such.
    """
    conn = db.connect()
    now = datetime.utcnow()
    failures: list[str] = []

    if backfill_start is not None:
        end = backfill_end or now
        if "entsoe" in sources:
            if not settings.entsoe_token:
                print("entsoe: skipped, ENTSOE_TOKEN not set")
            else:
                cursor = backfill_start
                while cursor < end:
                    chunk_end = min(cursor + timedelta(days=BACKFILL_CHUNK_DAYS), end)
                    _load_entsoe_window(conn, cursor, chunk_end)
                    cursor = chunk_end
                    time.sleep(BACKFILL_PAUSE_SECONDS)
        if "energycharts" in sources:
            # Chunked like ENTSO-E: the API served a transiently wrong hour on a
            # multi-year single request (INC-007); modest windows keep every
            # refetch re-validating a small range.
            cursor = backfill_start
            while cursor < end:
                chunk_end = min(cursor + timedelta(days=BACKFILL_CHUNK_DAYS), end)
                _load_energycharts_window(conn, cursor, chunk_end)
                cursor = chunk_end
                time.sleep(BACKFILL_PAUSE_SECONDS)
        if "openmeteo" in sources:
            # Archive API handles multi-year windows; chunk per year to keep
            # payloads modest and resumable.
            cursor = datetime(backfill_start.year, 1, 1)
            while cursor <= end:
                year_end = min(datetime(cursor.year, 12, 31, 23, 0), end)
                _load_openmeteo(conn, max(cursor, backfill_start), year_end)
                cursor = datetime(cursor.year + 1, 1, 1)
                time.sleep(BACKFILL_PAUSE_SECONDS)
        if "knmi" in sources:
            _load_knmi(conn, backfill_start, end)
        conn.close()
        return

    if "entsoe" in sources:
        if not settings.entsoe_token:
            print("entsoe: skipped, ENTSOE_TOKEN not set")
        else:
            try:
                wm = db.watermark(conn, "entsoe")
                start = (
                    (wm - timedelta(days=settings.lookback_days))
                    if wm
                    else now - timedelta(days=30)
                )
                _load_entsoe_window(conn, start, now)
            except Exception as error:  # isolate: one dead source must not kill the batch
                failures.append("entsoe")
                print(f"entsoe: FAILED ({error}) - continuing with remaining sources")

    if "energycharts" in sources:
        try:
            wm = db.watermark(conn, "energycharts")
            start = (
                (wm - timedelta(days=settings.lookback_days)) if wm else now - timedelta(days=30)
            )
            _load_energycharts_window(conn, start, now)
        except Exception as error:  # isolate: one dead source must not kill the batch
            failures.append("energycharts")
            print(f"energycharts: FAILED ({error}) - continuing with remaining sources")

    if "openmeteo" in sources:
        try:
            _load_openmeteo(conn, now - timedelta(days=30), now)
        except Exception as error:  # isolate: one dead source must not kill the batch
            failures.append("openmeteo")
            print(f"openmeteo: FAILED ({error}) - continuing with remaining sources")

    if "knmi" in sources:
        try:
            _load_knmi(conn, now - timedelta(days=400), now)
        except Exception as error:  # isolate: one dead source must not kill the batch
            failures.append("knmi")
            print(f"knmi: FAILED ({error}) - continuing with remaining sources")

    conn.close()
    if failures:
        print(f"load finished with failures: {', '.join(failures)}")
    return failures


def export_marts(out_dir: Path | None = None, duckdb_path: Path | None = None) -> None:
    conn = db.connect(duckdb_path)
    out = out_dir or (settings.root / "exports")
    out.mkdir(parents=True, exist_ok=True)
    for table in ("fct_hourly_price_weather", "mart_daily_summary"):
        df = conn.execute(f"select * from main.{table}").fetchdf()
        if table == "fct_hourly_price_weather" and "hour_local_label" in df.columns:
            # Nullable by design (hours without weather); keep the pandas dtype
            # stable whether or not the current warehouse has weather rows.
            df["hour_local_label"] = df["hour_local_label"].astype("Int64")
        path = out / f"{table}.parquet"
        df.to_parquet(path, index=False)
        print(f"exported {path.name} ({len(df)} rows)")
    conn.close()


def run_bi_query(name: str | None) -> None:
    blocks = bi_queries.load_blocks(settings.root / "analysis" / "bi_queries.sql")
    if name is None:
        print("available queries (python -m ingest.cli bi <key>):")
        for block in blocks:
            print(f"  {block.key:<10} {block.title}")
        return
    block = bi_queries.find_block(blocks, name)
    if block is None:
        print(f"no query matches '{name}'. available keys:")
        for b in blocks:
            print(f"  {b.key:<10} {b.title}")
        raise SystemExit(1)
    conn = db.connect()
    df = conn.execute(block.sql).fetchdf()
    conn.close()
    print(f"== {block.title}")
    print(df.to_string(index=False))


def refresh() -> None:
    """One command from stale to fresh: incremental load -> dbt build -> export -> report."""
    print("== 1/4 incremental load")
    failures = load_live(["entsoe", "energycharts", "openmeteo"], None, None)
    if failures:
        print(
            f"!! degraded: {', '.join(failures)} unavailable - building from the healthy "
            "sources; provenance flags mark the gaps"
        )
    print("== 2/4 dbt build")
    _run_dbt_build()
    print("== 3/4 export parquet")
    export_marts()
    print("== 4/4 report")
    print(f"report written to {report.generate()}")


def _run_dbt_build() -> None:
    dbt = shutil.which("dbt")
    if dbt is None:
        raise SystemExit("dbt executable not found on PATH")
    env = os.environ.copy()
    env["DUCKDB_PATH"] = str(settings.duckdb_path)
    result = subprocess.run(
        ["dbt", "build", "--project-dir", "dbt", "--profiles-dir", "dbt"],
        cwd=settings.root,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        print(result.stdout[-2000:])
        raise SystemExit(f"dbt build failed (exit {result.returncode})")
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    summary = [line for line in lines if "Done." in line]
    print(summary[-1] if summary else lines[-1])


def main() -> None:
    parser = argparse.ArgumentParser(description="Load raw data into the DuckDB warehouse")
    sub = parser.add_subparsers(dest="command", required=True)

    load = sub.add_parser("load", help="load data")
    load.add_argument(
        "--sample",
        action="store_true",
        help="load deterministic sample data instead of live sources",
    )
    load.add_argument(
        "--sources",
        default="entsoe,energycharts,openmeteo",
        help="comma-separated subset of entsoe,energycharts,openmeteo,knmi",
    )
    load.add_argument(
        "--backfill", action="store_true", help="chunked historical load; requires --from"
    )
    load.add_argument(
        "--from", dest="date_from", default=None, help="backfill start date, YYYY-MM-DD"
    )
    load.add_argument(
        "--to", dest="date_to", default=None, help="backfill end date, YYYY-MM-DD (default: now)"
    )

    sub.add_parser("export", help="export mart tables to exports/ as Parquet for BI tools")
    sub.add_parser("report", help="generate exports/report.html from the marts")
    sub.add_parser(
        "refresh",
        help="one command: incremental live load -> dbt build -> export -> report",
    )

    bi = sub.add_parser("bi", help="run analysis queries from analysis/bi_queries.sql")
    bi.add_argument(
        "name", nargs="?", default=None, help="query key (e.g. V1, headline); omit to list all"
    )

    args = parser.parse_args()

    if args.command == "load":
        if args.sample:
            load_sample()
            return
        backfill_start = None
        if args.backfill:
            if not args.date_from:
                parser.error("--backfill requires --from YYYY-MM-DD")
            backfill_start = datetime.strptime(args.date_from, "%Y-%m-%d")
        backfill_end = datetime.strptime(args.date_to, "%Y-%m-%d") if args.date_to else None
        failures = load_live(
            [s.strip() for s in args.sources.split(",") if s.strip()], backfill_start, backfill_end
        )
        if failures:
            # Non-zero exit so automation (cron, CI) treats the run as failed,
            # even though the healthy sources were still loaded.
            sys.exit(1)
    elif args.command == "export":
        export_marts()
    elif args.command == "report":
        print(f"report written to {report.generate()}")
    elif args.command == "bi":
        run_bi_query(args.name)
    elif args.command == "refresh":
        refresh()


if __name__ == "__main__":
    main()
