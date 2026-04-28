"""Fixture-based regression tests for src.services.discovery.

Tests `discover_brands_from_products`, `discover_sku_lines_from_products`,
and `auto_map_canonical_categories` against a frozen 27-product fixture.
A change to the discovery heuristics that drops well-known brands (ASUS,
MSI, Intel, …) or known SKU lines (ventus, shadow, …) trips this guard.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.services.discovery import (
    auto_map_canonical_categories,
    discover_brands_from_products,
    discover_sku_lines_from_products,
)


_FIXTURE = (
    Path(__file__).parent / "fixtures" / "discovery" / "products_sample.json"
)


def _load_products() -> list[dict]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


# ---------- minimal fake supabase --------------------------------------------


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, table: "_Table"):
        self.table = table
        self._eqs: list[tuple[str, object]] = []
        self._is_null: str | None = None
        self._range: tuple[int, int] | None = None
        self._limit: int | None = None
        self._update: dict | None = None
        self._insert: dict | None = None

    def select(self, *_cols):
        return self

    def eq(self, col, val):
        self._eqs.append((col, val))
        return self

    def is_(self, col, val):
        if val == "null":
            self._is_null = col
        return self

    def range(self, lo, hi):
        self._range = (lo, hi)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def update(self, payload):
        self._update = payload
        return self

    def insert(self, payload):
        self._insert = payload
        return self

    def _matches(self, row: dict) -> bool:
        for col, val in self._eqs:
            if row.get(col) != val:
                return False
        if self._is_null is not None and row.get(self._is_null) is not None:
            return False
        return True

    def execute(self):
        if self._insert is not None:
            payloads = (
                self._insert if isinstance(self._insert, list) else [self._insert]
            )
            inserted = []
            for p in payloads:
                row = dict(p)
                row.setdefault("id", len(self.table.rows) + 1)
                self.table.rows.append(row)
                inserted.append(row)
            return _Result(inserted)
        if self._update is not None:
            for r in self.table.rows:
                if self._matches(r):
                    r.update(self._update)
            return _Result([])
        rows = [dict(r) for r in self.table.rows if self._matches(r)]
        if self._range is not None:
            lo, hi = self._range
            rows = rows[lo : hi + 1]
        if self._limit is not None:
            rows = rows[: self._limit]
        return _Result(rows)


class _Table:
    def __init__(self):
        self.rows: list[dict] = []


class _DB:
    def __init__(self):
        self._tables: dict[str, _Table] = {}

    def table(self, name):
        if name not in self._tables:
            self._tables[name] = _Table()
        return _Query(self._tables[name])

    def rows(self, name):
        return self._tables.setdefault(name, _Table()).rows

    def seed(self, name, rows):
        self.table(name)
        self._tables[name].rows.extend(rows)


# ---------- discover_brands_from_products ------------------------------------


def test_discover_brands_from_fixture_finds_known_brands() -> None:
    db = _DB()
    db.seed("products", _load_products())

    summary = discover_brands_from_products(db, min_doc_freq=2)

    assert summary["wrote"] >= 6  # asus, msi, gigabyte, intel, amd, samsung, ...
    canonicals = {r["canonical"] for r in db.rows("brands")}
    for expected in ("asus", "msi", "intel", "amd", "samsung", "corsair"):
        assert expected in canonicals, f"{expected!r} missing: {canonicals}"


def test_discover_brands_respects_min_doc_freq() -> None:
    db = _DB()
    db.seed("products", _load_products())

    discover_brands_from_products(db, min_doc_freq=3)
    canonicals = {r["canonical"] for r in db.rows("brands")}
    # ASUS appears 3× in gpu, MSI appears 3× — both should pass freq=3.
    assert "asus" in canonicals
    assert "msi" in canonicals


# ---------- discover_sku_lines_from_products ---------------------------------


def test_discover_sku_lines_from_fixture_finds_subline_tokens() -> None:
    db = _DB()
    db.seed("products", _load_products())

    summary = discover_sku_lines_from_products(db, min_doc_freq=2, max_share=0.5)

    assert summary["total"] >= 1
    by_cat: dict[str, set[str]] = {}
    for r in db.rows("sku_lines"):
        by_cat.setdefault(r["category"], set()).add(r["canonical"])

    # gpu sub-models: ventus (MSI), shadow (이엠텍) appear ≥ 2× in gpu only.
    assert "gpu" in by_cat
    assert "ventus" in by_cat["gpu"], by_cat.get("gpu")
    assert "shadow" in by_cat["gpu"], by_cat.get("gpu")


def test_discover_sku_lines_skips_cross_category_terms() -> None:
    db = _DB()
    db.seed("products", _load_products())

    discover_sku_lines_from_products(db, min_doc_freq=2, max_share=0.5)

    by_cat: dict[str, set[str]] = {}
    for r in db.rows("sku_lines"):
        by_cat.setdefault(r["category"], set()).add(r["canonical"])

    # "ddr5" appears in EVERY ram product (high share) — should NOT be a
    # gpu sku line. And we explicitly skip digit-bearing tokens, so ddr5
    # itself is excluded too.
    assert not any("ddr5" in s for s in by_cat.get("gpu", set()))


# ---------- auto_map_canonical_categories ------------------------------------


def test_auto_map_canonical_categories_handles_korean_labels() -> None:
    db = _DB()
    db.seed(
        "danawa_categories",
        [
            {"cate_id": "112747", "name_ko": "CPU 프로세서", "canonical": None},
            {"cate_id": "112753", "name_ko": "그래픽카드", "canonical": None},
            {"cate_id": "112752", "name_ko": "메모리/RAM", "canonical": None},
            {"cate_id": "112760", "name_ko": "메인보드", "canonical": None},
            {"cate_id": "112778", "name_ko": "CPU 공랭쿨러", "canonical": None},
            {"cate_id": "112763", "name_ko": "SSD", "canonical": None},
            {"cate_id": "112765", "name_ko": "PC케이스", "canonical": None},
            {"cate_id": "112777", "name_ko": "파워서플라이", "canonical": None},
            {"cate_id": "112757", "name_ko": "모니터", "canonical": None},
            {"cate_id": "999999", "name_ko": "키보드", "canonical": None},
        ],
    )

    summary = auto_map_canonical_categories(db)

    assert summary["mapped"] == 9  # everything except 키보드
    by_id = {r["cate_id"]: r["canonical"] for r in db.rows("danawa_categories")}
    assert by_id["112747"] == "cpu"
    assert by_id["112753"] == "gpu"
    assert by_id["112752"] == "ram"
    assert by_id["112760"] == "mainboard"
    # cooler keyword must beat "CPU" prefix.
    assert by_id["112778"] == "cooler"
    assert by_id["112763"] == "ssd"
    assert by_id["112765"] == "case"
    assert by_id["112777"] == "psu"
    assert by_id["112757"] == "monitor"
    assert by_id["999999"] is None
