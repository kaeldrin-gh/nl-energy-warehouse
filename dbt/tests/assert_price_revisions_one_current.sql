-- Exactly one open (current) revision per delivery hour. Closed revisions are
-- expected; two open ones would mean the snapshot lost track of history.
select
    hour_utc
from {{ ref('price_revisions') }}
group by hour_utc
having count(*) filter (where dbt_valid_to is null) > 1
