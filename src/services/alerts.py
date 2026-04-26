"""Lightweight alerting for pipeline anomalies. Slack/Discord webhook with
stdout fallback. Errors swallowed — alerting must not break the pipeline."""

from __future__ import annotations

import os
import sys

import httpx


def notify(message: str, *, level: str = "info") -> None:
    prefix = {"info": "ℹ️", "warn": "⚠️", "alert": "🚨"}.get(level, "")
    text = f"{prefix} {message}".strip()
    slack = os.environ.get("SLACK_WEBHOOK_URL")
    discord = os.environ.get("DISCORD_WEBHOOK_URL")
    try:
        if slack:
            httpx.post(slack, json={"text": text}, timeout=10).raise_for_status()
            return
        if discord:
            httpx.post(discord, json={"content": text}, timeout=10).raise_for_status()
            return
    except Exception as e:
        print(f"[alerts] webhook failed: {e}", file=sys.stderr)
    print(f"[alert {level}] {text}")


def detect_anomalies(prev_summary: dict | None, curr_summary: dict | None) -> list[str]:
    """Compare current run metrics vs previous run. Return list of anomaly strings.
    No previous run → empty list (baseline). Threshold: 50% drop or zero matches."""
    prev = (prev_summary or {}).get("metrics") or {}
    curr = (curr_summary or {}).get("metrics") or {}
    if not prev or not curr:
        return []
    anomalies: list[str] = []
    prev_total = prev.get("stats_total", 0)
    curr_total = curr.get("stats_total", 0)
    if prev_total and curr_total < prev_total * 0.5:
        anomalies.append(
            f"products dropped by >50%: {prev_total} → {curr_total}"
        )
    prev_used = prev.get("with_used", 0)
    curr_used = curr.get("with_used", 0)
    if prev_used and curr_used == 0:
        anomalies.append(f"matched-with-used dropped to ZERO (prev: {prev_used})")
    elif prev_used and curr_used < prev_used * 0.5:
        anomalies.append(
            f"matched-with-used dropped by >50%: {prev_used} → {curr_used}"
        )
    return anomalies
