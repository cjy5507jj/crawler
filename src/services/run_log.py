"""Operational log for run_all.py — records each pipeline run to
`crawl_runs` for post-hoc trend analysis (matching counts, failures)."""

from __future__ import annotations

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
