# Power BI: import guide + measure pack

Data source: `exports/*.parquet`, produced by `python -m ingest.cli export`
(re-run after every ingest/dbt build; the scheduled workflow uploads fresh
exports automatically).

## Import (Power BI Desktop)

1. **Get data → Parquet** → `exports/mart_daily_summary.parquet`. Name the table
   `Daily`.
2. Repeat for `exports/fct_hourly_price_weather.parquet` → table `Hourly`.
3. Create a date table (`Date = CALENDAR(DATE(2024,8,1), TODAY())`), mark it
   as date table, relate `Date[Date]` → `Daily[local_date]` (1:*).
4. For `Hourly`, add calculated column
   `date_key = DATE(YEAR([hour_local]), MONTH([hour_local]), DAY([hour_local]))`
   and relate `Date[Date]` → `Hourly[date_key]`.
5. Format: `price_*` as EUR, one decimal; percentages one decimal.

## Measures

```dax
Avg Price EUR/MWh = AVERAGE ( Hourly[price_eur_mwh] )

Min Price EUR/MWh = MIN ( Hourly[price_eur_mwh] )

Max Price EUR/MWh = MAX ( Hourly[price_eur_mwh] )

Price Volatility = STDEV.P ( Hourly[price_eur_mwh] )

Negative Hours =
    CALCULATE ( COUNTROWS ( Hourly ), Hourly[is_negative_price] = TRUE )

% Negative Hours = DIVIDE ( [Negative Hours], COUNTROWS ( Hourly ) )

Cross-Source Mean Diff = AVERAGE ( Hourly[price_diff_eur] )
-- Expect |value| < 2 (CI-enforced); empty until ENTSO-E access is live.

Hours Covered = COUNTROWS ( Hourly )

Share From Fallback =
    DIVIDE (
        CALCULATE ( COUNTROWS ( Hourly ), Hourly[price_source] = "energycharts" ),
        [Hours Covered]
    )
-- 100% while ENTSO-E access is pending; drops toward 0 once live.
```

Weather measures (null-safe while KNMI is offline — they return BLANK instead
of misleading zeros):

```dax
Avg Temp C = CALCULATE ( AVERAGE ( Hourly[temp_c] ), NOT ISBLANK ( Hourly[temp_c] ) )

Max Wind MS = CALCULATE ( MAX ( Hourly[wind_ms] ), NOT ISBLANK ( Hourly[wind_ms] ) )

Radiation MJ/M2 =
    CALCULATE (
        SUM ( Hourly[radiation_jm2] ) / 1000000,
        NOT ISBLANK ( Hourly[radiation_jm2] )
    )
```

Period intelligence (needs the marked date table):

```dax
Avg Price PY =
    CALCULATE (
        [Avg Price EUR/MWh],
        SAMEPERIODLASTYEAR ( 'Date'[Date] )
    )

Avg Price YoY % =
    DIVIDE ( [Avg Price EUR/MWh] - [Avg Price PY], [Avg Price PY] )
```

## Visuals → source mapping

Matches the query blocks in [`bi_queries.sql`](bi_queries.sql):

| Visual | Table/measure | Query |
| --- | --- | --- |
| Card: price vs temp correlation | DAX: `CORREL` over Hourly, or precomputed card from headline block | headline |
| Dual-axis line: daily avg price vs avg temp | `Daily[avg_price_eur_mwh]`, `Daily[avg_temp_c]` | V1 |
| Line: average day shape (x = hour) | Hourly grouped by `HOUR(hour_local)` with Avg/Min/Max price | V2 |
| Bar: negative-price hours per day (>0 filter) | `Daily[negative_price_hours]` | V3 |
| Scatter: radiation vs price | Hourly `[radiation_jm2]/1e6` vs `[price_eur_mwh]` | V4 |
| Line: cross-source diff timeline | `Hourly[price_diff_eur]` | V5 |

## Suggested report page order

1. **Headline** — cards (correlations, % negative hours, hours covered,
   share-from-fallback provenance gauge)
2. **Price drivers** — V1 dual-axis + V4 scatter
3. **Market shape** — V2 average-day line + season slicer
4. **Trust** — V5 cross-source timeline + data-quality note
