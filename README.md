# Bitcoin Auto Trading Bot

비트코인 자동매매 봇 - E>0 구조 기반 손익비 중심 트레이딩 시스템

## 🎯 핵심 특징

- **E>0 구조**: 승률이 낮아도 손익비로 수익 창출
- **R 기반 리스크 관리**: 포지션당 0.5% 고정 리스크
- **ATR 트레일링 스탑**: Chandelier Exit으로 이익 극대화
- **자동 손실 제한**: 일일 -2R, 주간 -5R 도달 시 자동 중단
- **킬스위치**: 긴급상황 시 즉시 포지션 청산

## 🚀 주요 기능

### 거래 전략
- **추세추종**: 20/50 EMA 크로스오버 + ATR 트레일링
- **변동성 돌파**: 전일 범위 돌파 + 볼륨 확인
- **RSI 역추세**: 과매도/과매수 구간 역추세 매매

### 리스크 관리
- 포지션 사이징: `size = (0.5% * equity) / stop_distance`
- 일일 손실 한도: -2R (자동 중단)
- 주간 손실 한도: -5R (전략 재검토)
- 킬스위치: API 호출로 즉시 청산

### 모니터링
- **Prometheus**: 실시간 메트릭 수집
- **Grafana**: 대시보드 시각화
- **FastAPI**: REST API 서버
- **로깅**: 구조화된 로그 시스템

## 🛠 기술 스택

- **언어**: Python 3.11
- **거래소**: 업비트 (Upbit)
- **데이터베이스**: PostgreSQL, Redis
- **모니터링**: Prometheus, Grafana
- **컨테이너**: Docker, Docker Compose
- **라이브러리**: ccxt, pandas, fastapi, pandas-ta

## 📦 설치 및 실행

### 1. 저장소 클론
```bash
git clone https://github.com/Yaklede/bitcoin-auto-bot.git
cd bitcoin-auto-bot
```

### 2. 환경 설정
```bash
# .env 파일 생성
cp .env.example .env

# API 키 설정 (필수)
# UPBIT_API_KEY=your_api_key
# UPBIT_SECRET=your_secret_key
```

### 3. Docker 실행
```bash
# 전체 시스템 실행
docker-compose up -d --build

# 상태 확인
docker-compose ps
```

### 4. 접속 정보
- **봇 API**: http://localhost:8000
- **Grafana**: http://localhost:3000 (admin/admin)
- **Prometheus**: http://localhost:9090

## 📊 API 엔드포인트

### 상태 조회
- `GET /healthz` - 헬스체크
- `GET /status` - 봇 상태 조회
- `GET /metrics` - Prometheus 메트릭

### 제어
- `POST /killswitch` - 킬스위치 활성화
- `DELETE /killswitch` - 킬스위치 비활성화

### 정보 조회
- `GET /positions` - 현재 포지션
- `GET /orders` - 활성 주문
- `GET /pnl` - 손익 정보

## 📈 운영 가이드

### 단계별 실행
1. **페이퍼 트레이딩** (48시간): 실시간 검증
2. **소액 실거래** (2주): 초기 R값 50% 축소
3. **정상 운영**: 무사고 확인 후 R값 복구

### 안전 수칙
- API 키는 **거래 전용, 출금 비활성** 설정
- 일일/주간 손실 한도 준수
- 킬스위치 테스트 정기 실행
- 로그 모니터링 및 알림 설정

## 📚 문서

- [rules.md](rules.md) - 매매봇 설계 원칙 및 리스크 관리
- [deployment.md](deployment.md) - 배포 및 운영 가이드
- [IMPLEMENTATION_REPORT.md](IMPLEMENTATION_REPORT.md) - 구현 완료 보고서

## ⚠️ 주의사항

- **투자 위험**: 자동매매는 손실 위험이 있습니다
- **백테스트 필수**: 실거래 전 충분한 검증 필요
- **리스크 관리**: 설정된 손실 한도 준수
- **모니터링**: 정기적인 시스템 상태 확인

## 📄 라이선스

MIT License - 자세한 내용은 [LICENSE](LICENSE) 파일 참조

## 🤝 기여

이슈 리포트, 기능 제안, 풀 리퀘스트를 환영합니다.

---

**⚡ 면책조항**: 이 소프트웨어는 교육 및 연구 목적으로 제공됩니다. 실제 거래에서 발생하는 손실에 대해 개발자는 책임지지 않습니다.
