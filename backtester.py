# backtester.py
# 5가지 전략 비교 백테스팅 (기존 3개 + AI 일봉 + AI 5분봉 단타)
import pandas as pd
import numpy as np
import pandas_ta as ta
from xgboost import XGBClassifier
from sklearn.metrics import accuracy_score


# ══════════════════════════════════════════════════════════
# 데이터 준비
# ══════════════════════════════════════════════════════════

def prepare_daily_data(ticker):
    """일봉 데이터 + 지표 준비 (전략 1~3, AI 일봉용)"""
    import yfinance as yf
    df = yf.download(ticker, period='1y', interval='1d')
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.reset_index().rename(columns={
        'Date': '날짜', 'Close': '종가', 'High': '고가',
        'Low': '저가', 'Open': '시가', 'Volume': '거래량'
    })

    df['MA5'] = ta.sma(df['종가'], length=5)
    df['MA20'] = ta.sma(df['종가'], length=20)
    df['RSI'] = ta.rsi(df['종가'], length=14)

    bb = ta.bbands(df['종가'], length=20, std=2)
    if bb is not None:
        df['BB_Lower'] = bb.iloc[:, 0]
        df['BB_Upper'] = bb.iloc[:, 2]

    macd = ta.macd(df['종가'])
    if macd is not None:
        df['MACD'] = macd.iloc[:, 0]
        df['MACD_Sig'] = macd.iloc[:, 2]

    df['VOL'] = df['고가'] - df['저가']
    df['Vol_Avg'] = df['거래량'].rolling(window=10).mean()
    df['Vol_Ratio'] = df['거래량'] / df['Vol_Avg']

    df.dropna(inplace=True)
    return df


def prepare_5min_data(ticker):
    """5분봉 데이터 + 고급 지표 준비 (AI 5분봉 단타용)"""
    import yfinance as yf
    print("  📥 60일 5분봉 데이터 수집 중...")
    df = yf.download(ticker, period='60d', interval='5m')
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.reset_index().rename(columns={
        'Datetime': '시간', 'Close': '종가', 'High': '고가',
        'Low': '저가', 'Open': '시가', 'Volume': '거래량'
    })

    if len(df) < 100:
        return None

    # 기술 지표
    bb = ta.bbands(df['종가'], length=20, std=2)
    if bb is not None:
        df['BB_Lower'] = bb.iloc[:, 0]
        df['BB_Upper'] = bb.iloc[:, 2]
        bb_width = df['BB_Upper'] - df['BB_Lower']
        df['BB_Pct'] = np.where(bb_width > 0, (df['종가'] - df['BB_Lower']) / bb_width, 0.5)

    macd = ta.macd(df['종가'], fast=12, slow=26, signal=9)
    if macd is not None:
        df['MACD'] = macd.iloc[:, 0]
        df['MACD_Hist'] = macd.iloc[:, 1]
        df['MACD_Sig'] = macd.iloc[:, 2]

    df['MA5'] = ta.sma(df['종가'], length=5)
    df['MA20'] = ta.sma(df['종가'], length=20)
    df['RSI'] = ta.rsi(df['종가'], length=14)

    stoch_rsi = ta.stochrsi(df['종가'], length=14)
    if stoch_rsi is not None:
        df['StochRSI_K'] = stoch_rsi.iloc[:, 0]
        df['StochRSI_D'] = stoch_rsi.iloc[:, 1]

    df['ATR'] = ta.atr(df['고가'], df['저가'], df['종가'], length=14)

    # 거래량
    df['Vol_Avg'] = df['거래량'].rolling(window=20).mean()
    df['Vol_Ratio'] = np.where(df['Vol_Avg'] > 0, df['거래량'] / df['Vol_Avg'], 1.0)
    df['Vol_Spike'] = (df['Vol_Ratio'] > 2.0).astype(int)

    # 모멘텀
    candle_range = df['고가'] - df['저가']
    df['Body_Ratio'] = np.where(candle_range > 0, (df['종가'] - df['시가']) / candle_range, 0)
    df['Ret_1'] = df['종가'].pct_change(1)
    df['Ret_3'] = df['종가'].pct_change(3)
    df['Ret_6'] = df['종가'].pct_change(6)
    df['Ret_12'] = df['종가'].pct_change(12)
    df['MA5_Dist'] = np.where(df['MA5'] > 0, (df['종가'] / df['MA5'] - 1) * 100, 0)
    df['MA20_Dist'] = np.where(df['MA20'] > 0, (df['종가'] / df['MA20'] - 1) * 100, 0)
    df['Intraday_Pos'] = np.where(candle_range > 0, (df['종가'] - df['저가']) / candle_range, 0.5)
    df['VOL'] = candle_range
    df['Vol_6'] = df['종가'].rolling(6).std()

    # 타겟: 6캔들(30분) 이내 1.5% 수익
    lookahead = 6
    profit_target = 0.015
    target = pd.Series(0, index=df.index)
    for i in range(len(df) - lookahead):
        current_price = df['종가'].iloc[i]
        future_highs = df['고가'].iloc[i + 1:i + 1 + lookahead]
        if len(future_highs) > 0:
            max_profit = (future_highs / current_price - 1).max()
            if max_profit >= profit_target:
                target.iloc[i] = 1
    df['target'] = target

    df.dropna(inplace=True)
    return df


