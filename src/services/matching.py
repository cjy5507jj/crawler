"""Score a used listing against Danawa product candidates."""

from __future__ import annotations

from dataclasses import dataclass

from src.adapters.base import UsedListing
from src.normalization.catalog import (
    is_excluded_listing,
    normalize_product_name,
)

# Score thresholds.
MATCH_THRESHOLD = 0.55          # >= : matched
PENDING_THRESHOLD = 0.40        # >= and < MATCH_THRESHOLD : recorded with no match link


@dataclass
class DanawaProductCandidate:
    category: str
    source_id: str
    name: str
    brand: str | None = None
    model_name: str | None = None
    url: str | None = None
    product_id: str | None = None  # uuid from products table when known


@dataclass
class MatchResult:
    candidate: DanawaProductCandidate
    score: float
    reasons: list[str]

    @property
    def is_match(self) -> bool:
        return self.score >= MATCH_THRESHOLD

    @property
    def is_pending(self) -> bool:
        return PENDING_THRESHOLD <= self.score < MATCH_THRESHOLD


def score_listing_against_candidate(
    listing: UsedListing,
    candidate: DanawaProductCandidate,
) -> MatchResult:
    listing_norm = normalize_product_name(candidate.category, listing.title)
    candidate_norm = normalize_product_name(candidate.category, candidate.name)

    # ------------------------------------------------------------------
    # HARD DISQUALIFICATIONS — these mean "definitely not the same SKU"
    # ------------------------------------------------------------------
    # 1. Brand mismatch: ASUS RTX 5070 ≠ MSI RTX 5070 (different SKU even
    #    if same chip).
    if (
        listing_norm.brand
        and candidate_norm.brand
        and listing_norm.brand != candidate_norm.brand
    ):
        return MatchResult(
            candidate=candidate,
            score=0.0,
            reasons=[f"dq:brand:{listing_norm.brand}!={candidate_norm.brand}"],
        )

    # 2. Category-token mismatch: RTX 5070 ≠ RTX 5080, 5600X ≠ 7800X3D.
    listing_cat = set(listing_norm.category_tokens)
    candidate_cat = set(candidate_norm.category_tokens)
    if listing_cat and candidate_cat and not (listing_cat & candidate_cat):
        return MatchResult(
            candidate=candidate,
            score=0.0,
            reasons=[f"dq:cat:{sorted(listing_cat)}!={sorted(candidate_cat)}"],
        )

    # 3. Capacity mismatch (SSD/RAM/HDD): 1TB SSD ≠ 2TB SSD.
    listing_cap = set(listing_norm.capacity_tokens)
    candidate_cap = set(candidate_norm.capacity_tokens)
    if listing_cap and candidate_cap and not (listing_cap & candidate_cap):
        return MatchResult(
            candidate=candidate,
            score=0.0,
            reasons=[f"dq:capacity:{sorted(listing_cap)}!={sorted(candidate_cap)}"],
        )

    # 4. SKU sub-model line mismatch (GPU/mainboard): MSI RTX 5070 VENTUS ≠
    #    MSI RTX 5070 GAMING TRIO. Only disqualify when BOTH sides explicitly
    #    name a sub-model line and they share none — silent listings get the
    #    benefit of the doubt and fall back to scoring.
    listing_line = set(listing_norm.sku_line_tokens)
    candidate_line = set(candidate_norm.sku_line_tokens)
    if listing_line and candidate_line and not (listing_line & candidate_line):
        return MatchResult(
            candidate=candidate,
            score=0.0,
            reasons=[f"dq:sku_line:{sorted(listing_line)}!={sorted(candidate_line)}"],
        )

    # ------------------------------------------------------------------
    # SCORING (only reachable when no hard disqualification triggered)
    # ------------------------------------------------------------------
    score = 0.0
    reasons: list[str] = []

    if (
        listing_norm.brand
        and candidate_norm.brand
        and listing_norm.brand == candidate_norm.brand
    ):
        score += 0.25
        reasons.append(f"brand:{listing_norm.brand}")

    overlap = set(listing_norm.tokens) & set(candidate_norm.tokens)
    if overlap:
        score += min(len(overlap) * 0.08, 0.30)
        reasons.append(f"tokens:{','.join(sorted(overlap)[:5])}")

    cat_overlap = listing_cat & candidate_cat
    if cat_overlap:
        score += min(len(cat_overlap) * 0.25, 0.50)
        reasons.append(f"cat:{','.join(sorted(cat_overlap))}")

    line_overlap = listing_line & candidate_line
    if line_overlap:
        score += min(len(line_overlap) * 0.20, 0.30)
        reasons.append(f"sku_line:{','.join(sorted(line_overlap))}")

    cap_overlap = listing_cap & candidate_cap
    if cap_overlap:
        score += 0.10
        reasons.append(f"capacity:{','.join(sorted(cap_overlap))}")

    if (
        listing.title
        and candidate.name
        and listing.title.strip().lower() == candidate.name.strip().lower()
    ):
        score += 0.10
        reasons.append("exact_title")

    return MatchResult(candidate=candidate, score=round(min(score, 1.0), 3), reasons=reasons)


def find_best_candidate(
    listing: UsedListing,
    candidates: list[DanawaProductCandidate],
) -> MatchResult | None:
    """Pick the highest-scoring candidate. Returns None if listing should be excluded."""
    if is_excluded_listing(listing.title):
        return None
    if not candidates:
        return None

    scored = [score_listing_against_candidate(listing, c) for c in candidates]
    scored.sort(key=lambda r: r.score, reverse=True)
    return scored[0]
