from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Product:
    category: str
    source: str
    source_id: str
    name: str
    brand: str | None = None
    model_name: str | None = None
    normalized_name: str | None = None
    url: str | None = None


@dataclass
class PriceSnapshot:
    product_id: str
    price: int
    market_type: str = "new"
    source: str | None = None
    shop_name: str | None = None


@dataclass
class UsedMarketRecord:
    source: str
    listing_id: str
    title: str
    price: int | None = None
    price_raw: str | None = None
    status: str | None = None
    url: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)
