-- Migration 014: expose source-provided reference market prices in app_price_index.
-- Reference prices are valuation anchors, not available inventory, so they do
-- not feed lowest_available_price. They can backfill buy_offer_price when C2C
-- market stats are not yet available. New crawls should populate canonical_key;
-- the model/storage fallback is intentionally exact to avoid cross-SKU matches.

drop view if exists app_price_index;

alter table market_price_observations
  add column if not exists domain text,
  add column if not exists canonical_key text;

create index if not exists idx_market_price_observations_canonical_key
  on market_price_observations(canonical_key);

create view app_price_index as
with b2c_candidates as (
  select
    ps.product_id,
    ps.price,
    s.used_count,
    s.used_median
  from price_snapshots ps
  left join product_market_stats s on s.product_id = ps.product_id
  where ps.market_type = 'b2c'
    and ps.snapshot_at >= now() - interval '30 days'
    and ps.price > 0
),
b2c_30d as (
  select
    product_id,
    min(price) as b2c_min,
    count(*)::integer as b2c_count
  from b2c_candidates
  where not (
    coalesce(used_count, 0) >= 3
    and used_median is not null
    and price < floor(used_median * 0.5)
  )
  group by product_id
),
market_reference_candidates as (
  select
    p.id as product_id,
    coalesce(m.avg_price, m.price) as price,
    m.source,
    m.observed_at
  from products p
  join market_price_observations m on m.observed_at >= now() - interval '30 days'
    and coalesce(m.avg_price, m.price) > 0
    and (
      coalesce(m.avg_price, m.price) >= case
        when p.domain = 'phone' then 30000
        else 1
      end
    )
    and (m.domain is null or m.domain = p.domain)
    and (m.category is null or m.category = p.category)
    and (
      (m.canonical_key is not null and p.canonical_key is not null and m.canonical_key = p.canonical_key)
      or (
        m.storage_gb is not null
        and m.storage_gb = case
          when (p.specs->>'storage_gb') ~ '^\d+$' then (p.specs->>'storage_gb')::integer
          else null
        end
        and (
          (m.model is not null and p.specs->>'model' is not null and lower(m.model) = lower(p.specs->>'model'))
          or (m.keyword is not null and p.specs->>'model' is not null and lower(m.keyword) = lower(p.specs->>'model'))
          or (m.model is not null and p.model_name is not null and lower(m.model) = lower(p.model_name))
          or (m.keyword is not null and p.model_name is not null and lower(m.keyword) = lower(p.model_name))
        )
      )
    )
),
market_reference_30d as (
  select
    product_id,
    avg(price)::integer as reference_market_price,
    count(*)::integer as reference_price_count,
    (array_agg(source order by observed_at desc))[1] as reference_price_source,
    max(observed_at) as reference_price_latest_at
  from market_reference_candidates
  group by product_id
)
select
  p.id as product_id,
  p.domain,
  p.category,
  p.brand,
  p.chipset,
  p.model_name,
  p.model_number,
  p.release_year,
  p.canonical_key,
  p.specs,
  p.name,
  p.url,
  coalesce(s.used_count, 0) as c2c_used_count,
  s.used_min as c2c_used_min,
  s.used_median as c2c_used_median,
  b.b2c_min,
  coalesce(b.b2c_count, 0) as b2c_count,
  r.reference_market_price,
  coalesce(r.reference_price_count, 0) as reference_price_count,
  r.reference_price_source,
  r.reference_price_latest_at,
  s.new_price,
  least(s.used_min, b.b2c_min, s.new_price) as lowest_available_price,
  case
    when coalesce(s.used_count, 0) >= 3 and s.used_median is not null
      then floor(s.used_median * 0.8)::integer
    when r.reference_market_price is not null
      then floor(r.reference_market_price * 0.75)::integer
    else null
  end as buy_offer_price,
  case
    when coalesce(s.used_count, 0) > 0
      then round(least(coalesce(s.used_count, 0)::numeric / 10.0, 0.8), 2)
    else round(
      least(
        (case when b.b2c_min is not null then 0.15 else 0 end)
        + (case when r.reference_market_price is not null then 0.20 else 0 end)
        + (case when s.new_price is not null then 0.10 else 0 end),
        1.0
      ),
      2
    )
  end as confidence_score,
  s.trend_7d_pct,
  s.trend_28d_pct,
  s.computed_at
from products p
left join product_market_stats s on s.product_id = p.id
left join b2c_30d b on b.product_id = p.id
left join market_reference_30d r on r.product_id = p.id
where coalesce(p.is_accessory, false) = false;

comment on view app_price_index is
  'Read-only app price index with domain/canonical/spec identity plus C2C, B2C, reference market price, new price, C2B offer anchor, and B2C sanity filtering.';
