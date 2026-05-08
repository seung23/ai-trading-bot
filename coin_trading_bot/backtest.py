"""
backtest.py — 변동성 돌파 전략 백테스트
──────────────────────────────────────────────────────────
분석 항목:
  1. 종목별 개별 성과 비교 (ETH, XRP, SOL, DOGE, ADA)
  2. 국면 필터별 효과 분석 (노이즈, BTC 추세, 거래량)
  3. 다종목 동시 감시 → 첫 돌파 매수 시뮬레이션
  4. 필터가 걸러낸 거래의 실제 성과 (기회비용 분석)
  5. 분봉 기반 트레일링 스탑 시뮬레이션 (익일 시가 청산과 비교)

한계:
  - 다종목 시뮬에서 '첫 돌파'를 돌파 강도로 근사 (실제 시간순 불명)
  - 슬리피지/호가 스프레드 미반영 (시장가 매수 가정)
──────────────────────────────────────────────────────────
"""
import requests
import time
import json
import os
from datetime import datetime, timedelta
from collections import defaultdict

# ── 설정 ──────────────────────────────────────────────────
COINS = ["KRW-ETH", "KRW-XRP", "KRW-SOL", "KRW-DOGE", "KRW-ADA"]
BTC_MARKET = "KRW-BTC"

FETCH_DAYS = 420       # API에서 가져올 일수 (피처 윈도우 여유분 포함)
BACKTEST_START = 15    # 처음 15일은 피처 계산용으로 버퍼

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backtest_cache")
MINUTE_CACHE_DIR = os.path.join(CACHE_DIR, "minutes")

BUY_FEE = 0.0005      # 업비트 매수 수수료 0.05%
SELL_FEE = 0.0005      # 업비트 매도 수수료 0.05%
K_MIN = 0.3
K_MAX = 0.6
TRAILING_STOP_PCT = 0.02  # 고점 대비 2% 하락 시 청산

API_BASE = "https://api.upbit.com"
API_DELAY = 0.2        # 초당 5회 (업비트 시세 API 제한 10회/초 대비 여유)


# ══════════════════════════════════════════════════════════
# 데이터 수집
# ══════════════════════════════════════════════════════════

def fetch_daily_candles(market, count=420):
    """업비트 일봉 데이터를 페이지네이션하여 가져옵니다.
    Returns: list of dict (oldest first), 중복 날짜 제거됨
    """
    all_raw = []
    remaining = count
    to_param = None

    while remaining > 0:
        batch = min(remaining, 200)
        params = {"market": market, "count": batch}
        if to_param:
            params["to"] = to_param

        try:
            res = requests.get(
                f"{API_BASE}/v1/candles/days", params=params, timeout=10)
            res.raise_for_status()
            data = res.json()
        except Exception as e:
            print(f"    API 에러 ({market}): {e}")
            break

        if not isinstance(data, list) or len(data) == 0:
            break

        all_raw.extend(data)
        remaining -= len(data)

        if len(data) < batch:
            break  # 더 이상 데이터 없음

        # 페이지네이션: 가장 오래된 캔들의 UTC 시각 사용
        to_param = data[-1]["candle_date_time_utc"]
        time.sleep(API_DELAY)

    # 최신→오래된 순으로 받았으므로 뒤집기 + 중복 제거
    candles = []
    seen_dates = set()
    for d in reversed(all_raw):
        date_str = d["candle_date_time_kst"][:10]
        if date_str in seen_dates:
            continue
        seen_dates.add(date_str)
        candles.append({
            "date": date_str,
            "open": float(d["opening_price"]),
            "high": float(d["high_price"]),
            "low": float(d["low_price"]),
            "close": float(d["trade_price"]),
            "volume": float(d["candle_acc_trade_volume"]),
        })

    return candles


