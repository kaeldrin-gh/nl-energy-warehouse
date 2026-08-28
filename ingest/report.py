import base64
import io
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from . import db
from .config import settings

RED = "#c0392b"
GREEN = "#1e8449"
BLUE = "#2471a3"
GREY = "#5d6d7e"


def _fig_to_b64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _load_data(duckdb_path: Path | None):
    conn = db.connect(duckdb_path)
    daily = conn.execute("select * from main.mart_daily_summary order by local_date").fetchdf()
    hourly = conn.execute("select * from main.fct_hourly_price_weather order by hour_utc").fetchdf()
    health = conn.execute(
        """
        select
            source,
            max(run_at) as last_run,
            max(window_end) as data_through,
            sum(rows_written) as rows_total,
            count(*) as runs
        from raw.ingest_log
        group by source
        order by source
        """
    ).fetchdf()
    conn.close()
    daily["local_date"] = pd.to_datetime(daily["local_date"])
    hourly["hour_local"] = pd.to_datetime(hourly["hour_local"])
    return daily, hourly, health


def _week_frame(frame: pd.DataFrame, date_col: str, last_date, offset_days: int, days: int = 7):
    start = last_date - pd.Timedelta(days=offset_days)
    end = start + pd.Timedelta(days=days)
    return frame[(frame[date_col] >= start) & (frame[date_col] < end)]


def _week_metrics(daily: pd.DataFrame, hourly: pd.DataFrame):
    """Week-over-week comparison over the last two fully-covered 7-day windows."""
    last_date = daily["local_date"].max()
    this = _week_frame(daily, "local_date", last_date, 6)
    prev = _week_frame(daily, "local_date", last_date, 13)
    hours_this = _week_frame(hourly, "hour_local", last_date, 6)
    hours_prev = _week_frame(hourly, "hour_local", last_date, 13)

    avg_this = this["avg_price_eur_mwh"].mean()
    avg_prev = prev["avg_price_eur_mwh"].mean()
    delta_pct = (avg_this - avg_prev) / avg_prev * 100 if avg_prev else 0.0

    extreme_max = hours_this.loc[hours_this["price_eur_mwh"].idxmax()]
    extreme_min = hours_this.loc[hours_this["price_eur_mwh"].idxmin()]

    metrics = {
        "avg_this": avg_this,
        "avg_prev": avg_prev,
        "delta_pct": delta_pct,
        "neg_hours_this": int(this["negative_price_hours"].sum()),
        "neg_hours_prev": int(prev["negative_price_hours"].sum()),
        "min_hourly": float(extreme_min["price_eur_mwh"]),
        "min_when": extreme_min["hour_local"],
        "max_hourly": float(extreme_max["price_eur_mwh"]),
        "max_when": extreme_max["hour_local"],
        "avg_temp": hours_this["temp_c"].mean(),
        "avg_wind": hours_this["wind_ms"].mean(),
        "days_covered": len(this),
    }
    return metrics, this, hours_this, hours_prev


def _week_chart(hours_this: pd.DataFrame, hours_prev: pd.DataFrame) -> str:
    fig, ax = plt.subplots(figsize=(11.5, 3.6))
    ax.plot(
        hours_prev["hour_local"],
        hours_prev["price_eur_mwh"],
        color=GREY,
        lw=1.2,
        label="previous week",
    )
    ax.plot(
        hours_this["hour_local"],
        hours_this["price_eur_mwh"],
        color=BLUE,
        lw=1.6,
        label="this week",
    )
    ax.axhline(0, color=GREY, lw=0.7, ls="--", alpha=0.6)
    ax.set_title("Hourly price: this week vs previous week (EUR/MWh)", fontsize=11)
    ax.set_ylabel("EUR/MWh")
    ax.legend(fontsize=9)
    fig.autofmt_xdate()
    return _fig_to_b64(fig)


def _weekly_table(this: pd.DataFrame, avg_prev: float) -> str:
    rows = []
    for r in this.itertuples():
        delta = r.avg_price_eur_mwh - avg_prev
        color = GREEN if delta < 0 else RED
        arrow = "▼" if delta < 0 else "▲"
        rows.append(
            f"<tr><td>{r.local_date:%a %d %b}</td>"
            f"<td>{r.avg_price_eur_mwh:.2f}</td>"
            f"<td style='color:{color}'>{arrow} {abs(delta):.2f}</td>"
            f"<td>{r.min_price_eur_mwh:.2f}</td>"
            f"<td>{r.max_price_eur_mwh:.2f}</td>"
            f"<td>{int(r.negative_price_hours)}</td></tr>"
        )
    body = "".join(rows)
    return (
        "<table><tr><th>day</th><th>avg price</th><th>vs prev-week avg</th>"
        "<th>min hour</th><th>max hour</th><th>negative hours</th></tr>"
        f"{body}</table>"
    )


def _month_table(daily: pd.DataFrame, months: int = 12) -> str:
    frame = daily.copy()
    frame["month"] = frame["local_date"].dt.to_period("M").astype(str)
    agg = (
        frame.groupby("month")
        .agg(avg_price=("avg_price_eur_mwh", "mean"), neg_hours=("negative_price_hours", "sum"))
        .tail(months)
        .reset_index()
    )
    rows = "".join(
        f"<tr><td>{r.month}</td><td>{r.avg_price:.2f}</td><td>{int(r.neg_hours)}</td></tr>"
        for r in agg.itertuples()
    )
    return (
        "<table><tr><th>month</th><th>avg price (EUR/MWh)</th><th>negative hours</th></tr>"
        f"{rows}</table>"
    )


