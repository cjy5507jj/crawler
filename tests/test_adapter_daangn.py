from pathlib import Path

from src.adapters.daangn import parse_list

FIXTURE = Path(__file__).parent / "fixtures" / "daangn" / "search_rtx4070.html"


def test_daangn_parses_rendered_search_results() -> None:
    listings = parse_list(FIXTURE.read_text())
    assert len(listings) >= 30  # Playwright-rendered fixture has ~58

    for l in listings:
        assert l.source == "daangn"
        assert l.listing_id
        assert l.title
        assert l.url.startswith("https://www.daangn.com/kr/buy-sell/")
        assert l.status in {"selling", "reserved", "sold", "unknown"}


def test_daangn_extracts_price_and_status() -> None:
    listings = parse_list(FIXTURE.read_text())
    priced = [l for l in listings if l.price is not None]
    assert len(priced) >= len(listings) * 0.8

    statuses = {l.status for l in listings}
    # Both selling and sold should appear in real results.
    assert "selling" in statuses or "sold" in statuses


def test_daangn_title_excludes_status_and_location() -> None:
    listings = parse_list(FIXTURE.read_text())
    for l in listings:
        assert "판매완료" not in l.title
        assert "끌올" not in l.title
        assert "·" not in l.title
