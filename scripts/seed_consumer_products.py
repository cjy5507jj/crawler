#!/usr/bin/env python3
"""Seed first consumer-electronics product masters into Supabase."""

from __future__ import annotations

from src.clients.supabase_client import get_client
from src.domains.consumer.catalog import build_seed_payloads


def main() -> None:
    db = get_client()
    rows = build_seed_payloads()
    db.table("products").upsert(rows, on_conflict="source,source_id").execute()
    print(f"Seeded {len(rows)} consumer product masters")


if __name__ == "__main__":
    main()