# ══════════════════════════════════════════════════════════
# 기존 전략들
# ══════════════════════════════════════════════════════════

def strategy_ma_crossover(df, buy_fee, sell_fee):
    """전략 1: MA 골든/데드크로스"""
    balance = 10000000
    holdings = 0
    bought_price = 0
    trade_count = 0
    win_count = 0

    for i in range(1, len(df)):
        price = df['종가'].iloc[i]
        ma5 = df['MA5'].iloc[i]
        ma20 = df['MA20'].iloc[i]
        ma5_prev = df['MA5'].iloc[i - 1]
        ma20_prev = df['MA20'].iloc[i - 1]

        if holdings == 0:
            if ma5_prev <= ma20_prev and ma5 > ma20:
                holdings = int(balance * 0.95 / (price * (1 + buy_fee)))
                if holdings > 0:
                    balance -= holdings * price * (1 + buy_fee)
                    bought_price = price
        elif holdings > 0:
            if ma5_prev >= ma20_prev and ma5 < ma20:
                balance += holdings * price * (1 - sell_fee)
                trade_count += 1
                if price > bought_price:
                    win_count += 1
                holdings = 0
                bought_price = 0

    if holdings > 0:
        balance += holdings * df['종가'].iloc[-1] * (1 - sell_fee)
        trade_count += 1
        if df['종가'].iloc[-1] > bought_price:
            win_count += 1

    return balance, trade_count, win_count


def strategy_rsi_swing(df, buy_fee, sell_fee):
    """전략 2: RSI 과매도 매수 / 과매수 매도"""
    balance = 10000000
    holdings = 0
    bought_price = 0
    trade_count = 0
    win_count = 0

    for i in range(len(df)):
        price = df['종가'].iloc[i]
        rsi = df['RSI'].iloc[i]
        ma5 = df['MA5'].iloc[i]
        ma20 = df['MA20'].iloc[i]

        if holdings == 0:
            if rsi < 35 and ma5 > ma20:
                holdings = int(balance * 0.95 / (price * (1 + buy_fee)))
                if holdings > 0:
                    balance -= holdings * price * (1 + buy_fee)
                    bought_price = price
        elif holdings > 0:
            profit_rate = (price - bought_price) / bought_price
            if rsi > 70 or profit_rate <= -0.03:
                balance += holdings * price * (1 - sell_fee)
                trade_count += 1
                if price > bought_price:
                    win_count += 1
                holdings = 0
                bought_price = 0

    if holdings > 0:
        balance += holdings * df['종가'].iloc[-1] * (1 - sell_fee)
        trade_count += 1
        if df['종가'].iloc[-1] > bought_price:
            win_count += 1

    return balance, trade_count, win_count


def strategy_trend_follow(df, buy_fee, sell_fee):
    """전략 3: 트렌드 추종 (MA20 위=보유, 아래=매도)"""
    balance = 10000000
    holdings = 0
    bought_price = 0
    trade_count = 0
    win_count = 0

    for i in range(len(df)):
        price = df['종가'].iloc[i]
        ma20 = df['MA20'].iloc[i]
        rsi = df['RSI'].iloc[i]

        if holdings == 0:
            if price > ma20 and rsi > 50:
                holdings = int(balance * 0.95 / (price * (1 + buy_fee)))
                if holdings > 0:
                    balance -= holdings * price * (1 + buy_fee)
                    bought_price = price
        elif holdings > 0:
            if price < ma20:
                balance += holdings * price * (1 - sell_fee)
                trade_count += 1
                if price > bought_price:
                    win_count += 1
                holdings = 0
                bought_price = 0

    if holdings > 0:
        balance += holdings * df['종가'].iloc[-1] * (1 - sell_fee)
        trade_count += 1
        if df['종가'].iloc[-1] > bought_price:
            win_count += 1

    return balance, trade_count, win_count


# ══════════════════════════════════════════════════════════
# AI 전략들
# ══════════════════════════════════════════════════════════

