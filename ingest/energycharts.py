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

    Hours with incomplete coverage are dropped (INC-007): a mean over 3 of 4
    quarters biases the hour, so a quarter-era hour must end at :45. A lone
    :00 point counts as complete only next to other single-point hours
    (hourly-era data); isolated single points are treated as partial.
    """
    seconds = payload.get("unix_seconds", [])
    prices = payload.get("price", [])
    rows = []
    for sec, price in zip(seconds, prices, strict=False):
        if price is None:
            continue
        ts = datetime.fromtimestamp(sec, tz=timezone.utc)
        rows.append(
            {
                "hour_utc": ts.replace(minute=0, second=0, tzinfo=None),
                "minute": ts.minute + ts.second / 60,
                "price_eur_mwh": float(price),
            }
        )
    df = pd.DataFrame(rows, columns=["hour_utc", "minute", "price_eur_mwh"])

    counts = df.groupby("hour_utc")["price_eur_mwh"].transform("size")
    last_minute = df.groupby("hour_utc")["minute"].transform("max")
    multi_point_complete = (counts >= 2) & (last_minute >= 45)

    # A lone :00 point is complete only in an hourly-era payload. The era is
    # read from the nearest *published* hours on either side (gaps from null
    # hours must not terminate the lookup): if either neighbour carries
    # multiple MTUs, the lone point is a partial hour and is dropped.
    hour_counts = df.groupby("hour_utc")["price_eur_mwh"].size()
    drop_lone = set()
    for i, hour in enumerate(hour_counts.index[hour_counts == 1]):
        prev_count = hour_counts.iloc[i - 1] if i > 0 else 1
        next_count = hour_counts.iloc[i + 1] if i + 1 < len(hour_counts) else 1
        if prev_count >= 2 or next_count >= 2:
            drop_lone.add(hour)

    keep_lone = (counts == 1) & (~df["hour_utc"].isin(drop_lone))
    full = df[multi_point_complete | keep_lone]
    return full.groupby("hour_utc", as_index=False)["price_eur_mwh"].mean()
