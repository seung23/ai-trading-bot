# KODEX KOSDAQ150 레버리지 모의투자 트레이딩 봇 종합 가이드

> 대상 종목: **KODEX KOSDAQ150 레버리지 (233740.KS)**
> 계좌: 한국투자증권 모의투자 계좌
> 목적: 3가지 단타 전략을 각각 실행하여 성과를 비교

---

## 목차

1. [프로젝트 구조](#1-프로젝트-구조)
2. [경제 용어 사전](#2-경제-용어-사전)
3. [공통 모듈 설명](#3-공통-모듈-설명)
   - [broker.py — 증권사 API 통신](#31-brokerpy--증권사-api-통신)
   - [data_manager.py — 데이터 수집 및 지표 계산](#32-data_managerpy--데이터-수집-및-지표-계산)
   - [model.py — XGBoost AI 모델](#33-modelpy--xgboost-ai-모델)
   - [telegram_notifier.py — 텔레그램 알림](#34-telegram_notifierpy--텔레그램-알림)
4. [Bot 1: bot_volatility.py — Larry Williams 변동성 돌파](#4-bot-1-bot_volatilitypy--larry-williams-변동성-돌파)
5. [Bot 2: bot_ai_scalper.py — XGBoost 5분봉 AI 단타](#5-bot-2-bot_ai_scalperpy--xgboost-5분봉-ai-단타)
6. [Bot 3: bot_combined.py — 복합 전략](#6-bot-3-bot_combinedpy--복합-전략)
7. [세 봇 비교 요약](#7-세-봇-비교-요약)
8. [파이썬 핵심 문법 해설](#8-파이썬-핵심-문법-해설)

---

## 1. 프로젝트 구조

```
tradingbot/
├── .env                        # API 키, 계좌번호 등 비밀 정보
├── broker.py                   # 한국투자증권 API 통신 (주문/잔고/시세)
├── data_manager.py             # yfinance 데이터 수집 + 기술적 지표 계산
├── model.py                    # XGBoost 학습/예측/저장
├── telegram_notifier.py        # 텔레그램 메시지 전송
├── main.py                     # 실전투자 일봉 전략 (이 문서와 무관)
├── backtester.py               # 백테스트 도구 (과거 데이터로 전략 검증)
├── bot_volatility.py           # ★ Bot 1: 래리 윌리엄스 변동성 돌파
├── bot_ai_scalper.py           # ★ Bot 2: XGBoost 5분봉 AI 단타
├── bot_combined.py             # ★ Bot 3: 변동성 돌파 + AI 복합
├── trade_log_volatility.csv    # Bot 1 매매 기록
├── trade_log_scalper.csv       # Bot 2 매매 기록
└── trade_log_combined.csv      # Bot 3 매매 기록
```

### 듀얼 토큰 구조

한국투자증권(KIS) API는 **실전 서버**와 **모의 서버**가 분리되어 있습니다.
그런데 **시세(가격) 조회는 실전 서버에서만 정확**합니다.
따라서 봇은 토큰을 **2개** 발급받아 사용합니다:

| 용도 | 서버 | 토큰 | 환경변수 |
|------|------|------|----------|
| 시세 조회 | 실전 (`URL_REAL`) | `token_real` | `APP_KEY`, `APP_SECRET` |
| 주문/잔고 | 모의 (`URL_MOCK`) | `token_mock` | `MOCK_APP_KEY`, `MOCK_APP_SECRET` |

```python
# 시세 조회 → 실전 서버 토큰 사용
current_price = broker.get_current_price(token_real, APP_KEY, APP_SECRET, URL_REAL, STOCK_CODE)

# 매수 주문 → 모의 서버 토큰 사용
res = broker.post_order(token_mock, MOCK_APP_KEY, MOCK_APP_SECRET, URL_MOCK, MOCK_ACC_NO, ...)
```

---

## 2. 경제 용어 사전

### 기본 용어

| 용어 | 설명 |
|------|------|
| **ETF** | Exchange Traded Fund. 여러 주식을 묶어 하나의 상품으로 만든 것. 주식처럼 거래소에서 실시간 매매 가능 |
| **레버리지 ETF** | 기초지수 변동의 **2배**를 추종하는 ETF. 코스닥이 1% 오르면 레버리지는 약 2% 오름 |
| **KODEX KOSDAQ150 레버리지** | 코스닥150 지수의 2배를 추종하는 삼성자산운용의 ETF (종목코드: 233740) |
| **코스닥(KOSDAQ)** | 한국의 기술주 중심 주식시장. 미국의 나스닥과 유사 |
| **단타 (데이 트레이딩)** | 당일 매수→당일 매도를 완결하는 초단기 매매 전략 |
| **스캘핑** | 단타보다 더 짧은 주기로 소액 수익을 반복적으로 취하는 전략 |
| **모의투자** | 가상 자금으로 실제 시장 가격에 맞춰 매매를 연습하는 시스템 |
| **캔들 (봉)** | 일정 시간 동안의 시가·고가·저가·종가를 하나의 막대로 표현한 차트 단위 |
| **5분봉** | 5분 단위로 만들어진 캔들. 장중 가격 흐름을 세밀하게 관찰 가능 |
| **일봉** | 하루 단위로 만들어진 캔들 |

### 가격 관련 용어

| 용어 | 설명 |
|------|------|
| **시가 (Open)** | 해당 시간 구간에서 가장 먼저 체결된 가격 |
| **고가 (High)** | 해당 구간 중 가장 높았던 가격 |
| **저가 (Low)** | 해당 구간 중 가장 낮았던 가격 |
| **종가 (Close)** | 해당 구간 마지막에 체결된 가격 |
| **거래량 (Volume)** | 해당 시간 동안 거래된 주식 수 |

### 매매 관련 용어

| 용어 | 설명 |
|------|------|
| **매수** | 주식을 사는 것 (Buy) |
| **매도** | 주식을 파는 것 (Sell) |
| **포지션** | 현재 보유하고 있는 주식 상태. "포지션이 있다" = 주식을 들고 있다 |
| **진입** | 매수하여 포지션을 잡는 것 |
| **청산** | 보유 주식을 매도하여 포지션을 없애는 것 |
| **체결** | 주문이 실제로 성사되는 것. 매수 주문을 넣었다고 바로 사지는 것이 아니고, 상대방(매도자)과 가격이 맞아야 체결됨 |
| **익절 (Take Profit)** | 수익이 난 상태에서 매도하여 이익을 확정하는 것 |
| **손절 (Stop Loss)** | 손실이 난 상태에서 더 큰 손실을 막기 위해 매도하는 것 |
| **수수료** | 매매할 때 증권사에 내는 비용. 모의투자는 왕복(매수+매도) 0.93% |
| **슬리피지 (Slippage)** | 주문 시점의 가격과 실제 체결 가격의 차이. 가격이 빠르게 움직일 때 발생 |

### 기술적 분석 용어 (지표)

| 용어 | 설명 |
|------|------|
| **이동평균선 (MA)** | Moving Average. 최근 N개 종가의 평균. MA5 = 최근 5개 봉의 평균 가격 |
| **RSI** | Relative Strength Index (상대강도지수). 0~100 사이 값으로, 70 이상이면 과매수(너무 많이 올랐다), 30 이하면 과매도(너무 많이 내렸다) |
| **볼린저 밴드 (BB)** | 이동평균 ± 표준편차 2배로 구성된 밴드. 가격이 상단에 닿으면 과열, 하단에 닿으면 과매도 신호 |
| **MACD** | Moving Average Convergence Divergence. 단기 이동평균과 장기 이동평균의 차이. 추세의 방향과 강도를 판단 |
| **MACD 히스토그램** | MACD와 시그널선의 차이. 양수면 상승 추세 강화, 음수면 하락 추세 강화 |
| **스토캐스틱 RSI** | RSI에 스토캐스틱 공식을 적용한 것. RSI보다 더 민감하게 과매수/과매도를 판단 |
| **ATR** | Average True Range (평균 진폭). 가격의 변동 폭을 나타내는 지표. 클수록 변동성이 큼 |
| **거래량 비율 (Vol_Ratio)** | 현재 거래량 ÷ 평균 거래량. 2.0 이상이면 평소 대비 2배 이상 거래가 활발한 것 |

### 전략 관련 용어

| 용어 | 설명 |
|------|------|
| **변동성 돌파** | 전일의 가격 변동폭을 기준으로, 당일 시가에서 일정 비율 이상 상승하면 매수하는 전략 |
| **트레일링 스탑** | 가격이 올라가면 매도 기준선도 함께 올려주는 방식. 수익을 최대한 키우면서 하락 반전 시 빠져나옴 |
| **XGBoost** | eXtreme Gradient Boosting. 여러 개의 결정 트리를 순차적으로 학습시키는 머신러닝 알고리즘. 테이블 형태 데이터에서 최고 성능을 보여주는 모델 중 하나 |
| **피처 (Feature)** | AI 모델에 입력으로 주는 특성값들. 이 봇에서는 RSI, MACD, 거래량 비율 등 26개의 기술적 지표가 피처 |
| **타겟 (Target)** | AI가 맞추려고 하는 정답. 이 봇에서는 "향후 6개 봉(30분) 내에 +1.5% 수익 도달 여부" (0 또는 1) |
| **확률 (Probability)** | AI가 예측한 "상승할 확률". 0.65 = 65% 확률로 상승할 것으로 예측 |
| **과적합 (Overfitting)** | AI가 학습 데이터에만 잘 맞고 새로운 데이터에는 잘 못 맞추는 현상 |

---

## 3. 공통 모듈 설명

### 3.1 broker.py — 증권사 API 통신

한국투자증권(KIS) OpenAPI와 HTTP 통신하여 시세 조회, 잔고 확인, 매수/매도 주문을 처리하는 모듈입니다.

#### TR_IDS 딕셔너리

```python
TR_IDS = {
    "REAL": {
        "balance_inquiry": "TTTC8908R",
        "stock_balance":   "TTTC8434R",
        "buy_order":       "TTTC0802U",
        "sell_order":      "TTTC0801U",
    },
    "MOCK": {
        "balance_inquiry": "VTTC8908R",
        "stock_balance":   "VTTC8434R",
        "buy_order":       "VTTC0802U",
        "sell_order":      "VTTC0801U",
    },
}
```

KIS API는 같은 기능이라도 실전/모의에 따라 **다른 거래 ID(tr_id)**를 사용합니다.
실전은 `T`로 시작, 모의는 `V`로 시작합니다.
이 딕셔너리를 사용하면 `mode="MOCK"` 또는 `mode="REAL"`만 바꿔서 같은 코드로 두 환경을 지원할 수 있습니다.

```python
# 사용 예: 모의투자 매수 주문의 tr_id를 가져옴
tr_id = TR_IDS["MOCK"]["buy_order"]  # → "VTTC0802U"
```

---

#### `get_access_token(app_key, app_secret, url_base)`

**역할**: KIS API를 사용하기 위한 **인증 토큰**을 발급받습니다.

```python
def get_access_token(app_key, app_secret, url_base):
    headers = {"content-type":"application/json"}
    body = {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "appsecret": app_secret
    }
    PATH = "oauth2/tokenP"
    URL = f"{url_base}/{PATH}"

    res = requests.post(URL, headers=headers, data=json.dumps(body))
    res_data = res.json()

    if 'access_token' in res_data:
        return res_data['access_token']
    else:
        print("❌ 토큰 발급 실패!")
        return None
```

**코드 해설:**

- `requests.post(URL, ...)` — HTTP POST 요청을 보냅니다. API 서버에 "나 로그인할게"라고 말하는 것
- `json.dumps(body)` — 파이썬 딕셔너리를 JSON 문자열로 변환. API는 JSON 형식으로 데이터를 주고받음
- `res.json()` — 서버 응답을 JSON → 파이썬 딕셔너리로 변환
- `f"{url_base}/{PATH}"` — f-string 문법. 변수를 문자열 안에 직접 삽입. 결과: `"https://openapi.koreainvestment.com:9443/oauth2/tokenP"`
- `res_data.get('access_token')` — 딕셔너리에서 안전하게 값을 가져옴. 키가 없으면 `None` 반환 (vs `res_data['access_token']`은 키가 없으면 에러)

---

#### `get_current_price(token, app_key, app_secret, url_base, stock_code)`

**역할**: 특정 종목의 **실시간 현재가**를 조회합니다.

```python
def get_current_price(token, app_key, app_secret, url_base, stock_code):
    PATH = "uapi/domestic-stock/v1/quotations/inquire-price"
    URL = f"{url_base}/{PATH}"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",   # 인증 토큰을 헤더에 포함
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": "FHKST01010100"               # 시세 조회용 tr_id (실전/모의 공통)
    }

    params = {
        "FID_COND_MRKT_DIV_CODE": "J",          # "J" = 주식 시장
        "FID_INPUT_ISCD": stock_code             # 종목 코드 (예: "233740")
    }

    res = requests.get(URL, headers=headers, params=params)
    res_data = res.json()

    if res_data.get('output'):
        return float(res_data['output']['stck_prpr'])  # stck_prpr = 주식 현재가
    else:
        return None
```

**코드 해설:**

- `requests.get(URL, headers=headers, params=params)` — HTTP GET 요청. POST와 달리 데이터를 URL 쿼리 파라미터로 전달
- `f"Bearer {token}"` — OAuth 인증 방식. "나는 이 토큰을 가진 사용자야"라고 서버에 알림
- `float(...)` — 문자열 → 실수 변환. API 응답은 `"17500"` 같은 문자열이므로 숫자로 변환 필요
- `'stck_prpr'` — KIS API가 정한 필드명. "주식 현재가(stock present price)"의 약어

---

#### `get_balance(token, app_key, app_secret, url_base, acc_no, stock_code, mode="MOCK")`

**역할**: 계좌의 **주문 가능 현금**(매수에 사용할 수 있는 돈)을 조회합니다.

```python
output = res_data.get('output', {})
cash = output.get('ord_psbl_cash') or output.get('nrcvb_buy_amt') or '0'
return int(cash)
```

**핵심 포인트:**

- `output.get('ord_psbl_cash') or output.get('nrcvb_buy_amt') or '0'`
  - 파이썬의 `or` 연산자 활용. 앞의 값이 `None`이나 빈 문자열(`""`)이면 다음 값을 시도
  - KIS API 버전에 따라 필드명이 다를 수 있어서 여러 필드명을 시도하는 방어적 코딩
- `int(cash)` — 현금은 정수(원 단위)로 변환

---

#### `get_stock_balance(...)` / `get_holding_quantity(...)`

**역할**:
- `get_stock_balance` → 특정 종목의 **매수 평균가** 반환
- `get_holding_quantity` → 특정 종목의 **보유 수량** 반환

```python
stocks = res_data.get('output1', [])   # 보유 종목 리스트
for s in stocks:                        # 각 종목을 순회
    if s.get('pdno') == stock_code:     # 우리가 찾는 종목 코드와 일치하면
        qty = s.get('hldg_qty') or '0'  # 보유 수량 추출
        return int(qty)
return 0                                # 못 찾으면 0
```

**코드 해설:**

- `for s in stocks:` — 리스트를 하나씩 순회. `stocks`가 `[{종목1 정보}, {종목2 정보}, ...]`이면 `s`에 하나씩 들어옴
- `s.get('pdno')` — `pdno` = Product Number (상품번호 = 종목코드)
- `s.get('hldg_qty') or s.get('cblc_qty13') or '0'` — 여러 필드명 시도 (API 버전 호환)

---

#### `post_order(...)` — 매수 주문

```python
def post_order(token, app_key, app_secret, url_base, acc_no, stock_code, quantity, price, mode="MOCK"):
    # ...
    body = {
        "CANO": acc_no,                # 계좌번호
        "ACNT_PRDT_CD": "01",          # 계좌 상품코드 (항상 "01")
        "PDNO": stock_code,            # 종목코드
        "ORD_DVSN": "00",              # 주문구분: "00" = 지정가 주문
        "ORD_QTY": str(quantity),       # 주문 수량 (문자열로 변환)
        "ORD_UNPR": str(int(price))     # 주문 단가 (문자열로 변환)
    }

    res = requests.post(URL, headers=headers, data=json.dumps(body))
    return res.json()
```

**코드 해설:**

- `"ORD_DVSN": "00"` — 지정가 주문. 내가 원하는 가격을 지정해서 주문. (vs "01" = 시장가: 현재 가격에 즉시 체결)
- `str(quantity)` — API가 숫자를 문자열로 요구하므로 변환
- `str(int(price))` — 소수점 제거 후 문자열 변환. 주식 가격은 정수 단위
- `return res.json()` — 응답을 딕셔너리로 반환. 호출하는 쪽에서 `res.get('rt_cd') == '0'`으로 성공 여부 확인

#### `post_sell_order(...)` — 매도 주문

매수와 구조가 동일하나, `tr_id`만 매도용(`sell_order`)을 사용합니다.

---

### 3.2 data_manager.py — 데이터 수집 및 지표 계산

야후 파이낸스(yfinance)에서 주가 데이터를 가져오고, 23개 이상의 기술적 지표를 계산합니다.

#### `fetch_large_data(ticker)`

**역할**: 60일치 5분봉 데이터 + 코스닥 지수를 수집합니다.

```python
def fetch_large_data(ticker):
    df = yf.download(tickers=ticker, period='60d', interval='5m')
```

**코드 해설:**

- `yf.download(...)` — yfinance 라이브러리로 주가 데이터를 다운로드
  - `tickers=ticker` — 다운로드할 종목 (`"233740.KS"`)
  - `period='60d'` — 최근 60일
  - `interval='5m'` — 5분봉 단위

```python
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
```

- `isinstance(A, B)` — A가 B 타입인지 확인하는 내장 함수 (True/False 반환)
- `pd.MultiIndex` — 판다스의 다중 인덱스. yfinance가 종목이 1개여도 가끔 멀티인덱스로 반환함
- `.get_level_values(0)` — 멀티인덱스의 첫 번째 레벨만 추출하여 일반 컬럼으로 변환

```python
    df = df.reset_index().rename(columns={
        'Datetime': '시간', 'Close': '종가', 'High': '고가',
        'Low': '저가', 'Open': '시가', 'Volume': '거래량'
    })
```

- `.reset_index()` — 인덱스를 일반 컬럼으로 변환. 시간 정보가 인덱스에 있으므로 컬럼으로 꺼냄
- `.rename(columns={...})` — 컬럼명을 영어 → 한글로 변경

```python
    index_data = yf.download(tickers='^KQ11', period='60d', interval='5m')
```

- `'^KQ11'` — 코스닥 종합지수의 yfinance 티커 코드
- 코스닥 지수를 함께 가져오는 이유: ETF가 코스닥을 추종하므로, 지수와의 괴리(Spread)도 AI 피처로 활용

```python
    df = pd.merge(df, index_data, on='시간', how='left').ffill()
```

- `pd.merge(df, index_data, on='시간', how='left')` — SQL의 LEFT JOIN과 동일. '시간' 기준으로 두 테이블을 합침
- `.ffill()` — Forward Fill. 빈 값(NaN)을 바로 위의 값으로 채움. 코스닥 지수 데이터가 빈 시간대를 채우기 위해 사용

---

#### `refresh_data(df_base, ticker)`

**역할**: 기존 60일 데이터에 **오늘의 최신 5분봉**을 덮어씌워 실시간 갱신합니다.

```python
def refresh_data(df_base, ticker):
    today = fetch_today_data(ticker)          # 오늘 5분봉만 다운로드
    if today is None or len(today) == 0:
        return df_base                         # 실패하면 기존 데이터 유지

    yesterday_end = today['시간'].iloc[0]      # 오늘 데이터의 시작점
    df_old = df_base[df_base['시간'] < yesterday_end].copy()  # 과거 데이터만 남김
    df_merged = pd.concat([df_old, today], ignore_index=True)  # 과거 + 오늘 합치기
    return df_merged
```

**코드 해설:**

- `.iloc[0]` — 인덱스 0번째(첫 번째) 행. 오늘 데이터의 첫 시간 = 09:00
- `df_base[df_base['시간'] < yesterday_end]` — 불리언 인덱싱. 조건을 만족하는 행만 필터링
- `.copy()` — 원본을 건드리지 않도록 복사본 생성 (파이썬 리스트의 `[:]`와 비슷)
- `pd.concat([A, B], ignore_index=True)` — 두 데이터프레임을 위아래로 붙임. `ignore_index=True`로 인덱스를 0부터 재번호

**왜 이렇게 하나?** AI가 예측할 때 최신 데이터가 필요합니다. 하지만 60일 전체를 매번 다시 다운로드하면 느리므로, 과거 데이터는 유지하고 오늘 부분만 교체합니다.

---

#### `add_indicators(df)`

**역할**: 데이터프레임에 23개 이상의 기술적 지표를 계산하여 새 컬럼으로 추가합니다.
이 지표들이 XGBoost 모델의 **입력 피처**가 됩니다.

##### 볼린저 밴드 (Bollinger Bands)

```python
bb = ta.bbands(df['종가'], length=20, std=2)
if bb is not None:
    df['BB_Lower'] = bb.iloc[:, 0]    # 하단 밴드
    df['BB_Mid'] = bb.iloc[:, 1]      # 중간선 (= 20일 이동평균)
    df['BB_Upper'] = bb.iloc[:, 2]    # 상단 밴드
    bb_width = df['BB_Upper'] - df['BB_Lower']
    df['BB_Pct'] = np.where(bb_width > 0, (df['종가'] - df['BB_Lower']) / bb_width, 0.5)
```

- `ta.bbands(...)` — pandas_ta 라이브러리로 볼린저 밴드 계산
- `bb.iloc[:, 0]` — 모든 행(`:`)의 0번째 열. 결과가 3개 열(하단/중간/상단)로 나오므로 인덱스로 분리
- `np.where(조건, 참일때, 거짓일때)` — 엑셀의 IF 함수와 동일
  - `bb_width > 0`이면 → `(종가 - 하단) / 밴드폭` 계산 (가격이 밴드 내 어디에 위치하는지 0~1 비율)
  - 아니면 → 0.5 (기본값)

##### MACD

```python
macd = ta.macd(df['종가'], fast=12, slow=26, signal=9)
if macd is not None:
    df['MACD'] = macd.iloc[:, 0]        # MACD 선
    df['MACD_Hist'] = macd.iloc[:, 1]   # MACD 히스토그램
    df['MACD_Sig'] = macd.iloc[:, 2]    # 시그널 선
```

- MACD = 12일 이동평균 - 26일 이동평균
- MACD가 양수 → 단기 상승 추세, 음수 → 단기 하락 추세
- 히스토그램 = MACD - 시그널. 추세의 가속/감속을 표현

##### 수익률 피처

```python
df['Ret_1'] = df['종가'].pct_change(1)    # 직전 대비 수익률
df['Ret_3'] = df['종가'].pct_change(3)    # 3봉 전 대비 수익률
df['Ret_6'] = df['종가'].pct_change(6)    # 6봉 전 대비 (= 30분 전)
df['Ret_12'] = df['종가'].pct_change(12)  # 12봉 전 대비 (= 1시간 전)
```

- `.pct_change(n)` — n개 전 값 대비 변화율. `(현재 - n개전) / n개전`
- 예: 종가가 `[100, 102, 105]`이면 `pct_change(1)` → `[NaN, 0.02, 0.0294]` (2%, 2.94%)

##### 이동평균 괴리도

```python
df['MA5_Dist'] = np.where(df['MA5'] > 0, (df['종가'] / df['MA5'] - 1) * 100, 0)
```

- 현재 가격이 5일 이동평균선 대비 몇 % 위/아래에 있는지 계산
- 양수 = 이동평균 위 (상승 추세), 음수 = 이동평균 아래 (하락 추세)

##### 타겟 (target) — AI가 맞추려는 "정답"

```python
lookahead = 6
profit_target = 0.015    # 1.5%
target = pd.Series(0, index=df.index)

for i in range(len(df) - lookahead):
    current_price = df['종가'].iloc[i]
    future_highs = df['고가'].iloc[i + 1:i + 1 + lookahead]
    if len(future_highs) > 0:
        max_profit = (future_highs / current_price - 1).max()
        if max_profit >= profit_target:
            target.iloc[i] = 1
df['target'] = target
```

**이 코드가 하는 일:**

"이 시점에서 매수했다면 향후 6개 봉(30분) 내에 +1.5% 수익을 달성할 수 있었는가?"

- `range(len(df) - lookahead)` — 마지막 6개 봉은 미래 데이터가 없으므로 제외
- `df['고가'].iloc[i + 1:i + 1 + lookahead]` — 슬라이싱. 현재 봉 다음부터 6개 봉의 고가를 가져옴
- `(future_highs / current_price - 1).max()` — 6개 봉 중 가장 높았던 가격 기준 최대 수익률
- `target.iloc[i] = 1` — 1.5% 이상 수익 가능했으면 1(매수 신호), 아니면 0(대기)

**비유**: 시험 채점표를 만드는 것. 과거 데이터에서 "이때 샀으면 돈 벌었을까?"를 계산해서 정답지를 만들고, AI에게 "이 패턴을 보고 정답을 맞춰봐"라고 학습시킴.

---

#### `get_feature_columns(df)`

```python
FEATURES = [
    '종가', 'MA5', 'MA20', 'RSI', 'BB_Pct', 'MACD', 'MACD_Hist',
    'StochRSI_K', 'StochRSI_D', 'ATR', 'Vol_Ratio', 'Vol_Spike',
    'Body_Ratio', 'Ret_1', 'Ret_3', 'Ret_6', 'Ret_12',
    'MA5_Dist', 'MA20_Dist', 'Intraday_Pos', 'VOL', 'Vol_6', '거래량',
]
FEATURES_WITH_INDEX = FEATURES + ['KQ_Ret_1', 'KQ_Ret_6', 'Spread']

def get_feature_columns(df):
    all_features = FEATURES_WITH_INDEX
    return [f for f in all_features if f in df.columns]
```

- `[f for f in all_features if f in df.columns]` — 리스트 컴프리헨션. 전체 피처 목록 중 실제로 데이터프레임에 존재하는 것만 필터링
- 코스닥 지수 데이터가 없는 경우(`KQ_Ret_1` 등이 없는 경우)에도 에러 없이 동작하도록 하는 방어적 코딩

---

### 3.3 model.py — XGBoost AI 모델

#### `train_model(df, features)`

**역할**: XGBoost 분류 모델을 학습합니다.

```python
def train_model(df, features):
    X = df[features]    # 피처 (입력 데이터)
    y = df['target']    # 타겟 (정답 라벨: 0 또는 1)

    # 시계열이므로 shuffle=False (섞지 않음!)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, shuffle=False
    )
```

**왜 `shuffle=False`인가?**

주가 데이터는 **시간 순서**가 중요합니다. 미래 데이터로 과거를 예측하면 의미가 없으므로:
- 앞쪽 80% = 학습 데이터 (과거)
- 뒤쪽 20% = 테스트 데이터 (최근)

```python
    # 클래스 불균형 보정
    pos_count = y_train.sum()       # target=1인 개수 (매수 신호)
    neg_count = len(y_train) - pos_count  # target=0인 개수 (대기)
    scale_weight = neg_count / pos_count if pos_count > 0 else 1.0
```

**클래스 불균형이란?**

대부분의 시간에 주가는 +1.5% 이상 오르지 않습니다. 그래서 target=1(매수 기회)은 전체의 10~20% 정도.
이대로 학습하면 AI가 "항상 0(대기)이라고 예측하면 80% 정확도"라고 학습해버림.
`scale_pos_weight`로 소수 클래스에 가중치를 줘서 이 문제를 보정합니다.

```python
    model = XGBClassifier(
        n_jobs=-1,                # CPU 코어를 전부 사용하여 병렬 학습
        n_estimators=300,         # 결정 트리를 300개 만듦
        learning_rate=0.05,       # 학습률: 각 트리가 조금씩만 학습 (과적합 방지)
        max_depth=6,              # 트리의 최대 깊이 (너무 깊으면 과적합)
        min_child_weight=5,       # 리프 노드의 최소 데이터 수 (과적합 방지)
        subsample=0.8,            # 각 트리에 데이터의 80%만 사용 (과적합 방지)
        colsample_bytree=0.8,     # 각 트리에 피처의 80%만 사용 (과적합 방지)
        reg_alpha=0.1,            # L1 정규화 (불필요한 피처 제거 유도)
        reg_lambda=1.0,           # L2 정규화 (가중치를 작게 유지)
        scale_pos_weight=scale_weight,  # 클래스 불균형 보정
        eval_metric='logloss',    # 평가 지표: 로그 손실 (분류 문제에 적합)
        random_state=42,          # 재현성을 위한 랜덤 시드 고정
    )
```

**XGBoost 하이퍼파라미터 설명:**

`n_estimators=300`을 비유하면: 300명의 전문가가 각자 의견을 내고, 다수결로 최종 결정.
각 전문가(트리)는 이전 전문가가 틀린 부분을 보완하도록 학습됩니다.

```python
    model.fit(
        X_train, y_train,
        eval_set=[(X_test, y_test)],   # 학습 중 테스트 데이터로 성능 모니터링
        verbose=False,                  # 학습 과정 출력 안 함
    )
```

- `.fit()` — 모델 학습 실행. 데이터를 보여주고 패턴을 찾도록 함

---

#### `predict_signal(model, row_data, features, threshold=0.60)`

**역할**: 하나의 5분봉 데이터에 대해 "매수해야 하나?"를 예측합니다.

```python
def predict_signal(model, row_data, features, threshold=0.60):
    input_df = pd.DataFrame([row_data[features].values], columns=features)
    prob = model.predict_proba(input_df)[0][1]

    if prob >= threshold:
        return 'BUY', prob
    return 'HOLD', prob
```

**코드 해설:**

- `row_data[features].values` — 필요한 피처 값만 추출하여 numpy 배열로 변환
- `pd.DataFrame([...], columns=features)` — 1행짜리 데이터프레임 생성 (모델 입력 형식에 맞춤)
- `model.predict_proba(input_df)` — 확률 예측. 결과: `[[0.35, 0.65]]` (0일 확률 35%, 1일 확률 65%)
- `[0][1]` — 첫 번째 행`[0]`의 두 번째 값`[1]` = 상승 확률 (target=1일 확률)
- `threshold` — 이 확률 이상이면 'BUY' 신호. 봇마다 다른 값 사용 (65%, 60%)

---

#### `save_model(model, filename)` / `load_model(filename)`

```python
def save_model(model, filename="trading_brain.json"):
    model.save_model(filename)

def load_model(filename="trading_brain.json"):
    if not os.path.exists(filename):
        return None
    loaded = XGBClassifier()
    loaded.load_model(filename)
    return loaded
```

- XGBoost는 `.json` 파일로 모델을 저장/로드 가능
- `os.path.exists(filename)` — 파일이 존재하는지 확인 (True/False)
- 봇은 매번 실행 시 새로 학습하고 저장하지만, 다음 실행 시에는 저장된 모델을 로드하지 않고 다시 학습 (최신 데이터 반영을 위해)

---

### 3.4 telegram_notifier.py — 텔레그램 알림

#### `TelegramNotifier` 클래스

```python
class TelegramNotifier:
    def __init__(self, bot_token, chat_id):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
```

**클래스(class) 설명:**

- `class`는 관련된 데이터와 기능을 하나로 묶는 설계도
- `__init__`은 **생성자** — 객체가 만들어질 때 자동 호출되는 함수
- `self`는 "자기 자신"을 가리키는 변수. `self.bot_token`은 이 객체의 `bot_token` 속성

```python
# 사용 예:
notifier = TelegramNotifier("토큰값", "채팅방ID")  # __init__ 호출됨
notifier.send_message("안녕하세요!")                 # 메시지 전송
```

#### `send_message(self, text)`

```python
def send_message(self, text):
    if not self.bot_token or not self.chat_id:
        return  # 설정 안 되어있으면 그냥 무시

    try:
        payload = {
            'chat_id': self.chat_id,
            'text': text,
            'parse_mode': 'HTML'     # HTML 태그 지원 (<b>굵게</b> 등)
        }
        response = requests.post(self.base_url, data=payload, timeout=10)
    except Exception as e:
        print(f"⚠️ Telegram 전송 에러: {e}")
```

- `try ... except` — 예외 처리. 네트워크 오류 등이 나도 봇이 죽지 않도록 함
- `timeout=10` — 10초 안에 응답이 없으면 포기 (무한 대기 방지)
- `parse_mode='HTML'` — 텔레그램에서 `<b>굵은글씨</b>` 같은 HTML 형식 지원

---

## 4. Bot 1: bot_volatility.py — Larry Williams 변동성 돌파

### 4.1 전략 개요

**래리 윌리엄스(Larry Williams)**는 1987년 세계 선물 트레이딩 대회에서 1년간 11,376%의 수익률을 기록한 전설적인 트레이더입니다. 그의 **변동성 돌파 전략**은 다음과 같습니다:

```
목표가 = 당일 시가 + (전일 고가 - 전일 저가) × K
```

- **전일 고가 - 전일 저가** = 전일의 가격 변동폭 (어제 하루 동안 가격이 얼마나 움직였는지)
- **K** = 돌파 계수 (0.0 ~ 1.0 사이 값). 작을수록 공격적, 클수록 보수적
- **목표가**를 돌파(현재가 ≥ 목표가)하면 → "오늘은 강한 상승세"로 판단하고 매수
- **장 마감 전에 무조건 청산** (하루 단위 전략)

**예시:**
- 어제 고가: 17,500원, 저가: 17,000원 → 변동폭 = 500원
- 오늘 시가: 17,200원, K = 0.3
- 목표가 = 17,200 + 500 × 0.3 = **17,350원**
- 오늘 중 현재가가 17,350원 이상 → 매수!

### 4.2 K 값의 의미

- `K = 0.3` (이 봇의 설정): 전일 변동폭의 30%만 올라가도 돌파로 인정
  - KODEX 150 레버리지는 코스닥 지수를 추종하는 ETF라서 변동폭이 작음
  - 변동폭이 작으니 K를 낮춰서 돌파 기회를 확보
- K가 작을수록 → 돌파 기준이 낮아 → 매수 기회 많음 → 하지만 거짓 돌파(잠깐 올랐다 내림)에 걸릴 위험도 증가
- K가 클수록 → 돌파 기준이 높아 → 매수 기회 적음 → 하지만 진짜 상승장에서만 진입

### 4.3 상태 머신 (State Machine)

이 봇은 3가지 **상태**를 순환합니다:

```
WAITING  ──(돌파!)──▶  BOUGHT  ──(15:15)──▶  SOLD  ──(장마감)──▶  종료
    │                                            │
    └──(슬리피지/잔고부족)──▶  SOLD ─────────────┘
```

- **WAITING**: 목표가 돌파를 감시하며 대기
- **BOUGHT**: 매수 완료. 보유 중. 15:15까지 기다림
- **SOLD**: 청산 완료. 장 마감까지 아무것도 안 함

### 4.4 전체 실행 흐름

```
1. 토큰 2개 발급 (실전/모의)
2. 전일 고가·저가 → 변동폭 계산
3. 미청산 포지션 확인 (어제 안 팔고 남은 것 있는지)
4. 장 시작 대기 (09:00)
5. 시가 캡처 → 목표가 계산
6. 매 1분 루프:
   ├─ WAITING: 현재가 ≥ 목표가? → 슬리피지 체크 → 매수
   ├─ BOUGHT: 15:15 됐나? → 청산
   └─ SOLD: 장 마감까지 대기
7. 15:20 → 봇 종료
```

### 4.5 핵심 함수 상세 설명

#### `get_yesterday_range()`

```python
def get_yesterday_range():
    df = yf.download(TICKER, period='5d', interval='1d')
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    today = date.today()
    df_past = df[df.index.date < today]

    if len(df_past) == 0:
        return None, None, None

    yesterday = df_past.iloc[-1]
    return float(yesterday['High']), float(yesterday['Low']), float(yesterday['High'] - yesterday['Low'])
```

**코드 해설:**

- `period='5d'` — 최근 5일 일봉을 가져옴 (공휴일 등으로 전일 데이터가 없을 수 있으므로 여유 있게)
- `date.today()` — 오늘 날짜 (`datetime.date` 객체)
- `df.index.date` — 각 행의 인덱스(날짜시간)에서 날짜 부분만 추출
- `df[df.index.date < today]` — 오늘 이전 데이터만 필터링 (장중에 실행하면 오늘 일봉이 아직 미완성이므로 제외)
- `.iloc[-1]` — 마지막 행 = 가장 최근 완료된 거래일 = "전일"
- 반환값: `(전일 고가, 전일 저가, 전일 변동폭)`

**왜 `period='1d'`가 아니라 `'5d'`인가?**

월요일에 실행하면 `period='1d'`는 오늘(월요일) 데이터만 줄 수 있습니다. 전일(금요일) 데이터를 확실히 얻으려면 넉넉하게 5일을 요청합니다.

---

#### `get_today_open()`

```python
def get_today_open():
    df = yf.download(TICKER, period='1d', interval='5m')
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    if df is None or len(df) == 0:
        return None

    return float(df.iloc[0]['Open'])
```

**역할**: 당일 시가(장 시작 가격)를 가져옵니다.

**왜 5분봉 데이터에서 시가를 가져오나?**

`get_current_price()`로 현재가를 가져오면, 시간이 지남에 따라 값이 변합니다.
시가는 장 시작 시점의 가격으로 **하루 종일 고정**이어야 하는데, 현재가로 대체하면 봇을 재시작할 때마다 목표가가 바뀌는 문제가 생깁니다.

5분봉의 **첫 번째 캔들의 Open 가격** = 09:00에 형성된 시가 → 항상 동일한 값.

---

#### 메인 루프: 돌파 감지 + 슬리피지 체크

```python
if current_price >= target_price:
    # 슬리피지 체크: 목표가 대비 너무 올라갔으면 스킵
    slippage = (current_price - target_price) / target_price
    if slippage > MAX_SLIPPAGE:
        print(f"⚠️ 슬리피지 초과!")
        state = "SOLD"  # 당일 매매 포기
        continue

    # 매수 진행
    cash = broker.get_balance(...)
    buy_qty = int((cash * POSITION_RATIO) / current_price)
    # ...
```

**슬리피지 체크가 필요한 이유:**

1분마다 가격을 확인하므로, 그 1분 사이에 가격이 급등할 수 있습니다.
예: 목표가 17,350원인데 다음 체크 때 이미 18,000원 → 너무 비싸게 사게 됨.
`MAX_SLIPPAGE = 0.01` (1%)이므로, 목표가 대비 1% 이상 올라가 있으면 매수를 포기합니다.

#### 체결 확인 루프

```python
for _ in range(10):
    time.sleep(2)
    bp = broker.get_stock_balance(...)
    if bp > 0:
        bought_price = bp
        holding_qty = broker.get_holding_quantity(...)
        break
else:
    bought_price = current_price
    holding_qty = buy_qty
```

**코드 해설:**

- `for _ in range(10):` — 10번 반복. `_`는 "변수를 쓸 일이 없다"는 관례적 표현
- `time.sleep(2)` — 2초 대기. 총 최대 20초 동안 체결 확인
- `break` — for 루프를 즉시 탈출
- **`for...else` 구문** — 파이썬 특유의 문법! `for`가 `break` 없이 끝까지 돌면 `else` 블록 실행
  - `break`로 탈출했으면 → `else` 실행 안 됨 (체결 확인 성공)
  - 10번 다 돌았는데도 체결 확인 안 됐으면 → `else` 실행 (주문 가격/수량으로 대체)

---

#### 장마감 청산

```python
if now.hour == 15 and now.minute >= 15:
    res = broker.post_sell_order(
        token_mock, MOCK_APP_KEY, MOCK_APP_SECRET, URL_MOCK, MOCK_ACC_NO,
        STOCK_CODE, holding_qty, current_price, mode="MOCK")

    if res.get('rt_cd') == '0':
        profit_rate = ((current_price - bought_price) / bought_price - COMMISSION) * 100
        log_trade("매도", current_price, holding_qty, profit=profit_rate, reason="장마감 청산")
        state = "SOLD"
```

**수익률 계산:**

```python
profit_rate = ((current_price - bought_price) / bought_price - COMMISSION) * 100
```

- `(current_price - bought_price) / bought_price` — 순수 수익률 (예: 매수 17,000, 매도 17,200 → 0.01176 = 1.176%)
- `- COMMISSION` — 수수료 0.0093 (0.93%) 차감
- `× 100` — 백분율로 변환
- 결과: `(0.01176 - 0.0093) × 100 = 0.25%` (수수료 반영 후 실제 수익률)

---

### 4.6 유틸리티 함수

#### `log_trade(side, price, quantity, profit=0, reason="")`

```python
def log_trade(side, price, quantity, profit=0, reason=""):
    file_exists = os.path.isfile(LOG_FILE)
    with open(LOG_FILE, mode='a', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(['시간', '구분', '가격', '수량', '순수익률', '사유', '참고사항'])
        time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        writer.writerow([time_str, side, price, quantity, f"{profit:.2f}%", reason, "[모의] 수수료 왕복 0.93%"])
```

**코드 해설:**

- `os.path.isfile(LOG_FILE)` — 파일이 존재하는지 확인. 처음이면 헤더 행을 먼저 씀
- `open(..., mode='a', ...)` — 'a' = append (추가). 기존 내용 뒤에 이어서 씀. 'w'는 덮어쓰기
- `newline=''` — CSV 모듈 사용 시 빈 줄 삽입 방지 (Windows 환경에서 필요)
- `encoding='utf-8-sig'` — BOM 포함 UTF-8. 엑셀에서 한글이 깨지지 않게 하려면 이 인코딩 사용
- `csv.writer(f)` — CSV 파일에 쓰기 위한 객체 생성
- `writer.writerow([...])` — 리스트를 CSV 한 줄로 작성
- `f"{profit:.2f}%"` — 소수점 2자리까지 표시. 예: `1.23%`
- `with open(...) as f:` — **컨텍스트 매니저**. `with` 블록이 끝나면 파일이 자동으로 닫힘 (안전)

---

#### `load_unclosed_position()`

```python
def load_unclosed_position():
    if not os.path.isfile(LOG_FILE):
        return 0, 0
    df = pd.read_csv(LOG_FILE, encoding='utf-8-sig')
    if len(df) == 0:
        return 0, 0
    last = df.iloc[-1]
    if last['구분'] == '매수':
        return float(last['가격']), int(last['수량'])
    return 0, 0
```

**역할**: 봇이 중간에 꺼졌다가 재시작했을 때, 아직 매도하지 않은 포지션을 복구합니다.

**로직**: CSV의 마지막 행이 '매수'이면 → 아직 '매도'를 안 한 것 → 미청산 포지션 존재 → 가격과 수량을 반환

---

#### `is_market_open()` / `wait_for_market_open()`

```python
def is_market_open():
    now = datetime.now()
    return (9 <= now.hour < 15) or (now.hour == 15 and now.minute < 20)
```

- 한국 주식 시장 시간: 09:00 ~ 15:30 (15:20까지를 장중으로 취급)
- `or` 연산자로 두 조건을 결합: 9시~14시 **또는** 15시이면서 20분 미만

```python
def wait_for_market_open():
    while True:
        now = datetime.now()
        if now.hour >= 9:
            return
        remaining = (9 - now.hour - 1) * 3600 + (60 - now.minute) * 60
        if remaining > 60:
            print(f"⏰ 장 시작 대기 중... ({remaining // 60}분 남음)")
            time.sleep(60)
        else:
            time.sleep(10)
```

- `while True:` — 무한 루프. `return`으로 탈출
- `//` — 정수 나눗셈 (소수점 버림). `150 // 60 = 2`
- 1분보다 많이 남았으면 1분마다, 1분 이하 남았으면 10초마다 체크

---

## 5. Bot 2: bot_ai_scalper.py — XGBoost 5분봉 AI 단타

### 5.1 전략 개요

AI(XGBoost)가 5분봉 데이터의 기술적 지표를 분석하여 "상승 확률"을 예측합니다.
확률이 높으면 매수, 수익이 나면 익절, 손실이 나면 손절. 하루에 **여러 번** 매매할 수 있습니다.

```
매수 조건: AI 상승 확률 ≥ 65%
매도 조건: 4가지 중 하나라도 해당되면 즉시 매도
  1. 익절: 수익률 ≥ +1.5%
  2. 손절: 수익률 ≤ -1.2%
  3. 트레일링 스탑: 고점 대비 0.5% 하락 (수익 1% 이상일 때 활성화)
  4. AI 반전: 확률 < 40%이면서 수익 중 → 매도
```

### 5.2 이중 모니터링 간격

```
가격 체크: 매 1분 (CHECK_INTERVAL = 60초)
  → 손절/트레일링 스탑은 빠르게 반응해야 하므로

AI 예측: 매 5분 (AI_REFRESH_INTERVAL = 300초)
  → 5분봉 데이터가 갱신되는 주기에 맞춤
  → 그 사이에는 마지막 AI 확률(last_prob)을 재사용
```

**왜 분리했나?**

5분마다만 가격을 체크하면, 그 사이에 -3% 급락이 발생해도 손절(-1.2%)이 작동하지 않습니다.
가격은 1분마다 체크하되, AI 예측은 5분봉 데이터가 바뀔 때만 갱신하면 효율적입니다.

### 5.3 트레일링 스탑 상세 설명

```
가격 흐름:  17,000(매수) → 17,100 → 17,200(+1.18%) → 17,250(+1.47%)
            → 17,300(+1.76%, 고점 갱신) → 17,250 → 17,200
                                                          ↑ 고점 17,300 대비 -0.58%
                                                            → 트레일링 스탑 발동! (0.5% 초과)
```

1. **활성화 조건**: 수익률이 +1.0% 이상 도달
2. **활성화 후**: 가격이 올라갈 때마다 `highest_price`(고점)를 갱신
3. **청산 조건**: 현재가가 고점 대비 0.5% 하락하면 매도

```python
# 고점 갱신
if current_price > highest_price:
    highest_price = current_price

# 트레일링 활성화 체크
if not trailing_active and profit_rate >= TRAIL_ACTIVATE:
    trailing_active = True

# 트레일링 스탑 발동 체크
if trailing_active:
    drop = (current_price - highest_price) / highest_price
    if drop <= -TRAIL_STOP:
        sell_reason = f"트레일링스탑(고점 {highest_price:,.0f}→{current_price:,.0f})"
```

**비유**: 산을 올라가는 중에, "여기까지 올라왔으니 이제부터는 아래로 0.5% 이상 내려가면 하산하자"라고 정하는 것. 정상에서 약간 내려온 지점에서 내려오므로 수익을 꽤 지켜가면서도 추가 상승의 기회를 놓치지 않습니다.

### 5.4 전체 실행 흐름

```
1. 토큰 2개 발급
2. 60일 5분봉 데이터 수집 → 23개 지표 계산 → XGBoost 학습
3. 미청산 포지션 복구
4. 장 시작 대기 (09:00)
5. 매 1분 루프:
   ├─ 현재가 조회
   ├─ 5분 주기: 5분봉 데이터 갱신 + AI 확률 갱신
   ├─ 미보유:
   │   └─ AI 확률 ≥ 65% → 매수
   └─ 보유 중:
       ├─ 익절(+1.5%) → 매도
       ├─ 손절(-1.2%) → 매도
       ├─ 트레일링 스탑 → 매도
       ├─ AI 반전(<40% + 수익 중) → 매도
       └─ 매도 후 → 다시 미보유 상태 (재진입 가능)
6. 15:20 장 마감 → 잔여 포지션 강제 청산 → 종료
```

### 5.5 핵심 코드 상세 설명

#### AI 예측 캐싱 메커니즘

```python
last_data_refresh = 0     # 마지막 데이터 갱신 시각 (Unix timestamp)
last_prob = 0.0           # 마지막 AI 예측 확률

while True:
    # ... 현재가 조회 ...

    # 5분마다 AI 갱신
    current_time = time.time()
    if current_time - last_data_refresh > AI_REFRESH_INTERVAL:
        df_base = data_manager.refresh_data(df_base, TICKER)
        df_live = data_manager.add_indicators(df_base.copy())
        if df_live is not None and len(df_live) > 0:
            latest = df_live.iloc[-1]
            _, last_prob = ai_model.predict_signal(xgb_model, latest, features, BUY_THRESH)
        last_data_refresh = current_time

    prob = last_prob    # 1분 체크에서는 캐싱된 확률 사용
    signal = 'BUY' if prob >= BUY_THRESH else 'HOLD'
```

**코드 해설:**

- `time.time()` — 현재 시각을 **Unix 타임스탬프**(1970년 1월 1일부터 경과한 초)로 반환. 예: `1707724800.0`
- `current_time - last_data_refresh > AI_REFRESH_INTERVAL` — 마지막 갱신으로부터 300초(5분) 이상 경과했는지 확인
- `last_prob` — 5분마다 갱신된 확률을 저장. 그 사이 1분 체크에서는 이 값을 재사용

#### 매도 조건 우선순위

```python
sell_reason = None

if profit_rate >= TAKE_PROFIT:                              # 1순위: 익절
    sell_reason = f"익절({profit_rate:.2%})"
elif profit_rate <= STOP_LOSS:                              # 2순위: 손절
    sell_reason = f"손절({profit_rate:.2%})"
elif trailing_active:                                        # 3순위: 트레일링
    drop = (current_price - highest_price) / highest_price
    if drop <= -TRAIL_STOP:
        sell_reason = f"트레일링스탑(...)"
elif prob < SELL_THRESH and profit_rate > 0:                 # 4순위: AI 반전
    sell_reason = f"AI반전({prob:.0%}, ...)"
```

- `if ... elif ... elif ...` — **첫 번째로 참인 조건만** 실행. 여러 조건이 동시에 참이어도 상위 조건이 우선
- `profit_rate:.2%` — 소수점 2자리 백분율 포맷. `0.0156` → `1.56%`
- 4순위 AI 반전은 `profit_rate > 0`(수익 중)일 때만 작동. 손실 중에 AI 반전으로 팔면 손절보다 나빠질 수 있음

#### 포지션 초기화 (재진입 가능)

```python
if sell_reason:
    res = broker.post_sell_order(...)
    if res.get('rt_cd') == '0':
        log_trade("매도", ...)
        trade_count += 1
        # 포지션 초기화 → 다시 매수 대기 상태로
        bought_price = 0
        holding_qty = 0
        highest_price = 0
        trailing_active = False
```

Bot 1(변동성)과 달리, 매도 후 `state = "SOLD"`로 바꾸지 않습니다.
`bought_price = 0`으로 초기화하면 다음 루프에서 `if bought_price == 0:` 조건이 참이 되어 다시 매수를 시도합니다.

---

## 6. Bot 3: bot_combined.py — 복합 전략

### 6.1 전략 개요

Bot 1(변동성 돌파)과 Bot 2(AI 단타)를 결합한 전략입니다.

```
진입: 변동성 돌파 AND AI 확률 ≥ 60% (이중 필터)
청산: AI 기반 (익절/손절/트레일링/AI반전) — 시간 기반이 아님
하루 1회 진입 (변동성 돌파는 1일 1회 이벤트)
```

**Bot 1과의 차이점:**
- Bot 1은 돌파만으로 매수 → Bot 3은 돌파 + AI 동의가 모두 필요
- Bot 1은 15:15에 시간 기반 청산 → Bot 3은 AI가 판단하여 청산

**Bot 2와의 차이점:**
- Bot 2는 AI 확률만으로 매수 → Bot 3은 돌파가 먼저 발생해야 AI 확인
- Bot 2는 하루 여러 번 매매 → Bot 3은 하루 1회만

### 6.2 이중 필터의 장점

```
시나리오 A (Bot 1만): 돌파 발생 → 매수 → 거짓 돌파여서 하락 → 손실
시나리오 B (Bot 3):   돌파 발생 → AI 확률 45% → AI가 "아직이야" → 매수 안 함 → 손실 회피!

시나리오 C (Bot 2만): AI 확률 70% → 매수 → 횡보 장세에서 수수료만 날림
시나리오 D (Bot 3):   AI 확률 70% → 그런데 돌파 안 됨 → 매수 안 함 → 수수료 절약!
```

두 조건을 동시에 충족해야 하므로 매매 빈도는 줄지만, 신호의 정확도는 높아집니다.

### 6.3 상태 머신

```
WAITING  ──(돌파+AI)──▶  BOUGHT  ──(AI청산)──▶  SOLD  ──(장마감)──▶  종료
    │                                              │
    └──(잔고부족)────────▶  SOLD ──────────────────┘
```

Bot 2와 달리 **SOLD 이후 재진입 없음** (하루 1회 진입 제한).

### 6.4 핵심 코드 상세 설명

#### 이중 조건 체크

```python
if state == "WAITING":
    is_breakout = current_price >= target_price      # 변동성 돌파 조건
    is_ai_ok = prob >= BUY_THRESH                    # AI 확률 조건 (≥ 60%)

    if is_breakout:
        volatility_triggered = True                  # 돌파 사실 기록 (리포팅용)

    status = ""
    if is_breakout and is_ai_ok:
        status = "🔥 이중 조건 충족!"
    elif is_breakout:
        status = f"⚡ 돌파 O, AI X ({prob:.0%} < {BUY_THRESH*100:.0f}%)"
    else:
        status = "대기"

    if is_breakout and is_ai_ok:
        # 매수 실행!
```

**코드 해설:**

- `is_breakout and is_ai_ok` — `and` 연산자: 두 조건이 **모두 True**여야 전체가 True
- `volatility_triggered = True` — 돌파는 했지만 AI가 거절한 경우를 추적. 장 마감 시 "돌파는 있었으나 AI 미충족" 리포트
- `BUY_THRESH = 0.60` — Bot 2(65%)보다 낮음. 변동성 돌파로 이미 1차 필터링되었으므로 AI 기준을 완화

#### 장마감 리포팅

```python
if not is_market_open():
    if state == "BOUGHT":
        # 강제 청산
    else:
        if volatility_triggered:
            notify(notifier, "⏹️ <b>장 마감</b>", "돌파 발생했으나 AI 미충족으로 매매 없음")
        else:
            notify(notifier, "⏹️ <b>장 마감</b>", "오늘은 돌파 없음. 매매 없이 종료.")
```

`volatility_triggered` 플래그 덕분에 "돌파는 했는데 AI가 막았다"를 구분하여 전략 효과를 분석할 수 있습니다.

#### 청산 후 재진입 차단

```python
if sell_reason:
    res = broker.post_sell_order(...)
    if res.get('rt_cd') == '0':
        # ...
        state = "SOLD"       # ← Bot 2는 bought_price=0으로만 초기화했지만,
        bought_price = 0     #    Bot 3은 state를 "SOLD"로 바꿔서
        holding_qty = 0      #    "SOLD" 상태의 루프(대기만 함)로 빠짐
```

`state = "SOLD"`가 핵심. Bot 2는 `state`를 사용하지 않고 `bought_price == 0`으로 매수/미보유를 구분하지만, Bot 3은 명시적으로 `state`를 "SOLD"로 바꿔서 당일 추가 진입을 차단합니다.

---

## 7. 세 봇 비교 요약

| 항목 | Bot 1: Volatility | Bot 2: AI-Scalper | Bot 3: Combined |
|------|-------------------|-------------------|-----------------|
| **전략 유형** | Rule-based (규칙 기반) | ML-based (머신러닝) | Hybrid (하이브리드) |
| **진입 조건** | 변동성 돌파 | AI 확률 ≥ 65% | 돌파 AND AI ≥ 60% |
| **청산 방식** | 15:15 시간 기반 | AI + 트레일링 + 손익 | AI + 트레일링 + 손익 |
| **일일 매매 횟수** | 최대 1회 | 여러 번 가능 | 최대 1회 |
| **AI 사용** | X | O | O (진입 필터 + 청산) |
| **모니터링 간격** | 1분 | 가격 1분 / AI 5분 | 5분 |
| **장점** | 단순, 검증된 전략 | 적응적, 다회 매매 | 높은 정확도 |
| **단점** | 거짓 돌파에 취약 | AI 오류 가능 | 매매 기회 적음 |
| **K 값** | 0.3 | - | 0.3 |
| **익절** | - (시간 청산) | +1.5% | +1.5% |
| **손절** | - (시간 청산) | -1.2% | -1.2% |
| **트레일링** | X | O (+1% → -0.5%) | O (+1% → -0.5%) |
| **로그 파일** | trade_log_volatility.csv | trade_log_scalper.csv | trade_log_combined.csv |

### 어떤 봇이 어떤 장세에 유리한가?

| 장세 | 유리한 봇 | 이유 |
|------|-----------|------|
| **강한 상승장** | Bot 1 (Volatility) | 돌파 후 쭉 올라가면 시간 청산까지 수익 극대화 |
| **횡보장 (등락 반복)** | Bot 2 (AI-Scalper) | 작은 등락에서 여러 번 매매로 소액 수익 누적 |
| **변동성 큰 장** | Bot 3 (Combined) | 이중 필터로 거짓 신호 걸러내어 손실 최소화 |
| **하락장** | 셋 다 불리 | 매수 전용 전략이므로 하락장에서는 매수 안 함 = 손실 없음 |

---

## 8. 파이썬 핵심 문법 해설

이 프로젝트에서 사용된 파이썬 문법 중 백준 실버 2에서 잘 안 쓰이는 것들을 정리합니다.

### 8.1 f-string (포맷 문자열)

```python
# 기본 사용
name = "ETF"
price = 17500
print(f"종목: {name}, 가격: {price}원")
# 출력: 종목: ETF, 가격: 17500원

# 포맷 지정
profit = 0.01567
print(f"수익률: {profit:.2%}")    # 소수점 2자리 백분율 → "1.57%"
print(f"수익률: {profit:+.2%}")   # 부호 표시 → "+1.57%"
print(f"가격: {price:,.0f}원")    # 천 단위 콤마 → "17,500원"
print(f"가격: {price:>10,}원")    # 우측 정렬 10자리 → "    17,500원"
```

### 8.2 딕셔너리 `.get()` vs `[]`

```python
data = {"name": "ETF", "price": 17500}

# 방법 1: 직접 접근 (키가 없으면 에러!)
data["name"]       # → "ETF"
data["volume"]     # → KeyError! 프로그램 종료

# 방법 2: .get() (키가 없으면 None 또는 기본값 반환)
data.get("name")           # → "ETF"
data.get("volume")         # → None (에러 안 남)
data.get("volume", 0)      # → 0 (기본값 지정)
```

API 응답을 다룰 때는 항상 `.get()`을 사용합니다. 서버 응답에 예상한 키가 없을 수 있기 때문입니다.

### 8.3 `with` 구문 (컨텍스트 매니저)

```python
# 나쁜 예 (파일을 수동으로 닫아야 함)
f = open("test.csv", "w")
f.write("hello")
f.close()    # 이 줄 전에 에러 나면 파일이 안 닫힘!

# 좋은 예 (with가 자동으로 닫아줌)
with open("test.csv", "w") as f:
    f.write("hello")
# with 블록이 끝나면 자동으로 f.close() 호출됨 (에러가 나도!)
```

### 8.4 리스트 컴프리헨션

```python
# 일반 for문
result = []
for f in all_features:
    if f in df.columns:
        result.append(f)

# 리스트 컴프리헨션 (같은 결과, 한 줄)
result = [f for f in all_features if f in df.columns]
```

형식: `[표현식 for 변수 in 반복대상 if 조건]`

### 8.5 `or` 연산자의 특수 활용

```python
# 일반적인 사용 (True/False)
True or False    # → True

# 값 선택에 활용 (파이썬 특유)
cash = output.get('ord_psbl_cash') or output.get('nrcvb_buy_amt') or '0'
```

파이썬에서 `or`는 "첫 번째 참(truthy)인 값을 반환"합니다:
- `None or "hello"` → `"hello"` (None은 falsy)
- `"" or "backup"` → `"backup"` (빈 문자열은 falsy)
- `0 or 100` → `100` (0은 falsy)
- `"first" or "second"` → `"first"` (첫 번째가 이미 truthy)

### 8.6 `for...else` 구문

```python
for _ in range(10):
    time.sleep(2)
    result = check_something()
    if result:
        print("성공!")
        break
else:
    # for문이 break 없이 끝까지 돌았을 때만 실행
    print("10번 시도했지만 실패")
```

- `break`로 빠져나왔으면 → `else` 실행 안 됨
- 10번 다 돌았으면 → `else` 실행됨

### 8.7 `_` 변수명 관례

```python
for _ in range(10):    # 반복 변수를 안 쓸 때
    do_something()

_, prob = ai_model.predict_signal(...)    # 첫 번째 반환값을 안 쓸 때
```

`_`는 "이 값은 필요 없어"라는 의미의 관례적 변수명입니다.

### 8.8 `isinstance()` — 타입 확인

```python
x = [1, 2, 3]
isinstance(x, list)    # → True
isinstance(x, str)     # → False

# 이 프로젝트에서의 사용
if isinstance(df.columns, pd.MultiIndex):
    # 멀티인덱스 처리
```

백준에서는 `type(x) == list`를 쓰기도 하지만, `isinstance()`가 더 안전합니다 (상속까지 체크).

### 8.9 `*args` — 가변 인자 (참고)

```python
def add(*numbers):     # 인자 개수가 정해지지 않음
    return sum(numbers)

add(1, 2)        # → 3
add(1, 2, 3, 4)  # → 10
```

### 8.10 클래스와 `self`

```python
class TelegramNotifier:
    def __init__(self, bot_token, chat_id):
        self.bot_token = bot_token    # 인스턴스 변수에 저장
        self.chat_id = chat_id

    def send_message(self, text):
        # self.bot_token으로 접근 가능
        url = f"...{self.bot_token}..."
```

- `self`는 "이 객체 자신"을 가리키는 참조. 자바의 `this`와 같음
- `__init__`에서 `self.xxx = 값`으로 저장하면, 다른 메서드에서 `self.xxx`로 접근 가능
- 호출할 때는 `self`를 넣지 않음: `notifier.send_message("hi")` (파이썬이 자동으로 `self=notifier`를 전달)

### 8.11 예외 처리 (`try...except`)

```python
try:
    # 에러가 날 수 있는 코드
    result = requests.get(url, timeout=10)
except Exception as e:
    # 에러 발생 시 실행되는 코드
    print(f"에러: {e}")
    # 프로그램이 죽지 않고 계속 실행됨
```

- `Exception` — 모든 에러의 부모 클래스. 어떤 에러든 잡음
- `as e` — 에러 정보를 `e` 변수에 저장
- 네트워크 통신이 많은 트레이딩 봇에서는 필수. API 서버가 응답 안 하거나 네트워크가 끊겨도 봇이 계속 동작해야 하기 때문

### 8.12 `time.sleep()` vs 이벤트 기반

```python
# 이 프로젝트 방식: 폴링 (polling)
while True:
    price = get_price()    # 가격 확인
    if price >= target:
        buy()
    time.sleep(60)          # 1분 대기 후 다시 확인
```

이 방식을 **폴링**이라고 합니다. 주기적으로 상태를 확인하는 것.
반대 개념은 **이벤트 기반** (가격이 바뀔 때 알림을 받는 것)인데, KIS API의 WebSocket을 사용해야 하므로 더 복잡합니다.

### 8.13 pandas 불리언 인덱싱

```python
df = pd.DataFrame({'이름': ['A', 'B', 'C'], '가격': [100, 200, 150]})

# 가격이 150 이상인 행만 필터링
df[df['가격'] >= 150]
# 결과:
#   이름  가격
# 1   B   200
# 2   C   150
```

`df['가격'] >= 150`은 `[False, True, True]` 같은 불리언 시리즈를 만들고, `df[불리언시리즈]`는 True인 행만 반환합니다.

### 8.14 `.iloc` vs `.loc`

```python
df.iloc[0]        # 0번째 행 (위치 기반, 0부터 시작)
df.iloc[-1]       # 마지막 행
df.iloc[2:5]      # 2~4번째 행 (슬라이싱)

df.loc[0]         # 인덱스가 0인 행 (라벨 기반)
df.loc['2024-01-01']  # 인덱스가 '2024-01-01'인 행
```

- `iloc` = **i**nteger **loc**ation (정수 위치)
- `loc` = **loc**ation (라벨/이름)
- 이 프로젝트에서는 주로 `iloc`을 사용 (위치 기반 접근이 더 직관적이므로)

### 8.15 `.pct_change()` — 변화율 계산

```python
prices = pd.Series([100, 102, 105, 103])
prices.pct_change(1)
# 결과: [NaN, 0.02, 0.0294, -0.0190]
# 해석: 100→102 = +2%, 102→105 = +2.94%, 105→103 = -1.9%
```

첫 값은 비교 대상이 없으므로 NaN(Not a Number).

---

## 부록: 환경변수 (.env) 설명

```env
# 모의투자 계좌 (봇 3개가 공유)
MOCK_APP_KEY=...           # 모의투자 앱 키
MOCK_APP_SECRET=...        # 모의투자 앱 시크릿
MOCK_ACC_NO=50162250       # 모의투자 계좌번호

# 실전투자 계좌 (main.py + 시세 조회용)
APP_KEY=...                # 실전 앱 키
APP_SECRET=...             # 실전 앱 시크릿
ACC_NO=68505295            # 실전 계좌번호

# 서버 URL
URL_REAL = "https://openapi.koreainvestment.com:9443"      # 실전 서버
URL_MOCK = "https://openapivts.koreainvestment.com:29443"   # 모의 서버

# 텔레그램 알림
TELEGRAM_BOT_TOKEN=...     # 텔레그램 봇 토큰
TELEGRAM_CHAT_ID=...       # 텔레그램 채팅방 ID
```

> **주의**: `.env` 파일은 절대 Git에 커밋하면 안 됩니다. API 키와 계좌 정보가 노출되면 큰 보안 사고가 발생합니다.
> `.gitignore` 파일에 `.env`를 반드시 추가하세요.

---

## 부록: 실행 방법

```bash
# Bot 1: 변동성 돌파
python bot_volatility.py

# Bot 2: AI 단타
python bot_ai_scalper.py

# Bot 3: 복합 전략
python bot_combined.py
```

> **주의**: 세 봇이 같은 모의투자 계좌(50162250)를 공유하므로, **하루에 하나의 봇만 실행**하세요.
> 동시에 실행하면 서로의 매수/매도가 간섭됩니다.

---

*이 문서는 Claude에 의해 생성되었습니다.*
