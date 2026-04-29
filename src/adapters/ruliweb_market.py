"""Ruliweb 핫딜 중고장터 (PC 하드웨어 board=45) used-market adapter.

Verified against live page on 2026-04-29 (Day 3 probe → Day 4 implementation).

URL:        https://bbs.ruliweb.com/market/board/45
Pagination: ?page=N (1-based)
List:       table.board_list_table > tbody > tr.table_body
Cells:      td.id, td.region, td.market_type ([판매]/[구매]/[교환]),
            td.subject (a.deco href=".../read/{N}"), td.writer, td.time

The board mixes 판매/구매/교환 — buy ([구매]) and exchange ([교환]) requests are
not used-market price evidence, so the adapter emits only [판매] rows by default.
The market_type marker is preserved on metadata so downstream filtering can be
revisited without reparsing.

Price is embedded in the title (no dedicated column) — same pattern as
joonggonara/coolenjoy. The matcher's existing title-based pricing is unchanged;
the adapter does a best-effort extraction so price-aware UIs still work.
"""

from __future__ import annotations

import re
import time

import httpx
from bs4 import BeautifulSoup, Tag

from src.adapters.base import (
    STATUS_RESERVED,
    STATUS_SELLING,
    STATUS_SOLD,
    STATUS_UNKNOWN,
    SourceAdapter,
    UsedListing,
)

_BASE = "https://bbs.ruliweb.com"
_BOARD = "/market/board/45"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
    "Referer": "https://bbs.ruliweb.com/market",
}

# Title price extraction: "30만원", "300,000원", "30만 원", "30 만원"
_PRICE_RE = re.compile(
    r"(?P<num>\d[\d,]*)\s*(?P<unit>만\s*원|만원|원|만)|"
    r"(?P<words>[가-힣]+\s*만\s*원)"
)
_KOREAN_NUM = {
    "일": 1, "이": 2, "삼": 3, "사": 4, "오": 5,
    "육": 6, "칠": 7, "팔": 8, "구": 9, "십": 10,
}


def _parse_korean_words_to_int(text: str) -> int | None:
    """Best-effort: '오십만원' → 500000. Falls back to None for unparseable forms."""
    digits = [_KOREAN_NUM[c] for c in text if c in _KOREAN_NUM]
    if not digits:
        return None
    if len(digits) == 1:
        return digits[0] * 10000
    if len(digits) == 2 and digits[-1] == 10:
        return digits[0] * 100000
    return None


def _extract_price(title: str) -> tuple[int | None, str | None]:
    if not title:
        return None, None
    for m in _PRICE_RE.finditer(title):
        if m.group("num"):
            num_raw = m.group("num").replace(",", "")
            unit = (m.group("unit") or "").replace(" ", "")
            try:
                n = int(num_raw)
            except ValueError:
                continue
            if unit.startswith("만"):
                return n * 10000, m.group(0).strip()
            return n, m.group(0).strip()
        if m.group("words"):
            v = _parse_korean_words_to_int(m.group("words"))
            if v is not None:
                return v, m.group(0).strip()
    return None, None


def _detect_status(title: str) -> str:
    if any(k in title for k in ("판매완료", "거래완료", "완료", "[판매완료]")):
        return STATUS_SOLD
    if any(k in title for k in ("예약", "예약중")):
        return STATUS_RESERVED
    lowered = title.lower()
    if any(k in lowered for k in ("sold", "[done]", "[완료]")):
        return STATUS_SOLD
    return STATUS_SELLING


def _row_market_type(tr: Tag) -> str | None:
    cell = tr.select_one("td.market_type")
    if not cell:
        return None
    text = cell.get_text(" ", strip=True)
    # Ruliweb wraps the marker as "[판매]" / "[구매]" / "[교환]"
    m = re.search(r"\[(판매|구매|교환|판매완료)\]", text)
    return m.group(1) if m else None


def parse_list(
    html: str,
    *,
    sale_only: bool = True,
) -> list[UsedListing]:
    """Pure parser — Ruliweb board=45 list HTML → list[UsedListing].

    sale_only=True (default) drops [구매]/[교환] rows since those are not
    used-market price evidence. Pass False to widen for analytics.
    """
    soup = BeautifulSoup(html, "lxml")
    out: list[UsedListing] = []
    for tr in soup.select("table.board_list_table > tbody > tr.table_body"):
        market_type = _row_market_type(tr)
        if sale_only and market_type and market_type not in ("판매", "판매완료"):
            continue

        anchor = tr.select_one("td.subject a.deco")
        if not anchor:
            continue
        href = anchor.get("href") or ""
        m = re.search(r"/market/board/\d+/read/(\d+)", href)
        if not m:
            continue
        listing_id = m.group(1)
        url = href if href.startswith("http") else f"{_BASE}{href}"
        title = anchor.get_text(" ", strip=True)
        if not title:
            continue

        price, price_raw = _extract_price(title)
        status = _detect_status(title)

        region_cell = tr.select_one("td.region")
        location = (
            region_cell.get_text(" ", strip=True) if region_cell else ""
        ) or None

        metadata: dict[str, str] = {}
        if market_type:
            metadata["market_type"] = market_type
        time_cell = tr.select_one("td.time")
        if time_cell:
            t = time_cell.get_text(" ", strip=True)
            if t:
                metadata["posted_label"] = t

        out.append(
            UsedListing(
                source="ruliweb_market",
                listing_id=listing_id,
                title=title,
                price=price,
                price_raw=price_raw,
                url=url,
                status=status,
                location=location,
                metadata=metadata,
            )
        )
    return out


class RuliwebMarketAdapter(SourceAdapter):
    source_name = "ruliweb_market"

    def __init__(
        self,
        *,
        board_path: str = _BOARD,
        sleep_seconds: float = 1.0,
        sale_only: bool = True,
    ):
        self.board_path = board_path
        self.sleep_seconds = sleep_seconds
        self.sale_only = sale_only

    def _fetch(self, page: int) -> str:
        params = {"page": page} if page > 1 else None
        with httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=20) as c:
            resp = c.get(f"{_BASE}{self.board_path}", params=params)
            resp.raise_for_status()
        return resp.text

    def fetch_recent(
        self,
        *,
        pages: int = 1,
        category: str | None = None,  # noqa: ARG002 (board has no category split)
    ) -> list[UsedListing]:
        out: list[UsedListing] = []
        for p in range(1, pages + 1):
            try:
                html = self._fetch(p)
            except httpx.HTTPError as e:
                print(f"  [ruliweb_market] page {p} fetch failed: {e}")
                break
            listings = parse_list(html, sale_only=self.sale_only)
            out.extend(listings)
            print(f"  [ruliweb_market] page {p}: +{len(listings)} listings")
            if p < pages:
                time.sleep(self.sleep_seconds)
        return out

    def search(
        self,
        query: str,  # noqa: ARG002
        *,
        category: str | None = None,  # noqa: ARG002
    ) -> list[UsedListing]:
        # Board search exists (?search_type=subject&search_key=) but the board
        # is small enough that page-walking covers all relevant rows; reserve
        # search for future per-category targeting if recall demands it.
        return []
