from datetime import datetime, timezone

import pandas as pd
import requests

BASE_URL = "https://api.energy-charts.info/price"


def fetch_day_ahead_prices(bidding_zone: str, start_utc: datetime, end_utc: datetime,
                           timeout: int = 60) -> pd.DataFrame:
    params = {
        "bzn": bidding_zone,
        "start": int(start_utc.replace(tzinfo=timezone.utc).timestamp()),
        "end": int(end_utc.replace(tzinfo=timezone.utc).timestamp()),
    }
    resp = requests.get(BASE_URL, params=params, timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()

    seconds = payload.get("unix_seconds", [])
    prices = payload.get("price", [])
    rows = []
    for sec, price in zip(seconds, prices):
        if price is None:
            continue
        hour_utc = datetime.fromtimestamp(sec, tz=timezone.utc).replace(minute=0, second=0, tzinfo=None)
        rows.append({"hour_utc": hour_utc, "price_eur_mwh": float(price)})
    df = pd.DataFrame(rows, columns=["hour_utc", "price_eur_mwh"])
    return df.drop_duplicates(subset="hour_utc", keep="last")
