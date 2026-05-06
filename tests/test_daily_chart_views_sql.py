from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _migration_sql() -> str:
    return (ROOT / "sql" / "migration_015_daily_chart_views.sql").read_text()


def test_daily_chart_views_dedupe_same_day_product_snapshots() -> None:
    sql = _migration_sql()

    assert "create or replace view product_market_daily_stats" in sql
    assert "distinct on (h.product_id" in sql
    assert "Asia/Seoul" in sql
    assert "h.captured_at desc" in sql


def test_category_chart_view_rolls_up_product_daily_view() -> None:
    sql = _migration_sql()

    assert "create or replace view category_market_daily_stats" in sql
    assert "select * from product_market_daily_stats" in sql
    assert "percentile_cont(0.5)" in sql
    assert "group by chart_date, category" in sql


def test_baseline_schema_includes_chart_read_models() -> None:
    sql = (ROOT / "sql" / "schema.sql").read_text()

    assert "create table if not exists product_market_stats_history" in sql
    assert "create or replace view product_market_daily_stats" in sql
    assert "create or replace view category_market_daily_stats" in sql
