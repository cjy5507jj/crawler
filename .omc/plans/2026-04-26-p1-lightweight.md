# Plan: P1 lightweight 번들 (2026-04-26)

NEXT.md P1 중 시간 비용 작고 즉시 효과 큰 3개를 묶음. P1.4 Daangn은 Playwright 시간 비용 + 검증 필요해서 별도 세션.

**Scope**: P1.7 retry 회복력 + P1.6 카테고리 canonical 자동 매핑 + P1.5 qb_jijang 로그인 옵션
**작업량**: ~3.5h

## Step 1 — P1.7: tenacity 기반 retry 회복력 (1h)

**파일**: `pyproject.toml`, `src/crawlers/danawa.py`, `src/services/discovery.py`

1. `pyproject.toml` dependencies에 `tenacity>=8` 추가.
2. `src/crawlers/danawa.py`:
   - `_init_category` httpx GET, `_fetch_page` httpx POST를 `@retry` 데코레이터로 래핑
   - exponential backoff: `wait=wait_exponential(multiplier=1, min=2, max=10)`
   - retry on `httpx.HTTPError`, `httpx.TimeoutException`
   - max attempts=3
   - 실패 후에도 기존처럼 print하고 다음 페이지 진행 (현재 동작 보존)
3. `src/services/discovery.py::_fetch_nav_html` 도 같은 retry.
4. 테스트: `tests/test_danawa_parser.py`에 retry 동작 검증 (fake httpx 클라이언트로 1번 실패 후 2번째 성공).

**Acceptance**: 일시적 네트워크 에러에서도 자동 재시도. 51 baseline + 신규 테스트 통과.

## Step 2 — P1.6: 다나와 카테고리 canonical 자동 매핑 (2h)

**파일**: `src/services/discovery.py`

현재 `danawa_categories` 125개 중 9개만 canonical(cpu/gpu/...) 세팅됨. Korean name 패턴 매칭으로 자동 매핑.

1. `src/services/discovery.py`에 새 함수 `auto_map_canonical_categories(db)`:
   ```python
   _CANONICAL_PATTERNS: list[tuple[re.Pattern, str]] = [
       (re.compile(r"cpu|프로세서|중앙처리장치", re.I), "cpu"),
       (re.compile(r"그래픽카드|gpu|vga|비디오카드", re.I), "gpu"),
       (re.compile(r"메인보드|마더보드", re.I), "mainboard"),
       (re.compile(r"^램$|메모리|ram\b|ddr[345]", re.I), "ram"),
       (re.compile(r"\bssd\b|솔리드", re.I), "ssd"),
       (re.compile(r"\bhdd\b|하드디스크", re.I), "hdd"),
       (re.compile(r"파워|psu|전원공급", re.I), "psu"),
       (re.compile(r"케이스(?!\s*팬)|컴퓨터케이스", re.I), "case"),
       (re.compile(r"쿨러|cpu쿨러|수랭|공랭", re.I), "cooler"),
       (re.compile(r"모니터|디스플레이", re.I), "monitor"),
   ]
   ```
2. canonical=NULL인 row만 처리. 매칭되면 update, 미매칭은 그대로.
3. `run_all.py` Phase 2 (vocab discovery)에서 `discover_categories_from_nav` 직후 `auto_map_canonical_categories` 호출.
4. 테스트: `tests/test_discovery.py::test_auto_map_canonical_categories` — 가짜 db에 "AI/딥러닝 CPU", "RTX 50 그래픽카드", "DDR5 램" row 입력 → canonical=cpu/gpu/ram로 업데이트되는지.

**Acceptance**: 125개 중 자동 매핑 가능한 row 카운트 ≥ 30 (실 데이터 기준). 명시적으로 매핑된 9개+monitor=10은 그대로 유지.

## Step 3 — P1.5: qb_jijang 로그인 옵션 wiring (30min)

**파일**: `scripts/run_all.py`

QuasarzoneAdapter는 이미 `session_cookie=` 파라미터 받음. run_all.py에서 env var 읽어서 전달만 추가.

1. `scripts/run_all.py`:
   ```python
   _QUASARZONE_COOKIE = os.environ.get("QUASARZONE_PHPSESSID") or None
   _QB_JIJANG_BOARDS = ("qb_saleinfo", "qb_partnersaleinfo", "qb_jijang")
   ```
2. QuasarzoneAdapter 인스턴스화를 dict comprehension에서 분리:
   ```python
   def _make_quasarzone():
       if _QUASARZONE_COOKIE:
           return QuasarzoneAdapter(
               boards=_QB_JIJANG_BOARDS, session_cookie=_QUASARZONE_COOKIE
           )
       return QuasarzoneAdapter()
   _BOARD_SOURCES = {"coolenjoy": CoolenjoyAdapter, "quasarzone": _make_quasarzone}
   ```
3. `_run_used_for_category`의 인스턴스화 코드(`c()`)는 callable이면 그대로 동작 — 변경 불필요.
4. README 또는 STATUS.md에 `QUASARZONE_PHPSESSID` env var 사용법 한 줄 추가.

**Acceptance**: `QUASARZONE_PHPSESSID=...` 환경변수 있을 때 qb_jijang 보드도 크롤. 없으면 기존과 동일.

## Step 4 — 통합 검증 (30min)

1. `pytest -v` — 신규 테스트 포함 모두 PASS.
2. `discover_vocab.py` 단독 실행 (또는 ad-hoc) — `auto_map_canonical_categories` 결과 카운트 확인.
3. `run_all.py --skip-danawa --skip-sources daangn` 1 페이지만 — quasarzone 환경변수 없이 평소처럼 동작 확인.
4. STATUS.md 업데이트.

## Out of Scope (다음 세션)

- P1.4 Daangn 본격 활성화 — Playwright 동시성 + cache. 시간 비용 큼.
- P2 운영/자동화 (cron, 알림, crawl_runs)
- P3 기능 확장 (대시보드, 알림, 시계열)
