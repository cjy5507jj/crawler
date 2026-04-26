# Plan: P0 매칭 정확도 개선 번들 (2026-04-26)

## Requirements Summary

NEXT.md P0 3개 항목을 한 세션에 묶어 매칭 정확도/관측가능성을 동시 개선.
세 항목 모두 동일한 검증 경로(`run_all.py --skip-danawa` → `aggregate_stats.py` → anomaly 카운트)를 공유하므로 번들이 가장 효율적.

**Scope**: P0.3 → P0.1 → P0.2 순으로 순차 구현. P1 이상 항목은 별도 세션.
**작업량**: 4~6시간 (코드 + DDL + 검증).

## Why this scope (not P0+P1)

- **즉시 효과**: 9,753 products / 785 matched listings에 대한 visible anomaly(컨버터 매칭, DDR3-1333 4,500원) 직접 제거.
- **검증 공유**: `ratio > 1.5` 이상치 카운트가 단일 metric — 한 번의 풀 재집계로 3개 변경 동시 검증.
- **P0.3 선행이 필수**: `match_reasons`가 DB에 박혀있어야 P0.1/P0.2의 false positive/negative 판별 가능. 1시간 투자로 나머지 검증 시간 대폭 단축.
- **P1은 별 작업**: Daangn 활성화·카테고리 매핑은 coverage 작업이라 P0 클린 후 측정해야 효과 확인 가능.

## Execution Order (rationale)

| # | 항목 | 시간 | 이유 |
|---|---|---|---|
| 1 | P0.3 match_reasons jsonb | 1h | 관측가능성 인프라 — 후속 작업 검증 도구 |
| 2 | P0.1 부속품 분리 | 1.5~2h | 순수 src + DDL, 재크롤 불필요 |
| 3 | P0.2 신품가 outlier 클램핑 | 2~3h | aggregate 단계에서 처리 (재크롤 불필요) |
| 4 | 검증 + 회귀 테스트 | 30~60m | `pytest` + 풀 재집계 + anomaly 카운트 비교 |

## Implementation Steps

### Step 1 — P0.3: match_reasons 영속화 (1h)

**파일**: `sql/migration_003_match_reasons.sql` (신규), `src/services/ingest.py`

1. `sql/migration_003_match_reasons.sql` 작성:
   ```sql
   alter table used_listings
     add column if not exists match_reasons jsonb;
   create index if not exists idx_used_listings_match_reasons_gin
     on used_listings using gin (match_reasons);
   ```
2. 사용자에게 dashboard SQL editor 붙여넣기 요청 (memory: DDL 수동 적용 패턴).
3. `src/services/ingest.py`에서 `MatchResult.reasons` (현재 in-memory만 존재 — `src/services/matching.py:33`) → `used_listings.match_reasons`로 upsert payload에 포함.
4. 신규 unit test `tests/test_ingest_used.py::test_match_reasons_persisted` — fixture listing이 매칭될 때 reasons 리스트가 payload에 담기는지.

**Verification**:
```bash
.venv/bin/pytest tests/test_ingest_used.py -k match_reasons -v
.venv/bin/python -c "from dotenv import load_dotenv; load_dotenv(); import os; from supabase import create_client; c = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_KEY']); rows = c.table('used_listings').select('match_reasons').not_.is_('match_reasons', 'null').limit(5).execute().data; print(rows)"
```

### Step 2 — P0.1: 부속품(accessory) 분리 (1.5~2h)

**파일**: `src/normalization/catalog.py`, `src/services/aggregate.py`, `src/models/product.py`, `sql/migration_004_accessory_flag.sql`

1. `sql/migration_004_accessory_flag.sql`:
   ```sql
   alter table products
     add column if not exists is_accessory boolean not null default false;
   create index if not exists idx_products_is_accessory on products(is_accessory)
     where is_accessory = true;
   ```
2. `src/normalization/catalog.py` 신규 함수:
   ```python
   ACCESSORY_TOKENS = (
       "컨버터", "젠더", "케이블", "브라켓", "허브", "독", "홀더", "스탠드",
       "어댑터", "슬리브", "캐디", "마운트", "클립", "고정대",
   )
   def is_accessory_product(name: str) -> bool: ...
   ```
3. `src/services/ingest.py::run_danawa` 또는 product upsert 지점에서 `is_accessory_product(name)` 호출 → `is_accessory` 컬럼 세팅.
4. `src/services/aggregate.py::_fetch_all_products` 쿼리에 `.eq("is_accessory", False)` 추가하여 stats 대상 제외.
5. 후행 backfill 1회: 기존 9,753 products에 대해 `is_accessory` 재계산 (`scripts/backfill_accessory.py` 또는 ad-hoc python).
6. Unit test `tests/test_normalization.py::test_is_accessory_product` — "M.2 SSD to SATA 컨버터" → True, "삼성 990 PRO 1TB" → False.

**Verification**:
```bash
.venv/bin/pytest tests/test_normalization.py -k accessory -v
# Backfill 후 카운트 확인
.venv/bin/python -c "...select('id', count='exact').eq('is_accessory', True).execute()"
```

**Acceptance**: 50~300개 products가 accessory 플래그됨. 컨버터/케이블 키워드의 명백한 매물이 stats에서 제외.

