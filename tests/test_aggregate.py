from datetime import datetime, timedelta, timezone

from src.services.aggregate import (
    MarketStats,
    _Snapshot,
    _fetch_all_used_snapshots_grouped,
    _trimmed_mean,
    compute_stats,
    compute_trend,
)


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, rows):
        self._rows = rows
        self._eqs = []
        self._gtes = []
        self._in = None
        self._range = None
        self._order = None

    def select(self, _cols):
        return self

    def eq(self, col, val):
        self._eqs.append((col, val))
        return self

    def gte(self, col, val):
        self._gtes.append((col, val))
        return self

    def in_(self, col, values):
        self._in = (col, set(values))
        return self

    def order(self, col, desc=False):
        self._order = (col, desc)
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def execute(self):
        rows = list(self._rows)
        for col, val in self._eqs:
            rows = [r for r in rows if r.get(col) == val]
        for col, val in self._gtes:
            rows = [r for r in rows if r.get(col) >= val]
        if self._in is not None:
            col, values = self._in
            rows = [r for r in rows if r.get(col) in values]
        if self._order is not None:
            col, desc = self._order
            rows.sort(key=lambda r: r.get(col), reverse=desc)
        if self._range is not None:
            start, end = self._range
            rows = rows[start : end + 1]
        return _Result(rows)


class _DB:
    def __init__(self, rows):
        self._rows = rows

    def table(self, name):
        assert name == "price_snapshots"
        return _Query(self._rows)


def test_trimmed_mean_short_sample_returns_simple_mean() -> None:
    # Below the trim threshold, no trimming applied.
    assert _trimmed_mean([100, 200, 300]) == 200.0


def test_trimmed_mean_drops_outliers_for_large_sample() -> None:
    prices = [100, 100, 100, 100, 100, 100, 100, 100, 100, 1_000_000]
    # Without trimming, mean is ~100090. With 10% trim of 10 items (k=1), drop top+bottom.
    result = _trimmed_mean(prices)
    assert result == 100.0  # all remaining values are 100


def test_trimmed_mean_handles_all_same_price() -> None:
    assert _trimmed_mean([500, 500, 500, 500, 500, 500]) == 500.0


def test_compute_stats_no_snapshots() -> None:
    stats = compute_stats(
        product_id="p-1",
        category="cpu",
        used_snapshots=[],
        new_price=300_000,
        window_days=30,
    )
    assert stats.used_count == 0
    assert stats.used_min is None
    assert stats.used_median is None
    assert stats.used_to_new_ratio is None
    assert stats.new_price == 300_000


def test_compute_stats_single_snapshot() -> None:
    stats = compute_stats(
        product_id="p-1",
        category="gpu",
        used_snapshots=[_Snapshot(price=900_000, snapshot_at="2026-04-26T10:00:00Z")],
        new_price=1_200_000,
        window_days=30,
    )
    assert stats.used_count == 1
    assert stats.used_min == stats.used_max == stats.used_median == 900_000
    assert stats.used_latest == 900_000
    assert stats.used_to_new_ratio == round(900_000 / 1_200_000, 4)


def test_compute_stats_typical_case_with_outlier() -> None:
    # 10 snapshots; one is wildly low (sale glitch — should be sanity-filtered).
    snaps = [
        _Snapshot(price=p, snapshot_at=f"2026-04-{20+i:02d}T00:00:00Z")
        for i, p in enumerate([900, 920, 930, 940, 950, 960, 970, 980, 990, 1])
    ]
    stats = compute_stats(
        product_id="p-1",
        category="gpu",
        used_snapshots=snaps,
        new_price=1500,
        window_days=30,
    )
    # Sanity filter drops 1, leaving 9 valid prices.
    assert stats.used_count == 9
    assert stats.used_min == 900
    assert stats.used_max == 990
    assert stats.used_mean is not None
    assert 900 <= stats.used_mean <= 985


