"""Persistence pipeline: Danawa products + used-market listings → Supabase."""

from __future__ import annotations

from typing import Iterable, Protocol

from src.adapters.base import SourceAdapter, UsedListing
from src.crawlers.danawa import RawProduct, crawl
from src.domains.consumer.matching import (
    CONSUMER_CATEGORIES,
    ConsumerProductCandidate,
    find_best_consumer_candidate,
)
from src.domains.consumer.normalization import normalize_consumer_product
from src.normalization.catalog import (
    detect_brand,
    is_accessory_product,
    is_excluded_listing,
    normalize_product_name,
)
from src.normalization.pc_identity import build_pc_identity
from src.services.matching import (
    DanawaProductCandidate,
    MATCH_THRESHOLD,
    PENDING_THRESHOLD,
    find_best_candidate,
)


class _SupabaseLike(Protocol):
    def table(self, name: str): ...


_B2C_SOURCES = {"naver_shop"}


# ---------------------------------------------------------------------------
# Danawa (new-parts) ingest
# ---------------------------------------------------------------------------

def _build_product_payload(category: str, raw: RawProduct) -> dict:
    norm = normalize_product_name(category, raw.name)
    identity = build_pc_identity(category, raw.name)
    return {
        "domain": identity.domain,
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
        "canonical_key": identity.canonical_key,
        "specs": identity.specs,
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
    domain: str | None = None,
    parsed_specs: dict | None = None,
) -> str:
    payload = {
        "source": listing.source,
        "listing_id": listing.listing_id,
        "domain": domain,
        "category": category,
        "title": listing.title,
        "price": listing.price,
        "price_raw": listing.price_raw,
        "status": listing.status,
        "url": listing.url,
        "matched_product_id": matched_product_id,
        "match_score": score,
        "match_reasons": reasons,
        "location_text": listing.location,
        "parsed_specs": parsed_specs or {},
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
    market_type = "b2c" if listing.source in _B2C_SOURCES else "used"
    db.table("price_snapshots").insert(
        {
            "product_id": product_id,
            "market_type": market_type,
            "source": listing.source,
            "price": listing.price,
            "shop_name": None,
        }
    ).execute()


def _fetch_consumer_candidates(
    db: _SupabaseLike, category: str
) -> list[ConsumerProductCandidate]:
    page_size = 1000
    offset = 0
    out: list[ConsumerProductCandidate] = []
    while True:
        rows = (
            db.table("products")
            .select("id,category,name,canonical_key")
            .eq("category", category)
            .range(offset, offset + page_size - 1)
            .execute()
            .data
        )
        if not rows:
            break
        for row in rows:
            out.append(
                ConsumerProductCandidate(
                    product_id=row["id"],
                    category=row["category"],
                    name=row["name"],
                    canonical_key=row.get("canonical_key"),
                )
            )
        if len(rows) < page_size:
            break
        offset += page_size
    return out


def _consumer_product_name(norm) -> str:
    if norm.domain == "phone" and norm.model and norm.storage_gb:
        brand = "Apple" if norm.brand == "apple" else "Samsung" if norm.brand == "samsung" else norm.brand or ""
        return f"{brand} {norm.model.title()} {norm.storage_gb}GB".strip()
    if norm.domain == "macbook":
        bits = ["MacBook", norm.family.title() if norm.family else None]
        if norm.screen_size:
            bits.append(str(norm.screen_size))
        if norm.chip:
            bits.append(norm.chip.upper().replace(" PRO", " Pro").replace(" MAX", " Max"))
        if norm.ram_gb:
            bits.append(f"{norm.ram_gb}GB")
        if norm.storage_gb:
            bits.append(f"{norm.storage_gb}GB")
        return " ".join(str(b) for b in bits if b)
    return norm.canonical_key or "consumer product"


def _consumer_model_name(norm) -> str | None:
    if norm.domain == "phone":
        if norm.model and norm.storage_gb:
            return f"{norm.model} {norm.storage_gb}gb"
        return norm.model
    if norm.domain == "macbook":
        bits = ["macbook", norm.family, str(norm.screen_size) if norm.screen_size else None, norm.chip]
        if norm.ram_gb:
            bits.append(f"{norm.ram_gb}gb")
        if norm.storage_gb:
            bits.append(f"{norm.storage_gb}gb")
        return " ".join(str(b) for b in bits if b)
    return None


def _ensure_consumer_candidate(
    db: _SupabaseLike,
    category: str,
    norm,
    candidates: list[ConsumerProductCandidate],
) -> ConsumerProductCandidate | None:
    if not norm or not norm.canonical_key:
        return None
    for candidate in candidates:
        if candidate.canonical_key == norm.canonical_key:
            return candidate

    payload = {
        "category": category,
        "domain": norm.domain,
        "source": "consumer_auto",
        "source_id": norm.canonical_key,
        "name": _consumer_product_name(norm),
        "brand": norm.brand,
        "model_name": _consumer_model_name(norm),
        "normalized_name": _consumer_model_name(norm),
        "canonical_key": norm.canonical_key,
        "specs": norm.specs,
        "is_accessory": False,
    }
    row = db.table("products").upsert(payload, on_conflict="source,source_id").execute().data[0]
    candidate = ConsumerProductCandidate(
        product_id=row["id"],
        category=category,
        name=row["name"],
        canonical_key=row.get("canonical_key"),
    )
    candidates.append(candidate)
    return candidate


def _ensure_pc_candidate(
    db: _SupabaseLike,
    category: str,
    listing: UsedListing,
    candidates: list[DanawaProductCandidate],
) -> DanawaProductCandidate | None:
    identity = build_pc_identity(category, listing.title)
    if not identity.canonical_key or not identity.specs.get("category_tokens"):
        return None
    # Require either a brand or capacity to avoid creating products from generic
    # noisy listings such as "RTX 삽니다" or accessory posts.
    if not identity.specs.get("brand") and not identity.specs.get("capacity_tokens"):
        return None
    for candidate in candidates:
        if getattr(candidate, "canonical_key", None) == identity.canonical_key:
            return candidate

    norm = normalize_product_name(category, listing.title)
    payload = {
        "domain": "pc_parts",
        "category": category,
        "source": "pc_auto",
        "source_id": identity.canonical_key,
        "name": listing.title,
        "brand": norm.brand,
        "chipset": norm.chipset,
        "model_name": norm.model_name or None,
        "normalized_name": norm.normalized_name or None,
        "url": listing.url,
        "is_accessory": False,
        "canonical_key": identity.canonical_key,
        "specs": identity.specs,
    }
    row = db.table("products").upsert(payload, on_conflict="source,source_id").execute().data[0]
    candidate = DanawaProductCandidate(
        category=category,
        source_id=row["source_id"],
        name=row["name"],
        brand=row.get("brand"),
        model_name=row.get("model_name"),
        url=row.get("url"),
        product_id=row["id"],
    )
    candidates.append(candidate)
    return candidate


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

    use_consumer_matcher = category in CONSUMER_CATEGORIES
    candidates = _fetch_consumer_candidates(db, category) if use_consumer_matcher else _fetch_candidates(db, category)
    print(f"Loaded {len(candidates)} candidates for category={category}")

    matched = pending = unmatched = excluded = saved_snapshots = 0

    for listing in listings:
        if is_excluded_listing(listing.title):
            excluded += 1
            continue

        consumer_norm = normalize_consumer_product(category, listing.title) if use_consumer_matcher else None
        domain = consumer_norm.domain if consumer_norm else "pc_parts"
        parsed_specs = consumer_norm.specs if consumer_norm else {}
        if not use_consumer_matcher:
            parsed_specs = build_pc_identity(category, listing.title).specs

        if use_consumer_matcher:
            _ensure_consumer_candidate(db, category, consumer_norm, candidates)
            result = find_best_consumer_candidate(listing, candidates, category=category)
            if result is None:
                unmatched += 1
                _upsert_used_listing(db, listing, category, None, None, None, domain, parsed_specs)
                continue
            if result.is_match:
                matched += 1
                _upsert_used_listing(
                    db, listing, category, result.candidate.product_id, result.score,
                    result.reasons, domain, parsed_specs
                )
                _insert_used_snapshot(db, result.candidate.product_id, listing)
                if listing.price is not None:
                    saved_snapshots += 1
            elif result.is_pending:
                pending += 1
                _upsert_used_listing(db, listing, category, None, result.score, result.reasons, domain, parsed_specs)
            else:
                unmatched += 1
                _upsert_used_listing(db, listing, category, None, result.score, result.reasons, domain, parsed_specs)
            continue

        # If brand is detectable, restrict the candidate pool — large speed win
        if not candidates:
            _ensure_pc_candidate(db, category, listing, candidates)

        listing_brand = detect_brand(listing.title, category)
        pool = (
            [c for c in candidates if not c.brand or not listing_brand or c.brand == listing_brand]
            or candidates
        )
        result = find_best_candidate(listing, pool)
        if result is None or (not result.is_match and not result.is_pending):
            auto_candidate = _ensure_pc_candidate(db, category, listing, candidates)
            if auto_candidate is not None:
                matched += 1
                reasons = ["auto:pc_identity"]
                _upsert_used_listing(
                    db, listing, category, auto_candidate.product_id, 1.0, reasons, domain, parsed_specs
                )
                _insert_used_snapshot(db, auto_candidate.product_id, listing)
                if listing.price is not None:
                    saved_snapshots += 1
                continue
            unmatched += 1
            _upsert_used_listing(
                db,
                listing,
                category,
                None,
                None if result is None else result.score,
                None if result is None else result.reasons,
                domain,
                parsed_specs,
            )
            continue

        if result.is_match and result.candidate.product_id:
            matched += 1
            _upsert_used_listing(
                db, listing, category, result.candidate.product_id, result.score, result.reasons, domain, parsed_specs
            )
            _insert_used_snapshot(db, result.candidate.product_id, listing)
            if listing.price is not None:
                saved_snapshots += 1
        elif result.is_pending:
            pending += 1
            _upsert_used_listing(db, listing, category, None, result.score, result.reasons, domain, parsed_specs)
        else:
            unmatched += 1
            _upsert_used_listing(db, listing, category, None, result.score, result.reasons, domain, parsed_specs)

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
