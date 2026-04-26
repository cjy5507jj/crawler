#!/usr/bin/env python3
"""Manual entrypoint — crawl Danawa new-parts prices for one category."""

import argparse
import sys

from src.clients.supabase_client import get_client
from src.crawlers.danawa import CATEGORY_MAP
from src.services.ingest import run_danawa


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crawl Danawa new-parts prices and store in Supabase."
    )
    parser.add_argument(
        "category",
        choices=sorted(CATEGORY_MAP),
        help="PC part category to crawl",
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=1,
        metavar="N",
        help="Number of listing pages to fetch (default: 1, ~20 products/page)",
    )
    args = parser.parse_args()

    db = get_client()
    run_danawa(db, args.category, pages=args.pages)


if __name__ == "__main__":
    main()
