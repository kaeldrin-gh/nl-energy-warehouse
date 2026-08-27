-- Hour-continuity guard for the recent window (last 14 days).
-- Gap math uses epoch extraction instead of DuckDB's datediff() so the test
-- runs on both engines; > 2 gaps fails the build (small gaps near DST or
-- publication edges are tolerated and surfaced in the report instead).
with bounds as (
    select max(hour_utc) as max_hour
    from {{ ref('fct_hourly_price_weather') }}
),

hours as (
    select
        f.hour_utc,
        lag(f.hour_utc) over (order by f.hour_utc) as prev_hour
    from {{ ref('fct_hourly_price_weather') }} f, bounds b
    where f.hour_utc >= b.max_hour - interval 14 day
),

gaps as (
    select
        hour_utc,
        prev_hour,
        cast(extract(epoch from (hour_utc - prev_hour)) / 3600 as bigint) as gap_hours
    from hours
    where prev_hour is not null
      and extract(epoch from (hour_utc - prev_hour)) > 3600
),

total as (
    select count(*) as n from gaps
)

select g.hour_utc, g.prev_hour, g.gap_hours
from gaps g, total t
where t.n > 2
