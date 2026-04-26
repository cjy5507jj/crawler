from src.services.queries import _good_query


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
