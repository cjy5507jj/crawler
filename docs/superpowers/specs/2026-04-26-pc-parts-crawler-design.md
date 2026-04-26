# PC Parts Crawler — Full Build Design (2026-04-26)

## Goal
다나와를 canonical product master로 두고, 5개 중고 소스(쿨앤조이/퀘이사존/번개장터/당근/중고나라)에서 시세를 수집해 매칭한 뒤 Supabase에 저장하는 end-to-end 파이프라인을 완성한다. fixture 기반 pytest로 검증하고, 마지막에 실 Supabase에 smoke test를 돌린다.

## Non-Goals
- 실시간 알림
- UI/대시보드
- 판매완료 추론 ML
- 모든 카테고리(CPU/GPU/RAM/SSD/HDD/PSU/케이스/쿨러) 카테고리별 깊은 튜닝 — 카테고리 인식만 강화하고 튜닝은 후속 라운드

---

## Architecture

```
┌─────────────┐    ┌──────────────────┐    ┌────────────────────────────┐
│  Danawa     │ ──▶│ products         │◀───│  matching                  │
│  crawler    │    │  (canonical)     │    │  (listing → product)       │
└─────────────┘    └──────────────────┘    └────────────┬───────────────┘
                          │                              │
                          ▼                              ▼
                   price_snapshots              used_listings
                   (market_type='new')          (per source raw + match)
                                                       │
                                                       ▼
                                              price_snapshots
                                              (market_type='used')
```

### Layers
| Layer | Module | Responsibility |
|---|---|---|
| Crawl (new) | `src/crawlers/danawa.py` | Danawa 카테고리 페이지 → `RawProduct` |
| Crawl (used) | `src/adapters/<source>.py` | 5개 중고 소스 → `UsedListing` |
| Normalize | `src/normalization/catalog.py` | brand/모델 토큰 추출 (카테고리 인식) |
| Match | `src/services/matching.py` | listing↔product 점수화 + threshold |
| Persist | `src/services/ingest.py` + `clients/supabase_client.py` | products / used_listings / price_snapshots upsert |
| CLI | `scripts/run_danawa.py`, `scripts/run_used.py` | 운영 진입점 |

---

## Data Model (sql/schema.sql 재작성)

```sql
create table products (
  id uuid primary key default gen_random_uuid(),
  category text not null,
  source text not null,            -- 항상 'danawa'
  source_id text not null,         -- danawa pcode
  name text not null,
  brand text,
  model_name text,
  normalized_name text,
  url text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (source, source_id)
);

create table used_listings (
  id uuid primary key default gen_random_uuid(),
  source text not null,            -- 'coolenjoy' | 'quasarzone' | ...
  listing_id text not null,
  category text,
  title text not null,
  price integer,
  price_raw text,
  status text,                     -- 'selling' | 'reserved' | 'sold' | 'unknown'
  url text,
  matched_product_id uuid references products(id) on delete set null,
  match_score numeric,
  crawled_at timestamptz not null default now(),
  unique (source, listing_id)
);

create table price_snapshots (
  id uuid primary key default gen_random_uuid(),
  product_id uuid not null references products(id) on delete cascade,
  market_type text not null default 'new',  -- 'new' | 'used'
  source text,
  price integer not null,
  shop_name text,
  snapshot_at timestamptz not null default now()
);

create index idx_used_listings_source_listing on used_listings(source, listing_id);
create index idx_used_listings_matched on used_listings(matched_product_id, crawled_at desc);
create index idx_price_snapshots_product_snapshot_at on price_snapshots(product_id, snapshot_at desc);
create index idx_price_snapshots_market_type on price_snapshots(market_type, snapshot_at desc);
```

---

## Adapter Contract

```python
class SourceAdapter(Protocol):
    source_name: str

    # Optional: 게시판 형식 소스용
    def fetch_recent(self, *, pages: int = 1, category: str | None = None) -> list[UsedListing]: ...

    # Optional: 검색 형식 소스용
    def search(self, query: str, *, category: str | None = None) -> list[UsedListing]: ...
```

각 adapter는 둘 중 하나 이상 구현. 둘 다 미지원이면 `NotImplementedError`. 외부 차단 발견 시 `[]` 반환 + 로그.

### Per-Source Approach
| Source | Type | Path | Risk |
|---|---|---|---|
| coolenjoy | board | `/bbs/board.php?bo_table=...` | 중간 (구조 변경) |
| quasarzone | board | `/bbs/qb_saleinfo` 류 | 중간 |
| bunjang | search | `https://api.bunjang.co.kr/api/1/find_v2.json` 같은 공개 search JSON | 낮음 |
| daangn | search | 공개 hot-articles 검색 페이지 | 높음 (지역/anti-bot) |
| joonggonara | search | 네이버 카페 공개 검색 | 매우 높음 (로그인 의존) |

bunjang/daangn/joonggonara는 차단 또는 구조 미확인 시 graceful skip + STATUS.md에 한계 명시.

---

## Normalization Rules

`detect_brand` 확장 + 카테고리별 핵심 토큰 패턴:

