"""Domain-aware matching for phones and MacBooks."""

from __future__ import annotations

from dataclasses import dataclass

from src.adapters.base import UsedListing
from src.domains.consumer.normalization import normalize_consumer_product


CONSUMER_CATEGORIES = {"iphone", "galaxy", "macbook", "laptop", "tv", "appliance"}
MATCH_THRESHOLD = 0.75
PENDING_THRESHOLD = 0.45


@dataclass(frozen=True)
class ConsumerProductCandidate:
    product_id: str
    category: str
    name: str
    canonical_key: str | None = None


@dataclass(frozen=True)
class ConsumerMatchResult:
    candidate: ConsumerProductCandidate
    score: float
    reasons: list[str]

    @property
    def is_match(self) -> bool:
        return self.score >= MATCH_THRESHOLD

    @property
    def is_pending(self) -> bool:
        return PENDING_THRESHOLD <= self.score < MATCH_THRESHOLD


def score_consumer_listing(
    listing: UsedListing,
    candidate: ConsumerProductCandidate,
    *,
    category: str,
) -> ConsumerMatchResult:
    ln = normalize_consumer_product(category, listing.title)
    cn = normalize_consumer_product(category, candidate.name)

    if ln.brand and cn.brand and ln.brand != cn.brand:
        return ConsumerMatchResult(candidate, 0.0, [f"dq:brand:{ln.brand}!={cn.brand}"])

    if category in {"iphone", "galaxy"}:
        if ln.model and cn.model and ln.model != cn.model:
            return ConsumerMatchResult(candidate, 0.0, [f"dq:model:{ln.model}!={cn.model}"])
        if ln.storage_gb and cn.storage_gb and ln.storage_gb != cn.storage_gb:
            return ConsumerMatchResult(candidate, 0.0, [f"dq:storage:{ln.storage_gb}!={cn.storage_gb}"])
        return _score_phone(candidate, ln, cn)

    if category == "macbook":
        if ln.family and cn.family and ln.family != cn.family:
            return ConsumerMatchResult(candidate, 0.0, [f"dq:family:{ln.family}!={cn.family}"])
        if ln.chip and cn.chip and ln.chip != cn.chip:
            return ConsumerMatchResult(candidate, 0.0, [f"dq:chip:{ln.chip}!={cn.chip}"])
        if ln.screen_size and cn.screen_size and ln.screen_size != cn.screen_size:
            return ConsumerMatchResult(candidate, 0.0, [f"dq:screen:{ln.screen_size}!={cn.screen_size}"])
        if ln.ram_gb and cn.ram_gb and ln.ram_gb != cn.ram_gb:
            return ConsumerMatchResult(candidate, 0.0, [f"dq:ram:{ln.ram_gb}!={cn.ram_gb}"])
        if ln.storage_gb and cn.storage_gb and ln.storage_gb != cn.storage_gb:
            return ConsumerMatchResult(candidate, 0.0, [f"dq:storage:{ln.storage_gb}!={cn.storage_gb}"])
        return _score_macbook(candidate, ln, cn)

    if category == "laptop":
        if ln.model_number and cn.model_number and ln.model_number != cn.model_number:
            return ConsumerMatchResult(candidate, 0.0, [f"dq:model_number:{ln.model_number}!={cn.model_number}"])
        if ln.ram_gb and cn.ram_gb and ln.ram_gb != cn.ram_gb:
            return ConsumerMatchResult(candidate, 0.0, [f"dq:ram:{ln.ram_gb}!={cn.ram_gb}"])
        if ln.storage_gb and cn.storage_gb and ln.storage_gb != cn.storage_gb:
            return ConsumerMatchResult(candidate, 0.0, [f"dq:storage:{ln.storage_gb}!={cn.storage_gb}"])
        return _score_by_attrs(candidate, ln, cn, (("brand", 0.15), ("model_number", 0.45), ("cpu", 0.15), ("ram_gb", 0.10), ("storage_gb", 0.10)))

    if category in {"tv", "appliance"}:
        if ln.model_number and cn.model_number and ln.model_number != cn.model_number:
            return ConsumerMatchResult(candidate, 0.0, [f"dq:model_number:{ln.model_number}!={cn.model_number}"])
        return _score_by_attrs(candidate, ln, cn, (("brand", 0.20), ("model_number", 0.55), ("screen_size", 0.10), ("resolution", 0.10)))

    return ConsumerMatchResult(candidate, 0.0, [])


def _score_phone(candidate, ln, cn) -> ConsumerMatchResult:
    score = 0.0
    reasons: list[str] = []
    if ln.brand and cn.brand and ln.brand == cn.brand:
        score += 0.20
        reasons.append(f"brand:{ln.brand}")
    if ln.model and cn.model and ln.model == cn.model:
        score += 0.50
        reasons.append(f"model:{ln.model}")
    if ln.storage_gb and cn.storage_gb and ln.storage_gb == cn.storage_gb:
        score += 0.25
        reasons.append(f"storage:{ln.storage_gb}gb")
    if ln.carrier and cn.carrier and ln.carrier == cn.carrier:
        score += 0.05
        reasons.append(f"carrier:{ln.carrier}")
    return ConsumerMatchResult(candidate, round(min(score, 1.0), 3), reasons)


def _score_macbook(candidate, ln, cn) -> ConsumerMatchResult:
    score = 0.0
    reasons: list[str] = []
    for attr, weight in (
        ("family", 0.20),
        ("screen_size", 0.15),
        ("chip", 0.30),
        ("ram_gb", 0.15),
        ("storage_gb", 0.15),
    ):
        lv = getattr(ln, attr)
        cv = getattr(cn, attr)
        if lv and cv and lv == cv:
            score += weight
            reasons.append(f"{attr}:{lv}")
    if ln.brand and cn.brand and ln.brand == cn.brand:
        score += 0.05
        reasons.append(f"brand:{ln.brand}")
    return ConsumerMatchResult(candidate, round(min(score, 1.0), 3), reasons)


def _score_by_attrs(candidate, ln, cn, attrs) -> ConsumerMatchResult:
    score = 0.0
    reasons: list[str] = []
    for attr, weight in attrs:
        lv = getattr(ln, attr)
        cv = getattr(cn, attr)
        if lv and cv and lv == cv:
            score += weight
            reasons.append(f"{attr}:{lv}")
    return ConsumerMatchResult(candidate, round(min(score, 1.0), 3), reasons)


def find_best_consumer_candidate(
    listing: UsedListing,
    candidates: list[ConsumerProductCandidate],
    *,
    category: str,
) -> ConsumerMatchResult | None:
    if not candidates:
        return None
    scored = [score_consumer_listing(listing, c, category=category) for c in candidates]
    scored.sort(key=lambda r: r.score, reverse=True)
    return scored[0]
