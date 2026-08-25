-- Queries behind the README dashboard screenshots.
-- Each block feeds one Power BI visual. Data source: exports/*.parquet
-- (produced by `python -m ingest.cli export`), or run directly against
-- warehouse/energy.duckdb.

-- ============================================================
-- HEADLINE STATS (card visuals)
-- How much do weather variables actually explain the price?
-- ============================================================

select
    round(corr(price_eur_mwh, temp_c), 3)          as price_temp_corr,
    round(corr(price_eur_mwh, wind_ms), 3)         as price_wind_corr,
    round(corr(price_eur_mwh, radiation_jm2), 3)   as price_radiation_corr,
    round(avg(price_diff_eur), 3)                  as mean_cross_source_diff_eur
from fct_hourly_price_weather
where temp_c is not null;

-- ============================================================
-- V1: Price vs temperature, daily (dual-axis line)
-- The core question of the repo in one picture.
-- ============================================================

select
    local_date,
    avg_price_eur_mwh,
    avg_temp_c
from mart_daily_summary
order by local_date;

-- ============================================================
-- V2: Shape of an average day (line, x = hour 0-23)
-- Evening peak and midday dip; split by season for extra credit
-- (add a season column in Power BI from local_date month).
-- ============================================================

select
    extract(hour from hour_local)          as hour_of_day,
    round(avg(price_eur_mwh), 2)           as avg_price_eur_mwh,
    round(min(price_eur_mwh), 2)           as min_price_eur_mwh,
    round(max(price_eur_mwh), 2)           as max_price_eur_mwh
from fct_hourly_price_weather
group by 1
order by 1;

-- ============================================================
-- V3: Negative price hours per day (bar, filtered > 0)
-- Solar surplus story: negative hours cluster around midday.
-- ============================================================

select
    local_date,
    negative_price_hours
from mart_daily_summary
where negative_price_hours > 0
order by local_date;

-- ============================================================
-- V4: Solar radiation vs price (scatter, x = radiation, y = price)
-- Expect downward pressure on price during high-radiation hours.
-- ============================================================

select
    hour_local,
    price_eur_mwh,
    radiation_jm2 / 1e6 as radiation_mj_m2
from fct_hourly_price_weather
where radiation_jm2 is not null;

-- ============================================================
-- V5: Cross-source validation timeline (line, should hug zero)
-- The "trust but verify" visual: two independent publishers of
-- the same price, divergence kept under EUR 2 by CI test.
-- ============================================================

select
    hour_local,
    price_diff_eur
from fct_hourly_price_weather
where price_diff_eur is not null
order by hour_local;
