#!/usr/bin/env python3
"""Full pipeline: Danawa for every category → all 5 used sources → aggregate stats.

Behavior per category:
  1. Crawl Danawa (--danawa-pages, default 2).
  2. Run board-style sources (coolenjoy, quasarzone) for the category.
  3. Run search-style sources (bunjang, joonggonara, daangn) using queries
     auto-derived from the products just ingested.
  4. After all categories, recompute product_market_stats (window 30 days).

This script is the canonical local orchestrator: a single command produces a
fully refreshed snapshot in Supabase covering every category × source.
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from typing import Any, Iterable

from src.adapters.bunjang import BunjangAdapter
from src.adapters.coolenjoy import CoolenjoyAdapter
from src.adapters.daangn import DaangnAdapter
from src.adapters.joonggonara import JoonggonaraAdapter
from src.adapters.quasarzone import QuasarzoneAdapter
from src.clients.supabase_client import get_client
from src.crawlers.danawa import CATEGORY_MAP
from src.normalization import vocab
from src.services.aggregate import aggregate_market_stats
from src.services.alerts import detect_anomalies, notify
from src.services.discovery import (
    auto_map_canonical_categories,
    discover_brands_from_products,
    discover_categories_from_nav,
    discover_sku_lines_from_products,
    seed_brands_from_constants,
)
from src.services.ingest import run_danawa, run_used
from src.services.queries import derive_queries
from src.services.run_log import finish_run, start_run
from src.services.watchlist import (
    check_watchlists,
    format_message,
    mark_alerted,
)


_QUASARZONE_COOKIE = os.environ.get("QUASARZONE_PHPSESSID") or None
_QB_JIJANG_BOARDS = ("qb_saleinfo", "qb_partnersaleinfo", "qb_jijang")


def _make_quasarzone() -> QuasarzoneAdapter:
    """Construct QuasarzoneAdapter, including qb_jijang when a session
    cookie is available via QUASARZONE_PHPSESSID env var."""
    if _QUASARZONE_COOKIE:
        print("  [quasarzone] using QUASARZONE_PHPSESSID — including qb_jijang")
        return QuasarzoneAdapter(
            boards=_QB_JIJANG_BOARDS,
            session_cookie=_QUASARZONE_COOKIE,
        )
    return QuasarzoneAdapter()


_BOARD_SOURCES = {
    "coolenjoy": CoolenjoyAdapter,
    "quasarzone": _make_quasarzone,
}
# Search-style sources require explicit queries (no flat recent feed).
_SEARCH_SOURCES = {
    "bunjang": BunjangAdapter,
    "joonggonara": JoonggonaraAdapter,
    "daangn": DaangnAdapter,
}


def _safe(label: str, fn) -> None:
    """Run `fn`; print and continue on any exception so one failure doesn't stop the pipeline."""
    try:
        fn()
    except Exception:
        print(f"  ⚠ {label} failed:")
        traceback.print_exc()


