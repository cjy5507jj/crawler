"""Tests for src.services.run_log — the crawl_runs operational log."""

from __future__ import annotations

import uuid

from src.services.run_log import finish_run, start_run, update_summary


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, table: "_Table"):
        self.table = table
        self._insert: dict | None = None
        self._update: dict | None = None
        self._eq: tuple[str, object] | None = None

    def insert(self, payload: dict):
        self._insert = payload
        return self

    def update(self, payload: dict):
        self._update = payload
        return self

    def eq(self, col, val):
        self._eq = (col, val)
        return self

    def execute(self):
        if self._insert is not None:
            row = dict(self._insert)
            row.setdefault("id", str(uuid.uuid4()))
            self.table.rows.append(row)
            return _Result([row])
        if self._update is not None and self._eq is not None:
            col, val = self._eq
            for r in self.table.rows:
                if r.get(col) == val:
                    r.update(self._update)
            return _Result([])
        return _Result(list(self.table.rows))


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


def test_start_run_inserts_row() -> None:
    db = _DB()
    run_id = start_run(db, trigger_source="launchd", args={"foo": "bar"})

    rows = db.rows("crawl_runs")
    assert len(rows) == 1
    assert rows[0]["id"] == run_id
    assert rows[0]["trigger_source"] == "launchd"
    assert rows[0]["args"] == {"foo": "bar"}
    assert rows[0]["status"] == "running"


def test_start_run_defaults_trigger_source_and_args() -> None:
    db = _DB()
    run_id = start_run(db)
    rows = db.rows("crawl_runs")
    assert rows[0]["id"] == run_id
    assert rows[0]["trigger_source"] == "manual"
    assert rows[0]["args"] == {}


def test_finish_run_marks_completed() -> None:
    db = _DB()
    run_id = start_run(db)

    finish_run(db, run_id, status="completed", summary={"phases": {"used": {}}})

    row = db.rows("crawl_runs")[0]
    assert row["status"] == "completed"
    assert row["finished_at"] == "now()"
    assert row["summary"] == {"phases": {"used": {}}}


def test_finish_run_records_error() -> None:
    db = _DB()
    run_id = start_run(db)

    finish_run(db, run_id, status="failed", error="boom")

    row = db.rows("crawl_runs")[0]
    assert row["status"] == "failed"
    assert row["error"] == "boom"


def test_update_summary_writes_payload() -> None:
    db = _DB()
    run_id = start_run(db)

    update_summary(db, run_id, {"metrics": {"stats_total": 42}})

    row = db.rows("crawl_runs")[0]
    assert row["summary"] == {"metrics": {"stats_total": 42}}
