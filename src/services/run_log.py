"""Operational log for run_all.py — records each pipeline run to
`crawl_runs` for post-hoc trend analysis (matching counts, failures)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Protocol


class _DBLike(Protocol):
    def table(self, name: str): ...


def start_run(
    db: _DBLike,
    *,
    trigger_source: str = "manual",
    args: dict[str, Any] | None = None,
) -> str:
    row = (
        db.table("crawl_runs")
        .insert(
            {
                "trigger_source": trigger_source,
                "args": args or {},
                "status": "running",
            }
        )
        .execute()
        .data
    )
    return row[0]["id"]


def mark_stale_running_runs(
    db: _DBLike,
    *,
    max_age_hours: int = 6,
    now: datetime | None = None,
) -> int:
    """Mark old `running` rows as failed before starting a new run.

    launchd/manual interruptions can leave `crawl_runs.status='running'` even
    when no crawler process is alive. Treat rows older than `max_age_hours` as
    stale so operational dashboards do not show phantom active jobs.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=max_age_hours)).isoformat()
    rows = (
        db.table("crawl_runs")
        .select("id")
        .eq("status", "running")
        .lt("started_at", cutoff)
        .execute()
        .data
    )
    if not rows:
        return 0

    payload = {
        "status": "failed",
        "finished_at": now.isoformat(),
        "error": f"stale running run auto-reconciled after {max_age_hours}h",
    }
    for row in rows:
        db.table("crawl_runs").update(payload).eq("id", row["id"]).execute()
    return len(rows)


def update_summary(db: _DBLike, run_id: str, summary: dict[str, Any]) -> None:
    db.table("crawl_runs").update({"summary": summary}).eq("id", run_id).execute()


def finish_run(
    db: _DBLike,
    run_id: str,
    *,
    status: str = "completed",
    error: str | None = None,
    summary: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "status": status,
        "finished_at": "now()",
    }
    if error is not None:
        payload["error"] = error
    if summary is not None:
        payload["summary"] = summary
    db.table("crawl_runs").update(payload).eq("id", run_id).execute()
