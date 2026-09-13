# nl-energy-warehouse

[![ci](https://github.com/kaeldrin-gh/nl-energy-warehouse/actions/workflows/ci.yml/badge.svg)](https://github.com/kaeldrin-gh/nl-energy-warehouse/actions/workflows/ci.yml)
[![docs](https://github.com/kaeldrin-gh/nl-energy-warehouse/actions/workflows/docs.yml/badge.svg)](https://github.com/kaeldrin-gh/nl-energy-warehouse/actions/workflows/docs.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

A data warehouse for Dutch electricity prices and weather, built to answer one
question: what drives the hourly power price in the Netherlands, and when is it
cheap?

**Stack:** Python · dbt · DuckDB · PostgreSQL · GitHub Actions · Power BI

Day-ahead prices come from the [ENTSO-E Transparency Platform](https://transparency.entsoe.eu/),
weather from KNMI station data ([Open-Meteo](https://open-meteo.com/) ERA5 covers
the gap while KNMI migrates), cross-checked against [energy-charts.info](https://energy-charts.info/).
Ingestion is idempotent with revision-aware upserts, modeling is done in dbt, and
the marts are tested in CI and served for BI.

Streaming counterpart: [de-energy-streaming](https://github.com/kaeldrin-gh/de-energy-streaming)
covers the Kafka → Spark → Iceberg stack on German day-ahead prices.

## Why this repo exists

Public energy data is a good engineering stress test:

- ENTSO-E revises published data retroactively, so the price fetched yesterday
  may not be the price published today, and append-only ingestion corrupts history.
- European timezones mean DST: KNMI hourly data is labelled 1-24 in local time,
  which does not map to UTC hours twice a year.
- Two independent sources disagree on the same price. How much disagreement is
  acceptable needs a test, not a hope.

Each is handled explicitly; [INCIDENTS.md](INCIDENTS.md) holds the postmortems
behind the design decisions.

## The answer in four numbers

Computed from the marts: 58,500+ delivery hours (Jan 2020 to today), ENTSO-E
primary with an energy-charts cross-check and Open-Meteo weather alongside.
Methodology and caveats: [analysis/findings.md](analysis/findings.md).

| Metric | Value |
| --- | --- |
| Evening peak vs midday trough | €147 vs €72 per MWh |
| Windy hours (≥ 6 m/s) vs calm | −46% average price |
| Negative-price hours per year | 97 (2020) → 584 (2025) |
| Midday hours below zero, weekends vs weekdays | 22.5% vs 6.7% |

![Duck curve and negative-price explosion](docs/images/05_findings.png)

The practical takeaway: a windy weekend midday is the cheapest window of the
Dutch electricity week, at roughly half the price of an average weekday evening.

Every number is re-runnable: `python -m ingest.cli bi headline` (or `v1`-`v5`)
runs the SQL in [`analysis/bi_queries.sql`](analysis/bi_queries.sql) against the
warehouse.

## What it looks like

Six and a half years of real prices flowing through the dbt marts into Power BI.
Every visual is backed by a query in [`analysis/bi_queries.sql`](analysis/bi_queries.sql),
with measures in [`analysis/powerbi_measures.md`](analysis/powerbi_measures.md)
and the report file in [`powerbi/nl-energy-dashboard.pbix`](powerbi/nl-energy-dashboard.pbix).

![Dashboard overview](docs/images/04_overview.png)

Solar-glut clusters concentrate in spring and summer, including days with up to
about 19 consecutive sub-zero hours:

![Negative-price hours per day](docs/images/02_negative_hours.png)

## Architecture

```
ENTSO-E      (XML API)  ─┐
energy-charts (JSON)    ─┼─> ingest/ (Python, idempotent upserts) ─> DuckDB raw
Open-Meteo    (ERA5)    ─┘         (KNMI station ingester ready; its legacy
                                   endpoint was retired mid-project: INC-006)
                                                       │
                                                       v
                                   dbt: staging -> intermediate -> marts
                                                       │
                                       tests + CI (GitHub Actions)
                                                       │
                                   BI, report.html, analysis/findings.md
```

- Ingestion: watermark plus a fixed lookback window, so revisions inside the
  window overwrite stale values (`INSERT OR REPLACE` on natural keys). Backfills
  run in chunks with retry and backoff, and every run is logged to `raw.ingest_log`.
- Staging: deduplication to the latest revision, weather local-hour to UTC
  conversion with explicit DST semantics, and a unified weather feed that prefers
  KNMI observations over the Open-Meteo reanalysis.
- Marts: `fct_hourly_price_weather` (one row per UTC hour with price, weather,
  cross-source diff and provenance flags) and `mart_daily_summary`, both
  incremental with a revision-matched reprocessing window. ENTSO-E is
  authoritative; energy-charts fills unpublished hours as a flagged fallback.

## Quickstart

```bash
pip install -e ".[dbt]"
python -m ingest.cli load --sample          # 90 days of seeded data, no API keys
dbt build --project-dir dbt --profiles-dir dbt
```

Refresh everything end to end (incremental load, dbt build, Parquet export,
report):

```bash
python -m ingest.cli refresh
python -m ingest.cli bi headline
```

For live sources, copy `.env.example` to `.env`, add a free
[ENTSO-E token](https://transparency.entsoe.eu/usrm/user/create) (KNMI key
optional), then:

```bash
python -m ingest.cli load                                   # incremental + 7-day revision lookback
python -m ingest.cli load --backfill --from 2024-01-01      # chunked historical load
```

A daily cron keeps the repositories fed from the live APIs: ENTSO-E primary,
energy-charts filling the ~1.5% of hours where publication is incomplete, and
Open-Meteo weather while the KNMI migration is pending (INC-006).
`assert_cross_source_alignment` holds the two publishers to a €2/MWh agreement
wherever they overlap.

Everything runs locally on DuckDB, and the same dbt project is validated against
PostgreSQL 17 in CI. A Snowflake profile stub is included; porting was designed
for but not executed yet.

## Semantic layer

`dbt/models/semantics.yml` exposes the marts through the dbt Semantic Layer: one
hourly semantic model with three metrics (`avg_day_ahead_price`,
`negative_price_hours`, `total_radiation`), validated on every CI run. The same
YAML works against a hosted Snowflake Semantic Layer; local querying through the
`mf` CLI is pending dbt-metricflow support for current dbt versions.

## CI/CD

Three workflows in `.github/workflows/`:

- **ci**: ruff, the full pytest suite (including DST integration tests that run
  complete dbt builds), a sample-data `dbt build` with source freshness, and
  `validate-postgres`, which builds the same project against PostgreSQL 17.
- **docs**: regenerates the dbt documentation site from sample data and deploys
  it to [GitHub Pages](https://kaeldrin-gh.github.io/nl-energy-warehouse/), a
  live data catalog with lineage, column docs and test coverage.
- **ingest**: daily cron for incremental load, `dbt build` and Parquet export.
  Skips cleanly when the `ENTSOE_TOKEN` secret is absent, so forks stay green.

Pre-commit hooks mirror the lint job: `pre-commit install`.

## When something breaks

| Symptom | Where to look | Background |
| --- | --- | --- |
| CI red | Actions log, failing step | Testing section below |
| Scheduled ingest failed | `ingest` workflow log | INC-007 (rate limits), INC-006 (retired endpoint), INC-009 (upstream 503) |
| Cross-source alignment fails | `dbt/tests/assert_cross_source_alignment.sql` output | INC-001, INC-003, INC-007, INC-010 |
| One hour looks wrong | `raw.ingest_log`, pipeline health in `exports/report.html` | INC-004, INC-007 |
| Source freshness fails | `dbt source freshness` output | INC-006 (KNMI offline) |

Guardrails reject what is provably broken (uniqueness, exchange limits,
alignment); anomalies within legal bounds surface in the report and provenance
flags rather than failed builds.

## Reproducibility and tests

`requirements-lock.txt` pins the dependency set CI runs against. The Docker image
wraps ingest and dbt:

```bash
docker build -t nl-energy-warehouse .
docker run -v "$PWD/warehouse:/data" nl-energy-warehouse                 # sample load
docker run --entrypoint dbt -v "$PWD/warehouse:/data" nl-energy-warehouse \
    build --project-dir dbt --profiles-dir dbt
```

```bash
pip install -e ".[dbt,test]"
python -m pytest tests -v
```

- Parser tests against committed ENTSO-E XML and KNMI fixtures (hourly and
  15-minute resolutions, negative prices, missing values, hour-24 labels)
- Ingestion tests: upsert idempotency and revision overwrite
- Determinism tests: the sample generator is byte-identical for a given seed
- DST integration tests: full dbt builds over synthetic spring and autumn
  transition days, asserting no duplicate hours

## License

MIT, see [LICENSE](LICENSE).
