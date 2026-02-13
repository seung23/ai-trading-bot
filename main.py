# main.py
# XGBoost 기반 일봉 AI 전략 (KODEX 코스닥150)
# ──────────────────────────────────────────────────────────
# 전략 흐름:
#
#   1) 실행 시 1년치 일봉 수집 → XGBoost 학습
#   2) 어제 일봉 기준으로 AI 판단 (1회)
#   3-A) 보유 없음 + 확률 < 60% → "오늘은 매수 없음" → 종료
#   3-B) 보유 없음 + 확률 ≥ 60% → 9시 장 시작 대기 → 시가 매수
#        → 이후 30분마다 익절/손절 감시
#        → 매도 완료 → 종료
#   3-C) 기존 보유 있음 → 30분마다 익절/손절 감시
#        → 매도 완료 → 종료
# ──────────────────────────────────────────────────────────
import os
import csv
import time
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

import broker
import data_manager
import model as ai_model
from telegram_notifier import TelegramNotifier

# ── 환경 설정 ──
load_dotenv()
APP_KEY = os.getenv("APP_KEY")
APP_SECRET = os.getenv("APP_SECRET")
ACC_NO = os.getenv("ACC_NO")
URL_MOCK = os.getenv("URL_MOCK")
URL_REAL = os.getenv("URL_REAL")

# Telegram 알림 설정 (선택사항)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

TICKER = "229200.KS"       # KODEX 코스닥150 (일반)
STOCK_CODE = "229200"

# ── 매매 모드 설정 ──
# "REAL" = 실전 매매 (tr_id: TTTC*, 서버: URL_REAL)
# "MOCK" = 모의 투자 (tr_id: VTTC*, 서버: URL_MOCK)
TRADING_MODE = "REAL"
TRADING_URL = URL_REAL if TRADING_MODE == "REAL" else URL_MOCK

# ── 전략 파라미터 (백테스트 검증 완료) ──
BUY_THRESHOLD = 0.60        # AI 상승 확률이 이 이상이면 매수
TAKE_PROFIT = 0.01          # +1.0% 익절 (일반 ETF 1배 기준)
STOP_LOSS = -0.01           # -1.0% 손절 (일반 ETF 1배 기준)
POSITION_RATIO = 0.70       # 현금의 70% 투입 (일반 ETF는 변동성 낮아 비중 확대)
CHECK_INTERVAL = 1800       # 30분마다 체크 (초)
# ETF 수수료 (실전투자: 0.004%, 수수료 우대 계좌, 거래세 면제)
BUY_FEE = 0.00004          # 매수 수수료 0.004%
SELL_FEE = 0.00004         # 매도 수수료 0.004%

# ── 시간대 설정 (한국 시간 KST) ──
KST = timezone(timedelta(hours=9))


