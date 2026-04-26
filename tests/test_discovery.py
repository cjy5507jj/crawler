"""Pure-function tests for discovery primitives."""

from src.services.discovery import (
    _first_token,
    _ngrams,
    _tokens,
    auto_map_canonical_categories,
)


def test_first_token_lowercases_and_strips() -> None:
    assert _first_token("MSI 지포스 RTX 5070") == "msi"
    assert _first_token("ASUS, ROG STRIX") == "asus"
    assert _first_token("이엠텍 지포스 RTX 5060") == "이엠텍"


def test_first_token_skips_too_short_or_generic() -> None:
    assert _first_token("") is None
    assert _first_token("PC 본체") is None  # 'pc' is in NON_BRAND_LEADING
    assert _first_token("a 키보드") is None  # 1-char


def test_tokens_drop_digit_only_and_short() -> None:
    out = _tokens("MSI 지포스 RTX 5070 게이밍 트리오 OC D7 12GB 트라이프로져4")
    # only alpha/Korean ≥ 2 chars retained, digits-prefix excluded
    assert "msi" in out
    assert "rtx" in out
    assert "지포스" in out
    assert "게이밍" in out
    assert "트리오" in out
    # digit-only/with-leading-digit should be dropped
    for tok in out:
        assert not tok[0].isdigit()


def test_ngrams_window() -> None:
    toks = ["msi", "rtx", "gaming", "trio"]
    bigrams = _ngrams(toks, 2)
    assert "msi rtx" in bigrams
    assert "rtx gaming" in bigrams
    assert "gaming trio" in bigrams
    assert len(bigrams) == 3


# --- auto_map_canonical_categories -----------------------------------------


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, table: "_Table"):
        self.table = table
        self._is_null: str | None = None
        self._eq: tuple[str, object] | None = None
        self._update: dict | None = None

    def select(self, *_cols):
        return self

    def is_(self, col, val):
        if val == "null":
            self._is_null = col
        return self

    def eq(self, col, val):
        self._eq = (col, val)
        return self

    def update(self, payload):
        self._update = payload
        return self

    def execute(self):
        if self._update is not None and self._eq is not None:
            col, val = self._eq
            for r in self.table.rows:
                if r.get(col) == val:
                    r.update(self._update)
            return _Result([])
        if self._is_null is not None:
            return _Result(
                [r for r in self.table.rows if r.get(self._is_null) is None]
            )
        return _Result(list(self.table.rows))


class _Table:
    def __init__(self):
        self.rows: list[dict] = []


class _DB:
    def __init__(self):
        self._tables: dict[str, _Table] = {}

    def table(self, name):
        if name not in self._tables:
            self._tables[name] = _Table()
        return _Query(self._tables[name])

    def rows(self, name):
        return self._tables[name].rows


def test_auto_map_canonical_categories() -> None:
    db = _DB()
    db.table("danawa_categories")  # ensure created
    db._tables["danawa_categories"].rows = [
        {"cate_id": "X", "name_ko": "AI/딥러닝 CPU", "canonical": None},
        {"cate_id": "Y", "name_ko": "RTX 50 그래픽카드", "canonical": None},
        {"cate_id": "Z", "name_ko": "DDR5 램", "canonical": None},
        {"cate_id": "W", "name_ko": "이미 매핑됨", "canonical": "cpu"},
    ]

    summary = auto_map_canonical_categories(db)

    assert summary == {
        "mapped": 3,
        "per_canonical": {"cpu": 1, "gpu": 1, "ram": 1},
    }
    by_id = {r["cate_id"]: r for r in db.rows("danawa_categories")}
    assert by_id["X"]["canonical"] == "cpu"
    assert by_id["Y"]["canonical"] == "gpu"
    assert by_id["Z"]["canonical"] == "ram"
    assert by_id["W"]["canonical"] == "cpu"
