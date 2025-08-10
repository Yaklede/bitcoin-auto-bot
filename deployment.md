---

# 비트코인 매매봇 구축·운영 계획서 (업비트 · Docker · 모니터링 포함)

> **핵심 목표**: 승률이 낮아도 **Expectancy(E)>0**를 유지하는 손익비·리스크 레일로 **잔고 우상향** 달성. 1트레이드 위험 R은 0.25\~1.0%(초기 0.5%) 고정, Daily -2R/Weekly -5R 컷을 코드로 강제. &#x20;

---

## 1) 시스템 개요(아키텍처)

* **모듈**: Ingestion(시세) → Strategy(시그널) → Risk(사이징/스탑) → Broker(주문) → State/Storage(DB) → Monitor(대시보드/알림/헬스/킬스위치)&#x20;
* **거래소**: 업비트 현물 KRW-BTC(초기)&#x20;
* **권장 스택**: Python(+ccxt), Postgres(시세/체결 로그), Redis(락/세션), Prometheus+Grafana(메트릭), Slack(알림)
* **운영 KPI**: 누적PnL, MDD, 현재 R, 노출, 체결·오류, 헬스체크 지표를 상시 시각화/알림.&#x20;

---

## 2) 레일(원칙) 요약 → 코드 규칙화

* **E>0 구조**(손익비 중심), **R 고정/변동성 타게팅**, **일·주 손실 컷 자동화**. &#x20;
* **전략 템플릿**: 추세추종(20/50 EMA + ATR 트레일러) 메인, 변동성 돌파 보조, RSI 역추세는 저레버 보조.  &#x20;

---

## 3) 저장소 & 디렉토리 구조(예시)

```
bot/
  app/
    __init__.py
    config.py           # YAML/ENV 로드
    data.py             # OHLCV 수집/집계
    indicators.py       # EMA/ATR/RSI 등
    strategy.py         # 시그널 엔진
    risk.py             # 사이징, 스탑/트레일
    broker_ccxt.py      # 실거래(업비트/ccxt)
    broker_paper.py     # 페이퍼/시뮬
    state.py            # 포지션/주문/체결 캐시
    api.py              # /healthz, /metrics, /killswitch
    metrics.py          # prometheus_client
    runner.py           # 메인 루프
  tests/
  docker/
    prometheus.yml
  docker-compose.yml
  Dockerfile
  .env.example
  config.yaml          # 전략/리스크 기본값
```

---

## 4) 설정값(YAML) 템플릿

아래는 네 문서의 기본 파라미터를 바로 쓸 수 있게 옮긴 것. 값 조정만 하면 됨.&#x20;

```yaml
# config.yaml
exchange:
  name: upbit
  market: KRW-BTC
  taker_fee_bps: 25
  slippage_bps: 10

risk:
  r_per_trade_bps: 50   # 0.5% = 1R
  daily_stop_R: -2
  weekly_stop_R: -5
  max_position: 1

strategy:
  main: trend_follow
  params:
    ema_fast: 20
    ema_slow: 50
    atr_len: 14
    init_stop_atr: 2.5
    trail_type: chandelier
    trail_atr_mult: 3.0

filters:
  only_long_when_fast_gt_slow: true
```

---

## 5) 핵심 로직 스켈레톤(요지)

문서의 포지션 사이징 식을 그대로 코드화.&#x20;

```python
# app/risk.py
def position_size(equity, entry, atr, init_stop_atr=2.5, r_per_trade=0.005, tick=0.0001):
    stop = entry - init_stop_atr * atr
    stop_dist = max(entry - stop, tick)
    qty = (r_per_trade * equity) / stop_dist
    return floor_to_tick(qty)

# app/strategy.py (trend-follow)
def trend_signal(ohlc):
    ema_fast = ema(ohlc.close, 20); ema_slow = ema(ohlc.close, 50)
    atr = atr14(ohlc)
    long_ok = ema_fast[-1] > ema_slow[-1]
    entry = ohlc.close[-1]
    return {"long": long_ok, "entry": entry, "atr": atr[-1]}

# app/api.py (health/metrics/killswitch)
from fastapi import FastAPI
from prometheus_client import Counter, Gauge, generate_latest
app = FastAPI()
trades_total = Counter("bot_trades_total","trades")
equity_g = Gauge("bot_equity","equity KRW")
@app.get("/healthz")         # docker healthcheck 용
def healthz(): return {"ok": True}
@app.get("/metrics")
def metrics(): return Response(generate_latest(), media_type="text/plain")
```

