#!/usr/bin/env python3
"""Re-match the recent used_listings sample under the current matcher and
report category-level precision/recall plus DQ failure attribution.

Usage:
  uv run python scripts/measure_matching_quality.py
  MATCH_THRESHOLD=0.45 uv run python scripts/measure_matching_quality.py
  uv run python scripts/measure_matching_quality.py --window-days 14 --category gpu

Output: per-category JSON with
  - sample_count
  - matched_n / pending_n / unmatched_n
  - dq_brand_n / dq_cat_n / dq_capacity_n / dq_sku_line_n
  - thresholds (MATCH_THRESHOLD, PENDING_THRESHOLD as resolved by env)

This script does NOT mutate Supabase — it re-scores in-process so threshold
sweeps stay safe in production. Pair with `MATCH_THRESHOLD=0.45` env vars to
A/B different cutoffs against the same listing sample.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from typing import Iterable

from src.adapters.base import UsedListing
from src.clients.supabase_client import get_client
from src.services.ingest import _fetch_candidates
from src.services.matching import (
    MATCH_THRESHOLD,
    PENDING_THRESHOLD,
    find_best_candidate,
)


def _iter_recent_listings(
    db, *, category: str | None, window_days: int, limit: int
) -> Iterable[tuple[str, UsedListing]]:
    """Stream (category, UsedListing) for re-match without mutating the DB."""
    page_size = 500
    offset = 0
    while True:
        q = (
            db.table("used_listings")
            .select("category,source,listing_id,title,price,price_raw,status,url")
            .gte("crawled_at", f"now() - interval '{window_days} days'")
            .order("crawled_at", desc=True)
            .range(offset, offset + page_size - 1)
        )
        if category:
            q = q.eq("category", category)
        rows = q.execute().data
        if not rows:
            return
        for row in rows:
            cat = row.get("category")
            if not cat:
                continue
            yield cat, UsedListing(
                source=row["source"],
                listing_id=row["listing_id"],
                title=row.get("title") or "",
                price=row.get("price"),
                price_raw=row.get("price_raw"),
                url=row.get("url"),
                status=row.get("status"),
            )
            if limit and offset >= limit:
                return
        if len(rows) < page_size:
            return
        offset += page_size
        if limit and offset >= limit:
            return


def _categorize_dq(reasons: list[str] | None) -> str | None:
    if not reasons:
        return None
    first = reasons[0]
    if first.startswith("dq:brand"):
        return "brand"
    if first.startswith("dq:cat"):
        return "cat"
    if first.startswith("dq:capacity"):
        return "capacity"
    if first.startswith("dq:sku_line"):
        return "sku_line"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--category", default=None, help="restrict to one category")
    parser.add_argument("--window-days", type=int, default=7)
    parser.add_argument("--limit", type=int, default=10000)
    args = parser.parse_args()

    db = get_client()

    # Pre-load candidate pools per category so we don't refetch per listing.
    candidates_by_cat: dict[str, list] = {}

    counters: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "sample": 0,
            "matched": 0,
            "pending": 0,
            "unmatched": 0,
            "dq_brand": 0,
            "dq_cat": 0,
            "dq_capacity": 0,
            "dq_sku_line": 0,
        }
    )

    for cat, listing in _iter_recent_listings(
        db, category=args.category, window_days=args.window_days, limit=args.limit
    ):
        if cat not in candidates_by_cat:
            candidates_by_cat[cat] = _fetch_candidates(db, cat)
        result = find_best_candidate(listing, candidates_by_cat[cat])
        c = counters[cat]
        c["sample"] += 1
        if result is None:
            c["unmatched"] += 1
            continue
        if result.is_match:
            c["matched"] += 1
        elif result.is_pending:
            c["pending"] += 1
        else:
            c["unmatched"] += 1
            dq = _categorize_dq(result.reasons)
            if dq:
                c[f"dq_{dq}"] += 1

    out = {
        "thresholds": {
            "match": MATCH_THRESHOLD,
            "pending": PENDING_THRESHOLD,
        },
        "window_days": args.window_days,
        "category_filter": args.category,
        "by_category": [
            {"category": cat, **stats}
            for cat, stats in sorted(counters.items())
        ],
    }
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
