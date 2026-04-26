# ops/ — 자동 실행 스케줄러

macOS launchd plist 3개. cron 사용자는 하단 crontab 예시 참고.

## 설치 (launchd)

1. 로그 디렉토리 생성:
   mkdir -p ~/Library/Logs/pc-parts-crawler

2. plist를 LaunchAgents 폴더로 복사 (하나씩):
   cp ops/com.pcpartscrawler.daily.plist ~/Library/LaunchAgents/
   cp ops/com.pcpartscrawler.daangn-weekly.plist ~/Library/LaunchAgents/
   cp ops/com.pcpartscrawler.vocab-weekly.plist ~/Library/LaunchAgents/

3. 로드:
   launchctl load ~/Library/LaunchAgents/com.pcpartscrawler.daily.plist
   launchctl load ~/Library/LaunchAgents/com.pcpartscrawler.daangn-weekly.plist
   launchctl load ~/Library/LaunchAgents/com.pcpartscrawler.vocab-weekly.plist

4. 즉시 한 번 실행 (테스트):
   launchctl start com.pcpartscrawler.daily

## 제거

launchctl unload ~/Library/LaunchAgents/com.pcpartscrawler.<name>.plist
rm ~/Library/LaunchAgents/com.pcpartscrawler.<name>.plist

## 로그 확인

tail -f ~/Library/Logs/pc-parts-crawler/daily.log
tail -f ~/Library/Logs/pc-parts-crawler/daily.err

## 환경변수 (.env가 launchd에 자동 적용 안 됨)

plist의 EnvironmentVariables 블록에 SUPABASE_URL / SUPABASE_KEY 직접 추가하거나,
run_all.py가 dotenv를 통해 .env를 자동 로드하므로 작업 디렉토리에 .env 파일이
있으면 그대로 동작.

## crontab 대안

launchd 대신 사용 시:

```cron
# 매일 03:00 — 풀 크롤 (Daangn 제외)
0 3 * * * cd /Users/joejaeyoung/2026/pc-parts-crawler && CRAWL_TRIGGER_SOURCE=cron .venv/bin/python scripts/run_all.py --skip-sources daangn --danawa-pages 0 >> ~/Library/Logs/pc-parts-crawler/daily.log 2>&1

# 매주 일요일 04:00 — Daangn 포함 풀
0 4 * * 0 cd /Users/joejaeyoung/2026/pc-parts-crawler && CRAWL_TRIGGER_SOURCE=cron .venv/bin/python scripts/run_all.py --danawa-pages 0 >> ~/Library/Logs/pc-parts-crawler/daangn-weekly.log 2>&1

# 매주 월요일 05:00 — vocab 재계산
0 5 * * 1 cd /Users/joejaeyoung/2026/pc-parts-crawler && CRAWL_TRIGGER_SOURCE=cron .venv/bin/python scripts/discover_vocab.py >> ~/Library/Logs/pc-parts-crawler/vocab-weekly.log 2>&1
```
