"""Read-only diagnostics for used-market storage quality."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable, Protocol


class _SupabaseLike(Protocol):
    def table(self, name: str): ...


def _page_through(query, page_size: int = 1000, max_pages: int = 100) -> list[dict]:
    out: list[dict] = []
    offset = 0
    for _ in range(max_pages):
        rows = query.range(offset, offset + page_size - 1).execute().data
        if not rows:
            break
        out.extend(rows)
        if len(rows) < page_size:
            break
        offset += page_size
    return out


def _date_key(value: str) -> str:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt.astimezone(timezone.utc).date().isoformat()


def duplicate_like_snapshot_stats(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    """Approximate duplicate pressure for legacy snapshots.

    Current `price_snapshots` rows do not carry listing identity, so this groups
    by product/source/price/UTC-day. It is intentionally conservative: it is a
    storage-pressure signal, not a deletion rule.
    """
    counts: Counter[tuple[Any, Any, Any, str]] = Counter()
    for row in rows:
        if row.get("market_type") not in {"used", "b2c"}:
            continue
        snapshot_at = row.get("snapshot_at")
        if not snapshot_at:
            continue
        counts[
            (
                row.get("product_id"),
                row.get("source"),
                row.get("price"),
                _date_key(str(snapshot_at)),
            )
        ] += 1

    repeated = [count for count in counts.values() if count > 1]
    return {
        "keys": len(counts),
        "repeated_keys": len(repeated),
        "extra_rows": sum(count - 1 for count in repeated),
        "max_repeat": max(repeated) if repeated else 0,
    }


def audit_used_data(db: _SupabaseLike, *, sample_pages: int = 120) -> dict[str, Any]:
    used_count = db.table("used_listings").select("id", count="exact").limit(1).execute().count
    snapshot_count = (
        db.table("price_snapshots").select("id", count="exact").limit(1).execute().count
    )
    history_count = (
        db.table("product_market_stats_history")
        .select("id", count="exact")
        .limit(1)
        .execute()
        .count
    )
    try:
        observation_count = (
            db.table("used_listing_observations")
            .select("id", count="exact")
            .limit(1)
            .execute()
            .count
        )
    except Exception:
        observation_count = None

    used_rows = _page_through(
        db.table("used_listings")
        .select("source,status,matched_product_id,match_score,crawled_at")
        .order("crawled_at", desc=True),
        max_pages=sample_pages,
    )
    snapshot_rows = _page_through(
        db.table("price_snapshots")
        .select("product_id,source,market_type,price,snapshot_at")
        .order("snapshot_at", desc=True),
        max_pages=sample_pages,
    )
    observation_rows: list[dict] = []
    if observation_count is not None:
        observation_rows = _page_through(
            db.table("used_listing_observations")
            .select("source,status,seen_count,last_observed_at")
            .order("last_observed_at", desc=True),
            max_pages=min(sample_pages, 20),
        )

    return {
        "counts": {
            "used_listings": used_count,
            "price_snapshots": snapshot_count,
            "product_market_stats_history": history_count,
            "used_listing_observations": observation_count,
            "used_sampled": len(used_rows),
            "snapshots_sampled": len(snapshot_rows),
            "observations_sampled": len(observation_rows),
        },
        "used_by_source": dict(Counter(row.get("source") for row in used_rows)),
        "used_by_status": dict(Counter(row.get("status") or "null" for row in used_rows)),
        "used_matched": sum(1 for row in used_rows if row.get("matched_product_id")),
        "duplicate_like_snapshots": duplicate_like_snapshot_stats(snapshot_rows),
        "observations_by_source": dict(
            Counter(row.get("source") for row in observation_rows)
        ),
        "observations_by_status": dict(
            Counter(row.get("status") or "null" for row in observation_rows)
        ),
        "observation_seen_count_total": sum(
            int(row.get("seen_count") or 0) for row in observation_rows
        ),
    }
