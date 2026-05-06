from scripts.backfill_used_observations import build_observation_row


def test_build_observation_row_uses_kst_observed_date() -> None:
    row = build_observation_row(
        {
            "id": "used-1",
            "source": "bunjang",
            "listing_id": "L1",
            "domain": "pc_parts",
            "category": "gpu",
            "price": 100_000,
            "status": "selling",
            "matched_product_id": "p1",
            "match_score": 0.9,
            "match_reasons": ["brand:msi"],
            "parsed_specs": {"brand": "msi"},
            "crawled_at": "2026-05-05T18:10:00+00:00",
        }
    )

    assert row["observed_date"] == "2026-05-06"
    assert row["used_listing_id"] == "used-1"
    assert row["metadata"] == {"backfill": True}
    assert row["seen_count"] == 1
