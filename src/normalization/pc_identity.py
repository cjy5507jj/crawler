"""Dynamic canonical identity for PC parts.

Danawa still supplies the product master, but the identity is derived from the
normalized title rather than a hardcoded SKU list. This lets newly crawled PC
parts get stable `canonical_key` / `specs` automatically.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.normalization.catalog import normalize_product_name


@dataclass(frozen=True)
class PCIdentity:
    domain: str
    canonical_key: str | None
    specs: dict


def build_pc_identity(category: str, name: str) -> PCIdentity:
    norm = normalize_product_name(category, name)
    parts = ["pc_parts", category]
    if norm.brand:
        parts.append(norm.brand)
    parts.extend(_identity_tokens(category, norm.category_tokens, norm.capacity_tokens))
    parts.extend(_slug(t) for t in norm.sku_line_tokens)
    parts.extend(norm.capacity_tokens)
    canonical_key = ":".join(parts) if len(parts) > 2 else None
    specs = {
        "brand": norm.brand,
        "chipset": norm.chipset,
        "model_name": norm.model_name,
        "category_tokens": norm.category_tokens,
        "sku_line_tokens": norm.sku_line_tokens,
        "capacity_tokens": norm.capacity_tokens,
    }
    return PCIdentity(domain="pc_parts", canonical_key=canonical_key, specs=specs)


def _slug(value: str) -> str:
    return value.strip().lower().replace(" ", "-")


def _identity_tokens(category: str, category_tokens: list[str], capacity_tokens: list[str]) -> list[str]:
    tokens = [t for t in category_tokens if t not in set(capacity_tokens)]
    if category == "ssd":
        model = [t for t in tokens if any(suffix in t for suffix in ("pro", "evo", "qvo"))]
        iface = [t for t in tokens if t in {"m.2", "nvme", "sata"}]
        other = [t for t in tokens if t not in set(model + iface)]
        out = model + other
        if iface:
            out.append("-".join(iface))
        return out
    return tokens
