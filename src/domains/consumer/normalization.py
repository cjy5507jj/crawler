"""Normalization for consumer electronics categories.

The PC-parts matcher is intentionally strict around part SKUs. Phones/MacBooks
need different identifiers: model family, screen/chip/RAM/storage, carrier, and
condition flags. This module starts with the high-value MVP categories.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ConsumerNormalized:
    domain: str
    category: str
    brand: str | None
    model: str | None = None
    model_number: str | None = None
    family: str | None = None
    screen_size: int | None = None
    chip: str | None = None
    cpu: str | None = None
    ram_gb: int | None = None
    storage_gb: int | None = None
    panel: str | None = None
    resolution: str | None = None
    capacity_l: int | None = None
    carrier: str | None = None
    battery_health: int | None = None
    condition_flags: list[str] = field(default_factory=list)
    canonical_key: str | None = None
    specs: dict = field(default_factory=dict)


def _norm_text(value: str) -> str:
    text = value.lower()
    text = re.sub(r"(?i)(iphone|아이폰)\s*(\d{1,2})\s*(프로맥스|프맥|promax|pro\s*max)", r"\1 \2 pro max", text)
    text = re.sub(r"(?i)(iphone|아이폰)\s*(\d{1,2})\s*(프로|pro)", r"\1 \2 pro", text)
    text = re.sub(r"(?i)(iphone|아이폰)\s*(\d{1,2})\s*(플러스|plus)", r"\1 \2 plus", text)
    text = re.sub(r"(?i)(s\d{2})\s*u\b", r"\1 ultra", text)
    text = text.replace("프로맥스", "프로 맥스")
    text = text.replace("프맥", "프로 맥스")
    text = text.replace("pro맥스", "pro max")
    text = text.replace("울트라", "ultra")
    text = text.replace("플러스", "plus")
    text = text.replace("폴드", "fold")
    text = text.replace("플립", "flip")
    text = text.replace("기가", "gb")
    text = text.replace("테라", "tb")
    text = re.sub(r"[()\[\],/]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _storage_gb(text: str) -> int | None:
    m = re.search(r"\b(32|64|128|256|512)\s?(?:gb|기가|g)\b", text, re.I)
    if m:
        return int(m.group(1))
    if re.search(r"\b2\s?(?:tb|테라)\b", text, re.I):
        return 2048
    if re.search(r"\b1\s?(?:tb|테라)\b", text, re.I):
        return 1024
    return None


def _ram_gb(text: str) -> int | None:
    values = [int(v) for v in re.findall(r"\b(8|16|18|24|32|36|48|64|96)\s?gb\b", text, re.I)]
    if not values:
        return None
    # MacBook titles usually mention RAM before SSD; storage parser handles SSD.
    return values[0]


def _condition_flags(text: str) -> list[str]:
    flags: list[str] = []
    if any(tok in text for tok in ("후면파손", "후면 파손", "뒷판파손", "뒷판 파손", "카메라파손", "카메라 파손", "외관파손", "외관 파손")):
        flags.append("damaged_body")
    if any(tok in text for tok in ("액정파손", "액정 파손", "화면파손", "화면 파손")):
        flags.append("damaged_display")
    elif "파손" in text and "damaged_body" not in flags:
        flags.append("damaged_display")
    if any(tok in text for tok in ("부품용", "고장", "침수")):
        flags.append("parts_only")
    if "미개봉" in text:
        flags.append("sealed")
    if any(tok in text for tok in ("리퍼", "교환폰")):
        flags.append("refurbished")
    if "사설수리" in text or "사설 수리" in text:
        flags.append("third_party_repair")
    return flags


def _battery_health(text: str) -> int | None:
    m = re.search(r"(?:배터리|배터리효율|효율|성능)\s*(?:성능)?\s*(\d{2,3})\s?%", text)
    if not m:
        return None
    value = int(m.group(1))
    return value if 50 <= value <= 100 else None


def _phone_carrier(text: str) -> str | None:
    if any(tok in text for tok in ("자급제", "언락", "unlocked", "공기계")):
        return "unlocked"
    if any(tok in text for tok in ("skt", "sk ", "에스케이")):
        return "skt"
    if "kt" in text or "케이티" in text:
        return "kt"
    if any(tok in text for tok in ("lgu", "lg u", "유플러스", "u+")):
        return "lgu"
    return None


def normalize_consumer_product(category: str, name: str) -> ConsumerNormalized:
    category = category.lower()
    text = _norm_text(name)
    if category == "iphone":
        return _normalize_iphone(category, text)
    if category == "galaxy":
        return _normalize_galaxy(category, text)
    if category == "macbook":
        return _normalize_macbook(category, text)
    if category == "laptop":
        return _normalize_laptop(category, text)
    if category == "tv":
        return _normalize_tv(category, text)
    if category == "appliance":
        return _normalize_appliance(category, text)
    return ConsumerNormalized(
        domain="consumer",
        category=category,
        brand=None,
        condition_flags=_condition_flags(text),
    )


def _normalize_iphone(category: str, text: str) -> ConsumerNormalized:
    m = re.search(r"(?:iphone|아이폰)\s?(1[1-9]|\d)(?:\s|-)?(pro\s?max|프로\s?맥스|pro|프로|plus|플러스|mini|미니|e)?", text, re.I)
    model = None
    if m:
        suffix = (m.group(2) or "").replace("프로", "pro").replace("맥스", "max").replace("플러스", "plus").replace("미니", "mini")
        suffix = re.sub(r"\s+", " ", suffix).strip()
        model = f"iphone {m.group(1)}{(' ' + suffix) if suffix else ''}"
    storage = _storage_gb(text)
    carrier = _phone_carrier(text)
    battery = _battery_health(text)
    canonical = _phone_key("apple", model, storage)
    return ConsumerNormalized(
        domain="phone",
        category=category,
        brand="apple",
        model=model,
        storage_gb=storage,
        carrier=carrier,
        battery_health=battery,
        condition_flags=_condition_flags(text),
        canonical_key=canonical,
        specs={"model": model, "storage_gb": storage, "carrier": carrier, "battery_health": battery},
    )


def _normalize_galaxy(category: str, text: str) -> ConsumerNormalized:
    m = re.search(r"(?:galaxy|갤럭시)?\s?(s\s?\d{2}|z\s?fold\s?\d|z\s?flip\s?\d|fold\s?\d|flip\s?\d)(?:\s|-)?(ultra|plus|\+)?", text, re.I)
    model = None
    if m:
        base = re.sub(r"\s+", "", m.group(1)).replace("fold", "zfold").replace("flip", "zflip")
        suffix = (m.group(2) or "").replace("+", "plus")
        model = f"galaxy {base}{(' ' + suffix) if suffix else ''}"
    storage = _storage_gb(text)
    carrier = _phone_carrier(text)
    battery = _battery_health(text)
    canonical = _phone_key("samsung", model, storage)
    return ConsumerNormalized(
        domain="phone",
        category=category,
        brand="samsung",
        model=model,
        storage_gb=storage,
        carrier=carrier,
        battery_health=battery,
        condition_flags=_condition_flags(text),
        canonical_key=canonical,
        specs={"model": model, "storage_gb": storage, "carrier": carrier, "battery_health": battery},
    )


def _normalize_macbook(category: str, text: str) -> ConsumerNormalized:
    family = "air" if any(tok in text for tok in ("air", "에어")) else None
    if any(tok in text for tok in ("pro", "프로")):
        family = "pro"
    screen = None
    m_screen = re.search(r"\b(13|14|15|16)\s?(?:인치|inch|\")?", text)
    if m_screen:
        screen = int(m_screen.group(1))
    m_chip = re.search(r"\b(m[1-4])\s?(pro|max|ultra)?\b", text, re.I)
    chip = None
    if m_chip:
        chip = m_chip.group(1).lower()
        if m_chip.group(2):
            chip += f" {m_chip.group(2).lower()}"
    ram = _ram_gb(text)
    storage = _storage_gb(text)
    canonical = None
    if family and screen and chip and ram and storage:
        canonical = "macbook:%s:%s:%s:%sgb:%sgb" % (
            family,
            screen,
            chip.replace(" ", "-"),
            ram,
            storage,
        )
    return ConsumerNormalized(
        domain="macbook",
        category=category,
        brand="apple",
        family=family,
        screen_size=screen,
        chip=chip,
        ram_gb=ram,
        storage_gb=storage,
        condition_flags=_condition_flags(text),
        canonical_key=canonical,
        specs={"family": family, "screen_size": screen, "chip": chip, "ram_gb": ram, "storage_gb": storage},
    )


def _normalize_laptop(category: str, text: str) -> ConsumerNormalized:
    brand = _detect_brand(text)
    model_number = _detect_model_code(text)
    cpu = _detect_cpu(text)
    ram = _ram_gb(text)
    storage = _storage_gb(text)
    canonical = None
    if brand and model_number:
        bits = ["laptop", brand, model_number]
        if cpu:
            bits.append(cpu)
        if ram:
            bits.append(f"{ram}gb")
        if storage:
            bits.append(f"{storage}gb")
        canonical = ":".join(bits)
    return ConsumerNormalized(
        domain="laptop",
        category=category,
        brand=brand,
        model_number=model_number,
        cpu=cpu,
        ram_gb=ram,
        storage_gb=storage,
        condition_flags=_condition_flags(text),
        canonical_key=canonical,
        specs={"model_number": model_number, "cpu": cpu, "ram_gb": ram, "storage_gb": storage},
    )


def _normalize_tv(category: str, text: str) -> ConsumerNormalized:
    brand = _detect_brand(text)
    model_number = _detect_model_code(text)
    screen = None
    m_screen = re.search(r"\b(32|43|48|50|55|65|75|77|83|85|98)\s?(?:인치|inch|\")?", text)
    if m_screen:
        screen = int(m_screen.group(1))
    panel = "qd-oled" if "qd-oled" in text else "oled" if "oled" in text else "qled" if "qled" in text else None
    resolution = "8k" if "8k" in text else "4k" if "4k" in text or "uhd" in text else None
    canonical = None
    if brand and model_number:
        canonical = f"appliance:tv:{brand}:{model_number}"
        if screen:
            canonical += f":{screen}"
        if resolution:
            canonical += f":{resolution}"
    return ConsumerNormalized(
        domain="appliance",
        category=category,
        brand=brand,
        model_number=model_number,
        screen_size=screen,
        panel=panel,
        resolution=resolution,
        condition_flags=_condition_flags(text),
        canonical_key=canonical,
        specs={"model_number": model_number, "screen_size": screen, "panel": panel, "resolution": resolution},
    )


def _normalize_appliance(category: str, text: str) -> ConsumerNormalized:
    brand = _detect_brand(text)
    model_number = _detect_model_code(text)
    m_capacity = re.search(r"\b(\d{2,4})\s?l\b", text, re.I)
    capacity_l = int(m_capacity.group(1)) if m_capacity else None
    canonical = f"appliance:{category}:{brand}:{model_number}" if brand and model_number else None
    return ConsumerNormalized(
        domain="appliance",
        category=category,
        brand=brand,
        model_number=model_number,
        capacity_l=capacity_l,
        condition_flags=_condition_flags(text),
        canonical_key=canonical,
        specs={"model_number": model_number, "capacity_l": capacity_l},
    )


def _phone_key(brand: str, model: str | None, storage_gb: int | None) -> str | None:
    if not model or not storage_gb:
        return None
    return f"phone:{brand}:{model.replace(' ', '-')}:{storage_gb}gb"


def _detect_brand(text: str) -> str | None:
    aliases = (
        ("samsung", ("samsung", "삼성")),
        ("lg", ("lg", "엘지")),
        ("apple", ("apple", "애플")),
        ("lenovo", ("lenovo", "레노버", "thinkpad", "legion")),
        ("asus", ("asus", "에이수스", "rog", "tuf", "zenbook")),
        ("hp", ("hp", "에이치피", "omen")),
        ("dell", ("dell", "델", "xps", "alienware")),
    )
    for canonical, names in aliases:
        if any(name in text for name in names):
            return canonical
    return None


def _detect_cpu(text: str) -> str | None:
    m = re.search(r"\b(i[3579])(?:[- ]?\d{4,5}[a-z]{0,3})?\b", text, re.I)
    if m:
        return m.group(1).lower()
    m = re.search(r"\b(ryzen\s?[3579])\b", text, re.I)
    if m:
        return re.sub(r"\s+", "", m.group(1).lower())
    return None


def _detect_model_code(text: str) -> str | None:
    # Prefer mixed alpha-numeric manufacturer model codes like 16Z90R,
    # RF85C90D1AP, OLED65C3. Ignore pure specs such as 512GB or 875L.
    for token in re.findall(r"\b(?:[a-z]{1,8}\d{2,5}[a-z0-9]{0,8}|\d{2}[a-z]\d{2}[a-z0-9]{0,4})\b", text, re.I):
        lowered = token.lower()
        if lowered.endswith(("gb", "tb")) or lowered.endswith("l"):
            continue
        if lowered.startswith(("iphone", "galaxy")):
            continue
        return lowered
    return None
