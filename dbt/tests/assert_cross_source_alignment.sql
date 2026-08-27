with recent as (
    select *
    from {{ ref('fct_hourly_price_weather') }}
    where price_diff_eur is not null
      and hour_utc >= (select max(hour_utc) - interval '30 day' from {{ ref('fct_hourly_price_weather') }})
)

select hour_utc, price_eur_mwh, price_eur_mwh_cross_source, price_diff_eur
from recent
where price_diff_eur > 2.0
