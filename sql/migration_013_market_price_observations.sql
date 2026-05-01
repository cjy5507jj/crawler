-- Migration 013: source-provided aggregate/reference price observations.

create table if not exists market_price_observations (
  id uuid primary key default gen_random_uuid(),
  source text not null,
  observation_id text not null,
  keyword text,
  brand text,
  category text,
  model text,
  storage_gb integer,
  price integer,
  avg_price integer,
  min_price integer,
  max_price integer,
  sample_count integer,
  price_type text,
  sample_window text,
  release_date date,
  trade_date date,
  url text,
  raw_title text,
  metadata jsonb not null default '{}'::jsonb,
  observed_at timestamptz not null default now(),
  unique (source, observation_id)
);

create index if not exists idx_market_price_observations_source_observed_at
  on market_price_observations(source, observed_at desc);
create index if not exists idx_market_price_observations_model_storage
  on market_price_observations(model, storage_gb);
create index if not exists idx_market_price_observations_category
  on market_price_observations(category);
