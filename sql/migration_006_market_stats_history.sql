create table if not exists product_market_stats_history (
  id uuid primary key default gen_random_uuid(),
  product_id uuid references products(id) on delete cascade,
  category text not null,
  captured_at timestamptz not null default now(),
  window_days integer not null,
  used_count integer not null default 0,
  used_min integer,
  used_max integer,
  used_median integer,
  used_mean integer,
  new_price integer,
  used_to_new_ratio numeric
);
create index if not exists idx_pmsh_product_captured
  on product_market_stats_history(product_id, captured_at desc);
create index if not exists idx_pmsh_captured
  on product_market_stats_history(captured_at desc);

alter table product_market_stats
  add column if not exists trend_7d_pct numeric,
  add column if not exists trend_28d_pct numeric;
