# 2026-05-11 Supabase service_role 키 회전 — crawler 적용 가이드

> 관련: pc-dealer 메인 repo `handoff/pre-launch-batch-2-handoff.md §2 #2`.
> Gadgeton 사전 출시 hardening 의 일부로 service_role 키를 legacy JWT →
> 신규 `sb_secret_*` 모델로 회전합니다.

## 무엇이 바뀌었나

Supabase 가 새 API key 모델 (`sb_publishable_*` / `sb_secret_*`) 로 전환했고,
이번 회전에서 crawler 가 사용하던 legacy JWT service_role 키를 신규
secret key 로 교체합니다.

신규 secret key 이름 (Supabase Dashboard 식별용): **`service_role_2026_05_11`**

> 실제 키 값(`sb_secret_5zS-...`)은 본 문서에 적지 않습니다. 운영자 채널 (1Password
> 또는 별도 안전 채널) 로 별도 전달.

## crawler 운영 PC 작업

1. crawler 디렉토리로 이동:

   ```bash
   cd ~/2026/crawler   # 실제 경로에 맞춰
   ```

2. `.env` 의 `SUPABASE_KEY` 를 신규 secret 으로 교체. (기존 백업 후 교체)

   ```bash
   cp .env .env.bak-2026-05-11
   sed -i.bak 's|^SUPABASE_KEY=.*|SUPABASE_KEY=<NEW_SECRET_HERE>|' .env
   rm .env.bak
   ```

   `<NEW_SECRET_HERE>` 는 운영자가 별도 채널로 받은 `sb_secret_*` 값.

3. `SUPABASE_URL` 도 확인 (변경 없음 — 그대로 유지):

   ```bash
   grep ^SUPABASE_URL .env
   # → SUPABASE_URL=https://nptlbfkzepbqmhsxqnuq.supabase.co
   ```

4. launchd 가 새 환경변수를 다시 읽도록 재기동:

   ```bash
   launchctl unload ~/Library/LaunchAgents/com.pcpartscrawler.daily.plist
   launchctl unload ~/Library/LaunchAgents/com.pcpartscrawler.daangn-weekly.plist
   launchctl unload ~/Library/LaunchAgents/com.pcpartscrawler.vocab-weekly.plist

   launchctl load ~/Library/LaunchAgents/com.pcpartscrawler.daily.plist
   launchctl load ~/Library/LaunchAgents/com.pcpartscrawler.daangn-weekly.plist
   launchctl load ~/Library/LaunchAgents/com.pcpartscrawler.vocab-weekly.plist
   ```

5. 즉시 한 번 수동 실행으로 새 키 인증 검증:

   ```bash
   launchctl start com.pcpartscrawler.daily
   tail -f ~/Library/Logs/pc-parts-crawler/daily.log ~/Library/Logs/pc-parts-crawler/daily.err
   ```

   로그에 `403`, `401`, `permission denied`, `Invalid API key` 등이 없으면
   OK. 첫 ingest 가 성공해서 `crawl_runs` 에 새 row 가 들어가야 함:

   ```bash
   # (Supabase SQL Editor 에서)
   select id, started_at, status, errors_count
   from public.crawl_runs
   order by started_at desc
   limit 3;
   ```

## 실패 시 롤백

새 키로 실패하면 `.env.bak-2026-05-11` 의 옛 값으로 되돌리고 launchd 재기동:

```bash
mv .env.bak-2026-05-11 .env
launchctl unload ~/Library/LaunchAgents/com.pcpartscrawler.daily.plist
launchctl load ~/Library/LaunchAgents/com.pcpartscrawler.daily.plist
```

운영자가 메인 repo Claude 에게 보고: 회전 실패, legacy 키로 롤백 완료.

## 검증 완료 후 — 키 폐기

운영 PC + Vercel 양쪽 모두 신규 키로 정상 동작 확인되면:

- Supabase Dashboard → Settings → API Keys → `default` (sb_secret_Zfcs-...)
  → `…` 메뉴 → Revoke / Delete
- Legacy JWT 도 같이 폐기 (Settings → API Keys → Legacy 탭 → `Disable
  JWT-based API keys`). 이후 어떤 머신에서도 legacy JWT 로 인증 불가.

폐기 후 `.env.bak-2026-05-11` 도 삭제 (롤백 옵션 종료).
