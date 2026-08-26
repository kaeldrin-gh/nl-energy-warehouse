{{ config(
    materialized='incremental',
    unique_key='local_date',
    incremental_strategy='delete+insert'
) }}

select
    cast(hour_local as date) as local_date,
    count(*) as hours_in_day,
    round(avg(price_eur_mwh), 2) as avg_price_eur_mwh,
    round(min(price_eur_mwh), 2) as min_price_eur_mwh,
    round(max(price_eur_mwh), 2) as max_price_eur_mwh,
    count(*) filter (where is_negative_price) as negative_price_hours,
    round(avg(temp_c), 1) as avg_temp_c,
    round(max(wind_ms), 1) as max_wind_ms,
    round(coalesce(sum(radiation_jm2), 0) / 1e6, 1) as total_radiation_mj_m2
from {{ ref('fct_hourly_price_weather') }}

{% if is_incremental() %}
where cast(hour_local as date) >= (select coalesce(max(local_date), date '1900-01-01') from {{ this }}) - interval 7 day
{% endif %}
group by 1
