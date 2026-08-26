# nl-energy-warehouse

[![ci](https://github.com/kaeldrin-gh/nl-energy-warehouse/actions/workflows/ci.yml/badge.svg)](https://github.com/kaeldrin-gh/nl-energy-warehouse/actions/workflows/ci.yml)
[![docs](https://github.com/kaeldrin-gh/nl-energy-warehouse/actions/workflows/docs.yml/badge.svg)](https://github.com/kaeldrin-gh/nl-energy-warehouse/actions/workflows/docs.yml)
![Python](https://img.shields.io/badge/python-3.12-blue)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

A production-style data warehouse for Dutch electricity prices and weather, built to answer one question: **what actually drives the hourly power price in the Netherlands, and when is it cheap?**

Day-ahead prices from the [ENTSO-E Transparency Platform](https://transparency.entsoe.eu/), hourly weather from the [KNMI](https://www.knmi.nl/nederland-nu/klimatologie/uurgegeven), cross-checked against [energy-charts.info](https://energy-charts.info/). Ingested idempotently with revision-aware upserts, modeled in dbt, tested in CI, and served as clean marts for BI.

## Why this repo exists

Public energy data is a great engineering stress test:

- **ENTSO-E revises published data retroactively.** The price you fetched yesterday may not be the price published today. Naive append-only ingestion silently corrupts history.
- **European timezones mean DST.** KNMI hourly data is labeled 1-24 in *local* time, which does not map 1:1 to UTC hours twice a year.
- **Two independent sources disagree** on the same price. By how much is acceptable? That needs a test, not a hope.

Each of these is handled explicitly and documented in [INCIDENTS.md](INCIDENTS.md) as a postmortem of the design decision it produced.

## Architecture

```
ENTSO-E (XML API) ─┐
KNMI (hourly CSV) ─┼─> ingest/ (Python, idempotent upserts) ─> DuckDB raw
energy-charts (JS)─┘                                              │
                                                                  v
                                              dbt: staging -> intermediate -> marts
                                                                  │
                                                     tests + CI (GitHub Actions)
                                                                  │
                                                            BI / analysis
```

- **Ingestion**: watermark + fixed lookback window, so revisions inside the window overwrite stale values (`INSERT OR REPLACE` on natural keys). Chunked backfill mode with retry and exponential backoff. Every run is logged to `raw.ingest_log`.
- **Staging**: deduplication to latest revision, KNMI local-hour to UTC conversion with explicit DST semantics.
- **Marts**: `fct_hourly_price_weather` (one row per UTC hour, price + weather + cross-source diff, `price_source` provenance flag) and `mart_daily_summary`, both incremental with a revision-matched reprocessing window. ENTSO-E is authoritative; energy-charts fills unpublished hours as a flagged fallback.
- **Tests**: uniqueness, sanity bounds, cross-source price alignment, hour-continuity.

## What it looks like

Two years of **real** Dutch day-ahead prices (energy-charts.info fallback source) flowing through the dbt marts to Parquet and Power BI. Every visual below is backed by a query block in [`analysis/bi_queries.sql`](analysis/bi_queries.sql); measures live in [`analysis/powerbi_measures.md`](analysis/powerbi_measures.md).

![Dashboard overview](docs/images/04_overview.png)
*Full report page: headline stats, daily price development, hour-of-day profile, negative-price analysis.*

**Daily average price** — the December 2024 scarcity event pushes one day's average to ~€360/MWh (hourly extreme that day: €873) *(V1)*:

![Daily average day-ahead price](docs/images/01_price_timeline.png)

**Days with negative prices** — solar-glut clusters concentrate in spring and summer 2026, including days with up to ~19 sub-zero hours *(V3)*:

![Negative-price hours per day](docs/images/02_negative_hours.png)

**Shape of an average day** — evening peak vs midday solar dip; the duck curve, straight from market data *(V2)*:

![Average price by hour of day](docs/images/03_day_shape.png)

## Quickstart

```bash
pip install -e ".[dbt]"
python -m ingest.cli load --sample          # 90 days of seeded sample data, no API keys needed
dbt build --project-dir dbt --profiles-dir dbt
```

To use real sources, copy `.env.example` to `.env`, add your free [ENTSO-E token](https://transparency.entsoe.eu/usrm/user/create) (KNMI key optional), then:

```bash
python -m ingest.cli load                                   # incremental: new window + 7-day revision lookback
python -m ingest.cli load --backfill --from 2024-01-01      # chunked historical load, retry with backoff
```

No ENTSO-E token yet? energy-charts.info needs no credentials, so the pipeline runs on **real prices** today:

```bash
python -m ingest.cli load --sources energycharts --backfill --from 2024-08-01
dbt build --project-dir dbt --profiles-dir dbt --full-refresh
```

The fact mart prefers ENTSO-E where both sources publish and falls back to energy-charts for hours it does not, with a `price_source` provenance column so every number in BI is attributable. When the token arrives, the coalesce starts preferring ENTSO-E automatically and the cross-source alignment test takes over. Live KNMI ingestion is temporarily offline - KNMI retired the legacy uurgeg file downloads mid-project ([INC-006](INCIDENTS.md)); weather arrives again after the Data Platform migration.

The mart models are incremental (`delete+insert`) with a 7-day reprocessing window that matches the ingestion revision lookback, so a retroactive source correction propagates from raw to marts on the next run without a full refresh.

The mart models are incremental (`delete+insert`) with a 7-day reprocessing window that matches the ingestion revision lookback, so a retroactive source correction propagates from raw to marts on the next run without a full refresh.

Everything runs locally on DuckDB. A Snowflake profile stub is included in `dbt/profiles.yml`; the models are plain SQL and port directly.

## Semantic layer

`dbt/models/semantics.yml` exposes the marts through the dbt Semantic Layer: an hourly semantic model over `fct_hourly_price_weather` with three metrics (`avg_day_ahead_price`, `negative_price_hours`, `total_radiation`). The definitions are parsed and validated on every CI run as part of `dbt build`. They are plain YAML and travel with the SQL to Snowflake unchanged, where metrics become queryable through the hosted dbt Semantic Layer and its BI integrations.

> Local metric queries via the `mf` CLI (dbt-metricflow) currently pin to dbt-core ~1.8-era adapters; against dbt 1.12 the CLI crashes inside adapter connection handling (the definitions themselves parse and validate cleanly). When dbt-metricflow catches up, `mf query --metrics avg_day_ahead_price --group-by metric_time` works against this repo out of the box.

## CI/CD

Three GitHub Actions workflows live in `.github/workflows/`:

- **ci** — ruff lint + format check, the full pytest suite (including the DST integration tests that run complete dbt builds), then a sample-data `dbt build`. Runs on every push and PR.
- **docs** — regenerates the dbt documentation site from seeded sample data and deploys it to GitHub Pages.
- **ingest** — daily cron running the incremental live ingest → `dbt build` → Parquet export, uploaded as workflow artifacts. Skips gracefully when the `ENTSOE_TOKEN` secret is absent, so forks stay green without credentials.

Local pre-commit hooks (`ruff --fix`, `ruff-format`) mirror the CI lint job: `pre-commit install`.

## Reproducibility

`requirements-lock.txt` pins the exact dependency set the CI suite runs against
(`pip install -r requirements-lock.txt`). The Docker image wraps ingest + dbt:

```bash
docker build -t nl-energy-warehouse .
docker run -v "$PWD/warehouse:/data" nl-energy-warehouse                 # sample load
docker run --entrypoint dbt -v "$PWD/warehouse:/data" nl-energy-warehouse \
    build --project-dir dbt --profiles-dir dbt                           # full pipeline on sample data
```

## Testing

```bash
pip install -e ".[dbt,test]"
python -m pytest tests -v
```

- **Parser tests** against committed ENTSO-E XML and KNMI uurgeg fixtures (hourly and 15-minute resolutions, negative prices, missing values, hour-24 labels) — no network needed
- **Ingestion tests**: upsert idempotency (load twice, same row count) and revision overwrite (newer `fetched_at` wins)
- **Determinism tests**: the sample generator produces byte-identical data for the same seed
- **DST integration tests**: a full dbt build runs against synthetic spring (missing local hour) and autumn (overlapping label) transition days, asserting staging produces no duplicate hours

## What this demonstrates

- Idempotent, revision-aware ingestion against a source that rewrites history
- Timezone and DST handling as an explicit, tested modeling decision
- Cross-source reconciliation with an automated alignment test
- Source failover with provenance tracking when the authoritative source is unavailable
- dbt layering (staging / intermediate / marts) with tests wired into CI
- dbt Semantic Layer metric definitions (YAML) over the fact mart, validated on every build
- Deterministic sample mode so the whole pipeline runs without credentials

## Roadmap

- [x] Incremental mart models with a revision-matched reprocessing window
- [x] dbt semantic layer metric definitions, validated in CI
- [x] Scheduled ingest workflow, docs site on GitHub Pages, pre-commit lint
- [x] Dependency lockfile and Docker image
- [x] Power BI dashboard screenshots in README (measure pack in `analysis/`)
- [ ] KNMI Data Platform migration for live weather ingestion ([INC-006](INCIDENTS.md))
- [ ] ENTSO-E generation mix and cross-border flows
- [ ] Cheap-hour notification service
