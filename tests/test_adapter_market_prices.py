from src.adapters.cetizen_price import parse_price_table
from src.adapters.joongna_price import parse_search_price
from src.adapters.usedking_iphone import parse_iphone_table


def test_joongna_price_parses_aggregate_and_samples() -> None:
    html = """
    <main>
      <h1>아이폰15 시세조회</h1>
      <p>평균 시세 650,000원 최저 580,000원 최고 720,000원</p>
      <a href="/product/123">아이폰15 128GB 블랙 610,000원</a>
    </main>
    """

    observations = parse_search_price(html, keyword="아이폰15", url="https://web.joongna.com/search-price/아이폰15")

    assert observations[0].source == "joongna_price"
    assert observations[0].price_type == "aggregate"
    assert observations[0].avg_price == 650_000
    assert observations[0].min_price == 580_000
    assert observations[0].max_price == 720_000
    assert observations[1].price_type == "listing_sample"
    assert observations[1].price == 610_000
    assert observations[1].url == "https://web.joongna.com/product/123"


def test_cetizen_price_parses_model_storage_rows() -> None:
    html = """
    <html><body>
    [w7][m12][c3][cAppleiPhone15Pro,A3102,아이폰15프로,]
    아이폰15프로
    128GB712,000
    256GB754,000
    2023-10-13
    </body></html>
    """

    observations = parse_price_table(html)

    assert len(observations) == 2
    assert observations[0].source == "cetizen_price"
    assert observations[0].model == "아이폰15프로"
    assert observations[0].storage_gb == 128
    assert observations[0].avg_price == 712_000
    assert observations[0].release_date == "2023-10-13"


def test_usedking_iphone_parses_transaction_table_and_empty_state() -> None:
    html = """
    <table>
      <tr><th>No</th><th>model</th><th>capacity</th><th>cost</th><th>subj</th><th>trade_date</th></tr>
      <tr><td>1</td><td>15PRO</td><td>1TB</td><td>900,000</td><td>아이폰15프로 1TB</td><td>2026-05-01</td></tr>
    </table>
    """

    observations = parse_iphone_table(html, model="15PRO", days="30days")

    assert len(observations) == 1
    assert observations[0].source == "usedking_iphone"
    assert observations[0].observation_id == "15PRO:1TB:900,000:아이폰15프로 1TB:2026-05-01"
    assert observations[0].storage_gb == 1024
    assert observations[0].price == 900_000
    assert observations[0].sample_window == "30days"
    assert parse_iphone_table("최근 30days 간 거래가 없습니다 !!! 16PRO") == []
