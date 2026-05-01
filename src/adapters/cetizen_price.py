"""Cetizen used-phone price table parser."""

from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup

from src.adapters.market_price import MarketPriceObservation
from src.domains.consumer.normalization import infer_consumer_product

_URL = "https://price.cetizen.com/price.php"
_ROW_RE = re.compile(
    r"(?P<aliases>\[[^\n]+\])\s*(?P<model>[^\n]+?)\s+"
    r"(?P<storage1>\d+(?:GB|TB))(?P<price1>[0-9,]+)\s+"
    r"(?P<storage2>\d+(?:GB|TB))(?P<price2>[0-9,]+)\s+"
    r"(?P<release>\d{4}-\d{2}-\d{2})",
    re.I,
)


def _price(value: str) -> int | None:
    try:
        return int(value.replace(",", ""))
    except ValueError:
        return None


def _storage(value: str) -> int | None:
    m = re.match(r"(\d+)(GB|TB)", value, re.I)
    if not m:
        return None
    gb = int(m.group(1))
    return gb * 1024 if m.group(2).lower() == "tb" else gb


def parse_price_table(html: str, *, url: str = _URL) -> list[MarketPriceObservation]:
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text("\n", strip=True)
    observations: list[MarketPriceObservation] = []
    for match in _ROW_RE.finditer(text):
        model = re.sub(r"\s+", " ", match.group("model")).strip()
        aliases = match.group("aliases")
        for idx in ("1", "2"):
            storage_raw = match.group(f"storage{idx}")
            price = _price(match.group(f"price{idx}"))
            storage = _storage(storage_raw)
            if price is None or storage is None:
                continue
            norm = infer_consumer_product(f"{model} {storage}GB")
            observations.append(
                MarketPriceObservation(
                    source="cetizen_price",
                    observation_id=f"{model}:{storage}gb:{idx}",
                    brand=norm.brand if norm else None,
                    domain=norm.domain if norm else None,
                    category=norm.category if norm else None,
                    model=model,
                    storage_gb=storage,
                    canonical_key=norm.canonical_key if norm else None,
                    avg_price=price,
                    price_type="completed_safe_trade_average",
                    release_date=match.group("release"),
                    url=url,
                    raw_title=model,
                    metadata={"aliases": aliases},
                )
            )
    return observations


class CetizenPriceAdapter:
    source_name = "cetizen_price"

    def fetch_prices(self) -> list[MarketPriceObservation]:
        response = httpx.get(_URL, timeout=30, follow_redirects=True)
        response.raise_for_status()
        html = response.content.decode("euc-kr", errors="replace")
        return parse_price_table(html, url=_URL)
