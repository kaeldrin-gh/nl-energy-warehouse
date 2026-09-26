# Metric definitions

Single source of truth for the numbers this warehouse publishes. The formal
definitions live in the dbt Semantic Layer (`dbt/models/semantics.yml`); this
page explains them for people who will not read YAML.

| Metric | Question it answers | Formula | Grain | Source model |
| --- | --- | --- | --- | --- |
| `avg_day_ahead_price` | What did a delivery hour cost on average? | `avg(price_eur_mwh)` | hour (Europe/Amsterdam) | `fct_hourly_price_weather` |
| `negative_price_hours` | How often did the price go below zero? | `sum(case when is_negative_price then 1 else 0 end)` | hour | `fct_hourly_price_weather` |
| `total_radiation` | How much sun did De Bilt get? | `sum(radiation_jm2)` | hour | `fct_hourly_price_weather` |

Available slices: `delivery_hour` (local hour) and `local_date` (local day).

## Rules

- A metric is defined once, in `semantics.yml`. To change what a number means,
  change that file first, then this page and the consumers.
- Every CI run parses and builds the semantic layer on both targets (DuckDB and
  PostgreSQL); an invalid definition fails the build.
- The report, Power BI and ad-hoc SQL are expected to match these definitions.
  If they drift, the definitions win and the consumers get fixed.

## Consumers

| Consumer | Uses | Where |
| --- | --- | --- |
| Live market report | weekly cards, headline stats, negative-hours chart | `ingest/report.py` → [report.html](https://kaeldrin-gh.github.io/nl-energy-warehouse/report.html) |
| dbt data catalog | rendered metric and column descriptions | [data catalog](https://kaeldrin-gh.github.io/nl-energy-warehouse/) |
| Power BI dashboard | rebuilt DAX measures over the exported marts | `powerbi/nl-energy-dashboard.pbix`; measures in `analysis/powerbi_measures.md` |
| Ad-hoc SQL | BI visual queries over the Parquet exports or `warehouse/energy.duckdb` | `analysis/bi_queries.sql` |

## Querying locally

```bash
python -m ingest.cli bi headline     # headline stats straight from the marts
```

The MetricFlow CLI (`mf`) is not usable with the pinned dbt version yet (see the
README); the equivalent SQL lives in `analysis/bi_queries.sql`.
