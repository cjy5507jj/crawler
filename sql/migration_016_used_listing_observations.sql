-- Migration 016: idempotent used-listing daily observations.
-- `used_listings` stores canonical listing identity. This table stores one
-- crawl observation per source/listing/KST day so repeated crawls do not
-- inflate used-market medians.

create table if not exists used_listing_observations (
  id uuid primary key default gen_random_uuid(),
  used_listing_id uuid references used_listings(id) on delete cascade,
  source text not null,
  listing_id text not null,
  observed_date date not null,
  first_observed_at timestamptz not null default now(),
  last_observed_at timestamptz not null default now(),
  seen_count integer not null default 1,
  category text,
  domain text,
  matched_product_id uuid references products(id) on delete set null,
  price integer,
  status text,
  match_score numeric,
  match_reasons jsonb,
  parsed_specs jsonb not null default '{}'::jsonb,
  metadata jsonb not null default '{}'::jsonb,
  unique (source, listing_id, observed_date)
);

create index if not exists idx_ulo_product_observed_date
  on used_listing_observations(matched_product_id, observed_date desc);
create index if not exists idx_ulo_source_listing_observed_date
  on used_listing_observations(source, listing_id, observed_date desc);
create index if not exists idx_ulo_category_status_observed_date
  on used_listing_observations(category, status, observed_date desc);
create index if not exists idx_ulo_last_observed_brin
  on used_listing_observations using brin (last_observed_at);
