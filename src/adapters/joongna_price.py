"""Joongna search-price parser for aggregate market-price pages."""

from __future__ import annotations

import re
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

from src.adapters.market_price import MarketPriceObservation
from src.domains.consumer.normalization import infer_consumer_product

_BASE = "https://web.joongna.com"
_WON_RE = re.compile(r"([0-9][0-9,]*)\s*원")
_LABELED_PRICE_RE = re.compile(r"(시세|평균|최저|최고)[^0-9]{0,12}([0-9][0-9,]*)\s*원")


def _to_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value.replace(",", ""))
    except ValueError:
        return None


def parse_search_price(html: str, *, keyword: str, url: str | None = None) -> list[MarketPriceObservation]:
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)
    labeled: dict[str, int] = {}
    for label, amount in _LABELED_PRICE_RE.findall(text):
        price = _to_int(amount)
        if price is not None:
            labeled[label] = price
    prices = [_to_int(m.group(1)) for m in _WON_RE.finditer(text)]
    prices = [p for p in prices if p and p > 0]

    observations: list[MarketPriceObservation] = []
    if labeled or prices:
        observations.append(
            MarketPriceObservation(
                source="joongna_price",
                observation_id=f"{keyword}:aggregate",
                keyword=keyword,
                avg_price=labeled.get("평균") or labeled.get("시세") or (prices[0] if prices else None),
                min_price=labeled.get("최저") or (min(prices) if prices else None),
                max_price=labeled.get("최고") or (max(prices) if prices else None),
                sample_count=len(prices),
                price_type="aggregate",
                url=url,
            )
        )

    for a in soup.select('a[href^="/product/"]'):
        href = (a.get("href") or "").split("?", 1)[0]
        m_id = re.match(r"^/product/(\d+)$", href)
        if not m_id:
            continue
        card_text = a.get_text(" ", strip=True)
        m_price = _WON_RE.search(card_text)
        price = _to_int(m_price.group(1)) if m_price else None
        title = card_text[: m_price.start()].strip() if m_price else card_text
        norm = infer_consumer_product(title)
        observations.append(
            MarketPriceObservation(
                source="joongna_price",
                observation_id=f"{keyword}:product:{m_id.group(1)}",
                keyword=keyword,
                brand=norm.brand if norm else None,
                domain=norm.domain if norm else None,
                category=norm.category if norm else None,
                model=norm.model if norm else None,
                storage_gb=norm.storage_gb if norm else None,
                canonical_key=norm.canonical_key if norm else None,
                price=price,
                price_type="listing_sample",
                url=f"{_BASE}{href}",
                raw_title=title,
            )
        )
    return observations


class JoongnaPriceAdapter:
    source_name = "joongna_price"

    def search_price(self, keyword: str) -> list[MarketPriceObservation]:
        url = f"{_BASE}/search-price/{quote(keyword)}"
        response = httpx.get(url, timeout=30, follow_redirects=True)
        response.raise_for_status()
        return parse_search_price(response.text, keyword=keyword, url=url)