def load_or_fetch(market, count=420):
    """캐시 파일이 있고 12시간 이내면 재사용, 아니면 API 호출."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    safe_name = market.replace("-", "_")
    cache_file = os.path.join(CACHE_DIR, f"{safe_name}.json")

    if os.path.exists(cache_file):
        age_hours = (time.time() - os.path.getmtime(cache_file)) / 3600
        if age_hours < 12:
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            print(f"    {market}: 캐시 사용 ({len(data)}일, {age_hours:.1f}시간 전)")
            return data

    print(f"    {market}: API에서 {count}일치 데이터 요청 중...")
    candles = fetch_daily_candles(market, count)
    print(f"    {market}: {len(candles)}일치 수신 완료")

    if candles:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(candles, f, ensure_ascii=False)

    return candles


# ══════════════════════════════════════════════════════════
# 분봉 데이터 수집 (트레일링 스탑 시뮬레이션용)
# ══════════════════════════════════════════════════════════

def fetch_minute_candles(market, date_str, unit=5):
    """특정 날짜의 분봉 데이터를 가져옵니다.
    업비트 사이클: 당일 09:00 KST ~ 익일 08:59 KST.
    unit분봉을 페이지네이션하여 가져옴.
    Returns: list of dict (시간순, oldest first)
    """
    # 당일 09:00 ~ 익일 09:00 KST 범위
    # 업비트 API의 to 파라미터는 UTC 기준
    # KST 09:00 = UTC 00:00
    base_date = datetime.strptime(date_str, "%Y-%m-%d")
    # 사이클 끝: 익일 09:00 KST = 익일 00:00 UTC
    cycle_end_utc = base_date + timedelta(days=1)  # 익일 00:00 UTC = 익일 09:00 KST
    cycle_start_utc = base_date  # 당일 00:00 UTC = 당일 09:00 KST

    # 하루 사이클 (24시간)에 필요한 캔들 수
    candles_per_day = (24 * 60) // unit  # 5분봉 = 288개

    all_raw = []
    remaining = candles_per_day
    to_param = cycle_end_utc.strftime("%Y-%m-%dT%H:%M:%S")

    while remaining > 0:
        batch = min(remaining, 200)
        params = {"market": market, "unit": unit, "count": batch, "to": to_param}

        try:
            res = requests.get(
                f"{API_BASE}/v1/candles/minutes/{unit}",
                params=params, timeout=10)
            res.raise_for_status()
            data = res.json()
        except Exception as e:
            print(f"    분봉 API 에러 ({market}, {date_str}): {e}")
            break

        if not isinstance(data, list) or len(data) == 0:
            break

        all_raw.extend(data)
        remaining -= len(data)

        if len(data) < batch:
            break

        to_param = data[-1]["candle_date_time_utc"]
        time.sleep(API_DELAY)

    # oldest first로 정렬, 사이클 시간 내 필터
    candles = []
    for d in reversed(all_raw):
        dt_utc = datetime.strptime(d["candle_date_time_utc"], "%Y-%m-%dT%H:%M:%S")
        if dt_utc < cycle_start_utc or dt_utc >= cycle_end_utc:
            continue
        candles.append({
            "datetime_kst": d["candle_date_time_kst"],
            "open": float(d["opening_price"]),
            "high": float(d["high_price"]),
            "low": float(d["low_price"]),
            "close": float(d["trade_price"]),
        })

    return candles


def load_or_fetch_minutes(market, date_str, unit=5):
    """분봉 데이터를 캐시에서 로드하거나 API로 가져옵니다."""
    os.makedirs(MINUTE_CACHE_DIR, exist_ok=True)
    safe_name = market.replace("-", "_")
    cache_file = os.path.join(MINUTE_CACHE_DIR, f"{safe_name}_{date_str}.json")

    if os.path.exists(cache_file):
        with open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f)

    candles = fetch_minute_candles(market, date_str, unit)

    if candles:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(candles, f, ensure_ascii=False)

    return candles


def simulate_trailing_stop(minute_candles, entry_price, trailing_pct=TRAILING_STOP_PCT):
    """분봉 데이터로 트레일링 스탑을 시뮬레이션합니다.

    매수 후 분봉을 순서대로 따라가며:
    - 고점 갱신 → 트레일링 스탑 라인 상승
    - 저가가 트레일링 라인 이하 → 청산

    Returns: (exit_price, exit_reason, peak_price, exit_time)
      exit_reason: "trailing_stop" / "time_exit"
    """
    if not minute_candles:
        return entry_price, "no_data", entry_price, ""

    highest = entry_price
    entered = False

    for candle in minute_candles:
        # 매수 시점 찾기: 고가가 entry_price 이상인 첫 캔들
        if not entered:
            if candle["high"] >= entry_price:
                entered = True
                # 이 캔들에서 진입 후 고점 갱신
                highest = max(highest, candle["high"])
                # 같은 캔들에서 트레일링 체크
                trail_line = highest * (1 - trailing_pct)
                if candle["low"] <= trail_line:
                    return trail_line, "trailing_stop", highest, candle["datetime_kst"]
            continue

        # 진입 이후: 고점 갱신 → 트레일링 체크
        if candle["high"] > highest:
            highest = candle["high"]

        trail_line = highest * (1 - trailing_pct)
        if candle["low"] <= trail_line:
            return trail_line, "trailing_stop", highest, candle["datetime_kst"]

    # 트레일링 미발동 → 마지막 캔들 종가로 청산 (08:55 시간 청산 근사)
    last_close = minute_candles[-1]["close"]
    return last_close, "time_exit", highest, minute_candles[-1]["datetime_kst"]


# ══════════════════════════════════════════════════════════
# 피처 계산
# ══════════════════════════════════════════════════════════

def noise_1d(candle):
    """1일 노이즈 비율."""
    r = candle["high"] - candle["low"]
    if r == 0:
        return 0.0
    return 1 - abs(candle["close"] - candle["open"]) / r


def noise_avg(candles, idx, n):
    """candles[idx-n : idx] 구간의 평균 1일 노이즈."""
    if idx < n:
        return None
    return sum(noise_1d(candles[i]) for i in range(idx - n, idx)) / n


def volume_ratio(candles, idx, n=5):
    """어제 거래량 / 최근 n일 평균 거래량."""
    if idx < n + 1:
        return None
    yesterday_vol = candles[idx - 1]["volume"]
    avg_vol = sum(candles[i]["volume"] for i in range(idx - n, idx)) / n
    if avg_vol == 0:
        return None
    return yesterday_vol / avg_vol


def dynamic_k(candle):
    """전일 캔들의 노이즈로 K 동적 계산."""
    n = noise_1d(candle)
    if n <= 0.4:
        return K_MIN
    if n >= 0.7:
        return K_MAX
    return round(K_MIN + (n - 0.4) / (0.7 - 0.4) * (K_MAX - K_MIN), 2)


def btc_daily_change(btc_by_date, today_date, yesterday_date):
    """BTC 전일 대비 변화율(%)과 추세 문자열."""
    bt = btc_by_date.get(today_date)
    by = btc_by_date.get(yesterday_date)
    if not bt or not by or by["close"] == 0:
        return None, "flat"
    change = (bt["close"] - by["close"]) / by["close"] * 100
    if change > 1:
        trend = "up"
    elif change < -1:
        trend = "down"
    else:
        trend = "flat"
    return change, trend


def build_features(candles, idx, btc_by_date):
    """idx 시점의 피처 딕셔너리를 생성합니다."""
    yesterday = candles[idx - 1]
    today = candles[idx]

    btc_change, btc_trend = btc_daily_change(
        btc_by_date, today["date"], yesterday["date"])

    return {
        "date": today["date"],
        "noise_1d": noise_1d(yesterday),
        "noise_avg_3d": noise_avg(candles, idx, 3),
        "noise_avg_7d": noise_avg(candles, idx, 7),
        "noise_avg_14d": noise_avg(candles, idx, 14),
        "volume_ratio": volume_ratio(candles, idx),
        "btc_24h_change": btc_change,
        "btc_trend": btc_trend,
    }


# ══════════════════════════════════════════════════════════
# 단일 종목 백테스트
# ══════════════════════════════════════════════════════════

def backtest_single(candles, btc_by_date):
    """단일 종목 변동성 돌파 백테스트.
    - 진입: 당일 고가 >= 목표가 → 목표가에 매수 가정
    - 청산: 익일 시가에 매도 가정
    Returns: list of trade dicts (피처 + 결과 포함)
    """
    trades = []

    for idx in range(BACKTEST_START, len(candles) - 1):
        yesterday = candles[idx - 1]
        today = candles[idx]
        tomorrow = candles[idx + 1]

        y_range = yesterday["high"] - yesterday["low"]
        if y_range == 0:
            continue

        k = dynamic_k(yesterday)
        target = today["open"] + y_range * k

        # 돌파 발생 여부 (당일 고가가 목표가 이상)
        if today["high"] < target:
            continue

        entry_price = target
        exit_price = tomorrow["open"]
        pnl = (exit_price * (1 - SELL_FEE)) / (entry_price * (1 + BUY_FEE)) - 1

        features = build_features(candles, idx, btc_by_date)

        trades.append({
            **features,
            "k": k,
            "target": target,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "pnl": pnl * 100,
        })

    return trades


# ══════════════════════════════════════════════════════════
# 다종목 동시 감시 백테스트
# ══════════════════════════════════════════════════════════

def backtest_multicoin(all_data, btc_by_date, filter_fn=None):
    """다종목 동시 감시 → 돌파 강도 최대 종목 매수 시뮬레이션.
    filter_fn: features dict를 받아 True(통과)/False(스킵) 반환하는 함수.
    """
    # 종목별 date→index 매핑
    date_idx = {}
    for market in COINS:
        candles = all_data.get(market, [])
        date_idx[market] = {c["date"]: i for i, c in enumerate(candles)}

    # 공통 날짜 (모든 종목에 데이터 있는 날)
    date_sets = [set(date_idx[m].keys()) for m in COINS if m in date_idx]
    if not date_sets:
        return []
    common_dates = sorted(set.intersection(*date_sets))

    trades = []

    for date in common_dates:
        candidates = []

        for market in COINS:
            candles = all_data[market]
            idx = date_idx[market].get(date)
            if idx is None or idx < BACKTEST_START or idx >= len(candles) - 1:
                continue

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

            features = build_features(candles, idx, btc_by_date)

            # 필터 적용
            if filter_fn and not filter_fn(features):
                continue

            entry_price = target
            exit_price = tomorrow["open"]
            pnl = (exit_price * (1 - SELL_FEE)) / (entry_price * (1 + BUY_FEE)) - 1

            # 돌파 강도: 고가가 목표가를 얼마나 넘었는지
            breakout_strength = (today["high"] - target) / target

            candidates.append({
                "market": market,
                **features,
                "k": k,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "pnl": pnl * 100,
                "breakout_strength": breakout_strength,
            })

        if candidates:
            # 돌파 강도 최대 종목 선택 (일봉 한계상 '첫 돌파' 근사)
            best = max(candidates, key=lambda x: x["breakout_strength"])
            trades.append(best)

    return trades


# ══════════════════════════════════════════════════════════
# 성과 분석
# ══════════════════════════════════════════════════════════

def analyze(trades, label=""):
    """거래 리스트 → 성과 지표 딕셔너리."""
    if not trades:
        return {"label": label, "count": 0}

    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    # 누적 수익률 (복리)
    cumulative = 1.0
    peak = 1.0
    max_dd = 0.0
    for p in pnls:
        cumulative *= (1 + p / 100)
        peak = max(peak, cumulative)
        dd = (peak - cumulative) / peak
        max_dd = max(max_dd, dd)

    return {
        "label": label,
        "count": len(trades),
        "win_rate": len(wins) / len(trades) * 100,
        "avg_pnl": sum(pnls) / len(pnls),
        "avg_win": sum(wins) / len(wins) if wins else 0,
        "avg_loss": sum(losses) / len(losses) if losses else 0,
        "total_return": (cumulative - 1) * 100,
        "max_drawdown": max_dd * 100,
        "best": max(pnls),
        "worst": min(pnls),
    }


def fmt_row(label, r):
    """분석 결과를 한 줄 테이블 행으로 포맷."""
    if r["count"] == 0:
        return f"  {label:<28} 거래 없음"
    return (
        f"  {label:<28} {r['count']:>4}회  "
        f"승률 {r['win_rate']:>5.1f}%  "
        f"평균 {r['avg_pnl']:>+6.2f}%  "
        f"누적 {r['total_return']:>+7.1f}%  "
        f"MDD {r['max_drawdown']:>5.1f}%"
    )


# ══════════════════════════════════════════════════════════
# 필터 정의
# ══════════════════════════════════════════════════════════

def make_noise_filter(threshold):
    """noise_avg_7d > threshold이면 스킵 (횡보장 필터)."""
    def f(feat):
        val = feat.get("noise_avg_7d")
        if val is None:
            return True  # 데이터 없으면 통과
        return val <= threshold
    f.__name__ = f"noise_7d≤{threshold}"
    return f


def filter_btc_down(feat):
    """BTC 하락 추세이면 스킵."""
    return feat.get("btc_trend") != "down"


def filter_low_volume(feat):
    """거래량이 평소의 50% 미만이면 스킵."""
    val = feat.get("volume_ratio")
    if val is None:
        return True
    return val >= 0.5


def filter_high_volume(feat):
    """거래량이 평소의 80% 미만이면 스킵."""
    val = feat.get("volume_ratio")
    if val is None:
        return True
    return val >= 0.8


FILTERS = {
    "noise_7d ≤ 0.65": make_noise_filter(0.65),
    "noise_7d ≤ 0.70": make_noise_filter(0.70),
    "noise_7d ≤ 0.75": make_noise_filter(0.75),
    "BTC 하락 스킵": filter_btc_down,
    "거래량 < 0.5 스킵": filter_low_volume,
    "거래량 < 0.8 스킵": filter_high_volume,
}

# 복합 필터
COMBO_FILTERS = {
    "noise≤0.70 + BTC하락스킵": lambda f: make_noise_filter(0.70)(f) and filter_btc_down(f),
    "noise≤0.70 + 거래량≥0.5": lambda f: make_noise_filter(0.70)(f) and filter_low_volume(f),
    "noise≤0.70 + BTC + 거래량": lambda f: (
        make_noise_filter(0.70)(f) and filter_btc_down(f) and filter_low_volume(f)
    ),
}


# ══════════════════════════════════════════════════════════
# 메인 실행
# ══════════════════════════════════════════════════════════

def main():
    print("=" * 72)
    print("  변동성 돌파 전략 백테스트")
    print("  전략: 당일 시가 + 전일 변동폭 × K 돌파 시 매수, 익일 시가 청산")
    print("  수수료: 매수 0.05% + 매도 0.05%")
    print("=" * 72)

    # ── 1. 데이터 수집 ──
    print("\n[1/5] 데이터 수집")
    all_data = {}
    all_data[BTC_MARKET] = load_or_fetch(BTC_MARKET, FETCH_DAYS)
    for coin in COINS:
        all_data[coin] = load_or_fetch(coin, FETCH_DAYS)
        time.sleep(API_DELAY)

    btc_by_date = {c["date"]: c for c in all_data[BTC_MARKET]}

    # 데이터 범위 출력
    for market in COINS:
        cd = all_data[market]
        if cd:
            print(f"    {market}: {cd[0]['date']} ~ {cd[-1]['date']} ({len(cd)}일)")

    # ── 2. 종목별 개별 성과 ──
    print("\n" + "=" * 72)
    print("[2/5] 종목별 개별 성과 (필터 없음)")
    print("=" * 72)

    coin_trades = {}
    for coin in COINS:
        trades = backtest_single(all_data[coin], btc_by_date)
        coin_trades[coin] = trades
        r = analyze(trades, coin)
        print(fmt_row(coin, r))

    # ── 3. 필터 효과 분석 ──
    print("\n" + "=" * 72)
    print("[3/5] 필터 효과 분석")
    print("=" * 72)

    for coin in COINS:
        trades = coin_trades[coin]
        if not trades:
            continue

        base = analyze(trades, "기준(필터없음)")
        print(f"\n  ── {coin} (기준: {base['count']}회, "
              f"승률 {base['win_rate']:.1f}%, "
              f"누적 {base['total_return']:+.1f}%) ──")

        # 단일 필터
        for fname, ffunc in FILTERS.items():
            passed = [t for t in trades if ffunc(t)]
            skipped = [t for t in trades if not ffunc(t)]
            rp = analyze(passed, fname)
            rs = analyze(skipped, f"(스킵된 거래)")

            skip_avg = f"{rs['avg_pnl']:+.2f}%" if rs["count"] > 0 else "N/A"
            diff = rp["total_return"] - base["total_return"]
            marker = "✓" if diff > 0 else " "

            print(f"  {marker} {fname:<26} "
                  f"{rp['count']:>4}회  "
                  f"승률 {rp['win_rate']:>5.1f}%  "
                  f"누적 {rp['total_return']:>+7.1f}%  "
                  f"(차이 {diff:>+6.1f}%, "
                  f"스킵 {len(skipped)}회 평균 {skip_avg})")

        # 복합 필터
        print(f"  -- 복합 필터 --")
        for fname, ffunc in COMBO_FILTERS.items():
            passed = [t for t in trades if ffunc(t)]
            rp = analyze(passed, fname)
            diff = rp["total_return"] - base["total_return"]
            marker = "✓" if diff > 0 else " "
            skipped_count = base["count"] - rp["count"]
            print(f"  {marker} {fname:<26} "
                  f"{rp['count']:>4}회  "
                  f"승률 {rp['win_rate']:>5.1f}%  "
                  f"누적 {rp['total_return']:>+7.1f}%  "
                  f"(차이 {diff:>+6.1f}%, 스킵 {skipped_count}회)")

    # ── 4. 다종목 동시 감시 시뮬레이션 ──
    print("\n" + "=" * 72)
    print("[4/5] 다종목 동시 감시 → 돌파 강도 최대 종목 매수")
    print("      (일봉 한계: '첫 돌파'를 돌파 강도로 근사)")
    print("=" * 72)

    # 필터 없음
    multi_trades = backtest_multicoin(all_data, btc_by_date)
    multi_base = analyze(multi_trades, "다종목 (필터 없음)")
    print(f"\n{fmt_row('필터 없음', multi_base)}")

    # 종목 선택 분포
    if multi_trades:
        print(f"\n  종목 선택 분포:")
        market_stats = defaultdict(list)
        for t in multi_trades:
            market_stats[t["market"]].append(t["pnl"])
        for m in COINS:
            if m in market_stats:
                pnls = market_stats[m]
                avg = sum(pnls) / len(pnls)
                wr = len([p for p in pnls if p > 0]) / len(pnls) * 100
                print(f"    {m:<12} {len(pnls):>3}회 선택  "
                      f"승률 {wr:>5.1f}%  평균 {avg:>+6.2f}%")

    # 필터 적용
    print(f"\n  -- 필터 적용 비교 --")
    all_filter_fns = {**FILTERS, **COMBO_FILTERS}
    for fname, ffunc in all_filter_fns.items():
        ft = backtest_multicoin(all_data, btc_by_date, filter_fn=ffunc)
        fr = analyze(ft, fname)
        diff = fr["total_return"] - multi_base["total_return"]
        marker = "✓" if diff > 0 else " "
        print(f"  {marker} {fname:<28} "
              f"{fr['count']:>4}회  "
              f"누적 {fr['total_return']:>+7.1f}%  "
              f"(차이 {diff:>+6.1f}%)")

    # ── 5. 트레일링 스탑 시뮬레이션 (분봉 기반) ──
    print("\n" + "=" * 72)
    print("[5/5] 분봉 기반 트레일링 스탑 시뮬레이션")
    print(f"      트레일링 스탑: 고점 대비 -{TRAILING_STOP_PCT*100:.0f}%")
    print("      돌파 발생일의 5분봉 데이터를 가져와 실제 경로대로 시뮬레이션")
    print("=" * 72)

    for coin in COINS:
        trades = coin_trades[coin]
        if not trades:
            continue

        print(f"\n  ── {coin} ({len(trades)}거래) ──")
        print(f"    분봉 데이터 수집 중... (최초 실행 시 시간이 걸립니다)")

        trailing_pnls = []
        nextopen_pnls = []
        comparison = {"trailing_better": 0, "nextopen_better": 0, "same": 0}
        trailing_stop_count = 0
        time_exit_count = 0

        # 승님의 지적: 트레일링에 걸려서 손해 본 케이스 추적
        missed_gains = []  # 트레일링 청산 후 익일 시가가 더 높았던 케이스

        for i, trade in enumerate(trades):
            date_str = trade["date"]
            entry_price = trade["entry_price"]
            nextopen_price = trade["exit_price"]  # 기존 백테스트의 익일 시가

            # 분봉 데이터 가져오기
            minute_candles = load_or_fetch_minutes(coin, date_str)

            if not minute_candles:
                # 분봉 없으면 기존 결과 사용
                trailing_pnls.append(trade["pnl"])
                nextopen_pnls.append(trade["pnl"])
                continue

            # 트레일링 스탑 시뮬레이션
            exit_price, exit_reason, peak, exit_time = simulate_trailing_stop(
                minute_candles, entry_price)

            trail_pnl = (exit_price * (1 - SELL_FEE)) / (entry_price * (1 + BUY_FEE)) - 1
            trail_pnl_pct = trail_pnl * 100
            trailing_pnls.append(trail_pnl_pct)
            nextopen_pnls.append(trade["pnl"])

            if exit_reason == "trailing_stop":
                trailing_stop_count += 1
            else:
                time_exit_count += 1

            # 비교
            if abs(trail_pnl_pct - trade["pnl"]) < 0.01:
                comparison["same"] += 1
            elif trail_pnl_pct > trade["pnl"]:
                comparison["trailing_better"] += 1
            else:
                comparison["nextopen_better"] += 1

            # 트레일링 스탑 후 더 올랐는지 추적
            if exit_reason == "trailing_stop":
                missed = trade["pnl"] - trail_pnl_pct  # 양수면 익일시가가 더 높았음
                missed_gains.append({
                    "date": date_str,
                    "trail_pnl": trail_pnl_pct,
                    "nextopen_pnl": trade["pnl"],
                    "missed": missed,
                    "peak_from_entry": (peak / entry_price - 1) * 100,
                })

            # 진행 상황 (50거래마다)
            if (i + 1) % 50 == 0:
                print(f"    ... {i+1}/{len(trades)} 거래 처리 완료")

        if not trailing_pnls:
            continue

        # 결과 비교
        trail_result = analyze(
            [{"pnl": p} for p in trailing_pnls], "트레일링 스탑")
        next_result = analyze(
            [{"pnl": p} for p in nextopen_pnls], "익일 시가 청산")

        print(f"\n    {'전략':<20} {'거래수':>6} {'승률':>7} {'평균':>8} {'누적':>9} {'MDD':>7}")
        print(f"    {'-'*20} {'-'*6} {'-'*7} {'-'*8} {'-'*9} {'-'*7}")
        print(f"    {'트레일링 스탑 2%':<20} {trail_result['count']:>6} "
              f"{trail_result['win_rate']:>6.1f}% "
              f"{trail_result['avg_pnl']:>+7.2f}% "
              f"{trail_result['total_return']:>+8.1f}% "
              f"{trail_result['max_drawdown']:>6.1f}%")
        print(f"    {'익일 시가 청산':<20} {next_result['count']:>6} "
              f"{next_result['win_rate']:>6.1f}% "
              f"{next_result['avg_pnl']:>+7.2f}% "
              f"{next_result['total_return']:>+8.1f}% "
              f"{next_result['max_drawdown']:>6.1f}%")

        print(f"\n    청산 유형: 트레일링 {trailing_stop_count}회 / "
              f"시간(08:55) {time_exit_count}회")
        print(f"    비교: 트레일링이 나은 {comparison['trailing_better']}회 / "
              f"익일시가가 나은 {comparison['nextopen_better']}회 / "
              f"비슷 {comparison['same']}회")

        # 트레일링에 걸렸는데 더 올랐던 케이스 분석
        if missed_gains:
            missed_positive = [m for m in missed_gains if m["missed"] > 0.1]
            missed_negative = [m for m in missed_gains if m["missed"] < -0.1]

            print(f"\n    [트레일링 스탑 발동 후 분석] (총 {len(missed_gains)}회)")
            print(f"    → 트레일링 후 더 올라간 날 (손해): {len(missed_positive)}회")
            if missed_positive:
                avg_missed = sum(m["missed"] for m in missed_positive) / len(missed_positive)
                print(f"      평균 놓친 수익: {avg_missed:+.2f}%p")
                worst_3 = sorted(missed_positive, key=lambda x: -x["missed"])[:3]
                for m in worst_3:
                    print(f"      예) {m['date']}: 트레일링 {m['trail_pnl']:+.2f}% → "
                          f"익일시가 {m['nextopen_pnl']:+.2f}% "
                          f"(고점 +{m['peak_from_entry']:.1f}%)")

            print(f"    → 트레일링이 수익 지켜준 날 (이득): {len(missed_negative)}회")
            if missed_negative:
                avg_saved = sum(m["missed"] for m in missed_negative) / len(missed_negative)
                print(f"      평균 지켜낸 수익: {abs(avg_saved):.2f}%p")
                best_3 = sorted(missed_negative, key=lambda x: x["missed"])[:3]
                for m in best_3:
                    print(f"      예) {m['date']}: 트레일링 {m['trail_pnl']:+.2f}% → "
                          f"익일시가 {m['nextopen_pnl']:+.2f}% "
                          f"(고점 +{m['peak_from_entry']:.1f}%)")

    # ── 요약 ──
    print("\n" + "=" * 72)
    print("  요약 및 주의사항")
    print("=" * 72)
    print("""
  [백테스트 구성]
  - 섹션 2~4: 익일 시가 청산 기준 (전략/필터/종목 비교용)
  - 섹션 5: 분봉 기반 트레일링 스탑 시뮬 (실전 봇과 동일 로직)

  [한계]
  - 다종목 시뮬의 '첫 돌파' 선택은 돌파 강도 기준 (실제 시간순 아님)
  - 슬리피지/호가 스프레드 미반영 (시장가 매수 가정)
  - 과거 성과 ≠ 미래 성과. 과적합 주의

  [활용법]
  - 종목별 성과: 어떤 코인이 변동성 돌파에 유리한지 비교
  - 필터 효과: ✓ 마크가 붙은 필터 = 기준 대비 누적 수익 개선
  - 스킵 거래 평균: 필터가 걸러낸 거래의 실제 수익률
    → 음수이면 필터가 손실을 잘 걸러낸 것
    → 양수이면 필터가 수익 기회도 함께 걸러낸 것 (과도한 필터)
  - 트레일링 시뮬: 실전 봇 기준 성과 확인
    → "트레일링 후 더 올라간 날" = 트레일링이 기회비용 발생시킨 날
    → "트레일링이 수익 지켜준 날" = 트레일링이 손실 방어한 날
    """)


if __name__ == "__main__":
    main()
