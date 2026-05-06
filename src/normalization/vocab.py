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


_UNSAFE_DYNAMIC_SKU_PARTS = {
    "rtx",
    "gtx",
    "geforce",
    "지포스",
    "radeon",
    "라데온",
    "라이젠",
    "ryzen",
    "intel",
    "인텔",
}


def _norm_alias(value: str) -> str:
    return _catalog.normalize_text(value).replace(" ", "-")


def _constant_brands() -> list[tuple[str, tuple[str, ...]]]:
    return list(_catalog.BRAND_ALIASES.items())


def _constant_sku_lines() -> dict[str, list[tuple[str, tuple[str, ...]]]]:
    return {
        cat: [(entry[0], tuple(entry)) for entry in entries]
        for cat, entries in _catalog.SKU_LINE_TOKENS.items()
    }


def _merge_brands(rows: list[dict]) -> list[tuple[str, tuple[str, ...]]]:
    merged = _constant_brands()
    seen = {canonical for canonical, _ in merged}
    for row in rows:
        canonical = row["canonical"]
        if canonical in seen:
            continue
        merged.append(
            (
                canonical,
                tuple(set([canonical, *(row.get("aliases") or [])])),
            )
        )
        seen.add(canonical)
    return merged


def _is_safe_dynamic_sku_line(
    *,
    category: str,
    canonical: str,
    aliases: tuple[str, ...],
    known_aliases: set[str],
) -> bool:
    normalized = {_norm_alias(value) for value in (canonical, *aliases)}
    if normalized & known_aliases:
        return False
    if any(
        value != known and (value in known or known in value)
        for value in normalized
        for known in known_aliases
    ):
        return False
    for value in normalized:
        if any(part in value for part in _UNSAFE_DYNAMIC_SKU_PARTS):
            return False
        if category == "gpu" and any(brand in value for brand in ("msi", "asus", "zotac")):
            return False
        if len(value.split("-")) > 3:
            return False
    return True


def _merge_sku_lines(rows: list[dict]) -> dict[str, list[tuple[str, tuple[str, ...]]]]:
    grouped = _constant_sku_lines()
    known_by_category: dict[str, set[str]] = {}
    for category, entries in grouped.items():
        known_by_category[category] = {
            _norm_alias(alias)
            for canonical, aliases in entries
            for alias in (canonical, *aliases)
        }

    seen = {
        (category, canonical)
        for category, entries in grouped.items()
        for canonical, _ in entries
    }
    for row in rows:
        category = row["category"]
        canonical = row["canonical"]
        aliases = tuple(set([canonical, *(row.get("aliases") or [])]))
        if (category, canonical) in seen:
            continue
        if not _is_safe_dynamic_sku_line(
            category=category,
            canonical=canonical,
            aliases=aliases,
            known_aliases=known_by_category.setdefault(category, set()),
        ):
            continue
        grouped.setdefault(category, []).append((canonical, aliases))
        seen.add((category, canonical))
        known_by_category[category].update(_norm_alias(alias) for alias in aliases)
    return grouped


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

    brands = _merge_brands(b_rows) if b_rows else None
    sku_lines = _merge_sku_lines(s_rows) if s_rows else None
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
            b = _constant_brands()
        if s is None:
            s = _constant_sku_lines()
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
