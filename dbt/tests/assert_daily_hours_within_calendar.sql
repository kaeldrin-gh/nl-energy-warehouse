-- A local day can never hold more delivery hours than the calendar gives it.
-- More would mean a duplicated hour or a DST day bucketed into the wrong date.
-- Fewer is allowed: the newest day is still being published.
select
    m.local_date,
    m.hours_in_day as mart_hours,
    d.hours_in_day as calendar_hours
from {{ ref('mart_daily_summary') }} m
join {{ ref('dim_date') }} d
    on d.local_date = m.local_date
where m.hours_in_day > d.hours_in_day
