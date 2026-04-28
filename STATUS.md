# STATUS.md (2026-04-26 v9)

end-to-end 파이프라인 + 동적 vocab + 시세 알고리즘 + accessory 분리 + new_price floor + tenacity retry + 카테고리 자동 매핑 + 운영 로그(crawl_runs) + 이상 감지 알림 + launchd 스케줄러 + 시세 시계열(7d/28d 트렌드) + 매칭 회귀 fixture + **가격 알림 watchlist + unknown_vocab 검토 CLI + discovery 회귀 fixture** 운영 중. 다음 개선 항목은 [`NEXT.md`](NEXT.md) 참고.

---

## 현재 운영 데이터 (실 Supabase)

| 테이블 | 카운트 | 메모 |
|---|---|---|
| products | **9,753** | 9개 카테고리 × 모든 페이지 (309는 `is_accessory=true`로 분리) |
| brands | 270 | 24 seed + 246 auto-discovered (frequency analysis) |
| sku_lines | 3,413 | TF-IDF로 카테고리별 sub-model 자동 발견 |
| danawa_categories | 125 | nav 스크랩으로 자동 |
| used_listings | 1,863 | (572 matched, 0.55 threshold; 신규 컬럼 `match_reasons` 다음 ingest부터 채워짐) |
| price_snapshots | 11,066 new + 867 used | |
| product_market_stats | 9,444 | accessory 309 제외, 199종 used 시세 (1종 floor-clamped) |

---

## 카테고리별 평균 감가율 (median ÷ new)

| 카테고리 | products | with stats | 평균 감가율 |
|---|---|---|---|
| cpu | 532 | 13 | 81% |
| gpu | 993 | 12 | 84% |
| ram | 756 | 44 | 79% |
| ssd | 1,000 | 64 | 56% |
| mainboard | 1,000 | 38 | 97% |
| psu | 1,000 | 8 | 55% |
| cooler | 1,000 | 9 | 82% |
| case | 1,000 | 3 | 50% |
| hdd | 426 | 2 | 51% |

---

## 적용된 알고리즘 스택

1. **다나와 페이지네이션**: AJAX POST `/list/ajax/getProductList.ajax.php` + physicsCate 자동 추출
2. **Brand 자동 발견**: 다나와 product 첫 토큰 frequency, 신규 제조사 즉시 인식
3. **SKU line 자동 발견**: 카테고리별 n-gram TF-IDF, category-specific token 채택
4. **Multi-component bundle 감지**: CPU+GPU / CPU+MB / GPU+MB 조합 매물 자동 제외 (조립PC false positive 방지)
5. **Accessory 분리**: 컨버터/젠더/케이블/허브/브라켓 등 14개 토큰 → `products.is_accessory=true`, aggregate에서 제외
6. **Brand / Capacity / SKU-line / Category-token mismatch DQ**: 다른 SKU 매칭 차단
7. **Sanity 필터**: median × 4 외 outlier 제거
8. **Adaptive trimmed mean**: n≥10이면 20% / n≥5이면 10% / 그 외 simple mean
9. **Median 기반 ratio**: `used_to_new_ratio = used_median / new_price`
10. **카테고리별 new_price floor**: ram 10k / ssd 15k / hdd 20k / cpu 30k / gpu 50k / mainboard 30k / psu 20k / cooler 5k / case 10k 미만이면 new_price=NULL 처리 (DDR3-1333 4500원 같은 outlier 차단)
11. **Match explainability**: `used_listings.match_reasons jsonb` — 매칭 시그널(brand/cat/sku_line/tokens) 영속화
12. **Bulk aggregate**: 9,444 active products → 3 쿼리로 집계 (페이징 + 메모리 join)
13. **Tenacity 재시도**: danawa init/page fetch + nav scrape에 exponential backoff (max 3회). 일시적 네트워크 에러 자동 회복.
14. **Canonical category 자동 매핑**: `danawa_categories` 125개 중 68개(54%)가 정규식 패턴으로 자동 매핑 (cpu/gpu/ram/ssd/hdd/mainboard/psu/case/cooler/monitor). cooler 키워드가 cpu/gpu/ram보다 우선 매칭되어 "CPU 공랭쿨러" → cooler.
15. **Quasarzone qb_jijang 옵션**: `QUASARZONE_PHPSESSID` 환경변수 설정 시 회원전용 보드도 크롤.
16. **운영 로그 (crawl_runs)**: 실행마다 `crawl_runs` 테이블에 1 row 기록 (started/finished/trigger/args/summary/status/error). post-hoc 트렌드 분석 가능.
17. **이상 감지 알림**: 직전 완료 run 대비 stats_total 50% 이상 감소 또는 with_used가 0으로 떨어지면 `SLACK_WEBHOOK_URL` / `DISCORD_WEBHOOK_URL` 또는 stdout으로 알림.
18. **launchd 스케줄러**: `ops/*.plist` 3개 (daily 03시 / Sunday 04시 Daangn / Monday 05시 vocab). cron 대안도 `ops/README.md`에 동봉.
19. **시세 시계열 + 트렌드**: `product_market_stats_history` 테이블에 매 집계마다 스냅샷 누적, `product_market_stats.trend_7d_pct/trend_28d_pct`로 7일/28일 변화율 자동 계산 (current vs ±2일 윈도우 baseline, flat threshold ±2%).
20. **매칭 회귀 fixture**: `tests/fixtures/matching_regression/cases.json` 22개 케이스 + `test_matching_regression.py` parametrized — precision/recall ≥ 0.85 회귀 가드.
21. **가격 알림 watchlist**: `watchlists` 테이블 (user_id × product_id × target_price × direction below|above) → `scripts/check_watchlist.py`가 `product_market_stats.used_median` 비교 후 Slack/Discord/stdout 알림. 24h cool-down (`last_alerted_at`). `run_all.py`에 자동 통합 (`--skip-watchlist`로 비활성).
22. **unknown_vocab 검토 CLI**: `scripts/review_vocab.py --top N [--category cpu|...]` — 미분류 토큰을 인터랙티브 prompt로 검토 (`b`rand / `s`ku_line / s`k`ip / `d`elete / `q`uit). 승격 시 `brands`/`sku_lines` 테이블 upsert + `reviewed=true`.
23. **discovery 회귀 fixture**: `tests/fixtures/discovery/products_sample.json` 27개 가짜 product → `discover_brands_from_products`/`discover_sku_lines_from_products`/`auto_map_canonical_categories` 동작 영구 가드.

