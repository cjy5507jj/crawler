from src.adapters.base import UsedListing
from src.services.matching import (
    DanawaProductCandidate,
    MATCH_THRESHOLD,
    PENDING_THRESHOLD,
    find_best_candidate,
    score_listing_against_candidate,
)


def _candidate(name: str, category: str = "cpu") -> DanawaProductCandidate:
    return DanawaProductCandidate(
        category=category,
        source_id="danawa-1",
        name=name,
        brand=None,
        product_id="prod-uuid",
    )


def test_score_brand_plus_category_token_strong_match() -> None:
    listing = UsedListing(
        source="bunjang",
        listing_id="1",
        title="AMD 라이젠5 5600X 정품 팝니다",
    )
    candidate = _candidate("AMD 라이젠5-5세대 5600X (버미어) (정품)")
    result = score_listing_against_candidate(listing, candidate)
    assert result.score >= MATCH_THRESHOLD
    assert result.is_match


def test_score_no_overlap_low_score() -> None:
    listing = UsedListing(source="bunjang", listing_id="2", title="자전거 팝니다")
    candidate = _candidate("AMD 라이젠5 5600X")
    result = score_listing_against_candidate(listing, candidate)
    assert result.score < PENDING_THRESHOLD


def test_find_best_candidate_picks_highest() -> None:
    listing = UsedListing(
        source="quasarzone", listing_id="3", title="라이젠 5600X 미개봉"
    )
    candidates = [
        _candidate("AMD 라이젠5 7600X"),
        _candidate("AMD 라이젠5 5600X 정품"),
        _candidate("인텔 i5-14600K"),
    ]
    result = find_best_candidate(listing, candidates)
    assert result is not None
    assert "5600X" in result.candidate.name


def test_find_best_candidate_excludes_buy_request() -> None:
    listing = UsedListing(source="coolenjoy", listing_id="4", title="RTX 4070 삽니다")
    candidates = [_candidate("ASUS RTX 4070 OC", category="gpu")]
    assert find_best_candidate(listing, candidates) is None


def test_pending_band_between_thresholds() -> None:
    # Same brand only — should land in the pending band, not auto-match.
    listing = UsedListing(source="bunjang", listing_id="5", title="ASUS 키보드 팝니다")
    candidate = _candidate("ASUS Z690 메인보드", category="mainboard")
    candidate.brand = "asus"
    result = score_listing_against_candidate(listing, candidate)
    assert result.score < MATCH_THRESHOLD


def test_brand_mismatch_disqualifies() -> None:
    """ASUS RTX 5070 listing must NOT match MSI RTX 5070 product."""
    listing = UsedListing(
        source="bunjang", listing_id="b1",
        title="ASUS ROG STRIX RTX 5070 OC",
    )
    candidate = _candidate("MSI 지포스 RTX 5070 게이밍 트리오 OC D7 12GB", category="gpu")
    result = score_listing_against_candidate(listing, candidate)
    assert result.score == 0.0
    assert "dq:brand" in result.reasons[0]


def test_capacity_mismatch_disqualifies() -> None:
    """1TB SSD must NOT match 2TB SSD product."""
    listing = UsedListing(
        source="bunjang", listing_id="s1",
        title="삼성 990 PRO 1TB M.2 NVMe",
    )
    candidate = _candidate("삼성전자 990 PRO M.2 NVMe 2TB", category="ssd")
    result = score_listing_against_candidate(listing, candidate)
    assert result.score == 0.0
    assert "dq:capacity" in result.reasons[0]


def test_capacity_match_qualifies() -> None:
    listing = UsedListing(
        source="bunjang", listing_id="s2",
        title="삼성 990 PRO 1TB M.2 NVMe",
    )
    candidate = _candidate("삼성전자 990 PRO M.2 NVMe 1TB", category="ssd")
    result = score_listing_against_candidate(listing, candidate)
    assert result.score >= MATCH_THRESHOLD


def test_sku_line_mismatch_disqualifies_same_chip() -> None:
    """MSI VENTUS RTX 5070 ≠ MSI GAMING TRIO RTX 5070."""
    listing = UsedListing(
        source="bunjang", listing_id="g1",
        title="MSI RTX 5070 VENTUS 3X OC 12GB",
    )
    candidate = _candidate("MSI 지포스 RTX 5070 게이밍 트리오 OC D7 12GB", category="gpu")
    result = score_listing_against_candidate(listing, candidate)
    assert result.score == 0.0
    assert "dq:sku_line" in result.reasons[0]


def test_sku_line_match_boosts_score() -> None:
    listing = UsedListing(
        source="bunjang", listing_id="g2",
        title="MSI RTX 5070 게이밍 트리오 OC 미개봉",
    )
    candidate = _candidate("MSI 지포스 RTX 5070 게이밍 트리오 OC D7 12GB", category="gpu")
    result = score_listing_against_candidate(listing, candidate)
    assert result.score >= MATCH_THRESHOLD
    assert any("sku_line:gaming trio" in r for r in result.reasons)
