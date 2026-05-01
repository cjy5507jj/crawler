-- Migration 011: product-domain expansion for phones, MacBooks, laptops, and appliances.

alter table products
  add column if not exists domain text not null default 'pc_parts',
  add column if not exists model_number text,
  add column if not exists release_year integer,
  add column if not exists specs jsonb not null default '{}'::jsonb,
  add column if not exists canonical_key text;

alter table used_listings
  add column if not exists domain text,
  add column if not exists condition_grade text,
  add column if not exists location_text text,
  add column if not exists seller_type text,
  add column if not exists parsed_specs jsonb not null default '{}'::jsonb;

create index if not exists idx_products_domain_category
  on products(domain, category);
create index if not exists idx_products_canonical_key
  on products(canonical_key);
create index if not exists idx_products_specs_gin
  on products using gin (specs);
create index if not exists idx_used_listings_domain_category
  on used_listings(domain, category);
create index if not exists idx_used_listings_parsed_specs_gin
  on used_listings using gin (parsed_specs);
