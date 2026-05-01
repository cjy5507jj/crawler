from src.services.queries import _good_query, derive_queries


def test_good_query_accepts_concrete_models() -> None:
    assert _good_query("5600x")
    assert _good_query("rtx4070")
    assert _good_query("b650m")
    assert _good_query("i7-14700k")


def test_good_query_rejects_too_short_or_long() -> None:
    assert not _good_query("")
    assert not _good_query("a")
    assert not _good_query("a" * 50)


def test_good_query_rejects_non_model_words() -> None:
    assert not _good_query("amd")          # no digit
    assert not _good_query("plus")          # generic alone
    assert not _good_query("intel core")    # no digit


# ---------------------------------------------------------------------------
# derive_queries — brand+model 결합 query 생성 (Card 2 보강)
# ---------------------------------------------------------------------------

class _FakeQuery:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def select(self, _cols: str) -> "_FakeQuery":
        return self

    def eq(self, _col: str, _value: str) -> "_FakeQuery":
        return self

    def execute(self) -> "_FakeResult":
        return _FakeResult(self._rows)


class _FakeResult:
    def __init__(self, rows: list[dict]) -> None:
        self.data = rows


class _FakeDB:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def table(self, _name: str) -> _FakeQuery:
        return _FakeQuery(self._rows)


def test_derive_queries_emits_brand_combined_for_search_sources() -> None:
    db = _FakeDB([
        {"brand": "samsung", "model_name": "27 ips qhd 165"},
        {"brand": "lg",      "model_name": "27 ips qhd 165"},
        {"brand": "asus",    "model_name": "27 ips qhd 165"},
    ])
    queries = derive_queries(db, category="monitor", limit=10)
    # Plain model bubbles up first (3 hits across brands).
    assert queries[0] == "27 ips qhd 165"
    # Each brand+model combined query is also emitted exactly once.
    assert "samsung 27 ips qhd 165" in queries
    assert "lg 27 ips qhd 165" in queries
    assert "asus 27 ips qhd 165" in queries


def test_derive_queries_skips_redundant_brand_prefix() -> None:
    # If model_name already starts with the brand, don't emit a duplicate
    # "asus asus ..." combined query.
    db = _FakeDB([
        {"brand": "asus", "model_name": "asus rog 4070 ti"},
    ])
    queries = derive_queries(db, category="gpu", limit=10)
    assert queries == ["asus rog 4070 ti"]


def test_derive_queries_drops_combined_when_too_long() -> None:
    # 30-char cap (_TOO_LONG) — the combined string is rejected, plain stays.
    long_model = "rtx 4070 ti super" + " padding"  # 25 chars
    long_brand = "very-long-brand-name"            # 20 chars; combined = 46
    db = _FakeDB([{"brand": long_brand, "model_name": long_model}])
    queries = derive_queries(db, category="gpu", limit=10)
    assert long_model in queries
    assert all(not q.startswith(long_brand) for q in queries)


# ---------------------------------------------------------------------------
# Cold-spot seed queries (Day 1/Day 2 — case/psu/cooler/hdd 보강)
# ---------------------------------------------------------------------------


def test_derive_queries_prepends_cold_spot_seed_for_case() -> None:
    db = _FakeDB([{"brand": "darkflash", "model_name": "dlx21"}])
    queries = derive_queries(db, category="case", limit=10)
    # Seed must come before model-derived queries.
    assert queries[0] == "미들타워 케이스"
    assert "ATX 케이스" in queries
    assert "강화유리 케이스" in queries
    assert "큐브 케이스" in queries
    # Model-derived query still present after the seed block.
    assert "dlx21" in queries


def test_derive_queries_prepends_cold_spot_seed_for_psu() -> None:
    db = _FakeDB([])  # no products → only seed comes back
    queries = derive_queries(db, category="psu", limit=10)
    assert queries[:4] == ["850W 골드", "750W 모듈러", "1000W 플래티넘", "850W 파워"]


def test_derive_queries_seed_is_guaranteed_under_small_limit() -> None:
    # Even with limit=2, the first 2 seed entries must survive — model-derived
    # queries must NOT push the cold-spot seed out of the result.
    db = _FakeDB([
        {"brand": "noctua", "model_name": "nh-d15 v2"},
        {"brand": "deepcool", "model_name": "ak620 ws"},
    ])
    queries = derive_queries(db, category="cooler", limit=2)
    assert queries == ["공랭쿨러", "AIO 240"]


def test_derive_queries_no_seed_for_non_cold_spot_category() -> None:
    db = _FakeDB([{"brand": "amd", "model_name": "ryzen 5 5600x"}])
    queries = derive_queries(db, category="cpu", limit=5)
    # CPU is not a cold-spot category — no seed prepended.
    assert "공랭쿨러" not in queries
    assert "850W 골드" not in queries
    assert "ryzen 5 5600x" in queries


def test_derive_queries_prepends_consumer_seed_for_iphone() -> None:
    db = _FakeDB([])
    queries = derive_queries(db, category="iphone", limit=3)
    assert queries == ["아이폰 15 프로 256GB", "아이폰 15 프로 512GB", "아이폰 15 프로맥스 256GB"]


def test_derive_queries_seed_dedupes_against_model_match() -> None:
    # If a product happens to have model_name "WD 4TB", it shouldn't appear twice.
    db = _FakeDB([
        {"brand": "wd", "model_name": "WD 4TB"},
        {"brand": "wd", "model_name": "WD 4TB"},
    ])
    queries = derive_queries(db, category="hdd", limit=10)
    assert queries.count("WD 4TB") == 1