```python
CATEGORY_PATTERNS = {
    "cpu":   [r"\b(i[3579]-\d{4,5}[a-z]*)\b", r"\b(\d{4,5}[xkfXKF]*)\b"],  # i7-14700K, 5600X
    "gpu":   [r"\b(rtx\s?\d{4}\s?(ti|super)?)\b", r"\b(rx\s?\d{4})\b"],
    "ram":   [r"\b(ddr[345])\b", r"\b(\d{4,5})mhz?\b", r"\b(\d{1,3})gb?\b"],
    "ssd":   [r"\b(\d{1,4})(tb|gb)\b", r"\b(nvme|sata|m\.2)\b"],
    "mainboard": [r"\b([abxz]\d{3}[a-z]*)\b"],   # B650M, X670E
}
```

추출된 카테고리 핵심 토큰은 매칭 시 가중치 가산.

### Exclusion (게시글 필터)
title에 `삽니다 / 구합니다 / 교환 / 고장 / 부품용 / 본체 / 세트 / 완본체` 포함 시 listing 자체를 drop.

---

## Matching

```
score = 0.35 * brand_match
      + min(0.55, 0.15 * |token_overlap|)
      + 0.15 * exact_category_token_match  (CPU 모델번호 일치 등)
      + 0.10 * exact_title_match

threshold:
  >= 0.55  → 자동 매칭 (matched_product_id 기록)
  0.40 ~ 0.55 → 보류 (matched_product_id 비움, score만 기록)
  < 0.40  → 비매칭
```

후보군은 같은 카테고리 products 만 대상.

---

## Ingest Flow

### `run_danawa(db, category, pages)`
변경 없음 (기존 흐름 유지) + brand/model_name/normalized_name 채워서 upsert.

### `run_used(db, adapter, *, category, queries=None, pages=1)`
1. `adapter.fetch_recent` 또는 `adapter.search(q)` 로 listings 수집
2. exclusion 필터 적용
3. 같은 category products 모두 fetch (`brand`, `model_name`, `normalized_name`)
4. 각 listing → `find_best_candidate` 점수화
5. `used_listings` upsert (`matched_product_id`, `match_score` 포함)
6. score ≥ 0.55 인 경우 `price_snapshots` (`market_type='used'`) insert

`queries` 미제공 시: products 의 `model_name` 들 중 카테고리 상위 N개를 자동 쿼리로 사용.

---

## CLI

```bash
# 신품
python scripts/run_danawa.py cpu --pages 2

# 중고 (board 소스)
python scripts/run_used.py coolenjoy --category cpu --pages 2
python scripts/run_used.py quasarzone --category cpu --pages 2

# 중고 (검색 소스)
python scripts/run_used.py bunjang --category cpu --queries "5600X,7800X3D"
python scripts/run_used.py daangn --category gpu --queries "RTX 4070"
python scripts/run_used.py joonggonara --category gpu --queries "RTX 4070"
```

---

## Testing Strategy

- `tests/` 디렉토리에 pytest 모듈
- `tests/fixtures/<source>/<file>.html` 또는 `.json` — 실 페이지 1회 수집 후 저장
- 단위 테스트만 fixture 의존, 네트워크 의존 없음

| Test file | Covers |
|---|---|
| `test_normalization.py` | brand 감지, 토큰 추출, 카테고리 패턴 |
| `test_matching.py` | 점수화, threshold, exclusion |
| `test_danawa_parser.py` | fixture HTML → RawProduct |
| `test_adapter_<source>.py` | fixture HTML/JSON → UsedListing (5 files) |

종료 조건: `pytest` 0 fails.

---

## Smoke Test (live)

`.env` 에 실 Supabase 키 존재 확인 → `python scripts/run_danawa.py cpu --pages 1` → Supabase `products` / `price_snapshots` 에 row ≥ 1 확인.

---

## Risks & Mitigations
| Risk | Mitigation |
|---|---|
| 다나와 셀렉터 변경 | fixture로 회귀 감지, 변경 시 셀렉터 재조정 |
| 중고 사이트 차단 | UA + Referer + 0.5–1.5s sleep, graceful `[]` 반환 |
| 당근/중고나라 접근 불가 | 가능한 만큼만 구현 + STATUS.md 명시 |
| 매칭 false positive | exclusion + threshold + 카테고리 일치 강제 |
| Supabase 스키마 마이그레이션 충돌 | DROP 없이 `if not exists` + 새 컬럼은 `add column if not exists` |

---

## Done When
- [ ] `sql/schema.sql` 재작성 + Supabase 적용 성공
- [ ] 다나와 파서 fixture 검증 통과
- [ ] 5개 adapter 모두 실구현 (가능한 만큼) + 각 fixture 테스트 통과
- [ ] 매칭 룰 + threshold 구현 + 단위 테스트 통과
- [ ] `scripts/run_used.py` 동작
- [ ] `pytest` 0 fails
- [ ] 실 Supabase smoke test row ≥ 1 확인
- [ ] STATUS.md / README.md 갱신
