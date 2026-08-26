import base64
import io
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from . import db
from .config import settings


def _fig_to_b64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _daily_price_vs_temp(daily: pd.DataFrame) -> str:
    fig, ax1 = plt.subplots(figsize=(11, 4))
    ax1.plot(daily["local_date"], daily["avg_price_eur_mwh"], color="#c0392b", label="avg price")
    ax1.set_ylabel("avg price (EUR/MWh)", color="#c0392b")
    ax2 = ax1.twinx()
    ax2.plot(daily["local_date"], daily["avg_temp_c"], color="#2471a3", alpha=0.7, label="avg temp")
    ax2.set_ylabel("avg temp (C)", color="#2471a3")
    ax1.set_title("Daily average price vs temperature")
    fig.autofmt_xdate()
    return _fig_to_b64(fig)


def _hour_of_day_profile(hourly: pd.DataFrame) -> str:
    profile = hourly.groupby(hourly["hour_local"].dt.hour)["price_eur_mwh"].mean()
    fig, ax = plt.subplots(figsize=(8, 3.5))
    ax.bar(profile.index.astype(str), profile.values, color="#7d3c98")
    ax.set_title("Average price by hour of day (local)")
    ax.set_xlabel("hour")
    ax.set_ylabel("EUR/MWh")
    return _fig_to_b64(fig)


def _negative_price_hours(daily: pd.DataFrame) -> str:
    neg = daily[daily["negative_price_hours"] > 0]
    fig, ax = plt.subplots(figsize=(11, 3.2))
    ax.bar(neg["local_date"].astype(str), neg["negative_price_hours"], color="#1e8449")
    ax.set_title("Hours with negative prices per day")
    ax.set_ylabel("hours")
    if len(neg) > 40:
        ax.set_xticks([])
    fig.autofmt_xdate()
    return _fig_to_b64(fig)


def _cross_source_diff(hourly: pd.DataFrame) -> str:
    fig, ax = plt.subplots(figsize=(11, 3.2))
    ax.plot(hourly["hour_local"], hourly["price_diff_eur"], lw=0.6, color="#5d6d7e")
    ax.axhline(2.0, color="#c0392b", ls="--", lw=0.8)
    ax.axhline(-2.0, color="#c0392b", ls="--", lw=0.8)
    ax.set_title("Cross-source price difference (ENTSO-E vs energy-charts), EUR 2 test bound")
    ax.set_ylabel("EUR/MWh")
    fig.autofmt_xdate()
    return _fig_to_b64(fig)


def generate() -> Path:
    conn = db.connect()
    daily = conn.execute("select * from main.mart_daily_summary order by local_date").fetchdf()
    hourly = conn.execute("select * from main.fct_hourly_price_weather order by hour_utc").fetchdf()
    health = conn.execute("""
        select
            source,
            max(run_at) as last_run,
            max(window_end) as data_through,
            sum(rows_written) as rows_total,
            count(*) as runs
        from raw.ingest_log
        group by source
        order by source
    """).fetchdf()
    conn.close()

    corr = hourly[["price_eur_mwh", "temp_c", "wind_ms", "radiation_jm2"]].corr()
    stats = {
        "price vs temp": corr.loc["price_eur_mwh", "temp_c"],
        "price vs wind": corr.loc["price_eur_mwh", "wind_ms"],
        "price vs radiation": corr.loc["price_eur_mwh", "radiation_jm2"],
        "mean cross-source diff": hourly["price_diff_eur"].mean(),
        "hours covered": len(hourly),
    }
    stat_rows = "".join(
        f"<tr><td>{name}</td><td>{value:.3f}</td></tr>" for name, value in stats.items()
    )
    health_rows = "".join(
        f"<tr><td>{r.source}</td><td>{r.last_run}</td><td>{r.data_through}</td>"
        f"<td>{r.rows_total:,}</td><td>{r.runs}</td></tr>"
        for r in health.itertuples()
    )

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>NL energy warehouse report</title>
<style>
body {{ font-family: -apple-system, Segoe UI, sans-serif; max-width: 1100px; margin: 2rem auto; color: #212529; }}
h1 {{ font-size: 1.4rem; }} h2 {{ font-size: 1.05rem; margin-top: 2rem; }}
table {{ border-collapse: collapse; }} td, th {{ border: 1px solid #dee2e6; padding: 4px 12px; font-size: 0.9rem; }}
img {{ max-width: 100%; }}
</style></head><body>
<h1>NL energy warehouse report</h1>
<h2>Headline stats</h2>
<table><tr><th>metric</th><th>value</th></tr>{stat_rows}</table>
<h2>Pipeline health</h2>
<table>
<tr><th>source</th><th>last run</th><th>data through</th><th>rows written (total)</th><th>runs</th></tr>
{health_rows}
</table>
<h2>Daily price vs temperature</h2>
<img src="data:image/png;base64,{_daily_price_vs_temp(daily)}">
<h2>Hour-of-day price profile</h2>
<img src="data:image/png;base64,{_hour_of_day_profile(hourly)}">
<h2>Negative price hours</h2>
<img src="data:image/png;base64,{_negative_price_hours(daily)}">
<h2>Cross-source alignment</h2>
<img src="data:image/png;base64,{_cross_source_diff(hourly)}">
</body></html>"""

    out = settings.root / "exports" / "report.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out
