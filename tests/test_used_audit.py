from src.services.used_audit import duplicate_like_snapshot_stats


def test_duplicate_like_snapshot_stats_counts_repeated_product_source_price_day() -> None:
    rows = [
        {
            "product_id": "p1",
            "source": "bunjang",
            "market_type": "used",
            "price": 100,
            "snapshot_at": "2026-05-06T01:00:00+00:00",
        },
        {
            "product_id": "p1",
            "source": "bunjang",
            "market_type": "used",
            "price": 100,
            "snapshot_at": "2026-05-06T08:00:00+00:00",
        },
        {
            "product_id": "p1",
            "source": "bunjang",
            "market_type": "used",
            "price": 120,
            "snapshot_at": "2026-05-06T09:00:00+00:00",
        },
        {
            "product_id": "p1",
            "source": "danawa",
            "market_type": "new",
            "price": 200,
            "snapshot_at": "2026-05-06T10:00:00+00:00",
        },
    ]

    assert duplicate_like_snapshot_stats(rows) == {
        "keys": 2,
        "repeated_keys": 1,
        "extra_rows": 1,
        "max_repeat": 2,
    }


def test_duplicate_like_snapshot_stats_treats_dates_independently() -> None:
    rows = [
        {
            "product_id": "p1",
            "source": "joonggonara",
            "market_type": "used",
            "price": 100,
            "snapshot_at": "2026-05-06T23:50:00+00:00",
        },
        {
            "product_id": "p1",
            "source": "joonggonara",
            "market_type": "used",
            "price": 100,
            "snapshot_at": "2026-05-07T00:10:00+00:00",
        },
    ]

    assert duplicate_like_snapshot_stats(rows)["extra_rows"] == 0