def strategy_ai_daily(df, buy_fee, sell_fee):
    """전략 4: AI (XGBoost) 일봉 기반 — Walking Forward (매일 재학습)"""
    features = ['종가', 'MA5', 'MA20', 'RSI', 'VOL', '거래량',
                'BB_Upper', 'BB_Lower', 'Vol_Ratio', 'MACD', 'MACD_Sig']

    lookahead = 5
    profit_target = 0.03
    target = pd.Series(0, index=df.index)
    for i in range(len(df) - lookahead):
        current_price = df['종가'].iloc[i]
        future_highs = df['고가'].iloc[i + 1:i + 1 + lookahead]
        max_profit = (future_highs / current_price - 1).max()
        if max_profit >= profit_target:
            target.iloc[i] = 1
    df['target'] = target

    split_idx = int(len(df) * 0.75)
    test = df.iloc[split_idx:].copy()
    test_len = len(test)

    balance = 10000000
    holdings = 0
    bought_price = 0
    trade_count = 0
    win_count = 0
    all_preds = []
    all_targets = []

    print(f"  AI 일봉 Walking Forward 시작 ({test_len}일, 매일 재학습)...")

    for i in range(test_len):
        # 매일 누적 데이터로 재학습 (main.py와 동일)
        train_end = split_idx + i
        train = df.iloc[:train_end]

        pos = train['target'].sum()
        neg = len(train) - pos
        scale_w = neg / pos if pos > 0 else 1.0

        ai = XGBClassifier(
            n_jobs=-1, n_estimators=100, learning_rate=0.1, max_depth=5,
            scale_pos_weight=scale_w, eval_metric='logloss', random_state=42,
        )
        ai.fit(train[features], train['target'], verbose=False)

        # 당일 예측
        row = test.iloc[i]
        price = row['종가']
        input_data = pd.DataFrame([row[features]], columns=features)
        up_prob = ai.predict_proba(input_data)[0][1]
        pred = 1 if up_prob >= 0.5 else 0
        all_preds.append(pred)
        all_targets.append(int(row['target']))

        # 매매 로직
        if holdings == 0:
            if up_prob >= 0.60:
                holdings = int(balance * 0.95 / (price * (1 + buy_fee)))
                if holdings > 0:
                    balance -= holdings * price * (1 + buy_fee)
                    bought_price = price
        elif holdings > 0:
            profit_rate = (price - bought_price) / bought_price
            if profit_rate >= 0.03 or profit_rate <= -0.02 or up_prob < 0.4:
                balance += holdings * price * (1 - sell_fee)
                trade_count += 1
                if price > bought_price:
                    win_count += 1
                holdings = 0
                bought_price = 0

    if holdings > 0:
        balance += holdings * test.iloc[-1]['종가'] * (1 - sell_fee)
        trade_count += 1
        if test.iloc[-1]['종가'] > bought_price:
            win_count += 1

    acc = accuracy_score(all_targets, all_preds)
    print(f"  AI 일봉 정확도 (Walking Forward): {acc:.2%}")

    return balance, trade_count, win_count, acc, test_len


