"""NAVER 공식 쇼핑 검색 OpenAPI adapter.

Endpoint: https://openapi.naver.com/v1/search/shop.json
Auth:     X-Naver-Client-Id / X-Naver-Client-Secret (env-driven)
Quota:    25,000 calls/day per app (free tier).

Response shape (items[]):
  - title (HTML — <b>...</b> highlighting; stripped)
  - link, image
  - lprice (string, 최저가), hprice (string, 최고가; "" 일 수 있음)
  - mallName, productId, productType
  - brand, maker, category1~4

productType codes (per NAVER docs / community references):
  1 = 일반   2 = 중고   3 = 단종   4 = 수입   5 = 판매중지

This adapter only emits productType 2 (중고) by default — the app's purpose
is used-market price discovery. The `accept_types` argument widens this if a
caller wants e.g. 일반 + 중고 baseline.

Listing id: NAVER doesn't expose a globally stable id, so we synthesize
"{productId}:{mallName}" — the same listing across malls is treated as
distinct (a feature, not a bug — different sellers list at different prices).
"""

from __future__ import annotations

import json
import os
import re
import time

import httpx

from src.adapters.base import (
    STATUS_SELLING,
    STATUS_UNKNOWN,
    SourceAdapter,
    UsedListing,
    parse_price_int,
)


_API = "https://openapi.naver.com/v1/search/shop.json"
_DEFAULT_ACCEPT_TYPES = frozenset({"2"})  # 중고 only
_TAG_RE = re.compile(r"<[^>]+>")
_USED_KEYWORDS = ("중고",)

# Suffix variants tilt response toward P2P (productType=2) listings instead of
# new-baseline products. PoC on 2026-04-29 showed bare "중고 RTX 4070" returned
# only 5/30 (16%) productType=2; the goal of this list is 30%+ via suffix mix.
# Empty string keeps the bare prefixed query.
_DEFAULT_QUERY_VARIANTS: tuple[str, ...] = ("", "판매", "직거래")


def _strip_tags(text: str) -> str:
    return _TAG_RE.sub("", text or "").strip()


def parse_response(
    payload: str | dict,
    *,
    accept_types: frozenset[str] | set[str] | None = None,
) -> list[UsedListing]:
    """Pure parser — NAVER /v1/search/shop.json response → list[UsedListing].

    Default filter: only productType="2" (중고). Pass accept_types to widen.
    """
    types = frozenset(accept_types) if accept_types else _DEFAULT_ACCEPT_TYPES
    data = json.loads(payload) if isinstance(payload, str) else payload
    out: list[UsedListing] = []
    for item in data.get("items", []) or []:
        product_type = str(item.get("productType", "")).strip()
        if product_type and product_type not in types:
            continue

        product_id = str(item.get("productId", "")).strip()
        mall_name = (item.get("mallName") or "").strip()
        if not product_id:
            continue
        listing_id = f"{product_id}:{mall_name}" if mall_name else product_id

        title = _strip_tags(item.get("title") or "")
        if not title:
            continue

        # lprice (최저가) preferred — represents what a buyer actually pays.
        lprice = parse_price_int(item.get("lprice"))
        hprice = parse_price_int(item.get("hprice"))
        price = lprice if lprice else hprice
        price_raw = str(item.get("lprice")) if item.get("lprice") else None

        link = (item.get("link") or "").strip() or None

        # productType 2 (중고) is by definition currently for sale on NAVER;
        # 5 (판매중지) is the only sold-equivalent. Map accordingly.
        status = STATUS_SELLING if product_type != "5" else STATUS_UNKNOWN

        metadata: dict[str, str] = {}
        if mall_name:
            metadata["mall_name"] = mall_name
        if product_type:
            metadata["product_type"] = product_type
        for k in ("brand", "maker", "category1", "category2", "category3", "category4"):
            v = (item.get(k) or "").strip()
            if v:
                metadata[k] = v

        out.append(
            UsedListing(
                source="naver_shop",
                listing_id=listing_id,
                title=title,
                price=price,
                price_raw=price_raw,
                url=link,
                status=status,
                metadata=metadata,
            )
        )
    return out


def has_credentials() -> bool:
    """True if NAVER_CLIENT_ID and NAVER_CLIENT_SECRET are both set in env."""
    return bool(os.environ.get("NAVER_CLIENT_ID")) and bool(
        os.environ.get("NAVER_CLIENT_SECRET")
    )