---

## 6) Dockerfile

```dockerfile
# Dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y build-essential && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot ./bot
ENV PYTHONUNBUFFERED=1
CMD ["python","-m","bot.runner"]
```

`requirements.txt` 예시:

```
ccxt==4.*
pandas==2.*
pandas_ta==0.3.*
fastapi==0.115.*
uvicorn==0.30.*
prometheus-client==0.20.*
psycopg2-binary==2.9.*
redis==5.*
pyyaml==6.*
```

---

## 7) docker-compose.yml (모니터링 포함, 싱글호스트)

```yaml
version: "3.8"
services:
  bot:
    build: .
    image: trading-bot:latest
    env_file: .env
    volumes:
      - ./config.yaml:/app/config.yaml:ro
    depends_on: [postgres, redis]
    ports: ["8000:8000"]        # (선택) api/metrics 노출
    healthcheck:
      test: ["CMD","curl","-fsS","http://localhost:8000/healthz"]
      interval: 15s
      timeout: 3s
      retries: 5

  postgres:
    image: postgres:16
    environment:
      POSTGRES_PASSWORD: ${PG_PASSWORD}
      POSTGRES_USER: ${PG_USER}
      POSTGRES_DB: ${PG_DB}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck: { test: ["CMD-SHELL","pg_isready -U ${PG_USER} -d ${PG_DB}"], interval: 10s, timeout: 5s, retries: 5 }

  redis:
    image: redis:7
    command: ["redis-server","--appendonly","yes"]
    volumes:
      - redisdata:/data

  prometheus:
    image: prom/prometheus:v2.53.0
    volumes:
      - ./docker/prometheus.yml:/etc/prometheus/prometheus.yml:ro
    ports: ["9090:9090"]

  grafana:
    image: grafana/grafana:10.4.7
    ports: ["3000:3000"]
    environment:
      GF_SECURITY_ADMIN_USER: admin
      GF_SECURITY_ADMIN_PASSWORD: admin
    depends_on: [prometheus]

volumes:
  pgdata:
  redisdata:
```

`docker/prometheus.yml`(예시):

```yaml
global: { scrape_interval: 10s }
scrape_configs:
- job_name: bot
  static_configs:
  - targets: ["bot:8000"]
    labels: { service: "bot" }
  metrics_path: /metrics
```

**Grafana 대시보드 패널 추천**

* `bot_equity`(Equity KRW), `bot_trades_total`(누적 체결), 드로다운(계산식 패널), 주문 오류율, 데이터 지연(커스텀 게이지), R 사용량 게이지. 문서의 모니터링 항목을 그대로 반영.&#x20;

---

## 8) .env 템플릿

```
UPBIT_API_KEY=xxxxx
UPBIT_SECRET=xxxxx
MODE=paper                 # live | paper
PG_HOST=postgres
PG_DB=bot
PG_USER=bot
PG_PASSWORD=botpass
REDIS_URL=redis://redis:6379/0
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/xxx/yyy/zzz
TZ=Asia/Seoul
```

---

## 9) 알림/안전장치

* **알림**: 신규 진입·증액·청산, 스탑 체결, 일일 손실 컷, 오류/지연 → Slack Webhook.&#x20;
* **킬스위치**: `/killswitch` 호출 시 즉시 평탄화 후 거래 중지(알림 발송).
* **보안**: API키는 **거래 전용/출금 비활성/IP 제한**, 시크릿 분리, 멱등키·재시도·중복주문 방지.&#x20;

