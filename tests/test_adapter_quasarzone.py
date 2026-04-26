from pathlib import Path

from src.adapters.quasarzone import parse_list

FIXTURE_SALEINFO = Path(__file__).parent / "fixtures" / "quasarzone" / "qb_saleinfo.html"
FIXTURE_PARTNER = Path(__file__).parent / "fixtures" / "quasarzone" / "qb_partnersaleinfo.html"


def test_quasarzone_parses_saleinfo_board() -> None:
    listings = parse_list(FIXTURE_SALEINFO.read_text(), board="qb_saleinfo")
    assert len(listings) >= 20

    for l in listings:
        assert l.source == "quasarzone"
        assert l.listing_id.isdigit()
        assert l.title
        assert l.url.startswith("https://quasarzone.com/bbs/")
        assert l.status in {"selling", "reserved", "sold", "unknown"}
        assert l.metadata["board"] == "qb_saleinfo"

    with_category = [l for l in listings if l.metadata.get("board_category")]
    assert with_category


def test_quasarzone_parses_partnersaleinfo_board() -> None:
    listings = parse_list(FIXTURE_PARTNER.read_text(), board="qb_partnersaleinfo")
    assert len(listings) >= 20
    assert all(l.metadata["board"] == "qb_partnersaleinfo" for l in listings)
