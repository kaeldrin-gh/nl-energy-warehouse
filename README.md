# nl-energy-warehouse

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

- **Ingestion**: watermark + fixed lookback window, so revisions inside the window overwrite stale values (`INSERT OR REPLACE` on natural keys). Every run is logged to `raw.ingest_log`.
- **Staging**: deduplication to latest revision, KNMI local-hour to UTC conversion with explicit DST semantics.
- **Marts**: `fct_hourly_price_weather` (one row per UTC hour, price + weather + cross-source diff) and `mart_daily_summary`.
- **Tests**: uniqueness, sanity bounds, cross-source price alignment, hour-continuity.

## Quickstart

```bash
pip install -e ".[dbt]"
python -m ingest.cli load --sample          # 90 days of seeded sample data, no API keys needed
dbt build --project-dir dbt --profiles-dir dbt
```

To use real sources, copy `.env.example` to `.env`, add your free [ENTSO-E token](https://transparency.entsoe.eu/usrm/user/create) (KNMI key optional), then:

```bash
python -m ingest.cli load
```

Everything runs locally on DuckDB. A Snowflake profile stub is included in `dbt/profiles.yml`; the models are plain SQL and port directly.

## What this demonstrates

- Idempotent, revision-aware ingestion against a source that rewrites history
- Timezone and DST handling as an explicit, tested modeling decision
- Cross-source reconciliation with an automated alignment test
- dbt layering (staging / intermediate / marts) with tests wired into CI
- Deterministic sample mode so the whole pipeline runs without credentials

## Roadmap

- [ ] Incremental models with `dbt.incremental` strategy once history grows
- [ ] Power BI dashboard pack (screenshots + PBIX)
- [ ] ENTSO-E generation mix and cross-border flows
- [ ] Cheap-hour notification service