### Step 3 — P0.2: 다나와 신품가 outlier 클램핑 (2~3h)

**파일**: `src/services/aggregate.py`

**전략**: 외부 재크롤 없이 aggregate 단계에서 카테고리별 price floor 적용 — 가장 적은 범위 변경.

1. `src/services/aggregate.py` 상단에 카테고리별 price floor:
   ```python
   _NEW_PRICE_FLOORS: dict[str, int] = {
       "ram": 10_000,      # DDR3-1333 같은 4500원 케이스 차단
       "ssd": 15_000,
       "hdd": 20_000,
       "cpu": 30_000,
       "gpu": 50_000,
       "mainboard": 30_000,
       "psu": 20_000,
       "cooler": 5_000,
       "case": 10_000,
   }
   ```
2. `_fetch_latest_new_prices` 또는 `compute_stats` 진입점에서 카테고리/floor 비교 → floor 미만이면 `new_price = None` 처리하여 `used_to_new_ratio`도 None으로 떨어지게 함.
3. 또는 (대안) `_fetch_latest_new_prices`에서 7일 이상 갱신 안 된 snapshot은 무시 — 단, 현재 신품 크롤 주기 대비 너무 공격적일 수 있으니 일단 floor 우선.
4. 신규 unit test `tests/test_aggregate.py::test_new_price_floor_clamps_outlier` — DDR3 ram, new_price=4500 입력 → ratio None 출력.

**Verification**:
```bash
.venv/bin/pytest tests/test_aggregate.py -k floor -v
.venv/bin/python scripts/aggregate_stats.py
# anomaly 재카운트
.venv/bin/python /tmp/check_anomalies.py
```

**Acceptance**: `ratio > 1.5` 카운트가 베이스라인 대비 80% 이상 감소.

### Step 4 — 통합 검증 + 회귀 (30~60m)

1. **회귀**: `.venv/bin/pytest -v` — 기존 51 passing이 그대로 통과해야 함. 신규 test 3개(reasons / accessory / floor) 추가.
2. **풀 aggregate 재실행**: `.venv/bin/python scripts/aggregate_stats.py`.
3. **Anomaly 비교**: 변경 전/후 `ratio > 1.5` 카운트, accessory 매칭 카운트, 평균 감가율 변화 기록.
4. **Match reasons 샘플링**: matched listing 10개 random sample → reasons 가독성 사람 검토.
5. STATUS.md 업데이트: 변경된 평균 감가율, 새 컬럼, 새 floor table 명시.

## Acceptance Criteria

- [ ] `pytest` 51 (기존) + 3 (신규) = 54 passing.
- [ ] `used_listings.match_reasons`가 NULL이 아닌 row >= 매칭된 row의 95%.
- [ ] `products.is_accessory = TRUE` 카운트가 50~500 범위.
- [ ] `aggregate.is_accessory=True` products는 `product_market_stats`에 새 row 안 박힘 (또는 used_count=0).
- [ ] `ratio > 1.5` anomaly 카운트가 베이스라인 대비 ≥ 70% 감소.
- [ ] 카테고리별 평균 감가율(STATUS.md 표) 정상 범위 유지: cpu/gpu/ram/ssd 모두 30~120% 안에 들어옴.
- [ ] DDL 2개(`migration_003`, `migration_004`)가 Supabase dashboard에 수동 적용 완료.

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Accessory 토큰이 너무 공격적 → 정상 product 제외 | Step 2-5 backfill 직후 카테고리별 분포 출력해 사람 sanity check. 의심스러우면 토큰 reduce. |
| Price floor가 카테고리에 따라 비현실적 | 값을 코드 상수로 두고, 실제 분포(`select category, percentile_cont(0.05) within group (...) ...`)를 한 번 뽑아 조정. |
| `migration_003/004` 적용 누락 | Step 시작 시 사용자에게 명시적으로 SQL 붙여넣기 요청 + 적용 확인 쿼리 함께 제공. |
| `match_reasons` jsonb size 폭발 | reasons 리스트는 평균 3~5개로 제한적. gin index 비용은 검토 후 필요 시 drop. |

## Verification Steps (순차)

```bash
# 1. DDL 적용 확인
psql / dashboard 에서:
  select column_name from information_schema.columns
   where table_name='used_listings' and column_name='match_reasons';
  select column_name from information_schema.columns
   where table_name='products' and column_name='is_accessory';

# 2. Unit tests
.venv/bin/pytest -v

# 3. Accessory backfill (한 번)
.venv/bin/python scripts/backfill_accessory.py   # 또는 ad-hoc

# 4. Re-aggregate
.venv/bin/python scripts/aggregate_stats.py

# 5. Anomaly recount + reasons sample
.venv/bin/python /tmp/check_anomalies.py
.venv/bin/python /tmp/sample_match_reasons.py
```

## Out of Scope (다음 세션)

- P1: Daangn 본격 활성화, qb_jijang 로그인, 카테고리 자동 매핑, retry 회복력
- P2: 스케줄러, 알림, crawl_runs 로그
- P3: 시세 트렌드, 대시보드, 가격 알림
- P4: 매칭 회귀 fixture, psycopg2 자동 마이그레이션
