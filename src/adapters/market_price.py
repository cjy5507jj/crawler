from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MarketPriceObservation:
    source: str
    observation_id: str
    keyword: str | None = None
    brand: str | None = None
    domain: str | None = None
    category: str | None = None
    model: str | None = None
    storage_gb: int | None = None
    canonical_key: str | None = None
    price: int | None = None
    avg_price: int | None = None
    min_price: int | None = None
    max_price: int | None = None
    sample_count: int | None = None
    price_type: str | None = None
    sample_window: str | None = None
    release_date: str | None = None
    trade_date: str | None = None
    url: str | None = None
    raw_title: str | None = None
    metadata: dict[str, str | int | None] = field(default_factory=dict)
