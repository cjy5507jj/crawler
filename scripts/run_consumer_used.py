#!/usr/bin/env python3
"""Crawl consumer-electronics used listings for seeded categories."""

from __future__ import annotations

import argparse
import sys

from src.adapters.bunjang import BunjangAdapter
from src.adapters.daangn import DaangnAdapter
from src.adapters.joonggonara import JoonggonaraAdapter
from src.adapters.naver_shop import NaverShopAdapter
from src.clients.supabase_client import get_client
from src.domains.consumer.catalog import query_seeds_for_category
from src.domains.consumer.matching import CONSUMER_CATEGORIES
from src.services.ingest import run_used


_ADAPTERS = {
    "bunjang": BunjangAdapter,
    "daangn": DaangnAdapter,
    "joonggonara": JoonggonaraAdapter,
    "naver_shop": NaverShopAdapter,
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crawl phone/MacBook used listings against seeded products.",
    )
    parser.add_argument("source", choices=sorted(_ADAPTERS))
    parser.add_argument("--category", choices=sorted(CONSUMER_CATEGORIES), required=True)
    parser.add_argument("--queries", type=str, default=None)
    parser.add_argument("--pages", type=int, default=1)
    args = parser.parse_args()

    queries = [q.strip() for q in args.queries.split(",") if q.strip()] if args.queries else query_seeds_for_category(args.category)
    if not queries:
        print(f"error: no seed queries for category {args.category!r}", file=sys.stderr)
        sys.exit(2)

    db = get_client()
    run_used(db, _ADAPTERS[args.source](), category=args.category, queries=queries, pages=args.pages)


if __name__ == "__main__":
    main()
