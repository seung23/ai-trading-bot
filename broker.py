# broker.py
import requests
import json
import os
from dotenv import load_dotenv

load_dotenv()

APP_KEY = os.getenv("APP_KEY")
APP_SECRET = os.getenv("APP_SECRET")
URL_REAL = os.getenv("URL_REAL")     # 실전 서버 (시세용)
URL_MOCK = os.getenv("URL_MOCK")  # 모의 서버 (잔고/주문용)

API_TIMEOUT = 10  # 모든 API 호출의 타임아웃 (초)

# ── 실전/모의 tr_id 매핑 ──
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

def _safe_json(res):
    """응답을 JSON으로 파싱합니다. 실패 시 빈 dict 반환."""
    try:
        return res.json()
    except (ValueError, TypeError):
        print(f"❌ JSON 파싱 실패 (HTTP {res.status_code}): {res.text[:200]}")
        return {}

def get_access_token(app_key, app_secret, url_base):
    headers = {"content-type":"application/json"}
    body = {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "appsecret": app_secret
    }
    PATH = "oauth2/tokenP"
    URL = f"{url_base}/{PATH}"

    try:
        res = requests.post(URL, headers=headers, data=json.dumps(body), timeout=API_TIMEOUT)
        res_data = _safe_json(res)
    except requests.exceptions.RequestException as e:
        print(f"❌ 토큰 발급 요청 실패: {e}")
        return None

    if 'access_token' in res_data:
        return res_data['access_token']
    else:
        print("❌ 토큰 발급 실패!")
        print(f"응답 내용: {res_data}")
        return None

def get_current_price(token, app_key, app_secret, url_base, stock_code):
    """한국투자증권 API를 통해 현재가를 가져옵니다."""
    PATH = "uapi/domestic-stock/v1/quotations/inquire-price"
    URL = f"{url_base}/{PATH}"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": "FHKST01010100"
    }

    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": stock_code
    }

    try:
        res = requests.get(URL, headers=headers, params=params, timeout=API_TIMEOUT)
        res_data = _safe_json(res)
    except requests.exceptions.RequestException as e:
        print(f"❌ 현재가 조회 요청 실패: {e}")
        return None

    if res_data.get('output'):
        return float(res_data['output']['stck_prpr'])
    else:
        print(f"❌ 시세 조회 실패: {res_data.get('msg1')}")
        return None

def get_yesterday_ohlc(token, app_key, app_secret, url_base, stock_code):
    """KIS API를 통해 전일 시가/고가/저가/종가를 가져옵니다."""
    PATH = "uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
    URL = f"{url_base}/{PATH}"

    from datetime import datetime, timezone, timedelta
    kst = timezone(timedelta(hours=9))
    today = datetime.now(kst)
    today_str = today.strftime('%Y%m%d')
    # 시작일을 30일 전으로 설정하여 전일 데이터가 반드시 포함되도록 함
    start_str = (today - timedelta(days=30)).strftime('%Y%m%d')

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": "FHKST03010100"
    }

    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": stock_code,
        "FID_INPUT_DATE_1": start_str,
        "FID_INPUT_DATE_2": today_str,
        "FID_PERIOD_DIV_CODE": "D",
        "FID_ORG_ADJ_PRC": "0"
    }

    try:
        res = requests.get(URL, headers=headers, params=params, timeout=API_TIMEOUT)
        res_data = _safe_json(res)
        items = res_data.get('output2', [])
        if items and len(items) >= 1:
            # output2[0]은 당일(또는 가장 최근), 전일 데이터를 찾음
            for item in items:
                if item.get('stck_bsop_date') != today_str:
                    return {
                        'open': float(item['stck_oprc']),
                        'high': float(item['stck_hgpr']),
                        'low': float(item['stck_lwpr']),
                        'close': float(item['stck_clpr'])
                    }
            # 전일 데이터를 찾지 못한 경우 (모든 항목이 당일)
            print(f"⚠️ KIS API: 전일 데이터를 찾지 못했습니다. (항목 수: {len(items)}, 모두 당일 날짜)")
            return None
    except Exception as e:
        print(f"❌ KIS API 전일 데이터 조회 실패: {e}")
    return None


def get_today_open(token, app_key, app_secret, url_base, stock_code):
    """한국투자증권 API를 통해 당일 시가를 가져옵니다."""
    PATH = "uapi/domestic-stock/v1/quotations/inquire-price"
    URL = f"{url_base}/{PATH}"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": "FHKST01010100"
    }

    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": stock_code
    }

    try:
        res = requests.get(URL, headers=headers, params=params, timeout=API_TIMEOUT)
        res_data = _safe_json(res)
    except requests.exceptions.RequestException as e:
        print(f"❌ 시가 조회 요청 실패: {e}")
        return None

    if res_data.get('output'):
        return float(res_data['output']['stck_oprc'])
    else:
        print(f"❌ 시가 조회 실패: {res_data.get('msg1')}")
        return None


