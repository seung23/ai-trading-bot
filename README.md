# 🤖 AI-Powered Trading Bot

**XGBoost 기반 한국 주식 자동매매 시스템**

실시간 데이터 수집, 머신러닝 예측, 백테스팅, 자동 주문 실행을 통합한 퀀트 트레이딩 봇입니다.

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/)
[![XGBoost](https://img.shields.io/badge/XGBoost-2.0+-green.svg)](https://xgboost.readthedocs.io/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)


---

## 🎯 프로젝트 개요

이 프로젝트는 **한국투자증권 Open API**를 활용하여 한국 주식 시장(특히 ETF)에서 자동매매를 수행하는 시스템입니다.

### 핵심 특징
- 🧠 **XGBoost 머신러닝 모델**로 상승/하락 예측
- 📊 **60개+ 기술 지표** 자동 계산 (RSI, MACD, Bollinger Bands 등)
- 🔄 **실시간 데이터 수집** 및 5분봉 분석
- 📈 **백테스팅 시스템**으로 전략 검증
- 💬 **Telegram 알림** 통합
- 🎛️ **실전/모의 투자** 모드 지원

---

## ✨ 주요 기능

### 1️⃣ 데이터 수집 & 전처리
- `yfinance`로 과거 데이터 자동 수집
- 60개+ 기술 지표 자동 계산
- 5분봉 실시간 업데이트

### 2️⃣ 머신러닝 모델
- **XGBoost Classifier** 기반 상승 확률 예측
- 자동 학습 및 모델 저장/로드
- 피처 중요도 분석

### 3️⃣ 트레이딩 봇
- 실시간 시세 조회 (한국투자증권 API)
- 자동 매수/매도 주문 실행
- 익절/손절/트레일링 스탑
- AI 신호 기반 진입/청산

### 4️⃣ 백테스팅
- 과거 데이터 기반 전략 검증
- Sharpe Ratio, MDD, 승률 등 성과 지표
- 파라미터 최적화 도구

### 5️⃣ 알림 시스템
- Telegram 실시간 알림
- 매매 체결 알림
- 에러/예외 상황 모니터링

---

## 🛠️ 기술 스택

### **머신러닝 & 데이터**
- **XGBoost** - 예측 모델
- **pandas** / **numpy** - 데이터 처리
- **scikit-learn** - 전처리 및 평가
- **yfinance** - 시장 데이터 수집

### **트레이딩 인프라**
- **한국투자증권 REST API** - 시세 조회 및 주문
- **python-dotenv** - 환경 변수 관리
- **requests** - HTTP 통신

### **알림 & 모니터링**
- **Telegram Bot API** - 실시간 알림

---

## 📊 트레이딩 전략

### 1. **변동성 돌파 전략** (`bot_volatility.py`)
Larry Williams의 변동성 돌파 전략 구현
```
목표가 = 당일 시가 + (전일 고가 - 전일 저가) × K
현재가 ≥ 목표가 → 매수
15:15 → 무조건 청산
```

**특징:**
- 단순하고 검증된 전략
- 1일 1회 매매
- 시간 기반 청산

---

### 2. **AI 스캘핑 전략** (`bot_ai_scalper.py`)
XGBoost 5분봉 예측 기반 단타 매매
```
매수: AI 상승 확률 ≥ 65%
매도: 익절(+1.5%) / 손절(-1.2%) / 트레일링 / AI 반전
```

**특징:**
- 5분마다 AI 재예측
- 하루 여러 번 진입 가능
- 동적 손익 관리

---

### 3. **복합 전략** (`bot_combined.py`)
변동성 돌파 + AI 필터 하이브리드
```
진입: 변동성 돌파 AND AI 확률 ≥ 60% (이중 필터)
청산: AI 기반 동적 관리
```

**특징:**
- 두 전략의 장점 결합
- 높은 승률 (이중 필터)
- AI 기반 스마트 청산

---

### 4. **일봉 AI 전략** (`main.py`)
XGBoost 일봉 예측 기반 스윙 트레이딩
```
1년치 일봉 학습 → 어제 일봉 기준 AI 판단 (1회)
확률 ≥ 60% → 당일 매수 → 익절/손절 대기
```

**특징:**
- 장기 보유 (스윙)
- 1일 1회 AI 판단
- 안정적 수익 추구

---

## 🚀 시작하기

### 1️⃣ 사전 준비

#### 필수 요구사항
- Python 3.8 이상
- 한국투자증권 계좌
- 한국투자증권 Open API 신청 (실전/모의)

#### API 신청 방법
1. [한국투자증권 홈페이지](https://www.koreainvestment.com/) 접속
2. `트레이딩 > Open API` 메뉴
3. 실전투자/모의투자 API 발급 신청
4. `APP_KEY`, `APP_SECRET`, `계좌번호` 발급 완료

---

### 2️⃣ 설치

```bash
# 저장소 클론
git clone https://github.com/seung23/ai-trading-bot.git
cd ai-trading-bot

# 가상환경 생성 (권장)
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 의존성 설치
pip install -r requirements.txt
```

---

### 3️⃣ 환경 설정

```bash
# .env.example을 .env로 복사
cp .env.example .env

# .env 파일 편집 (본인의 API 키 입력)
# APP_KEY, APP_SECRET, ACC_NO 등 설정
```

**`.env` 예시:**
```env
APP_KEY=your_real_app_key
APP_SECRET=your_real_app_secret
ACC_NO=12345678-01
MOCK_APP_KEY=your_mock_app_key
...
```

---

### 4️⃣ Telegram 알림 설정 (선택)

```bash
# 1. BotFather에서 봇 생성 후 토큰 발급
# 2. chat_id 확인
python get_chat_id.py

# 3. .env에 추가
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_CHAT_ID=123456789
```

---

## 💻 사용법

### 백테스팅 (전략 검증)

```bash
# 변동성 돌파 전략 백테스트
python backtester.py

# 파라미터 최적화
python optimizer.py
```

### 실전 매매

#### 일봉 AI 전략 (실전 모드)
```bash
python main.py
```

#### 변동성 돌파 (모의투자)
```bash
python bot_volatility.py
```

#### AI 스캘핑 (모의투자)
```bash
python bot_ai_scalper.py
```

#### 복합 전략 (모의투자)
```bash
python bot_combined.py
```

---

## 📈 백테스팅

백테스팅 예시 코드 (`backtester.py`):

```python
# 전략 파라미터 설정
K = 0.3  # 변동성 계수
TAKE_PROFIT = 0.015  # 익절 +1.5%
STOP_LOSS = -0.012   # 손절 -1.2%

# 백테스트 실행
python backtester.py
```

**출력 예시:**
```
========================================
백테스트 결과
========================================
거래 횟수: 45회
승률: 62.22%
총 수익률: +18.45%
Sharpe Ratio: 1.82
최대 낙폭(MDD): -3.21%
평균 보유 기간: 2.3일
```

---

## 📁 프로젝트 구조

```
ai-trading-bot/
│
├── main.py                    # 일봉 AI 전략 (실전/모의)
├── bot_volatility.py          # 변동성 돌파 전략 (모의)
├── bot_ai_scalper.py          # AI 스캘핑 전략 (모의)
├── bot_combined.py            # 복합 전략 (모의)
│
├── broker.py                  # 한국투자증권 API 래퍼
├── data_manager.py            # 데이터 수집 및 지표 계산
├── model.py                   # XGBoost 모델 학습/예측
├── telegram_notifier.py       # Telegram 알림
│
├── backtester.py              # 백테스팅 엔진
├── optimizer.py               # 파라미터 최적화
├── get_chat_id.py             # Telegram Chat ID 확인
│
├── .env.example               # 환경 변수 템플릿
├── requirements.txt           # Python 의존성
├── README.md                  # 프로젝트 문서 (이 파일)
└── .gitignore                 # Git 제외 파일
```

---

## ⚠️ 주의사항

### 🚨 **면책 조항 (Disclaimer)**

```
본 프로젝트는 교육 및 연구 목적으로 제작되었습니다.

1. 실제 투자 시 발생하는 손실에 대해 개발자는 책임지지 않습니다.
2. 금융 투자는 원금 손실 위험이 있으니 신중히 판단하세요.
3. 자동매매 프로그램 사용 전 충분한 테스트를 권장합니다.
4. 한국 금융 규제를 준수하여 사용하세요.
```

### 🔐 **보안**
- `.env` 파일을 절대 공개 저장소에 커밋하지 마세요
- API 키가 노출되면 즉시 재발급하세요
- 모의투자로 충분히 검증 후 실전 사용하세요

### 📊 **성능**
- 과거 성과가 미래 수익을 보장하지 않습니다
- 시장 상황에 따라 전략 성과가 크게 달라질 수 있습니다
- 정기적으로 모델을 재학습하세요

---

## 🤝 기여하기

버그 리포트, 기능 제안, Pull Request 환영합니다!

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## 📄 라이선스

이 프로젝트는 MIT 라이선스 하에 배포됩니다. 자세한 내용은 [LICENSE](LICENSE) 파일을 참조하세요.

---

## 🙏 감사의 말

- [한국투자증권](https://www.koreainvestment.com/) - Open API 제공
- [XGBoost](https://xgboost.readthedocs.io/) - 머신러닝 라이브러리
- [yfinance](https://github.com/ranaroussi/yfinance) - 금융 데이터 수집

---

<div align="center">

Made by seung23

</div>
