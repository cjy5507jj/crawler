"""Daangn (당근마켓) public-search adapter — Playwright-rendered.

Verified against live page on 2026-04-26.

Strategy:
  - Public search URL: https://www.daangn.com/kr/buy-sell/?search=<query>
  - SPA renders cards client-side; static HTML has no listings.
  - Render with headless Chromium, parse `a[data-gtm="search_article"]`.

Per-card structure (verified after render):
  <a data-gtm="search_article" href="/kr/buy-sell/<slug>-<id>/">
    [optional badge: "판매완료" / "예약중"]
    <title>
    <price>원
    <location> · 끌올 <time-ago>
"""

from __future__ import annotations

import re
import time
from urllib.parse import quote

from bs4 import BeautifulSoup

from src.adapters.base import (
    STATUS_RESERVED,
    STATUS_SELLING,
    STATUS_SOLD,
    STATUS_UNKNOWN,
    SourceAdapter,
    UsedListing,
)

_BASE = "https://www.daangn.com"
_HREF_ID_RE = re.compile(r"/kr/buy-sell/[^/]*-([a-z0-9]{8,})/?")
_PRICE_RE = re.compile(r"([\d,]+)\s*원")


def _detect_status(text: str) -> str:
    if "판매완료" in text or "거래완료" in text:
        return STATUS_SOLD
    if "예약중" in text:
        return STATUS_RESERVED
    return STATUS_SELLING


def parse_list(html: str) -> list[UsedListing]:
    soup = BeautifulSoup(html, "lxml")
    out: list[UsedListing] = []
    seen: set[str] = set()
    for a in soup.select('a[data-gtm="search_article"]'):
        href = a.get("href") or ""
        m = _HREF_ID_RE.search(href.split("?", 1)[0])
        if not m:
            continue
        listing_id = m.group(1)
        if listing_id in seen:
            continue
        seen.add(listing_id)

        # Children that hold the title cleanly: the smallest text-only
        # div that does NOT contain the price or "끌올". Fallback: full text.
        full_text = a.get_text(" ", strip=True)
        status = _detect_status(full_text)

        # Pull price
        price = price_raw = None
        pm = _PRICE_RE.search(full_text)
        if pm:
            price_raw = pm.group(0)
            try:
                price = int(pm.group(1).replace(",", ""))
            except ValueError:
                price = None

        # Title heuristic: pick the LONGEST child whose text is purely the
        # product name — no badge, no price, no "·", no "끌올", and not a
        # bare administrative-area token (e.g. "가산동").
        title = ""
        candidates: list[str] = []
        for el in a.find_all(["span", "div", "p"]):
            t = el.get_text(" ", strip=True)
            if not t or "원" in t or "끌올" in t or "·" in t:
                continue
            if t in ("판매완료", "거래완료", "예약중"):
                continue
            if re.match(r"^[가-힣A-Za-z0-9]{1,6}(?:동|구|시)$", t):
                continue  # location label
            candidates.append(t)
        if candidates:
            title = max(candidates, key=len)
        else:
            t = _PRICE_RE.sub("", full_text)
            for badge in ("판매완료", "거래완료", "예약중"):
                t = t.replace(badge, "")
            title = re.sub(r"\s*·.*$", "", t).strip()

        # Pull location: " · 끌올" segment usually preceded by location
        location = None
        loc_match = re.search(r"([가-힣A-Za-z0-9]+동|[가-힣]+구|[가-힣]+시)\s*·", full_text)
        if loc_match:
            location = loc_match.group(1)

        out.append(
            UsedListing(
                source="daangn",
                listing_id=listing_id,
                title=title,
                price=price,
                price_raw=price_raw,
                url=f"{_BASE}{href}",
                status=status,
                location=location,
            )
        )
    return out


class DaangnAdapter(SourceAdapter):
    source_name = "daangn"

    def __init__(self, sleep_seconds: float = 1.0):
        self.sleep_seconds = sleep_seconds

    def _render(self, query: str) -> str:
        from src.adapters._browser import render_html

        url = f"{_BASE}/kr/buy-sell/?search={quote(query)}"
        return render_html(
            url,
            wait_for_selector='a[data-gtm="search_article"]',
            wait_until="domcontentloaded",
            timeout_ms=30_000,
            extra_wait_ms=1500,
        )

    def search(
        self,
        query: str,
        *,
        category: str | None = None,  # noqa: ARG002
        pages: int = 1,  # noqa: ARG002 (Daangn search is single page in static markup)
    ) -> list[UsedListing]:
        try:
            html = self._render(query)
        except Exception as e:
            print(f"  [daangn] '{query}' render failed: {e}")
            return []
        listings = parse_list(html)
        print(f"  [daangn] '{query}': +{len(listings)} listings")
        time.sleep(self.sleep_seconds)
        return listings

    def fetch_recent(
        self,
        *,
        pages: int = 1,  # noqa: ARG002
        category: str | None = None,  # noqa: ARG002
    ) -> list[UsedListing]:
        return []
