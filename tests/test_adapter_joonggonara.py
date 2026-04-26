from pathlib import Path

from src.adapters.joonggonara import parse_list

FIXTURE = Path(__file__).parent / "fixtures" / "joonggonara" / "search_rtx4070.html"


def test_joonggonara_parses_search_results() -> None:
    listings = parse_list(FIXTURE.read_text())
    assert len(listings) >= 20

    for l in listings:
        assert l.source == "joonggonara"
        assert l.listing_id.isdigit()
        assert l.title
        assert l.url.startswith("https://web.joongna.com/product/")
        assert l.price is None or l.price > 0
        assert l.status == "selling"  # search filter excludes 판매완료 by default


def test_joonggonara_extracts_prices_for_most_items() -> None:
    listings = parse_list(FIXTURE.read_text())
    priced = [l for l in listings if l.price is not None]
    assert len(priced) >= len(listings) * 0.8
