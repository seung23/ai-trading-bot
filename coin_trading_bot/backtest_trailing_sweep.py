"""
backtest_trailing_sweep.py
트레일링 스탑 폭별 성과 비교 (분봉 기반)
캐시된 분봉 데이터를 재사용하므로 빠르게 실행됨.
"""
import json
import os
from backtest import (
    COINS, BTC_MARKET, BACKTEST_START, BUY_FEE, SELL_FEE,
    CACHE_DIR, MINUTE_CACHE_DIR,
    load_or_fetch, dynamic_k, build_features, analyze,
    load_or_fetch_minutes, simulate_trailing_stop,
)

# 테스트할 트레일링 폭
TRAILING_PCTS = [0.01, 0.015, 0.02, 0.03, 0.04, 0.05, 0.07, 0.10, None]
# None = 트레일링 없음 (시간 청산만)


def run_trailing_sweep(coin, candles, btc_by_date):
    """한 종목에 대해 다양한 트레일링 폭으로 시뮬레이션."""

    # 먼저 돌파 발생일 목록 만들기
    breakout_days = []
    for idx in range(BACKTEST_START, len(candles) - 1):
        yesterday = candles[idx - 1]
        today = candles[idx]
        tomorrow = candles[idx + 1]

        y_range = yesterday["high"] - yesterday["low"]
        if y_range == 0:
            continue

        k = dynamic_k(yesterday)
        target = today["open"] + y_range * k

        if today["high"] < target:
            continue

        entry_price = target
        nextopen_price = tomorrow["open"]

        breakout_days.append({
            "date": today["date"],
            "entry_price": entry_price,
            "nextopen_price": nextopen_price,
            "nextopen_pnl": (nextopen_price * (1 - SELL_FEE)) / (entry_price * (1 + BUY_FEE)) - 1,
        })

    # 분봉 데이터 미리 로드 (캐시에서)
    minute_data = {}
    missing = 0
    for bd in breakout_days:
        mc = load_or_fetch_minutes(coin, bd["date"])
        if mc:
            minute_data[bd["date"]] = mc
        else:
            missing += 1

    if missing > 0:
        print(f"    (분봉 데이터 없는 날: {missing}일 — 해당 거래는 익일시가 청산 적용)")

    # 각 트레일링 폭별 시뮬레이션
    results = {}
    for trail_pct in TRAILING_PCTS:
        label = f"{trail_pct*100:.1f}%" if trail_pct else "없음(시간청산)"

        pnls = []
        trailing_fired = 0
        for bd in breakout_days:
            mc = minute_data.get(bd["date"])

            if trail_pct is None or not mc:
                # 트레일링 없음 or 분봉 없음 → 익일 시가 청산
                pnls.append(bd["nextopen_pnl"] * 100)
                continue

            exit_price, reason, peak, _ = simulate_trailing_stop(
                mc, bd["entry_price"], trail_pct)

            pnl = (exit_price * (1 - SELL_FEE)) / (bd["entry_price"] * (1 + BUY_FEE)) - 1
            pnls.append(pnl * 100)

            if reason == "trailing_stop":
                trailing_fired += 1

        # 성과 계산
        if not pnls:
            continue

        wins = [p for p in pnls if p > 0]
        cumulative = 1.0
        peak_val = 1.0
        max_dd = 0.0
        for p in pnls:
            cumulative *= (1 + p / 100)
            peak_val = max(peak_val, cumulative)
            dd = (peak_val - cumulative) / peak_val
            max_dd = max(max_dd, dd)

        results[label] = {
            "count": len(pnls),
            "win_rate": len(wins) / len(pnls) * 100,
            "avg_pnl": sum(pnls) / len(pnls),
            "total_return": (cumulative - 1) * 100,
            "max_dd": max_dd * 100,
            "trailing_fired": trailing_fired,
            "trail_pct": trail_pct,
        }

    return results


def main():
    print("=" * 76)
    print("  트레일링 스탑 폭별 성과 비교 (분봉 기반 시뮬레이션)")
    print("  테스트: 1%, 1.5%, 2%, 3%, 4%, 5%, 7%, 10%, 없음(시간청산)")
    print("=" * 76)

    # 데이터 로드
    all_data = {}
    all_data[BTC_MARKET] = load_or_fetch(BTC_MARKET)
    for coin in COINS:
        all_data[coin] = load_or_fetch(coin)

    btc_by_date = {c["date"]: c for c in all_data[BTC_MARKET]}

    for coin in COINS:
        candles = all_data[coin]
        if not candles:
            continue

        print(f"\n  ── {coin} ──")
        results = run_trailing_sweep(coin, candles, btc_by_date)

        print(f"\n    {'트레일링':<16} {'거래':>5} {'발동':>5} {'승률':>7} "
              f"{'평균':>8} {'누적':>9} {'MDD':>7}")
        print(f"    {'-'*16} {'-'*5} {'-'*5} {'-'*7} "
              f"{'-'*8} {'-'*9} {'-'*7}")

        for label, r in results.items():
            fired_str = f"{r['trailing_fired']}" if r['trail_pct'] else "-"
            print(f"    {label:<16} {r['count']:>5} {fired_str:>5} "
                  f"{r['win_rate']:>6.1f}% "
                  f"{r['avg_pnl']:>+7.2f}% "
                  f"{r['total_return']:>+8.1f}% "
                  f"{r['max_dd']:>6.1f}%")

        # 최적 트레일링 찾기
        best = max(results.items(), key=lambda x: x[1]["total_return"])
        print(f"\n    → 최고 누적 수익: {best[0]} ({best[1]['total_return']:+.1f}%)")


if __name__ == "__main__":
    main()
