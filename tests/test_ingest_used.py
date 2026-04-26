"""Exercise the used-listing ingest pipeline against an in-memory fake DB."""

from __future__ import annotations

from typing import Any

from src.adapters.base import SourceAdapter, UsedListing
from src.services.ingest import run_used


# --- Fake Supabase client ---------------------------------------------------

class _Builder:
    def __init__(self, table: "_Table"):
        self._t = table
        self._mode = ""
        self._payload: Any = None
        self._on_conflict: str | None = None
        self._eq: tuple[str, Any] | None = None
        self._range: tuple[int, int] | None = None
        self._select: str | None = None

    def upsert(self, payload, on_conflict=None):
        self._mode = "upsert"
        self._payload = payload
        self._on_conflict = on_conflict
        return self

    def insert(self, payload):
        self._mode = "insert"
        self._payload = payload
        return self

    def select(self, cols):
        self._mode = "select"
        self._select = cols
        return self

    def eq(self, col, val):
        self._eq = (col, val)
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def execute(self):
        if self._mode == "upsert":
            return self._t._upsert(self._payload, self._on_conflict)
        if self._mode == "insert":
            return self._t._insert(self._payload)
        if self._mode == "select":
            return self._t._select(self._eq, self._range)
        raise RuntimeError(f"unknown mode {self._mode}")


class _Result:
    def __init__(self, data):
        self.data = data


class _Table:
    def __init__(self, name: str, db: "FakeDB"):
        self.name = name
        self.db = db
        self.rows: list[dict] = []
        self._id_seq = 0

    def _next_id(self) -> str:
        self._id_seq += 1
        return f"{self.name}-{self._id_seq}"

    def _upsert(self, payload, on_conflict):
        keys = (on_conflict or "").split(",") if on_conflict else []
        if keys:
            for r in self.rows:
                if all(r.get(k.strip()) == payload.get(k.strip()) for k in keys):
                    r.update(payload)
                    return _Result([r])
        new = {**payload, "id": self._next_id()}
        self.rows.append(new)
        return _Result([new])

    def _insert(self, payload):
        new = {**payload, "id": self._next_id()}
        self.rows.append(new)
        return _Result([new])

    def _select(self, eq, rng):
        rows = self.rows
        if eq:
            col, val = eq
            rows = [r for r in rows if r.get(col) == val]
        if rng:
            s, e = rng
            rows = rows[s : e + 1]
        return _Result(rows)


class FakeDB:
    def __init__(self):
        self._tables: dict[str, _Table] = {}

    def table(self, name: str) -> _Builder:
        if name not in self._tables:
            self._tables[name] = _Table(name, self)
        return _Builder(self._tables[name])

    def rows(self, name: str) -> list[dict]:
        return self._tables.get(name, _Table(name, self)).rows


# --- Fake adapter -----------------------------------------------------------

class _StaticAdapter(SourceAdapter):
    source_name = "fake"

    def __init__(self, listings: list[UsedListing]):
        self._listings = listings

    def fetch_recent(self, *, pages=1, category=None) -> list[UsedListing]:
        return list(self._listings)

    def search(self, query, *, category=None) -> list[UsedListing]:
        return list(self._listings)


# --- Tests ------------------------------------------------------------------

def _seed_products(db: FakeDB) -> None:
    db.table("products").upsert(
        {
            "category": "cpu",
            "source": "danawa",
            "source_id": "P-5600X",
            "name": "AMD 라이젠5 5600X 정품",
            "brand": "amd",
            "model_name": "5600x",
            "normalized_name": "amd 라이젠5 5600x 정품",
            "url": "https://prod.danawa.com/info/?pcode=P-5600X",
        },
        on_conflict="source,source_id",
    ).execute()
    db.table("products").upsert(
        {
            "category": "cpu",
            "source": "danawa",
            "source_id": "P-7600X",
            "name": "AMD 라이젠5 7600X 정품",
            "brand": "amd",
            "model_name": "7600x",
            "normalized_name": "amd 라이젠5 7600x 정품",
            "url": "https://prod.danawa.com/info/?pcode=P-7600X",
        },
        on_conflict="source,source_id",
    ).execute()


def test_run_used_matches_and_writes_snapshots() -> None:
    db = FakeDB()
    _seed_products(db)

    adapter = _StaticAdapter([
        UsedListing(
            source="fake",
            listing_id="L1",
            title="AMD 라이젠5 5600X 미개봉",
            price=200_000,
            url="http://example/L1",
        ),
        UsedListing(
            source="fake",
            listing_id="L2",
            title="AMD 라이젠5 7600X 박스",
            price=320_000,
            url="http://example/L2",
        ),
        UsedListing(
            source="fake",
            listing_id="L3",
            title="자전거 팝니다",  # unmatched
            price=50_000,
        ),
        UsedListing(
            source="fake",
            listing_id="L4",
            title="RTX 4070 삽니다",  # excluded
        ),
    ])

    summary = run_used(db, adapter, category="cpu")

    assert summary["matched"] == 2
    assert summary["snapshots"] == 2
    assert summary["excluded"] == 1
    assert summary["unmatched"] == 1

    used_rows = db.rows("used_listings")
    assert len(used_rows) == 3  # L4 excluded entirely
    snapshots = db.rows("price_snapshots")
    assert len(snapshots) == 2
    assert all(s["market_type"] == "used" for s in snapshots)


def test_match_reasons_persisted_in_payload() -> None:
    """Matched listings persist MatchResult.reasons as a list[str] for observability."""
    db = FakeDB()
    _seed_products(db)

    adapter = _StaticAdapter([
        UsedListing(
            source="fake",
            listing_id="L1",
            title="AMD 라이젠5 5600X 미개봉",
            price=200_000,
            url="http://example/L1",
        ),
        UsedListing(
            source="fake",
            listing_id="L2",
            title="자전거 팝니다",  # unmatched — no candidate scored
        ),
    ])

    run_used(db, adapter, category="cpu")

    used_rows = db.rows("used_listings")
    by_id = {r["listing_id"]: r for r in used_rows}

    matched = by_id["L1"]
    assert matched["matched_product_id"] is not None
    assert isinstance(matched["match_reasons"], list)
    assert matched["match_reasons"], "matched listing should have at least one reason"
    assert all(isinstance(r, str) for r in matched["match_reasons"])
    # Brand match should always be in the reasons for this fixture.
    assert any(r.startswith("brand:") for r in matched["match_reasons"])

    # Unmatched listings still get a row; reasons may be a list (DQ reasons)
    # or None when no candidate was scored at all. Just assert the column is
    # present in the payload (key exists).
    unmatched = by_id["L2"]
    assert "match_reasons" in unmatched
