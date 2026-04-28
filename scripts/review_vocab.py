#!/usr/bin/env python3
"""Interactive review of `unknown_vocab` tokens.

Surfaces the most-frequently-seen unreviewed tokens and lets a human classify
each as a brand, SKU line, skipped (mark reviewed), or deleted. Promoted
entries land in `brands` / `sku_lines` and become eligible for matching on
the next vocab refresh.

Usage:
    python scripts/review_vocab.py --top 20
    python scripts/review_vocab.py --top 5 --category gpu
"""

from __future__ import annotations

import argparse
import sys
from typing import Iterable, Protocol


class _DBLike(Protocol):
    def table(self, name: str): ...


def _fetch_top_unknown(
    db: _DBLike,
    *,
    top: int,
    category: str | None = None,
) -> list[dict]:
    q = (
        db.table("unknown_vocab")
        .select("token,category,seen_count")
        .eq("reviewed", False)
    )
    if category:
        q = q.eq("category", category)
    return (
        q.order("seen_count", desc=True).limit(top).execute().data or []
    )


def _fetch_listing_samples(
    db: _DBLike, *, token: str, category: str, limit: int = 3
) -> list[str]:
    rows = (
        db.table("used_listings")
        .select("title")
        .eq("category", category)
        .ilike("title", f"%{token}%")
        .order("crawled_at", desc=True)
        .limit(limit)
        .execute()
        .data
        or []
    )
    return [r["title"] for r in rows if r.get("title")]


def _promote_to_brand(db: _DBLike, token: str) -> dict:
    """Insert into brands (if missing) and mark unknown_vocab rows for the
    same token as reviewed across all categories."""
    canonical = token.strip().lower()
    existing = (
        db.table("brands")
        .select("id,aliases")
        .eq("canonical", canonical)
        .limit(1)
        .execute()
        .data
        or []
    )
    if existing:
        old = existing[0]
        merged = list({*(old.get("aliases") or []), canonical})
        db.table("brands").update(
            {"aliases": merged, "updated_at": "now()"}
        ).eq("id", old["id"]).execute()
        action = "updated"
    else:
        db.table("brands").insert(
            {
                "canonical": canonical,
                "display": canonical.upper() if canonical.isascii() else canonical,
                "aliases": [canonical],
                "confidence": 0.9,
                "source": "manual_review",
                "doc_freq": 0,
            }
        ).execute()
        action = "inserted"
    db.table("unknown_vocab").update({"reviewed": True}).eq(
        "token", canonical
    ).execute()
    return {"action": action, "canonical": canonical}


def _promote_to_sku_line(db: _DBLike, token: str, category: str) -> dict:
    canonical = token.strip().lower()
    existing = (
        db.table("sku_lines")
        .select("id")
        .eq("canonical", canonical)
        .eq("category", category)
        .limit(1)
        .execute()
        .data
        or []
    )
    if existing:
        action = "exists"
    else:
        db.table("sku_lines").insert(
            {
                "canonical": canonical,
                "category": category,
                "aliases": [canonical],
                "doc_freq": 0,
                "confidence": 0.9,
                "source": "manual_review",
            }
        ).execute()
        action = "inserted"
    db.table("unknown_vocab").update({"reviewed": True}).eq(
        "token", canonical
    ).eq("category", category).execute()
    return {"action": action, "canonical": canonical, "category": category}


def _skip_token(db: _DBLike, token: str, category: str) -> dict:
    db.table("unknown_vocab").update({"reviewed": True}).eq(
        "token", token
    ).eq("category", category).execute()
    return {"action": "skipped", "token": token, "category": category}


def _delete_token(db: _DBLike, token: str, category: str) -> dict:
    db.table("unknown_vocab").delete().eq("token", token).eq(
        "category", category
    ).execute()
    return {"action": "deleted", "token": token, "category": category}


def _prompt(text: str, choices: Iterable[str]) -> str:
    """One round of input. Returns the lowercase first char of the answer."""
    valid = {c.lower() for c in choices}
    while True:
        try:
            ans = input(text).strip().lower()
        except EOFError:
            return "q"
        if ans and ans[0] in valid:
            return ans[0]
        print(f"  -> please enter one of {sorted(valid)}")


def _interactive_loop(db: _DBLike, rows: list[dict]) -> dict:
    counts = {"brand": 0, "sku_line": 0, "skipped": 0, "deleted": 0}
    total = len(rows)
    for idx, row in enumerate(rows, start=1):
        token = row["token"]
        category = row["category"]
        seen = row.get("seen_count", 0)
        samples = _fetch_listing_samples(db, token=token, category=category, limit=3)

        print()
        print(f"[{idx}/{total}] cat={category}  token='{token}'  seen={seen}")
        if samples:
            print("  관련 listing 샘플:")
            for s in samples:
                print(f"    - {s}")
        else:
            print("  (관련 listing 없음)")

        ans = _prompt(
            "  [b]rand / [s]ku_line / [k]ip / [d]elete / [q]uit: ",
            "bskdq",
        )
        if ans == "q":
            print("  → 종료 요청")
            break
        if ans == "b":
            _promote_to_brand(db, token)
            counts["brand"] += 1
            print(f"  ✓ '{token}' → brand")
        elif ans == "s":
            _promote_to_sku_line(db, token, category)
            counts["sku_line"] += 1
            print(f"  ✓ '{token}' → sku_line ({category})")
        elif ans == "k":
            _skip_token(db, token, category)
            counts["skipped"] += 1
            print(f"  ✓ '{token}' → skipped")
        elif ans == "d":
            _delete_token(db, token, category)
            counts["deleted"] += 1
            print(f"  ✓ '{token}' → deleted")
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top", type=int, default=20, help="Top-N tokens to review")
    parser.add_argument("--category", type=str, default=None, help="Filter by category")
    args = parser.parse_args()

    # Lazy import: keeps the module importable in tests without triggering
    # dotenv side effects (which would warm the vocab cache from real DB).
    from src.clients.supabase_client import get_client

    db = get_client()
    rows = _fetch_top_unknown(db, top=args.top, category=args.category)
    if not rows:
        print("No unreviewed unknown_vocab rows.")
        return

    print(f"Reviewing {len(rows)} token(s). Press q to quit.")
    counts = _interactive_loop(db, rows)
    print()
    print(
        "Summary — "
        f"brand: {counts['brand']}, sku_line: {counts['sku_line']}, "
        f"skipped: {counts['skipped']}, deleted: {counts['deleted']}"
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAborted.", file=sys.stderr)
        sys.exit(130)
