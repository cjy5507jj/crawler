from pathlib import Path

from src.adapters.bunjang import parse_response

FIXTURE = Path(__file__).parent / "fixtures" / "bunjang" / "search_5600x.json"


def test_bunjang_parses_search_response() -> None:
    listings = parse_response(FIXTURE.read_text())
    assert len(listings) >= 20

    for l in listings:
        assert l.source == "bunjang"
        assert l.listing_id.isdigit()
        assert l.title
        assert l.url.startswith("https://m.bunjang.co.kr/products/")
        assert l.status in {"selling", "reserved", "sold", "unknown"}
        assert l.price is None or l.price > 0


def test_bunjang_skips_ads() -> None:
    import json

    raw = json.loads(FIXTURE.read_text())
    ad_pids = {str(item["pid"]) for item in raw["list"] if item.get("ad")}
    parsed_pids = {l.listing_id for l in parse_response(FIXTURE.read_text())}
    assert not (ad_pids & parsed_pids)
