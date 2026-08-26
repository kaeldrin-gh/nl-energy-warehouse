from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

AMS = "Europe/Amsterdam"


def generate(sample_days: int) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(42)
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0, tzinfo=None)
    start = now - timedelta(days=sample_days)
    hours_utc = pd.date_range(start=start, end=now - timedelta(hours=1), freq="h")

    hour_of_day = hours_utc.hour.to_numpy()
    day_of_year = hours_utc.dayofyear.to_numpy()

    seasonal = 25.0 + 12.0 * np.cos(2 * np.pi * (day_of_year - 15) / 365.25)
    diurnal_price = 8.0 * np.sin(2 * np.pi * (hour_of_day - 6) / 24.0)
    evening_spike = np.where((hour_of_day >= 17) & (hour_of_day <= 20), 18.0, 0.0)
    noise = rng.normal(0, 6.0, len(hours_utc))
    price = seasonal + diurnal_price + evening_spike + noise
    negative_hours = rng.choice(len(hours_utc), size=max(len(hours_utc) // 200, 3), replace=False)
    price[negative_hours] = rng.uniform(-60, -5, len(negative_hours))
    price = np.round(price, 2)

    entsoe = pd.DataFrame(
        {
            "hour_utc": hours_utc,
            "price_eur_mwh": price,
            "fetched_at": now.replace(tzinfo=None),
        }
    )

    charts_noise = rng.normal(0, 0.15, len(hours_utc))
    charts = pd.DataFrame(
        {
            "hour_utc": hours_utc,
            "price_eur_mwh": np.round(price + charts_noise, 2),
            "fetched_at": now.replace(tzinfo=None),
        }
    )

    seasonal_temp = 11.5 + 9.0 * np.sin(2 * np.pi * (day_of_year - 105) / 365.25)
    diurnal_temp = 3.5 * np.sin(2 * np.pi * (hour_of_day - 9) / 24.0)
    temp = np.round(seasonal_temp + diurnal_temp + rng.normal(0, 1.5, len(hours_utc)), 1)
    wind = np.round(np.clip(rng.lognormal(1.3, 0.5, len(hours_utc)), 0.2, 18.0), 1)
    daylight = np.clip(np.sin(np.pi * (hour_of_day - 6) / 13.0), 0, None)
    cloud = rng.uniform(0.3, 1.0, len(hours_utc))
    radiation = np.round(daylight * cloud * 3_200_000.0, 0)

    local_end = hours_utc.tz_localize("UTC").tz_convert(AMS).tz_localize(None) + pd.Timedelta(
        hours=1
    )

    knmi = pd.DataFrame(
        {
            "station": 260,
            "interval_end_local": local_end,
            "temp_c": temp,
            "wind_ms": wind,
            "radiation_jm2": radiation,
            "fetched_at": now.replace(tzinfo=None),
        }
    ).drop_duplicates(subset=["station", "interval_end_local"], keep="first")

    return {"entsoe_prices": entsoe, "energycharts_prices": charts, "knmi_weather": knmi}
