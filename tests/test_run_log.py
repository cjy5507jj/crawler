from datetime import datetime, timedelta, timezone
import uuid

from src.services.run_log import finish_run, mark_stale_running_runs, start_run, update_summary


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, table):
        self._table = table
        self._eqs = []
        self._lt = None
        self._update = None
        self._insert = None

    def insert(self, payload):
        self._insert = payload
        return self

    def select(self, _cols):
        return self

    def eq(self, col, val):
        self._eqs.append((col, val))
        return self

    def lt(self, col, val):
        self._lt = (col, val)
        return self

    def update(self, payload):
        self._update = payload
        return self

    def _matches(self, row):
        for col, val in self._eqs:
            if row.get(col) != val:
                return False
        if self._lt is not None:
            col, val = self._lt
            if row.get(col) >= val:
                return False
        return True

    def execute(self):
        if self._insert is not None:
            row = dict(self._insert)
            row.setdefault("id", str(uuid.uuid4()))
            self._table.rows.append(row)
            return _Result([row])
        matches = [r for r in self._table.rows if self._matches(r)]
        if self._update is not None:
            for row in matches:
                row.update(self._update)
        return _Result([dict(r) for r in matches])


class _Table:
    def __init__(self, rows):
        self.rows = rows or []


class _DB:
    def __init__(self, rows=None):
        self._table = _Table(rows)

    def table(self, name):
        assert name == "crawl_runs"
        return _Query(self._table)

    @property
    def rows(self):
        return self._table.rows


def test_start_run_inserts_row() -> None:
    db = _DB()
    run_id = start_run(db, trigger_source="launchd", args={"foo": "bar"})

    rows = db.rows
    assert len(rows) == 1
    assert rows[0]["id"] == run_id
    assert rows[0]["trigger_source"] == "launchd"
    assert rows[0]["args"] == {"foo": "bar"}
    assert rows[0]["status"] == "running"


def test_start_run_defaults_trigger_source_and_args() -> None:
    db = _DB()
    run_id = start_run(db)
    rows = db.rows
    assert rows[0]["id"] == run_id
    assert rows[0]["trigger_source"] == "manual"
    assert rows[0]["args"] == {}


def test_finish_run_marks_completed() -> None:
    db = _DB()
    run_id = start_run(db)

    finish_run(db, run_id, status="completed", summary={"phases": {"used": {}}})

    row = db.rows[0]
    assert row["status"] == "completed"
    assert row["finished_at"] == "now()"
    assert row["summary"] == {"phases": {"used": {}}}


def test_finish_run_records_error() -> None:
    db = _DB()
    run_id = start_run(db)

    finish_run(db, run_id, status="failed", error="boom")

    row = db.rows[0]
    assert row["status"] == "failed"
    assert row["error"] == "boom"


def test_update_summary_writes_payload() -> None:
    db = _DB()
    run_id = start_run(db)

    update_summary(db, run_id, {"metrics": {"stats_total": 42}})

    row = db.rows[0]
    assert row["summary"] == {"metrics": {"stats_total": 42}}


def test_mark_stale_running_runs_only_marks_old_running_rows() -> None:
    now = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    db = _DB([
        {
            "id": "old-running",
            "status": "running",
            "started_at": (now - timedelta(hours=7)).isoformat(),
        },
        {
            "id": "fresh-running",
            "status": "running",
            "started_at": (now - timedelta(hours=1)).isoformat(),
        },
        {
            "id": "old-completed",
            "status": "completed",
            "started_at": (now - timedelta(hours=8)).isoformat(),
        },
    ])

    count = mark_stale_running_runs(db, max_age_hours=6, now=now)

    assert count == 1
    by_id = {r["id"]: r for r in db.rows}
    assert by_id["old-running"]["status"] == "failed"
    assert by_id["old-running"]["finished_at"] == now.isoformat()
    assert "stale running run" in by_id["old-running"]["error"]
    assert by_id["fresh-running"]["status"] == "running"
    assert by_id["old-completed"]["status"] == "completed"
