#!/usr/bin/env python3
"""Evaluate price-alert watchlists and dispatch notifications.

Reads `watchlists` (active=true), compares each row's target_price with the
current `product_market_stats.used_median`, and fires an alert via
`src.services.alerts.notify` when the threshold is crossed. Updates
`last_alerted_at` so the 24h cool-down kicks in.

Intended to run after `aggregate_market_stats` (e.g. at the end of run_all.py)
or standalone via cron / launchd.
"""

from __future__ import annotations

import argparse

from src.clients.supabase_client import get_client
from src.services.alerts import notify
from src.services.watchlist import (
    COOLDOWN_HOURS,
    check_watchlists,
    format_message,
    mark_alerted,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cooldown-hours",
        type=int,
        default=COOLDOWN_HOURS,
        help=f"Hours to suppress repeat alerts (default: {COOLDOWN_HOURS})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print would-be alerts without notifying or marking as alerted",
    )
    args = parser.parse_args()

    db = get_client()
    triggers = check_watchlists(db, cooldown_hours=args.cooldown_hours)
    if not triggers:
        print("No watchlist alerts.")
        return

    for t in triggers:
        msg = format_message(t)
        if args.dry_run:
            print(f"[dry-run] {msg}")
            continue
        notify(msg, level="alert")
        mark_alerted(db, t.watchlist_id)

    print(f"Dispatched {len(triggers)} alert(s).")


if __name__ == "__main__":
    main()
