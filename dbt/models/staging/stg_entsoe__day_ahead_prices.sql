with latest as (
    select
        hour_utc,
        price_eur_mwh,
        fetched_at,
        row_number() over (partition by hour_utc order by fetched_at desc) as rn
    from {{ source('raw', 'entsoe_prices') }}
)

select
    hour_utc,
    price_eur_mwh,
    fetched_at as source_fetched_at,
    timezone('Europe/Amsterdam', timezone('UTC', hour_utc)) as hour_local
from latest
where rn = 1
