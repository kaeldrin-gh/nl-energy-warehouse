from datetime import datetime, timezone

import pandas as pd

from .http import get_with_retry

BASE_URL = "https://api.energy-charts.info/price"

# energy-charts.info uses its own bidding-zone ids, not ENTO-E EIC codes.
ZONE_MAP = {
    "10YNL----------L": "NL",
}


def fetch_day_ahead_prices(
    bidding_zone: str, start_utc: datetime, end_utc: datetime, timeout: int = 60
) -> pd.DataFrame:
    params = {
        "bzn": ZONE_MAP.get(bidding_zone, bidding_zone),
        "start": int(start_utc.replace(tzinfo=timezone.utc).timestamp()),
        "end": int(end_utc.replace(tzinfo=timezone.utc).timestamp()),
    }
    resp = get_with_retry(BASE_URL, params=params, timeout=timeout)
    return parse_price_payload(resp.json())


def parse_price_payload(payload: dict) -> pd.DataFrame:
    """Parse an energy-charts price response into hourly UTC rows.

    Day-ahead market units are 15 minutes since the 2025 EU coupling switch,
    but this warehouse is hourly-grained (raw tables keyed on hour_utc), so
    sub-hourly points are averaged into their containing hour. Nulls (hours
    the source has not published) are dropped and left to revision-aware
    refetches rather than guessed.
    """
    seconds = payload.get("unix_seconds", [])
    prices = payload.get("price", [])
    rows = []
    for sec, price in zip(seconds, prices, strict=False):
        if price is None:
            continue
        hour_utc = datetime.fromtimestamp(sec, tz=timezone.utc).replace(
            minute=0, second=0, tzinfo=None
        )
        rows.append({"hour_utc": hour_utc, "price_eur_mwh": float(price)})
    df = pd.DataFrame(rows, columns=["hour_utc", "price_eur_mwh"])
    if df.empty:
        return df
    return df.groupby("hour_utc", as_index=False)["price_eur_mwh"].mean()
