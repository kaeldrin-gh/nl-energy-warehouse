select
    hour_utc,
    hour_local,
    price_eur_mwh,
    price_eur_mwh_cross_source,
    price_diff_eur,
    has_weather_match,
    temp_c,
    wind_ms,
    radiation_jm2,
    hour_local_label,
    price_eur_mwh < 0 as is_negative_price
from {{ ref('int_price_weather_hourly') }}
