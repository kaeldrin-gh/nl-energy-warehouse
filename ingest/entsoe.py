from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree

import pandas as pd
import requests

BASE_URL = "https://web-api.tp.entsoe.eu/api"
NS = {"m": "urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:3"}


def fetch_day_ahead_prices(token: str, bidding_zone: str, start_utc: datetime, end_utc: datetime,
                            timeout: int = 60) -> pd.DataFrame:
    params = {
        "securityToken": token,
        "documentType": "A44",
        "in_Domain": bidding_zone,
        "out_Domain": bidding_zone,
        "periodStart": start_utc.strftime("%Y%m%d%H%M"),
        "periodEnd": end_utc.strftime("%Y%m%d%H%M"),
    }
    resp = requests.get(BASE_URL, params=params, timeout=timeout)
    resp.raise_for_status()
    return parse_price_xml(resp.content)


def parse_price_xml(content: bytes) -> pd.DataFrame:
    root = ElementTree.fromstring(content)
    rows = []
    for series in root.findall(".//m:TimeSeries", NS):
        period = series.find("m:Period", NS)
        if period is None:
            continue
        resolution = period.findtext("m:resolution", namespaces=NS) or "PT60M"
        step = timedelta(minutes=15 if resolution == "PT15M" else 60)
        start_text = period.findtext("m:timeInterval/m:start", namespaces=NS)
        if start_text is None:
            continue
        start = datetime.strptime(start_text, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
        for point in period.findall("m:Point", NS):
            position = int(point.findtext("m:position", namespaces=NS))
            price_text = point.findtext("m:price.amount", namespaces=NS)
            if price_text is None:
                continue
            hour_utc = (start + step * (position - 1)).replace(tzinfo=None)
            rows.append({"hour_utc": hour_utc, "price_eur_mwh": float(price_text)})
    return pd.DataFrame(rows, columns=["hour_utc", "price_eur_mwh"])
