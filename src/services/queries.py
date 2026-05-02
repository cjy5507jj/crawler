"""Generate search queries for search-style adapters from products in DB.

Picks the most useful model_name strings per category — distinct, non-empty,
preferring those that are short enough to be effective search keywords.

Augmented with category-specific cold-spot seed keywords (case/psu/cooler/hdd)
that don't surface naturally from product model_names — generic Korean
keywords ("미들타워", "850W 골드") drive bunjang/joongna recall on categories
whose model_name strings are too SKU-specific.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Protocol

from src.domains.consumer.catalog import query_seeds_for_category


class _SupabaseLike(Protocol):
    def table(self, name: str): ...


# Filter: keywords likely to return useful matches when fed to Bunjang/Daangn/Joongna search
_TOO_SHORT = 2          # below this length is too generic
_TOO_LONG = 30          # above this length is too specific
_BAD_TOKENS = {"plus", "pro", "evo", "max"}   # stand-alone words too generic


# Cold-spot category seed queries — generic Korean keywords that pull broad
# secondary-market listings for categories whose model_name strings (e.g.
# "AAA-X470 Pro Wifi-X") are too SKU-specific to drive recall on their own.
# Prepended to the model-derived list — guaranteed in the output regardless
# of frequency. Source: handoff/used-market-coverage-handoff.md §3.1 + Day 1
# matrix (docs/diagnosis/used-market-sources-matrix.md §4.3).
_CATEGORY_SEED_QUERIES: dict[str, tuple[str, ...]] = {
    "case": (
        "미들타워 케이스",
        "ATX 케이스",
        "강화유리 케이스",
        "큐브 케이스",
    ),
    "psu": (
        "850W 골드",
        "750W 모듈러",
        "1000W 플래티넘",
        "850W 파워",
    ),
    "cooler": (
        "공랭쿨러",
        "AIO 240",
        "수랭 360",
        "CPU 쿨러",
    ),
    "hdd": (
        "WD 8TB",
        "Seagate IronWolf",
        "외장하드 4TB",
        "WD 4TB",
    ),
}


def _good_query(model_name: str) -> bool:
    if not model_name:
        return False
    cleaned = model_name.strip()
    if len(cleaned) < _TOO_SHORT or len(cleaned) > _TOO_LONG:
        return False
    if cleaned.lower() in _BAD_TOKENS:
        return False
    # Require at least one digit OR a model-like word (avoids pure brand strings)
    if not re.search(r"\d", cleaned):
        return False
    return True


def _seed_queries_for_category(category: str) -> list[str]:
    return list(
        query_seeds_for_category(category) or _CATEGORY_SEED_QUERIES.get(category, ())
    )


def _combined_brand_query(brand: str, model_name: str) -> str | None:
    if not brand:
        return None
    if model_name.lower().startswith(brand.lower()):
        return None

    combined = f"{brand} {model_name}"
    if len(combined) > _TOO_LONG:
        return None
    return combined


def _add_model_queries(counter: Counter[str], row: dict) -> None:
    model_name = (row.get("model_name") or "").strip()
    if not _good_query(model_name):
        return

    counter[model_name] += 1

    brand = (row.get("brand") or "").strip()
    combined = _combined_brand_query(brand, model_name)
    if combined:
        counter[combined] += 1


def derive_queries(
    db: _SupabaseLike,
    *,
    category: str,
    limit: int = 15,
) -> list[str]:
    """Return up to `limit` distinct queries derived from products in `category`.

    Strategy:
      1. Read `brand` + `model_name` for every product in the category.
      2. Plain `model_name` is always a candidate (frequency-counted across
         brands so a popular model bubbles up first).
      3. When `brand` is present and `model_name` does not already start with
         it, also emit a `"<brand> <model>"` combined query — search-style
         sources (joonggonara/bunjang/daangn) match better with brand context,
         which is critical for sparse categories like monitor/cpu.
      4. Filter both shapes through `_good_query` and the length cap.
      5. Order by frequency, most-listed first.
      6. For cold-spot categories (case/psu/cooler/hdd), prepend generic
         Korean seed keywords — guaranteed in output even when limit is small.
    """
    rows = (
        db.table("products")
        .select("brand,model_name")
        .eq("category", category)
        .execute()
        .data
    )
    counter: Counter[str] = Counter()
    for row in rows:
        _add_model_queries(counter, row)

    seed = _seed_queries_for_category(category)
    seed_set = {s for s in seed}
    model_queries = [
        name for name, _ in counter.most_common() if name not in seed_set
    ]
    return (seed + model_queries)[:limit]
