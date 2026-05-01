"""Seed catalog for first consumer-electronics expansion.

The seed is intentionally compact and high-signal. It gives the matcher a
canonical product master before broader automated product discovery exists.
"""

from __future__ import annotations

from src.domains.consumer.normalization import normalize_consumer_product


_PHONE_MODELS: tuple[tuple[str, str, str, tuple[int, ...]], ...] = (
    ("iphone", "Apple iPhone 13", "iphone-13", (128, 256, 512)),
    ("iphone", "Apple iPhone 14", "iphone-14", (128, 256, 512)),
    ("iphone", "Apple iPhone 15", "iphone-15", (128, 256, 512)),
    ("iphone", "Apple iPhone 15 Pro", "iphone-15-pro", (128, 256, 512, 1024)),
    ("iphone", "Apple iPhone 15 Pro Max", "iphone-15-pro-max", (256, 512, 1024)),
    ("iphone", "Apple iPhone 16", "iphone-16", (128, 256, 512)),
    ("iphone", "Apple iPhone 16 Pro", "iphone-16-pro", (128, 256, 512, 1024)),
    ("iphone", "Apple iPhone 16 Pro Max", "iphone-16-pro-max", (256, 512, 1024)),
    ("galaxy", "Samsung Galaxy S23", "galaxy-s23", (128, 256, 512)),
    ("galaxy", "Samsung Galaxy S24", "galaxy-s24", (128, 256, 512)),
    ("galaxy", "Samsung Galaxy S24 Ultra", "galaxy-s24-ultra", (256, 512, 1024)),
    ("galaxy", "Samsung Galaxy S25", "galaxy-s25", (128, 256, 512)),
    ("galaxy", "Samsung Galaxy Z Fold 6", "galaxy-z-fold-6", (256, 512, 1024)),
    ("galaxy", "Samsung Galaxy Z Flip 6", "galaxy-z-flip-6", (256, 512)),
)

_MACBOOK_MODELS: tuple[tuple[str, str, str, tuple[tuple[int, int], ...]], ...] = (
    ("MacBook Air 13 M2", "macbook-air-13-m2", "macbook", ((8, 256), (8, 512), (16, 512))),
    ("MacBook Air 13 M3", "macbook-air-13-m3", "macbook", ((8, 256), (8, 512), (16, 512), (24, 1024))),
    ("MacBook Air 15 M3", "macbook-air-15-m3", "macbook", ((8, 256), (16, 512), (24, 1024))),
    ("MacBook Pro 14 M3 Pro", "macbook-pro-14-m3-pro", "macbook", ((18, 512), (18, 1024), (36, 1024))),
    ("MacBook Pro 14 M4", "macbook-pro-14-m4", "macbook", ((16, 512), (16, 1024), (24, 1024))),
    ("MacBook Pro 16 M3 Max", "macbook-pro-16-m3-max", "macbook", ((36, 1024), (48, 1024), (64, 2048))),
)

_QUERY_SEEDS: dict[str, tuple[str, ...]] = {
    "iphone": (
        "아이폰 15 프로 256GB",
        "아이폰 15 프로 512GB",
        "아이폰 15 프로맥스 256GB",
        "아이폰 15 프로맥스 512GB",
        "아이폰 16 프로 256GB",
        "아이폰 16 프로 512GB",
        "아이폰 14 128GB",
    ),
    "galaxy": (
        "갤럭시 S24 울트라 256GB",
        "갤럭시 S24 울트라 512GB",
        "갤럭시 S24 울트라 1TB",
        "갤럭시 S24 256GB",
        "갤럭시 Z Fold 6 512GB",
        "갤럭시 Z Flip 6 256GB",
    ),
    "macbook": (
        "맥북프로 14 M3 Pro 18GB 512GB",
        "맥북에어 13 M2 8GB 256GB",
        "맥북에어 15 M3 16GB 512GB",
        "맥북프로 16 M3 Max 36GB 1TB",
    ),
    "laptop": (
        "LG 그램 16Z90R",
        "삼성 갤럭시북 NT950",
        "레노버 씽크패드 X1",
        "ASUS ROG 노트북",
    ),
    "tv": (
        "LG OLED 65인치 4K",
        "삼성 QLED 65인치 4K",
        "OLED65C3",
        "KQ75",
    ),
    "appliance": (
        "삼성 비스포크 냉장고",
        "LG 오브제 냉장고",
        "LG 트롬 세탁기",
        "다이슨 청소기",
    ),
}


def build_seed_payloads() -> list[dict]:
    rows: list[dict] = []
    for category, source_id, name in _seed_names():
        norm = normalize_consumer_product(category, name)
        rows.append(
            {
                "category": category,
                "domain": norm.domain,
                "source": "consumer_seed",
                "source_id": source_id,
                "name": name,
                "brand": norm.brand,
                "model_name": _model_name(norm),
                "normalized_name": name.lower(),
                "canonical_key": norm.canonical_key,
                "specs": norm.specs,
                "is_accessory": False,
            }
        )
    return rows


def _seed_names() -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for category, model_name, source_prefix, capacities in _PHONE_MODELS:
        for capacity in capacities:
            rows.append((category, f"{source_prefix}-{capacity}", f"{model_name} {_format_capacity(capacity)}"))
    for model_name, source_prefix, category, variants in _MACBOOK_MODELS:
        for ram, storage in variants:
            rows.append((category, f"{source_prefix}-{ram}-{storage}", f"{model_name} {ram}GB {_format_capacity(storage)}"))
    return rows


def _format_capacity(gb: int) -> str:
    return "1TB" if gb == 1024 else "2TB" if gb == 2048 else f"{gb}GB"


def query_seeds_for_category(category: str) -> list[str]:
    return list(_QUERY_SEEDS.get(category.lower(), ()))


def _model_name(norm) -> str | None:
    if norm.domain == "phone":
        if norm.model and norm.storage_gb:
            return f"{norm.model} {norm.storage_gb}gb"
        return norm.model
    if norm.domain == "macbook":
        bits = ["macbook", norm.family, str(norm.screen_size) if norm.screen_size else None, norm.chip]
        if norm.ram_gb:
            bits.append(f"{norm.ram_gb}gb")
        if norm.storage_gb:
            bits.append(f"{norm.storage_gb}gb")
        return " ".join(str(b) for b in bits if b)
    return None
