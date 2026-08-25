select hour_utc, price_eur_mwh
from {{ ref('fct_hourly_price_weather') }}
where price_eur_mwh is not null
  and (price_eur_mwh < -200 or price_eur_mwh > 500)
