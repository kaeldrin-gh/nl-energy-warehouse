select
    p.hour_utc,
    p.hour_local,
    p.price_eur_mwh,
    c.price_eur_mwh as price_eur_mwh_cross_source,
    abs(p.price_eur_mwh - c.price_eur_mwh) as price_diff_eur,
    k.interval_start_utc is not null as has_weather_match,
    k.temp_c,
    k.wind_ms,
    k.radiation_jm2,
    k.hour_local_label
from {{ ref('stg_entsoe__day_ahead_prices') }} p
left join {{ ref('stg_energycharts__day_ahead_prices') }} c using (hour_utc)
left join {{ ref('stg_knmi__hourly_weather') }} k
    on k.interval_start_utc = p.hour_utc
