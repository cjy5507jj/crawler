-- Migration 007: price-alert watchlists.
-- A watchlist row pairs a (user_id, product_id) with a target_price + direction.
-- scripts/check_watchlist.py compares against product_market_stats.used_median
-- and notifies via src/services/alerts.notify when triggered.
-- 24h cool-down is enforced by last_alerted_at to avoid alert spam.

create table if not exists watchlists (
  id uuid primary key default gen_random_uuid(),
  user_id text not null,
  product_id uuid not null references products(id) on delete cascade,
  target_price integer not null,
  direction text not null default 'below',
  active boolean not null default true,
  created_at timestamptz not null default now(),
  last_alerted_at timestamptz,
  unique (user_id, product_id)
);

create index if not exists idx_watchlists_active
  on watchlists(active) where active = true;
create index if not exists idx_watchlists_product on watchlists(product_id);

alter table watchlists
  drop constraint if exists watchlists_direction_check;
alter table watchlists
  add constraint watchlists_direction_check
  check (direction in ('below', 'above'));