def strategy_ai_5min_scalp(df, buy_fee, sell_fee):
    """
    전략 5: AI (XGBoost) 5분봉 단타 + 트레일링 스탑
    Walking Forward: 날짜가 바뀔 때마다 누적 데이터로 재학습
    """
    features = [
        '종가', 'MA5', 'MA20', 'RSI',
        'BB_Pct', 'MACD', 'MACD_Hist',
        'StochRSI_K', 'StochRSI_D', 'ATR',
        'Vol_Ratio', 'Vol_Spike', 'Body_Ratio',
        'Ret_1', 'Ret_3', 'Ret_6', 'Ret_12',
        'MA5_Dist', 'MA20_Dist', 'Intraday_Pos',
        'VOL', 'Vol_6', '거래량',
    ]
    features = [f for f in features if f in df.columns]

    # 시계열 분할 (75% 학습 / 25% 테스트)
    split_idx = int(len(df) * 0.75)
    test = df.iloc[split_idx:].copy()
    test_len = len(test)

    # 날짜 컬럼 추출 (5분봉의 시간 컬럼에서 날짜만)
    time_col = '시간' if '시간' in test.columns else test.columns[0]
    test_dates = pd.to_datetime(test[time_col]).dt.date

    # 전략 파라미터 (main.py와 동일)
    BUY_THRESH = 0.65
    SELL_THRESH = 0.40
    TAKE_PROFIT = 0.015
    STOP_LOSS = -0.012
    TRAIL_ACTIVATE = 0.01
    TRAIL_STOP = 0.005

    balance = 10000000
    holdings = 0
    bought_price = 0
    highest_price = 0
    trailing_active = False
    trade_count = 0
    win_count = 0
    all_preds = []
    all_targets = []

    current_date = None
    ai = None
    unique_dates = test_dates.unique()
    print(f"  AI 5분봉 Walking Forward 시작 ({test_len}캔들, {len(unique_dates)}일, 매일 재학습)...")

    for i in range(test_len):
        row_date = test_dates.iloc[i]

        # 날짜가 바뀌면 재학습
        if row_date != current_date:
            train_end = split_idx + i
            train = df.iloc[:train_end]

            pos = train['target'].sum()
            neg = len(train) - pos
            scale_w = neg / pos if pos > 0 else 1.0

            ai = XGBClassifier(
                n_jobs=-1, n_estimators=300, learning_rate=0.05,
                max_depth=6, min_child_weight=5,
                subsample=0.8, colsample_bytree=0.8,
                reg_alpha=0.1, reg_lambda=1.0,
                scale_pos_weight=scale_w,
                eval_metric='logloss', random_state=42,
            )
            ai.fit(train[features], train['target'], verbose=False)
            current_date = row_date

        # 당일 예측
        row = test.iloc[i]
        price = row['종가']
        input_data = pd.DataFrame([row[features].values], columns=features)
        up_prob = ai.predict_proba(input_data)[0][1]
        pred = 1 if up_prob >= 0.5 else 0
        all_preds.append(pred)
        all_targets.append(int(row['target']))

        if holdings == 0:
            # 매수
            if up_prob >= BUY_THRESH:
                holdings = int(balance * 0.80 / (price * (1 + buy_fee)))
                if holdings > 0:
                    balance -= holdings * price * (1 + buy_fee)
                    bought_price = price
                    highest_price = price
                    trailing_active = False

        elif holdings > 0:
            profit_rate = (price - bought_price) / bought_price
            sell = False

            # 익절
            if profit_rate >= TAKE_PROFIT:
                sell = True
            # 손절
            elif profit_rate <= STOP_LOSS:
                sell = True
            # 트레일링 스탑
            elif trailing_active:
                drop = (price - highest_price) / highest_price
                if drop <= -TRAIL_STOP:
                    sell = True
            # AI 반전
            elif up_prob < SELL_THRESH and profit_rate > 0:
                sell = True

            # 고점 갱신
            if price > highest_price:
                highest_price = price
            if not trailing_active and profit_rate >= TRAIL_ACTIVATE:
                trailing_active = True

            if sell:
                balance += holdings * price * (1 - sell_fee)
                trade_count += 1
                if price > bought_price:
                    win_count += 1
                holdings = 0
                bought_price = 0
                highest_price = 0
                trailing_active = False

    # 잔여 포지션 청산
    if holdings > 0:
        balance += holdings * test.iloc[-1]['종가'] * (1 - sell_fee)
        trade_count += 1
        if test.iloc[-1]['종가'] > bought_price:
            win_count += 1

    acc = accuracy_score(all_targets, all_preds)
    print(f"  AI 5분봉 정확도 (Walking Forward): {acc:.2%}")

    return balance, trade_count, win_count, acc, test_len


# ══════════════════════════════════════════════════════════
# 메인 실행
# ══════════════════════════════════════════════════════════

