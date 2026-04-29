from src.normalization.catalog import (
    detect_brand,
    detect_chipset,
    extract_category_tokens,
    is_accessory_product,
    is_excluded_listing,
    normalize_product_name,
    tokenize_model,
)


def test_detect_brand_korean_alias() -> None:
    # CPU brand legitimately resolves to chip vendor (intel / amd) — chip
    # vendor suppression only applies to GPU listings.
    assert detect_brand("AMD 라이젠5 5600X CPU") == "amd"
    assert detect_brand("인텔 코어 울트라7 270K") == "intel"
    assert detect_brand("ASUS ROG Strix RTX 4070") == "asus"


def test_detect_brand_gpu_skips_chip_vendors() -> None:
    # GPU category: chip vendor must NOT collapse into brand — that was the
    # 763-row "nvidia" bug. AIB partner is preserved when present.
    assert detect_brand("ASUS ROG Strix RTX 4070", category="gpu") == "asus"
    assert detect_brand("MSI 지포스 RTX 5070 ventus", category="gpu") == "msi"
    assert detect_brand("기가바이트 라데온 RX 7800 XT", category="gpu") == "gigabyte"
    # Listings without an AIB token must surface as brand=None instead of
    # "nvidia"/"amd".
    assert detect_brand("지포스 RTX 4070 신품", category="gpu") is None
    assert detect_brand("라데온 RX 7800 XT", category="gpu") is None


def test_detect_chipset_extracts_chip_vendor() -> None:
    assert detect_chipset("ASUS ROG Strix RTX 4070") == "nvidia"
    assert detect_chipset("MSI 지포스 RTX 5070 ventus") == "nvidia"
    assert detect_chipset("기가바이트 라데온 RX 7800 XT") == "amd"
    assert detect_chipset("AMD 라이젠5 5600X") == "amd"
    assert detect_chipset("인텔 코어 울트라7 270K") == "intel"
    assert detect_chipset("그냥 잡다한 부품") is None


def test_normalize_gpu_separates_brand_and_chipset() -> None:
    # Card 1 + Crawler-A: an AIB GPU listing must record brand=AIB and
    # chipset=chip vendor in two distinct fields.
    norm = normalize_product_name("gpu", "ASUS ROG Strix GeForce RTX 4070 OC")
    assert norm.brand == "asus"
    assert norm.chipset == "nvidia"

    norm = normalize_product_name("gpu", "ZOTAC GAMING 지포스 RTX 5070 트윈 엣지")
    assert norm.brand == "zotac"
    assert norm.chipset == "nvidia"

    # Listing without AIB token on a GPU: brand=None (chip-vendor bleed
    # blocked), chipset still captured.
    norm = normalize_product_name("gpu", "지포스 RTX 4070 신품 미개봉")
    assert norm.brand is None
    assert norm.chipset == "nvidia"


def test_detect_brand_returns_none_when_unknown() -> None:
    assert detect_brand("그냥 잡다한 부품") is None


def test_tokenize_model_drops_noise() -> None:
    tokens = tokenize_model("[정품] AMD 라이젠5 5600X 박스 (택포)")
    assert "정품" not in tokens
    assert "박스" not in tokens
    assert "택포" not in tokens
    assert "5600x" in tokens


def test_extract_category_tokens_cpu() -> None:
    assert "5600x" in extract_category_tokens("cpu", "AMD 라이젠 5600X")
    assert "7800x3d" in extract_category_tokens("cpu", "라이젠7 7800X3D 정품")
    assert "i7-14700k" in extract_category_tokens("cpu", "인텔 i7-14700K")


def test_extract_category_tokens_gpu() -> None:
    # GPU suffix alternation must keep the longest match. RTX 4070 Ti SUPER
    # and RTX 4070 Ti are different SKUs and must produce different tokens.
    assert "rtx4070ti" in extract_category_tokens("gpu", "ASUS ROG RTX 4070 Ti")
    assert "rtx4070tisuper" in extract_category_tokens("gpu", "MSI RTX 4070 Ti SUPER")
    assert "rtx5070super" in extract_category_tokens("gpu", "이엠텍 RTX 5070 SUPER")
    assert "rtx4070" in extract_category_tokens("gpu", "기가바이트 RTX 4070")
    # AMD: XTX must outrank XT, GRE included.
    assert "rx7900xtx" in extract_category_tokens("gpu", "사파이어 RX 7900 XTX")
    assert "rx7900xt" in extract_category_tokens("gpu", "MSI RX 7900 XT")
    assert "rx7900gre" in extract_category_tokens("gpu", "ASRock RX 7900 GRE")


