#!/usr/bin/env python3
"""Audit used-market storage growth, matching coverage, and duplicate pressure."""

from __future__ import annotations

import argparse
import json

from src.clients.supabase_client import get_client
from src.services.used_audit import audit_used_data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sample-pages",
        type=int,
        default=120,
        help="Number of 1000-row pages to sample from recent used/snapshot tables.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the full audit report as JSON.",
    )
    args = parser.parse_args()

    report = audit_used_data(get_client(), sample_pages=args.sample_pages)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return

    counts = report["counts"]
    dup = report["duplicate_like_snapshots"]
    print("Used data audit")
    print(f"- used_listings: {counts['used_listings']}")
    print(f"- price_snapshots: {counts['price_snapshots']}")
    print(f"- product_market_stats_history: {counts['product_market_stats_history']}")
    print(f"- used_listing_observations: {counts['used_listing_observations']}")
    print(f"- sampled used listings: {counts['used_sampled']}")
    print(f"- sampled snapshots: {counts['snapshots_sampled']}")
    print(f"- matched used listings in sample: {report['used_matched']}")
    print(
        "- duplicate-like snapshot pressure: "
        f"{dup['extra_rows']} extra rows across {dup['repeated_keys']} repeated keys "
        f"(max repeat {dup['max_repeat']})"
    )
    print(f"- used_by_source: {report['used_by_source']}")
    print(f"- used_by_status: {report['used_by_status']}")
    print(f"- observations_by_source: {report['observations_by_source']}")
    print(f"- observations_by_status: {report['observations_by_status']}")
    print(f"- observation_seen_count_total: {report['observation_seen_count_total']}")


if __name__ == "__main__":
    main()
