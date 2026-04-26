"""Auto-discover brands, danawa categories, and SKU sub-model lines from
the data we already have, instead of hardcoding them.

Three discovery functions, each idempotent (safe to re-run):

  discover_categories_from_nav(db)  — scrape Danawa nav, populate
      `danawa_categories`. Lets new categories appear automatically.

  discover_brands_from_products(db, category=None)  — frequency analysis on
      product names (first whitespace-separated token). Brands that appear
      in N+ products become canonical brand entries.

  discover_sku_lines_from_products(db, category)  — per-category TF-IDF on
      bigrams/trigrams; tokens with high category-specificity become SKU
      sub-model line candidates (ventus, gaming trio, eagle, …).

Each function returns a small summary dict for logging.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Iterable, Protocol

import httpx
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


_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
}


class _DBLike(Protocol):
    def table(self, name: str): ...


# ---------------------------------------------------------------------------
# 1. Categories — scrape Danawa nav once, get all cate IDs
# ---------------------------------------------------------------------------

# Pages that surface every PC-parts cate ID Danawa exposes.
_NAV_URLS = (
    "https://prod.danawa.com/list/?cate=112747",  # CPU page sidebar lists all parts
)

_CATE_LINK_RE = re.compile(
    r'(?:cate|categoryCode)=(\d{5,8})[^"]*"[^>]*>([^<]{2,40})<'
)

# Order matters: cooler/케이스/모니터 류 specific 합성어가 cpu/gpu/ram 토큰보다
# 먼저 매칭되어야 한다 — "CPU 공랭쿨러" → cooler, "그래픽카드 쿨러" → cooler.
_CANONICAL_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"쿨러|수랭|공랭", re.I), "cooler"),
    (re.compile(r"메인보드|마더보드", re.I), "mainboard"),
    (re.compile(r"파워|psu|전원공급", re.I), "psu"),
    (re.compile(r"\bssd\b|솔리드", re.I), "ssd"),
    (re.compile(r"\bhdd\b|하드디스크", re.I), "hdd"),
    (re.compile(r"모니터|디스플레이", re.I), "monitor"),
    (re.compile(r"케이스|컴퓨터케이스", re.I), "case"),
    (re.compile(r"그래픽카드|gpu|vga|비디오카드", re.I), "gpu"),
    (re.compile(r"^램$|메모리|\bram\b|ddr[345]", re.I), "ram"),
    (re.compile(r"cpu|프로세서|중앙처리장치", re.I), "cpu"),
]


def auto_map_canonical_categories(db: _DBLike) -> dict:
    """For danawa_categories rows where canonical IS NULL, attempt to
    map name_ko via _CANONICAL_PATTERNS. Returns a summary dict."""
    rows = (
        db.table("danawa_categories")
        .select("cate_id,name_ko,canonical")
        .is_("canonical", "null")
        .execute()
        .data
    )
    mapped = 0
    per_canon: dict[str, int] = {}
    for r in rows:
        name = (r.get("name_ko") or "").strip()
        if not name:
            continue
        for pat, canon in _CANONICAL_PATTERNS:
            if pat.search(name):
                db.table("danawa_categories").update(
                    {"canonical": canon}
                ).eq("cate_id", r["cate_id"]).execute()
                mapped += 1
                per_canon[canon] = per_canon.get(canon, 0) + 1
                break
    print(f"  [discovery] auto-mapped {mapped} categories: {per_canon}")
    return {"mapped": mapped, "per_canonical": per_canon}


@_retry_http
def _get_with_retry(client: httpx.Client, url: str) -> str:
    resp = client.get(url)
    resp.raise_for_status()
    return resp.text


def _fetch_nav_html() -> str:
    parts: list[str] = []
    with httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=20) as c:
        for url in _NAV_URLS:
            try:
                parts.append(_get_with_retry(c, url))
            except httpx.HTTPError as e:
                print(f"  [discovery] nav fetch failed for {url}: {e}")
    return "\n".join(parts)


def discover_categories_from_nav(db: _DBLike) -> dict:
    html = _fetch_nav_html()
    raw = _CATE_LINK_RE.findall(html)
    found: dict[str, str] = {}
    for cid, label in raw:
        label = label.strip()
        if not label or len(label) < 2:
            continue
        # First-seen wins (sidebar usually lists canonical name first).
        found.setdefault(cid, label)

    inserted = updated = 0
    for cid, label in found.items():
        existing = (
            db.table("danawa_categories")
            .select("cate_id,name_ko")
            .eq("cate_id", cid)
            .limit(1)
            .execute()
            .data
        )
        if existing:
            if existing[0]["name_ko"] != label:
                db.table("danawa_categories").update(
                    {"name_ko": label, "scraped_at": "now()"}
                ).eq("cate_id", cid).execute()
                updated += 1
        else:
            db.table("danawa_categories").insert(
                {"cate_id": cid, "name_ko": label}
            ).execute()
            inserted += 1
    print(
        f"  [discovery] categories: {len(found)} from nav, "
        f"{inserted} inserted, {updated} updated"
    )
    return {"discovered": len(found), "inserted": inserted, "updated": updated}


# ---------------------------------------------------------------------------
# 2. Brands — first-token frequency on existing products
# ---------------------------------------------------------------------------

# Generic Danawa-name leading tokens that aren't brand names (skip them).
_NON_BRAND_LEADING = {
    "pc",
    "데스크탑",
    "데스크톱",
    "노트북",
    "외장",
    "내장",
    "정품",
    "벌크",
    "리퍼",
}


def _first_token(name: str) -> str | None:
    if not name:
        return None
    raw = name.strip().split()
    if not raw:
        return None
    token = raw[0].strip(".,/-").lower()
    if not token or len(token) < 2:
        return None
    if token in _NON_BRAND_LEADING:
        return None
    return token


def discover_brands_from_products(
    db: _DBLike,
    *,
    category: str | None = None,
    min_doc_freq: int = 3,
) -> dict:
    query = db.table("products").select("category,name")
    if category:
        query = query.eq("category", category)
    rows = _read_all(query)
    if not rows:
        return {"discovered": 0, "wrote": 0}

    # global frequency across (potentially) multiple categories
    counter: Counter[tuple[str, str]] = Counter()
    for r in rows:
        cat = r.get("category") or ""
        token = _first_token(r.get("name") or "")
        if token:
            counter[(cat, token)] += 1

    candidates: dict[str, dict] = {}
    for (cat, token), cnt in counter.items():
        if cnt < min_doc_freq:
            continue
        bucket = candidates.setdefault(
            token,
            {
                "canonical": token,
                "display": token.upper() if token.isascii() else token,
                "aliases": [token],
                "category": None,
                "doc_freq": 0,
            },
        )
        bucket["doc_freq"] += cnt
        # If a brand only appears in one category, tag that category for
        # downstream filtering.
        if bucket["category"] is None:
            bucket["category"] = cat
        elif bucket["category"] != cat:
            bucket["category"] = None  # cross-category

    wrote = 0
    for entry in candidates.values():
        existing = (
            db.table("brands")
            .select("id,doc_freq,aliases")
            .eq("canonical", entry["canonical"])
            .limit(1)
            .execute()
            .data
        )
        if existing:
            old = existing[0]
            merged_aliases = list({*old["aliases"], *entry["aliases"]})
            db.table("brands").update(
                {
                    "doc_freq": entry["doc_freq"],
                    "aliases": merged_aliases,
                    "updated_at": "now()",
                }
            ).eq("id", old["id"]).execute()
        else:
            db.table("brands").insert(
                {
                    "canonical": entry["canonical"],
                    "display": entry["display"],
                    "aliases": entry["aliases"],
                    "category": entry["category"],
                    "confidence": 0.7,
                    "source": "freq_analysis",
                    "doc_freq": entry["doc_freq"],
                }
            ).execute()
        wrote += 1
    print(f"  [discovery] brands: {wrote} written from product first-tokens")
    return {"discovered": len(candidates), "wrote": wrote}


# ---------------------------------------------------------------------------
# 3. SKU lines — per-category TF-IDF on n-grams
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[A-Za-z가-힣]{2,}")
_DIGIT_PREFIX_RE = re.compile(r"^\d")


def _tokens(name: str) -> list[str]:
    """Lowercase alpha/Korean tokens, length >= 2, no digits-only."""
    return [t.lower() for t in _TOKEN_RE.findall(name) if not _DIGIT_PREFIX_RE.match(t)]


def _ngrams(tokens: list[str], n: int) -> list[str]:
    return [" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]


def discover_sku_lines_from_products(
    db: _DBLike,
    *,
    min_doc_freq: int = 3,
    max_share: float = 0.5,
) -> dict:
    """For each category, extract n-grams (1-3) that:
       - appear in ≥ min_doc_freq products in this category, AND
       - appear in ≤ max_share fraction of products in OTHER categories
       i.e. category-specific recurring sub-model identifiers.
    """
    rows = _read_all(db.table("products").select("category,name"))
    if not rows:
        return {"categories": {}}

    by_cat: dict[str, list[str]] = {}
    for r in rows:
        by_cat.setdefault(r["category"], []).append(r.get("name") or "")

    # Precompute presence per category
    cat_grams: dict[str, Counter[str]] = {}
    for cat, names in by_cat.items():
        c: Counter[str] = Counter()
        for n in names:
            tokens = _tokens(n)
            grams = set(_ngrams(tokens, 1) + _ngrams(tokens, 2) + _ngrams(tokens, 3))
            for g in grams:
                c[g] += 1
        cat_grams[cat] = c

    summary: dict[str, int] = {}
    total_wrote = 0
    for cat, this_counts in cat_grams.items():
        cat_size = len(by_cat[cat])
        wrote = 0
        for gram, cnt in this_counts.items():
            if cnt < min_doc_freq:
                continue
            # category-specificity check
            others_max_share = 0.0
            for other_cat, other_counts in cat_grams.items():
                if other_cat == cat:
                    continue
                share = other_counts.get(gram, 0) / max(len(by_cat[other_cat]), 1)
                if share > others_max_share:
                    others_max_share = share
            if others_max_share > max_share:
                continue
            # skip "rtx 5070"-like raw chip identifiers (already CATEGORY_PATTERNS)
            if any(ch.isdigit() for ch in gram):
                continue
            confidence = 1.0 - others_max_share
            existing = (
                db.table("sku_lines")
                .select("id,doc_freq")
                .eq("canonical", gram)
                .eq("category", cat)
                .limit(1)
                .execute()
                .data
            )
            if existing:
                db.table("sku_lines").update(
                    {
                        "doc_freq": cnt,
                        "confidence": confidence,
                        "updated_at": "now()",
                    }
                ).eq("id", existing[0]["id"]).execute()
            else:
                db.table("sku_lines").insert(
                    {
                        "canonical": gram,
                        "category": cat,
                        "aliases": [gram],
                        "doc_freq": cnt,
                        "confidence": confidence,
                    }
                ).execute()
            wrote += 1
        summary[cat] = wrote
        total_wrote += wrote
    print(f"  [discovery] sku_lines: {total_wrote} entries across {len(summary)} categories")
    return {"categories": summary, "total": total_wrote}


# ---------------------------------------------------------------------------
# 4. Seed: write current hardcoded BRAND_ALIASES into brands table at first
#    use, so cold-start has a baseline.
# ---------------------------------------------------------------------------

def seed_brands_from_constants(db: _DBLike) -> int:
    from src.normalization.catalog import BRAND_ALIASES

    wrote = 0
    for canonical, aliases in BRAND_ALIASES.items():
        existing = (
            db.table("brands")
            .select("id")
            .eq("canonical", canonical)
            .limit(1)
            .execute()
            .data
        )
        if existing:
            continue
        db.table("brands").insert(
            {
                "canonical": canonical,
                "display": canonical.upper() if canonical.isascii() else canonical,
                "aliases": list(aliases),
                "confidence": 1.0,
                "source": "seed",
            }
        ).execute()
        wrote += 1
    print(f"  [discovery] seed brands: {wrote} new entries")
    return wrote


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_all(query) -> list[dict]:
    page_size = 1000
    out: list[dict] = []
    offset = 0
    while True:
        rows = query.range(offset, offset + page_size - 1).execute().data
        if not rows:
            break
        out.extend(rows)
        if len(rows) < page_size:
            break
        offset += page_size
    return out
