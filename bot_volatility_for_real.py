# bot_volatility_for_real.py
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

TICKER = "233740.KS"
STOCK_CODE = "233740"

# ── 전략 파라미터 ──
BOT_NAME = "Volatility-REAL"
LOG_FILE = "trade_log_volatility_real.csv"
K = 0.3                    # 지수 ETF는 변동폭이 작아 K를 낮춰 돌파 기회 확보
MAX_SLIPPAGE = 0.01        # 목표가 대비 1% 이상 올라가 있으면 매수 스킵
POSITION_RATIO = 0.50      # 현금의 50% 투입
CHECK_INTERVAL = 60        # 1분마다 체크 (돌파 감지는 빠를수록 좋음)
# ETF 수수료 (실전투자: 0.014%, 수수료 우대, 거래세 면제)
BUY_FEE = 0.00014         # 매수 수수료 0.014%
SELL_FEE = 0.00014        # 매도 수수료 0.014%


# ── 유틸리티 ──
def log_trade(side, price, quantity, profit=0, reason=""):
    file_exists = os.path.isfile(LOG_FILE)
    with open(LOG_FILE, mode='a', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(['시간', '구분', '가격', '수량', '순수익률', '사유', '참고사항'])
        time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        writer.writerow([time_str, side, price, quantity, f"{profit:.2f}%", reason, "[실전] ETF 매수 0.014% + 매도 0.014%"])


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
    now = datetime.now()
    return (9 <= now.hour < 15) or (now.hour == 15 and now.minute < 20)


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


def get_yesterday_range():
    """전일 고가-저가 변동폭을 구합니다."""
    df = yf.download(TICKER, period='5d', interval='1d')
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # 한국 시간 기준 오늘 (UTC+9)
    kst = timezone(timedelta(hours=9))
    today = datetime.now(kst).date()
    df_past = df[df.index.date < today]

    if len(df_past) == 0:
        print("❌ 전일 데이터를 찾을 수 없습니다.")
        return None, None, None

    yesterday = df_past.iloc[-1]
    return float(yesterday['High']), float(yesterday['Low']), float(yesterday['High'] - yesterday['Low'])


def get_today_open():
    """당일 시가를 yfinance 5분봉 첫 캔들에서 가져옵니다."""
    df = yf.download(TICKER, period='1d', interval='5m')
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

    # ── STEP 1: 토큰 발급 ──
    token = broker.get_access_token(APP_KEY, APP_SECRET, URL_REAL)
    if not token:
        notify(notifier, "❌ <b>에러</b>", "토큰 발급 실패")
        print("❌ 토큰 발급 실패. 종료합니다.")
        return

    # ── STEP 2: 전일 변동폭 계산 ──
    yesterday_high, yesterday_low, yesterday_range = get_yesterday_range()
    if yesterday_range is None:
        notify(notifier, "❌ <b>에러</b>", "전일 데이터 조회 실패")
        return

    print(f"📊 전일 고가: {yesterday_high:,.0f}원, 저가: {yesterday_low:,.0f}원")
    print(f"   변동폭: {yesterday_range:,.0f}원, K={K}")

    # ── STEP 3: 미청산 포지션 확인 ──
    bought_price, holding_qty = load_unclosed_position()
    if bought_price > 0:
        print(f"⚡ 미청산 포지션 복구: {holding_qty}주, 매수가 {bought_price:,.0f}원")
        state = "BOUGHT"
    else:
        state = "WAITING"

    # ── STEP 4: 장 시작 대기 + 시가 캡처 ──
    if state == "WAITING":
        if not is_market_open():
            print("장 시작을 기다립니다...")
            wait_for_market_open()

        # 시가 캡처 (yfinance 5분봉 첫 캔들의 시가 사용 — 언제 실행해도 동일)
        time.sleep(10)  # yfinance 데이터 반영 대기
        today_open = get_today_open()
        if today_open is None:
            # fallback: KIS API 현재가 사용
            print("⚠️ yfinance 시가 조회 실패, KIS 현재가로 대체")
            today_open = broker.get_current_price(token, APP_KEY, APP_SECRET, URL_REAL, STOCK_CODE)
        if today_open is None:
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
               f"변동폭: {yesterday_range:,.0f}원 × K={K}")
    else:
        # 미청산 포지션이 있으면 목표가 불필요 (이미 매수됨)
        target_price = 0
        today_open = 0

    # ── STEP 5: 메인 루프 ──
    print(f"\n👀 모니터링 시작 (5분 간격)")
    print("-" * 40)

    while True:
        try:
            now = datetime.now()

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
                else:
                    notify(notifier, "⏹️ <b>장 마감</b>", "오늘은 돌파 없음. 매매 없이 종료.")
                    print("⏹️ 장 마감. 오늘은 돌파 없었습니다.")

                notify(notifier, "✅ <b>봇 종료</b>", "내일 다시 실행됩니다.")
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
                        # 체결 확인
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
                        else:
                            bought_price = current_price
                            holding_qty = buy_qty

                        log_trade("매수", bought_price, holding_qty, reason=f"돌파(목표 {target_price:,.0f}원)")
                        notify(notifier, "📈 <b>돌파 매수!</b>",
                               f"가격: {bought_price:,.0f}원\n수량: {holding_qty}주\n목표가: {target_price:,.0f}원")
                        print(f"✅ 매수 체결! {bought_price:,.0f}원 × {holding_qty}주")
                        state = "BOUGHT"
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
