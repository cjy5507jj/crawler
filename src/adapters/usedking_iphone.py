"""UsedKing iPhone transaction sample parser."""

from __future__ import annotations

import re
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup

from src.adapters.market_price import MarketPriceObservation
from src.domains.consumer.normalization import infer_consumer_product

_URL = "https://usedking.xyz/iphone/"


def _to_int(value: str) -> int | None:
    try:
        return int(re.sub(r"[^0-9]", "", value))
    except ValueError:
        return None


def _storage_gb(value: str) -> int | None:
    text = value.strip().lower()
    m = re.search(r"(\d+)\s*tb", text)
    if m:
        return int(m.group(1)) * 1024
    m = re.search(r"(\d+)\s*(?:gb|g)?", text)
    if m:
        return int(m.group(1))
    return None


def _usedking_iphone_title(model: str, storage_gb: int | None) -> str:
    text = model.lower().replace("iphone", "")
    suffix = ""
    for raw, normalized in (
        ("promax", "pro max"),
        ("pro", "pro"),
        ("plus", "plus"),
        ("mini", "mini"),
        ("e", "e"),
    ):
        if raw in text:
            suffix = normalized
            text = text.replace(raw, "")
            break
    generation = re.sub(r"[^0-9]", "", text)
    storage = "1TB" if storage_gb == 1024 else "2TB" if storage_gb == 2048 else f"{storage_gb}GB" if storage_gb else None
    bits = ["iphone", generation, suffix, storage]
    return " ".join(b for b in bits if b)


def parse_iphone_table(html: str, *, model: str | None = None, days: str | None = None, url: str = _URL) -> list[MarketPriceObservation]:
    soup = BeautifulSoup(html, "lxml")
    observations: list[MarketPriceObservation] = []
    rows = soup.select("table tr")
    for row in rows:
        cells = [c.get_text(" ", strip=True) for c in row.select("td")]
        if len(cells) < 6 or not cells[0].isdigit():
            continue
        price = _to_int(cells[3])
        storage = _storage_gb(cells[2])
        norm = infer_consumer_product(_usedking_iphone_title(cells[1], storage))
        observations.append(
            MarketPriceObservation(
                source="usedking_iphone",
                observation_id=f"{cells[1]}:{cells[2]}:{cells[3]}:{cells[4]}:{cells[5]}",
                domain=norm.domain if norm else None,
                category="iphone",
                model=cells[1],
                storage_gb=storage,
                canonical_key=norm.canonical_key if norm else None,
                price=price,
                price_type="transaction_sample",
                sample_window=days,
                trade_date=cells[5],
                url=url,
                raw_title=cells[4],
            )
        )
    if observations:
        return observations

    text = soup.get_text(" ", strip=True)
    if "거래가 없습니다" in text:
        return []
    return []


class UsedKingIphoneAdapter:
    source_name = "usedking_iphone"

    def search_price(self, model: str, *, capacity: str = "", days: str = "30days") -> list[MarketPriceObservation]:
        query = urlencode({"select_gpu": model, "select_capa": capacity, "days": days})
        url = f"{_URL}?{query}"
        response = httpx.get(url, timeout=30, follow_redirects=True)
        response.raise_for_status()
        return parse_iphone_table(response.text, model=model, days=days, url=url)
