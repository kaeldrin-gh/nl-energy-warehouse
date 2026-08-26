-- Bounds follow the SDAC/EUPHEMIA technical price limits (-500 .. +4000
-- EUR/MWh), not sample data: real NL hours have reached ~870 EUR (scarcity,
-- Dec 2024) and ~-498 EUR (solar glut, May 2026), both legal market outcomes.
-- Anything outside the technical range is a unit or sign bug.
select hour_utc, price_eur_mwh
from {{ ref('fct_hourly_price_weather') }}
where price_eur_mwh is not null
  and (price_eur_mwh < -500 or price_eur_mwh > 4000)
