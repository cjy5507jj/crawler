from src.adapters.base import parse_price_int


def test_parse_price_int_handles_api_price_shapes() -> None:
    assert parse_price_int(None) is None
    assert parse_price_int("") is None
    assert parse_price_int(780000) == 780000
    assert parse_price_int("780000") == 780000
    assert parse_price_int("780,000원") == 780000
    assert parse_price_int("가격문의") is None
