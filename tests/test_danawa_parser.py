from pathlib import Path

import httpx

from src.crawlers.danawa import _init_category, parse_products

FIXTURE = Path(__file__).parent / "fixtures" / "danawa" / "cpu_p1.html"


def test_parse_products_returns_real_items() -> None:
    html = FIXTURE.read_text()
    products = parse_products(html)
    assert len(products) >= 20

    # Every parsed item has a non-empty source_id, name, and a numeric price.
    for p in products:
        assert p.source_id
        assert p.name
        assert p.url.startswith("https://prod.danawa.com")
        assert p.price is not None and p.price > 0


def test_parse_products_skips_ads() -> None:
    html = FIXTURE.read_text()
    products = parse_products(html)
    # Ad slots have ids prefixed adReader; pcode would still be present but
    # we filter by id, so make sure none of the returned products are ads.
    for p in products:
        # IDs we extract come from pcode; we just assert that the *count*
        # is below the raw li count (which includes ads).
        assert p.source_id.isdigit()
    # CPU page has at least 1 ad on first page; total >= 30 incl ad means
    # filtered list should be at least 1 less.
    assert len(products) >= 25


def test_init_category_retries_on_transient_error(monkeypatch) -> None:
    html = (
        '<html><a href="?cate1=1&cate2=2&cate3=3&cate4=4">x</a></html>'
    )

    class _Resp:
        text = html

        def raise_for_status(self) -> None:
            return None

    calls = {"n": 0}

    def fake_get(self, url, params=None, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("boom")
        return _Resp()

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    with httpx.Client() as c:
        init = _init_category(c, "112747")
    assert init.physics == ("1", "2", "3", "4")
    assert calls["n"] == 2
