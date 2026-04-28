"""Price-alert watchlist evaluation against product_market_stats.

A watchlist row triggers when the latest used_median crosses the target_price
in the configured direction (below|above), subject to a 24h cool-down.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Protocol


COOLDOWN_HOURS = 24


class _DBLike(Protocol):
    def table(self, name: str): ...


@dataclass
class WatchlistTrigger:
    watchlist_id: str
    user_id: str
    product_id: str
    product_name: str | None
    direction: str
    target_price: int
    used_median: int


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _within_cooldown(last_alerted_at: str | None, *, now: datetime, cooldown_hours: int) -> bool:
    last = _parse_iso(last_alerted_at)
    if last is None:
        return False
    return (now - last) < timedelta(hours=cooldown_hours)


def _is_triggered(*, direction: str, used_median: int | None, target_price: int) -> bool:
    if used_median is None:
        return False
    if direction == "below":
        return used_median <= target_price
    if direction == "above":
        return used_median >= target_price
    return False


def _fetch_active_watchlists(db: _DBLike) -> list[dict]:
    return (
        db.table("watchlists")
        .select("id,user_id,product_id,target_price,direction,last_alerted_at")
        .eq("active", True)
        .execute()
        .data
        or []
    )


def _fetch_used_medians(db: _DBLike, product_ids: Iterable[str]) -> dict[str, int]:
    ids = list({pid for pid in product_ids if pid})
    if not ids:
        return {}
    rows = (
        db.table("product_market_stats")
        .select("product_id,used_median")
        .in_("product_id", ids)
        .execute()
        .data
        or []
    )
    out: dict[str, int] = {}
    for r in rows:
        med = r.get("used_median")
        if med is not None:
            out[r["product_id"]] = int(med)
    return out


def _fetch_product_names(db: _DBLike, product_ids: Iterable[str]) -> dict[str, str]:
    ids = list({pid for pid in product_ids if pid})
    if not ids:
        return {}
    rows = (
        db.table("products")
        .select("id,name")
        .in_("id", ids)
        .execute()
        .data
        or []
    )
    return {r["id"]: r.get("name") or "" for r in rows}


def check_watchlists(
    db: _DBLike,
    *,
    now: datetime | None = None,
    cooldown_hours: int = COOLDOWN_HOURS,
) -> list[WatchlistTrigger]:
    """Return list of watchlist rows that should fire an alert right now.

    A row fires when:
      - active = true
      - last_alerted_at is older than cooldown_hours (or null)
      - used_median crosses target_price in the requested direction
    """
    now = now or datetime.now(timezone.utc)
    rows = _fetch_active_watchlists(db)
    if not rows:
        return []

    pids = [r["product_id"] for r in rows if r.get("product_id")]
    medians = _fetch_used_medians(db, pids)
    names = _fetch_product_names(db, pids)

    triggers: list[WatchlistTrigger] = []
    for row in rows:
        if _within_cooldown(row.get("last_alerted_at"), now=now, cooldown_hours=cooldown_hours):
            continue
        pid = row.get("product_id")
        if not pid:
            continue
        used_median = medians.get(pid)
        direction = row.get("direction") or "below"
        target = int(row.get("target_price") or 0)
        if not _is_triggered(direction=direction, used_median=used_median, target_price=target):
            continue
        triggers.append(
            WatchlistTrigger(
                watchlist_id=row["id"],
                user_id=row["user_id"],
                product_id=pid,
                product_name=names.get(pid),
                direction=direction,
                target_price=target,
                used_median=used_median,  # type: ignore[arg-type]
            )
        )
    return triggers


def mark_alerted(db: _DBLike, watchlist_id: str, *, now: datetime | None = None) -> None:
    ts = (now or datetime.now(timezone.utc)).isoformat()
    db.table("watchlists").update({"last_alerted_at": ts}).eq("id", watchlist_id).execute()


def format_message(trigger: WatchlistTrigger) -> str:
    name = trigger.product_name or trigger.product_id
    arrow = "≤" if trigger.direction == "below" else "≥"
    return (
        f"💰 [{trigger.user_id}] {name} {arrow} {trigger.target_price:,} 원 "
        f"(현재 시세 {trigger.used_median:,} 원)"
    )
