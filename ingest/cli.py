import argparse
import time
from datetime import datetime, timedelta

from . import db, energycharts, entsoe, knmi, report, sample
from .config import settings

BACKFILL_CHUNK_DAYS = 30
BACKFILL_PAUSE_SECONDS = 1.1


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
) -> None:
    conn = db.connect()
    now = datetime.utcnow()

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
            _load_energycharts_window(conn, backfill_start, end)
        if "knmi" in sources:
            _load_knmi(conn, backfill_start, end)
        conn.close()
        return

    if "entsoe" in sources:
        if not settings.entsoe_token:
            print("entsoe: skipped, ENTSOE_TOKEN not set")
        else:
            wm = db.watermark(conn, "entsoe")
            start = (
                (wm - timedelta(days=settings.lookback_days)) if wm else now - timedelta(days=30)
            )
            _load_entsoe_window(conn, start, now)

    if "energycharts" in sources:
        wm = db.watermark(conn, "energycharts")
        start = (wm - timedelta(days=settings.lookback_days)) if wm else now - timedelta(days=30)
        _load_energycharts_window(conn, start, now)

    if "knmi" in sources:
        _load_knmi(conn, now - timedelta(days=400), now)

    conn.close()


def export_marts() -> None:
    conn = db.connect()
    out = settings.root / "exports"
    out.mkdir(exist_ok=True)
    for table in ("fct_hourly_price_weather", "mart_daily_summary"):
        df = conn.execute(f"select * from main.{table}").fetchdf()
        path = out / f"{table}.parquet"
        df.to_parquet(path, index=False)
        print(f"exported {path.name} ({len(df)} rows)")
    conn.close()


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
        default="entsoe,energycharts,knmi",
        help="comma-separated subset of entsoe,energycharts,knmi",
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
        load_live(
            [s.strip() for s in args.sources.split(",") if s.strip()], backfill_start, backfill_end
        )
    elif args.command == "export":
        export_marts()
    elif args.command == "report":
        print(f"report written to {report.generate()}")


if __name__ == "__main__":
    main()
