"""Persistence pipeline: Danawa products + used-market listings → Supabase."""

from __future__ import annotations

from typing import Iterable, Protocol

from src.adapters.base import SourceAdapter, UsedListing
from src.crawlers.danawa import RawProduct, crawl
from src.normalization.catalog import (
    detect_brand,
    is_accessory_product,
    is_excluded_listing,
    normalize_product_name,
)
from src.services.matching import (
    DanawaProductCandidate,
    MATCH_THRESHOLD,
    PENDING_THRESHOLD,
    find_best_candidate,
)


class _SupabaseLike(Protocol):
    def table(self, name: str): ...


# ---------------------------------------------------------------------------
# Danawa (new-parts) ingest
# ---------------------------------------------------------------------------

def _build_product_payload(category: str, raw: RawProduct) -> dict:
    norm = normalize_product_name(category, raw.name)
    return {
        "category": category,
        "source": "danawa",
        "source_id": raw.source_id,
        "name": raw.name,
        "brand": norm.brand,
        "chipset": norm.chipset,
        "model_name": norm.model_name or None,
        "normalized_name": norm.normalized_name or None,
        "url": raw.url,
        "is_accessory": is_accessory_product(raw.name),
    }


def _upsert_product(db: _SupabaseLike, category: str, raw: RawProduct) -> str:
    payload = _build_product_payload(category, raw)
    result = (
        db.table("products")
        .upsert(payload, on_conflict="source,source_id")
        .execute()
    )
    return result.data[0]["id"]


def _insert_new_snapshot(db: _SupabaseLike, product_id: str, raw: RawProduct) -> None:
    if raw.price is None:
        return
    db.table("price_snapshots").insert(
        {
            "product_id": product_id,
            "market_type": "new",
            "source": "danawa",
            "price": raw.price,
            "shop_name": raw.shop_name,
        }
    ).execute()


def run_danawa(db: _SupabaseLike, category: str, pages: int = 1) -> dict:
    print(f"Crawling danawa/{category} ({pages} page(s))…")
    products = crawl(category, pages)
    print(f"Parsed {len(products)} products. Writing to Supabase…")

    saved = skipped = 0
    for raw in products:
        product_id = _upsert_product(db, category, raw)
        _insert_new_snapshot(db, product_id, raw)
        if raw.price is not None:
            saved += 1
        else:
            skipped += 1

    print(f"Done — saved: {saved}, skipped (no price): {skipped}")
    return {"products": len(products), "saved": saved, "skipped": skipped}


# ---------------------------------------------------------------------------
# Used-market ingest
# ---------------------------------------------------------------------------

def _fetch_candidates(db: _SupabaseLike, category: str) -> list[DanawaProductCandidate]:
    page_size = 1000
    offset = 0
    out: list[DanawaProductCandidate] = []
    while True:
        rows = (
            db.table("products")
            .select("id,category,source_id,name,brand,model_name,url")
            .eq("category", category)
            .range(offset, offset + page_size - 1)
            .execute()
            .data
        )
        if not rows:
            break
        for row in rows:
            out.append(
                DanawaProductCandidate(
                    category=row["category"],
                    source_id=row["source_id"],
                    name=row["name"],
                    brand=row.get("brand"),
                    model_name=row.get("model_name"),
                    url=row.get("url"),
                    product_id=row["id"],
                )
            )
        if len(rows) < page_size:
            break
        offset += page_size
    return out


def _upsert_used_listing(
    db: _SupabaseLike,
    listing: UsedListing,
    category: str | None,
    matched_product_id: str | None,
    score: float | None,
    reasons: list[str] | None = None,
) -> str:
    payload = {
        "source": listing.source,
        "listing_id": listing.listing_id,
        "category": category,
        "title": listing.title,
        "price": listing.price,
        "price_raw": listing.price_raw,
        "status": listing.status,
        "url": listing.url,
        "matched_product_id": matched_product_id,
        "match_score": score,
        "match_reasons": reasons,
    }
    result = (
        db.table("used_listings")
        .upsert(payload, on_conflict="source,listing_id")
        .execute()
    )
    return result.data[0]["id"]


def _insert_used_snapshot(
    db: _SupabaseLike,
    product_id: str,
    listing: UsedListing,
) -> None:
    if listing.price is None:
        return
    db.table("price_snapshots").insert(
        {
            "product_id": product_id,
            "market_type": "used",
            "source": listing.source,
            "price": listing.price,
            "shop_name": None,
        }
    ).execute()


def _collect_listings(
    adapter: SourceAdapter,
    *,
    category: str | None,
    queries: Iterable[str] | None,
    pages: int,
) -> list[UsedListing]:
    if queries:
        out: list[UsedListing] = []
        for q in queries:
            try:
                out.extend(adapter.search(q, category=category))
            except NotImplementedError:
                print(f"  [{adapter.source_name}] search not implemented; stopping")
                break
        return out
    try:
        return adapter.fetch_recent(pages=pages, category=category)
    except NotImplementedError:
        print(f"  [{adapter.source_name}] fetch_recent not implemented; need queries")
        return []


def run_used(
    db: _SupabaseLike,
    adapter: SourceAdapter,
    *,
    category: str,
    queries: Iterable[str] | None = None,
    pages: int = 1,
) -> dict:
    """Crawl one used source for one category, match to Danawa products, persist."""
    print(f"Crawling {adapter.source_name}/{category}…")
    listings = _collect_listings(adapter, category=category, queries=queries, pages=pages)
    print(f"Collected {len(listings)} raw listings. Filtering + matching…")

    candidates = _fetch_candidates(db, category)
    print(f"Loaded {len(candidates)} Danawa candidates for category={category}")

    matched = pending = unmatched = excluded = saved_snapshots = 0

    for listing in listings:
        if is_excluded_listing(listing.title):
            excluded += 1
            continue

        # If brand is detectable, restrict the candidate pool — large speed win
        listing_brand = detect_brand(listing.title, category)
        pool = (
            [c for c in candidates if not c.brand or not listing_brand or c.brand == listing_brand]
            or candidates
        )
        result = find_best_candidate(listing, pool)
        if result is None:
            unmatched += 1
            _upsert_used_listing(db, listing, category, None, None, None)
            continue

        if result.is_match and result.candidate.product_id:
            matched += 1
            _upsert_used_listing(
                db, listing, category, result.candidate.product_id, result.score, result.reasons
            )
            _insert_used_snapshot(db, result.candidate.product_id, listing)
            if listing.price is not None:
                saved_snapshots += 1
        elif result.is_pending:
            pending += 1
            _upsert_used_listing(db, listing, category, None, result.score, result.reasons)
        else:
            unmatched += 1
            _upsert_used_listing(db, listing, category, None, result.score, result.reasons)

    print(
        f"Done — matched: {matched}, pending: {pending}, "
        f"unmatched: {unmatched}, excluded: {excluded}, snapshots: {saved_snapshots}"
    )
    return {
        "listings": len(listings),
        "matched": matched,
        "pending": pending,
        "unmatched": unmatched,
        "excluded": excluded,
        "snapshots": saved_snapshots,
        "thresholds": {"match": MATCH_THRESHOLD, "pending": PENDING_THRESHOLD},
    }
