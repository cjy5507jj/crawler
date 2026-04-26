"""Danawa new-parts listing crawler.

Pagination uses Danawa's AJAX endpoint:

  GET  https://prod.danawa.com/list/?cate=NNNN
       → extract physicsCate1/2/3/4 codes from the embedded powerLink URL.

  POST https://prod.danawa.com/list/ajax/getProductList.ajax.php
       payload: page, listCategoryCode (= leaf cate), physicsCate1..4,
                viewMethod=LIST, sortMethod=BEST, listCount=30, group=11, depth=2
       → returns the same product-card HTML as page 1, but for arbitrary page N.

Verified live 2026-04-26 across 9 categories.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup, Tag
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


_retry_http = retry(
    retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)


CATEGORY_MAP: dict[str, str] = {
    "cpu": "112747",
    "gpu": "112753",
    "mainboard": "112751",
    "ram": "112752",
    "ssd": "112760",
    "hdd": "112763",
    "psu": "112777",
    "case": "112775",
    "cooler": "11236855",
    "monitor": "112757",
}

_BASE = "https://prod.danawa.com"
_LIST_URL = f"{_BASE}/list/"
_AJAX_URL = f"{_BASE}/list/ajax/getProductList.ajax.php"

_HEADERS_GET = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Referer": "https://www.danawa.com/",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
}

_HEADERS_POST = {
    **_HEADERS_GET,
    "X-Requested-With": "XMLHttpRequest",
    "Origin": _BASE,
}

_PHYSICS_RE = re.compile(r"cate?1=(\d+)&cate?2=(\d+)&cate?3=(\d+)&cate?4=(\d+)")
_LIST_COUNT = 30


@dataclass
class RawProduct:
    source_id: str
    name: str
    price: int | None
    shop_name: str | None
    url: str


@dataclass
class _CategoryInit:
    leaf_code: str        # listCategoryCode value (e.g. '747' for cate=112747)
    physics: tuple[str, str, str, str]


# ---------------------------------------------------------------------------
# Init: GET cate page once to extract physicsCate codes + leaf code
# ---------------------------------------------------------------------------

def _leaf_code(cate: str) -> str:
    # Standard PC-parts cates start with '112' (6 digits) or '1123…' (8 digits).
    # Strip the '112' prefix to get Danawa's internal listCategoryCode.
    if cate.startswith("112"):
        return cate[3:]
    return cate


@_retry_http
def _init_category(client: httpx.Client, cate: str) -> _CategoryInit:
    resp = client.get(_LIST_URL, params={"cate": cate})
    resp.raise_for_status()
    m = _PHYSICS_RE.search(resp.text)
    if not m:
        raise RuntimeError(
            f"Could not extract physicsCate codes for cate={cate}; "
            "Danawa page structure may have changed."
        )
    physics = (m.group(1), m.group(2), m.group(3), m.group(4))
    return _CategoryInit(leaf_code=_leaf_code(cate), physics=physics)


# ---------------------------------------------------------------------------
# Pagination: POST AJAX endpoint per page
# ---------------------------------------------------------------------------

@_retry_http
def _fetch_page(client: httpx.Client, init: _CategoryInit, page: int, cate: str) -> str:
    p1, p2, p3, p4 = init.physics
    data = {
        "page": page,
        "listCategoryCode": init.leaf_code,
        "categoryCode": init.leaf_code,
        "physicsCate1": p1,
        "physicsCate2": p2,
        "physicsCate3": p3,
        "physicsCate4": p4,
        "viewMethod": "LIST",
        "sortMethod": "BEST",
        "listCount": _LIST_COUNT,
        "group": 11,
        "depth": 2,
    }
    headers = {**_HEADERS_POST, "Referer": f"{_LIST_URL}?cate={cate}"}
    resp = client.post(_AJAX_URL, data=data, headers=headers)
    resp.raise_for_status()
    return resp.text


# ---------------------------------------------------------------------------
# Parse helpers
# ---------------------------------------------------------------------------

def _parse_price(text: str) -> int | None:
    digits = "".join(c for c in text if c.isdigit())
    return int(digits) if digits else None


def _source_id_from_url(url: str) -> str:
    if "pcode=" in url:
        return url.split("pcode=")[1].split("&")[0]
    return ""


def _is_ad(li: Tag) -> bool:
    return (li.get("id") or "").startswith("adReader")


def parse_products(html: str) -> list[RawProduct]:
    soup = BeautifulSoup(html, "lxml")
    out: list[RawProduct] = []
    for li in soup.select("li.prod_item"):
        if _is_ad(li):
            continue
        name_tag = li.select_one(".prod_main_info .prod_name a")
        if not name_tag:
            continue
        name = name_tag.get_text(strip=True)
        if not name:
            continue
        href = name_tag.get("href", "")
        url = href if href.startswith("http") else f"{_BASE}{href}"
        source_id = _source_id_from_url(url)
        if not source_id:
            raw_id = li.get("id", "")
            source_id = raw_id.replace("productItem", "") if raw_id else ""
        if not source_id:
            continue
        price_tag = li.select_one("p.price_sect strong") or li.select_one(
            ".lowest_price strong"
        )
        price = _parse_price(price_tag.get_text()) if price_tag else None
        out.append(
            RawProduct(
                source_id=source_id,
                name=name,
                price=price,
                shop_name=None,
                url=url,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def crawl(
    category: str,
    pages: int = 1,
    sleep_seconds: float = 1.0,
    *,
    max_pages: int = 200,
) -> list[RawProduct]:
    """Crawl listing pages for `category`. Returns parsed products.

    pages > 0  → fetch exactly that many pages.
    pages == 0 → fetch ALL pages until an empty/duplicate page (capped at
                 `max_pages`). Picks up every manufacturer + model Danawa
                 currently exposes for the category.
    """
    cate = CATEGORY_MAP.get(category.lower())
    if not cate:
        raise ValueError(
            f"Unknown category '{category}'. Valid options: {sorted(CATEGORY_MAP)}"
        )

    exhaustive = pages == 0
    limit = max_pages if exhaustive else pages

    out: list[RawProduct] = []
    seen: set[str] = set()
    with httpx.Client(headers=_HEADERS_GET, follow_redirects=True, timeout=20) as client:
        try:
            init = _init_category(client, cate)
        except (httpx.HTTPError, RuntimeError) as e:
            print(f"  [{category}] init failed: {e}")
            return []
        for page in range(1, limit + 1):
            try:
                html = _fetch_page(client, init, page, cate)
            except httpx.HTTPError as e:
                print(f"  [{category}] page {page} fetch failed: {e}")
                break
            found = parse_products(html)
            new_items = [p for p in found if p.source_id not in seen]
            for p in new_items:
                seen.add(p.source_id)
            out.extend(new_items)
            print(
                f"  [{category}] page {page}: +{len(new_items)} new "
                f"({len(found)} on page, {len(out)} unique total)"
            )
            if exhaustive and (not found or not new_items):
                print(f"  [{category}] exhaustive crawl reached end at page {page}")
                break
            if page < limit:
                time.sleep(sleep_seconds)
    return out