def _run_used_for_category(
    db,
    category: str,
    *,
    used_pages: int,
    queries_per_search: int,
    skip_sources: Iterable[str],
) -> None:
    # Board sources (recent feed)
    for name, cls in _BOARD_SOURCES.items():
        if name in skip_sources:
            continue
        _safe(
            f"{name}/{category}",
            lambda c=cls, n=name: run_used(
                db, c(), category=category, pages=used_pages
            ),
        )

    # Search sources — derive queries from the products just ingested
    queries = derive_queries(db, category=category, limit=queries_per_search)
    if not queries:
        print(f"  [{category}] no derivable queries — skipping search sources")
        return
    print(f"  [{category}] queries: {queries}")

    for name, cls in _SEARCH_SOURCES.items():
        if name in skip_sources:
            continue
        _safe(
            f"{name}/{category}",
            lambda c=cls, n=name: run_used(
                db, c(), category=category, queries=queries, pages=used_pages
            ),
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--categories",
        type=str,
        default=",".join(sorted(CATEGORY_MAP)),
        help="Comma-separated categories (default: all 9)",
    )
    parser.add_argument(
        "--danawa-pages",
        type=int,
        default=2,
        help="Danawa pages per category (default: 2). Use 0 for ALL pages "
             "(every manufacturer + model — pulls until empty page).",
    )
    parser.add_argument(
        "--skip-danawa",
        action="store_true",
        help="Skip the Danawa crawl phase entirely (use existing products).",
    )
    parser.add_argument(
        "--used-pages",
        type=int,
        default=1,
        help="Pages per board source (default: 1)",
    )
    parser.add_argument(
        "--queries-per-search",
        type=int,
        default=8,
        help="Top N model queries per category for search sources (default: 8)",
    )
    parser.add_argument(
        "--skip-sources",
        type=str,
        default="",
        help="Comma-separated source names to skip (e.g. daangn,joonggonara)",
    )
    parser.add_argument(
        "--window-days",
        type=int,
        default=30,
        help="Aggregation window for product_market_stats (default: 30)",
    )
    parser.add_argument(
        "--skip-watchlist",
        action="store_true",
        help="Skip the post-aggregate watchlist alert dispatch",
    )
    args = parser.parse_args()

    categories = [c.strip().lower() for c in args.categories.split(",") if c.strip()]
    invalid = [c for c in categories if c not in CATEGORY_MAP]
    if invalid:
        print(f"Unknown category: {invalid}", file=sys.stderr)
        sys.exit(2)

    skip_sources = {s.strip() for s in args.skip_sources.split(",") if s.strip()}

    db = get_client()

    trigger_source = os.environ.get("CRAWL_TRIGGER_SOURCE", "manual")
    run_args = {
        "categories": categories,
        "danawa_pages": args.danawa_pages,
        "skip_danawa": args.skip_danawa,
        "skip_sources": sorted(skip_sources),
        "queries_per_search": args.queries_per_search,
        "window_days": args.window_days,
    }
    run_id = start_run(db, trigger_source=trigger_source, args=run_args)
    summary: dict[str, Any] = {"phases": {}}

    try:
        # Phase 1: Crawl Danawa for every requested category. We do this BEFORE
        # used-source matching so that vocab discovery has a current product base
        # to learn from. Used-market matching runs in phase 3.
        if args.skip_danawa:
            print("\n[skip-danawa] using existing products in DB")
            summary["phases"]["danawa"] = {"skipped": True}
        else:
            for category in categories:
                print(f"\n========== {category.upper()} (danawa) ==========")
                try:
                    run_danawa(db, category, pages=args.danawa_pages)
                except Exception:
                    traceback.print_exc()
            summary["phases"]["danawa"] = {"skipped": False}

        # Phase 2: Refresh dynamic vocabulary (brands / sku_lines / categories)
        # from the products just ingested.
        print("\n========== VOCAB DISCOVERY ==========")
        try:
            seed_brands_from_constants(db)
            discover_categories_from_nav(db)
            auto_map_canonical_categories(db)
            discover_brands_from_products(db, min_doc_freq=3)
            discover_sku_lines_from_products(db, min_doc_freq=3)
            vocab.refresh()
            summary["phases"]["vocab"] = {"done": True}
        except Exception:
            traceback.print_exc()
            summary["phases"]["vocab"] = {"done": False}

        # Phase 3: Run all 5 used-market sources for each category.
        for category in categories:
            print(f"\n========== {category.upper()} (used) ==========")
            _run_used_for_category(
                db,
                category,
                used_pages=args.used_pages,
                queries_per_search=args.queries_per_search,
                skip_sources=skip_sources,
            )
        summary["phases"]["used"] = {"categories": categories}

        print("\n========== AGGREGATE ==========")
        aggregate_market_stats(db, window_days=args.window_days)
        summary["phases"]["aggregate"] = {"done": True}

        stats_count = (
            db.table("product_market_stats")
            .select("product_id", count="exact")
            .execute()
            .count
        )
        with_used = (
            db.table("product_market_stats")
            .select("product_id", count="exact")
            .gt("used_count", 0)
            .execute()
            .count
        )
        summary["metrics"] = {
            "stats_total": stats_count,
            "with_used": with_used,
        }

        prev = (
            db.table("crawl_runs")
            .select("summary")
            .eq("status", "completed")
            .order("started_at", desc=True)
            .neq("id", run_id)
            .limit(1)
            .execute()
            .data
        )
        prev_summary = prev[0]["summary"] if prev else None
        anomalies = detect_anomalies(prev_summary, summary)
        for a in anomalies:
            notify(f"[pc-parts-crawler] {a}", level="alert")

        if not args.skip_watchlist:
            try:
                triggers = check_watchlists(db)
                for t in triggers:
                    notify(format_message(t), level="alert")
                    mark_alerted(db, t.watchlist_id)
                summary["phases"]["watchlist"] = {
                    "alerts": len(triggers),
                }
            except Exception:
                traceback.print_exc()
                summary["phases"]["watchlist"] = {"failed": True}

        finish_run(db, run_id, status="completed", summary=summary)
    except Exception as e:
        finish_run(db, run_id, status="failed", error=str(e)[:2000], summary=summary)
        raise


if __name__ == "__main__":
    main()
