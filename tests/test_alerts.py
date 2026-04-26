"""Tests for src.services.alerts — anomaly detection + notify dispatch."""

from __future__ import annotations

import pytest

from src.services import alerts
from src.services.alerts import detect_anomalies, notify


def test_detect_anomalies_no_baseline() -> None:
    assert detect_anomalies(None, {"metrics": {"stats_total": 100}}) == []


def test_detect_anomalies_no_current_metrics() -> None:
    assert detect_anomalies({"metrics": {"stats_total": 100}}, {}) == []


def test_detect_anomalies_total_drop_50pct() -> None:
    prev = {"metrics": {"stats_total": 1000, "with_used": 500}}
    curr = {"metrics": {"stats_total": 400, "with_used": 300}}
    out = detect_anomalies(prev, curr)
    assert any("products dropped" in s for s in out)


def test_detect_anomalies_zero_matches_after_nonzero() -> None:
    prev = {"metrics": {"stats_total": 1000, "with_used": 500}}
    curr = {"metrics": {"stats_total": 1000, "with_used": 0}}
    out = detect_anomalies(prev, curr)
    assert any("ZERO" in s for s in out)


def test_detect_anomalies_used_drop_50pct() -> None:
    prev = {"metrics": {"stats_total": 1000, "with_used": 500}}
    curr = {"metrics": {"stats_total": 1000, "with_used": 100}}
    out = detect_anomalies(prev, curr)
    assert any("matched-with-used dropped by >50%" in s for s in out)


def test_detect_anomalies_no_drop() -> None:
    prev = {"metrics": {"stats_total": 1000, "with_used": 500}}
    curr = {"metrics": {"stats_total": 950, "with_used": 480}}
    assert detect_anomalies(prev, curr) == []


def test_notify_falls_back_to_stdout_when_no_webhook(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)

    notify("hello world", level="alert")

    out = capsys.readouterr().out
    assert "[alert alert]" in out
    assert "hello world" in out


def test_notify_uses_slack_webhook_when_set(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example/slack")
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)

    calls: list[tuple[str, dict]] = []

    class _Resp:
        def raise_for_status(self) -> None:
            return None

    def fake_post(url, json=None, timeout=None):
        calls.append((url, json))
        return _Resp()

    monkeypatch.setattr(alerts.httpx, "post", fake_post)

    notify("hi", level="info")

    assert calls and calls[0][0] == "https://hooks.example/slack"
    assert "text" in calls[0][1]
    assert capsys.readouterr().out == ""


def test_notify_swallows_webhook_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example/slack")
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)

    def fake_post(*_a, **_kw):
        raise RuntimeError("network down")

    monkeypatch.setattr(alerts.httpx, "post", fake_post)

    notify("oops", level="alert")

    captured = capsys.readouterr()
    assert "webhook failed" in captured.err
    assert "[alert alert]" in captured.out
