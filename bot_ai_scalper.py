# bot_ai_scalper.py
# XGBoost 5분봉 AI 단타 전략 (모의투자 전용)
# ──────────────────────────────────────────────────────────
# 전략:
#   60일 5분봉으로 XGBoost 학습 → 5분마다 AI 예측
#   BUY: 상승 확률 ≥ 65% → 매수
#   SELL: 익절(+1.0%) / 손절(-1.0%) / 트레일링스탑 / AI반전
#   하루에 여러 번 진입/청산 가능
# ──────────────────────────────────────────────────────────
import os
import csv
import time
from datetime import datetime
from dotenv import load_dotenv
import pandas as pd

import broker
import data_manager
import model as ai_model
from telegram_notifier import TelegramNotifier

# ── 환경 설정 ──
load_dotenv()
APP_KEY = os.getenv("APP_KEY")                 # 실전 (시세 조회용)
APP_SECRET = os.getenv("APP_SECRET")
MOCK_APP_KEY = os.getenv("MOCK_APP_KEY")       # 모의 (주문용)
MOCK_APP_SECRET = os.getenv("MOCK_APP_SECRET")
MOCK_ACC_NO = os.getenv("MOCK_ACC_NO")
URL_REAL = os.getenv("URL_REAL")
URL_MOCK = os.getenv("URL_MOCK")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

TICKER = "229200.KS"       # KODEX 코스닥150 (일반)
STOCK_CODE = "229200"

# ── 전략 파라미터 (backtester.py에서 검증) ──
BOT_NAME = "AI-Scalper"
LOG_FILE = "trade_log_scalper.csv"
MODEL_FILE = "trading_brain_scalper.json"
BUY_THRESH = 0.65           # AI 확률 65% 이상 매수
SELL_THRESH = 0.40           # 확률 40% 이하 + 수익 중이면 청산
TAKE_PROFIT = 0.006          # +0.6% 익절 (5분봉 단타, 빠른 익절)
STOP_LOSS = -0.005           # -0.5% 손절 (5분봉 단타, 빠른 손절)
TRAIL_ACTIVATE = 0.005       # +0.5% 도달 시 트레일링 활성화
TRAIL_STOP = 0.002           # 고점 대비 0.2% 하락 시 청산
POSITION_RATIO = 0.80        # 현금의 80% 투입
CHECK_INTERVAL = 60          # 1분마다 가격 체크 (손절/트레일링은 빠를수록 좋음)
AI_REFRESH_INTERVAL = 300    # 5분마다 5분봉 데이터 갱신 + AI 예측
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