def run_backtest():
    ticker = "233740.KS"
    # ETF 수수료 (실전 기준: 0.0146%, 수수료 우대, 거래세 면제)
    buy_fee = 0.000146
    sell_fee = 0.000146

    print("=" * 80)
    print("📊 전략 비교 백테스팅 (ETF 수수료: 매수 0.0146% + 매도 0.0146%)")
    print("   KODEX 코스닥150레버리지 (233740)")
    print("=" * 80)

    # ── 일봉 데이터 준비 ──
    print("\n📥 1년치 일봉 데이터 수집 중...")
    df_daily = prepare_daily_data(ticker)
    print(f"   총 {len(df_daily)}개 일봉 로드 완료")

    split_idx = int(len(df_daily) * 0.75)
    test_daily = df_daily.iloc[split_idx:].copy()

    first_price = test_daily.iloc[0]['종가']
    last_price = test_daily.iloc[-1]['종가']
    buy_hold_daily = (last_price / first_price - 1) * 100

    print(f"   테스트 기간: {test_daily.iloc[0]['날짜'].strftime('%Y-%m-%d')} ~ {test_daily.iloc[-1]['날짜'].strftime('%Y-%m-%d')}")
    print(f"   테스트 일수: {len(test_daily)}일")

    # ── 5분봉 데이터 준비 ──
    print("\n📥 5분봉 데이터 수집 중...")
    df_5min = prepare_5min_data(ticker)
    has_5min = df_5min is not None and len(df_5min) >= 200

    if has_5min:
        split_5 = int(len(df_5min) * 0.75)
        test_5min = df_5min.iloc[split_5:]
        fp5 = test_5min.iloc[0]['종가']
        lp5 = test_5min.iloc[-1]['종가']
        buy_hold_5min = (lp5 / fp5 - 1) * 100
        print(f"   총 {len(df_5min)}개 5분봉 로드 완료 (테스트: {len(test_5min)}개)")
    else:
        print("   ⚠️ 5분봉 데이터 부족 — AI 5분봉 전략 스킵")

    # ══════════════════════════════════════════════════════════
    # 전략 실행 (ETF 수수료: 매수 0.0146% + 매도 0.0146%)
    # ══════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("🏁 전략 실행 중 (ETF 수수료: 매수 0.0146% + 매도 0.0146%)...")
    print("=" * 80)

    bal1, tc1, wc1 = strategy_ma_crossover(test_daily.copy(), buy_fee, sell_fee)
    ret1 = (bal1 / 10000000 - 1) * 100

    bal2, tc2, wc2 = strategy_rsi_swing(test_daily.copy(), buy_fee, sell_fee)
    ret2 = (bal2 / 10000000 - 1) * 100

    bal3, tc3, wc3 = strategy_trend_follow(test_daily.copy(), buy_fee, sell_fee)
    ret3 = (bal3 / 10000000 - 1) * 100

    print(f"  AI 일봉 학습 중...")
    bal4, tc4, wc4, _, _ = strategy_ai_daily(df_daily.copy(), buy_fee, sell_fee)
    ret4 = (bal4 / 10000000 - 1) * 100

    ret5, tc5, wc5 = 0, 0, 0
    if has_5min:
        print(f"  AI 5분봉 학습 중...")
        bal5, tc5, wc5, _, _ = strategy_ai_5min_scalp(df_5min.copy(), buy_fee, sell_fee)
        ret5 = (bal5 / 10000000 - 1) * 100

    # ══════════════════════════════════════════════════════════
    # 결과 출력
    # ══════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("📋 전략별 결과 (ETF 수수료: 왕복 0.0292%)")
    print("=" * 80)

    strategies = [
        ("MA 크로스오버", ret1, tc1, wc1),
        ("RSI 스윙", ret2, tc2, wc2),
        ("트렌드 추종(기존)", ret3, tc3, wc3),
        ("AI 일봉", ret4, tc4, wc4),
    ]
    if has_5min:
        strategies.append(("AI 5분봉 단타⚡", ret5, tc5, wc5))

    print(f"{'전략':<22} {'수익률':<12} {'거래횟수':<10} {'승률':<8}")
    print("-" * 60)

    for name, ret, tc, wc in strategies:
        wr = f"{wc/tc*100:.0f}%" if tc > 0 else "N/A"
        print(f"{name:<22} {ret:+6.2f}%      {tc}회        {wr:>4}")

    # Buy & Hold
    print(f"{'─' * 60}")
    print(f"{'Buy&Hold (일봉)':<22} {buy_hold_daily:+6.2f}%      0회        N/A")
    if has_5min:
        print(f"{'Buy&Hold (5분봉)':<22} {buy_hold_5min:+6.2f}%      0회        N/A")

    # ── 종합 순위 ──
    results_all = [
        ("MA 크로스오버", ret1, tc1),
        ("RSI 스윙", ret2, tc2),
        ("트렌드 추종(기존)", ret3, tc3),
        ("AI 일봉", ret4, tc4),
        ("Buy&Hold(일봉)", buy_hold_daily, 0),
    ]
    if has_5min:
        results_all.append(("AI 5분봉 단타⚡", ret5, tc5))
        results_all.append(("Buy&Hold(5분봉)", buy_hold_5min, 0))
    results_all.sort(key=lambda x: x[1], reverse=True)

    print(f"\n{'=' * 80}")
    print("🏆 수익률 순위 (ETF 수수료: 매수 0.0146% + 매도 0.0146%)")
    print(f"{'=' * 80}")
    for rank, (name, ret, tc) in enumerate(results_all, 1):
        marker = " ← 최고" if rank == 1 else ""
        print(f"  {rank}위: {name:20s} {ret:+.2f}% ({tc}회 거래){marker}")
    print(f"{'=' * 80}")
    print(f"  ※ 일봉/5분봉 테스트 기간이 다르므로 직접 비교 시 참고")


if __name__ == "__main__":
    run_backtest()
