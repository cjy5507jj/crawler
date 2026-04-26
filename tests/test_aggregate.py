from src.services.aggregate import (
    MarketStats,
    _Snapshot,
    _trimmed_mean,
    compute_stats,
)


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
