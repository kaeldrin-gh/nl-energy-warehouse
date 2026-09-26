{% snapshot price_revisions %}

{{
    config(
        target_schema='snapshots',
        unique_key='hour_utc',
        strategy='timestamp',
        updated_at='source_fetched_at',
        hard_deletes='invalidate'
    )
}}

-- The staging view already deduplicates to the newest revision per hour, so an
-- upstream revision arrives as a changed `source_fetched_at`: the snapshot
-- closes the previous row (dbt_valid_to) and opens a new current one.
select
    hour_utc,
    hour_local,
    price_eur_mwh,
    source_fetched_at
from {{ ref('stg_entsoe__day_ahead_prices') }}

{% endsnapshot %}
