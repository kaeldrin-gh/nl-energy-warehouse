-- Optional enrichment: public energy-news headlines with classified topics.
-- The raw table exists on every connect (possibly empty), so the model builds in
-- sample warehouses too; dedup keeps the latest fetched revision per headline.
with ranked as (
    select
        *,
        row_number() over (partition by source, link order by fetched_at desc) as rn
    from {{ source('raw', 'news_headlines') }}
)

select
    source,
    link,
    source || '|' || link as headline_key,
    title,
    published_ts,
    category,
    confidence,
    model,
    fetched_at as source_fetched_at
from ranked
where rn = 1
