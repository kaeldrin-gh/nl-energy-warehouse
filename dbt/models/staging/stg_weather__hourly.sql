-- Unified hourly weather: KNMI station observations are authoritative; the
-- Open-Meteo ERA5 grid cell fills hours KNMI does not cover (currently: all
-- of them - see INC-006). weather_source keeps the provenance explicit.
with combined as (
    select
        interval_start_utc,
        hour_local_label,
        temp_c,
        wind_ms,
        radiation_jm2,
        'knmi' as weather_source
    from {{ ref('stg_knmi__hourly_weather') }}
    union all
    select
        interval_start_utc,
        hour_local_label,
        temp_c,
        wind_ms,
        radiation_jm2,
        'openmeteo' as weather_source
    from {{ ref('stg_openmeteo__hourly_weather') }}
),

ranked as (
    select
        *,
        row_number() over (
            partition by interval_start_utc
            order by case when weather_source = 'knmi' then 1 else 2 end
        ) as rn
    from combined
)

select
    interval_start_utc,
    hour_local_label,
    temp_c,
    wind_ms,
    radiation_jm2,
    weather_source
from ranked
where rn = 1
