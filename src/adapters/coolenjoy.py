"""Coolenjoy 회원장터(/bbs/mart2) used-market adapter.

Verified against live page on 2026-04-26.
- list container:  ul.na-table > li
- title link:      a.na-subject  (href ends with /bbs/mart2/<wr_id>)
- price cell:      sibling div containing <span class="sr-only">판매가</span>
- notice rows:     contain "공지" text or have id="abcd" marker
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

_BASE = "https://coolenjoy.net"
_BOARD = "mart2"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
}

_NUM_RE = re.compile(r"\d[\d,]*")


def _parse_price(text: str | None) -> tuple[int | None, str | None]:
    if not text:
        return None, None
    match = _NUM_RE.search(text)
    if not match:
        return None, text.strip() or None
    raw = match.group(0)
    try:
        return int(raw.replace(",", "")), text.strip()
    except ValueError:
        return None, text.strip()


def _detect_status(title: str, raw_price: str | None) -> str:
    lowered = title.lower()
    if any(k in title for k in ("판매완료", "거래완료", "완료")):
        return STATUS_SOLD
    if any(k in title for k in ("예약", "예약중")):
        return STATUS_RESERVED
    if raw_price and "본문참고" in raw_price:
        return STATUS_UNKNOWN
    if any(k in lowered for k in ("sold", "[done]", "[완료]")):
        return STATUS_SOLD
    return STATUS_SELLING


def _is_notice(li: Tag) -> bool:
    title_anchor = li.select_one("a.na-subject")
    if not title_anchor:
        return True
    # Notice rows wrap the title in <strong><b class="text-white">...
    if title_anchor.select_one("b.text-white") or title_anchor.select_one("strong b"):
        return True
    text = title_anchor.get_text(" ", strip=True)
    return text.startswith("공지") or "공지사항" in text


def parse_list(html: str) -> list[UsedListing]:
    soup = BeautifulSoup(html, "lxml")
    out: list[UsedListing] = []
    for li in soup.select("ul.na-table > li"):
        if _is_notice(li):
            continue
        anchor = li.select_one("a.na-subject")
        if not anchor:
            continue
        href = anchor.get("href") or ""
        if not href:
            continue
        url = href if href.startswith("http") else f"{_BASE}{href}"
        m = re.search(r"/bbs/[^/]+/(\d+)", url)
        if not m:
            continue
        listing_id = m.group(1)

        title = anchor.get_text(" ", strip=True)
        # Find the price cell: search for the sr-only label "판매가"
        raw_price: str | None = None
        for label in li.select("span.sr-only"):
            if label.get_text(strip=True) == "판매가":
                container = label.parent
                if container is not None:
                    raw_price = (
                        container.get_text(" ", strip=True).replace("판매가", "").strip()
                    )
                break

        price, price_raw = _parse_price(raw_price)
        status = _detect_status(title, raw_price)

        out.append(
            UsedListing(
                source="coolenjoy",
                listing_id=listing_id,
                title=title,
                price=price,
                price_raw=price_raw,
                url=url,
                status=status,
            )
        )
    return out


class CoolenjoyAdapter(SourceAdapter):
    source_name = "coolenjoy"

    def __init__(self, board: str = _BOARD, sleep_seconds: float = 1.0):
        self.board = board
        self.sleep_seconds = sleep_seconds

    def _fetch(self, page: int) -> str:
        params = {"page": page} if page > 1 else None
        with httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=20) as c:
            resp = c.get(f"{_BASE}/bbs/{self.board}", params=params)
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
                print(f"  [coolenjoy] page {p} fetch failed: {e}")
                break
            listings = parse_list(html)
            out.extend(listings)
            print(f"  [coolenjoy] page {p}: +{len(listings)} listings")
            if p < pages:
                time.sleep(self.sleep_seconds)
        return out

    def search(
        self,
        query: str,
        *,
        category: str | None = None,  # noqa: ARG002
    ) -> list[UsedListing]:
        params = {"sfl": "wr_subject", "stx": query}
        with httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=20) as c:
            try:
                resp = c.get(f"{_BASE}/bbs/{self.board}", params=params)
                resp.raise_for_status()
            except httpx.HTTPError as e:
                print(f"  [coolenjoy] search '{query}' failed: {e}")
                return []
        return parse_list(resp.text)