---

## 구조 (파일별 역할)

```
src/
├── crawlers/danawa.py            # AJAX-based pagination, parse_products
├── adapters/                     # 5개 source (coolenjoy/quasarzone/bunjang/joonggonara/daangn)
│   ├── _browser.py               # Playwright wrapper (daangn/joonggonara)
│   └── base.py
├── normalization/
│   ├── catalog.py                # detect_brand / extract_category_tokens / is_excluded_listing / multi-component bundle
│   └── vocab.py                  # lazy-loaded DB vocab cache (brands/sku_lines)
└── services/
    ├── matching.py               # score + 4가지 DQ + threshold (0.55/0.40)
    ├── ingest.py                 # run_danawa / run_used (matching → upsert → snapshot)
    ├── aggregate.py              # batched market stats (트림드 평균 + sanity)
    ├── discovery.py              # auto vocab discovery (brands/categories/sku_lines)
    └── queries.py                # search query auto-generation from products

scripts/
├── run_danawa.py                 # 단일 카테고리 신품 크롤
├── run_used.py                   # 단일 source × 카테고리
├── run_all.py                    # 9개 × 5개 + discovery + aggregate + watchlist (오케스트레이터)
├── discover_vocab.py             # vocab만 재계산
├── aggregate_stats.py            # stats만 재계산
├── check_watchlist.py            # 가격 알림 평가 + 알림 dispatch
└── review_vocab.py               # unknown_vocab 인터랙티브 검토

sql/
├── schema.sql                    # 전체 스키마
├── migration_001_market_stats.sql
├── migration_002_vocabulary.sql
├── migration_003_match_reasons.sql
├── migration_004_accessory_flag.sql
├── migration_005_crawl_runs.sql
├── migration_006_market_stats_history.sql
└── migration_007_watchlists.sql

tests/                            # 127 passed (fixture 기반, 네트워크 미의존)
```

---

## CLI

```bash
# 전체 파이프라인 (모든 페이지, 신규 제조사 자동 발견)
python scripts/run_all.py --danawa-pages 0

# 빠른 모드 (Daangn Playwright 제외)
python scripts/run_all.py --skip-sources daangn --queries-per-search 5

# 사용중인 products로 used만 다시
python scripts/run_all.py --skip-danawa

# 단독 단계
python scripts/discover_vocab.py        # vocab 재계산
python scripts/aggregate_stats.py       # stats 재계산
python scripts/check_watchlist.py       # 가격 알림 평가 (--dry-run / --cooldown-hours N)
python scripts/review_vocab.py --top 20 # unknown_vocab 인터랙티브 검토
```

---

## 알려진 한계 (다음 라운드 대상)
[`NEXT.md`](NEXT.md) 참고.
