"""Regression fixture for find_best_candidate.

Loads `tests/fixtures/matching_regression/cases.json` and verifies the
matching algorithm still agrees with hand-labeled ground truth. Catches
regressions when matching heuristics change.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.adapters.base import UsedListing
from src.services.matching import (
    DanawaProductCandidate,
    find_best_candidate,
)

_CASES_PATH = Path(__file__).parent / "fixtures" / "matching_regression" / "cases.json"
_CASES: list[dict] = json.loads(_CASES_PATH.read_text())


def _case_id(case: dict) -> str:
    return case["id"]


def _build(case: dict) -> tuple[UsedListing, list[DanawaProductCandidate], int | None]:
    listing = UsedListing(
        source="regression",
        listing_id=case["id"],
        title=case["listing_title"],
    )
    candidates = [
        DanawaProductCandidate(
            category=case["category"],
            source_id=f"danawa-{case['id']}-{i}",
            name=cd["name"],
            product_id=f"prod-{case['id']}-{i}",
        )
        for i, cd in enumerate(case["candidates"])
    ]
    truth_idx = next(
        (i for i, cd in enumerate(case["candidates"]) if cd["expected_match"]),
        None,
    )
    return listing, candidates, truth_idx


@pytest.mark.parametrize("case", _CASES, ids=[_case_id(c) for c in _CASES])
def test_matching_regression_case(case: dict) -> None:
    listing, candidates, truth_idx = _build(case)
    result = find_best_candidate(listing, candidates)

    if truth_idx is None:
        # No candidate should match. Algorithm must return None or not is_match.
        assert result is None or not result.is_match, (
            f"{case['id']}: expected no match, got "
            f"{result.candidate.name!r} score={result.score} reasons={result.reasons}"
        )
    else:
        expected_name = case["candidates"][truth_idx]["name"]
        assert result is not None, (
            f"{case['id']}: expected match {expected_name!r}, got None"
        )
        assert result.is_match, (
            f"{case['id']}: expected match {expected_name!r}, got "
            f"score={result.score} candidate={result.candidate.name!r} "
            f"reasons={result.reasons}"
        )
        assert result.candidate.name == expected_name, (
            f"{case['id']}: matched wrong candidate. "
            f"expected={expected_name!r} got={result.candidate.name!r} "
            f"score={result.score} reasons={result.reasons}"
        )


def test_matching_regression_overall_metrics() -> None:
    """Aggregate precision/recall floor across the full fixture."""
    tp = fp = tn = fn = 0
    for case in _CASES:
        listing, candidates, truth_idx = _build(case)
        result = find_best_candidate(listing, candidates)
        matched_correct = (
            truth_idx is not None
            and result is not None
            and result.is_match
            and result.candidate.name == case["candidates"][truth_idx]["name"]
        )
        is_negative_case = truth_idx is None
        algo_says_match = result is not None and result.is_match
        if matched_correct:
            tp += 1
        elif is_negative_case and not algo_says_match:
            tn += 1
        elif is_negative_case and algo_says_match:
            fp += 1
        else:
            fn += 1
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    print(
        f"\nmatching regression: tp={tp} fp={fp} tn={tn} fn={fn} "
        f"precision={precision:.3f} recall={recall:.3f}"
    )
    assert precision >= 0.85, f"precision {precision:.3f} below 0.85 floor"
    assert recall >= 0.85, f"recall {recall:.3f} below 0.85 floor"