def get_balance(token, app_key, app_secret, url_base, acc_no, stock_code, mode="MOCK"):
    """계좌의 현금 잔고(주문 가능 금액)를 숫자로 반환합니다."""
    PATH = "uapi/domestic-stock/v1/trading/inquire-psbl-order"
    URL = f"{url_base}/{PATH}"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": TR_IDS[mode]["balance_inquiry"]
    }

    params = {
        "CANO": acc_no,
        "ACNT_PRDT_CD": "01",
        "PDNO": stock_code,
        "ORD_UNPR": "0",
        "ORD_DVSN": "00",
        "CMA_EVLU_AMT_ICLD_YN": "Y",
        "OVRS_ICLD_YN": "N"
    }

    try:
        res = requests.get(URL, headers=headers, params=params, timeout=API_TIMEOUT)
        res_data = _safe_json(res)
    except requests.exceptions.RequestException as e:
        print(f"❌ 잔고 조회 요청 실패: {e}")
        return 0

    # 주문 가능 현금 추출
    output = res_data.get('output', {})
    cash = output.get('ord_psbl_cash') or output.get('nrcvb_buy_amt') or '0'
    return int(float(cash))

def get_stock_balance(token, app_key, app_secret, url_base, acc_no, stock_code, mode="MOCK"):
    """특정 종목의 매수 평균가를 반환합니다. 보유하지 않으면 0 반환."""
    PATH = "uapi/domestic-stock/v1/trading/inquire-balance"
    URL = f"{url_base}/{PATH}"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": TR_IDS[mode]["stock_balance"]
    }

    params = {
        "CANO": acc_no,
        "ACNT_PRDT_CD": "01",
        "AFHR_FLG": "N",
        "OVAL_DVSN": "00",
        "IVRE_DVSN": "01",
        "SORT_DVSN": "01",
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": ""
    }

    try:
        res = requests.get(URL, headers=headers, params=params, timeout=API_TIMEOUT)
        res_data = _safe_json(res)
    except requests.exceptions.RequestException as e:
        print(f"❌ 종목잔고 조회 요청 실패: {e}")
        return 0

    stocks = res_data.get('output1', [])

    if not stocks:
        print("🔎 잔고가 비어있습니다.")
        return 0

    for s in stocks:
        if s.get('pdno') == stock_code:
            avg_price = s.get('pavg') or s.get('pchs_avg_pric') or s.get('prvs_pdno_pavg')
            if avg_price:
                print(f"🎯 잔고 확인 성공! 매수단가: {avg_price}원")
                return float(avg_price)
            else:
                print(f"⚠️ 매수단가 키를 찾을 수 없어요. 실제 데이터: {s}")
                return 0
    return 0

def get_holding_quantity(token, app_key, app_secret, url_base, acc_no, stock_code, mode="MOCK"):
    """특정 종목의 보유 수량을 반환합니다. 보유하지 않으면 0 반환."""
    PATH = "uapi/domestic-stock/v1/trading/inquire-balance"
    URL = f"{url_base}/{PATH}"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": TR_IDS[mode]["stock_balance"]
    }

    params = {
        "CANO": acc_no,
        "ACNT_PRDT_CD": "01",
        "AFHR_FLG": "N",
        "OVAL_DVSN": "00",
        "IVRE_DVSN": "01",
        "SORT_DVSN": "01",
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": ""
    }

    try:
        res = requests.get(URL, headers=headers, params=params, timeout=API_TIMEOUT)
        res_data = _safe_json(res)
    except requests.exceptions.RequestException as e:
        print(f"❌ 보유수량 조회 요청 실패: {e}")
        return 0

    stocks = res_data.get('output1', [])
    for s in stocks:
        if s.get('pdno') == stock_code:
            qty = s.get('hldg_qty') or s.get('cblc_qty13') or '0'
            return int(float(qty))
    return 0

# 매수
def post_order(token, app_key, app_secret, url_base, acc_no, stock_code, quantity, price, mode="MOCK"):
    PATH = "uapi/domestic-stock/v1/trading/order-cash"
    URL = f"{url_base}/{PATH}"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": TR_IDS[mode]["buy_order"]
    }

    body = {
        "CANO": acc_no,
        "ACNT_PRDT_CD": "01",
        "PDNO": stock_code,
        "ORD_DVSN": "01",
        "ORD_QTY": str(quantity),
        "ORD_UNPR": "0"
    }

    try:
        res = requests.post(URL, headers=headers, data=json.dumps(body), timeout=API_TIMEOUT)
        return _safe_json(res)
    except requests.exceptions.RequestException as e:
        print(f"❌ 매수 주문 요청 실패: {e}")
        return {"rt_cd": "-1", "msg1": str(e)}

# 매도
def post_sell_order(token, app_key, app_secret, url_base, acc_no, stock_code, quantity, price, mode="MOCK"):
    PATH = "uapi/domestic-stock/v1/trading/order-cash"
    URL = f"{url_base}/{PATH}"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": TR_IDS[mode]["sell_order"]
    }

    body = {
        "CANO": acc_no,
        "ACNT_PRDT_CD": "01",
        "PDNO": stock_code,
        "ORD_DVSN": "01",
        "ORD_QTY": str(quantity),
        "ORD_UNPR": "0"
    }

    try:
        res = requests.post(URL, headers=headers, data=json.dumps(body), timeout=API_TIMEOUT)
        return _safe_json(res)
    except requests.exceptions.RequestException as e:
        print(f"❌ 매도 주문 요청 실패: {e}")
        return {"rt_cd": "-1", "msg1": str(e)}
