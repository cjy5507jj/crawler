-- Migration 012: expose domain/canonical/spec metadata in app_price_index.
-- Apps can now render PC parts, phones, laptops, MacBooks, TVs, and appliances
-- from one read-only view without joining back to products for identity fields.
--
-- We drop/recreate instead of CREATE OR REPLACE because Postgres does not allow
-- inserting `domain` before the existing `category` column in-place.

drop view if exists app_price_index;

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
  s.new_price,
  least(s.used_min, b.b2c_min, s.new_price) as lowest_available_price,
  case
    when coalesce(s.used_count, 0) >= 3 and s.used_median is not null
      then floor(s.used_median * 0.8)::integer
    else null
  end as buy_offer_price,
  case
    when coalesce(s.used_count, 0) > 0
      then round(least(coalesce(s.used_count, 0)::numeric / 10.0, 0.8), 2)
    else round(
      least(
        (case when b.b2c_min is not null then 0.15 else 0 end)
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
where coalesce(p.is_accessory, false) = false;

comment on view app_price_index is
  'Read-only app price index with domain/canonical/spec identity plus C2C, B2C, new price, C2B offer anchor, and B2C sanity filtering.';
