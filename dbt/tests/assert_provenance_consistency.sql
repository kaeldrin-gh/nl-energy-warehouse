-- Provenance consistency (INC-004/007): the cross-source diff is only defined
-- when ENTSO-E supplied the primary price. An energycharts-sourced hour with a
-- non-null diff would mean we reconciled a source against itself.
select
    hour_utc,
    price_source,
    price_diff_eur
from {{ ref('fct_hourly_price_weather') }}
where price_source = 'energycharts'
  and price_diff_eur is not null
