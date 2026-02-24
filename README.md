# Larry Williams Volatility Breakout Trading Bot

**래리 윌리엄스 변동성 돌파 전략 기반 한국 주식 자동매매 시스템**

래리 윌리엄스의 변동성 돌파 전략을 핵심으로, 실시간 데이터 수집과 자동 주문 실행을 통합한 트레이딩 봇입니다.

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 프로젝트 개요

이 프로젝트는 **한국투자증권 Open API**를 활용하여 한국 주식 시장(특히 ETF)에서 자동매매를 수행하는 시스템입니다.

### 핵심 전략: 래리 윌리엄스 변동성 돌파

```
목표가 = 당일 시가 + (전일 고가 - 전일 저가) x K
현재가 >= 목표가 -> 매수 (1회)
15:15 -> 무조건 청산 (당일 매매 완결)
```

- 단순하고 검증된 전략
- 1일 1회 매매, 당일 청산 원칙
- 노이즈 비율 기반 동적 K값 조정 (K_MIN=0.3 ~ K_MAX=0.6)
- 슬리피지 제한 (목표가 대비 1% 초과 시 매수 스킵)
- ETF 수수료 최적화 (수수료 우대 계좌 기준)

---

## 주요 기능

### 1. 변동성 돌파 실전 매매봇 (`bot_volatility_for_real.py`)
**실전투자 전용** 래리 윌리엄스 변동성 돌파 전략 봇
- 실전 계좌 연동 (한국투자증권 Open API)
- 동적 K값 계산 (노이즈 비율 기반)
- 시장가 주문으로 빠른 체결
- Telegram 실시간 알림
- 거래 로그 CSV 자동 기록

### 2. 변동성 돌파 모의투자 (`bot_volatility.py`)
모의투자 환경에서 변동성 돌파 전략 테스트

### 3. AI 스캘핑 전략 (`bot_ai_scalper.py`)
XGBoost 5분봉 예측 기반 단타 매매 (보조 전략)
- AI 상승 확률 기반 진입/청산
- 익절/손절/트레일링 스탑

### 4. 복합 전략 (`bot_combined.py`)
변동성 돌파 + AI 필터 하이브리드 (보조 전략)
- 변동성 돌파 AND AI 확률 이중 필터

### 5. 백테스팅 시스템
- `backtester.py` - 과거 데이터 기반 전략 검증
- `optimizer.py` - 파라미터 최적화 도구

### 6. 알림 시스템
- Telegram 실시간 알림 (매매 체결, 에러 모니터링)

---

## 기술 스택

| 분류 | 기술 |
|------|------|
| 트레이딩 | 한국투자증권 REST API |
| 데이터 | yfinance, pandas, numpy |
| ML (보조) | XGBoost, scikit-learn |
| 알림 | Telegram Bot API |
| 환경 관리 | python-dotenv |

---

## 시작하기

### 1. 사전 준비

- Python 3.8 이상
- 한국투자증권 계좌 및 Open API 신청 (실전/모의)
- [한국투자증권 홈페이지](https://www.koreainvestment.com/) > 트레이딩 > Open API

### 2. 설치

```bash
git clone https://github.com/seung23/ai-trading-bot.git
cd ai-trading-bot

python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

### 3. 환경 설정

```bash
cp .env.example .env
# .env 파일에 APP_KEY, APP_SECRET, ACC_NO 등 입력
```

### 4. Telegram 알림 설정 (선택)

```bash
python get_chat_id.py
# .env에 TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 추가
```

---

## 사용법

### 실전 매매 (변동성 돌파)
```bash
python bot_volatility_for_real.py
```

### 모의투자
```bash
python bot_volatility.py      # 변동성 돌파
python bot_ai_scalper.py      # AI 스캘핑
python bot_combined.py        # 복합 전략
```

### 백테스팅
```bash
python backtester.py          # 전략 검증
python optimizer.py           # 파라미터 최적화
```

---

## 프로젝트 구조

```
ai-trading-bot/
|
|-- bot_volatility_for_real.py   # [핵심] 변동성 돌파 실전 매매봇
|-- bot_volatility.py            # 변동성 돌파 (모의투자)
|-- bot_ai_scalper.py            # AI 스캘핑 (보조)
|-- bot_combined.py              # 복합 전략 (보조)
|
|-- broker.py                    # 한국투자증권 API 래퍼
|-- data_manager.py              # 데이터 수집 및 지표 계산
|-- model.py                     # XGBoost 모델 학습/예측
|-- telegram_notifier.py         # Telegram 알림
|
|-- backtester.py                # 백테스팅 엔진
|-- optimizer.py                 # 파라미터 최적화
|-- get_chat_id.py               # Telegram Chat ID 확인
|
|-- .env.example                 # 환경 변수 템플릿
|-- requirements.txt             # Python 의존성
|-- README.md                    # 프로젝트 문서
|-- .gitignore                   # Git 제외 파일
```

---

## 주의사항

```
본 프로젝트는 연구 및 시험 목적으로 제작되었습니다.

1. 실제 투자 시 발생하는 손실에 대해 개발자는 책임지지 않습니다.
2. 금융 투자는 원금 손실 위험이 있으니 신중히 판단하세요.
3. 자동매매 프로그램 사용 전 충분한 테스트를 권장합니다.
4. 한국 금융 규제를 준수하여 사용하세요.
```

- `.env` 파일을 절대 공개 저장소에 커밋하지 마세요
- API 키가 노출되면 즉시 재발급하세요
- 모의투자로 충분히 검증 후 실전 사용하세요

---

## 라이선스

이 프로젝트는 MIT 라이선스 하에 배포됩니다.

---

<div align="center">

Made by seung23

</div>
