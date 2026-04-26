"""Quasarzone adapter — public price-listing boards.

Verified against live page on 2026-04-26.

Quasarzone splits price-listing posts across multiple public boards:
- /bbs/qb_saleinfo         할인/세일정보 (community-shared deals)
- /bbs/qb_partnersaleinfo  파트너 핫딜 (partner hot deals)
- /bbs/qe_trade            라이브판매 (banner-heavy, mostly empty)

Plus one user-to-user marketplace that REQUIRES LOGIN:
- /bbs/qb_jijang           장터 — gated. To enable, pass `session_cookie=`
  to QuasarzoneAdapter (PHPSESSID from a logged-in browser session).
  Without it, fetch returns "목록을 볼 권한이 없습니다." and we skip.

Default boards: qb_saleinfo + qb_partnersaleinfo (both public, same DOM).

DOM contract per item (verified):
  div.market-info-list-cont
    a.subject-link              → href + title
    span.ellipsis-with-reply-cnt → title text
    span.label                  → status (진행중 / 종료 / 품절)
    span.text-orange / .text-info → price string with KRW
    span.category                → board sub-category
"""

from __future__ import annotations

import re
import time

import httpx
from bs4 import BeautifulSoup

from src.adapters.base import (
    STATUS_RESERVED,
    STATUS_SELLING,
    STATUS_SOLD,
    STATUS_UNKNOWN,
    SourceAdapter,
    UsedListing,
)

_BASE = "https://quasarzone.com"
_DEFAULT_BOARDS = ("qb_saleinfo", "qb_partnersaleinfo")
_GATED_HINT = "권한이 없습니다"

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
    cleaned = text.strip()
    match = _NUM_RE.search(cleaned)
    if not match:
        return None, cleaned or None
    try:
        return int(match.group(0).replace(",", "")), cleaned
    except ValueError:
        return None, cleaned


def _normalize_status(label_text: str | None) -> str:
    if not label_text:
        return STATUS_UNKNOWN
    text = label_text.strip()
    if any(k in text for k in ("진행중", "판매중", "선착순")):
        return STATUS_SELLING
    if any(k in text for k in ("품절", "종료", "마감", "완료")):
        return STATUS_SOLD
    if "예약" in text:
        return STATUS_RESERVED
    return STATUS_UNKNOWN


def parse_list(html: str, *, board: str = _DEFAULT_BOARDS[0]) -> list[UsedListing]:
    soup = BeautifulSoup(html, "lxml")
    out: list[UsedListing] = []
    for cont in soup.select("div.market-info-list-cont"):
        anchor = cont.select_one("a.subject-link")
        if not anchor:
            continue
        href = anchor.get("href") or ""
        if not href:
            continue
        url = href if href.startswith("http") else f"{_BASE}{href}"
        m = re.search(r"/views/(\d+)", url)
        if not m:
            continue
        listing_id = m.group(1)

        title_node = cont.select_one("span.ellipsis-with-reply-cnt") or anchor
        title = title_node.get_text(" ", strip=True)

        label = cont.select_one("span.label")
        status = _normalize_status(label.get_text(strip=True) if label else None)

        price_node = cont.select_one("span.text-orange") or cont.select_one(
            "span.text-info"
        )
        price, price_raw = _parse_price(
            price_node.get_text(" ", strip=True) if price_node else None
        )

        category_node = cont.select_one("span.category")
        metadata: dict[str, str] = {"board": board}
        if category_node:
            metadata["board_category"] = category_node.get_text(strip=True)

        out.append(
            UsedListing(
                source="quasarzone",
                listing_id=listing_id,
                title=title,
                price=price,
                price_raw=price_raw,
                url=url,
                status=status,
                metadata=metadata,
            )
        )
    return out


class QuasarzoneAdapter(SourceAdapter):
    source_name = "quasarzone"

    def __init__(
        self,
        boards: tuple[str, ...] | list[str] = _DEFAULT_BOARDS,
        session_cookie: str | None = None,
        sleep_seconds: float = 1.0,
    ):
        self.boards = tuple(boards)
        self.sleep_seconds = sleep_seconds
        self._cookies = (
            {"PHPSESSID": session_cookie} if session_cookie else None
        )

    def _fetch(self, board: str, page: int) -> str | None:
        params = {"page": page} if page > 1 else None
        with httpx.Client(
            headers=_HEADERS,
            cookies=self._cookies,
            follow_redirects=True,
            timeout=20,
        ) as c:
            resp = c.get(f"{_BASE}/bbs/{board}", params=params)
            resp.raise_for_status()
        if _GATED_HINT in resp.text:
            print(
                f"  [quasarzone/{board}] gated — supply session_cookie= "
                "PHPSESSID to access (login required)"
            )
            return None
        return resp.text

    def fetch_recent(
        self,
        *,
        pages: int = 1,
        category: str | None = None,  # noqa: ARG002
    ) -> list[UsedListing]:
        out: list[UsedListing] = []
        for board in self.boards:
            for p in range(1, pages + 1):
                try:
                    html = self._fetch(board, p)
                except httpx.HTTPError as e:
                    print(f"  [quasarzone/{board}] page {p} fetch failed: {e}")
                    break
                if html is None:
                    break
                listings = parse_list(html, board=board)
                out.extend(listings)
                print(f"  [quasarzone/{board}] page {p}: +{len(listings)} listings")
                if p < pages:
                    time.sleep(self.sleep_seconds)
        return out

    def search(
        self,
        query: str,
        *,
        category: str | None = None,  # noqa: ARG002
    ) -> list[UsedListing]:
        out: list[UsedListing] = []
        for board in self.boards:
            params = {"kind": "subject", "keyword": query}
            with httpx.Client(
                headers=_HEADERS,
                cookies=self._cookies,
                follow_redirects=True,
                timeout=20,
            ) as c:
                try:
                    resp = c.get(f"{_BASE}/bbs/{board}", params=params)
                    resp.raise_for_status()
                except httpx.HTTPError as e:
                    print(f"  [quasarzone/{board}] search '{query}' failed: {e}")
                    continue
            if _GATED_HINT in resp.text:
                continue
            out.extend(parse_list(resp.text, board=board))
        return out
