-- Migration 003: persist MatchResult.reasons on used_listings for observability.
-- Idempotent: safe to re-run.

alter table used_listings
  add column if not exists match_reasons jsonb;

create index if not exists idx_used_listings_match_reasons_gin
  on used_listings using gin (match_reasons);
