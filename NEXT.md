# NEXT.md — 다음 세션 개선 백로그

우선순위 순. 각 항목은 **What / Why / How / 예상 작업량**을 한 단락 정리.

---

## P0 — 매칭 정확도 개선

### 1. 부속품 vs 본품 분리
**What.** "M.2 SSD to SATA 컨버터" 같은 부속품이 같은 카테고리(SSD)의 본품 listing과 매칭됨 (median 70k 컨버터 → 본품 250k matched).
**Why.** 다나와도 부속품을 같은 카테고리에 분류, 부속품 제품명에 본품 토큰이 들어감(`SSD`, `M.2`).
**How.** product 단계에서 부속품 마커(`컨버터`, `젠더`, `케이블`, `브라켓`, `허브`, `독`, `홀더`, `스탠드`)를 검출 → product 자체를 stats 대상에서 제외. 또는 `accessory` 플래그를 products 테이블에 추가.
**작업량.** 1~2시간 (정규식 + products 테이블에 `is_accessory` boolean + aggregate에서 skip).

### 2. 다나와 신품가 outlier 클램핑
**What.** 단종 모델(`삼성 노트북 DDR3-1333`)의 신품가가 4,500원으로 비현실적 → ratio 500%.
**Why.** 다나와 list view의 lowest_price가 어떤 outdated/소진 옵션을 가져옴.
**How.** (a) 다나와 detail 페이지에서 가격 검증, (b) 카테고리별 price floor 적용 (예: RAM 신품가 < 5,000원이면 무효), (c) 또는 7일 이상 갱신 안 된 new_price snapshot을 사용 안 함.
**작업량.** 2~3시간.

### 3. 매칭 스코어 explainability 강화
**What.** `match_score` 외에 어느 시그널(brand/cat_token/sku_line)이 기여했는지 DB 컬럼으로 저장.
**Why.** 디버깅, 사람 검토 시 false positive 빠르게 식별.
**How.** `used_listings.match_reasons` jsonb 컬럼 추가, `MatchResult.reasons` 그대로 저장.
**작업량.** 1시간.

---

## P1 — 데이터 품질 / 커버리지

### 4. Daangn 본격 활성화 + Playwright 풀 사용
**What.** 현재 `--skip-sources daangn`이 기본. 풀 모드는 Playwright 시간 비용(query당 ~15s).
**Why.** Daangn 거래량이 가장 큼.
**How.** (a) 별도 cron으로 매일 1회만 daangn 풀 실행, (b) Playwright 동시성(asyncio + browser context 풀), (c) cache 적용 (같은 query 24h 내 skip).
**작업량.** 3~4시간.

### 5. Quasarzone qb_jijang 로그인 모드
**What.** `qb_jijang` (장터, 회원전용) 데이터 미수집. 로그인 쿠키 옵션 이미 코드에 있음.
**Why.** 진짜 user-to-user 매물 채널.
**How.** `.env`에 `QUASARZONE_PHPSESSID` 추가, run_all.py가 있으면 `QuasarzoneAdapter(session_cookie=...)`로 호출.
**작업량.** 30분 + 사용자 쿠키 1회 추출.

### 6. 카테고리 → canonical 매핑 자동화
**What.** `danawa_categories` 125개 발견됐지만 9개만 `canonical='cpu'/'gpu'/...`로 매핑됨.
**Why.** AI/딥러닝 CPU, RTX 50 신제품 같은 sub-category가 메인 카테고리와 분리됨.
**How.** Korean category name → canonical mapping 학습/룰 (예: 이름에 'CPU' 포함 → cpu, 'RAM' 포함 → ram). 또는 product source_id 중복으로 부모 카테고리 추론.
**작업량.** 2시간.

### 7. 다나와 페이지네이션 회복력
**What.** 9개 카테고리 풀 크롤(~17분) 중 1~2개 page에서 timeout 발생 가능.
**Why.** 외부 의존성, 일시적 네트워크 이슈.
**How.** httpx에 retry (`tenacity`) 적용, 페이지별 백오프, 실패 page 로그 후 다음 페이지로 진행.
**작업량.** 1시간.

---

## P2 — 운영 / 자동화

