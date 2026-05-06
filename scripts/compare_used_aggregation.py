#!/usr/bin/env python3
"""Compare legacy snapshot stats with deduped observation stats without writing."""

from __future__ import annotations

import argparse
from statistics import median

from src.clients.supabase_client import get_client
from src.crawlers.danawa import CATEGORY_MAP
from src.services.aggregate import (
    _fetch_all_products,
    _fetch_all_used_observations_grouped,
    _fetch_all_used_snapshots_grouped,
    _fetch_latest_new_prices,
    _iso_window_start,
    compute_stats,
)


def _pct_delta(new: int | None, old: int | None) -> float | None:
    if new is None or old in (None, 0):
        return None
    return round((new - old) / old * 100, 2)


def compare_used_aggregation(db, *, category: str | None, window_days: int) -> dict:
    products = _fetch_all_products(db, category)
    since_iso = _iso_window_start(window_days)
    since_date = since_iso[:10]
    snapshot_by_pid = _fetch_all_used_snapshots_grouped(db, since_iso)
    supported, observation_by_pid = _fetch_all_used_observations_grouped(db, since_date)
    if not supported:
        raise RuntimeError("used_listing_observations is unavailable")
    hybrid_by_pid = {
        pid: observation_by_pid.get(pid) or snapshots
        for pid, snapshots in snapshot_by_pid.items()
    }
    for pid, observations in observation_by_pid.items():
        if pid not in hybrid_by_pid:
            hybrid_by_pid[pid] = observations
    new_by_pid = _fetch_latest_new_prices(db)

    compared = []
    snapshot_with_used = 0
    observation_with_used = 0
    hybrid_with_used = 0
    for product in products:
        pid = product["id"]
        snapshot_stats = compute_stats(
            product_id=pid,
            category=product["category"],
            used_snapshots=snapshot_by_pid.get(pid, []),
            new_price=new_by_pid.get(pid),
            window_days=window_days,
        )
        observation_stats = compute_stats(
            product_id=pid,
            category=product["category"],
            used_snapshots=observation_by_pid.get(pid, []),
            new_price=new_by_pid.get(pid),
            window_days=window_days,
        )
        hybrid_stats = compute_stats(
            product_id=pid,
            category=product["category"],
            used_snapshots=hybrid_by_pid.get(pid, []),
            new_price=new_by_pid.get(pid),
            window_days=window_days,
        )
        if snapshot_stats.used_count > 0:
            snapshot_with_used += 1
        if observation_stats.used_count > 0:
            observation_with_used += 1
        if hybrid_stats.used_count > 0:
            hybrid_with_used += 1
        if snapshot_stats.used_count > 0 or observation_stats.used_count > 0 or hybrid_stats.used_count > 0:
            compared.append(
                {
                    "product_id": pid,
                    "category": product["category"],
                    "snapshot_count": snapshot_stats.used_count,
                    "observation_count": observation_stats.used_count,
                    "hybrid_count": hybrid_stats.used_count,
                    "snapshot_median": snapshot_stats.used_median,
                    "observation_median": observation_stats.used_median,
                    "hybrid_median": hybrid_stats.used_median,
                    "median_delta_pct": _pct_delta(
                        observation_stats.used_median,
                        snapshot_stats.used_median,
                    ),
                    "hybrid_delta_pct": _pct_delta(
                        hybrid_stats.used_median,
                        snapshot_stats.used_median,
                    ),
                }
            )

    deltas = [
        row["median_delta_pct"]
        for row in compared
        if row["median_delta_pct"] is not None
    ]
    hybrid_deltas = [
        row["hybrid_delta_pct"]
        for row in compared
        if row["hybrid_delta_pct"] is not None
    ]
    count_deltas = [
        row["snapshot_count"] - row["observation_count"]
        for row in compared
        if row["snapshot_count"] or row["observation_count"]
    ]
    hybrid_count_deltas = [
        row["snapshot_count"] - row["hybrid_count"]
        for row in compared
        if row["snapshot_count"] or row["hybrid_count"]
    ]
    changed = [row for row in compared if row["median_delta_pct"] not in (None, 0)]
    changed.sort(key=lambda row: abs(row["median_delta_pct"] or 0), reverse=True)

    return {
        "products": len(products),
        "compared": len(compared),
        "snapshot_with_used": snapshot_with_used,
        "observation_with_used": observation_with_used,
        "hybrid_with_used": hybrid_with_used,
        "median_delta_p50_pct": median(deltas) if deltas else None,
        "median_delta_max_abs_pct": max((abs(d) for d in deltas), default=None),
        "hybrid_delta_p50_pct": median(hybrid_deltas) if hybrid_deltas else None,
        "hybrid_delta_max_abs_pct": max((abs(d) for d in hybrid_deltas), default=None),
        "sample_count_delta_total": sum(count_deltas),
        "hybrid_sample_count_delta_total": sum(hybrid_count_deltas),
        "top_changed": changed[:10],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--category", choices=sorted(CATEGORY_MAP), default=None)
    parser.add_argument("--window-days", type=int, default=30)
    args = parser.parse_args()

    result = compare_used_aggregation(
        get_client(),
        category=args.category,
        window_days=args.window_days,
    )
    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
