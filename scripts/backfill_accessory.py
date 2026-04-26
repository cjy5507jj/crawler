#!/usr/bin/env python3
"""One-shot backfill: recompute is_accessory for every existing product.

Run after applying migration_004_accessory_flag.sql. Safe to re-run — only
updates rows where the flag actually flipped, so writes are minimized.
"""

from __future__ import annotations

from src.clients.supabase_client import get_client
from src.normalization.catalog import is_accessory_product


_PAGE_SIZE = 1000
_UPDATE_CHUNK = 200


def _page_products(db) -> list[dict]:
    out: list[dict] = []
    offset = 0
    while True:
        rows = (
            db.table("products")
            .select("id,name,is_accessory")
            .range(offset, offset + _PAGE_SIZE - 1)
            .execute()
            .data
        )
        if not rows:
            break
        out.extend(rows)
        if len(rows) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE
    return out


def main() -> None:
    db = get_client()

    products = _page_products(db)
    print(f"Loaded {len(products)} products")

    flipped_true: list[str] = []
    flipped_false: list[str] = []
    flagged_total = 0

    for p in products:
        new_flag = is_accessory_product(p.get("name") or "")
        if new_flag:
            flagged_total += 1
        # Treat None as False (column has not-null default false, but defensive).
        old_flag = bool(p.get("is_accessory"))
        if new_flag and not old_flag:
            flipped_true.append(p["id"])
        elif not new_flag and old_flag:
            flipped_false.append(p["id"])

    print(
        f"Scanned {len(products)} | accessory={flagged_total} "
        f"| flip→true={len(flipped_true)} flip→false={len(flipped_false)}"
    )

    # Bulk update in chunks. Supabase has no batch-update-by-id-list, so we
    # iterate ids; chunking only bounds the loop progress reporting.
    def _apply(ids: list[str], value: bool) -> None:
        for i in range(0, len(ids), _UPDATE_CHUNK):
            batch = ids[i : i + _UPDATE_CHUNK]
            for pid in batch:
                db.table("products").update({"is_accessory": value}).eq("id", pid).execute()
            print(f"  updated {min(i + _UPDATE_CHUNK, len(ids))}/{len(ids)} → {value}")

    if flipped_true:
        print(f"Flipping {len(flipped_true)} → true")
        _apply(flipped_true, True)
    if flipped_false:
        print(f"Flipping {len(flipped_false)} → false")
        _apply(flipped_false, False)

    print("Done.")


if __name__ == "__main__":
    main()
