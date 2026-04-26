# PC Parts Price Crawler 구현 계획

## 현재 상태
- 다나와 신품 크롤러 초안이 있음
- Supabase 저장 구조 초안이 있음
- 중고 시세 조사 문서와 adapter/matching 뼈대가 추가됨
- 아직 실제 중고 소스 수집기는 구현되지 않았음

## 핵심 아키텍처

### Danawa = 기준 상품 마스터
다나와에서 아래를 관리한다:
- category
- brand
- model_name
- normalized_name
- source_id
- url
- current_new_price

### Secondhand markets = 시세 입력원
대상 소스:
- 쿨앤조이
- 퀘이사존
- 당근마켓
- 번개장터
- 중고나라

각 소스에서 수집한 게시글은 다나와 상품에 매핑한다.

### Matching layer = 핵심
브랜드/모델/카테고리 정규화를 통해:
- 중고 게시글 title
- 다나와 상품 name
를 연결한다.

---

## 추천 MVP 범위
### 포함
- 다나와 카테고리별 신품 상품 마스터 수집
- 브랜드/모델 정규화
- 커뮤니티 장터 1~2개 소스(쿨앤조이, 퀘이사존)부터 시작
- 중고 게시글 → 다나와 상품 후보 매칭

### 제외
- 모든 소스 동시 구현
- 실시간 알림
- 완전한 시세 분석 UI
- 판매완료 추론 고도화

---

## 데이터 모델 방향
```sql
create table if not exists products (
  id uuid primary key default gen_random_uuid(),
  category text not null,
  source text not null,
  source_id text not null,
  brand text,
  model_name text,
  normalized_name text,
  name text not null,
  url text,
  created_at timestamptz not null default now(),
  unique (source, source_id)
);

create table if not exists price_snapshots (
  id uuid primary key default gen_random_uuid(),
  product_id uuid not null references products(id) on delete cascade,
  market_type text not null default 'new',
  source text,
  price integer not null,
  shop_name text,
  snapshot_at timestamptz not null default now()
);
```

---

## 단계별 계획

### Phase 1 — Danawa master 안정화
- 다나와 실페이지 기준 파서 보정
- brand/model_name/normalized_name 추출
- 신품 기준가 수집 안정화

### Phase 2 — Secondhand research + adapter rollout
- `SECONDHAND_RESEARCH.md` 유지/보강
- 쿨앤조이 adapter 구현
- 퀘이사존 adapter 구현
- 번개장터 / 당근 / 중고나라 feasibility 검증 후 순차 추가

### Phase 3 — Matching and price intelligence
- 중고 listing → 다나와 후보 상품 점수화
- 소스별 이상치 필터링
- 최근가/평균가/최저가 계산
- 신품가 대비 중고가 비율 계산

### Phase 4 — Storage / automation
- Supabase 저장 연결
- 수동 검증 후 배치 스케줄링
- 운영 로그/실패 재시도 구조 추가

---

## 현재 즉시 해야 할 일
1. 다나와 파서 실보정
2. 쿨앤조이 실제 수집 구현
3. 퀘이사존 실제 수집 구현
4. 매칭 점수화 룰 튜닝
5. DB 연결

---

## 구현 원칙
- 다나와를 기준축으로 유지
- 중고 소스는 adapter 단위로 독립 구현
- 정규화/매칭 레이어를 먼저 분리
- DB는 optional interface 로 유지하다가 나중에 붙임
- 아직 확인되지 않은 부분은 문서에 TODO로 명시
