# optimizer.py
# AI 5분봉 전략 파라미터 최적화 도구
# 다양한 설정 조합을 테스트하여 최적의 전략 찾기

import pandas as pd
import numpy as np
from itertools import product
from backtester import prepare_5min_data, strategy_ai_5min_scalp
from xgboost import XGBClassifier
from sklearn.metrics import accuracy_score


def optimize_parameters(ticker="233740.KS"):
    """
    그리드 서치로 최적 파라미터 탐색
    - BUY_THRESHOLD: AI 매수 확률 임계값
    - TAKE_PROFIT: 익절 수익률
    - STOP_LOSS: 손절 수익률
    - TRAILING_ACTIVATE: 트레일링 활성화 수익률
    """

    print("=" * 60)
    print("🔍 AI 5분봉 전략 파라미터 최적화")
    print("=" * 60)

    # 데이터 준비
    print("\n📥 데이터 수집 중...")
    df = prepare_5min_data(ticker)
    if df is None or len(df) < 200:
        print("❌ 데이터 부족")
        return

    print(f"   총 {len(df)}개 5분봉 로드 완료")

    # 파라미터 그리드
    buy_thresholds = [0.55, 0.60, 0.65, 0.70]      # 낮을수록 공격적
    take_profits = [0.010, 0.015, 0.020, 0.025]     # 익절 목표
    stop_losses = [-0.008, -0.010, -0.012, -0.015]  # 손절선

    # ETF 수수료 (실전 기준: 0.0146%, 수수료 우대, 거래세 면제)
    buy_fee = 0.000146
    sell_fee = 0.000146
    results = []

    print(f"\n🧪 총 {len(buy_thresholds) * len(take_profits) * len(stop_losses)}가지 조합 테스트 중...\n")

    for i, (buy_th, tp, sl) in enumerate(product(buy_thresholds, take_profits, stop_losses), 1):
        # 백테스트 실행 (strategy_ai_5min_scalp 수정 버전)
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

        split_idx = int(len(df) * 0.75)
        train = df.iloc[:split_idx]
        test = df.iloc[split_idx:].copy()

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

        # 파라미터 적용한 백테스트
        SELL_THRESH = 0.40
        TRAIL_ACTIVATE = 0.01
        TRAIL_STOP = 0.005

        balance = 10000000
        holdings = 0
        bought_price = 0
        highest_price = 0
        trailing_active = False
        trade_count = 0
        win_count = 0

        for j in range(len(test)):
            row = test.iloc[j]
            price = row['종가']
            input_data = pd.DataFrame([row[features].values], columns=features)
            up_prob = ai.predict_proba(input_data)[0][1]

            if holdings == 0:
                if up_prob >= buy_th:  # 파라미터 적용
                    holdings = int(balance * 0.80 / (price * (1 + buy_fee)))
                    if holdings > 0:
                        balance -= holdings * price * (1 + buy_fee)
                        bought_price = price
                        highest_price = price
                        trailing_active = False

            elif holdings > 0:
                profit_rate = (price - bought_price) / bought_price
                sell = False

                if profit_rate >= tp:  # 파라미터 적용
                    sell = True
                elif profit_rate <= sl:  # 파라미터 적용
                    sell = True
                elif trailing_active:
                    drop = (price - highest_price) / highest_price
                    if drop <= -TRAIL_STOP:
                        sell = True
                elif up_prob < SELL_THRESH and profit_rate > 0:
                    sell = True

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

        if holdings > 0:
            balance += holdings * test.iloc[-1]['종가'] * (1 - total_fee / 2)
            trade_count += 1
            if test.iloc[-1]['종가'] > bought_price:
                win_count += 1

        ret = (balance / 10000000 - 1) * 100
        win_rate = (win_count / trade_count * 100) if trade_count > 0 else 0

        results.append({
            'BUY_THRESHOLD': buy_th,
            'TAKE_PROFIT': tp,
            'STOP_LOSS': sl,
            'Return': ret,
            'Trades': trade_count,
            'WinRate': win_rate,
            'Score': ret  # 정렬 기준
        })

        if i % 16 == 0:
            print(f"  진행: {i}/{len(buy_thresholds) * len(take_profits) * len(stop_losses)} 완료...")

    # 결과 정렬
    results_df = pd.DataFrame(results)
    results_df = results_df.sort_values('Score', ascending=False)

    print("\n" + "=" * 80)
    print("🏆 최적 파라미터 TOP 10")
    print("=" * 80)
    print(f"{'순위':<4} {'매수임계':<8} {'익절':<8} {'손절':<8} {'수익률':<10} {'거래':<6} {'승률':<8}")
    print("-" * 80)

    for idx, row in results_df.head(10).iterrows():
        print(f"{results_df.index.get_loc(idx)+1:<4} "
              f"{row['BUY_THRESHOLD']:<8.2f} "
              f"{row['TAKE_PROFIT']*100:<7.1f}% "
              f"{row['STOP_LOSS']*100:<7.1f}% "
              f"{row['Return']:+9.2f}% "
              f"{int(row['Trades']):<6} "
              f"{row['WinRate']:>6.1f}%")

    print("=" * 80)

    # 최적값
    best = results_df.iloc[0]
    print("\n✅ 최적 설정:")
    print(f"   BUY_THRESHOLD = {best['BUY_THRESHOLD']}")
    print(f"   TAKE_PROFIT = {best['TAKE_PROFIT']}")
    print(f"   STOP_LOSS = {best['STOP_LOSS']}")
    print(f"   예상 수익률: {best['Return']:+.2f}%")
    print(f"   거래 횟수: {int(best['Trades'])}회")
    print(f"   승률: {best['WinRate']:.1f}%")

    print("\n💡 main.py의 32~36번 줄에 위 값을 반영하세요!")

    return results_df


if __name__ == "__main__":
    optimize_parameters()
