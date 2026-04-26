"""Brand/model normalization for matching used listings to Danawa products."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


# Order matters: board partners / SI brands come BEFORE chip vendors so a
# listing like "ASUS RTX 4070" resolves to ASUS (the seller) rather than
# Nvidia (the chip vendor). Korean importers/distributors come last so they
# only win when no upstream OEM is identified.
BRAND_ALIASES: dict[str, tuple[str, ...]] = {
    # GPU / Mainboard OEMs
    "asus": ("asus", "에이수스", "rog", "tuf", "proart", "strix"),
    "msi": ("msi", "엠에스아이", "ventus", "벤투스"),
    "gigabyte": ("gigabyte", "기가바이트", "aorus", "eagle"),
    "asrock": ("asrock", "애즈락", "에즈락", "에즈윈"),
    "powercolor": ("powercolor", "파워컬러"),
    "sapphire": ("sapphire", "사파이어"),
    "zotac": ("zotac", "조탁"),
    "palit": ("palit", "팔릿"),
    "gainward": ("gainward", "게인워드"),
    "inno3d": ("inno3d",),
    "evga": ("evga",),
    "xfx": ("xfx",),
    "manli": ("manli", "만리"),
    "biostar": ("biostar", "바이오스타"),
    # RAM
    "corsair": ("corsair", "커세어"),
    "gskill": ("g.skill", "g skill", "지스킬"),
    "kingston": ("kingston", "킹스톤", "hyperx"),
    "teamgroup": ("teamgroup", "team group", "팀그룹"),
    "klevv": ("klevv", "클레브"),
    # Storage
    "samsung": ("samsung", "삼성", "갤럭시"),
    "skhynix": ("sk hynix", "sk하이닉스", "하이닉스", "솔리다임"),
    "micron": ("micron", "마이크론", "crucial"),
    "wd": ("wd", "western digital", "웨스턴디지털"),
    "seagate": ("seagate", "시게이트"),
    "kioxia": ("kioxia",),
    "sandisk": ("sandisk", "샌디스크"),
    # PSU
    "seasonic": ("seasonic", "시소닉"),
    "fsp": ("fsp",),
    "superflower": ("super flower", "superflower", "슈퍼플라워"),
    "antec": ("antec", "안텍"),
    # Cooler
    "noctua": ("noctua", "녹투아"),
    "deepcool": ("deepcool", "딥쿨"),
    "thermalright": ("thermalright", "써멀라이트"),
    "arctic": ("arctic", "아틱"),
    "nzxt": ("nzxt",),
    # Case
    "fractal": ("fractal", "프렉탈"),
    "lianli": ("lian li", "lian-li", "리안리"),
    "phanteks": ("phanteks", "팬텍스"),
    "bequiet": ("be quiet", "bequiet", "비콰이엇"),
    # Monitor / display OEMs
    "lg": ("lg", "엘지", "lg전자"),
    "dell": ("dell", "델", "alienware", "에일리언웨어"),
    "benq": ("benq", "벤큐", "zowie"),
    "aoc": ("aoc",),
    "viewsonic": ("viewsonic", "뷰소닉"),
    "philips": ("philips", "필립스"),
    "acer": ("acer", "에이서", "predator"),
    "hp": ("hp", "에이치피", "omen"),
    # Apple — covers Studio Display, MacBook, iMac, Mac mini, Mac Studio, Mac Pro
    "apple": ("apple", "애플", "맥북", "macbook", "imac", "아이맥",
              "mac mini", "맥미니", "mac studio", "맥스튜디오",
              "mac pro", "맥프로", "studio display", "스튜디오 디스플레이",
              "pro display"),
    # Korean importers / distributors (used as brand only when no OEM matched)
    "iemtek": ("이엠텍",),
    "pcdirect": ("피씨디렉트",),
    "jcheyon": ("제이씨현",),
    "daewoocts": ("대원씨티에스", "대원"),
    "stcom": ("stcom",),
    # Chip vendors last
    "amd": ("amd", "라이젠", "ryzen", "에이엠디"),
    "intel": ("intel", "인텔", "코어 울트라", "core ultra", "i3-", "i5-", "i7-", "i9-"),
    "nvidia": ("nvidia", "엔비디아", "geforce", "rtx", "gtx", "지포스"),
}

# Tokens that indicate the listing should be skipped entirely.
# Includes:
#  - buy-side posts (삽니다 / 구합니다 / 구함)
#  - swap/broken (교환, 고장, 부품용)
#  - whole-PC sales bundling many parts (본체, 데스크탑, PC, 시스템, 세트, 일괄)
#    These mention CPU/GPU model names in the title but the price reflects the
#    entire PC, which would skew per-part stats.
EXCLUDED_LISTING_KEYWORDS = (
    "삽니다",
    "구합니다",
    "구해요",
    "구함",
    "교환",
    "고장",
    "부품용",
    "본체",
    "완본체",
    "세트일괄",
    "사기",
    "데스크탑",
    "데스크톱",
    "조립pc",
    "조립 pc",
    "게이밍pc",
    "게이밍 pc",
    "게이밍컴퓨터",
    "게이밍 컴퓨터",
    "게이밍노트북",
    "게이밍 노트북",
    "노트북",
    "일괄",
    "풀세트",
    "올인원",
)

# Tokens stripped from the model string but do not invalidate the listing.
NOISE_TOKENS = {
    "정품",
    "박스",
    "택포",
    "직거래",
    "상태",
    "급처",
    "급매",
    "새제품",
    "미개봉",
    "신품",
    "쿨러",
    "팝니다",
}

# Per-category model regexes. Matches contribute "category model" tokens
# weighted higher in the matcher.
CATEGORY_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "cpu": (
        re.compile(r"\b(i[3579]-?\d{4,5}[a-z]{0,3})\b", re.I),                  # i7-14700K
        re.compile(r"\b(\d{4,5}(?:[xkfgst][a-z0-9]{0,3})?)\b", re.I),           # 5600X, 7800X3D
        re.compile(r"\b(ryzen\s?[3579]\s?\d{3,5}[a-z0-9]{0,3})\b", re.I),       # ryzen 5 5600
        re.compile(r"\b(core\s?ultra\s?[3579]\s?\d{3})\b", re.I),
    ),
    "gpu": (
        re.compile(r"\b(rtx\s?\d{4}\s?(?:ti|super)?)\b", re.I),         # RTX 4070 Ti
        re.compile(r"\b(gtx\s?\d{3,4}\s?(?:ti|super)?)\b", re.I),
        re.compile(r"\b(rx\s?\d{3,4}\s?(?:xt|gre)?)\b", re.I),          # RX 7800 XT
        re.compile(r"\b(arc\s?[ab]\d{3})\b", re.I),
    ),
    "ram": (
        re.compile(r"\b(ddr[345])\b", re.I),
        re.compile(r"\b(\d{4,5})\s?mhz\b", re.I),                       # 6000MHz
        re.compile(r"\b(\d{1,3})gb\b", re.I),                           # 32GB
        re.compile(r"\b(\d{1,3}gb\s?x\s?\d)\b", re.I),                  # 16GB x 2
    ),
    "ssd": (
        re.compile(r"\b(\d{1,4}(?:tb|gb))\b", re.I),
        re.compile(r"\b(nvme|sata|m\.2|pcie\s?[345]\.0?)\b", re.I),
        re.compile(r"\b(\d{3,4}\s?evo|pro|qvo)\b", re.I),               # 990 PRO, 980 EVO
    ),
    "hdd": (
        re.compile(r"\b(\d{1,2}tb)\b", re.I),
        re.compile(r"\b(\d{4}rpm)\b", re.I),
    ),
    "mainboard": (
        re.compile(r"\b([abxz]\d{3}[a-z]{0,3})\b", re.I),               # B650M, X670E
        re.compile(r"\b(am[45])\b", re.I),
        re.compile(r"\b(lga\s?\d{4})\b", re.I),
    ),
    "psu": (
        re.compile(r"\b(\d{3,4})w\b", re.I),
        re.compile(r"\b(80\s?plus\s?(?:bronze|silver|gold|platinum|titanium))\b", re.I),
    ),
    "case": (),
    "cooler": (
        re.compile(r"\b(nh-[duUL]\d+[a-z]*)\b", re.I),                  # NH-D15
        re.compile(r"\b(\d{3}mm)\b", re.I),
    ),
    "monitor": (
        re.compile(r"\b(\d{2}(?:\.\d)?)\s?(?:인치|in|\")", re.I),         # 27인치, 32"
        re.compile(r"\b(4k|uhd|qhd|fhd|wqhd|2k|5k|8k)\b", re.I),         # 해상도
        re.compile(r"\b(\d{3,4})\s?[xX×]\s?(\d{3,4})\b"),                 # 2560x1440
        re.compile(r"\b(\d{2,3})\s?hz\b", re.I),                          # 165Hz, 240Hz
        re.compile(r"\b(ips|va|tn|oled|qd-?oled|mini-?led)\b", re.I),    # 패널
    ),
}


# SKU sub-model line tokens — distinguish SAME-chip cards from different SKUs.
# Example: "MSI RTX 5070 ventus" vs "MSI RTX 5070 gaming trio" → different SKUs
# even though brand and chip match.
# Each entry can be (canonical, *aliases) — first item is the canonical name
# stored in tokens, all aliases are searched in the title.
SKU_LINE_TOKENS: dict[str, tuple[tuple[str, ...], ...]] = {
    "gpu": (
        # MSI lines
        ("ventus", "벤투스"),
        ("gaming trio", "게이밍 트리오", "게이밍트리오"),
        ("gaming x", "게이밍 x"),
        ("shadow", "쉐도우"),
        ("suprim", "슈프림"),
        # ASUS lines
        ("rog",),
        ("tuf",),
        ("prime",),
        ("dual", "듀얼"),
        ("proart",),
        ("strix",),
        ("astral",),
        # GIGABYTE / AORUS lines
        ("aorus",),
        ("eagle", "이글"),
        ("windforce", "윈드포스"),
        ("gaming oc",),
        ("elite",),
        # ZOTAC / PALIT / Gainward / EVGA / Inno3D
        ("twin edge", "트윈 엣지"),
        ("trinity",),
        ("infinity",),
        ("gamingpro",),
        ("ghost", "고스트"),
        ("jetstream",),
        ("ichill",),
        ("ftw3",),
        # Sapphire / PowerColor (AMD)
        ("nitro+", "nitro plus"),
        ("pulse",),
        ("hellhound",),
        ("red devil",),
    ),
    "mainboard": (
        ("rog",),
        ("tuf",),
        ("prime",),
        ("proart",),
        ("strix",),
        ("tomahawk", "토마호크"),
        ("mortar", "모르타르"),
        ("carbon", "카본"),
        ("mag",),
        ("mpg",),
        ("meg",),
        ("aorus",),
        ("eagle",),
        ("elite",),
        ("ultra",),
        ("steel legend", "스틸레전드"),
        ("phantom",),
        ("riptide",),
        ("pro rs",),
        ("lightning",),
        ("x3d",),
    ),
    "cooler": (
        ("nh-d15",), ("nh-d12",), ("nh-u12",), ("nh-u9",), ("nh-l12",),
        ("ag400",), ("ag500",), ("ag620",),
        ("ak400",), ("ak620",),
        ("lt360",), ("lt520",),
        ("freezer", "프리저"),
        ("liquid freezer",),
        ("h60",), ("h100",), ("h115",), ("h150",),
        ("kraken", "크라켄"),
    ),
    "case": (
        ("o11",), ("evolv",), ("core",), ("node",), ("define",),
        ("h510",), ("h7",), ("h9",), ("h6",), ("h5",),
    ),
    "psu": (
        ("rm750",), ("rm850",), ("rm1000",), ("rmx",),
        ("focus",), ("vertex",), ("prime",),
        ("leadex",),
    ),
}

# Capacity tokens — for SSD/RAM/HDD a capacity mismatch means a totally
# different SKU (1TB SSD ≠ 2TB SSD, 16GB RAM ≠ 32GB RAM).
_CAPACITY_RE = re.compile(r"\b(\d{1,4})\s?(tb|gb)\b", re.I)
_RAM_KIT_RE = re.compile(r"\b(\d{1,2})gb\s?[x×]\s?(\d)\b", re.I)


@dataclass
class NormalizedProduct:
    category: str
    original_name: str
    brand: str | None
    model_name: str
    normalized_name: str
    tokens: list[str]
    category_tokens: list[str] = field(default_factory=list)
    sku_line_tokens: list[str] = field(default_factory=list)
    capacity_tokens: list[str] = field(default_factory=list)


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def normalize_text(value: str) -> str:
    text = normalize_whitespace(value).lower()
    text = re.sub(r"[\[\](){},/]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def detect_brand(name: str) -> str | None:
    lowered = normalize_text(name)
    # Vocab module gives DB-loaded entries (auto-discovered + seeded) when
    # available; falls back to BRAND_ALIASES otherwise. Iteration order
    # preserves seeded order: OEMs first, importers last, chip vendors last.
    from src.normalization import vocab

    for canonical, aliases in vocab.brand_aliases():
        if any(alias in lowered for alias in aliases):
            return canonical
    return None


def tokenize_model(name: str) -> list[str]:
    lowered = normalize_text(name)
    chunks = re.split(r"[^a-z0-9.]+", lowered)
    return [c for c in chunks if c and c not in NOISE_TOKENS and len(c) >= 2]


def extract_category_tokens(category: str, name: str) -> list[str]:
    """Return strong identifying tokens for a category (e.g. CPU SKU like 5600X)."""
    patterns = CATEGORY_PATTERNS.get(category.lower(), ())
    if not patterns:
        return []
    found: list[str] = []
    for pat in patterns:
        for match in pat.findall(name):
            value = match if isinstance(match, str) else match[0]
            value = re.sub(r"\s+", "", value).lower()
            if value and value not in found:
                found.append(value)
    return found


def is_excluded_listing(title: str) -> bool:
    lowered = title.lower()
    if any(kw in lowered for kw in EXCLUDED_LISTING_KEYWORDS):
        return True
    if is_multi_component_bundle(title):
        return True
    return False


# Accessory tokens (부속품) — Danawa product names that contain these describe
# converters/cables/brackets/etc. rather than the part itself. Flagged on the
# products table via `is_accessory` so aggregate stats can exclude them.
ACCESSORY_TOKENS: tuple[str, ...] = (
    "컨버터", "젠더", "케이블", "브라켓", "허브", "독", "홀더",
    "스탠드", "어댑터", "슬리브", "캐디", "마운트", "클립", "고정대",
)


def is_accessory_product(name: str) -> bool:
    """Return True when a Danawa product name describes an accessory
    (e.g. M.2-to-SATA converter) rather than the part itself."""
    if not name:
        return False
    lowered = name.lower()
    return any(tok in lowered for tok in ACCESSORY_TOKENS)


# Tokens that, when combined with cross-category model tokens, indicate the
# listing is a complete PC (or laptop) rather than a single component.
_BUNDLE_HINTS = (
    "pc",
    "컴퓨터",
    "본체",
    "풀셋",
    "풀세트",
    "감성",
    "오멘",
    "리전",
    "갤럭시북",
    "에일리언웨어",
    "레노버",
    "alienware",
    "legion",
    "omen",
)

# Lightweight category-anchor patterns used ONLY to detect multi-component
# listings (separate from the canonical CATEGORY_PATTERNS used for matching).
_BUNDLE_ANCHORS: dict[str, re.Pattern[str]] = {
    "cpu": re.compile(
        r"\b("
        r"i[3579]-?\d{4,5}[a-z]{0,3}|"           # i7-14700K
        r"\d{4,5}[xkfgst][a-z0-9]{0,3}|"          # 5600X, 7800X3D
        r"ryzen\s?[3579]\s?\d{3,5}[a-z0-9]{0,3}"  # ryzen 5 5600
        r")\b",
        re.I,
    ),
    "gpu": re.compile(
        r"\b("
        r"rtx\s?\d{4}\s?(?:ti|super)?|"
        r"gtx\s?\d{3,4}\s?(?:ti|super)?|"
        r"rx\s?\d{3,4}\s?(?:xt|gre)?"
        r")\b",
        re.I,
    ),
    "mainboard": re.compile(
        r"\b([abxz]\d{3}[a-z]{0,3})\b",          # B650M, X670E
        re.I,
    ),
}


def is_multi_component_bundle(title: str) -> bool:
    """Return True if the title looks like a full PC / laptop sale.

    Heuristic: TWO+ different part categories are mentioned (CPU + GPU,
    CPU + MB, GPU + MB), OR a single component is paired with a "bundle
    hint" word (PC, 컴퓨터, 본체, 풀셋, laptop product names).
    """
    lowered = title.lower()
    hits = sum(1 for pat in _BUNDLE_ANCHORS.values() if pat.search(title))
    has_hint = any(h in lowered for h in _BUNDLE_HINTS)
    if hits >= 2:
        return True
    if hits >= 1 and has_hint:
        return True
    return False


def extract_sku_line_tokens(category: str, name: str) -> list[str]:
    """Sub-model line tokens (e.g. 'ventus', 'gaming trio', 'eagle').

    Vocabulary is loaded dynamically from the `sku_lines` table at first use
    (with hardcoded SKU_LINE_TOKENS as cold-start fallback).
    """
    from src.normalization import vocab

    entries = vocab.sku_line_aliases(category)
    if not entries:
        return []
    lowered = normalize_text(name)
    found: list[str] = []
    for canonical, aliases in entries:
        if canonical in found:
            continue
        for alias in aliases:
            if alias in lowered:
                found.append(canonical)
                break
    return found


def extract_capacity_tokens(category: str, name: str) -> list[str]:
    """Capacity tokens (e.g. '1tb', '16gb', '32gb x 2'). Empty when irrelevant."""
    if category.lower() not in {"ssd", "ram", "hdd"}:
        return []
    found: list[str] = []
    for m in _CAPACITY_RE.finditer(name):
        size, unit = m.group(1), m.group(2).lower()
        # normalize: 1024gb → 1tb? Skip — sites use raw values.
        token = f"{size}{unit}"
        if token not in found:
            found.append(token)
    # RAM kit: "16GB x 2" expands to "16gbx2"
    for m in _RAM_KIT_RE.finditer(name):
        token = f"{m.group(1)}gbx{m.group(2)}"
        if token not in found:
            found.append(token)
    return found


def normalize_product_name(category: str, name: str) -> NormalizedProduct:
    brand = detect_brand(name)
    tokens = tokenize_model(name)
    category_tokens = extract_category_tokens(category, name)
    sku_line_tokens = extract_sku_line_tokens(category, name)
    capacity_tokens = extract_capacity_tokens(category, name)
    normalized_name = " ".join(tokens)
    model_name = " ".join(category_tokens) if category_tokens else normalized_name
    return NormalizedProduct(
        category=category,
        original_name=name,
        brand=brand,
        model_name=model_name,
        normalized_name=normalized_name,
        tokens=tokens,
        category_tokens=category_tokens,
        sku_line_tokens=sku_line_tokens,
        capacity_tokens=capacity_tokens,
    )
