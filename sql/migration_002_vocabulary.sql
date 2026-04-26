-- Migration 002: dynamic vocabulary tables (brands, danawa_categories,
-- sku_lines, unknown_vocab). All idempotent.
-- Replaces hardcoded BRAND_ALIASES / SKU_LINE_TOKENS / CATEGORY_MAP at runtime.

-- ---------------------------------------------------------------------------
-- brands: canonical brand registry (auto-discovered + seeded from constants)
-- ---------------------------------------------------------------------------
create table if not exists brands (
  id          serial primary key,
  canonical   text unique not null,
  display     text,
  aliases     text[] not null default '{}',
  category    text,                       -- null = cross-category
  confidence  real not null default 1.0,  -- < 1.0 for auto-discovered
  source      text not null default 'manual',  -- 'seed' | 'freq_analysis' | 'danawa_nav'
  doc_freq    integer not null default 0,      -- # of products that matched
  updated_at  timestamptz not null default now()
);

create index if not exists idx_brands_canonical on brands(canonical);
create index if not exists idx_brands_aliases_gin on brands using gin (aliases);

-- ---------------------------------------------------------------------------
-- danawa_categories: cate ID → korean name + canonical mapping
-- ---------------------------------------------------------------------------
create table if not exists danawa_categories (
  id          serial primary key,
  cate_id     text unique not null,
  name_ko     text not null,
  canonical   text,                          -- 'cpu' | 'gpu' | ... | null if unmapped
  parent_id   text,
  verified    boolean not null default false,
  scraped_at  timestamptz not null default now()
);

create index if not exists idx_danawa_categories_canonical
  on danawa_categories(canonical);

-- ---------------------------------------------------------------------------
-- sku_lines: sub-model identifiers per category (e.g. ventus, gaming trio)
-- ---------------------------------------------------------------------------
create table if not exists sku_lines (
  id          serial primary key,
  canonical   text not null,
  category    text not null,
  aliases     text[] not null default '{}',
  doc_freq    integer not null default 0,
  confidence  real not null default 0.5,
  source      text not null default 'freq_analysis',
  updated_at  timestamptz not null default now(),
  unique (canonical, category)
);

create index if not exists idx_sku_lines_category on sku_lines(category);
create index if not exists idx_sku_lines_aliases_gin on sku_lines using gin (aliases);

-- ---------------------------------------------------------------------------
-- unknown_vocab: tokens we couldn't classify — for review / seeding
-- ---------------------------------------------------------------------------
create table if not exists unknown_vocab (
  token       text not null,
  category    text not null,
  seen_count  integer not null default 1,
  first_seen  timestamptz not null default now(),
  last_seen   timestamptz not null default now(),
  reviewed    boolean not null default false,
  primary key (token, category)
);

create index if not exists idx_unknown_vocab_seen
  on unknown_vocab(seen_count desc);
