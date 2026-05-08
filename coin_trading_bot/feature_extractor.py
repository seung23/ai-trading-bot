# feature_extractor.py
# 진입 시점 피처 계산 전담 모듈
# ──────────────────────────────────────────────────────────
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))


def compute_noise_1d(candle):
    """1일 노이즈 비율. high==low이면 0 반환."""
    day_range = candle["high"] - candle["low"]
    if day_range == 0:
        return 0.0
    return 1 - abs(candle["close"] - candle["open"]) / day_range


def compute_noise_avg(candles, n):
    """최근 n일 각각의 1일 노이즈를 산술평균."""
    if len(candles) < n:
        return None
    values = [compute_noise_1d(c) for c in candles[:n]]
    return sum(values) / len(values)


def compute_noise_window(candles, n):
    """n일 윈도우 방식 노이즈 비율."""
    if len(candles) < n:
        return None
    window = candles[:n]
    period_open = window[-1]["open"]      # 가장 오래된 날의 시가
    period_close = window[0]["close"]     # 가장 최근 날의 종가
    period_high = max(c["high"] for c in window)
    period_low = min(c["low"] for c in window)
    period_range = period_high - period_low
    if period_range == 0:
        return 0.0
    return 1 - abs(period_close - period_open) / period_range


def compute_volume_ratio(candles, n=5):
    """어제 거래량 / 최근 n일 평균 거래량."""
    if len(candles) < n + 1:
        return None
    # candles[0] = 오늘(진행중), candles[1] = 어제
    yesterday_vol = candles[1]["volume"]
    avg_vol = sum(c["volume"] for c in candles[1:n + 1]) / n
    if avg_vol == 0:
        return None
    return yesterday_vol / avg_vol


def compute_btc_trend(btc_candles):
    """BTC 24시간 추세: 'up' / 'down' / 'flat'.
    btc_candles[0] = 오늘(진행중), btc_candles[1] = 어제.
    """
    if len(btc_candles) < 2:
        return "flat"
    yesterday_close = btc_candles[1]["close"]
    today_price = btc_candles[0]["close"]
    if yesterday_close == 0:
        return "flat"
    change_pct = (today_price - yesterday_close) / yesterday_close * 100
    if change_pct > 1:
        return "up"
    elif change_pct < -1:
        return "down"
    return "flat"


def compute_btc_24h_change(btc_candles):
    """BTC 24시간 수익률(%)."""
    if len(btc_candles) < 2:
        return None
    yesterday_close = btc_candles[1]["close"]
    today_price = btc_candles[0]["close"]
    if yesterday_close == 0:
        return None
    return (today_price - yesterday_close) / yesterday_close * 100


def extract_all_features(eth_daily, btc_daily, current_price, k_value, target_price):
    """모든 피처를 통합 계산하여 dict로 반환.
    개별 피처 실패 시 None으로 저장, 나머지는 정상 진행.

    eth_daily: 최신순 ETH 일봉 리스트 (최소 15개 권장)
    btc_daily: 최신순 BTC 일봉 리스트 (최소 2개)
    """
    features = {}
    now = datetime.now(KST)

    try:
        features["k_value"] = k_value
    except Exception:
        features["k_value"] = None

    try:
        features["target_price"] = target_price
    except Exception:
        features["target_price"] = None

    # 노이즈 비율 (1일) — eth_daily[1] = 어제
    try:
        features["noise_1d"] = compute_noise_1d(eth_daily[1]) if len(eth_daily) > 1 else None
    except Exception:
        features["noise_1d"] = None

    # 노이즈 비율 (평균 방식)
    for n in [3, 7, 14]:
        try:
            features[f"noise_avg_{n}d"] = compute_noise_avg(eth_daily[1:], n)
        except Exception:
            features[f"noise_avg_{n}d"] = None

    # 노이즈 비율 (윈도우 방식)
    for n in [3, 7, 14]:
        try:
            features[f"noise_window_{n}d"] = compute_noise_window(eth_daily[1:], n)
        except Exception:
            features[f"noise_window_{n}d"] = None

    # 거래량 비율
    try:
        features["volume_ratio"] = compute_volume_ratio(eth_daily)
    except Exception:
        features["volume_ratio"] = None

    # BTC 추세
    try:
        features["btc_trend"] = compute_btc_trend(btc_daily)
    except Exception:
        features["btc_trend"] = None

    try:
        features["btc_24h_change_pct"] = compute_btc_24h_change(btc_daily)
    except Exception:
        features["btc_24h_change_pct"] = None

    # 시간 정보
    features["hour_kst"] = now.hour
    features["day_of_week"] = now.weekday()

    # 어제 OHLC (raw 저장)
    try:
        yesterday = eth_daily[1]
        features["prev_open"] = yesterday["open"]
        features["prev_high"] = yesterday["high"]
        features["prev_low"] = yesterday["low"]
        features["prev_close"] = yesterday["close"]
        features["prev_volume"] = yesterday["volume"]
    except Exception:
        for key in ["prev_open", "prev_high", "prev_low", "prev_close", "prev_volume"]:
            features[key] = None

    return features
