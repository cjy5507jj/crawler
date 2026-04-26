# Plan: P3.13 watchlist + P3.14 unknown_vocab + P4.16 discovery fixture (다음 세션)

**Scope**: 가격 알림 watchlist + unknown_vocab 검토 CLI + discovery 회귀 테스트
**작업량**: ~8h
**Entry point**: 새 세션은 `.omc/plans/2026-04-26-p3-watchlist-vocab-discovery.md 진행 검증까지`로 시작.

## Step 1 — P3.13: 가격 알림 watchlist (4h)

**파일**: `sql/migration_007_watchlists.sql`, `src/services/watchlist.py` (신규), `scripts/check_watchlist.py` (신규), `scripts/run_all.py`, `tests/test_watchlist.py`

1. `sql/migration_007_watchlists.sql`:
   ```sql
   create table if not exists watchlists (
     id uuid primary key default gen_random_uuid(),
     user_id text not null,                -- email or external user ref
     product_id uuid references products(id) on delete cascade,
     target_price integer not null,        -- alert when used_median <= this
     direction text not null default 'below',  -- 'below' | 'above'
     active boolean not null default true,
     created_at timestamptz not null default now(),
     last_alerted_at timestamptz,
     unique (user_id, product_id)
   );
   create index if not exists idx_watchlists_active on watchlists(active) where active = true;
   ```

2. `src/services/watchlist.py`:
   - `check_watchlists(db) -> list[dict]` — active watchlists 조회 + 현재 `product_market_stats.used_median`과 비교 → triggered 리스트 반환
   - `mark_alerted(db, watchlist_id) -> None` — `last_alerted_at = now()`
   - cool-down: 24h 이내 재알림 방지 (`last_alerted_at`이 24h 이내면 스킵)

3. `scripts/check_watchlist.py`:
   - argparse, dotenv, supabase 클라이언트
   - `check_watchlists(db)` 호출 → 각 트리거에 `alerts.notify(f"💰 [{user_id}] {product_name} {direction} {target_price}: 현재 {used_median}", level='alert')`
   - `mark_alerted` 호출

4. `scripts/run_all.py` 끝(aggregate 직후, anomaly 체크와 함께)에 `check_watchlists` 호출 옵션 추가. `--skip-watchlist` 플래그.

5. 테스트 `tests/test_watchlist.py`:
   - `test_check_watchlists_triggers_below_threshold`
   - `test_check_watchlists_skips_within_cooldown`
   - `test_check_watchlists_skips_inactive`
   - `test_check_watchlists_above_direction`

**Acceptance**: pytest 신규 ≥4 통과. DDL 007 적용 후 `INSERT INTO watchlists` 1행 → `check_watchlist.py` 실행 시 알림 출력.

## Step 2 — P3.14: unknown_vocab 검토 CLI (3h)

**파일**: `scripts/review_vocab.py` (신규), `tests/test_review_vocab.py`

`unknown_vocab` 테이블은 이미 migration_002로 존재. 사람이 검토 후 brand/sku_line으로 승격.

1. `scripts/review_vocab.py`:
   - argparse: `--top N` (default 20), `--category cpu|...`
   - `unknown_vocab`에서 `seen_count desc limit N` 조회 (reviewed=false만)
   - 각 토큰에 대해 인터랙티브 prompt:
     ```
     [3/20] cat=gpu  token='shadow'  seen=15
       관련 listing 샘플:
         - "MSI RTX 4070 SHADOW 정품"
         - "MSI 4070 shadow 새상품"
       [b]rand / [s]ku_line / [k]ip(skip+mark reviewed) / [d]elete / [q]uit:
     ```
   - 입력 처리:
     - b → `brands` upsert (canonical=token, aliases=[token]) + reviewed=true
     - s → `sku_lines` insert (category from current row) + reviewed=true
     - k → reviewed=true 만 set
     - d → row 삭제
     - q → 종료
   - 종료 시 처리한 카운트 출력

2. 테스트 `tests/test_review_vocab.py`:
   - 함수 분리: `_promote_to_brand(db, token)`, `_promote_to_sku_line(db, token, category)`, `_skip_token(db, token, category)`
   - 각각 fake supabase로 호출 결과 검증

**Acceptance**: `python scripts/review_vocab.py --top 5` 시 인터랙티브 작동. 단위 테스트 ≥3 통과.

## Step 3 — P4.16: discovery fixture 테스트 (1h)

**파일**: `tests/fixtures/discovery/`, `tests/test_discovery_regression.py`

기존 `tests/test_discovery.py`는 helper 함수 단위. fixture-based 회귀 테스트 추가.

1. `tests/fixtures/discovery/products_sample.json` — 가짜 product 30개 (10 brand × 3 카테고리 분포):
   ```json
   [
     {"category": "gpu", "name": "ASUS ROG RTX 5070"},
     {"category": "gpu", "name": "ASUS TUF RTX 5080"},
     ...
   ]
   ```

2. `tests/test_discovery_regression.py`:
   - `test_discover_brands_from_fixture`: fake db에 fixture 로드 → `discover_brands_from_products(db, min_doc_freq=2)` 호출 → ASUS doc_freq>=2, MSI 등 expected brands 검출 검증
   - `test_discover_sku_lines_from_fixture`: 카테고리별 sub-model n-gram 검출 검증
   - `test_auto_map_canonical_categories_fixture`: 가짜 danawa_categories rows 입력 → 매핑 결과 검증 (이미 `test_discovery.py::test_auto_map_canonical_categories` 있으면 보강)

**Acceptance**: pytest 신규 ≥3 통과.

## Step 4 — 통합 검증 (30min)

1. `pytest -v` — 모두 통과
2. DDL 007 사용자 paste 요청
3. `scripts/check_watchlist.py` smoke test
4. `scripts/review_vocab.py --top 3` 실행 가능 확인 (입력 없이 q로 종료)
5. STATUS.md v9 업데이트 (#21 watchlist / #22 vocab review / #23 discovery fixture)

## Out of Scope (다음 세션 이후)

- P1.4 Daangn 본격 활성화 (Playwright 동시성)
- P3.12 대시보드 (Next.js, 별도 repo `crawler-dashboard`)