class NaverShopAdapter(SourceAdapter):
    source_name = "naver_shop"

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        *,
        accept_types: frozenset[str] | set[str] | None = None,
        sleep_seconds: float = 0.2,
        page_size: int = 100,
        prepend_used_keyword: bool = True,
        query_variants: tuple[str, ...] | None = None,
    ):
        self._client_id = client_id or os.environ.get("NAVER_CLIENT_ID")
        self._client_secret = client_secret or os.environ.get("NAVER_CLIENT_SECRET")
        self.accept_types = (
            frozenset(accept_types) if accept_types else _DEFAULT_ACCEPT_TYPES
        )
        self.sleep_seconds = sleep_seconds
        # API max display=100, max start=1000 → up to 1000 results per query
        self.page_size = max(1, min(int(page_size), 100))
        self.prepend_used_keyword = prepend_used_keyword
        # Empty tuple disables variants (single bare query). None → defaults.
        self.query_variants = (
            tuple(query_variants)
            if query_variants is not None
            else _DEFAULT_QUERY_VARIANTS
        )

    def _headers(self) -> dict[str, str]:
        if not (self._client_id and self._client_secret):
            raise RuntimeError(
                "NaverShopAdapter requires NAVER_CLIENT_ID + NAVER_CLIENT_SECRET "
                "env vars (or constructor args)."
            )
        return {
            "X-Naver-Client-Id": self._client_id,
            "X-Naver-Client-Secret": self._client_secret,
            "Accept": "application/json",
            "Accept-Language": "ko-KR,ko;q=0.9",
        }

    def _normalize_query(self, query: str) -> str:
        q = (query or "").strip()
        if not q:
            return ""
        if not self.prepend_used_keyword:
            return q
        # Skip if any used-keyword already present.
        if any(k in q for k in _USED_KEYWORDS):
            return q
        return f"중고 {q}"

    def _expand_variants(self, base: str) -> list[str]:
        """Expand a base query into the configured suffix variants.

        Empty self.query_variants → single base query.
        Each variant is appended after the prefixed base, deduplicated, and
        the bare base is always included (even if not in variants) so the
        original recall is preserved.
        """
        if not base:
            return []
        if not self.query_variants:
            return [base]
        seen: list[str] = []
        for suffix in self.query_variants:
            q = f"{base} {suffix}".strip() if suffix else base
            if q and q not in seen:
                seen.append(q)
        return seen

    def _fetch(self, query: str, start: int) -> str:
        params = {
            "query": query,
            "display": self.page_size,
            "start": start,
            "sort": "sim",
        }
        with httpx.Client(headers=self._headers(), timeout=20) as c:
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
        base = self._normalize_query(query)
        if not base:
            return []
        if not (self._client_id and self._client_secret):
            print("  [naver_shop] credentials missing — skipping")
            return []

        seen_listing_ids: set[str] = set()
        out: list[UsedListing] = []
        # `start` is 1-based, max 1000. With page_size=100 → max 10 pages.
        max_start = min(pages, 10) * self.page_size
        for variant in self._expand_variants(base):
            start = 1
            while start <= max_start:
                try:
                    body = self._fetch(variant, start)
                except httpx.HTTPError as e:
                    print(f"  [naver_shop] '{variant}' start={start} failed: {e}")
                    break
                listings = parse_response(body, accept_types=self.accept_types)
                # Dedup across variants — same listing may surface under multiple suffixes.
                fresh = [
                    listing
                    for listing in listings
                    if listing.listing_id not in seen_listing_ids
                ]
                seen_listing_ids.update(listing.listing_id for listing in fresh)
                out.extend(fresh)
                print(
                    f"  [naver_shop] '{variant}' start={start}: "
                    f"+{len(fresh)} new (raw {len(listings)}, "
                    f"productType in {sorted(self.accept_types)})"
                )
                if not listings:
                    break
                start += self.page_size
                if start <= max_start:
                    time.sleep(self.sleep_seconds)
        return out

    def fetch_recent(
        self,
        *,
        pages: int = 1,  # noqa: ARG002
        category: str | None = None,  # noqa: ARG002
    ) -> list[UsedListing]:
        # NAVER OpenAPI is search-only — no flat recent feed.
        return []
