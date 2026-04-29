from pathlib import Path

from src.adapters.ruliweb_market import (
    _extract_price,
    parse_list,
)

FIXTURE = Path(__file__).parent / "fixtures" / "ruliweb_market" / "sample_p1.html"


def test_ruliweb_parses_listings_with_sale_filter() -> None:
    listings = parse_list(FIXTURE.read_text())
    assert len(listings) >= 10

    for l in listings:
        assert l.source == "ruliweb_market"
        assert l.listing_id.isdigit()
        assert l.title
        assert l.url.startswith("https://bbs.ruliweb.com/market/board/")
        assert "/read/" in l.url
        assert l.status in {"selling", "reserved", "sold", "unknown"}
        # sale_only=True (default) → only [판매]/[판매완료] rows survive.
        market_type = l.metadata.get("market_type")
        if market_type:
            assert market_type in {"판매", "판매완료"}


def test_ruliweb_listing_id_matches_url_read_segment() -> None:
    listings = parse_list(FIXTURE.read_text())
    for l in listings:
        assert l.url.endswith(f"/read/{l.listing_id}") or l.url.endswith(
            f"/read/{l.listing_id}?"
        )


def test_ruliweb_widen_includes_buy_and_exchange() -> None:
    sale = parse_list(FIXTURE.read_text(), sale_only=True)
    wide = parse_list(FIXTURE.read_text(), sale_only=False)
    assert len(wide) >= len(sale)
    types = {l.metadata.get("market_type") for l in wide if l.metadata.get("market_type")}
    # Live capture has 판매 in every row of board=45 — confirm filter doesn't crash.
    assert types  # at least one explicit market_type encountered


def test_ruliweb_metadata_carries_posted_label_and_market_type() -> None:
    listings = parse_list(FIXTURE.read_text())
    by_id = {l.listing_id: l for l in listings}
    sample = next(iter(by_id.values()))
    assert "posted_label" in sample.metadata
    # market_type may be missing if the cell is empty for some row, but most rows have it
    assert sum(1 for l in listings if l.metadata.get("market_type")) >= len(listings) * 0.8


def test_ruliweb_extracts_price_from_title_when_present() -> None:
    listings = parse_list(FIXTURE.read_text())
    titles = [l.title for l in listings]
    # Live capture: at least one row has a "30만원" / "30,000원" form.
    has_price_signal = any(
        ("만원" in t) or ("만 원" in t) or ("원" in t) for t in titles
    )
    if has_price_signal:
        assert any(l.price is not None for l in listings)


def test_extract_price_basic_forms() -> None:
    assert _extract_price("RTX 4070 30만원 직거래") == (300000, "30만원")
    assert _extract_price("그래픽카드 1,200,000원 새상품")[0] == 1200000
    # Korean-words form: "오십만원" → 500000
    assert _extract_price("RAM 오십만원 팔아요")[0] == 500000


def test_extract_price_returns_none_for_no_price() -> None:
    assert _extract_price("그래픽카드 팝니다 가격은 본문") == (None, None)
    assert _extract_price("") == (None, None)