### 8. 스케줄러 (cron / launchd)
**What.** `run_all.py`를 매일 새벽 자동 실행, vocab 재계산은 주 1회.
**How.**
```cron
# 매일 03:00 — 풀 크롤 (Daangn 제외)
0 3 * * * cd /path/to/repo && .venv/bin/python scripts/run_all.py --skip-sources daangn --danawa-pages 0
# 매주 일요일 04:00 — Daangn 포함 풀
0 4 * * 0 cd /path/to/repo && .venv/bin/python scripts/run_all.py --danawa-pages 0
# 매주 월요일 05:00 — vocab 재계산만
0 5 * * 1 cd /path/to/repo && .venv/bin/python scripts/discover_vocab.py
```
launchd 사용 시 plist 작성 + `launchctl load`.
**작업량.** 1시간.

### 9. 변화 감지 알림
**What.** 다나와 셀렉터 변경, source 차단 등을 즉시 인지.
**How.** `run_all.py` summary가 0 매칭이거나 다나와 product가 평소의 50% 미만이면 알림 (Slack webhook / 이메일). 결과 파일 기준 baseline 비교.
**작업량.** 2시간.

### 10. 운영 로그 → DB
**What.** 현재 stdout만. 실패 추적, retry 통계 안 보임.
**How.** `crawl_runs` 테이블 추가, 시작/종료/카테고리/source/매칭 카운트 기록. SQL 한 줄로 운영 트렌드 조회.
**작업량.** 2시간.

---

## P3 — 기능 확장

### 11. 시세 트렌드 (시계열)
**What.** 현재 `product_market_stats`는 latest만. 1주/4주 트렌드(상승/하락) 없음.
**How.** `aggregate_market_stats(window_days=7)` 추가 호출 → window별 별도 row, 또는 별도 `product_market_stats_history` 테이블에 매일 스냅샷.
**작업량.** 2~3시간.

### 12. 시세 대시보드 (read-only UI)
**What.** Supabase 데이터를 보여주는 simple dashboard. 카테고리/모델 검색, 시세 그래프, 매물 링크.
**How.** Vercel + Next.js + Supabase client (또는 Streamlit, FastAPI+HTMX). MVP는 카테고리별 top product 리스트 + 시세 디테일.
**작업량.** 8~16시간.

### 13. 알림 (price drop)
**What.** 사용자가 watchlist 등록한 product의 used 가격이 threshold 아래로 떨어지면 알림.
**How.** `watchlists` 테이블 + 매번 aggregate 후 비교.
**작업량.** 4시간.

### 14. unknown_vocab 검토 워크플로우
**What.** 자동 분류 못한 토큰이 `unknown_vocab` 테이블에 모임. 사람이 일주일에 한 번 검토 후 brand/sku_line으로 승격.
**How.** `scripts/review_vocab.py` (CLI 인터랙티브). 또는 dashboard에 review 페이지.
**작업량.** 3시간.

---

## P4 — 기술 부채

### 15. 매칭 알고리즘 unit test 강화
- 카테고리별 fixtures (실 listing 100개 × 정답 라벨)
- 매칭 정확도 % 회귀 테스트

### 16. discovery 알고리즘 fixture 테스트
- 가짜 product list 입력 → 예상 brand/sku_line 출력

### 17. Postgres direct connection (DDL용)
- 새 마이그레이션 적용 자동화 (현재 사용자가 dashboard 붙여넣기 필요)
- `psycopg2` + `DATABASE_URL` env

---

## 리스크 / 의존성

- **다나와 사이트 구조 변경**: AJAX endpoint나 physicsCate 추출 regex가 깨질 수 있음. 회복력(P1.7) + 알림(P2.9)이 방패.
- **법적 / robots.txt**: 5개 소스 모두 ToS 확인 필요. 운영 단계 진입 전 검토.
- **Supabase 무료 한도**: row 수 / DB egress / 동시 connection. 10k+ products + 일별 누적 시 유료 플랜 필요할 수 있음.

---

## 마지막 풀 실행 명령 (재현용)

```bash
# Migration 002까지 적용된 DB 가정
.venv/bin/python -c "from dotenv import load_dotenv; load_dotenv(); import os; from supabase import create_client; c = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_KEY']); c.table('price_snapshots').delete().eq('market_type','used').execute(); c.table('used_listings').delete().neq('id','00000000-0000-0000-0000-000000000000').execute()"
.venv/bin/python scripts/run_all.py --danawa-pages 0 --queries-per-search 5 --skip-sources daangn
.venv/bin/python /tmp/show_stats.py     # 결과 확인
.venv/bin/python /tmp/check_anomalies.py  # ratio>1.5 확인
```
