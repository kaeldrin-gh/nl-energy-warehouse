import json
from pathlib import Path

import pandas as pd

from . import db
from .config import settings
from .report_charts import SCRIPT

# Status text for price deltas: a price drop is good for consumers. Always shown
# with an arrow, so the color never carries the meaning alone.
GOOD = "var(--good-text)"
BAD = "var(--bad-text)"


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


def _ts(value) -> str:
    """Minute-precision timestamp for tables; a dash when there is none (e.g. news)."""
    return "–" if pd.isna(value) else f"{pd.Timestamp(value):%Y-%m-%d %H:%M}"


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


def _weekly_table(this: pd.DataFrame, avg_prev: float) -> str:
    rows = []
    for r in this.itertuples():
        delta = r.avg_price_eur_mwh - avg_prev
        color = GOOD if delta < 0 else BAD
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


def _month_table(daily: pd.DataFrame, months: int = 12) -> tuple[str, int]:
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
    table = (
        "<table><tr><th>month</th><th>avg price (EUR/MWh)</th><th>negative hours</th></tr>"
        f"{rows}</table>"
    )
    return table, len(agg)


def _news_stats(conn) -> tuple[pd.DataFrame, int, int] | None:
    """(energy topics, total headlines, filtered) from the staging model."""
    exists = conn.execute(
        "select 1 from information_schema.tables "
        "where table_schema = 'main' and table_name = 'stg_news__headlines'"
    ).fetchone()
    if not exists:
        return None
    topics = conn.execute(
        """
        select category as topic, count(*) as headlines
        from main.stg_news__headlines
        where category is not null
        group by 1
        order by headlines desc, topic
        """
    ).fetchdf()
    total, filtered = conn.execute(
        "select count(*), count(*) filter (where category is null) from main.stg_news__headlines"
    ).fetchone()
    return topics, int(total), int(filtered)


def _load_news(duckdb_path: Path | None = None) -> tuple[pd.DataFrame, int, int] | None:
    conn = db.connect(duckdb_path)
    news = _news_stats(conn)
    conn.close()
    return news


def _news_table(news: pd.DataFrame) -> str:
    rows = "".join(
        f"<tr><td>{row.topic}</td><td>{int(row.headlines)}</td></tr>" for row in news.itertuples()
    )
    return f"<table><tr><th>topic</th><th>headlines</th></tr>{rows}</table>"


