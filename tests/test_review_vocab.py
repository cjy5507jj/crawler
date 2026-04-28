"""Tests for scripts/review_vocab.py — promotion + skip + delete helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


# review_vocab.py lives under scripts/ (no package init). Load it as a module.
_ROOT = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "review_vocab", _ROOT / "scripts" / "review_vocab.py"
)
review_vocab = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(review_vocab)  # type: ignore[union-attr]


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, table: "_Table"):
        self.table = table
        self._eqs: list[tuple[str, object]] = []
        self._update: dict | None = None
        self._insert: dict | None = None
        self._delete = False
        self._limit: int | None = None
        self._order: tuple[str, bool] | None = None
        self._ilike: tuple[str, str] | None = None

    def select(self, *_cols):
        return self

    def eq(self, col, val):
        self._eqs.append((col, val))
        return self

    def order(self, col, desc=False):
        self._order = (col, desc)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def ilike(self, col, pattern):
        self._ilike = (col, pattern.strip("%").lower())
        return self

    def update(self, payload):
        self._update = payload
        return self

    def insert(self, payload):
        self._insert = payload
        return self

    def delete(self):
        self._delete = True
        return self

    def _matches(self, row: dict) -> bool:
        for col, val in self._eqs:
            if row.get(col) != val:
                return False
        if self._ilike is not None:
            col, needle = self._ilike
            if needle not in str(row.get(col, "")).lower():
                return False
        return True

    def execute(self):
        if self._insert is not None:
            row = dict(self._insert)
            row.setdefault("id", len(self.table.rows) + 1)
            self.table.rows.append(row)
            return _Result([row])
        if self._update is not None:
            for r in self.table.rows:
                if self._matches(r):
                    r.update(self._update)
            return _Result([])
        if self._delete:
            kept = [r for r in self.table.rows if not self._matches(r)]
            self.table.rows[:] = kept
            return _Result([])
        rows = [dict(r) for r in self.table.rows if self._matches(r)]
        if self._order is not None:
            col, desc = self._order
            rows.sort(key=lambda r: r.get(col, 0), reverse=desc)
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


# --- _promote_to_brand ------------------------------------------------------


def test_promote_to_brand_inserts_new() -> None:
    db = _DB()
    db.seed(
        "unknown_vocab",
        [
            {"token": "hyperx", "category": "ram", "seen_count": 7, "reviewed": False},
            {"token": "hyperx", "category": "ssd", "seen_count": 2, "reviewed": False},
        ],
    )

    result = review_vocab._promote_to_brand(db, "HyperX")

    brands = db.rows("brands")
    assert result["action"] == "inserted"
    assert result["canonical"] == "hyperx"
    assert len(brands) == 1
    assert brands[0]["canonical"] == "hyperx"
    assert brands[0]["aliases"] == ["hyperx"]
    assert brands[0]["source"] == "manual_review"
    # Both unknown_vocab rows for the token must be marked reviewed.
    for r in db.rows("unknown_vocab"):
        assert r["reviewed"] is True


def test_promote_to_brand_merges_aliases_when_existing() -> None:
    db = _DB()
    db.seed(
        "brands",
        [{"id": 1, "canonical": "asus", "aliases": ["asus", "에이수스"]}],
    )
    db.seed(
        "unknown_vocab",
        [{"token": "asus", "category": "gpu", "seen_count": 3, "reviewed": False}],
    )

    review_vocab._promote_to_brand(db, "asus")

    assert len(db.rows("brands")) == 1
    aliases = db.rows("brands")[0]["aliases"]
    assert "asus" in aliases
    assert "에이수스" in aliases
    assert db.rows("unknown_vocab")[0]["reviewed"] is True


# --- _promote_to_sku_line ---------------------------------------------------


def test_promote_to_sku_line_inserts_and_marks_reviewed() -> None:
    db = _DB()
    db.seed(
        "unknown_vocab",
        [
            {"token": "shadow", "category": "gpu", "seen_count": 8, "reviewed": False},
            {"token": "shadow", "category": "ram", "seen_count": 1, "reviewed": False},
        ],
    )

    result = review_vocab._promote_to_sku_line(db, "shadow", "gpu")

    sku_lines = db.rows("sku_lines")
    assert result["action"] == "inserted"
    assert len(sku_lines) == 1
    assert sku_lines[0]["canonical"] == "shadow"
    assert sku_lines[0]["category"] == "gpu"
    by_cat = {r["category"]: r for r in db.rows("unknown_vocab")}
    assert by_cat["gpu"]["reviewed"] is True
    # The ram row is unrelated and remains unreviewed.
    assert by_cat["ram"]["reviewed"] is False


def test_promote_to_sku_line_noop_when_existing() -> None:
    db = _DB()
    db.seed(
        "sku_lines",
        [{"id": 1, "canonical": "ventus", "category": "gpu"}],
    )
    db.seed(
        "unknown_vocab",
        [{"token": "ventus", "category": "gpu", "seen_count": 5, "reviewed": False}],
    )

    result = review_vocab._promote_to_sku_line(db, "ventus", "gpu")

    assert result["action"] == "exists"
    assert len(db.rows("sku_lines")) == 1
    assert db.rows("unknown_vocab")[0]["reviewed"] is True


# --- _skip_token ------------------------------------------------------------


def test_skip_token_marks_reviewed_only_for_category() -> None:
    db = _DB()
    db.seed(
        "unknown_vocab",
        [
            {"token": "x", "category": "gpu", "seen_count": 1, "reviewed": False},
            {"token": "x", "category": "ram", "seen_count": 1, "reviewed": False},
        ],
    )

    review_vocab._skip_token(db, "x", "gpu")

    by_cat = {r["category"]: r for r in db.rows("unknown_vocab")}
    assert by_cat["gpu"]["reviewed"] is True
    assert by_cat["ram"]["reviewed"] is False


# --- _delete_token ----------------------------------------------------------


def test_delete_token_removes_only_target_row() -> None:
    db = _DB()
    db.seed(
        "unknown_vocab",
        [
            {"token": "junk", "category": "gpu", "reviewed": False},
            {"token": "junk", "category": "ram", "reviewed": False},
        ],
    )

    review_vocab._delete_token(db, "junk", "gpu")

    rows = db.rows("unknown_vocab")
    assert len(rows) == 1
    assert rows[0]["category"] == "ram"


# --- _fetch_top_unknown -----------------------------------------------------


def test_fetch_top_unknown_orders_by_seen_count_desc() -> None:
    db = _DB()
    db.seed(
        "unknown_vocab",
        [
            {"token": "a", "category": "gpu", "seen_count": 1, "reviewed": False},
            {"token": "b", "category": "gpu", "seen_count": 9, "reviewed": False},
            {"token": "c", "category": "gpu", "seen_count": 5, "reviewed": True},
            {"token": "d", "category": "ram", "seen_count": 7, "reviewed": False},
        ],
    )

    rows = review_vocab._fetch_top_unknown(db, top=3)
    tokens = [r["token"] for r in rows]
    assert tokens == ["b", "d", "a"]  # reviewed=False only, desc by seen_count


def test_fetch_top_unknown_filters_by_category() -> None:
    db = _DB()
    db.seed(
        "unknown_vocab",
        [
            {"token": "a", "category": "gpu", "seen_count": 9, "reviewed": False},
            {"token": "b", "category": "ram", "seen_count": 8, "reviewed": False},
        ],
    )

    rows = review_vocab._fetch_top_unknown(db, top=10, category="ram")
    assert [r["token"] for r in rows] == ["b"]


def test_prompt_quits_on_eof(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_text):
        raise EOFError

    monkeypatch.setattr("builtins.input", boom)
    assert review_vocab._prompt("> ", "bskdq") == "q"
