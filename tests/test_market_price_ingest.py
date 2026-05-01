from src.adapters.market_price import MarketPriceObservation
from src.services.ingest import upsert_market_price_observations


class _Result:
    data = []


class _Table:
    def __init__(self):
        self.rows = None
        self.on_conflict = None

    def upsert(self, rows, on_conflict=None):
        self.rows = rows
        self.on_conflict = on_conflict
        return self

    def execute(self):
        return _Result()


class _DB:
    def __init__(self):
        self.table_name = None
        self.table_obj = _Table()

    def table(self, name):
        self.table_name = name
        return self.table_obj


def test_upsert_market_price_observations_refreshes_observed_at() -> None:
    db = _DB()
    result = upsert_market_price_observations(
        db,
        [
            MarketPriceObservation(
                source="joongna_price",
                observation_id="아이폰15:aggregate",
                keyword="아이폰15",
                avg_price=650_000,
            )
        ],
    )

    assert result == {"observations": 1}
    assert db.table_name == "market_price_observations"
    assert db.table_obj.on_conflict == "source,observation_id"
    assert db.table_obj.rows[0]["observed_at"]
    assert db.table_obj.rows[0]["avg_price"] == 650_000


def test_upsert_market_price_observations_skips_empty_batch() -> None:
    db = _DB()

    result = upsert_market_price_observations(db, [])

    assert result == {"observations": 0}
    assert db.table_name is None
