from pathlib import Path

import pytest

from src.adapters.naver_shop import (
    NaverShopAdapter,
    has_credentials,
    parse_response,
)

FIXTURE = Path(__file__).parent / "fixtures" / "naver_shop" / "sample_response.json"


def test_naver_shop_default_filters_to_used_only() -> None:
    listings = parse_response(FIXTURE.read_text())
    # 7 items in fixture, productType 2 = items 1, 3, 5, 6 + 7 (skipped: empty productId)
    # → 4 used items with valid productId
    assert len(listings) == 4
    for l in listings:
        assert l.source == "naver_shop"
        assert l.metadata["product_type"] == "2"


def test_naver_shop_strips_html_tags_in_title() -> None:
    listings = parse_response(FIXTURE.read_text())
    titles = [l.title for l in listings]
    # First used item: "<b>RTX 4070</b> SUPER 그래픽카드 중고"
    assert "RTX 4070 SUPER 그래픽카드 중고" in titles
    # No HTML tags survive
    assert all("<" not in t and ">" not in t for t in titles)


def test_naver_shop_listing_id_combines_product_and_mall() -> None:
    listings = parse_response(FIXTURE.read_text())
    ids = {l.listing_id for l in listings}
    # productId 12345678 + mall "스마트스토어 PC파츠"
    assert "12345678:스마트스토어 PC파츠" in ids
    # productId 55555555 + empty mall → just productId
    assert "55555555" in ids


def test_naver_shop_lprice_extracted_as_int() -> None:
    listings = parse_response(FIXTURE.read_text())
    by_id = {l.listing_id: l for l in listings}
    assert by_id["12345678:스마트스토어 PC파츠"].price == 780000
    assert by_id["33333333:중고나라샵"].price == 750000
    assert by_id["66666666:리퍼브왕"].price == 799000


def test_naver_shop_metadata_carries_category_breadcrumbs() -> None:
    listings = parse_response(FIXTURE.read_text())
    by_id = {l.listing_id: l for l in listings}
    meta = by_id["12345678:스마트스토어 PC파츠"].metadata
    assert meta["category1"] == "디지털/가전"
    assert meta["category2"] == "PC부품"
    assert meta["category3"] == "그래픽카드"
    assert meta["brand"] == "ASUS"
    assert meta["mall_name"] == "스마트스토어 PC파츠"


def test_naver_shop_widen_to_general_includes_productType_1() -> None:
    listings = parse_response(FIXTURE.read_text(), accept_types={"1", "2"})
    # Adds the productType=1 item (22222222) → 5 total (excludes empty-id row)
    types = {l.metadata.get("product_type") for l in listings}
    assert types == {"1", "2"}
    assert len(listings) == 5


def test_naver_shop_skips_empty_product_id() -> None:
    listings = parse_response(FIXTURE.read_text(), accept_types={"1", "2", "5"})
    ids = [l.listing_id for l in listings]
    # Last item has empty productId → must be skipped regardless of accept_types
    assert all(i for i in ids)
    # productType=5 with valid productId IS included when accept_types allows it
    assert any(":광고없는샵" in i for i in ids)


def test_naver_shop_url_uses_link_field() -> None:
    listings = parse_response(FIXTURE.read_text())
    by_id = {l.listing_id: l for l in listings}
    assert by_id["12345678:스마트스토어 PC파츠"].url == (
        "https://smartstore.naver.com/main/products/12345678"
    )


def test_has_credentials_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NAVER_CLIENT_ID", raising=False)
    monkeypatch.delenv("NAVER_CLIENT_SECRET", raising=False)
    assert has_credentials() is False
    monkeypatch.setenv("NAVER_CLIENT_ID", "x")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "y")
    assert has_credentials() is True


def test_naver_shop_search_skips_when_credentials_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NAVER_CLIENT_ID", raising=False)
    monkeypatch.delenv("NAVER_CLIENT_SECRET", raising=False)
    adapter = NaverShopAdapter()
    assert adapter.search("RTX 4070") == []


def test_naver_shop_normalizes_query_with_used_prefix() -> None:
    adapter = NaverShopAdapter(client_id="x", client_secret="y")
    assert adapter._normalize_query("RTX 4070") == "중고 RTX 4070"
    # Already contains 중고 → unchanged
    assert adapter._normalize_query("중고 RTX 4070") == "중고 RTX 4070"
    # Empty query → empty
    assert adapter._normalize_query("") == ""


def test_naver_shop_normalize_can_be_disabled() -> None:
    adapter = NaverShopAdapter(
        client_id="x", client_secret="y", prepend_used_keyword=False
    )
    assert adapter._normalize_query("RTX 4070") == "RTX 4070"


def test_naver_shop_expand_variants_default_is_three() -> None:
    adapter = NaverShopAdapter(client_id="x", client_secret="y")
    variants = adapter._expand_variants("중고 RTX 4070")
    # Default variants: ("", "판매", "직거래") → 3 distinct queries.
    assert variants == ["중고 RTX 4070", "중고 RTX 4070 판매", "중고 RTX 4070 직거래"]


def test_naver_shop_expand_variants_dedups() -> None:
    # Repeating "" twice should still yield only the bare query once.
    adapter = NaverShopAdapter(
        client_id="x", client_secret="y", query_variants=("", "", "판매")
    )
    variants = adapter._expand_variants("중고 RAM")
    assert variants == ["중고 RAM", "중고 RAM 판매"]


def test_naver_shop_expand_variants_empty_disables() -> None:
    # Explicit empty tuple → only the bare base query.
    adapter = NaverShopAdapter(client_id="x", client_secret="y", query_variants=())
    assert adapter._expand_variants("중고 SSD") == ["중고 SSD"]


def test_naver_shop_expand_variants_handles_empty_base() -> None:
    adapter = NaverShopAdapter(client_id="x", client_secret="y")
    assert adapter._expand_variants("") == []
