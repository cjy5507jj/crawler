#!/usr/bin/env python3
"""Recompute product_market_stats from the price_snapshots history."""

from __future__ import annotations

import argparse

from src.clients.supabase_client import get_client
from src.crawlers.danawa import CATEGORY_MAP
from src.services.aggregate import aggregate_market_stats, aggregate_trends


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Recompute used-market stats per product (median/mean/min/max/ratio)."
    )
    parser.add_argument(
        "--category",
        choices=sorted(CATEGORY_MAP),
        default=None,
        help="Limit to one category (default: all categories)",
    )
    parser.add_argument(
        "--window-days",
        type=int,
        default=30,
        metavar="N",
        help="Aggregation window in days (default: 30)",
    )
    parser.add_argument(
        "--no-trends",
        action="store_true",
        help="Skip trend (7d/28d) computation after aggregation.",
    )
    parser.add_argument(
        "--no-history",
        action="store_true",
        help="Skip writing a row to product_market_stats_history.",
    )
    args = parser.parse_args()

    db = get_client()
    aggregate_market_stats(
        db,
        category=args.category,
        window_days=args.window_days,
        write_history=not args.no_history,
    )
    if not args.no_trends:
        aggregate_trends(db)


if __name__ == "__main__":
    main()
