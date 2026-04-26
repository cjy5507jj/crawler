-- Migration 004: flag accessory products (cables/converters/brackets) so the
-- aggregate stats step can skip them. Idempotent.

alter table products
  add column if not exists is_accessory boolean not null default false;

create index if not exists idx_products_is_accessory
  on products(is_accessory)
  where is_accessory = true;
