"""Aggregate used-market price snapshots into per-product stats."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Iterable, Protocol

# Trimmed-mean threshold:
#   < _TRIM_MIN_COUNT  → simple mean
#   ≥ _TRIM_MIN_COUNT  → drop top/bottom _TRIM_FRACTION
#   ≥ _DEEP_TRIM_COUNT → drop top/bottom _DEEP_TRIM_FRACTION (more aggressive)
_TRIM_MIN_COUNT = 5
_TRIM_FRACTION = 0.10
_DEEP_TRIM_COUNT = 10
_DEEP_TRIM_FRACTION = 0.20

# Sanity bounds: drop prices outside [median/MAX_DEV, median*MAX_DEV] before
# computing mean — kills "1원" sale glitches and "9999999원" placeholders.
_MAX_DEVIATION = 4.0

# Per-category new-price floors. A Danawa snapshot below the floor is almost
# certainly an outlier (discontinued SKU, scraping glitch, EOL clearance) and
# would produce a misleadingly large used_to_new_ratio. We treat such prices
# as missing for ratio purposes — used-side stats are still computed.
# Categories not in this dict get no floor (graceful default).
_NEW_PRICE_FLOORS: dict[str, int] = {
    "ram": 10_000,       # DDR3-1333 4,500원 case
    "ssd": 15_000,
    "hdd": 20_000,
    "cpu": 30_000,
    "gpu": 50_000,
    "mainboard": 30_000,
    "psu": 20_000,
    "cooler": 5_000,
    "case": 10_000,
    "monitor": 50_000,
}


class _SupabaseLike(Protocol):
    def table(self, name: str): ...


@dataclass
class MarketStats:
    product_id: str
    category: str
    used_count: int
    used_min: int | None
    used_max: int | None
    used_median: int | None
    used_mean: int | None
    used_latest: int | None
    used_latest_at: str | None
    new_price: int | None
    used_to_new_ratio: float | None
    window_days: int


# ---------------------------------------------------------------------------
# Pure algorithm — testable without DB
# ---------------------------------------------------------------------------

def _trimmed_mean(prices: list[int]) -> float | None:
    """Trimmed mean with adaptive trim fraction by sample size."""
    if not prices:
        return None
    if len(prices) < _TRIM_MIN_COUNT:
        return sum(prices) / len(prices)
    fraction = _DEEP_TRIM_FRACTION if len(prices) >= _DEEP_TRIM_COUNT else _TRIM_FRACTION
    s = sorted(prices)
    k = max(1, int(len(s) * fraction))
    trimmed = s[k:-k] if len(s) - 2 * k >= 1 else s
    return sum(trimmed) / len(trimmed)


def _sanity_filter(prices: list[int]) -> list[int]:
    """Drop prices outside [median/MAX_DEV, median*MAX_DEV]."""
    if len(prices) < 3:
        return prices
    med = median(prices)
    if not med:
        return prices
    lo = med / _MAX_DEVIATION
    hi = med * _MAX_DEVIATION
    return [p for p in prices if lo <= p <= hi]


@dataclass
class _Snapshot:
    price: int
    snapshot_at: str


def compute_stats(
    *,
    product_id: str,
    category: str,
    used_snapshots: Iterable[_Snapshot],
    new_price: int | None,
    window_days: int,
) -> MarketStats:
    snaps = sorted(used_snapshots, key=lambda s: s.snapshot_at, reverse=True)
    raw_prices = [s.price for s in snaps if s.price is not None and s.price > 0]
    # Drop sale-glitch / placeholder outliers using a median-deviation filter
    # before computing min/max/mean/ratio. The "latest" still references the
    # most recent raw snapshot so the user can see what was actually crawled.
    prices = _sanity_filter(raw_prices)

    # Clamp implausibly low Danawa snapshots: a 4,500원 RAM "new" price is
    # almost certainly a discontinued/EOL listing and produces nonsense ratios.
    # Drop only the new-side; used stats remain.
    floor = _NEW_PRICE_FLOORS.get(category.lower()) if category else None
    if new_price is not None and floor is not None and new_price < floor:
        new_price = None

    if not prices:
        return MarketStats(
            product_id=product_id,
            category=category,
            used_count=0,
            used_min=None,
            used_max=None,
            used_median=None,
            used_mean=None,
            used_latest=None,
            used_latest_at=None,
            new_price=new_price,
            used_to_new_ratio=None,
            window_days=window_days,
        )

    used_min = min(prices)
    used_max = max(prices)
    used_median = int(median(prices))
    mean = _trimmed_mean(prices)
    used_mean = int(mean) if mean is not None else None
    used_latest = snaps[0].price
    used_latest_at = snaps[0].snapshot_at

    ratio: float | None = None
    if new_price and new_price > 0 and used_median:
        ratio = round(used_median / new_price, 4)

    return MarketStats(
        product_id=product_id,
        category=category,
        used_count=len(prices),
        used_min=used_min,
        used_max=used_max,
        used_median=used_median,
        used_mean=used_mean,
        used_latest=used_latest,
        used_latest_at=used_latest_at,
        new_price=new_price,
        used_to_new_ratio=ratio,
        window_days=window_days,
    )


# ---------------------------------------------------------------------------
# DB-bound runner
# ---------------------------------------------------------------------------

def _iso_window_start(window_days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()


def _page_through(query, page_size: int = 1000) -> list[dict]:
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


def _fetch_all_products(db: _SupabaseLike, category: str | None) -> list[dict]:
    # Skip is_accessory=true rows: cables/converters/brackets aren't real parts
    # and would skew used-vs-new ratios for the category.
    q = db.table("products").select("id,category").eq("is_accessory", False)
    if category:
        q = q.eq("category", category)
    return _page_through(q)


def _fetch_all_used_snapshots_grouped(
    db: _SupabaseLike, since_iso: str
) -> dict[str, list[_Snapshot]]:
    rows = _page_through(
        db.table("price_snapshots")
        .select("product_id,price,snapshot_at")
        .eq("market_type", "used")
        .gte("snapshot_at", since_iso)
        .order("snapshot_at", desc=True)
    )
    grouped: dict[str, list[_Snapshot]] = {}
    for r in rows:
        if r.get("price") is None:
            continue
        grouped.setdefault(r["product_id"], []).append(
            _Snapshot(price=int(r["price"]), snapshot_at=r["snapshot_at"])
        )
    return grouped


def _fetch_latest_new_prices(db: _SupabaseLike) -> dict[str, int]:
    """Return {product_id: latest new price}.
    Postgres returns rows ordered by snapshot_at desc, so first per product wins."""
    rows = _page_through(
        db.table("price_snapshots")
        .select("product_id,price,snapshot_at")
        .eq("market_type", "new")
        .order("snapshot_at", desc=True)
    )
    latest: dict[str, int] = {}
    for r in rows:
        pid = r["product_id"]
        if pid in latest or r.get("price") is None:
            continue
        latest[pid] = int(r["price"])
    return latest


def _bulk_upsert_stats(db: _SupabaseLike, stats: list[MarketStats], chunk: int = 200) -> None:
    if not stats:
        return
    payloads = [
        {
            "product_id": s.product_id,
            "category": s.category,
            "used_count": s.used_count,
            "used_min": s.used_min,
            "used_max": s.used_max,
            "used_median": s.used_median,
            "used_mean": s.used_mean,
            "used_latest": s.used_latest,
            "used_latest_at": s.used_latest_at,
            "new_price": s.new_price,
            "used_to_new_ratio": s.used_to_new_ratio,
            "window_days": s.window_days,
        }
        for s in stats
    ]
    for i in range(0, len(payloads), chunk):
        batch = payloads[i : i + chunk]
        db.table("product_market_stats").upsert(batch, on_conflict="product_id").execute()


def aggregate_market_stats(
    db: _SupabaseLike,
    *,
    category: str | None = None,
    window_days: int = 30,
) -> dict:
    """Recompute product_market_stats. Returns summary.

    Batched: pulls all products + all snapshots in pages, joins in memory,
    bulk-upserts in chunks. O(rows) DB roundtrips instead of O(products).
    """
    since = _iso_window_start(window_days)
    products = _fetch_all_products(db, category)
    print(f"Aggregating {len(products)} products...")

    used_by_pid = _fetch_all_used_snapshots_grouped(db, since)
    new_by_pid = _fetch_latest_new_prices(db)

    stats_list: list[MarketStats] = []
    with_used = 0
    for p in products:
        used = used_by_pid.get(p["id"], [])
        stats = compute_stats(
            product_id=p["id"],
            category=p["category"],
            used_snapshots=used,
            new_price=new_by_pid.get(p["id"]),
            window_days=window_days,
        )
        stats_list.append(stats)
        if stats.used_count > 0:
            with_used += 1

    _bulk_upsert_stats(db, stats_list)

    print(
        f"Aggregated {len(stats_list)} products"
        f"{' (category=' + category + ')' if category else ''}"
        f", {with_used} have used snapshots in last {window_days} day(s)"
    )
    return {"written": len(stats_list), "with_used": with_used, "window_days": window_days}
