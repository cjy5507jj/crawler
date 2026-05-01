"""UsedKing iPhone transaction sample parser."""

from __future__ import annotations

import re
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup

from src.adapters.market_price import MarketPriceObservation

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


def parse_iphone_table(html: str, *, model: str | None = None, days: str | None = None, url: str = _URL) -> list[MarketPriceObservation]:
    soup = BeautifulSoup(html, "lxml")
    observations: list[MarketPriceObservation] = []
    rows = soup.select("table tr")
    for row in rows:
        cells = [c.get_text(" ", strip=True) for c in row.select("td")]
        if len(cells) < 6 or not cells[0].isdigit():
            continue
        price = _to_int(cells[3])
        observations.append(
            MarketPriceObservation(
                source="usedking_iphone",
                observation_id=f"{cells[1]}:{cells[2]}:{cells[3]}:{cells[4]}:{cells[5]}",
                category="iphone",
                model=cells[1],
                storage_gb=_storage_gb(cells[2]),
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
