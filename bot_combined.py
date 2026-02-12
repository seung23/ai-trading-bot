# bot_combined.py
# 복합 전략: 변동성 돌파 진입 + AI 필터/청산 (모의투자 전용)
# ──────────────────────────────────────────────────────────
# 전략:
#   진입: 변동성 돌파 AND AI 확률 ≥ 60% (이중 필터)
#   청산: AI 기반 (익절/손절/트레일링/AI반전) — 시간 기반 아님
#   하루 1회 진입 (변동성 돌파는 1일 1회 이벤트)
# ──────────────────────────────────────────────────────────
import os
import csv
import time
from datetime import datetime, date
from dotenv import load_dotenv
import yfinance as yf
import pandas as pd

import broker
import data_manager
import model as ai_model
from telegram_notifier import TelegramNotifier

# ── 환경 설정 ──
load_dotenv()
APP_KEY = os.getenv("APP_KEY")
APP_SECRET = os.getenv("APP_SECRET")
MOCK_APP_KEY = os.getenv("MOCK_APP_KEY")
MOCK_APP_SECRET = os.getenv("MOCK_APP_SECRET")
MOCK_ACC_NO = os.getenv("MOCK_ACC_NO")
URL_REAL = os.getenv("URL_REAL")
URL_MOCK = os.getenv("URL_MOCK")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

TICKER = "229200.KS"       # KODEX 코스닥150 (일반)
STOCK_CODE = "229200"

# ── 전략 파라미터 ──
BOT_NAME = "Combined"
LOG_FILE = "trade_log_combined.csv"
MODEL_FILE = "trading_brain_combined.json"

# 변동성 돌파
K = 0.3                    # 지수 ETF는 변동폭이 작아 K를 낮춰 돌파 기회 확보

# AI 파라미터 (변동성으로 1차 필터링되므로 BUY_THRESH 낮춤)
BUY_THRESH = 0.60
SELL_THRESH = 0.40
TAKE_PROFIT = 0.01           # +1.0% (일반 ETF 1배 기준)
STOP_LOSS = -0.01            # -1.0% (일반 ETF 1배 기준)
TRAIL_ACTIVATE = 0.007       # +0.7%
TRAIL_STOP = 0.003           # 0.3%
POSITION_RATIO = 0.80
CHECK_INTERVAL = 300
# ETF 수수료 (모의투자: 0.014%, 거래세 면제)
BUY_FEE = 0.00014           # 매수 수수료 0.014%
SELL_FEE = 0.00014          # 매도 수수료 0.014%