---

## 10) 단계별 테스트 & 실행 체크리스트 (실행 명령 포함)

### A. 환경 준비

* [ ] `.env` 채움(키/DB/Slack)
* [ ] `config.yaml` 값 검토(시장/수수료/슬리피지/리스크)&#x20;
* [ ] `docker/prometheus.yml` 존재 확인

### B. 로컬 단위 테스트

```bash
python -m pytest -q
```

### C. 백테스트

* [ ] 수수료·슬리피지·부분체결 시뮬 반영, WFO/MC 리샘플링으로 러그드니스 점검
* [ ] 출력: CAGR, MDD, PF, Sharpe/Sortino, 승률, 평균R → **E>0 확인**
  (문서의 체크리스트를 그대로 준수)&#x20;

```bash
python -m bot.backtest --start 2023-01-01 --end 2025-07-31 --config config.yaml --report out/backtest.html
```

### D. 페이퍼 트레이딩(드라이런)

* [ ] `MODE=paper`로 컴포즈 기동
* [ ] 실시간 지표/시그널이 백테스트와 일치하는지, 주문 경로/지연/슬리피지 계측, 알림/킬스위치 동작 확인&#x20;

```bash
docker compose up -d --build
# 건강상태
docker compose ps
curl -fsS http://localhost:8000/healthz
# 메트릭 시각화: http://localhost:3000 (admin/admin)
```

**운영 대시보드 확인(필수)**

* [ ] Equity 상승/드로다운, 체결 카운트, 오류율, 데이터 지연이 정상 범위
* [ ] Daily -2R 시 자동 중지/알림 발생&#x20;

### E. 소액 실거래 베타(2주)

* [ ] `MODE=live`, R 절반 축소(예: 0.25%R)로 시작
* [ ] 2주 **무사고** 후 R 복구 판단, 드로다운 규칙 준수 확인&#x20;

### F. 지속 운영

* [ ] 주간 리포트(손익, R분포, 규칙 위반, 알림 통계), 월간 파라미터 드리프트 점검/버전 고정.&#x20;

---

## 11) 운영 Runbook(문제 대응)

* **데이터 지연↑/WS 재연결 잦음** → 자동 알림 발생 시 `docker logs bot` 확인, 데이터 소스 전환/쿨다운.&#x20;
* **주문 실패율↑** → 멱등키/재시도 로직 확인, 슬리피지 상향, 시장가 전환.&#x20;
* **급락/비정상 슬리피지** → **즉시 Flat + 쿨다운**(재진입 지연).&#x20;
* **재시작** → 상태복구(포지션/주문 일치) 검증 후 거래 재개.&#x20;

---

## 12) 릴리즈 절차 & 일정(권장)

* Staging → 페이퍼 48h → 소액 실거래(베타) → 점진 확대.&#x20;
* 권장 4주 롤아웃: 주1(뼈대) → 주2(백테/WFO/페이퍼) → 주3(베타/모니터링) → 주4(러그드니스/리스크 튜닝·자동리포팅).&#x20;

---

## 13) 최종 릴리스 전 체크리스트(요약)

* [ ] **E>0**인지(백테/페이퍼 결과로 확인)&#x20;
* [ ] **R 규율**이 코드로 **강제**되는지(손절·일/주 컷)&#x20;
* [ ] **재시작 안전**/데이터 이상 방어/슬리피지·수수료 보수적 반영&#x20;
* [ ] **릴리즈 절차**(페이퍼→소액→확대) 준수 계획&#x20;

---

### 참고

* 문서의 운영·모니터링/보안·리스크·전략 템플릿/체크리스트 항목을 그대로 코드·도커·대시보드에 대응시켰음.  &#x20;

---

원하면 위 내용 **그대로 레포 구조+파일 세트**로 만들어서 `.zip`로 뽑아줄게. 또는 **실제 Grafana JSON 대시보드**/Prometheus 알람룰(yaml)도 바로 붙여서 줄 수 있어. 어디부터 손댈지 말만 해.