# ── 메인 봇 ──
def run_bot():
    notifier = TelegramNotifier(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    notify(notifier, "🚀 <b>AI 스캘퍼 봇 시작</b>", "모드: 🟢 모의투자")

    print("=" * 60)
    print(f"🚀 XGBoost 5분봉 AI 단타 봇 시작! (🟢 모의투자)")
    print("=" * 60)

    # ── STEP 1: 토큰 발급 ──
    token_real = broker.get_access_token(APP_KEY, APP_SECRET, URL_REAL)
    token_mock = broker.get_access_token(MOCK_APP_KEY, MOCK_APP_SECRET, URL_MOCK)
    if not token_real or not token_mock:
        notify(notifier, "❌ <b>에러</b>", "토큰 발급 실패")
        print("❌ 토큰 발급 실패. 종료합니다.")
        return

    # ── STEP 2: 60일 5분봉 데이터 + 지표 + XGBoost 학습 ──
    print("\n📥 60일 5분봉 데이터 수집 중...")
    df_base = data_manager.fetch_large_data(TICKER)
    df_train = data_manager.add_indicators(df_base.copy())

    if df_train is None or len(df_train) < 200:
        notify(notifier, "❌ <b>에러</b>", "5분봉 데이터 부족")
        print("❌ 데이터 부족. 종료합니다.")
        return

    features = data_manager.get_feature_columns(df_train)
    print(f"📊 학습 피처 {len(features)}개: {features}")

    xgb_model = ai_model.train_model(df_train, features)
    ai_model.save_model(xgb_model, MODEL_FILE)
    print("✅ AI 학습 완료!")

    # ── STEP 3: 미청산 포지션 확인 ──
    bought_price, holding_qty = load_unclosed_position()
    highest_price = bought_price
    trailing_active = False
    trade_count = 0

    if bought_price > 0:
        print(f"⚡ 미청산 포지션 복구: {holding_qty}주, 매수가 {bought_price:,.0f}원")

    # ── STEP 4: 장 시작 대기 ──
    if not is_market_open():
        print("장 시작을 기다립니다...")
        wait_for_market_open()

    print(f"\n📋 전략 파라미터:")
    print(f"   매수: AI ≥ {BUY_THRESH*100:.0f}% | 매도: AI < {SELL_THRESH*100:.0f}% (수익 중)")
    print(f"   익절: +{TAKE_PROFIT*100:.1f}% | 손절: {STOP_LOSS*100:.1f}%")
    print(f"   트레일링: {TRAIL_ACTIVATE*100:.1f}% 활성 → {TRAIL_STOP*100:.1f}% 하락 시 청산")
    print("=" * 60)

    notify(notifier, "📋 <b>전략 준비 완료</b>",
           f"매수: AI ≥ {BUY_THRESH*100:.0f}%\n"
           f"익절: +{TAKE_PROFIT*100:.1f}% | 손절: {STOP_LOSS*100:.1f}%\n"
           f"트레일링: +{TRAIL_ACTIVATE*100:.1f}% → -{TRAIL_STOP*100:.1f}%")

    # ── STEP 5: 메인 루프 ──
    # 가격 체크: 1분마다 (손절/트레일링은 빠를수록 좋음)
    # AI 예측: 5분마다 (5분봉 데이터 갱신 주기에 맞춤)
    print(f"\n👀 모니터링 시작 (가격: 1분, AI: 5분 간격)")
    print("-" * 40)

    last_data_refresh = 0  # 데이터 갱신 타이밍 추적
    last_prob = 0.0        # 마지막 AI 예측값 (1분 체크 시 재사용)

    while True:
        try:
            now = datetime.now()

            # 장 마감 체크
            if not is_market_open():
                if bought_price > 0:
                    # 잔여 포지션 강제 청산
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

                notify(notifier, "✅ <b>봇 종료</b>", f"오늘 거래: {trade_count}회\n내일 다시 실행됩니다.")
                print(f"\n⏹️ 장 마감. 오늘 총 {trade_count}회 거래. 종료합니다.")
                return

            # ── 현재가 조회 (매 1분) ──
            current_price = broker.get_current_price(token_real, APP_KEY, APP_SECRET, URL_REAL, STOCK_CODE)
            if current_price is None:
                time.sleep(60)
                continue

            # ── 5분봉 데이터 갱신 + AI 예측 (5분마다) ──
            current_time = time.time()
            if current_time - last_data_refresh > AI_REFRESH_INTERVAL:
                df_base = data_manager.refresh_data(df_base, TICKER)
                df_live = data_manager.add_indicators(df_base.copy())
                if df_live is not None and len(df_live) > 0:
                    latest = df_live.iloc[-1]
                    _, last_prob = ai_model.predict_signal(xgb_model, latest, features, BUY_THRESH)
                last_data_refresh = current_time

            prob = last_prob
            signal = 'BUY' if prob >= BUY_THRESH else 'HOLD'

            # ── 미보유: 매수 판단 ──
            if bought_price == 0:
                print(f"[{now.strftime('%H:%M:%S')}] 현재가: {current_price:,.0f}원 | AI: {prob:.1%} | {'🔥 매수!' if signal == 'BUY' else '대기'}")

                if signal == 'BUY':
                    cash = broker.get_balance(
                        token_mock, MOCK_APP_KEY, MOCK_APP_SECRET, URL_MOCK, MOCK_ACC_NO, STOCK_CODE, mode="MOCK")
                    buy_qty = int((cash * POSITION_RATIO) / current_price)

                    if buy_qty <= 0:
                        print(f"⚠️ 잔고 부족 (현금: {cash:,}원)")
                        time.sleep(CHECK_INTERVAL)
                        continue

                    res = broker.post_order(
                        token_mock, MOCK_APP_KEY, MOCK_APP_SECRET, URL_MOCK, MOCK_ACC_NO,
                        STOCK_CODE, buy_qty, current_price, mode="MOCK")

                    if res.get('rt_cd') == '0':
                        # 체결 확인
                        for _ in range(10):
                            time.sleep(2)
                            bp = broker.get_stock_balance(
                                token_mock, MOCK_APP_KEY, MOCK_APP_SECRET, URL_MOCK, MOCK_ACC_NO,
                                STOCK_CODE, mode="MOCK")
                            if bp > 0:
                                bought_price = bp
                                qty = broker.get_holding_quantity(
                                    token_mock, MOCK_APP_KEY, MOCK_APP_SECRET, URL_MOCK, MOCK_ACC_NO,
                                    STOCK_CODE, mode="MOCK")
                                holding_qty = qty if qty is not None and qty > 0 else buy_qty
                                break
                        else:
                            bought_price = current_price
                            holding_qty = buy_qty

                        highest_price = bought_price
                        trailing_active = False
                        log_trade("매수", bought_price, holding_qty, reason=f"AI신호({prob:.1%})")
                        notify(notifier, "📈 <b>매수 체결!</b>",
                               f"가격: {bought_price:,.0f}원\n수량: {holding_qty}주\nAI 확률: {prob:.1%}")
                        print(f"✅ 매수 체결! {bought_price:,.0f}원 × {holding_qty}주 (AI: {prob:.1%})")
                    else:
                        print(f"❌ 매수 실패: {res.get('msg1')}")

            # ── 보유 중: 매도 판단 ──
            else:
                profit_rate = (current_price - bought_price) / bought_price
                pnl_pct = (current_price * (1 - SELL_FEE) / (bought_price * (1 + BUY_FEE)) - 1) * 100  # 수수료 반영 수익률

                # 고점 갱신 + 트레일링 활성화
                if current_price > highest_price:
                    highest_price = current_price
                if not trailing_active and profit_rate >= TRAIL_ACTIVATE:
                    trailing_active = True
                    print(f"   🔔 트레일링 스탑 활성화! (고점: {highest_price:,.0f}원)")

                # 매도 조건 판단
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
                    sell_reason = f"AI반전({prob:.1%}, 수익 {profit_rate:.2%})"

                trail_info = f" [T:{highest_price:,.0f}]" if trailing_active else ""
                print(f"[{now.strftime('%H:%M:%S')}] 현재가: {current_price:,.0f}원 | 수익: {pnl_pct:+.2f}% | AI: {prob:.1%}{trail_info}")

                # 매도 실행
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
                        trade_count += 1
                        # 포지션 초기화 (재진입 가능)
                        bought_price = 0
                        holding_qty = 0
                        highest_price = 0
                        trailing_active = False
                    else:
                        print(f"❌ 매도 실패: {res.get('msg1')}")

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
