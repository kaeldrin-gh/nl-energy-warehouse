import argparse
from datetime import datetime, timedelta

from . import db, energycharts, entsoe, knmi, sample
from .config import settings


def load_sample() -> None:
    conn = db.connect()
    frames = sample.generate(settings.sample_days)
    for table, df in frames.items():
        n = db.upsert(conn, table, df)
        db.log_run(conn, f"sample:{table}", None, None, n)
        print(f"sample:{table}: wrote {n} rows")
    conn.close()


def load_live(sources: list[str]) -> None:
    conn = db.connect()
    now = datetime.utcnow()

    if "entsoe" in sources:
        if not settings.entsoe_token:
            print("entsoe: skipped, ENTSOE_TOKEN not set")
        else:
            wm = db.watermark(conn, "entsoe")
            start = (wm - timedelta(days=settings.lookback_days)) if wm else now - timedelta(days=30)
            df = entsoe.fetch_day_ahead_prices(
                settings.entsoe_token, settings.nl_bidding_zone, start, now,
                timeout=settings.request_timeout,
            )
            n = db.upsert(conn, "entsoe_prices", df)
            db.log_run(conn, "entsoe", start, now, n)
            print(f"entsoe: wrote {n} rows for window {start} .. {now}")

    if "energycharts" in sources:
        wm = db.watermark(conn, "energycharts")
        start = (wm - timedelta(days=settings.lookback_days)) if wm else now - timedelta(days=30)
        df = energycharts.fetch_day_ahead_prices(settings.nl_bidding_zone, start, now,
                                                 timeout=settings.request_timeout)
        n = db.upsert(conn, "energycharts_prices", df)
        db.log_run(conn, "energycharts", start, now, n)
        print(f"energycharts: wrote {n} rows for window {start} .. {now}")

    if "knmi" in sources:
        this_year = now.year
        df = knmi.fetch_hourly(station=260, start_year=this_year - 1, end_year=this_year,
                               timeout=settings.request_timeout)
        n = db.upsert(conn, "knmi_weather", df)
        db.log_run(conn, "knmi", df["interval_end_local"].min() if n else None,
                   df["interval_end_local"].max() if n else None, n)
        print(f"knmi: wrote {n} rows")

    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Load raw data into the DuckDB warehouse")
    sub = parser.add_subparsers(dest="command", required=True)

    load = sub.add_parser("load", help="load data")
    load.add_argument("--sample", action="store_true",
                      help="load deterministic sample data instead of live sources")
    load.add_argument("--sources", default="entsoe,energycharts,knmi",
                      help="comma-separated subset of entsoe,energycharts,knmi")

    args = parser.parse_args()

    if args.command == "load":
        if args.sample:
            load_sample()
        else:
            load_live([s.strip() for s in args.sources.split(",") if s.strip()])


if __name__ == "__main__":
    main()