# ── 로그 함수 ──
def log_trade(side, price, quantity, profit=0, reason=""):
    """매매 내역을 trade_log.csv에 기록합니다."""
    file_name = 'trade_log.csv'
    mode_str = "실전" if TRADING_MODE == "REAL" else "모의"
    fee_info = f"[{mode_str}] ETF 매수 0.004% + 매도 0.004%"
    file_exists = os.path.isfile(file_name)

    with open(file_name, mode='a', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(['시간', '구분', '가격', '수량', '순수익률', '사유', '참고사항'])
        time_str = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
        writer.writerow([time_str, side, price, quantity, f"{profit:.2f}%", reason, fee_info])


def wait_for_market_open():
    """장 시작(09:00)까지 대기합니다."""
    while True:
        now = datetime.now(KST)
        if now.hour >= 9:
            return
        remaining = (9 - now.hour - 1) * 3600 + (60 - now.minute) * 60
        if remaining > 60:
            print(f"⏰ 장 시작 대기 중... ({remaining // 60}분 남음)")
            time.sleep(60)
        else:
            time.sleep(10)


def is_market_open():
    """현재 장 운영 시간(09:00~15:20)인지 확인합니다."""
    now = datetime.now(KST)
    return (9 <= now.hour < 15) or (now.hour == 15 and now.minute < 20)


# ── 메인 봇 ──
def run_bot():
    mode_label = "🔴 실전 매매" if TRADING_MODE == "REAL" else "🟢 모의 투자"

    # Telegram 알림 초기화
    notifier = TelegramNotifier(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    notifier.notify_start(mode_label)

    print("=" * 60)
    print(f"🚀 XGBoost 일봉 AI 전략 봇 시작! ({mode_label})")
    print("=" * 60)

    # ── STEP 1: 증권사 토큰 발급 ──
    token = broker.get_access_token(APP_KEY, APP_SECRET, TRADING_URL)
    if not token:
        notifier.notify_error("토큰 발급 실패")
        print("❌ 토큰 발급 실패. 프로그램을 종료합니다.")
        return

    # ── STEP 2: 현재 계좌 상태 확인 ──
    bought_price = broker.get_stock_balance(
        token, APP_KEY, APP_SECRET, TRADING_URL, ACC_NO, STOCK_CODE, mode=TRADING_MODE)
    holding_qty = broker.get_holding_quantity(
        token, APP_KEY, APP_SECRET, TRADING_URL, ACC_NO, STOCK_CODE, mode=TRADING_MODE)

    # ── STEP 3: 1년치 일봉 데이터 수집 + 지표 계산 + XGBoost 학습 ──
    df = data_manager.fetch_daily_data(TICKER)
    df = data_manager.add_daily_indicators(df)
    if df is None or len(df) < 50:
        notifier.notify_error("데이터 부족 (50일 미만)")
        print("❌ 데이터 부족. 종료합니다.")
        return

    features = data_manager.get_daily_feature_columns(df)
    print(f"📊 학습 피처 {len(features)}개: {features}")

    xgb_model = ai_model.train_model(df, features)
    ai_model.save_model(xgb_model)
    print("✅ AI 학습 완료! (모델 저장: trading_brain.json)")

    # ── STEP 4: AI 판단 (어제 일봉 기준, 1회만) ──
    latest = df.iloc[-1]
    signal, prob = ai_model.predict_signal(xgb_model, latest, features, BUY_THRESHOLD)

    # Telegram 알림: AI 예측 결과
    notifier.notify_ai_prediction(prob, signal, BUY_THRESHOLD, mode_label)

    print(f"\n📋 오늘의 AI 판단:")
    print(f"   모드: {mode_label}")
    print(f"   AI 상승 확률: {prob:.1%} → {signal}")
    print(f"   매수 기준: ≥ {BUY_THRESHOLD*100:.0f}%")
    print(f"   익절: +{TAKE_PROFIT*100:.0f}% | 손절: {STOP_LOSS*100:.0f}%")

    if bought_price > 0:
        print(f"   ⚡ 기존 보유: {holding_qty}주, 매수단가 {bought_price:,.0f}원")
    print("=" * 60)

    # ══════════════════════════════════════════════════════════
    # STEP 5: 의사 결정
    # ══════════════════════════════════════════════════════════

    # ── 5-A) 보유 없음 + 매수 신호 없음 → 종료 ──
    if bought_price == 0 and signal != 'BUY':
        notifier.notify_no_buy(prob, BUY_THRESHOLD)
        print(f"\n📭 오늘은 매수 조건 미충족 (AI: {prob:.1%} < {BUY_THRESHOLD*100:.0f}%)")
        print("프로그램을 종료합니다. 내일 다시 실행하세요.")
        notifier.notify_finish()
        return

    # ── 5-B) 보유 없음 + 매수 신호 → 장 시작 대기 후 매수 ──
    if bought_price == 0 and signal == 'BUY':
        print(f"\n🔥 AI 매수 신호 감지! (확률: {prob:.1%})")

        # 장 시작 대기
        if not is_market_open():
            print("장 시작을 기다립니다...")
            wait_for_market_open()

        # 시가 조회 (KIS API, 재시도 포함)
        buy_price = None
        max_retries = 6  # 최대 30초 (5초 × 6회)
        for attempt in range(max_retries):
            time.sleep(5)
            buy_price = broker.get_today_open(token, APP_KEY, APP_SECRET, URL_REAL, STOCK_CODE)
            if buy_price is not None and buy_price > 0:
                print(f"✅ 시가 조회 성공: {buy_price:,.0f}원 (시도 {attempt+1}회)")
                break
            print(f"⏳ 시가 조회 재시도 중... ({attempt+1}/{max_retries})")
        else:
            # 재시도 실패, 현재가로 fallback
            print("⚠️ 시가 조회 실패, 현재가로 대체")
            buy_price = broker.get_current_price(token, APP_KEY, APP_SECRET, URL_REAL, STOCK_CODE)

        if buy_price is None:
            notifier.notify_error("시가/현재가 조회 실패")
            print("❌ 시가/현재가 조회 실패. 종료합니다.")
            notifier.notify_finish()
            return

        cash = broker.get_balance(
            token, APP_KEY, APP_SECRET, TRADING_URL, ACC_NO, STOCK_CODE, mode=TRADING_MODE)
        buy_qty = int((cash * POSITION_RATIO) / buy_price)

        if buy_qty <= 0:
            notifier.notify_error(f"잔고 부족 (현금: {cash:,}원)")
            print(f"⚠️ 잔고 부족 (현금: {cash:,}원). 종료합니다.")
            notifier.notify_finish()
            return

        print(f"📈 매수 실행! {buy_price:,.0f}원 × {buy_qty}주")
        res = broker.post_order(
            token, APP_KEY, APP_SECRET, TRADING_URL, ACC_NO,
            STOCK_CODE, buy_qty, buy_price, mode=TRADING_MODE)

        if res.get('rt_cd') != '0':
            notifier.notify_error(f"매수 주문 실패: {res.get('msg1')}")
            print(f"❌ 주문 실패: {res.get('msg1')}. 종료합니다.")
            notifier.notify_finish()
            return

        print("✅ 주문 성공! 체결 확인 중...")
        for _ in range(10):
            time.sleep(2)
            bought_price = broker.get_stock_balance(
                token, APP_KEY, APP_SECRET, TRADING_URL, ACC_NO, STOCK_CODE, mode=TRADING_MODE)
            if bought_price > 0:
                holding_qty = broker.get_holding_quantity(
                    token, APP_KEY, APP_SECRET, TRADING_URL, ACC_NO, STOCK_CODE, mode=TRADING_MODE)
                log_trade("매수", bought_price, holding_qty, reason=f"AI신호({prob:.0%})")
                notifier.notify_buy(bought_price, holding_qty, prob)
                print(f"✅ 체결 완료! 매수단가: {bought_price:,.0f}원, {holding_qty}주")
                break
        else:
            notifier.notify_error("매수 체결 확인 실패")
            print("⚠️ 체결 확인 실패. 계좌를 직접 확인하세요. 종료합니다.")
            notifier.notify_finish()
            return

    # ══════════════════════════════════════════════════════════
    # STEP 6: 보유 중 → 30분마다 익절/손절 감시
    # ══════════════════════════════════════════════════════════
    print(f"\n👀 익절/손절 감시 시작 (30분 간격)")
    print(f"   익절: +{TAKE_PROFIT*100:.0f}% | 손절: {STOP_LOSS*100:.0f}%")
    print("-" * 40)

    while True:
        try:
            if not is_market_open():
                notifier.notify_market_closed(holding_qty, bought_price)
                print(f"\n⏹️ 장 마감. 보유 유지한 채로 종료합니다.")
                print(f"   보유: {holding_qty}주, 매수단가 {bought_price:,.0f}원")
                print("내일 다시 실행하세요.")
                notifier.notify_finish()
                return

            current_price = broker.get_current_price(token, APP_KEY, APP_SECRET, URL_REAL, STOCK_CODE)
            if current_price is None:
                time.sleep(60)
                continue

            profit_rate = (current_price - bought_price) / bought_price
            pnl_pct = (current_price * (1 - SELL_FEE) / (bought_price * (1 + BUY_FEE)) - 1) * 100  # 수수료 반영 수익률
            now = datetime.now(KST)
            print(f"[{now.strftime('%H:%M:%S')}] 현재가: {current_price:,.0f}원 | 수익률: {pnl_pct:+.2f}%")

            # Telegram 알림: 30분마다 보유 현황 (수수료 반영 수익률)
            notifier.notify_monitoring(current_price, bought_price, holding_qty, pnl_pct)

            # 매도 조건 확인
            sell_reason = None
            if profit_rate >= TAKE_PROFIT:
                sell_reason = f"익절({profit_rate:.2%})"
            elif profit_rate <= STOP_LOSS:
                sell_reason = f"손절({profit_rate:.2%})"

            # 매도 실행
            if sell_reason:
                sell_qty = holding_qty if holding_qty > 0 else 1
                print(f"\n📤 매도! 사유: {sell_reason} → {sell_qty}주")
                res = broker.post_sell_order(
                    token, APP_KEY, APP_SECRET, TRADING_URL, ACC_NO,
                    STOCK_CODE, sell_qty, current_price, mode=TRADING_MODE)

                if res.get('rt_cd') == '0':
                    log_trade("매도", current_price, sell_qty, profit=pnl_pct, reason=sell_reason)
                    notifier.notify_sell(current_price, sell_qty, pnl_pct, sell_reason)
                    print(f"✅ 매도 완료! 수익률: {pnl_pct:+.2f}%")
                    print("프로그램을 종료합니다.")
                    notifier.notify_finish()
                    return
                else:
                    notifier.notify_error(f"매도 실패: {res.get('msg1')}")
                    print(f"❌ 매도 실패: {res.get('msg1')}")

            time.sleep(CHECK_INTERVAL)

        except Exception as e:
            error_msg = f"에러 발생: {str(e)}"
            notifier.notify_error(error_msg)
            print(f"⚠️ {error_msg}")
            import traceback
            traceback.print_exc()
            time.sleep(60)


if __name__ == "__main__":
    run_bot()
