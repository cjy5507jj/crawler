"""Tests for src.services.watchlist — trigger evaluation + cool-down."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from src.services.watchlist import check_watchlists, mark_alerted


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, table: "_Table"):
        self.table = table
        self._select_cols: tuple[str, ...] = ()
        self._eqs: list[tuple[str, object]] = []
        self._in: tuple[str, list] | None = None
        self._update: dict | None = None
        self._insert: dict | None = None

    def select(self, *cols):
        self._select_cols = cols
        return self

    def eq(self, col, val):
        self._eqs.append((col, val))
        return self

    def in_(self, col, values):
        self._in = (col, list(values))
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
        if self._in is not None:
            col, values = self._in
            if row.get(col) not in values:
                return False
        return True

    def execute(self):
        if self._insert is not None:
            row = dict(self._insert)
            row.setdefault("id", str(uuid.uuid4()))
            self.table.rows.append(row)
            return _Result([row])
        if self._update is not None:
            for r in self.table.rows:
                if self._matches(r):
                    r.update(self._update)
            return _Result([])
        return _Result([dict(r) for r in self.table.rows if self._matches(r)])


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
        return self._tables[name].rows

    def seed(self, name, rows):
        self.table(name)
        self._tables[name].rows.extend(rows)


def _make_db_with_watchlist(*, last_alerted_at=None, used_median=110_000, direction="below", target=120_000, active=True, product_name="RTX 5070"):
    db = _DB()
    pid = "p-1"
    db.seed(
        "watchlists",
        [
            {
                "id": "w-1",
                "user_id": "joe",
                "product_id": pid,
                "target_price": target,
                "direction": direction,
                "active": active,
                "last_alerted_at": last_alerted_at,
            }
        ],
    )
    db.seed("product_market_stats", [{"product_id": pid, "used_median": used_median}])
    db.seed("products", [{"id": pid, "name": product_name}])
    return db


def test_check_watchlists_triggers_below_threshold():
    db = _make_db_with_watchlist(used_median=100_000, direction="below", target=120_000)
    triggers = check_watchlists(db)
    assert len(triggers) == 1
    t = triggers[0]
    assert t.user_id == "joe"
    assert t.product_id == "p-1"
    assert t.target_price == 120_000
    assert t.used_median == 100_000
    assert t.product_name == "RTX 5070"


def test_check_watchlists_does_not_trigger_when_above_target():
    db = _make_db_with_watchlist(used_median=130_000, direction="below", target=120_000)
    assert check_watchlists(db) == []


def test_check_watchlists_above_direction():
    db = _make_db_with_watchlist(used_median=200_000, direction="above", target=180_000)
    triggers = check_watchlists(db)
    assert len(triggers) == 1
    assert triggers[0].direction == "above"


def test_check_watchlists_skips_within_cooldown():
    now = datetime(2026, 4, 26, tzinfo=timezone.utc)
    recently = (now - timedelta(hours=2)).isoformat()
    db = _make_db_with_watchlist(
        used_median=100_000, direction="below", target=120_000, last_alerted_at=recently
    )
    assert check_watchlists(db, now=now) == []


def test_check_watchlists_fires_after_cooldown_expires():
    now = datetime(2026, 4, 26, tzinfo=timezone.utc)
    long_ago = (now - timedelta(hours=48)).isoformat()
    db = _make_db_with_watchlist(
        used_median=100_000, direction="below", target=120_000, last_alerted_at=long_ago
    )
    assert len(check_watchlists(db, now=now)) == 1


def test_check_watchlists_skips_inactive():
    db = _make_db_with_watchlist(used_median=100_000, target=120_000, active=False)
    assert check_watchlists(db) == []


def test_check_watchlists_skips_when_no_used_median():
    db = _make_db_with_watchlist(used_median=None, direction="below", target=120_000)
    assert check_watchlists(db) == []


def test_mark_alerted_writes_timestamp():
    now = datetime(2026, 4, 26, 9, 0, tzinfo=timezone.utc)
    db = _make_db_with_watchlist()
    mark_alerted(db, "w-1", now=now)
    assert db.rows("watchlists")[0]["last_alerted_at"] == now.isoformat()
