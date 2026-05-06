#!/usr/bin/env python3
"""Seed used_listing_observations from current canonical used_listings rows."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from src.clients.supabase_client import get_client


_KST = ZoneInfo("Asia/Seoul")
_B2C_SOURCES = {"naver_shop"}


def _page(query, page_size: int = 1000) -> list[dict]:
    out: list[dict] = []
    offset = 0
    while True:
        rows = query.range(offset, offset + page_size - 1).execute().data
        if not rows:
            break
        out.extend(rows)
        if len(rows) < page_size:
            break
        offset += page_size
    return out


def _parse_dt(value: str | None) -> datetime:
    if value:
        try:
            if value.endswith("Z"):
                value = value[:-1] + "+00:00"
            dt = datetime.fromisoformat(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def build_observation_row(row: dict) -> dict:
    observed_at = _parse_dt(row.get("crawled_at"))
    return {
        "used_listing_id": row["id"],
        "source": row["source"],
        "listing_id": row["listing_id"],
        "observed_date": observed_at.astimezone(_KST).date().isoformat(),
        "first_observed_at": observed_at.isoformat(),
        "last_observed_at": observed_at.isoformat(),
        "seen_count": 1,
        "category": row.get("category"),
        "domain": row.get("domain"),
        "matched_product_id": row.get("matched_product_id"),
        "price": row.get("price"),
        "status": row.get("status"),
        "match_score": row.get("match_score"),
        "match_reasons": row.get("match_reasons"),
        "parsed_specs": row.get("parsed_specs") or {},
        "metadata": {"backfill": True},
    }


def backfill_used_observations(db, *, dry_run: bool, chunk_size: int = 500) -> dict:
    rows = _page(
        db.table("used_listings")
        .select(
            "id,source,listing_id,domain,category,price,status,matched_product_id,"
            "match_score,match_reasons,parsed_specs,crawled_at"
        )
        .order("crawled_at", desc=False)
    )
    payloads = [
        build_observation_row(row)
        for row in rows
        if row.get("source") not in _B2C_SOURCES
        and row.get("matched_product_id") is not None
        and row.get("price") is not None
    ]
    if dry_run:
        return {"candidates": len(payloads), "written": 0, "dry_run": True}

    written = 0
    for i in range(0, len(payloads), chunk_size):
        batch = payloads[i : i + chunk_size]
        db.table("used_listing_observations").upsert(
            batch,
            on_conflict="source,listing_id,observed_date",
        ).execute()
        written += len(batch)
    return {"candidates": len(payloads), "written": written, "dry_run": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--chunk-size", type=int, default=500)
    args = parser.parse_args()

    result = backfill_used_observations(
        get_client(),
        dry_run=args.dry_run,
        chunk_size=args.chunk_size,
    )
    print(result)


if __name__ == "__main__":
    main()
