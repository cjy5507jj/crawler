from src.adapters.base import UsedListing
from src.domains.consumer.matching import ConsumerProductCandidate, find_best_consumer_candidate
from src.domains.consumer.normalization import infer_consumer_product, normalize_consumer_product


def test_normalize_iphone_model_storage_and_carrier() -> None:
    norm = normalize_consumer_product("iphone", "아이폰 15 프로맥스 256기가 자급제 블랙")

    assert norm.domain == "phone"
    assert norm.brand == "apple"
    assert norm.model == "iphone 15 pro max"
    assert norm.storage_gb == 256
    assert norm.carrier == "unlocked"
    assert norm.canonical_key == "phone:apple:iphone-15-pro-max:256gb"


def test_normalize_iphone_korean_shorthand_battery_and_repair_flags() -> None:
    norm = normalize_consumer_product("iphone", "아이폰15프맥 1TB 자급제 배터리효율 87% 사설수리")

    assert norm.model == "iphone 15 pro max"
    assert norm.storage_gb == 1024
    assert norm.carrier == "unlocked"
    assert norm.battery_health == 87
    assert "third_party_repair" in norm.condition_flags
    assert norm.canonical_key == "phone:apple:iphone-15-pro-max:1024gb"


def test_infer_consumer_product_picks_phone_identity_without_category_hint() -> None:
    norm = infer_consumer_product("아이폰15프맥 1TB 자급제")

    assert norm is not None
    assert norm.domain == "phone"
    assert norm.category == "iphone"
    assert norm.canonical_key == "phone:apple:iphone-15-pro-max:1024gb"


def test_normalize_galaxy_model_storage_and_condition() -> None:
    norm = normalize_consumer_product("galaxy", "갤럭시 S24 울트라 512GB 액정파손")

    assert norm.domain == "phone"
    assert norm.brand == "samsung"
    assert norm.model == "galaxy s24 ultra"
    assert norm.storage_gb == 512
    assert norm.condition_flags == ["damaged_display"]


def test_normalize_galaxy_shorthand_fold_and_carrier() -> None:
    norm = normalize_consumer_product("galaxy", "S24U 512g KT 정상해지")

    assert norm.model == "galaxy s24 ultra"
    assert norm.storage_gb == 512
    assert norm.carrier == "kt"

    fold = normalize_consumer_product("galaxy", "갤럭시 폴드6 256GB 후면파손")
    assert fold.model == "galaxy zfold6"
    assert fold.storage_gb == 256
    assert "damaged_body" in fold.condition_flags
    assert "damaged_display" not in fold.condition_flags

    camera = normalize_consumer_product("galaxy", "갤럭시 S24 256GB 카메라 파손")
    assert "damaged_body" in camera.condition_flags
    assert "damaged_display" not in camera.condition_flags


def test_normalize_macbook_chip_ram_storage() -> None:
    norm = normalize_consumer_product("macbook", "맥북프로 14 M3 Pro 18GB 512GB 스페이스블랙")

    assert norm.domain == "macbook"
    assert norm.brand == "apple"
    assert norm.family == "pro"
    assert norm.screen_size == 14
    assert norm.chip == "m3 pro"
    assert norm.ram_gb == 18
    assert norm.storage_gb == 512
    assert norm.canonical_key == "macbook:pro:14:m3-pro:18gb:512gb"


def test_normalize_laptop_model_code_cpu_ram_storage() -> None:
    norm = normalize_consumer_product("laptop", "LG 그램 16Z90R i7 16GB 512GB")

    assert norm.domain == "laptop"
    assert norm.brand == "lg"
    assert norm.model_number == "16z90r"
    assert norm.cpu == "i7"
    assert norm.ram_gb == 16
    assert norm.storage_gb == 512
    assert norm.canonical_key == "laptop:lg:16z90r:i7:16gb:512gb"


def test_normalize_tv_brand_size_resolution_model_code() -> None:
    norm = normalize_consumer_product("tv", "LG OLED65C3 65인치 OLED 4K TV")

    assert norm.domain == "appliance"
    assert norm.brand == "lg"
    assert norm.model_number == "oled65c3"
    assert norm.screen_size == 65
    assert norm.panel == "oled"
    assert norm.resolution == "4k"
    assert norm.canonical_key == "appliance:tv:lg:oled65c3:65:4k"


def test_normalize_appliance_uses_model_code_when_present() -> None:
    norm = normalize_consumer_product("appliance", "삼성 비스포크 냉장고 RF85C90D1AP 875L")

    assert norm.domain == "appliance"
    assert norm.brand == "samsung"
    assert norm.model_number == "rf85c90d1ap"
    assert norm.capacity_l == 875
    assert norm.canonical_key == "appliance:appliance:samsung:rf85c90d1ap"


def test_consumer_match_requires_phone_storage_match() -> None:
    listing = UsedListing(source="bunjang", listing_id="l1", title="아이폰15 프로 256GB 자급제")
    candidates = [
        ConsumerProductCandidate(
            product_id="p-128",
            category="iphone",
            name="Apple iPhone 15 Pro 128GB",
            canonical_key="phone:apple:iphone-15-pro:128gb",
        ),
        ConsumerProductCandidate(
            product_id="p-256",
            category="iphone",
            name="Apple iPhone 15 Pro 256GB",
            canonical_key="phone:apple:iphone-15-pro:256gb",
        ),
    ]

    result = find_best_consumer_candidate(listing, candidates, category="iphone")

    assert result is not None
    assert result.is_match
    assert result.candidate.product_id == "p-256"


def test_consumer_match_rejects_macbook_air_vs_pro() -> None:
    listing = UsedListing(source="joonggonara", listing_id="l2", title="맥북에어 13 M2 8GB 256GB")
    candidates = [
        ConsumerProductCandidate(
            product_id="p-pro",
            category="macbook",
            name="MacBook Pro 13 M2 8GB 256GB",
            canonical_key="macbook:pro:13:m2:8gb:256gb",
        )
    ]

    result = find_best_consumer_candidate(listing, candidates, category="macbook")


    assert result is not None
    assert not result.is_match
    assert any(r.startswith("dq:family") for r in result.reasons)


def test_consumer_match_laptop_requires_model_code() -> None:
    listing = UsedListing(source="bunjang", listing_id="l3", title="LG 그램 16Z90R i7 16GB 512GB")
    candidates = [
        ConsumerProductCandidate(
            product_id="p-gram",
            category="laptop",
            name="LG Gram 16Z90R i7 16GB 512GB",
            canonical_key="laptop:lg:16z90r:i7:16gb:512gb",
        )
    ]

    result = find_best_consumer_candidate(listing, candidates, category="laptop")

    assert result is not None
    assert result.is_match
    assert result.candidate.product_id == "p-gram"
