-- pc-parts-crawler schema
-- Idempotent: safe to re-run on an existing database.

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------------
-- products: canonical Danawa product master
-- ---------------------------------------------------------------------------
create table if not exists products (
  id uuid primary key default gen_random_uuid(),
  category text not null,
  domain text not null default 'pc_parts',
  source text not null,
  source_id text not null,
  name text not null,
  brand text,
  chipset text,
  model_number text,
  release_year integer,
  specs jsonb not null default '{}'::jsonb,
  canonical_key text,
  model_name text,
  normalized_name text,
  url text,
  is_accessory boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (source, source_id)
);

alter table products add column if not exists brand text;
alter table products add column if not exists domain text not null default 'pc_parts';
alter table products add column if not exists chipset text;
alter table products add column if not exists model_number text;
alter table products add column if not exists release_year integer;
alter table products add column if not exists specs jsonb not null default '{}'::jsonb;
alter table products add column if not exists canonical_key text;
alter table products add column if not exists model_name text;
alter table products add column if not exists normalized_name text;
alter table products add column if not exists is_accessory boolean not null default false;
alter table products add column if not exists updated_at timestamptz not null default now();

create index if not exists idx_products_category on products(category);
create index if not exists idx_products_domain_category on products(domain, category);
create index if not exists idx_products_brand on products(brand);
create index if not exists idx_products_chipset on products(chipset);
create index if not exists idx_products_canonical_key on products(canonical_key);
create index if not exists idx_products_specs_gin on products using gin (specs);
create index if not exists idx_products_model_name on products(model_name);
create index if not exists idx_products_is_accessory
  on products(is_accessory)
  where is_accessory = true;

-- ---------------------------------------------------------------------------
-- used_listings: per-source raw used-market posts + match metadata
-- ---------------------------------------------------------------------------
create table if not exists used_listings (
  id uuid primary key default gen_random_uuid(),
  source text not null,
  listing_id text not null,
  domain text,
  category text,
  title text not null,
  price integer,
  price_raw text,
  status text,
  url text,
  matched_product_id uuid references products(id) on delete set null,
  match_score numeric,
  match_reasons jsonb,
  condition_grade text,
  location_text text,
  seller_type text,
  parsed_specs jsonb not null default '{}'::jsonb,
  crawled_at timestamptz not null default now(),
  unique (source, listing_id)
);

create index if not exists idx_used_listings_source_listing
  on used_listings(source, listing_id);
create index if not exists idx_used_listings_matched
  on used_listings(matched_product_id, crawled_at desc);
create index if not exists idx_used_listings_category_status
  on used_listings(category, status);
create index if not exists idx_used_listings_domain_category
  on used_listings(domain, category);
create index if not exists idx_used_listings_match_reasons_gin
  on used_listings using gin (match_reasons);
create index if not exists idx_used_listings_parsed_specs_gin
  on used_listings using gin (parsed_specs);

-- ---------------------------------------------------------------------------
-- price_snapshots: time series of prices (new + used)
-- ---------------------------------------------------------------------------
create table if not exists price_snapshots (
  id uuid primary key default gen_random_uuid(),
  product_id uuid not null references products(id) on delete cascade,
  market_type text not null default 'new',
  source text,
  price integer not null,
  shop_name text,
  snapshot_at timestamptz not null default now()
);

alter table price_snapshots add column if not exists market_type text not null default 'new';
alter table price_snapshots add column if not exists source text;

create index if not exists idx_price_snapshots_product_snapshot_at
  on price_snapshots(product_id, snapshot_at desc);
create index if not exists idx_price_snapshots_market_type
  on price_snapshots(market_type, snapshot_at desc);
create index if not exists idx_price_snapshots_market_source_snapshot_at
  on price_snapshots(market_type, source, snapshot_at desc);

-- ---------------------------------------------------------------------------
-- product_market_stats: aggregated used-market metrics per product
-- Refreshed by scripts/aggregate_stats.py.
-- ---------------------------------------------------------------------------
create table if not exists product_market_stats (
  product_id uuid primary key references products(id) on delete cascade,
  category text not null,
  used_count integer not null default 0,
  used_min integer,
  used_max integer,
  used_median integer,
  used_mean integer,            -- trimmed mean (10% top/bottom dropped when count >= 5)
  used_latest integer,
  used_latest_at timestamptz,
  new_price integer,            -- most recent danawa lowest price
  used_to_new_ratio numeric,    -- used_median / new_price
  window_days integer not null,
  computed_at timestamptz not null default now(),
  trend_7d_pct numeric,
  trend_28d_pct numeric
);

create index if not exists idx_product_market_stats_category
  on product_market_stats(category);
create index if not exists idx_product_market_stats_ratio
  on product_market_stats(used_to_new_ratio);
