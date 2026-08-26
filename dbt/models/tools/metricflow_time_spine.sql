{{ config(materialized='table') }}

select cast(d as date) as date_day
from generate_series(
    timestamp '2020-01-01',
    timestamp '2035-12-31',
    interval 1 day
) as t(d)
