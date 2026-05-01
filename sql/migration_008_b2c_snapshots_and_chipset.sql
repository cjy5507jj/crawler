-- Migration 008: align schema with B2C/C2C price separation.
-- `market_type` is intentionally free text in the base schema; crawler code now
-- writes naver_shop snapshots as market_type='b2c' and C2C listings as 'used'.

alter table products
  add column if not exists chipset text;

create index if not exists idx_products_chipset on products(chipset);

-- Aggregate reads used C2C snapshots by market_type + source + recent window.
create index if not exists idx_price_snapshots_market_source_snapshot_at
  on price_snapshots(market_type, source, snapshot_at desc);
