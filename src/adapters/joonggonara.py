"""Joonggonara (web.joongna.com) search adapter — Playwright-rendered.

Verified against live page on 2026-04-26.

Strategy:
  - Public search URL: https://web.joongna.com/search/<query>
  - Server response includes the product cards but the page also requires
    JS hydration to render the full list reliably; we use Playwright to
    render and then parse anchor + price tokens from the rendered HTML.
  - The default search view EXCLUDES 판매완료 items via a built-in filter
    ("판매완료 상품 제외"), so every visible card is by definition currently
    listed for sale → status defaults to "selling".

Per-card structure (verified after render):
  <a href="/product/<id>"> with text segmented by spaces:
    "<title> <price> 원 [chat-count] [reply-count] <time-ago> [무료배송]"
"""

from __future__ import annotations

import re
import time
from urllib.parse import quote

from bs4 import BeautifulSoup

from src.adapters.base import (
    STATUS_SELLING,
    STATUS_UNKNOWN,
    SourceAdapter,
    UsedListing,
)

_BASE = "https://web.joongna.com"
_PATH_RE = re.compile(r"^/product/(\d+)$")
_PRICE_TOKEN_RE = re.compile(r"^\d{1,3}(?:,\d{3})+$|^\d{4,}$")


def _parse_anchor_text(text: str) -> tuple[str, int | None, str | None]:
    parts = [p.strip() for p in text.split("|") if p.strip()]
    if not parts:
        return "", None, None
    title = parts[0]
    price: int | None = None
    price_raw: str | None = None
    for token in parts[1:]:
        if _PRICE_TOKEN_RE.match(token):
            price_raw = token
            try:
                price = int(token.replace(",", ""))
            except ValueError:
                price = None
            break
    return title, price, price_raw


def parse_list(html: str) -> list[UsedListing]:
    """Pure parser — works on either statically fetched OR rendered HTML."""
    soup = BeautifulSoup(html, "lxml")
    out: list[UsedListing] = []
    seen: set[str] = set()
    for a in soup.select('a[href^="/product/"]'):
        href = a.get("href") or ""
        path = href.split("?", 1)[0]
        m = _PATH_RE.match(path)
        if not m:
            continue
        listing_id = m.group(1)
        if listing_id in seen:
            continue
        seen.add(listing_id)

        text = a.get_text("|", strip=True)
        title, price, price_raw = _parse_anchor_text(text)
        if not title:
            continue

        out.append(
            UsedListing(
                source="joonggonara",
                listing_id=listing_id,
                title=title,
                price=price,
                price_raw=price_raw,
                url=f"{_BASE}{path}",
                # Search filter excludes 판매완료, so visible items are selling.
                status=STATUS_SELLING,
            )
        )
    return out


class JoonggonaraAdapter(SourceAdapter):
    source_name = "joonggonara"

    def __init__(self, sleep_seconds: float = 1.0, headless: bool = True):
        self.sleep_seconds = sleep_seconds
        self.headless = headless

    def _render(self, query: str, page: int) -> str:
        from src.adapters._browser import render_html

        url = f"{_BASE}/search/{quote(query)}"
        if page > 1:
            url += f"?page={page}"
        return render_html(
            url,
            wait_for_selector='a[href^="/product/"]',
            wait_until="networkidle",
            timeout_ms=30_000,
            extra_wait_ms=500,
        )

    def search(
        self,
        query: str,
        *,
        category: str | None = None,  # noqa: ARG002
        pages: int = 1,
    ) -> list[UsedListing]:
        out: list[UsedListing] = []
        for p in range(1, pages + 1):
            try:
                html = self._render(query, p)
            except Exception as e:
                print(f"  [joonggonara] '{query}' page {p} render failed: {e}")
                break
            listings = parse_list(html)
            out.extend(listings)
            print(f"  [joonggonara] '{query}' page {p}: +{len(listings)} listings")
            if not listings:
                break
            if p < pages:
                time.sleep(self.sleep_seconds)
        return out

    def fetch_recent(
        self,
        *,
        pages: int = 1,  # noqa: ARG002
        category: str | None = None,  # noqa: ARG002
    ) -> list[UsedListing]:
        return []