def test_compute_stats_sanity_filter_drops_extreme_high() -> None:
    # Real prices around 100k, one obviously bogus 9_999_999.
    snaps = [
        _Snapshot(price=p, snapshot_at=f"2026-04-{20+i:02d}T00:00:00Z")
        for i, p in enumerate([95_000, 100_000, 105_000, 110_000, 9_999_999])
    ]
    stats = compute_stats(
        product_id="p-1",
        category="ram",
        used_snapshots=snaps,
        new_price=130_000,
        window_days=30,
    )
    assert stats.used_count == 4  # 9_999_999 dropped (median ≈ 102500)
    assert stats.used_max <= 110_000


def test_compute_stats_drops_implausible_low_used_price_when_new_price_is_normal() -> None:
    snaps = [
        _Snapshot(price=2_000, snapshot_at="2026-04-26T10:00:00Z"),
        _Snapshot(price=750_000, snapshot_at="2026-04-26T11:00:00Z"),
        _Snapshot(price=780_000, snapshot_at="2026-04-26T12:00:00Z"),
    ]
    stats = compute_stats(
        product_id="p-1",
        category="gpu",
        used_snapshots=snaps,
        new_price=900_000,
        window_days=30,
    )
    assert stats.used_count == 2
    assert stats.used_min == 750_000
    assert stats.used_median == 765_000


def test_compute_stats_drops_used_price_far_above_normal_new_price() -> None:
    snaps = [
        _Snapshot(price=750_000, snapshot_at="2026-04-26T10:00:00Z"),
        _Snapshot(price=8_200_000, snapshot_at="2026-04-26T11:00:00Z"),
    ]
    stats = compute_stats(
        product_id="p-1",
        category="mainboard",
        used_snapshots=snaps,
        new_price=900_000,
        window_days=30,
    )
    assert stats.used_count == 1
    assert stats.used_median == 750_000


def test_fetch_used_snapshots_uses_only_c2c_sources() -> None:
    db = _DB([
        {
            "product_id": "p-1",
            "market_type": "used",
            "source": "bunjang",
            "price": 100_000,
            "snapshot_at": "2026-04-26T10:00:00Z",
        },
        {
            "product_id": "p-1",
            "market_type": "used",
            "source": "joonggonara",
            "price": 110_000,
            "snapshot_at": "2026-04-26T11:00:00Z",
        },
        {
            "product_id": "p-1",
            "market_type": "used",
            "source": "naver_shop",
            "price": 999_000,
            "snapshot_at": "2026-04-26T12:00:00Z",
        },
        {
            "product_id": "p-1",
            "market_type": "new",
            "source": "danawa",
            "price": 120_000,
            "snapshot_at": "2026-04-26T13:00:00Z",
        },
    ])
    grouped = _fetch_all_used_snapshots_grouped(db, "2026-04-26T00:00:00Z")
    assert [s.price for s in grouped["p-1"]] == [110_000, 100_000]


def test_compute_stats_skips_zero_and_negative_prices() -> None:
    snaps = [
        _Snapshot(price=200_000, snapshot_at="2026-04-26T10:00:00Z"),
        _Snapshot(price=0, snapshot_at="2026-04-26T11:00:00Z"),
        _Snapshot(price=-1, snapshot_at="2026-04-26T12:00:00Z"),
    ]
    stats = compute_stats(
        product_id="p-1",
        category="cpu",
        used_snapshots=snaps,
        new_price=300_000,
        window_days=30,
    )
    assert stats.used_count == 1
    assert stats.used_min == 200_000


def test_compute_stats_no_new_price_returns_no_ratio() -> None:
    stats = compute_stats(
        product_id="p-1",
        category="ram",
        used_snapshots=[_Snapshot(price=50_000, snapshot_at="2026-04-26T10:00:00Z")],
        new_price=None,
        window_days=30,
    )
    assert stats.used_median == 50_000
    assert stats.used_to_new_ratio is None


