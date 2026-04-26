from pathlib import Path

from src.adapters.coolenjoy import parse_list

FIXTURE = Path(__file__).parent / "fixtures" / "coolenjoy" / "mart2_p1.html"


def test_coolenjoy_parses_listings_with_prices() -> None:
    listings = parse_list(FIXTURE.read_text())
    assert len(listings) >= 10

    priced = [l for l in listings if l.price is not None]
    assert len(priced) >= len(listings) * 0.8  # most have a numeric price

    for l in listings:
        assert l.source == "coolenjoy"
        assert l.listing_id.isdigit()
        assert l.title
        assert l.url.startswith("https://coolenjoy.net/bbs/")
        assert l.status in {"selling", "reserved", "sold", "unknown"}


def test_coolenjoy_skips_notice_rows() -> None:
    listings = parse_list(FIXTURE.read_text())
    titles = [l.title for l in listings]
    assert not any("공지사항" in t for t in titles)