# ── 유틸리티 ──
def log_trade(side, price, quantity, profit=0, reason=""):
    file_exists = os.path.isfile(LOG_FILE)
    with open(LOG_FILE, mode='a', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(['시간', '구분', '가격', '수량', '순수익률', '사유', '참고사항'])
        time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        writer.writerow([time_str, side, price, quantity, f"{profit:.2f}%", reason, "[모의] ETF 매수 0.0148% + 매도 0.0148%"])


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


def notify(notifier, title, body):
    msg = f"[{BOT_NAME}] {title}\n\n{body}\n시간: {datetime.now().strftime('%H:%M:%S')}"
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
    df = yf.download(TICKER, period='5d', interval='1d')
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    today = date.today()
    df_past = df[df.index.date < today]
    if len(df_past) == 0:
        return None, None, None
    yesterday = df_past.iloc[-1]
    return float(yesterday['High']), float(yesterday['Low']), float(yesterday['High'] - yesterday['Low'])


def get_today_open_yf():
    """(fallback) 당일 시가를 yfinance 5분봉 첫 캔들에서 가져옵니다."""
    df = yf.download(TICKER, period='1d', interval='5m')
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if df is None or len(df) == 0:
        return None
    return float(df.iloc[0]['Open'])


# ── 메인 봇 ──
def run_bot():
    notifier = TelegramNotifier(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    notify(notifier, "🚀 <b>복합 전략 봇 시작</b>", "모드: 🟢 모의투자\n변동성 돌파 + AI 필터/청산")

    print("=" * 60)
    print(f"🚀 복합 전략 봇 시작! (변동성 돌파 + AI) (🟢 모의투자)")
    print("=" * 60)

    # ── STEP 1: 토큰 발급 ──
    token_real = broker.get_access_token(APP_KEY, APP_SECRET, URL_REAL)
    token_mock = broker.get_access_token(MOCK_APP_KEY, MOCK_APP_SECRET, URL_MOCK)
    if not token_real or not token_mock:
        notify(notifier, "❌ <b>에러</b>", "토큰 발급 실패")
        print("❌ 토큰 발급 실패. 종료합니다.")
        return

    # ── STEP 2: 전일 변동폭 ──
    yesterday_high, yesterday_low, yesterday_range = get_yesterday_range()
    if yesterday_range is None:
        notify(notifier, "❌ <b>에러</b>", "전일 데이터 조회 실패")
        return

    print(f"📊 전일 고가: {yesterday_high:,.0f}원, 저가: {yesterday_low:,.0f}원, 변동폭: {yesterday_range:,.0f}원")

    # ── STEP 3: 60일 5분봉 + XGBoost 학습 ──
    print("\n📥 60일 5분봉 데이터 수집 중...")
    df_base = data_manager.fetch_large_data(TICKER)
    df_train = data_manager.add_indicators(df_base.copy())

    if df_train is None or len(df_train) < 200:
        notify(notifier, "❌ <b>에러</b>", "5분봉 데이터 부족")
        print("❌ 데이터 부족. 종료합니다.")
        return

    features = data_manager.get_feature_columns(df_train)
    print(f"📊 학습 피처 {len(features)}개")

    xgb_model = ai_model.train_model(df_train, features)
    ai_model.save_model(xgb_model, MODEL_FILE)
    print("✅ AI 학습 완료!")

    # ── STEP 4: 미청산 포지션 확인 ──
    bought_price, holding_qty = load_unclosed_position()
    highest_price = bought_price
    trailing_active = False

    if bought_price > 0:
        print(f"⚡ 미청산 포지션 복구: {holding_qty}주, 매수가 {bought_price:,.0f}원")
        state = "BOUGHT"
    else:
        state = "WAITING"

    # ── STEP 5: 장 시작 대기 + 시가/목표가 ──
    if state == "WAITING":
        if not is_market_open():
            print("장 시작을 기다립니다...")
            wait_for_market_open()

        time.sleep(3)  # 장 시작 직후 API 안정화 대기
        today_open = broker.get_today_open(token_real, APP_KEY, APP_SECRET, URL_REAL, STOCK_CODE)
        if today_open is None or today_open == 0:
            print("⚠️ KIS API 시가 조회 실패, yfinance로 대체")
            today_open = get_today_open_yf()
        if today_open is None:
            notify(notifier, "❌ <b>에러</b>", "시가 조회 실패")
            return

        target_price = today_open + yesterday_range * K
        print(f"\n📋 오늘의 전략:")
        print(f"   시가: {today_open:,.0f}원")
        print(f"   돌파 목표가: {target_price:,.0f}원 (시가 + {yesterday_range:,.0f} × {K})")
        print(f"   AI 매수 기준: ≥ {BUY_THRESH*100:.0f}%")
        print(f"   청산: AI 기반 (익절 +{TAKE_PROFIT*100:.1f}% / 손절 {STOP_LOSS*100:.1f}% / 트레일링)")
        print("=" * 60)

        notify(notifier, "📋 <b>오늘의 전략</b>",
               f"시가: {today_open:,.0f}원\n"
               f"돌파 목표가: {target_price:,.0f}원\n"
               f"AI 매수 기준: ≥ {BUY_THRESH*100:.0f}%\n"
               f"청산: AI 기반 (시간X)")
    else:
        target_price = 0

    # ── STEP 6: 메인 루프 ──
    print(f"\n👀 모니터링 시작 (5분 간격)")
    print("-" * 40)

    last_data_refresh = 0
    volatility_triggered = False  # 돌파 여부 추적

    while True:
        try:
            now = datetime.now()

            # 장 마감
            if not is_market_open():
                if state == "BOUGHT":
                    current_price = broker.get_current_price(token_real, APP_KEY, APP_SECRET, URL_REAL, STOCK_CODE)
                    if current_price:
                        profit_rate = (current_price * (1 - SELL_FEE) / (bought_price * (1 + BUY_FEE)) - 1) * 100
                        res = broker.post_sell_order(
                            token_mock, MOCK_APP_KEY, MOCK_APP_SECRET, URL_MOCK, MOCK_ACC_NO,
                            STOCK_CODE, holding_qty, current_price, mode="MOCK")
                        if res.get('rt_cd') == '0':
                            log_trade("매도", current_price, holding_qty, profit=profit_rate, reason="장마감 강제청산")
                            notify(notifier, "⏹️ <b>장마감 강제청산</b>",
                                   f"가격: {current_price:,.0f}원\n수익률: {profit_rate:+.2f}%")
                            print(f"⏹️ 장마감 강제청산! 수익률: {profit_rate:+.2f}%")
                        else:
                            notify(notifier, "❌ <b>매도 실패</b>", f"{res.get('msg1')}")
                else:
                    if volatility_triggered:
                        notify(notifier, "⏹️ <b>장 마감</b>", "돌파 발생했으나 AI 미충족으로 매매 없음")
                    else:
                        notify(notifier, "⏹️ <b>장 마감</b>", "오늘은 돌파 없음. 매매 없이 종료.")

                notify(notifier, "✅ <b>봇 종료</b>", "내일 다시 실행됩니다.")
                print("프로그램을 종료합니다.")
                return

            current_price = broker.get_current_price(token_real, APP_KEY, APP_SECRET, URL_REAL, STOCK_CODE)
            if current_price is None:
                time.sleep(60)
                continue

            # ── 5분봉 데이터 갱신 + AI 예측 ──
            current_time = time.time()
            if current_time - last_data_refresh > 290:
                df_base = data_manager.refresh_data(df_base, TICKER)
                last_data_refresh = current_time

            df_live = data_manager.add_indicators(df_base.copy())
            prob = 0.0
            if df_live is not None and len(df_live) > 0:
                latest = df_live.iloc[-1]
                _, prob = ai_model.predict_signal(xgb_model, latest, features, BUY_THRESH)

            # ── 대기: 이중 조건 (돌파 + AI) ──
            if state == "WAITING":
                is_breakout = current_price >= target_price
                is_ai_ok = prob >= BUY_THRESH

                if is_breakout:
                    volatility_triggered = True

                status = ""
                if is_breakout and is_ai_ok:
                    status = "🔥 이중 조건 충족!"
                elif is_breakout:
                    status = f"⚡ 돌파 O, AI X ({prob:.0%} < {BUY_THRESH*100:.0f}%)"
                else:
                    status = "대기"

                print(f"[{now.strftime('%H:%M:%S')}] 현재가: {current_price:,.0f}원 | 목표: {target_price:,.0f}원 | AI: {prob:.0%} | {status}")

                if is_breakout and is_ai_ok:
                    # 매수!
                    cash = broker.get_balance(
                        token_mock, MOCK_APP_KEY, MOCK_APP_SECRET, URL_MOCK, MOCK_ACC_NO, STOCK_CODE, mode="MOCK")
                    buy_qty = int((cash * POSITION_RATIO) / current_price)

                    if buy_qty <= 0:
                        print(f"⚠️ 잔고 부족 (현금: {cash:,}원)")
                        state = "SOLD"
                        time.sleep(CHECK_INTERVAL)
                        continue

                    res = broker.post_order(
                        token_mock, MOCK_APP_KEY, MOCK_APP_SECRET, URL_MOCK, MOCK_ACC_NO,
                        STOCK_CODE, buy_qty, current_price, mode="MOCK")

                    if res.get('rt_cd') == '0':
                        for _ in range(10):
                            time.sleep(2)
                            bp = broker.get_stock_balance(
                                token_mock, MOCK_APP_KEY, MOCK_APP_SECRET, URL_MOCK, MOCK_ACC_NO,
                                STOCK_CODE, mode="MOCK")
                            if bp > 0:
                                bought_price = bp
                                holding_qty = broker.get_holding_quantity(
                                    token_mock, MOCK_APP_KEY, MOCK_APP_SECRET, URL_MOCK, MOCK_ACC_NO,
                                    STOCK_CODE, mode="MOCK")
                                break
                        else:
                            bought_price = current_price
                            holding_qty = buy_qty

                        highest_price = bought_price
                        trailing_active = False
                        log_trade("매수", bought_price, holding_qty, reason=f"돌파+AI({prob:.0%})")
                        notify(notifier, "📈 <b>복합 매수!</b>",
                               f"가격: {bought_price:,.0f}원\n수량: {holding_qty}주\n"
                               f"돌파: {current_price:,.0f} ≥ {target_price:,.0f}\nAI: {prob:.0%}")
                        print(f"✅ 매수! 돌파+AI({prob:.0%}) | {bought_price:,.0f}원 × {holding_qty}주")
                        state = "BOUGHT"
                    else:
                        print(f"❌ 매수 실패: {res.get('msg1')}")

            # ── 보유 중: AI 기반 청산 ──
            elif state == "BOUGHT":
                profit_rate = (current_price - bought_price) / bought_price
                pnl_pct = (current_price * (1 - SELL_FEE) / (bought_price * (1 + BUY_FEE)) - 1) * 100  # 수수료 반영 수익률

                if current_price > highest_price:
                    highest_price = current_price
                if not trailing_active and profit_rate >= TRAIL_ACTIVATE:
                    trailing_active = True
                    print(f"   🔔 트레일링 스탑 활성화! (고점: {highest_price:,.0f}원)")

                sell_reason = None
                if profit_rate >= TAKE_PROFIT:
                    sell_reason = f"익절({profit_rate:.2%})"
                elif profit_rate <= STOP_LOSS:
                    sell_reason = f"손절({profit_rate:.2%})"
                elif trailing_active:
                    drop = (current_price - highest_price) / highest_price
                    if drop <= -TRAIL_STOP:
                        sell_reason = f"트레일링스탑(고점 {highest_price:,.0f}→{current_price:,.0f})"
                elif prob < SELL_THRESH and profit_rate > 0:
                    sell_reason = f"AI반전({prob:.0%}, 수익 {profit_rate:.2%})"

                trail_info = f" [T:{highest_price:,.0f}]" if trailing_active else ""
                print(f"[{now.strftime('%H:%M:%S')}] 현재가: {current_price:,.0f}원 | 수익: {pnl_pct:+.2f}% | AI: {prob:.0%}{trail_info}")

                if sell_reason:
                    res = broker.post_sell_order(
                        token_mock, MOCK_APP_KEY, MOCK_APP_SECRET, URL_MOCK, MOCK_ACC_NO,
                        STOCK_CODE, holding_qty, current_price, mode="MOCK")

                    if res.get('rt_cd') == '0':
                        log_trade("매도", current_price, holding_qty, profit=pnl_pct, reason=sell_reason)
                        emoji = "🎉" if profit_rate > 0 else "⚠️"
                        notify(notifier, f"{emoji} <b>매도 체결!</b>",
                               f"가격: {current_price:,.0f}원\n수익률: {pnl_pct:+.2f}%\n사유: {sell_reason}")
                        print(f"✅ 매도! {sell_reason} | 수익률: {pnl_pct:+.2f}%")
                        # 당일 추가 진입 없음 (변동성 돌파는 1일 1회)
                        state = "SOLD"
                        bought_price = 0
                        holding_qty = 0
                    else:
                        print(f"❌ 매도 실패: {res.get('msg1')}")

            # ── 청산 완료: 장 마감 대기 ──
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
