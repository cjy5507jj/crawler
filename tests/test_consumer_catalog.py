from src.domains.consumer.catalog import build_seed_payloads, query_seeds_for_category


def test_build_seed_payloads_contains_domain_specs_and_canonical_key() -> None:
    rows = build_seed_payloads()
    iphone = next(r for r in rows if r["source_id"] == "iphone-15-pro-256")

    assert iphone["domain"] == "phone"
    assert iphone["category"] == "iphone"
    assert iphone["canonical_key"] == "phone:apple:iphone-15-pro:256gb"
    assert iphone["specs"]["storage_gb"] == 256


def test_query_seeds_for_consumer_categories() -> None:
    assert "아이폰 15 프로 256GB" in query_seeds_for_category("iphone")
    assert "아이폰 15 프로 512GB" in query_seeds_for_category("iphone")
    assert "갤럭시 S24 울트라 512GB" in query_seeds_for_category("galaxy")
    assert "갤럭시 S24 울트라 1TB" in query_seeds_for_category("galaxy")
    assert "맥북프로 14 M3 Pro 18GB 512GB" in query_seeds_for_category("macbook")


def test_build_seed_payloads_has_capacity_variants_as_separate_products() -> None:
    rows = build_seed_payloads()
    keys = {r["canonical_key"] for r in rows}

    assert "phone:apple:iphone-15-pro:128gb" in keys
    assert "phone:apple:iphone-15-pro:256gb" in keys
    assert "phone:apple:iphone-15-pro:512gb" in keys
    assert "phone:samsung:galaxy-s24-ultra:256gb" in keys
    assert "phone:samsung:galaxy-s24-ultra:512gb" in keys
    assert "phone:samsung:galaxy-s24-ultra:1024gb" in keys
    assert "macbook:pro:14:m3-pro:18gb:512gb" in keys
    assert "macbook:pro:14:m3-pro:18gb:1024gb" in keys
