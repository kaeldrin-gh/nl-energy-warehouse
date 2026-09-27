-- Every year in dim_date has exactly one 23-hour day (last Sunday of March)
-- and one 25-hour day (last Sunday of October). A wrong timezone conversion
-- shows up here as a year with zero, two, or misplaced change days.
with change_days as (
    select
        year,
        count(*) filter (where hours_in_day = 23) as short_days,
        count(*) filter (where hours_in_day = 25) as long_days,
        count(*) filter (
            where hours_in_day = 23
              and not (month = 3 and iso_day_of_week = 7 and day_of_month >= 25)
        ) as misplaced_short,
        count(*) filter (
            where hours_in_day = 25
              and not (month = 10 and iso_day_of_week = 7 and day_of_month >= 25)
        ) as misplaced_long
    from {{ ref('dim_date') }}
    group by year
)

select *
from change_days
where short_days <> 1
   or long_days <> 1
   or misplaced_short > 0
   or misplaced_long > 0
