#!/usr/bin/env python3
"""Collect source-provided reference market prices into Supabase."""

from __future__ import annotations

import argparse
import traceback
from typing import Iterable

from src.adapters.cetizen_price import CetizenPriceAdapter
from src.adapters.joongna_price import JoongnaPriceAdapter
from src.adapters.market_price import MarketPriceObservation
from src.adapters.usedking_iphone import UsedKingIphoneAdapter
from src.clients.supabase_client import get_client
from src.domains.consumer.catalog import query_seeds_for_category
from src.services.ingest import upsert_market_price_observations


_USEDKING_IPHONE_MODELS = (
    "13",
    "14",
    "15",
    "15PRO",
    "15PROMAX",
    "16",
    "16PRO",
    "16PROMAX",
)
_USEDKING_CAPACITIES = ("128GB", "256GB", "512GB", "1TB")


def _safe_collect(label: str, fn) -> list[MarketPriceObservation]:
    try:
        rows = fn()
        print(f"  [{label}] collected {len(rows)} observations")
        return rows
    except Exception:
        print(f"  [{label}] failed:")
        traceback.print_exc()
        return []


def _joongna_keywords(limit: int) -> list[str]:
    keywords: list[str] = []
    for category in ("iphone", "galaxy"):
        keywords.extend(query_seeds_for_category(category))
    if limit > 0:
        return keywords[:limit]
    return keywords


def collect_market_prices(
    *,
    include_cetizen: bool = True,
    joongna_limit: int = 8,
    usedking_days: str = "30days",
) -> list[MarketPriceObservation]:
    observations: list[MarketPriceObservation] = []

    if include_cetizen:
        observations.extend(
            _safe_collect("cetizen_price", CetizenPriceAdapter().fetch_prices)
        )

    joongna = JoongnaPriceAdapter()
    for keyword in _joongna_keywords(joongna_limit):
        observations.extend(
            _safe_collect(
                f"joongna_price/{keyword}",
                lambda k=keyword: joongna.search_price(k),
            )
        )

    usedking = UsedKingIphoneAdapter()
    for model in _USEDKING_IPHONE_MODELS:
        for capacity in _USEDKING_CAPACITIES:
            observations.extend(
                _safe_collect(
                    f"usedking_iphone/{model}/{capacity}",
                    lambda m=model, c=capacity: usedking.search_price(
                        m, capacity=c, days=usedking_days
                    ),
                )
            )

    return observations


def _is_linkable_observation(observation: MarketPriceObservation) -> bool:
    if observation.canonical_key:
        return True
    return bool(
        observation.category
        and observation.storage_gb
        and (observation.model or observation.keyword)
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-cetizen",
        action="store_true",
        help="Skip Cetizen aggregate phone price table",
    )
    parser.add_argument(
        "--joongna-limit",
        type=int,
        default=8,
        help="Number of Joongna search-price keywords to query; 0 means all seeds",
    )
    parser.add_argument(
        "--usedking-days",
        type=str,
        default="30days",
        help="UsedKing transaction window parameter",
    )
    args = parser.parse_args()

    observations = collect_market_prices(
        include_cetizen=not args.skip_cetizen,
        joongna_limit=args.joongna_limit,
        usedking_days=args.usedking_days,
    )
    linkable_observations = [o for o in observations if _is_linkable_observation(o)]
    skipped = len(observations) - len(linkable_observations)
    if skipped:
        print(f"Skipped {skipped} unkeyed market price observations")
    result = upsert_market_price_observations(get_client(), linkable_observations)
    print(f"Persisted {result['observations']} market price observations")


if __name__ == "__main__":
    main()
