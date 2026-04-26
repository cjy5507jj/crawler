create table if not exists crawl_runs (
  id uuid primary key default gen_random_uuid(),
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  trigger_source text not null default 'manual',
  args jsonb not null default '{}'::jsonb,
  summary jsonb not null default '{}'::jsonb,
  status text not null default 'running',
  error text
);
create index if not exists idx_crawl_runs_started_at
  on crawl_runs(started_at desc);
