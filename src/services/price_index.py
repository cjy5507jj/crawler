"""App-facing price index primitives.

This layer combines C2C used-market stats, B2C/refurb snapshots, and Danawa new
prices into a compact shape that a lowest-price app or C2B offer engine can
consume without understanding crawler internals.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class PriceIndex:
    product_id: str
    domain: str
    category: str
    canonical_key: str | None
    specs: dict
    c2c_used_count: int
    c2c_used_min: int | None
    c2c_used_median: int | None
    b2c_min: int | None
    new_price: int | None
    lowest_available_price: int | None
    buy_offer_price: int | None
    confidence_score: float


def _min_positive(values: Iterable[int | None]) -> int | None:
    prices = [int(v) for v in values if v is not None and int(v) > 0]
    return min(prices) if prices else None


def _valid_b2c_prices(
    values: Iterable[int | None],
    *,
    c2c_used_count: int,
    c2c_used_median: int | None,
) -> list[int]:
    prices = [int(v) for v in values if v is not None and int(v) > 0]
    if c2c_used_count >= 3 and c2c_used_median is not None:
        floor = int(c2c_used_median * 0.5)
        prices = [p for p in prices if p >= floor]
    return prices


def _confidence(c2c_used_count: int, b2c_min: int | None, new_price: int | None) -> float:
    # C2C count is the strongest signal. B2C/new prices are supporting anchors.
    score = min(max(c2c_used_count, 0) / 10, 0.8)
    if c2c_used_count > 0:
        return round(score, 2)
    if b2c_min is not None:
        score += 0.15
    if new_price is not None:
        score += 0.10
    return round(min(score, 1.0), 2)


def compute_price_index(
    *,
    product_id: str,
    domain: str,
    category: str,
    canonical_key: str | None,
    specs: dict,
    c2c_used_count: int,
    c2c_used_min: int | None,
    c2c_used_median: int | None,
    new_price: int | None,
    b2c_prices: Iterable[int | None],
) -> PriceIndex:
    b2c_min = _min_positive(
        _valid_b2c_prices(
            b2c_prices,
            c2c_used_count=c2c_used_count,
            c2c_used_median=c2c_used_median,
        )
    )
    lowest_available_price = _min_positive([c2c_used_min, b2c_min, new_price])
    buy_offer_price = None
    if c2c_used_median is not None and c2c_used_count >= 3:
        # Conservative C2B anchor: leave room for inspection risk, margin, and
        # stale listings. This should become category/condition-specific later.
        buy_offer_price = int(c2c_used_median * 0.8)

    return PriceIndex(
        product_id=product_id,
        domain=domain,
        category=category,
        canonical_key=canonical_key,
        specs=specs,
        c2c_used_count=c2c_used_count,
        c2c_used_min=c2c_used_min,
        c2c_used_median=c2c_used_median,
        b2c_min=b2c_min,
        new_price=new_price,
        lowest_available_price=lowest_available_price,
        buy_offer_price=buy_offer_price,
        confidence_score=_confidence(c2c_used_count, b2c_min, new_price),
    )
