"""Generate search queries for search-style adapters from products in DB.

Picks the most useful model_name strings per category — distinct, non-empty,
preferring those that are short enough to be effective search keywords.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Protocol


class _SupabaseLike(Protocol):
    def table(self, name: str): ...


# Filter: keywords likely to return useful matches when fed to Bunjang/Daangn/Joongna search
_TOO_SHORT = 2          # below this length is too generic
_TOO_LONG = 30          # above this length is too specific
_BAD_TOKENS = {"plus", "pro", "evo", "max"}   # stand-alone words too generic


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


def derive_queries(
    db: _SupabaseLike,
    *,
    category: str,
    limit: int = 15,
) -> list[str]:
    """Return up to `limit` distinct queries derived from products in `category`.

    Strategy:
    1. Read distinct `model_name` values from products in the category.
    2. Filter for queries useful in third-party search (`_good_query`).
    3. Order by frequency (most-listed model first).
    """
    rows = (
        db.table("products")
        .select("model_name")
        .eq("category", category)
        .execute()
        .data
    )
    counter: Counter[str] = Counter()
    for r in rows:
        mn = (r.get("model_name") or "").strip()
        if _good_query(mn):
            counter[mn] += 1

    return [name for name, _ in counter.most_common(limit)]
