# main.py
# Larry Williams 변동성 돌파 전략 (🔴 실전투자)
# ──────────────────────────────────────────────────────────
# 전략:
#   목표가 = 당일시가 + (전일고가 - 전일저가) × K
#   현재가 ≥ 목표가 → 매수 (1회)
#   15:15 → 무조건 청산 (당일 매매 완결)
# ──────────────────────────────────────────────────────────
import os
import csv
import time
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
import yfinance as yf
import pandas as pd

import broker
from telegram_notifier import TelegramNotifier

# ── 환경 설정 ──
load_dotenv()
APP_KEY = os.getenv("APP_KEY")
APP_SECRET = os.getenv("APP_SECRET")
ACC_NO = os.getenv("ACC_NO")
URL_REAL = os.getenv("URL_REAL")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

TICKER = "229200.KS"       # KODEX 코스닥150 (일반)
STOCK_CODE = "229200"

# ── 전략 파라미터 ──
BOT_NAME = "Volatility-REAL"
LOG_FILE = "trade_log_volatility_real.csv"
K_MIN = 0.3                # 추세 명확 시 최소 K (노이즈 비율 ≤ 0.4)
K_MAX = 0.6                # 노이즈 심할 때 최대 K (노이즈 비율 ≥ 0.7)
MAX_SLIPPAGE = 0.01        # 목표가 대비 1% 이상 올라가 있으면 매수 스킵
POSITION_RATIO = 0.70      # 현금의 70% 투입 (일반 ETF는 변동성 낮아 비중 확대)
CHECK_INTERVAL = 2         # 2초마다 체크 (API 응답 포함 실제 ~3초 주기)
# ETF 수수료 (실전투자: 0.004%, 수수료 우대 계좌, 거래세 면제)
BUY_FEE = 0.00004         # 매수 수수료 0.004%
SELL_FEE = 0.00004        # 매도 수수료 0.004%


