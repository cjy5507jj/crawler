-- Migration 001: product_market_stats (idempotent + defensive)
-- Safe to re-run on a database that already has a partial/older version.

create table if not exists product_market_stats (
  product_id uuid primary key references products(id) on delete cascade,
  category text not null default '',
  used_count integer not null default 0,
  used_min integer,
  used_max integer,
  used_median integer,
  used_mean integer,
  used_latest integer,
  used_latest_at timestamptz,
  new_price integer,
  used_to_new_ratio numeric,
  window_days integer not null default 30,
  computed_at timestamptz not null default now()
);

-- Backfill any missing columns when the table existed previously.
alter table product_market_stats add column if not exists category text not null default '';
alter table product_market_stats add column if not exists used_count integer not null default 0;
alter table product_market_stats add column if not exists used_min integer;
alter table product_market_stats add column if not exists used_max integer;
alter table product_market_stats add column if not exists used_median integer;
alter table product_market_stats add column if not exists used_mean integer;
alter table product_market_stats add column if not exists used_latest integer;
alter table product_market_stats add column if not exists used_latest_at timestamptz;
alter table product_market_stats add column if not exists new_price integer;
alter table product_market_stats add column if not exists used_to_new_ratio numeric;
alter table product_market_stats add column if not exists window_days integer not null default 30;
alter table product_market_stats add column if not exists computed_at timestamptz not null default now();

create index if not exists idx_product_market_stats_category
  on product_market_stats(category);
create index if not exists idx_product_market_stats_ratio
  on product_market_stats(used_to_new_ratio);
