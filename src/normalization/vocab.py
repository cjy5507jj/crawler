"""Lazy-loaded vocabulary cache.

`detect_brand` / `extract_sku_line_tokens` query this module instead of the
hardcoded constants in `catalog.py`. The cache is filled on first use from
Supabase tables (`brands`, `sku_lines`). If the DB is unreachable or empty
(cold start), we fall back to the hardcoded constants so the system still
works out of the box.

Cache lifetime: per-process. Call `refresh()` to reload after running
`scripts/discover_vocab.py`.
"""

from __future__ import annotations

import os
from threading import Lock

from src.normalization import catalog as _catalog


_lock = Lock()
_brands_cache: list[tuple[str, tuple[str, ...]]] | None = None
_sku_lines_cache: dict[str, list[tuple[str, tuple[str, ...]]]] | None = None


def _load_from_db() -> tuple[
    list[tuple[str, tuple[str, ...]]] | None,
    dict[str, list[tuple[str, tuple[str, ...]]]] | None,
]:
    if not os.environ.get("SUPABASE_URL"):
        return None, None
    try:
        from src.clients.supabase_client import get_client

        db = get_client()
        b_rows = (
            db.table("brands")
            .select("canonical,aliases,confidence")
            .order("confidence", desc=True)
            .execute()
            .data
        )
        s_rows = (
            db.table("sku_lines")
            .select("canonical,category,aliases,confidence")
            .order("confidence", desc=True)
            .execute()
            .data
        )
    except Exception as e:
        print(f"  [vocab] DB load failed, using hardcoded fallback: {e}")
        return None, None

    if not b_rows:
        brands = None
    else:
        brands = [
            (
                r["canonical"],
                tuple(set([r["canonical"], *(r.get("aliases") or [])])),
            )
            for r in b_rows
        ]
    if not s_rows:
        sku_lines = None
    else:
        grouped: dict[str, list[tuple[str, tuple[str, ...]]]] = {}
        for r in s_rows:
            grouped.setdefault(r["category"], []).append(
                (
                    r["canonical"],
                    tuple(set([r["canonical"], *(r.get("aliases") or [])])),
                )
            )
        sku_lines = grouped
    return brands, sku_lines


def _ensure_loaded() -> None:
    global _brands_cache, _sku_lines_cache
    if _brands_cache is not None and _sku_lines_cache is not None:
        return
    with _lock:
        if _brands_cache is not None and _sku_lines_cache is not None:
            return
        b, s = _load_from_db()

        # Fall back to hardcoded if DB returned nothing (cold start)
        if b is None:
            b = list(_catalog.BRAND_ALIASES.items())
        if s is None:
            s = {
                cat: [(entry[0], tuple(entry)) for entry in entries]
                for cat, entries in _catalog.SKU_LINE_TOKENS.items()
            }
        _brands_cache = b
        _sku_lines_cache = s


def refresh() -> None:
    """Drop the cache so the next call reloads from DB."""
    global _brands_cache, _sku_lines_cache
    with _lock:
        _brands_cache = None
        _sku_lines_cache = None


def brand_aliases() -> list[tuple[str, tuple[str, ...]]]:
    """Return all brand aliases including chip vendors.

    GPU-specific suppression of chip vendors happens in `detect_brand`
    (see `catalog.CHIPSET_ALIASES`). Non-GPU categories still want chip
    vendors as a valid brand match (CPU brand=amd/intel).
    """
    _ensure_loaded()
    assert _brands_cache is not None
    return _brands_cache


def chipset_aliases() -> list[tuple[str, tuple[str, ...]]]:
    """Return chip vendor aliases (nvidia / amd / intel).

    Always uses the hardcoded `CHIPSET_ALIASES` constant — DB rows omit
    the GPU-specific aliases like `라데온` that chipset extraction needs.
    """
    return list(_catalog.CHIPSET_ALIASES.items())


def sku_line_aliases(category: str) -> list[tuple[str, tuple[str, ...]]]:
    _ensure_loaded()
    assert _sku_lines_cache is not None
    return _sku_lines_cache.get(category.lower(), [])