# ── 유틸리티 ──
def log_trade(side, price, quantity, profit=0, reason=""):
    kst = timezone(timedelta(hours=9))
    file_exists = os.path.isfile(LOG_FILE)
    with open(LOG_FILE, mode='a', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(['시간', '구분', '가격', '수량', '순수익률', '사유', '참고사항'])
        time_str = datetime.now(kst).strftime('%Y-%m-%d %H:%M:%S')
        writer.writerow([time_str, side, price, quantity, f"{profit:.2f}%", reason, "[실전] ETF 매수 0.004% + 매도 0.004%"])


def load_unclosed_position():
    """CSV에서 미청산 포지션을 복구합니다."""
    if not os.path.isfile(LOG_FILE):
        return 0, 0
    df = pd.read_csv(LOG_FILE, encoding='utf-8-sig')
    if len(df) == 0:
        return 0, 0
    last = df.iloc[-1]
    if last['구분'] == '매수':
        return float(last['가격']), int(last['수량'])
    return 0, 0


def notify(notifier, title, body):
    kst = timezone(timedelta(hours=9))
    msg = f"[{BOT_NAME}] {title}\n\n{body}\n시간: {datetime.now(kst).strftime('%H:%M:%S')}"
    notifier.send_message(msg)


def is_market_open():
    kst = timezone(timedelta(hours=9))
    now = datetime.now(kst)
    return (9 <= now.hour < 15) or (now.hour == 15 and now.minute < 20)


def wait_for_market_open():
    kst = timezone(timedelta(hours=9))
    while True:
        now = datetime.now(kst)
        if now.hour >= 9:
            return
        remaining = (9 - now.hour - 1) * 3600 + (60 - now.minute) * 60
        if remaining > 60:
            print(f"⏰ 장 시작 대기 중... ({remaining // 60}분 남음)")
            time.sleep(60)
        else:
            time.sleep(10)


def get_yesterday_range_yf():
    """(fallback) yfinance로 전일 고가-저가 변동폭과 시가/종가를 구합니다."""
    df = yf.download(TICKER, period='5d', interval='1d', timeout=10)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # 한국 시간 기준 오늘 (UTC+9)
    kst = timezone(timedelta(hours=9))
    today = datetime.now(kst).date()
    df_past = df[df.index.date < today]

    if len(df_past) == 0:
        print("❌ yfinance: 전일 데이터를 찾을 수 없습니다.")
        return None, None, None, None, None

    yesterday = df_past.iloc[-1]
    return (float(yesterday['High']), float(yesterday['Low']),
            float(yesterday['High'] - yesterday['Low']),
            float(yesterday['Open']), float(yesterday['Close']))


def get_yesterday_range(token=None):
    """전일 고가-저가 변동폭과 시가/종가를 구합니다.
    1차: KIS API (빠르고 안정적)
    2차: yfinance (fallback, timeout 10초)
    """
    # 1차: KIS API
    if token:
        ohlc = broker.get_yesterday_ohlc(token, APP_KEY, APP_SECRET, URL_REAL, STOCK_CODE)
        if ohlc:
            high, low = ohlc['high'], ohlc['low']
            print(f"✅ KIS API로 전일 데이터 조회 성공")
            return high, low, high - low, ohlc['open'], ohlc['close']
        print("⚠️ KIS API 전일 데이터 실패, yfinance로 대체 시도...")

    # 2차: yfinance (timeout 포함)
    try:
        return get_yesterday_range_yf()
    except Exception as e:
        print(f"❌ yfinance 전일 데이터 조회 실패: {e}")
        return None, None, None, None, None


def calculate_dynamic_k(yesterday_open, yesterday_close, yesterday_high, yesterday_low):
    """전일 노이즈 비율로 K를 동적으로 결정합니다.

    노이즈 비율 = 1 - (|시가 - 종가| / (고가 - 저가))
    - 노이즈 ≤ 0.4 → 추세 명확 → K = 0.3 (공격적)
    - 노이즈 ≥ 0.7 → 잔파도 심함 → K = 0.6 (보수적)
    - 그 사이 → 선형 보간
    """
    day_range = yesterday_high - yesterday_low
    if day_range == 0:
        return K_MAX  # 변동 없으면 보수적으로

    noise_ratio = 1 - abs(yesterday_open - yesterday_close) / day_range

    # 노이즈 비율 0.4~0.7 구간을 K_MIN~K_MAX로 선형 보간
    if noise_ratio <= 0.4:
        k = K_MIN
    elif noise_ratio >= 0.7:
        k = K_MAX
    else:
        k = K_MIN + (noise_ratio - 0.4) / (0.7 - 0.4) * (K_MAX - K_MIN)

    return round(k, 2)


def get_today_open_yf():
    """(fallback) 당일 시가를 yfinance 5분봉 첫 캔들에서 가져옵니다."""
    df = yf.download(TICKER, period='1d', interval='5m', timeout=10)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    if df is None or len(df) == 0:
        return None

    return float(df.iloc[0]['Open'])


# ── 메인 봇 ──
def run_bot():
    notifier = TelegramNotifier(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    notify(notifier, "🚀 <b>변동성 돌파 봇 시작</b>", "모드: 🔴 실전투자")

    print("=" * 60)
    print(f"🚀 Larry Williams 변동성 돌파 봇 시작! (🔴 실전투자)")
    print("=" * 60)

    try:
        # ── STEP 1: 토큰 발급 ──
        token = broker.get_access_token(APP_KEY, APP_SECRET, URL_REAL)
        if not token:
            notify(notifier, "❌ <b>에러</b>", "토큰 발급 실패")
            print("❌ 토큰 발급 실패. 종료합니다.")
            return

        # ── STEP 2: 전일 변동폭 + 노이즈 기반 K 계산 ──
        yesterday_high, yesterday_low, yesterday_range, yesterday_open, yesterday_close = get_yesterday_range(token)
        if yesterday_range is None:
            notify(notifier, "❌ <b>에러</b>", "전일 데이터 조회 실패")
            return

        K = calculate_dynamic_k(yesterday_open, yesterday_close, yesterday_high, yesterday_low)
        noise_ratio = 1 - abs(yesterday_open - yesterday_close) / (yesterday_high - yesterday_low) if yesterday_high != yesterday_low else 1.0

        print(f"📊 전일 고가: {yesterday_high:,.0f}원, 저가: {yesterday_low:,.0f}원")
        print(f"   변동폭: {yesterday_range:,.0f}원")
        print(f"   노이즈 비율: {noise_ratio:.2f} → K={K} (범위: {K_MIN}~{K_MAX})")

        # ── STEP 3: 미청산 포지션 확인 (CSV + 실제 계좌 교차 검증) ──
        bought_price, holding_qty = load_unclosed_position()
        if bought_price > 0:
            # CSV에 미청산 기록이 있어도, 실제 계좌 잔고로 검증
            actual_qty = broker.get_holding_quantity(
                token, APP_KEY, APP_SECRET, URL_REAL, ACC_NO, STOCK_CODE, mode="REAL")
            if actual_qty > 0:
                holding_qty = actual_qty  # 실제 수량으로 덮어씀
                print(f"⚡ 미청산 포지션 복구: {holding_qty}주, 매수가 {bought_price:,.0f}원")
                state = "BOUGHT"
            else:
                print(f"⚠️ CSV에 미청산 기록 있으나 실제 잔고 없음 → 포지션 없음으로 처리")
                notify(notifier, "⚠️ <b>포지션 불일치</b>",
                       f"CSV: {holding_qty}주 보유 기록\n실제 계좌: 0주\n신규 매매로 진행합니다.")
                bought_price, holding_qty = 0, 0
                state = "WAITING"
        else:
            state = "WAITING"

        # ── STEP 4: 장 시작 대기 + 시가 캡처 ──
        if state == "WAITING":
            if not is_market_open():
                print("장 시작을 기다립니다...")
                wait_for_market_open()

            # 시가 캡처 (KIS API로 정확한 시가 조회, 재시도 포함)
            today_open = None
            max_retries = 6  # 최대 30초 (5초 × 6회)
            for attempt in range(max_retries):
                time.sleep(5)  # 장 시작 직후 API 안정화 대기
                today_open = broker.get_today_open(token, APP_KEY, APP_SECRET, URL_REAL, STOCK_CODE)
                if today_open is not None and today_open > 0:
                    print(f"✅ 시가 조회 성공: {today_open:,.0f}원 (시도 {attempt+1}회)")
                    break
                print(f"⏳ 시가 조회 재시도 중... ({attempt+1}/{max_retries})")
            else:
                # 재시도 실패, fallback
                print("⚠️ KIS API 시가 조회 실패 (30초 타임아웃), yfinance로 대체")
                today_open = get_today_open_yf()

            if today_open is None or today_open == 0:
                notify(notifier, "❌ <b>에러</b>", "시가 조회 실패")
                print("❌ 시가 조회 실패. 종료합니다.")
                return

            target_price = today_open + yesterday_range * K
            print(f"\n📋 오늘의 전략:")
            print(f"   시가: {today_open:,.0f}원")
            print(f"   목표가: {target_price:,.0f}원 (시가 + {yesterday_range:,.0f} × {K})")
            print(f"   청산: 15:15 장마감 전 무조건 청산")
            print("=" * 60)

            notify(notifier, "📋 <b>오늘의 목표가</b>",
                   f"시가: {today_open:,.0f}원\n"
                   f"목표가: {target_price:,.0f}원\n"
                   f"변동폭: {yesterday_range:,.0f}원 × K={K}\n"
                   f"노이즈: {noise_ratio:.2f} (K범위: {K_MIN}~{K_MAX})")
        else:
            # 미청산 포지션이 있으면 목표가 불필요 (이미 매수됨)
            target_price = 0
            today_open = 0

    except Exception as e:
        error_msg = f"초기화 중 에러: {str(e)}"
        import traceback
        traceback.print_exc()
        notify(notifier, "❌ <b>초기화 에러 (봇 종료)</b>", error_msg)
        print(f"❌ {error_msg}")
        return

    # ── STEP 5: 메인 루프 ──
    print(f"\n👀 모니터링 시작 (1분 간격)")
    print("-" * 40)

    kst = timezone(timedelta(hours=9))
    while True:
        try:
            now = datetime.now(kst)

            # 장 마감 체크
            if now.hour >= 15 and now.minute >= 20:
                if state == "BOUGHT":
                    # 강제 청산
                    current_price = broker.get_current_price(token, APP_KEY, APP_SECRET, URL_REAL, STOCK_CODE)
                    if current_price:
                        profit_rate = (current_price * (1 - SELL_FEE) / (bought_price * (1 + BUY_FEE)) - 1) * 100
                        res = broker.post_sell_order(
                            token, APP_KEY, APP_SECRET, URL_REAL, ACC_NO,
                            STOCK_CODE, holding_qty, current_price, mode="REAL")
                        if res.get('rt_cd') == '0':
                            log_trade("매도", current_price, holding_qty, profit=profit_rate, reason="장마감 강제청산")
                            notify(notifier, "⏹️ <b>장마감 강제청산</b>",
                                   f"가격: {current_price:,.0f}원\n수익률: {profit_rate:+.2f}%")
                            print(f"⏹️ 장마감 강제청산! 수익률: {profit_rate:+.2f}%")
                        else:
                            notify(notifier, "❌ <b>매도 실패</b>", f"{res.get('msg1')}")
                    notify(notifier, "✅ <b>봇 종료</b>", "내일 다시 실행됩니다.")
                elif state == "WAITING":
                    notify(notifier, "⏹️ <b>장 마감</b>", "오늘은 돌파 없음. 매매 없이 종료.")
                    print("⏹️ 장 마감. 오늘은 돌파 없었습니다.")
                    notify(notifier, "✅ <b>봇 종료</b>", "내일 다시 실행됩니다.")
                # state == "SOLD": 당일 매매 완료, 장 마감 알림 없음
                print("프로그램을 종료합니다.")
                return

            # 장중 아닌 경우 대기
            if not is_market_open():
                time.sleep(60)
                continue

            current_price = broker.get_current_price(token, APP_KEY, APP_SECRET, URL_REAL, STOCK_CODE)
            if current_price is None:
                time.sleep(60)
                continue

            # ── 대기 상태: 돌파 감시 ──
            if state == "WAITING":
                print(f"[{now.strftime('%H:%M:%S')}] 현재가: {current_price:,.0f}원 | 목표가: {target_price:,.0f}원 | 대기 중")

                if current_price >= target_price:
                    # 슬리피지 체크: 목표가 대비 너무 올라갔으면 스킵
                    slippage = (current_price - target_price) / target_price
                    if slippage > MAX_SLIPPAGE:
                        print(f"   ⚠️ 슬리피지 초과! {current_price:,.0f}원은 목표가 대비 +{slippage:.2%} (한도: {MAX_SLIPPAGE:.0%})")
                        notify(notifier, "⚠️ <b>돌파 감지했으나 스킵</b>",
                               f"현재가: {current_price:,.0f}원\n목표가: {target_price:,.0f}원\n슬리피지: +{slippage:.2%} > 한도 {MAX_SLIPPAGE:.0%}")
                        state = "SOLD"  # 이미 너무 올라갔으니 당일 매매 포기
                        time.sleep(CHECK_INTERVAL)
                        continue

                    # 매수!
                    cash = broker.get_balance(
                        token, APP_KEY, APP_SECRET, URL_REAL, ACC_NO, STOCK_CODE, mode="REAL")
                    buy_qty = int((cash * POSITION_RATIO) / current_price)

                    if buy_qty <= 0:
                        notify(notifier, "⚠️ <b>잔고 부족</b>", f"현금: {cash:,}원")
                        print(f"⚠️ 잔고 부족 (현금: {cash:,}원)")
                        state = "SOLD"
                        time.sleep(CHECK_INTERVAL)
                        continue

                    print(f"\n🔥 돌파! {current_price:,.0f}원 ≥ {target_price:,.0f}원")
                    res = broker.post_order(
                        token, APP_KEY, APP_SECRET, URL_REAL, ACC_NO,
                        STOCK_CODE, buy_qty, current_price, mode="REAL")

                    if res.get('rt_cd') == '0':
                        # 체결 확인 (20초 대기)
                        bought_price = 0
                        holding_qty = 0
                        for _ in range(10):
                            time.sleep(2)
                            bp = broker.get_stock_balance(
                                token, APP_KEY, APP_SECRET, URL_REAL, ACC_NO,
                                STOCK_CODE, mode="REAL")
                            if bp > 0:
                                bought_price = bp
                                holding_qty = broker.get_holding_quantity(
                                    token, APP_KEY, APP_SECRET, URL_REAL, ACC_NO,
                                    STOCK_CODE, mode="REAL")
                                break

                        if holding_qty > 0:
                            log_trade("매수", bought_price, holding_qty, reason=f"돌파(목표 {target_price:,.0f}원)")
                            notify(notifier, "📈 <b>돌파 매수!</b>",
                                   f"가격: {bought_price:,.0f}원\n수량: {holding_qty}주\n목표가: {target_price:,.0f}원")
                            print(f"✅ 매수 체결! {bought_price:,.0f}원 × {holding_qty}주")
                            state = "BOUGHT"
                        else:
                            # 20초 내 잔고 미확인 → 미체결로 판단, 당일 매매 포기
                            notify(notifier, "⚠️ <b>미체결 감지</b>",
                                   f"20초 내 잔고 미확인\n주문은 장마감 시 자동 취소됩니다\n당일 매매를 포기합니다")
                            print(f"⚠️ 미체결: 20초 내 잔고 확인 실패. 당일 매매 포기.")
                            state = "SOLD"
                    else:
                        notify(notifier, "❌ <b>매수 실패</b>", f"{res.get('msg1')}")
                        print(f"❌ 매수 실패: {res.get('msg1')}")

            # ── 보유 상태: 장마감 청산 대기 ──
            elif state == "BOUGHT":
                profit_rate = (current_price * (1 - SELL_FEE) / (bought_price * (1 + BUY_FEE)) - 1) * 100
                print(f"[{now.strftime('%H:%M:%S')}] 현재가: {current_price:,.0f}원 | 수익률: {profit_rate:+.2f}% | 청산 대기")

                # 15:15 이후 청산
                if now.hour == 15 and now.minute >= 15:
                    res = broker.post_sell_order(
                        token, APP_KEY, APP_SECRET, URL_REAL, ACC_NO,
                        STOCK_CODE, holding_qty, current_price, mode="REAL")

                    if res.get('rt_cd') == '0':
                        log_trade("매도", current_price, holding_qty, profit=profit_rate, reason="장마감 청산")
                        notify(notifier, "📤 <b>장마감 청산!</b>",
                               f"가격: {current_price:,.0f}원\n수익률: {profit_rate:+.2f}%")
                        print(f"✅ 장마감 청산! 수익률: {profit_rate:+.2f}%")
                        state = "SOLD"
                    else:
                        notify(notifier, "❌ <b>매도 실패</b>", f"{res.get('msg1')}")
                        print(f"❌ 매도 실패: {res.get('msg1')}")

            # ── 청산 완료: 장 마감까지 대기 ──
            elif state == "SOLD":
                print(f"[{now.strftime('%H:%M:%S')}] 청산 완료. 장 마감 대기 중...")

            time.sleep(CHECK_INTERVAL)

        except Exception as e:
            error_msg = f"에러: {str(e)}"
            notify(notifier, "❌ <b>에러 발생</b>", error_msg)
            print(f"⚠️ {error_msg}")
            import traceback
            traceback.print_exc()
            time.sleep(60)


if __name__ == "__main__":
    run_bot()
