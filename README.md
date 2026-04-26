# pc-parts-crawler

다나와를 **기준 상품 마스터**로, 5개 중고 source(쿨앤조이/퀘이사존/번개장터/당근/중고나라)에서 시세를 수집·매칭해 Supabase에 저장하는 크롤러. **모든 정규화 vocabulary는 동적으로 자동 발견**되며, 신규 제조사·모델은 다음 크롤 사이클에 자동 추가된다.

- 운영 상태: [`STATUS.md`](STATUS.md)
- 다음 개선 백로그: [`NEXT.md`](NEXT.md)
- 설계 문서: [`docs/superpowers/specs/2026-04-26-pc-parts-crawler-design.md`](docs/superpowers/specs/2026-04-26-pc-parts-crawler-design.md)

---

## 빠른 시작

### 1. 의존성

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,browser]"
playwright install chromium    # daangn / joonggonara 렌더링용
```

Python 3.11+ 권장.

### 2. 환경변수

```bash
cp .env.example .env
# SUPABASE_URL + SUPABASE_KEY (service_role) 입력
```

선택 환경변수:
- `QUASARZONE_PHPSESSID` — 로그인 쿠키. 설정 시 회원전용 보드 `qb_jijang`(장터)도 크롤.

### 3. Supabase 스키마 적용 (1회)

Supabase 대시보드 SQL 에디터에 붙여넣고 Run:
1. `sql/schema.sql` (products / used_listings / price_snapshots)
2. `sql/migration_001_market_stats.sql` (product_market_stats)
3. `sql/migration_002_vocabulary.sql` (brands / sku_lines / danawa_categories / unknown_vocab)
4. `sql/migration_003_match_reasons.sql` (used_listings.match_reasons jsonb)
5. `sql/migration_004_accessory_flag.sql` (products.is_accessory)

### 4. 풀 파이프라인 한 방

```bash
python scripts/run_all.py --danawa-pages 0
```

순서: 9개 카테고리 × 다나와 모든 페이지 → vocab 자동 발견 → 5개 used source × 검색 매칭 → product_market_stats 집계.

옵션:
```bash
# Daangn 제외 (Playwright 시간 절약)
python scripts/run_all.py --danawa-pages 0 --skip-sources daangn

# 일부 카테고리만
python scripts/run_all.py --categories cpu,gpu --danawa-pages 0

# 다나와 재크롤 없이 used만
python scripts/run_all.py --skip-danawa
```

### 5. 단계별 실행

```bash
# 신품 (단일 카테고리)
python scripts/run_danawa.py cpu --pages 2

# 중고 (단일 source × 카테고리)
python scripts/run_used.py coolenjoy   --category cpu --pages 2
python scripts/run_used.py quasarzone  --category cpu --pages 2
python scripts/run_used.py bunjang     --category cpu --queries "5600X,7800X3D"
python scripts/run_used.py joonggonara --category gpu --queries "RTX 5070,RTX 5080"
python scripts/run_used.py daangn      --category gpu --queries "RTX 5070"

# vocabulary만 재계산 (주 1회 추천)
python scripts/discover_vocab.py

# 시세만 재집계
python scripts/aggregate_stats.py --window-days 30
```

### 6. 테스트

```bash
pytest -q
```

51개 테스트가 fixture 기반으로 동작 (네트워크 미의존).

---

## 시세 알고리즘

`product_market_stats` 테이블에 product별로 다음을 계산:

| 컬럼 | 의미 |
|---|---|
| `used_count` | 윈도우 내 sanity-필터 통과한 used snapshot 수 |
| `used_min` / `used_max` | 윈도우 내 최저/최고 |
| `used_median` | 중앙값 (메인 시세) |
| `used_mean` | **트림드 평균** — n≥10이면 상하 20%, n≥5이면 10% 절단 후 산술평균 |
| `used_latest` / `used_latest_at` | 가장 최근 거래가 + 시각 |
| `new_price` | 가장 최근 다나와 신품가 |
| `used_to_new_ratio` | `used_median / new_price` (감가율 지표) |
| `window_days` | 집계 윈도우 (기본 30일) |

**적용된 매칭 disqualification**:
1. **Brand mismatch** — ASUS RTX ≠ MSI RTX
2. **Category-token mismatch** — RTX 5070 ≠ RTX 5080
3. **Capacity mismatch** — 1TB SSD ≠ 2TB SSD
4. **SKU-line mismatch** — VENTUS ≠ GAMING TRIO
5. **Multi-component bundle 감지** — CPU+GPU/CPU+MB/GPU+MB 매물은 PC 빌드로 자동 제외

**Sanity 필터**: median × 4 외 outlier 제거 + adaptive 트림드 평균.

---

## 동적 Vocabulary

| 사전 | 자동 발견 방식 |
|---|---|
| **brands** | 다나와 product 첫 토큰 frequency analysis (≥3회 등장 → 후보), seed는 hardcoded 24개 |
| **sku_lines** | 카테고리별 n-gram (1~3) TF-IDF — 다른 카테고리에서 드문 token만 채택 |
| **danawa_categories** | 다나와 nav HTML 스크랩으로 cate_id ↔ name_ko 매핑 자동 |
| **unknown_vocab** | 분류 못한 토큰 보관, 사람 검토용 |

신규 제조사/모델이 다나와에 등록되면 다음 `discover_vocab` 사이클에 자동으로 매칭 vocabulary에 편입.

---

## 프로젝트 구조

```
pc-parts-crawler/
├── docs/superpowers/specs/    # 설계 문서
├── sql/
│   ├── schema.sql
│   ├── migration_001_market_stats.sql
│   └── migration_002_vocabulary.sql
├── scripts/
│   ├── run_danawa.py            # 단일 카테고리 신품
│   ├── run_used.py              # 단일 source × 카테고리
│   ├── run_all.py               # 풀 오케스트레이터
│   ├── discover_vocab.py        # vocab 재계산
│   └── aggregate_stats.py       # stats 재계산
├── src/
│   ├── crawlers/danawa.py       # AJAX pagination, parse_products
│   ├── adapters/                # 5개 source + _browser (Playwright)
│   ├── normalization/
│   │   ├── catalog.py           # detect_brand, extract tokens, bundle 감지
│   │   └── vocab.py             # DB 기반 lazy 캐시
│   └── services/
│       ├── matching.py          # score + 4개 DQ
│       ├── ingest.py            # run_danawa / run_used
│       ├── aggregate.py         # batched stats
│       ├── discovery.py         # auto vocab
│       └── queries.py           # search query 자동 생성
└── tests/                       # 51 fixture-based tests
```

---

## 알려진 한계 / 다음 라운드

[`NEXT.md`](NEXT.md) 참고. 주요 항목:
- 부속품/본품 분리 (P0)
- 다나와 단종 신품가 outlier 클램핑 (P0)
- Daangn 풀 활성화 + 동시성 (P1)
- Quasarzone qb_jijang 로그인 모드 (P1)
- 운영 cron / 변화 알림 / 시세 트렌드 / 대시보드 (P2~P3)
# crawler
