-- Open-Meteo ERA5 reanalysis, staged to the same contract as stg_knmi.
-- Labels arrive as Amsterdam wall-clock hour-ends (mirroring KNMI uurgeg), so
-- the same named-zone conversion applies unchanged.
with converted as (
    select
        station,
        interval_end_local,
        cast(timezone('Europe/Amsterdam', interval_end_local) as timestamp) as interval_end_utc,
        temp_c,
        wind_ms,
        radiation_jm2,
        fetched_at
    from {{ source('raw', 'openmeteo_weather') }}
)

select
    station,
    interval_end_local,
    interval_end_utc,
    interval_end_utc - interval 1 hour as interval_start_utc,
    extract(hour from interval_end_local) as hour_local_label,
    temp_c,
    wind_ms,
    radiation_jm2,
    fetched_at as source_fetched_at
from converted
qualify row_number() over (partition by station, interval_end_utc order by fetched_at desc) = 1