def summary_markdown(duckdb_path: Path | None = None) -> str:
    """Compact Markdown metrics summary for a CI run page (GITHUB_STEP_SUMMARY)."""
    conn = db.connect(duckdb_path)
    built = conn.execute(
        "select 1 from information_schema.tables "
        "where table_schema = 'main' and table_name = 'fct_hourly_price_weather'"
    ).fetchone()
    if not built:
        conn.close()
        return (
            "## NL energy warehouse - ingest summary\n\n"
            "Marts are not built (the dbt build failed) - see the run log.\n"
        )
    hourly = conn.execute("select * from main.fct_hourly_price_weather order by hour_utc").fetchdf()
    health = conn.execute(
        """
        select source, max(run_at) as last_run, max(window_end) as data_through,
               sum(rows_written) as rows_total, count(*) as runs
        from raw.ingest_log
        group by source
        order by source
        """
    ).fetchdf()
    news = _news_stats(conn)
    conn.close()

    latest = hourly["hour_utc"].max()
    now = pd.Timestamp.now(tz="UTC").tz_localize(None)
    fallback = int((hourly["price_source"] != "entsoe").sum())
    diff = hourly["price_diff_eur"]

    lines = [
        "## NL energy warehouse - ingest summary",
        "",
        f"Data through **{latest} UTC** ({(now - latest).total_seconds() / 3600:.1f} h old) · "
        f"**{len(hourly)}** delivery hours · price sources: entsoe "
        f"{len(hourly) - fallback} / energycharts {fallback}",
        "",
        "| Window | Avg EUR/MWh | Min | Max | Negative hours |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for days, label in ((1, "Last 24 h"), (7, "Last 7 days"), (30, "Last 30 days")):
        window = hourly[hourly["hour_utc"] > latest - pd.Timedelta(days=days)]
        negative = int(window["is_negative_price"].sum())
        lines.append(
            f"| {label} | {window['price_eur_mwh'].mean():.2f} | "
            f"{window['price_eur_mwh'].min():.2f} | {window['price_eur_mwh'].max():.2f} | "
            f"{negative} ({100 * negative / len(window):.1f} %) |"
        )

    lines += [
        "",
        "| Quality | Value |",
        "| --- | ---: |",
        f"| Max cross-source diff | {diff.max():.2f} EUR/MWh |",
        f"| Hours above 1 EUR diff | {int((diff > 1).sum())} |",
        f"| Weather match | {100 * hourly['has_weather_match'].mean():.1f} % |",
        "",
        "| Source | Last run | Data through | Rows written |",
        "| --- | --- | --- | ---: |",
    ]
    lines += [
        f"| {row.source} | {_ts(row.last_run)} | {_ts(row.data_through)} | {int(row.rows_total):,} |"
        for row in health.itertuples()
    ]
    if news is not None:
        topics, total, filtered = news
        lines += [
            "",
            "### News context",
            "",
            f"| Energy topic (latest {total} headlines) | Headlines |",
            "| --- | ---: |",
        ]
        if not topics.empty:
            lines += [f"| {row.topic} | {int(row.headlines)} |" for row in topics.itertuples()]
        else:
            lines.append("| (none found) | 0 |")
        lines += ["", f"_{filtered} of {total} headlines were general news and filtered out._"]
    return "\n".join(lines)


def _chart_data(daily, hourly, news, hours_this, hours_prev) -> dict:
    """Everything the browser-side charts draw, as plain JSON-ready values."""
    last_date = daily["local_date"].max()
    start_this = last_date - pd.Timedelta(days=6)
    start_prev = last_date - pd.Timedelta(days=13)

    def by_offset(frame: pd.DataFrame, start) -> dict[int, float]:
        offsets = (frame["hour_local"] - start) // pd.Timedelta(hours=1)
        prices = frame["price_eur_mwh"].round(2)
        return {int(i): float(p) for i, p in zip(offsets, prices, strict=True)}

    current, previous = by_offset(hours_this, start_this), by_offset(hours_prev, start_prev)
    week_rows = [
        {
            "i": i,
            "label": f"{start_this + pd.Timedelta(hours=i):%a %d %b %H:00}",
            "current": current.get(i),
            "previous": previous.get(i),
        }
        for i in range(168)
    ]

    first_day = hourly["hour_local"].min().normalize()
    positive = hourly.loc[hourly["price_eur_mwh"] >= 0, "price_eur_mwh"]
    fingerprint_rows = [
        [int((t.normalize() - first_day).days), int(t.hour), round(float(p), 1)]
        for t, p in zip(hourly["hour_local"], hourly["price_eur_mwh"], strict=True)
    ]

    kind = (hourly["hour_local"].dt.dayofweek >= 5).map({True: "weekend", False: "weekday"})
    profile = (
        hourly.assign(kind=kind, hour=hourly["hour_local"].dt.hour)
        .groupby(["kind", "hour"])["price_eur_mwh"]
        .mean()
        .round(2)
        .reset_index(name="price")
    )

    months = daily.assign(month=daily["local_date"].dt.to_period("M").astype(str))
    monthly = (
        months.groupby("month")
        .agg(
            negative_hours=("negative_price_hours", "sum"),
            avg_price=("avg_price_eur_mwh", "mean"),
        )
        .reset_index()
    )
    monthly["negative_hours"] = monthly["negative_hours"].astype(int)
    monthly["avg_price"] = monthly["avg_price"].round(2)

    windy = hourly.dropna(subset=["wind_ms"])
    per_day = (
        windy.assign(date=windy["hour_local"].dt.strftime("%Y-%m-%d"))
        .groupby("date")
        .agg(price=("price_eur_mwh", "mean"), wind=("wind_ms", "mean"))
        .round(2)
        .reset_index()
    )
    wind_r = per_day["price"].corr(per_day["wind"]) if len(per_day) > 2 else None

    topics = [] if news is None else news[0].to_dict("records")
    return {
        "week": {
            "rows": week_rows,
            "ticks": list(range(0, 168, 24)),
            "day_names": [f"{start_this + pd.Timedelta(days=k):%a}" for k in range(7)],
        },
        "fingerprint": {
            "start": f"{first_day:%Y-%m-%d}",
            "p98": round(float(positive.quantile(0.98)), 1) if len(positive) else 1.0,
            "rows": fingerprint_rows,
        },
        "profile": profile.to_dict("records"),
        "monthly": monthly.to_dict("records"),
        "month_labels": {m: pd.Period(m).strftime("%b %Y") for m in monthly["month"]},
        "wind": {
            "rows": per_day.to_dict("records"),
            "r": None if wind_r is None or pd.isna(wind_r) else round(float(wind_r), 2),
        },
        "topics": [{"topic": r["topic"], "headlines": int(r["headlines"])} for r in topics],
    }


def _json_script(payload: dict) -> str:
    # "</" would end the <script> element early; the JSON is identical once parsed.
    return json.dumps(payload, separators=(",", ":"), default=str).replace("</", "<\\/")


def _legend(*items: tuple[str, str]) -> str:
    keys = "".join(
        f"<span class='key'><span class='line' style='background:var({var})'></span>{label}</span>"
        for var, label in items
    )
    return f"<div class='legend'>{keys}</div>"


def _cross_source_tiles(hourly: pd.DataFrame) -> str:
    diff = hourly["price_diff_eur"].dropna()
    fallback = int((hourly["price_source"] != "entsoe").sum())
    tiles = [
        (f"{len(diff):,}", "hours published by both sources"),
        (f"€{diff.max():.2f}" if len(diff) else "–", "largest difference (test bound €2.00)"),
        (f"{int((diff > 1).sum()):,}", "hours differing by more than €1"),
        (f"{fallback:,}", "hours filled from energy-charts (ENTSO-E not yet published)"),
    ]
    cards = "".join(
        f"<div class='card'><div class='num'>{value}</div><div class='lbl'>{label}</div></div>"
        for value, label in tiles
    )
    return f"<div class='cards'>{cards}</div>"


PAGE_STYLE = """
:root {
  color-scheme: light;
  --page: #f9f9f7; --surface: #fcfcfb; --border: rgba(11, 11, 11, 0.10);
  --text-primary: #0b0b0b; --text-secondary: #52514e; --text-muted: #898781;
  --grid: #e1e0d9; --baseline: #c3c2b7;
  --series-1: #2a78d6; --series-2: #eb6834; --ramp-lo: #fbe7da; --ramp-hi: #9c3a12;
  --good-text: #006300; --bad-text: #d03b3b;
}
@media (prefers-color-scheme: dark) {
  :root {
    color-scheme: dark;
    --page: #0d0d0d; --surface: #1a1a19; --border: rgba(255, 255, 255, 0.10);
    --text-primary: #ffffff; --text-secondary: #c3c2b7; --text-muted: #898781;
    --grid: #2c2c2a; --baseline: #383835;
    --series-1: #3987e5; --series-2: #d95926; --ramp-lo: #2a1d16; --ramp-hi: #ff9d63;
    --good-text: #0ca30c; --bad-text: #ef6b6b;
  }
}
* { box-sizing: border-box; }
body { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; max-width: 1100px;
       margin: 0 auto; padding: 2rem 16px 3rem; background: var(--page);
       color: var(--text-primary); line-height: 1.45; }
h1 { font-size: 1.6rem; margin: 0; }
h2 { font-size: 1.1rem; margin-top: 2.6rem; padding-bottom: 6px;
     border-bottom: 1px solid var(--grid); }
h3 { font-size: 0.98rem; margin: 1.4rem 0 0; }
.chart h3 { margin: 0; }
.sub { color: var(--text-secondary); font-size: 0.9rem; margin: 0.35rem 0 0.8rem; }
a { color: var(--series-1); }
table { border-collapse: collapse; margin-top: 8px; font-variant-numeric: tabular-nums;
        display: block; overflow-x: auto; max-width: 100%; }
td, th { border-bottom: 1px solid var(--grid); padding: 5px 12px; font-size: 0.88rem;
         text-align: right; white-space: nowrap; }
th { color: var(--text-secondary); font-weight: 600; }
th:nth-child(1), td:nth-child(1) { text-align: left; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
         gap: 12px; margin-top: 12px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
        padding: 12px 16px; }
.num { font-size: 1.4rem; font-weight: 600; }
.lbl { color: var(--text-secondary); font-size: 0.82rem; margin-top: 2px; }
.chart { background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
         padding: 14px 16px 8px; margin: 14px 0 0; }
.plot { width: 100%; min-height: 60px; }
.legend { display: flex; gap: 18px; flex-wrap: wrap; margin: 6px 0 2px;
          color: var(--text-secondary); font-size: 0.85rem; }
.key { display: inline-flex; align-items: center; gap: 6px; }
.line { display: inline-block; width: 18px; height: 2px; border-radius: 1px; }
.swatch { display: inline-block; width: 14px; height: 12px; border-radius: 2px; }
.ramp { width: 64px; }
details { margin-top: 8px; color: var(--text-secondary); font-size: 0.88rem; }
noscript p { color: var(--text-secondary); }
"""


def generate(out_path: Path | None = None, duckdb_path: Path | None = None) -> Path:
    daily, hourly, health = _load_data(duckdb_path)
    news = _load_news(duckdb_path)
    metrics, this_week, hours_this, hours_prev = _week_metrics(daily, hourly)

    corr = hourly[["price_eur_mwh", "temp_c", "wind_ms", "radiation_jm2"]].corr()
    stats = {
        "correlation: price vs temperature": f"{corr.loc['price_eur_mwh', 'temp_c']:.2f}",
        "correlation: price vs wind": f"{corr.loc['price_eur_mwh', 'wind_ms']:.2f}",
        "correlation: price vs radiation": f"{corr.loc['price_eur_mwh', 'radiation_jm2']:.2f}",
        "mean cross-source diff": f"{hourly['price_diff_eur'].mean():.2f} EUR/MWh",
        "hours covered": f"{len(hourly):,}",
    }
    stat_rows = "".join(
        f"<tr><td>{name}</td><td>{value}</td></tr>" for name, value in stats.items()
    )
    month_table, month_count = _month_table(daily)

    health_rows = "".join(
        f"<tr><td>{r.source}</td><td>{_ts(r.last_run)}</td><td>{_ts(r.data_through)}</td>"
        f"<td>{int(r.rows_total):,}</td><td>{int(r.runs)}</td></tr>"
        for r in health.itertuples()
    )

    delta = metrics["delta_pct"]
    arrow = "▼" if delta < 0 else "▲"
    week_cards = "".join(
        f"<div class='card'><div class='num' style='color:{color}'>{value}</div>"
        f"<div class='lbl'>{label}</div></div>"
        for value, label, color in [
            (f"€{metrics['avg_this']:.2f}", "average price this week (per MWh)", "inherit"),
            (f"{arrow} {abs(delta):.1f}%", "vs the previous week", GOOD if delta < 0 else BAD),
            (str(metrics["neg_hours_this"]), "negative-price hours this week", "inherit"),
            (
                f"€{metrics['min_hourly']:.2f}",
                f"cheapest hour ({metrics['min_when']:%a %H:%M})",
                "inherit",
            ),
            (
                f"€{metrics['max_hourly']:.2f}",
                f"priciest hour ({metrics['max_when']:%a %H:%M})",
                "inherit",
            ),
        ]
    )

    if news is not None and news[1]:
        topics, total, filtered = news
        news_section = (
            f"<h2>News context (latest {total} headlines)</h2>"
            "<p class='sub'>Topics from public energy-news feeds, classified by "
            f"classifier.dev. {filtered} of {total} headlines were general news and "
            "filtered out.</p>"
            + (
                "<figure class='chart'><div class='plot' id='chart-topics'></div></figure>"
                f"<details><summary>Table</summary>{_news_table(topics)}</details>"
                if not topics.empty
                else "<p>No energy topics found.</p>"
            )
        )
    else:
        news_section = ""

    payload = _chart_data(daily, hourly, news, hours_this, hours_prev)
    wind_r = payload["wind"]["r"]
    generated = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H:%M UTC")
    data_range = f"{hourly['hour_local'].min():%d %b %Y} – {hourly['hour_local'].max():%d %b %Y}"
    ramp_top = payload["fingerprint"]["p98"]

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NL energy warehouse report</title>
<style>{PAGE_STYLE}</style></head><body>
<h1>NL energy warehouse report</h1>
<p class="sub">generated {generated} · data coverage {data_range} ·
{len(hourly):,} delivery hours</p>
<noscript><p>The charts need JavaScript; the tables carry the same numbers.</p></noscript>

<h2>This week in the market</h2>
<div class="cards">{week_cards}</div>
<figure class="chart">
  <h3>Hourly price, this week against last week (EUR/MWh)</h3>
  {_legend(("--series-1", "this week"), ("--text-muted", "last week"))}
  <div class="plot" id="chart-week"></div>
</figure>
{_weekly_table(this_week, metrics["avg_prev"])}
<p class="sub">Weather this week: avg temp {metrics["avg_temp"]:.1f} °C, avg wind
{metrics["avg_wind"]:.1f} m/s. Comparisons use the previous 7-day window; a green ▼ means
cheaper than last week.</p>

<h2>Price fingerprint</h2>
<figure class="chart">
  <h3>Every delivery hour in the window: one column per day, one row per hour</h3>
  <div class="legend">
    <span class="key"><span class="swatch ramp"
      style="background:linear-gradient(90deg, var(--ramp-lo), var(--ramp-hi))"></span>
      €0 to €{ramp_top:.0f}+ per MWh</span>
    <span class="key"><span class="swatch" style="background:var(--series-1)"></span>
      below €0</span>
  </div>
  <div class="plot" id="chart-fingerprint"></div>
  <p class="sub">Blue cells are hours priced below zero. Hover a cell for its date, hour and
  price.</p>
</figure>

<h2>When power is cheap</h2>
<figure class="chart">
  <h3>Average price by hour of day (EUR/MWh)</h3>
  {_legend(("--series-1", "weekday"), ("--series-2", "weekend"))}
  <div class="plot" id="chart-profile"></div>
</figure>
<figure class="chart">
  <h3>Hours priced below zero, per month</h3>
  <div class="plot" id="chart-negative"></div>
</figure>
<h3>Market calendar (last {month_count} months)</h3>
{month_table}

<h2>Wind and price</h2>
<figure class="chart">
  <h3>Daily average price against daily average wind speed</h3>
  <p class="sub">One dot per day: wind speed in m/s across, price in EUR/MWh up; correlation
  r = {"–" if wind_r is None else wind_r}. The line is a least-squares fit with its 95% band.</p>
  <div class="plot" id="chart-wind"></div>
</figure>
<h3>Headline stats (whole coverage window)</h3>
<table><tr><th>metric</th><th>value</th></tr>{stat_rows}</table>

<h2>Cross-source agreement</h2>
<p class="sub">ENTSO-E is the primary source; energy-charts.info publishes the same auction
result and fills hours ENTSO-E has not published yet. A dbt test fails the build if the two
differ by more than €2 in the last 30 days.</p>
{_cross_source_tiles(hourly)}
{news_section}

<h2>Pipeline health</h2>
<table>
<tr><th>source</th><th>last run</th><th>data through</th><th>rows written (total)</th><th>runs</th></tr>
{health_rows}
</table>

<p class="sub" style="margin-top:2.5rem">Part of a three-project portfolio:
<a href="https://github.com/kaeldrin-gh/nl-energy-warehouse">nl-energy-warehouse</a> ·
<a href="https://github.com/kaeldrin-gh/de-energy-streaming">de-energy-streaming</a> ·
<a href="https://github.com/kaeldrin-gh/databricks-energy-quality">databricks-energy-quality</a>.</p>
<script type="application/json" id="report-data">{_json_script(payload)}</script>
<script type="module">{SCRIPT}</script>
</body></html>"""

    out = out_path or (settings.root / "exports" / "report.html")
    out.parent.mkdir(exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out
