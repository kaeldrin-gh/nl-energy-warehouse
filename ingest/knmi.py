import io
import zipfile
from datetime import datetime, timezone

import pandas as pd

from .http import get_with_retry

CDN_URL = "https://cdn.knmi.nl/knmi/json/page/weer/waarnemingen/uurgeg_{station}_{decade}.zip"

VARIABLE_MAP = {
    "T": "temp_c",
    "FH": "wind_ms",
    "Q": "radiation_jm2",
}


def decade_for(year: int) -> str:
    return f"{year - year % 10}-{year - year % 10 + 9}"


def fetch_hourly(station: int, start_year: int, end_year: int, timeout: int = 120) -> pd.DataFrame:
    frames = []
    for decade in sorted({decade_for(y) for y in (start_year, end_year)}):
        url = CDN_URL.format(station=station, decade=decade)
        resp = get_with_retry(url, timeout=timeout)
        frames.append(parse_uurgeg_zip(resp.content))
    df = pd.concat(frames, ignore_index=True)
    df = df.drop_duplicates(subset=["station", "interval_end_local"], keep="last")
    return df


def parse_uurgeg_zip(content: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        name = zf.namelist()[0]
        text = zf.read(name).decode("utf-8", errors="replace")
    return parse_uurgeg_text(text)


def parse_uurgeg_text(text: str) -> pd.DataFrame:
    lines = text.splitlines()
    header_idx = max(i for i, line in enumerate(lines)
                     if line.startswith("#") and "STN" in line)
    header = [c.strip() for c in lines[header_idx].lstrip("# ").split(",")]
    data = "\n".join(lines[header_idx + 1:])
    df = pd.read_csv(io.StringIO(data), names=header, na_values=["", " "], skipinitialspace=True)
    df.columns = [c.strip() for c in df.columns]

    out = pd.DataFrame()
    out["station"] = df["STN"].astype(int)
    dates = pd.to_datetime(df["YYYYMMDD"].astype(int).astype(str), format="%Y%m%d")
    hours = df["H"].astype(int)
    out["interval_end_local"] = dates + pd.to_timedelta(hours, unit="h")

    renames = {k: v for k, v in VARIABLE_MAP.items() if k in df.columns}
    for src, dst in renames.items():
        out[dst] = pd.to_numeric(df[src], errors="coerce")
    if "temp_c" in out:
        out["temp_c"] = out["temp_c"] / 10.0
    if "wind_ms" in out:
        out["wind_ms"] = out["wind_ms"] / 10.0
    if "radiation_jm2" in out:
        out["radiation_jm2"] = out["radiation_jm2"] * 10_000.0
        out.loc[out["radiation_jm2"] < 0, "radiation_jm2"] = 0.0

    out["fetched_at"] = datetime.now(timezone.utc).replace(tzinfo=None)
    cols = ["station", "interval_end_local", "temp_c", "wind_ms", "radiation_jm2", "fetched_at"]
    return out[[c for c in cols if c in out.columns]]
