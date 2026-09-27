"""Regenerate the README charts from the warehouse marts.

    python analysis/make_readme_charts.py --through 2026-08-26   # the findings.md window

Writes docs/images/05_findings.png (the day shape and negative hours per year)
and docs/images/06_price_fingerprint.png (every delivery hour since 2020).
Every figure drawn on a chart is computed here from fct_hourly_price_weather,
so the images cannot drift from the numbers in the README's headline table. Pass
--through with the last day of the findings.md window so both describe the same
hours; without it the charts cover everything in the warehouse.
Colours are the validated light-mode categorical pair with recessive hairline
chrome; text never wears a series colour.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, to_rgba  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "images"

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
SECONDARY = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"
SERIES_1 = "#2a78d6"
RAMP = LinearSegmentedColormap.from_list("price", ["#fbe7da", "#eb6834", "#9c3a12"])


def load_hourly(path: Path, through: str | None) -> pd.DataFrame:
    conn = duckdb.connect(str(path), read_only=True)
    frame = conn.execute(
        "select hour_local, price_eur_mwh from main.fct_hourly_price_weather "
        "where ? is null or hour_local < cast(? as date) + interval 1 day order by hour_utc",
        [through, through],
    ).fetchdf()
    conn.close()
    frame["hour_local"] = pd.to_datetime(frame["hour_local"])
    return frame


def style(ax, title: str, subtitle: str) -> None:
    ax.set_facecolor(SURFACE)
    ax.set_title(title, color=INK, fontsize=12.5, loc="left", pad=24, fontweight="bold")
    ax.text(0, 1.03, subtitle, transform=ax.transAxes, color=SECONDARY, fontsize=9.5)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(colors=SECONDARY, labelsize=9, length=0, pad=6)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(BASELINE)


def save(fig, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    fig.savefig(path, facecolor=SURFACE, bbox_inches="tight", pad_inches=0.25, dpi=150)
    plt.close(fig)
    print(f"wrote {path}")


def findings_chart(hourly: pd.DataFrame) -> None:
    first, last = hourly["hour_local"].min(), hourly["hour_local"].max()
    profile = hourly.groupby(hourly["hour_local"].dt.hour)["price_eur_mwh"].mean()
    years = (
        hourly.assign(year=hourly["hour_local"].dt.year)
        .groupby("year")["price_eur_mwh"]
        .apply(lambda p: int((p < 0).sum()))
    )

    fig, (left, right) = plt.subplots(
        1, 2, figsize=(12.5, 4.4), facecolor=SURFACE, gridspec_kw={"width_ratios": [1.25, 1]}
    )

    left.fill_between(profile.index, profile.values, 0, color=SERIES_1, alpha=0.10, linewidth=0)
    left.plot(profile.index, profile.values, color=SERIES_1, linewidth=2, solid_capstyle="round")
    low, high = int(profile.idxmin()), int(profile.idxmax())
    for hour, va, dy in ((low, "top", -12), (high, "bottom", 10)):
        value = profile[hour]
        left.scatter(
            [hour], [value], s=46, color=SERIES_1, edgecolors=SURFACE, linewidths=2, zorder=5
        )
        left.annotate(
            f"€{value:.0f} at {hour:02d}:00",
            (hour, value),
            xytext=(0, dy),
            textcoords="offset points",
            ha="center",
            va=va,
            color=INK,
            fontsize=9,
        )
    left.set_xlim(-0.5, 23.5)
    left.set_ylim(0, profile.max() * 1.25)
    left.set_xticks(range(0, 24, 3), [f"{h:02d}:00" for h in range(0, 24, 3)])
    style(
        left,
        "The shape of an average day",
        f"Average NL day-ahead price by local hour, €/MWh, {first:%b %Y} – {last:%b %Y}",
    )

    partial_year = last.year if (last.month, last.day) != (12, 31) else None
    labels = [f"{y}*" if y == partial_year else str(y) for y in years.index]
    bars = right.bar(labels, years.values, color=SERIES_1, width=0.55)
    right.bar_label(bars, labels=[f"{n:,}" for n in years.values], color=INK, fontsize=9, padding=4)
    right.set_ylim(0, years.max() * 1.18)
    style(right, "Hours priced below zero", "per calendar year")
    if partial_year:
        right.text(
            0,
            -0.13,
            f"* {partial_year} to {last:%d %b}",
            transform=right.transAxes,
            color=MUTED,
            fontsize=8.5,
        )
    fig.tight_layout(w_pad=3)
    save(fig, "05_findings.png")


def fingerprint_chart(hourly: pd.DataFrame) -> None:
    frame = hourly.assign(
        day=hourly["hour_local"].dt.normalize(), hour=hourly["hour_local"].dt.hour
    )
    # Autumn DST days have two local 02:00 hours; the cell shows their mean.
    grid = frame.pivot_table(index="hour", columns="day", values="price_eur_mwh", aggfunc="mean")
    grid = grid.reindex(
        index=range(24), columns=pd.date_range(grid.columns.min(), grid.columns.max())
    )
    values = grid.to_numpy()

    top = float(np.nanpercentile(values[values >= 0], 98))
    rgba = RAMP(np.clip(values, 0, top) / top)
    rgba[values < 0] = to_rgba(SERIES_1)
    rgba[np.isnan(values)] = to_rgba(SURFACE)

    days = grid.columns
    fig, ax = plt.subplots(figsize=(12.5, 4.6), facecolor=SURFACE)
    ax.imshow(
        rgba,
        aspect="auto",
        interpolation="nearest",
        extent=(0, len(days), 24, 0),
    )
    year_starts = [i for i, d in enumerate(days) if d.month == 1 and d.day == 1]
    ax.set_xticks(year_starts, [str(days[i].year) for i in year_starts])
    ax.set_yticks([0, 6, 12, 18], ["00:00", "06:00", "12:00", "18:00"])
    ax.tick_params(colors=SECONDARY, labelsize=9, length=0, pad=6)
    for spine in ax.spines.values():
        spine.set_visible(False)
    # Counted from the hours, not the grid: the grid averages autumn DST's two 02:00 hours.
    negative = int((hourly["price_eur_mwh"] < 0).sum())
    ax.set_title(
        "Price fingerprint: every delivery hour since 2020",
        color=INK,
        fontsize=12.5,
        loc="left",
        pad=24,
        fontweight="bold",
    )
    ax.text(
        0,
        1.03,
        f"One column per day, one row per local hour · {negative:,} hours below €0 in blue",
        transform=ax.transAxes,
        color=SECONDARY,
        fontsize=9.5,
    )

    # Legend on the subtitle line, right-aligned: "€0 [ramp] €402+   [blue] below €0".
    bar_y, bar_h = 0.935, 0.03
    legend = fig.add_axes((0.64, bar_y, 0.13, bar_h))
    legend.imshow(np.linspace(0, 1, 256)[None, :], cmap=RAMP, aspect="auto")
    legend.axis("off")
    label_y = bar_y + bar_h / 2
    fig.text(0.635, label_y, "€0", color=SECONDARY, fontsize=8.5, ha="right", va="center")
    fig.text(0.775, label_y, f"€{top:.0f}+", color=SECONDARY, fontsize=8.5, va="center")
    swatch = fig.add_axes((0.845, bar_y, 0.012, bar_h))
    swatch.set_facecolor(SERIES_1)
    swatch.set_xticks([])
    swatch.set_yticks([])
    for spine in swatch.spines.values():
        spine.set_visible(False)
    fig.text(0.862, label_y, "below €0", color=SECONDARY, fontsize=8.5, va="center")
    save(fig, "06_price_fingerprint.png")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--through", help="last local date to include, YYYY-MM-DD")
    args = parser.parse_args()
    path = Path(os.environ.get("DUCKDB_PATH", ROOT / "warehouse" / "energy.duckdb"))
    hourly = load_hourly(path, args.through)
    print(f"{len(hourly):,} hours, {hourly['hour_local'].min()} .. {hourly['hour_local'].max()}")
    findings_chart(hourly)
    fingerprint_chart(hourly)


if __name__ == "__main__":
    main()
