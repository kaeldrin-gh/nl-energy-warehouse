-- Conformed date dimension: one row per calendar date, keyed on local_date so
-- it joins mart_daily_summary directly and fct_hourly_price_weather through
-- cast(hour_local as date).
--
-- The calendar comes from the MetricFlow time spine, so the warehouse has one
-- date range. hours_in_day is the length of the Europe/Amsterdam day, measured
-- between two local midnights in UTC: 23 on the spring DST change, 25 on the
-- autumn one. Measuring it instead of hard-coding the EU rule keeps it right
-- if the rule ever changes in the timezone database.
with calendar as (
    select date_day as local_date
    from {{ ref('metricflow_time_spine') }}
),

parts as (
    select
        local_date,
        cast(extract(year from local_date) as bigint) as year,
        cast(extract(quarter from local_date) as bigint) as quarter,
        cast(extract(month from local_date) as bigint) as month,
        cast(extract(day from local_date) as bigint) as day_of_month,
        cast(extract(isoyear from local_date) as bigint) as iso_year,
        cast(extract(week from local_date) as bigint) as iso_week,
        cast(extract(isodow from local_date) as bigint) as iso_day_of_week,
        cast(
            extract(epoch from (
                timezone('Europe/Amsterdam', cast(local_date + 1 as timestamp))
                - timezone('Europe/Amsterdam', cast(local_date as timestamp))
            )) / 3600 as bigint
        ) as hours_in_day
    from calendar
)

select
    local_date,
    year,
    quarter,
    month,
    -- Names come from CASE rather than dayname()/to_char(): the two engines
    -- spell those functions differently.
    case month
        when 1 then 'January'
        when 2 then 'February'
        when 3 then 'March'
        when 4 then 'April'
        when 5 then 'May'
        when 6 then 'June'
        when 7 then 'July'
        when 8 then 'August'
        when 9 then 'September'
        when 10 then 'October'
        when 11 then 'November'
        when 12 then 'December'
    end as month_name,
    day_of_month,
    iso_year,
    iso_week,
    iso_day_of_week,
    case iso_day_of_week
        when 1 then 'Monday'
        when 2 then 'Tuesday'
        when 3 then 'Wednesday'
        when 4 then 'Thursday'
        when 5 then 'Friday'
        when 6 then 'Saturday'
        when 7 then 'Sunday'
    end as day_name,
    iso_day_of_week >= 6 as is_weekend,
    hours_in_day,
    hours_in_day <> 24 as is_dst_change_day
from parts
