#!/usr/bin/env python3
"""Refresh the dynamic vocabulary tables (brands, sku_lines, danawa_categories).

Run after a Danawa crawl to:
  1. Seed any new entries from current hardcoded constants (cold start).
  2. Discover new categories from Danawa nav.
  3. Discover brands from product first-tokens.
  4. Discover SKU sub-model lines from per-category n-gram TF-IDF.

The dynamic vocab is then picked up automatically by detect_brand /
extract_sku_line_tokens on the next process start (or by calling
src.normalization.vocab.refresh()).
"""

from __future__ import annotations

import argparse

from src.clients.supabase_client import get_client
from src.crawlers.danawa import CATEGORY_MAP
from src.services.discovery import (
    discover_brands_from_products,
    discover_categories_from_nav,
    discover_sku_lines_from_products,
    seed_brands_from_constants,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-nav",
        action="store_true",
        help="Skip Danawa nav scrape (useful when offline or rate-limited)",
    )
    parser.add_argument(
        "--category",
        choices=sorted(CATEGORY_MAP),
        default=None,
        help="Limit brand discovery to one category (default: all)",
    )
    parser.add_argument(
        "--min-doc-freq",
        type=int,
        default=3,
        help="Minimum product count for brand/sku_line to qualify (default: 3)",
    )
    args = parser.parse_args()

    db = get_client()

    print("== seed brands from constants ==")
    seed_brands_from_constants(db)

    if not args.skip_nav:
        print("== discover categories from Danawa nav ==")
        discover_categories_from_nav(db)

    print("== discover brands from products ==")
    discover_brands_from_products(
        db,
        category=args.category,
        min_doc_freq=args.min_doc_freq,
    )

    print("== discover sku_lines from products ==")
    discover_sku_lines_from_products(db, min_doc_freq=args.min_doc_freq)


if __name__ == "__main__":
    main()
