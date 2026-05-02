"""Bunjang public search-API adapter.

Verified against live API on 2026-04-26.

Endpoint: https://api.bunjang.co.kr/api/1/find_v2.json
Params:   q=<query>, order=score, page=<0-based>, n=<count>
Response: { "list": [ { pid, name, price, status, ad, location, ... } ] }
Status:   "0" → selling, "1" → reserved, "2"/"3" → sold
"""

from __future__ import annotations

import json
import time

import httpx

from src.adapters.base import (
    STATUS_RESERVED,
    STATUS_SELLING,
    STATUS_SOLD,
    STATUS_UNKNOWN,
    SourceAdapter,
    UsedListing,
    parse_price_int,
)

_API = "https://api.bunjang.co.kr/api/1/find_v2.json"
_WEB_PRODUCT = "https://m.bunjang.co.kr/products/"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
    "Referer": "https://m.bunjang.co.kr/",
}

_STATUS_MAP = {
    "0": STATUS_SELLING,
    "1": STATUS_RESERVED,
    "2": STATUS_SOLD,
    "3": STATUS_SOLD,
}


def parse_response(payload: str | dict) -> list[UsedListing]:
    data = json.loads(payload) if isinstance(payload, str) else payload
    out: list[UsedListing] = []
    for item in data.get("list", []) or []:
        if item.get("ad"):
            continue
        pid = str(item.get("pid", "")).strip()
        name = (item.get("name") or "").strip()
        if not pid or not name:
            continue
        raw_price = item.get("price")
        price = parse_price_int(raw_price)
        status = _STATUS_MAP.get(str(item.get("status")), STATUS_UNKNOWN)
        location = (item.get("location") or "").strip() or None
        out.append(
            UsedListing(
                source="bunjang",
                listing_id=pid,
                title=name,
                price=price,
                price_raw=str(raw_price) if raw_price is not None else None,
                url=f"{_WEB_PRODUCT}{pid}",
                status=status,
                location=location,
            )
        )
    return out


class BunjangAdapter(SourceAdapter):
    source_name = "bunjang"

    def __init__(self, sleep_seconds: float = 0.5, page_size: int = 30):
        self.sleep_seconds = sleep_seconds
        self.page_size = page_size

    def _fetch(self, query: str, page: int) -> str:
        params = {
            "q": query,
            "order": "score",
            "page": page,
            "n": self.page_size,
        }
        with httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=20) as c:
            resp = c.get(_API, params=params)
            resp.raise_for_status()
        return resp.text

    def search(
        self,
        query: str,
        *,
        category: str | None = None,  # noqa: ARG002
        pages: int = 1,
    ) -> list[UsedListing]:
        out: list[UsedListing] = []
        for p in range(pages):
            try:
                body = self._fetch(query, p)
            except httpx.HTTPError as e:
                print(f"  [bunjang] '{query}' page {p} failed: {e}")
                break
            listings = parse_response(body)
            out.extend(listings)
            if not listings:
                break
            if p < pages - 1:
                time.sleep(self.sleep_seconds)
        return out

    def fetch_recent(
        self,
        *,
        pages: int = 1,  # noqa: ARG002
        category: str | None = None,  # noqa: ARG002
    ) -> list[UsedListing]:
        # Bunjang has no flat "recent" feed without a query.
        return []
