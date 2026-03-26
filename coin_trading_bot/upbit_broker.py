# upbit_broker.py
# 업비트 REST API 래퍼 (broker.py 대응)
# ──────────────────────────────────────────────────────────
# 인증: JWT (PyJWT + hashlib)
# 매 요청마다 access_key + nonce로 토큰 생성
# ──────────────────────────────────────────────────────────
import uuid
import hashlib
import jwt
import requests
from urllib.parse import urlencode, unquote

API_BASE = "https://api.upbit.com"
API_TIMEOUT = 10


def _make_token(access_key, secret_key, query=None):
    """업비트 JWT 토큰을 생성합니다."""
    payload = {
        "access_key": access_key,
        "nonce": str(uuid.uuid4()),
    }
    if query:
        query_string = unquote(urlencode(query, doseq=True)).encode()
        m = hashlib.sha512()
        m.update(query_string)
        payload["query_hash"] = m.hexdigest()
        payload["query_hash_alg"] = "SHA512"

    return jwt.encode(payload, secret_key)


def _safe_json(res):
    """응답을 JSON으로 파싱합니다. 실패 시 빈 dict/list 반환."""
    try:
        return res.json()
    except (ValueError, TypeError):
        print(f"   JSON 파싱 실패 (HTTP {res.status_code}): {res.text[:200]}")
        return {}


# ── 시세 조회 (인증 불필요) ──

def get_current_price(market="KRW-ETH"):
    """현재가를 조회합니다. 실패 시 None 반환."""
    url = f"{API_BASE}/v1/ticker"
    params = {"markets": market}
    try:
        res = requests.get(url, params=params, timeout=API_TIMEOUT)
        data = _safe_json(res)
        if isinstance(data, list) and len(data) > 0:
            return float(data[0]["trade_price"])
    except requests.exceptions.RequestException as e:
        print(f"   현재가 조회 실패: {e}")
    return None


def get_yesterday_ohlc(market="KRW-ETH"):
    """전일 일봉 OHLC를 조회합니다. 실패 시 None 반환.
    Returns: dict {open, high, low, close} or None
    """
    url = f"{API_BASE}/v1/candles/days"
    params = {"market": market, "count": 2}
    try:
        res = requests.get(url, params=params, timeout=API_TIMEOUT)
        data = _safe_json(res)
        if isinstance(data, list) and len(data) >= 2:
            # data[0] = 오늘(진행중), data[1] = 어제(완성)
            y = data[1]
            return {
                "open": float(y["opening_price"]),
                "high": float(y["high_price"]),
                "low": float(y["low_price"]),
                "close": float(y["trade_price"]),
            }
    except requests.exceptions.RequestException as e:
        print(f"   전일 OHLC 조회 실패: {e}")
    return None


def get_today_open(market="KRW-ETH"):
    """당일 시가를 조회합니다. 실패 시 None 반환."""
    url = f"{API_BASE}/v1/candles/days"
    params = {"market": market, "count": 1}
    try:
        res = requests.get(url, params=params, timeout=API_TIMEOUT)
        data = _safe_json(res)
        if isinstance(data, list) and len(data) > 0:
            return float(data[0]["opening_price"])
    except requests.exceptions.RequestException as e:
        print(f"   당일 시가 조회 실패: {e}")
    return None


# ── 계좌 조회 (인증 필요) ──

def get_balance(access_key, secret_key):
    """KRW 현금 잔고를 반환합니다. 실패 시 0 반환."""
    url = f"{API_BASE}/v1/accounts"
    token = _make_token(access_key, secret_key)
    headers = {"Authorization": f"Bearer {token}"}
    try:
        res = requests.get(url, headers=headers, timeout=API_TIMEOUT)
        data = _safe_json(res)
        if isinstance(data, list):
            for item in data:
                if item.get("currency") == "KRW":
                    return float(item.get("balance", 0))
    except requests.exceptions.RequestException as e:
        print(f"   잔고 조회 실패: {e}")
    return 0


def get_holding_quantity(access_key, secret_key, currency="ETH"):
    """특정 코인 보유 수량을 반환합니다. 미보유 0, API 실패 시 None."""
    url = f"{API_BASE}/v1/accounts"
    token = _make_token(access_key, secret_key)
    headers = {"Authorization": f"Bearer {token}"}
    try:
        res = requests.get(url, headers=headers, timeout=API_TIMEOUT)
        data = _safe_json(res)
        if isinstance(data, list):
            for item in data:
                if item.get("currency") == currency:
                    return float(item.get("balance", 0))
            return 0  # 코인을 보유하고 있지 않음
    except requests.exceptions.RequestException as e:
        print(f"   보유수량 조회 실패: {e}")
    return None  # API 실패


def get_avg_buy_price(access_key, secret_key, currency="ETH"):
    """특정 코인 매수 평균가를 반환합니다. 미보유 0, API 실패 시 0."""
    url = f"{API_BASE}/v1/accounts"
    token = _make_token(access_key, secret_key)
    headers = {"Authorization": f"Bearer {token}"}
    try:
        res = requests.get(url, headers=headers, timeout=API_TIMEOUT)
        data = _safe_json(res)
        if isinstance(data, list):
            for item in data:
                if item.get("currency") == currency:
                    return float(item.get("avg_buy_price", 0))
    except requests.exceptions.RequestException as e:
        print(f"   매수평균가 조회 실패: {e}")
    return 0


# ── 주문 (인증 필요) ──

def post_buy_order(access_key, secret_key, market="KRW-ETH", price=0):
    """시장가 매수 (KRW 금액 지정). 업비트는 매수 시 금액(원)을 지정합니다.
    Returns: 응답 dict (uuid 포함) or 에러 dict
    """
    url = f"{API_BASE}/v1/orders"
    query = {
        "market": market,
        "side": "bid",
        "ord_type": "price",   # 시장가 매수 = KRW 금액 지정
        "price": str(price),
    }
    token = _make_token(access_key, secret_key, query)
    headers = {"Authorization": f"Bearer {token}"}
    try:
        res = requests.post(url, json=query, headers=headers, timeout=API_TIMEOUT)
        return _safe_json(res)
    except requests.exceptions.RequestException as e:
        print(f"   매수 주문 실패: {e}")
        return {"error": {"message": str(e)}}


def post_sell_order(access_key, secret_key, market="KRW-ETH", volume=0):
    """시장가 매도 (코인 수량 지정).
    Returns: 응답 dict (uuid 포함) or 에러 dict
    """
    url = f"{API_BASE}/v1/orders"
    query = {
        "market": market,
        "side": "ask",
        "ord_type": "market",   # 시장가 매도 = 수량 지정
        "volume": str(volume),
    }
    token = _make_token(access_key, secret_key, query)
    headers = {"Authorization": f"Bearer {token}"}
    try:
        res = requests.post(url, json=query, headers=headers, timeout=API_TIMEOUT)
        return _safe_json(res)
    except requests.exceptions.RequestException as e:
        print(f"   매도 주문 실패: {e}")
        return {"error": {"message": str(e)}}


def get_order(access_key, secret_key, uuid_str):
    """주문 상태를 조회합니다.
    Returns: 응답 dict or 빈 dict
    """
    url = f"{API_BASE}/v1/order"
    query = {"uuid": uuid_str}
    token = _make_token(access_key, secret_key, query)
    headers = {"Authorization": f"Bearer {token}"}
    try:
        res = requests.get(url, params=query, headers=headers, timeout=API_TIMEOUT)
        return _safe_json(res)
    except requests.exceptions.RequestException as e:
        print(f"   주문 조회 실패: {e}")
        return {}
