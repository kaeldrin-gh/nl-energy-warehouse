-- One row per delivery hour that at least one price source has published.
--
-- ENTSO-E is authoritative; energy-charts.info fills hours ENTSO-E has not
-- published yet (or cannot be fetched). Provenance travels alongside the
-- value so BI can always tell which source produced a number.
--
-- price_diff_eur is only defined when the primary price came from ENTSO-E:
-- reconciling a source against itself would manufacture agreement.
with prices as (
    select
        coalesce(e.hour_utc, c.hour_utc) as hour_utc,
        case when e.hour_utc is not null then 'entsoe' else 'energycharts' end as price_source,
        coalesce(e.price_eur_mwh, c.price_eur_mwh) as price_eur_mwh,
        case when e.hour_utc is not null then c.price_eur_mwh end as price_eur_mwh_cross_source,
        case
            when e.hour_utc is not null then abs(e.price_eur_mwh - c.price_eur_mwh)
        end as price_diff_eur
    from {{ ref('stg_entsoe__day_ahead_prices') }} e
    full outer join {{ ref('stg_energycharts__day_ahead_prices') }} c
        on e.hour_utc = c.hour_utc
)

select
    p.hour_utc,
    timezone('Europe/Amsterdam', timezone('UTC', p.hour_utc)) as hour_local,
    p.price_eur_mwh,
    p.price_eur_mwh_cross_source,
    p.price_diff_eur,
    p.price_source,
    k.interval_start_utc is not null as has_weather_match,
    k.weather_source,
    k.temp_c,
    k.wind_ms,
    k.radiation_jm2,
-- hour_local_label is the KNMI 1-24 local label; nullable by design (no weather
-- match), so cast to a nullable integer type explicitly for a stable BI contract.
    cast(k.hour_local_label as bigint) as hour_local_label
from prices p
left join {{ ref('stg_weather__hourly') }} k
    on k.interval_start_utc = p.hour_utc
