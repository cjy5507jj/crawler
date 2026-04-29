#!/usr/bin/env python3
"""Manual entrypoint — crawl a used-market source for a single category."""

from __future__ import annotations

import argparse
import sys

from src.adapters.bunjang import BunjangAdapter
from src.adapters.coolenjoy import CoolenjoyAdapter
from src.adapters.daangn import DaangnAdapter
from src.adapters.joonggonara import JoonggonaraAdapter
from src.adapters.naver_shop import NaverShopAdapter
from src.adapters.quasarzone import QuasarzoneAdapter
from src.clients.supabase_client import get_client
from src.crawlers.danawa import CATEGORY_MAP
from src.services.ingest import run_used


_ADAPTERS = {
    "coolenjoy": CoolenjoyAdapter,
    "quasarzone": QuasarzoneAdapter,
    "bunjang": BunjangAdapter,
    "daangn": DaangnAdapter,
    "joonggonara": JoonggonaraAdapter,
    "naver_shop": NaverShopAdapter,
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crawl a used-market source and store listings in Supabase.",
    )
    parser.add_argument("source", choices=sorted(_ADAPTERS), help="Used-market source")
    parser.add_argument(
        "--category",
        choices=sorted(CATEGORY_MAP),
        required=True,
        help="PC part category to ingest into",
    )
    parser.add_argument(
        "--queries",
        type=str,
        default=None,
        help='Comma-separated search queries, e.g. "5600X,7800X3D"',
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=1,
        metavar="N",
        help="Pages to fetch for board-style sources (default: 1)",
    )
    args = parser.parse_args()

    adapter = _ADAPTERS[args.source]()

    queries = None
    if args.queries:
        queries = [q.strip() for q in args.queries.split(",") if q.strip()]
    elif args.source in {"bunjang", "daangn", "joonggonara", "naver_shop"}:
        print(
            f"error: --queries is required for source '{args.source}' "
            "(no flat recent feed)",
            file=sys.stderr,
        )
        sys.exit(2)

    db = get_client()
    run_used(db, adapter, category=args.category, queries=queries, pages=args.pages)


if __name__ == "__main__":
    main()