def test_new_price_floor_clamps_outlier() -> None:
    """A 4,500원 RAM new price is below the floor — drop it from the ratio
    but keep all used-side stats."""
    snaps = [
        _Snapshot(price=p, snapshot_at=f"2026-04-{20+i:02d}T00:00:00Z")
        for i, p in enumerate([40_000, 45_000, 50_000])
    ]
    stats = compute_stats(
        product_id="p-1",
        category="ram",
        used_snapshots=snaps,
        new_price=4_500,  # below the 10_000 RAM floor
        window_days=30,
    )
    assert stats.new_price is None
    assert stats.used_to_new_ratio is None
    # Used-side stats unaffected by the floor.
    assert stats.used_count == 3
    assert stats.used_median == 45_000
    assert stats.used_min == 40_000
    assert stats.used_max == 50_000


def test_new_price_floor_passes_normal_value() -> None:
    """A 50,000원 RAM new price is well above the floor — ratio computed normally."""
    snaps = [
        _Snapshot(price=p, snapshot_at=f"2026-04-{20+i:02d}T00:00:00Z")
        for i, p in enumerate([40_000, 45_000, 50_000])
    ]
    stats = compute_stats(
        product_id="p-1",
        category="ram",
        used_snapshots=snaps,
        new_price=50_000,
        window_days=30,
    )
    assert stats.new_price == 50_000
    assert stats.used_to_new_ratio == round(45_000 / 50_000, 4)


# ---------------------------------------------------------------------------
# Trend computation (P3.11)
# ---------------------------------------------------------------------------


_NOW = datetime(2026, 4, 26, 12, 0, 0, tzinfo=timezone.utc)


def _hist_row(days_ago: float, used_median: int | None) -> dict:
    captured = _NOW - timedelta(days=days_ago)
    return {
        "captured_at": captured.isoformat(),
        "used_median": used_median,
    }


def test_compute_trend_no_history() -> None:
    out = compute_trend([], window_days=7, now=_NOW)
    assert out == {"trend_pct": None, "direction": None}


def test_compute_trend_no_baseline_in_window() -> None:
    # Only recent rows; nothing near (now - 7d).
    rows = [_hist_row(0, 100_000), _hist_row(1, 99_500)]
    out = compute_trend(rows, window_days=7, now=_NOW)
    assert out == {"trend_pct": None, "direction": None}


def test_compute_trend_up_5pct() -> None:
    rows = [_hist_row(0, 105_000), _hist_row(7, 100_000)]
    out = compute_trend(rows, window_days=7, now=_NOW)
    assert out == {"trend_pct": 5.0, "direction": "up"}


def test_compute_trend_down_10pct() -> None:
    rows = [_hist_row(0, 90_000), _hist_row(7, 100_000)]
    out = compute_trend(rows, window_days=7, now=_NOW)
    assert out == {"trend_pct": -10.0, "direction": "down"}


def test_compute_trend_flat_within_threshold() -> None:
    rows = [_hist_row(0, 101_000), _hist_row(7, 100_000)]
    out = compute_trend(rows, window_days=7, now=_NOW)
    assert out["trend_pct"] == 1.0
    assert out["direction"] == "flat"


def test_compute_trend_zero_baseline_returns_none() -> None:
    rows = [_hist_row(0, 50_000), _hist_row(7, 0)]
    out = compute_trend(rows, window_days=7, now=_NOW)
    assert out == {"trend_pct": None, "direction": None}


def test_compute_trend_zero_current_returns_none() -> None:
    rows = [_hist_row(0, 0), _hist_row(7, 100_000)]
    out = compute_trend(rows, window_days=7, now=_NOW)
    assert out == {"trend_pct": None, "direction": None}


def test_compute_trend_28d_window() -> None:
    # 28d window: pick the row near 28 days ago, ignore 7-day-old rows.
    rows = [
        _hist_row(0, 120_000),
        _hist_row(7, 110_000),
        _hist_row(28, 100_000),
    ]
    out = compute_trend(rows, window_days=28, now=_NOW)
    assert out == {"trend_pct": 20.0, "direction": "up"}