def test_extract_category_tokens_ssd() -> None:
    # SSD alternation regression: pre-fix bug collapsed '990 PRO' to 'pro' alone
    # because alternation parsed as `(\d{3,4}\s?evo)|(pro)|(qvo)`.
    # Now the digit prefix is mandatory (non-capturing inner alternation).
    assert "990pro" in extract_category_tokens("ssd", "삼성 990 PRO 1TB")
    assert "980pro" in extract_category_tokens("ssd", "Samsung 980 Pro NVMe 2TB")
    assert "980evo" in extract_category_tokens("ssd", "삼성 980 EVO 500GB")
    assert "870qvo" in extract_category_tokens("ssd", "삼성 870 QVO 4TB SATA")
    # Bare 'PRO' / 'EVO' without a digit prefix must NOT match.
    bare = extract_category_tokens("ssd", "Crucial PRO M.2 SSD")
    assert not any(t in bare for t in ("pro", "evo", "qvo"))


def test_extract_category_tokens_mainboard() -> None:
    assert any(
        t.startswith("b650") for t in extract_category_tokens("mainboard", "ASUS B650M-A")
    )


def test_is_excluded_listing() -> None:
    assert is_excluded_listing("RTX 4070 삽니다")
    assert is_excluded_listing("부품용 본체")
    assert not is_excluded_listing("MSI RTX 4070 정품 팝니다")


def test_excludes_full_pc_bundles() -> None:
    """Listings mentioning ≥2 part categories are clearly full PCs."""
    assert is_excluded_listing("라이젠 9800X3D RTX5070TI 감성PC 팝니다")  # CPU+GPU
    assert is_excluded_listing("9800X3D & RTX5080 풀셋")
    assert is_excluded_listing("i7 14700k RTX5070 컴퓨터")
    assert is_excluded_listing("9800x3d + b850m 박격포 wifi")  # CPU+MB
    assert is_excluded_listing("RTX5080 + B650M 메인보드 같이")  # GPU+MB


def test_excludes_laptop_bundles() -> None:
    assert is_excluded_listing("HP 오멘16 라이젠9 RTX5070 노트북")
    assert is_excluded_listing("레노버 LEGION PRO 9I RTX5080 32램")
    assert is_excluded_listing("에일리언웨어 16X RTX5060")


def test_keeps_single_component_listings() -> None:
    assert not is_excluded_listing("MSI 지포스 RTX 5070 게이밍 트리오 미개봉")
    assert not is_excluded_listing("AMD 라이젠5 5600X 정품")
    assert not is_excluded_listing("기가바이트 RTX 4070 Eagle OC 12G")


def test_normalize_product_name_full() -> None:
    norm = normalize_product_name("cpu", "AMD 라이젠5-5세대 5600X (정품)")
    # CPU keeps brand=amd (chip vendor IS the brand for CPUs); chipset
    # mirrors brand for the dedicated chipset column.
    assert norm.brand == "amd"
    assert norm.chipset == "amd"
    assert "5600x" in norm.tokens
    assert "5600x" in norm.category_tokens


def test_is_accessory_product() -> None:
    # Clear accessories
    assert is_accessory_product("M.2 SSD to SATA 컨버터")
    assert is_accessory_product("USB 3.0 허브 4포트")
    assert is_accessory_product("CPU 쿨러 RGB 케이블")  # 케이블 token wins
    assert is_accessory_product("DP to HDMI 젠더")
    # Real parts
    assert not is_accessory_product("삼성 990 PRO 1TB")
    assert not is_accessory_product("AMD 라이젠5 5600X")
    # Edge case
    assert not is_accessory_product("")


def test_detect_brand_apple() -> None:
    assert detect_brand("Apple MacBook Pro 14인치 M4") == "apple"
    assert detect_brand("애플 아이맥 24인치") == "apple"
    assert detect_brand("Apple Studio Display 스탠드형") == "apple"
    assert detect_brand("맥미니 M2 8GB") == "apple"


def test_detect_brand_monitor_oems() -> None:
    assert detect_brand("LG 울트라기어 27GR75Q") == "lg"
    assert detect_brand("Dell Alienware AW3423DWF") == "dell"
    assert detect_brand("BenQ ZOWIE XL2566K") == "benq"


def test_extract_category_tokens_monitor() -> None:
    tokens = extract_category_tokens("monitor", "LG 울트라기어 27인치 QHD 165Hz IPS")
    # 27 + qhd + 165 + ips
    assert "27" in tokens
    assert "qhd" in tokens
    assert "165" in tokens
    assert "ips" in tokens

    tokens = extract_category_tokens("monitor", "삼성 오디세이 32\" 2560x1440 240Hz OLED")
    assert "32" in tokens
    assert "240" in tokens
    assert "oled" in tokens
    # resolution pair captures (2560, 1440) — first capture stored
    assert any("2560" in t or "1440" in t for t in tokens)
