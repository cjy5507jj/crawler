-- Migration 015: app-facing daily chart read models.
-- History keeps one row per product per aggregate run. These views collapse
-- multiple same-day runs into the latest Asia/Seoul day snapshot so charts do
-- not double-count manual retries or weekly Daangn runs.

create index if not exists idx_pmsh_category_captured
  on product_market_stats_history(category, captured_at desc);

create or replace view product_market_daily_stats as
select distinct on (h.product_id, ((h.captured_at at time zone 'Asia/Seoul')::date))
  ((h.captured_at at time zone 'Asia/Seoul')::date) as chart_date,
  h.captured_at,
  h.product_id,
  h.category,
  p.domain,
  p.brand,
  p.model_name,
  p.canonical_key,
  p.name,
  h.window_days,
  h.used_count,
  h.used_min,
  h.used_max,
  h.used_median,
  h.used_mean,
  h.new_price,
  h.used_to_new_ratio
from product_market_stats_history h
join products p on p.id = h.product_id
where coalesce(p.is_accessory, false) = false
  and h.used_count > 0
order by
  h.product_id,
  ((h.captured_at at time zone 'Asia/Seoul')::date),
  h.captured_at desc;

comment on view product_market_daily_stats is
  'One latest Asia/Seoul daily history row per product for price charts; removes duplicate same-day aggregate runs.';

create or replace view category_market_daily_stats as
with daily as (
  select * from product_market_daily_stats
)
select
  chart_date,
  category,
  count(*)::integer as product_count,
  sum(used_count)::integer as listing_count,
  percentile_cont(0.5) within group (order by used_median)::integer as median_used_median,
  avg(used_median)::integer as avg_used_median,
  min(used_min) as min_used_price,
  max(used_max) as max_used_price,
  avg(new_price)::integer as avg_new_price,
  avg(used_to_new_ratio)::numeric(10,4) as avg_used_to_new_ratio
from daily
where used_median is not null
group by chart_date, category;

comment on view category_market_daily_stats is
  'Daily category-level chart series derived from product_market_daily_stats.';
