from src.services.price_index import compute_price_index


def test_compute_price_index_combines_c2c_b2c_and_new_signals() -> None:
    out = compute_price_index(
        product_id="p-1",
        domain="pc_parts",
        category="gpu",
        canonical_key="pc_parts:gpu:msi:rtx5070",
        specs={"brand": "msi"},
        c2c_used_count=8,
        c2c_used_min=700_000,
        c2c_used_median=780_000,
        new_price=1_000_000,
        b2c_prices=[850_000, 830_000, 900_000],
    )

    assert out.product_id == "p-1"
    assert out.domain == "pc_parts"
    assert out.canonical_key == "pc_parts:gpu:msi:rtx5070"
    assert out.specs == {"brand": "msi"}
    assert out.c2c_used_median == 780_000
    assert out.c2c_used_min == 700_000
    assert out.b2c_min == 830_000
    assert out.reference_market_price is None
    assert out.reference_price_count == 0
    assert out.new_price == 1_000_000
    assert out.lowest_available_price == 700_000
    assert out.buy_offer_price == 624_000
    assert out.confidence_score == 0.8


def test_compute_price_index_uses_b2c_when_c2c_missing() -> None:
    out = compute_price_index(
        product_id="p-2",
        domain="pc_parts",
        category="ssd",
        canonical_key=None,
        specs={},
        c2c_used_count=0,
        c2c_used_min=None,
        c2c_used_median=None,
        new_price=120_000,
        b2c_prices=[80_000, 90_000],
    )

    assert out.lowest_available_price == 80_000
    assert out.buy_offer_price is None
    assert out.confidence_score == 0.25


def test_compute_price_index_uses_reference_price_as_offer_anchor_only() -> None:
    out = compute_price_index(
        product_id="p-phone",
        domain="phone",
        category="iphone",
        canonical_key="phone:apple:iphone-15-pro:256gb",
        specs={"model": "iphone 15 pro", "storage_gb": 256},
        c2c_used_count=0,
        c2c_used_min=None,
        c2c_used_median=None,
        new_price=None,
        b2c_prices=[],
        reference_prices=[754_000, 746_000],
    )

    assert out.reference_market_price == 750_000
    assert out.reference_price_count == 2
    assert out.lowest_available_price is None
    assert out.buy_offer_price == 562_500
    assert out.confidence_score == 0.2


def test_compute_price_index_filters_implausible_phone_reference_price() -> None:
    out = compute_price_index(
        product_id="p-phone",
        domain="phone",
        category="iphone",
        canonical_key="phone:apple:iphone-15-pro:256gb",
        specs={"model": "iphone 15 pro", "storage_gb": 256},
        c2c_used_count=0,
        c2c_used_min=None,
        c2c_used_median=None,
        new_price=None,
        b2c_prices=[],
        reference_prices=[1_000],
    )

    assert out.reference_market_price is None
    assert out.reference_price_count == 0
    assert out.buy_offer_price is None
    assert out.confidence_score == 0.0


def test_compute_price_index_ignores_b2c_far_below_c2c_median() -> None:
    out = compute_price_index(
        product_id="p-4",
        domain="pc_parts",
        category="ram",
        canonical_key=None,
        specs={},
        c2c_used_count=20,
        c2c_used_min=90_000,
        c2c_used_median=110_000,
        new_price=300_000,
        b2c_prices=[27_000, 95_000],
    )

    assert out.b2c_min == 95_000
    assert out.lowest_available_price == 90_000


def test_compute_price_index_returns_low_confidence_without_market_signals() -> None:
    out = compute_price_index(
        product_id="p-3",
        domain="pc_parts",
        category="case",
        canonical_key=None,
        specs={},
        c2c_used_count=0,
        c2c_used_min=None,
        c2c_used_median=None,
        new_price=None,
        b2c_prices=[],
    )

    assert out.lowest_available_price is None
    assert out.buy_offer_price is None
    assert out.confidence_score == 0.0
