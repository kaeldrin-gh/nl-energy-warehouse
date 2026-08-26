"""Open-Meteo historical weather (ERA5 reanalysis), De Bilt grid cell.

Keyless interim weather source while the KNMI Data Platform migration is
pending (INC-006): the archive API needs no account. Units are converted to
the warehouse contract on arrival - wind km/h -> m/s, shortwave radiation
W/m2 -> J/m2 per hour - so the marts need no source-specific knowledge.

https://open-meteo.com/en/docs/historical-weather-api
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from .http import get_with_retry

BASE_URL = "https://archive-api.open-meteo.com/v1/archive"

# De Bilt, KNMI station 260's location.
LATITUDE = 52.10
LONGITUDE = 5.18
STATION = 0  # sentinel: reanalysis grid cell, not a KNMI station

AMS = ZoneInfo("Europe/Amsterdam")

# km/h -> m/s, W/m2 averaged over the hour -> J/m2.
KM_H_TO_MS = 1.0 / 3.6
W_M2_TO_J_M2 = 3600.0


def fetch_hourly(start_date: str, end_date: str, timeout: int = 60) -> pd.DataFrame:
    """Fetch hourly weather for [start_date, end_date] as YYYY-MM-DD strings."""
    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "start_date": start_date,
        "end_date": end_date,
        "hourly": "temperature_2m,wind_speed_10m,shortwave_radiation",
        "timezone": "UTC",
    }
    resp = get_with_retry(BASE_URL, params=params, timeout=timeout)
    return parse_hourly_payload(resp.json())


def parse_hourly_payload(payload: dict) -> pd.DataFrame:
    """Convert the API payload to the warehouse weather contract.

    Open-Meteo labels are UTC hour STARTs; the KNMI-mirroring contract stores
    the hour END as an Amsterdam wall-clock label, so staging's single DST-aware
    conversion recovers the same UTC instant for both sources.
    """
    hourly = payload.get("hourly", {})
    times = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    winds = hourly.get("wind_speed_10m", [])
    radiation = hourly.get("shortwave_radiation", [])

    rows = []
    for i, time_text in enumerate(times):
        temp, wind, rad = temps[i], winds[i], radiation[i]
        if temp is None and wind is None and rad is None:
            continue
        hour_start_utc = datetime.strptime(time_text, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
        hour_end_utc = hour_start_utc + timedelta(hours=1)
        rows.append(
            {
                "station": STATION,
                # Amsterdam wall-clock hour-ending label, mirroring KNMI uurgeg
                "interval_end_local": hour_end_utc.astimezone(AMS).replace(tzinfo=None),
                "temp_c": float(temp) if temp is not None else None,
                "wind_ms": round(float(wind) * KM_H_TO_MS, 2) if wind is not None else None,
                "radiation_jm2": round(float(rad) * W_M2_TO_J_M2, 1) if rad is not None else None,
                "fetched_at": datetime.now(timezone.utc).replace(tzinfo=None),
            }
        )
    return pd.DataFrame(
        rows,
        columns=[
            "station",
            "interval_end_local",
            "temp_c",
            "wind_ms",
            "radiation_jm2",
            "fetched_at",
        ],
    ).drop_duplicates(subset="interval_end_local", keep="last")