def _daily_price_vs_temp(daily: pd.DataFrame) -> str:
    fig, ax1 = plt.subplots(figsize=(11, 4))
    ax1.plot(daily["local_date"], daily["avg_price_eur_mwh"], color=RED, label="avg price")
    ax1.set_ylabel("avg price (EUR/MWh)", color=RED)
    ax2 = ax1.twinx()
    ax2.plot(daily["local_date"], daily["avg_temp_c"], color=BLUE, alpha=0.7, label="avg temp")
    ax2.set_ylabel("avg temp (C)", color=BLUE)
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
    ax.bar(neg["local_date"].astype(str), neg["negative_price_hours"], color=GREEN)
    ax.set_title("Hours with negative prices per day")
    ax.set_ylabel("hours")
    if len(neg) > 40:
        ax.set_xticks([])
    fig.autofmt_xdate()
    return _fig_to_b64(fig)


def _cross_source_diff(hourly: pd.DataFrame) -> str:
    fig, ax = plt.subplots(figsize=(11, 3.2))
    ax.plot(hourly["hour_local"], hourly["price_diff_eur"], lw=0.6, color=GREY)
    ax.axhline(2.0, color=RED, ls="--", lw=0.8)
    ax.axhline(-2.0, color=RED, ls="--", lw=0.8)
    ax.set_title("Cross-source price difference (ENTSO-E vs energy-charts), EUR 2 test bound")
    ax.set_ylabel("EUR/MWh")
    fig.autofmt_xdate()
    return _fig_to_b64(fig)


def generate(out_path: Path | None = None, duckdb_path: Path | None = None) -> Path:
    daily, hourly, health = _load_data(duckdb_path)
    metrics, this_week, hours_this, hours_prev = _week_metrics(daily, hourly)

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

    delta = metrics["delta_pct"]
    delta_color = GREEN if delta < 0 else RED
    arrow = "▼" if delta < 0 else "▲"
    week_cards = "".join(
        f"<div class='card'><div class='num' style='color:{color}'>{value}</div>"
        f"<div class='lbl'>{label}</div></div>"
        for value, label, color in [
            (f"{metrics['avg_this']:.2f}", "avg price this week (EUR/MWh)", "#212529"),
            (f"{arrow} {abs(delta):.1f}%", "vs previous week", delta_color),
            (str(metrics["neg_hours_this"]), "negative-price hours this week", RED),
            (
                f"{metrics['min_hourly']:.2f}",
                f"cheapest hour ({metrics['min_when']:%a %H:%M})",
                GREEN,
            ),
            (
                f"{metrics['max_hourly']:.2f}",
                f"priciest hour ({metrics['max_when']:%a %H:%M})",
                RED,
            ),
        ]
    )

    generated = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H:%M UTC")
    data_range = f"{hourly['hour_local'].min():%d %b %Y} – {hourly['hour_local'].max():%d %b %Y}"

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>NL energy warehouse report</title>
<style>
body {{ font-family: -apple-system, Segoe UI, sans-serif; max-width: 1100px; margin: 2rem auto; color: #212529; }}
h1 {{ font-size: 1.5rem; margin-bottom: 0; }}
h2 {{ font-size: 1.05rem; margin-top: 2.2rem; border-bottom: 1px solid #dee2e6; padding-bottom: 4px; }}
.sub {{ color: #6c757d; font-size: 0.9rem; }}
table {{ border-collapse: collapse; margin-top: 8px; }}
td, th {{ border: 1px solid #dee2e6; padding: 4px 12px; font-size: 0.9rem; text-align: right; }}
th:nth-child(1), td:nth-child(1) {{ text-align: left; }}
tr:nth-child(even) {{ background: #f8f9fa; }}
img {{ max-width: 100%; }}
.cards {{ display: flex; gap: 12px; flex-wrap: wrap; margin-top: 12px; }}
.card {{ border: 1px solid #dee2e6; border-radius: 8px; padding: 10px 16px; min-width: 170px; }}
.num {{ font-size: 1.35rem; font-weight: 600; }}
.lbl {{ color: #6c757d; font-size: 0.82rem; margin-top: 2px; }}
</style></head><body>
<h1>NL energy warehouse report</h1>
<p class="sub">generated {generated} · data coverage {data_range} · {len(hourly):,} delivery hours</p>

<h2>This week in the market</h2>
<div class="cards">{week_cards}</div>
{_weekly_table(this_week, metrics["avg_prev"])}
<p class="sub">Weather this week: avg temp {metrics["avg_temp"]:.1f} °C, avg wind {metrics["avg_wind"]:.1f} m/s.
Comparisons use the previous 7-day window; lower price deltas are green.</p>
<img src="data:image/png;base64,{_week_chart(hours_this, hours_prev)}">

<h2>Pipeline health</h2>
<table>
<tr><th>source</th><th>last run</th><th>data through</th><th>rows written (total)</th><th>runs</th></tr>
{health_rows}
</table>

<h2>Headline stats (full history)</h2>
<table><tr><th>metric</th><th>value</th></tr>{stat_rows}</table>

<h2>Market calendar (last 12 months)</h2>
{_month_table(daily)}

<h2>Daily price vs temperature</h2>
<img src="data:image/png;base64,{_daily_price_vs_temp(daily)}">
<h2>Hour-of-day price profile</h2>
<img src="data:image/png;base64,{_hour_of_day_profile(hourly)}">
<h2>Negative price hours</h2>
<img src="data:image/png;base64,{_negative_price_hours(daily)}">
<h2>Cross-source alignment</h2>
<img src="data:image/png;base64,{_cross_source_diff(hourly)}">
</body></html>"""

    out = out_path or (settings.root / "exports" / "report.html")
    out.parent.mkdir(exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out
