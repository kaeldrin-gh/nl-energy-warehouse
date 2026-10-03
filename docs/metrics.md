# Metric definitions

This page is the single source of truth for the numbers that this warehouse
publishes. The formal definitions are in the dbt Semantic Layer
(`dbt/models/semantics.yml`). This page explains them for readers who do not
read YAML.

| Metric | Question it answers | Formula | Grain | Source model |
| --- | --- | --- | --- | --- |
| `avg_day_ahead_price` | What did a delivery hour cost on average? | `avg(price_eur_mwh)` | hour (Europe/Amsterdam) | `fct_hourly_price_weather` |
| `negative_price_hours` | How often did the price go below zero? | `sum(case when is_negative_price then 1 else 0 end)` | hour | `fct_hourly_price_weather` |
| `total_radiation` | How much sun did De Bilt get? | `sum(radiation_jm2)` | hour | `fct_hourly_price_weather` |

You can slice the metrics by `delivery_hour` (local hour) and `local_date`
(local day).

## Rules

- Each metric has one definition, in `semantics.yml`. To change what a number
  means, change that file first. Then change this page and the consumers.
- Each CI run parses and builds the semantic layer on both targets (DuckDB and
  PostgreSQL). An incorrect definition makes the build fail.
- The report, Power BI and ad-hoc SQL must agree with these definitions. If a
  consumer does not agree, the definition is correct. Change the consumer.

## Consumers

| Consumer | Uses | Where |
| --- | --- | --- |
| Live market report | weekly cards, headline stats, negative-hours chart | `ingest/report.py` → [report.html](https://kaeldrin-gh.github.io/nl-energy-warehouse/report.html) |
| dbt data catalog | rendered metric and column descriptions | [data catalog](https://kaeldrin-gh.github.io/nl-energy-warehouse/) |
| Power BI dashboard | rebuilt DAX measures over the exported marts | `powerbi/nl-energy-dashboard.pbix`; measures in `analysis/powerbi_measures.md` |
| Ad-hoc SQL | BI visual queries over the Parquet exports or `warehouse/energy.duckdb` | `analysis/bi_queries.sql` |

## Query locally

```bash
python -m ingest.cli bi headline     # headline stats straight from the marts
```

You cannot use the MetricFlow CLI (`mf`) with the pinned dbt version yet. The
same queries in SQL are in `analysis/bi_queries.sql`.
