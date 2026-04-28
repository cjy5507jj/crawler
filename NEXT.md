# NEXT.md — 다음 세션 백로그 (2026-04-26 갱신 v2)

이전 세션에서 완료된 항목은 [STATUS.md](STATUS.md) 알고리즘 스택 #21/#22/#23 참고.
현재 pytest **127 passed**, watchlist + review_vocab + discovery fixture 가드 완비.

---

## 🚀 다음 세션 진입점

이번 세션에서 P3.13 / P3.14 / P4.16 번들이 모두 완료되어 잔여 작업은 별도 세션 단위로 분리:

| 항목 | 추정 | 비고 |
|---|---|---|
| **P1.4 Daangn 본격 활성화** | 3~4h | Playwright 동시성 + 24h 쿼리 캐시 — 전용 세션 권장 |
| **P3.12 시세 대시보드** | 8~16h | 별도 repo `crawler-dashboard` (Next.js + Supabase read-only) |

---

## 잔여 백로그

### P1 — 데이터 품질 / 커버리지

#### 1. Daangn 본격 활성화 (3~4h, 별도 세션 권장)
**What.** 현재 `--skip-sources daangn`이 사실상 기본. Playwright 시간 비용(query당 ~15s)이 큼.
**Why.** Daangn 거래량이 가장 많음. 누락 시 시세 신호 손실.
**How.** (a) 별도 cron으로 daily 1회만 daangn 풀, (b) `asyncio + browser context 풀`로 동시성, (c) 같은 query 24h 캐시.
**Risk.** 검증 어려움(수동 페이지 확인 필요), Playwright 환경 의존.

### P3 — 기능 확장

#### 12. 시세 대시보드 (Vercel + Next.js, 8~16h) — **별도 프로젝트**
**What.** Supabase 데이터 read-only UI (카테고리/모델 검색, 시세 그래프, 매물 링크).
**Why 별도.** Next.js 프로젝트 규모. `crawler` 저장소와 분리해서 `crawler-dashboard` 별도 repo 추천.

---

## 닫힌 항목 (이번 세션 추가)

- ✅ **P3.13 가격 알림 watchlist** — DDL 007 + `src/services/watchlist.py` + `scripts/check_watchlist.py` (--dry-run, --cooldown-hours) + `run_all.py` 통합 (--skip-watchlist) + 8개 테스트
- ✅ **P3.14 unknown_vocab 검토 CLI** — `scripts/review_vocab.py --top N [--category]` (b/s/k/d/q) + 9개 테스트
- ✅ **P4.16 discovery fixture 회귀 테스트** — 27개 가짜 product fixture + 5개 회귀 케이스 (brand/sku_line/canonical category)

## 닫힌 항목 (이전 세션 참고)

- ✅ P0.1 accessory 분리 (309+12=321 products `is_accessory=true`)
- ✅ P0.2 카테고리별 new_price floor (1+ 클램핑 작동)
- ✅ P0.3 match_reasons jsonb (1,651 row 채워짐)
- ✅ Monitor 카테고리 + Apple 브랜드 추가
- ✅ P1.5 qb_jijang 로그인 옵션 (`QUASARZONE_PHPSESSID` env)
- ✅ P1.6 카테고리 canonical 자동 매핑 (68/125, cooler 우선)
- ✅ P1.7 tenacity 재시도 (danawa init/page + nav scrape)
- ✅ P2.8 launchd 스케줄러 (3 plist + cron 대안)
- ✅ P2.9 변화 감지 알림 (Slack/Discord/stdout, 50% drop threshold)
- ✅ P2.10 crawl_runs 운영 로그 (status/args/summary jsonb/error)
- ✅ P3.11 시세 시계열 (history 테이블 + trend_7d/28d_pct, 250 첫 스냅샷)
- ✅ P4.15 매칭 회귀 fixture (22 케이스, precision/recall 1.00)
- ✅ git init + push (`https://github.com/cjy5507jj/crawler` main)
- ❌ P4.17 psycopg2 자동 DDL — 사용자 preference 위배 (dashboard paste 선호)

---

## 리스크 / 의존성 (변동 없음)

- 다나와 사이트 구조 변경 → tenacity가 일시 회복, anomaly 알림이 사후 감지.
- 법적/robots.txt 5개 source 검토 필요 (운영 단계 진입 전).
- Supabase 무료 한도: row 수 / DB egress / 동시 connection. 10k+ products + 일별 누적 시 유료 필요할 수 있음.

---

## 마지막 풀 실행 명령 (재현용)

```bash
# 단계별
.venv/bin/python scripts/run_all.py --skip-danawa --skip-sources daangn   # used만 (watchlist 자동 평가)
.venv/bin/python scripts/aggregate_stats.py                               # history + trends
.venv/bin/python scripts/discover_vocab.py                                # vocab만
.venv/bin/python scripts/check_watchlist.py --dry-run                     # watchlist 평가만
.venv/bin/python scripts/review_vocab.py --top 20                         # 미분류 토큰 검토

# 풀 (Daangn 포함, ~30분+)
.venv/bin/python scripts/run_all.py --danawa-pages 0
```
