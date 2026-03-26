# main.py
# Larry Williams 변동성 돌파 전략 — 업비트 이더리움 (ETH/KRW)
# ──────────────────────────────────────────────────────────
# 전략:
#   목표가 = 당일시가 + (전일고가 - 전일저가) × K
#   현재가 ≥ 목표가 → 매수 (1회/일)
#   다음날 08:55 → 무조건 청산
# 사이클: 09:00 시작 → 다음날 08:55 청산 → 5분 대기 → 09:00 새 사이클
# ──────────────────────────────────────────────────────────
import os
import csv
import time
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

import upbit_broker
from telegram_notifier import TelegramNotifier

# ── 환경 설정 ──
load_dotenv()
UPBIT_ACCESS_KEY = os.getenv("UPBIT_ACCESS_KEY")
UPBIT_SECRET_KEY = os.getenv("UPBIT_SECRET_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

MARKET = "KRW-ETH"         # 업비트 마켓 코드
CURRENCY = "ETH"            # 계좌 조회용 통화

# ── 전략 파라미터 ──
BOT_NAME = "ETH-Volatility"
LOG_FILE = "trade_log_eth.csv"
K_MIN = 0.3                # 추세 명확 시 최소 K (노이즈 비율 ≤ 0.4)
K_MAX = 0.6                # 노이즈 심할 때 최대 K (노이즈 비율 ≥ 0.7)
MAX_SLIPPAGE = 0.01        # 목표가 대비 1% 이상 올라가 있으면 매수 스킵
POSITION_RATIO = 0.01      # 현금의 1% 투입 (테스트용, 정상 확인 후 0.70으로 변경)
CHECK_INTERVAL = 1         # 1초마다 체크
# 업비트 수수료 (0.05%)
BUY_FEE = 0.0005
SELL_FEE = 0.0005
# 사이클 시간 (KST)
CYCLE_START_HOUR = 9       # 09:00 새 사이클 시작
CYCLE_START_MINUTE = 0
SELL_HOUR = 8              # 08:55 청산
SELL_MINUTE = 55
# 트레일링 스탑 (백테스트 최적: 2%)
TRAILING_STOP_PCT = 0.02   # 고점 대비 2% 하락 시 청산

KST = timezone(timedelta(hours=9))


# ── 유틸리티 ──
def log_trade(side, price, quantity, profit=0, reason=""):
    file_exists = os.path.isfile(LOG_FILE)
    with open(LOG_FILE, mode='a', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(['시간', '구분', '가격', '수량', '순수익률', '사유', '참고사항'])
        time_str = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
        writer.writerow([time_str, side, f"{price:.0f}", f"{quantity:.8f}",
                         f"{profit:.2f}%", reason, "업비트 ETH 매수/매도 0.05%"])


def load_unclosed_position():
    """CSV에서 미청산 포지션을 복구합니다."""
    if not os.path.isfile(LOG_FILE):
        return 0, 0
    try:
        import pandas as pd
        df = pd.read_csv(LOG_FILE, encoding='utf-8-sig')
        if len(df) == 0:
            return 0, 0
        last = df.iloc[-1]
        if last['구분'] == '매수':
            return float(last['가격']), float(last['수량'])
    except Exception:
        pass
    return 0, 0


def notify(notifier, title, body):
    msg = f"[{BOT_NAME}] {title}\n\n{body}\n시간: {datetime.now(KST).strftime('%H:%M:%S')}"
    notifier.send_message(msg)


def calculate_dynamic_k(yesterday_open, yesterday_close, yesterday_high, yesterday_low):
    """전일 노이즈 비율로 K를 동적으로 결정합니다."""
    day_range = yesterday_high - yesterday_low
    if day_range == 0:
        return K_MAX

    noise_ratio = 1 - abs(yesterday_open - yesterday_close) / day_range

    if noise_ratio <= 0.4:
        k = K_MIN
    elif noise_ratio >= 0.7:
        k = K_MAX
    else:
        k = K_MIN + (noise_ratio - 0.4) / (0.7 - 0.4) * (K_MAX - K_MIN)

    return round(k, 2)


def wait_until(hour, minute):
    """KST 기준 특정 시각까지 대기합니다."""
    while True:
        now = datetime.now(KST)
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now >= target:
            return
        remaining = (target - now).total_seconds()
        if remaining > 120:
            print(f"   {hour:02d}:{minute:02d} 대기 중... ({int(remaining // 60)}분 남음)")
            time.sleep(60)
        elif remaining > 10:
            time.sleep(10)
        else:
            time.sleep(1)


# ── 메인 봇 ──
def run_bot():
    notifier = TelegramNotifier(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    notify(notifier, "🚀 <b>ETH 변동성 돌파 봇 시작</b>",
           f"마켓: {MARKET}\n모드: 24/7 연속 운영")

    print("=" * 60)
    print(f"🚀 ETH 변동성 돌파 봇 시작! (업비트)")
    print(f"   마켓: {MARKET}")
    print(f"   사이클: 09:00 매수 감시 → 다음날 08:55 청산")
    print("=" * 60)

    # 무한 루프: 매일 사이클 반복
    while True:
        try:
            run_daily_cycle(notifier)
        except Exception as e:
            error_msg = f"사이클 에러: {str(e)}"
            import traceback
            traceback.print_exc()
            notify(notifier, "❌ <b>사이클 에러</b>", error_msg)
            print(f"❌ {error_msg}")
            print("   60초 후 새 사이클을 시작합니다...")
            time.sleep(60)


def run_daily_cycle(notifier):
    """하루 사이클: 09:00 시작 → 다음날 08:55 청산"""

    now = datetime.now(KST)
    print(f"\n{'='*60}")
    print(f"📅 새 사이클 시작: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    # ── STEP 1: 09:00 대기 ──
    if now.hour < CYCLE_START_HOUR or (now.hour == CYCLE_START_HOUR and now.minute < CYCLE_START_MINUTE):
        print(f"   09:00까지 대기합니다...")
        wait_until(CYCLE_START_HOUR, CYCLE_START_MINUTE)

    # ── STEP 2: 전일 OHLC + 동적 K 계산 ──
    ohlc = upbit_broker.get_yesterday_ohlc(MARKET)
    if ohlc is None:
        notify(notifier, "❌ <b>에러</b>", "전일 OHLC 조회 실패")
        print("❌ 전일 OHLC 조회 실패. 5분 후 재시도합니다.")
        time.sleep(300)
        return  # run_bot의 while True가 다시 호출

    yesterday_high = ohlc['high']
    yesterday_low = ohlc['low']
    yesterday_open = ohlc['open']
    yesterday_close = ohlc['close']
    yesterday_range = yesterday_high - yesterday_low

    if yesterday_range == 0:
        notify(notifier, "⚠️ <b>매매 중단</b>",
               f"전일 변동폭이 0원입니다.\n데이터 이상으로 판단하여 오늘 매매를 중단합니다.")
        print("⚠️ 전일 변동폭 0원. 다음 사이클까지 대기합니다.")
        wait_until_next_cycle()
        return

    K = calculate_dynamic_k(yesterday_open, yesterday_close, yesterday_high, yesterday_low)
    noise_ratio = 1 - abs(yesterday_open - yesterday_close) / yesterday_range

    print(f"📊 전일 고가: {yesterday_high:,.0f}원, 저가: {yesterday_low:,.0f}원")
    print(f"   변동폭: {yesterday_range:,.0f}원")
    print(f"   노이즈 비율: {noise_ratio:.2f} → K={K} (범위: {K_MIN}~{K_MAX})")

    # ── STEP 3: 포지션 확인 ──
    actual_qty = upbit_broker.get_holding_quantity(UPBIT_ACCESS_KEY, UPBIT_SECRET_KEY, CURRENCY)
    csv_price, csv_qty = load_unclosed_position()

    if actual_qty is None:
        # API 실패 → CSV 기반 복구
        print(f"⚠️ 잔고 조회 실패 → CSV 기록 기반으로 판단합니다.")
        if csv_qty > 0:
            bought_price = csv_price
            holding_qty = csv_qty
            notify(notifier, "⚠️ <b>포지션 복구 (CSV)</b>",
                   f"잔고 API 조회 실패\nCSV: {holding_qty:.8f} ETH, 매수가 {bought_price:,.0f}원")
            state = "BOUGHT"
        else:
            bought_price, holding_qty = 0, 0
            state = "WAITING"
    elif actual_qty > 0:
        actual_price = upbit_broker.get_avg_buy_price(UPBIT_ACCESS_KEY, UPBIT_SECRET_KEY, CURRENCY)
        bought_price = actual_price if actual_price > 0 else csv_price
        holding_qty = actual_qty
        if bought_price <= 0:
            fallback_price = upbit_broker.get_current_price(MARKET)
            if fallback_price and fallback_price > 0:
                bought_price = fallback_price
                print(f"⚠️ 매수가 조회 실패 → 현재가({bought_price:,.0f}원)로 대체")
            else:
                notify(notifier, "❌ <b>매수가 조회 불가</b>",
                       f"보유 {holding_qty:.8f} ETH이나 매수가를 알 수 없습니다.")
                wait_until_next_cycle()
                return
        notify(notifier, "⚡ <b>포지션 복구</b>",
               f"보유: {holding_qty:.8f} ETH (매수가 {bought_price:,.0f}원)")
        print(f"⚡ 포지션 확인: {holding_qty:.8f} ETH, 매수가 {bought_price:,.0f}원")
        state = "BOUGHT"
    else:
        if csv_qty > 0:
            notify(notifier, "🔍 <b>수동 매도 감지</b>",
                   f"CSV: {csv_qty:.8f} ETH → 실제: 0\n수동 청산된 것으로 판단합니다.")
        bought_price, holding_qty = 0, 0
        state = "WAITING"

    # ── STEP 4: 당일 시가 + 목표가 ──
    if state == "WAITING":
        today_open = upbit_broker.get_today_open(MARKET)
        if today_open is None or today_open == 0:
            # 재시도
            for attempt in range(5):
                time.sleep(5)
                today_open = upbit_broker.get_today_open(MARKET)
                if today_open and today_open > 0:
                    break
                print(f"   시가 조회 재시도 ({attempt+2}/6)...")

        if today_open is None or today_open == 0:
            notify(notifier, "❌ <b>에러</b>", "시가 조회 실패")
            print("❌ 시가 조회 실패. 다음 사이클까지 대기합니다.")
            wait_until_next_cycle()
            return

        target_price = today_open + yesterday_range * K
        print(f"\n📋 오늘의 전략:")
        print(f"   시가: {today_open:,.0f}원")
        print(f"   목표가: {target_price:,.0f}원 (시가 + {yesterday_range:,.0f} × {K})")
        print(f"   청산: 내일 08:55")
        print("=" * 60)

        notify(notifier, "📋 <b>오늘의 목표가</b>",
               f"시가: {today_open:,.0f}원\n"
               f"목표가: {target_price:,.0f}원\n"
               f"변동폭: {yesterday_range:,.0f}원 × K={K}\n"
               f"노이즈: {noise_ratio:.2f}")
    else:
        target_price = 0
        today_open = 0

    # ── STEP 5: 메인 루프 ──
    print(f"\n👀 모니터링 시작")
    print("-" * 40)

    loop_count = 0
    MANUAL_CHECK_INTERVAL = 15
    zero_qty_count = 0
    highest_price = bought_price  # 트레일링 스탑용 고점 추적

    while True:
        try:
            now = datetime.now(KST)
            loop_count += 1
            check_manual = (loop_count % MANUAL_CHECK_INTERVAL == 0)

            # 청산 시각 체크 (08:55)
            if is_sell_time(now) and state == "BOUGHT":
                sell_price = upbit_broker.get_current_price(MARKET)
                if sell_price and sell_price > 0 and holding_qty > 0:
                    res = upbit_broker.post_sell_order(
                        UPBIT_ACCESS_KEY, UPBIT_SECRET_KEY, MARKET, volume=holding_qty)

                    if "uuid" in res:
                        profit_rate = (sell_price * (1 - SELL_FEE) / (bought_price * (1 + BUY_FEE)) - 1) * 100
                        log_trade("매도", sell_price, holding_qty, profit=profit_rate, reason="사이클 청산")
                        notify(notifier, "📤 <b>사이클 청산!</b>",
                               f"가격: {sell_price:,.0f}원\n수량: {holding_qty:.8f} ETH\n수익률: {profit_rate:+.2f}%")
                        print(f"✅ 사이클 청산! 수익률: {profit_rate:+.2f}%")
                        state = "SOLD"
                    else:
                        error_msg = res.get("error", {}).get("message", str(res))
                        notify(notifier, "⚠️ <b>매도 실패 (재시도 중)</b>", error_msg)
                        print(f"⚠️ 매도 실패: {error_msg}")
                        time.sleep(CHECK_INTERVAL)
                        continue
                else:
                    print(f"⚠️ 현재가 조회 실패 → 다음 루프에서 재시도")
                    time.sleep(CHECK_INTERVAL)
                    continue

            # 새 사이클 전환 시점 (09:00 도달)
            if state == "SOLD" or (state == "WAITING" and is_next_cycle(now)):
                if state == "WAITING":
                    notify(notifier, "⏹️ <b>사이클 종료</b>", "오늘은 돌파 없음. 매매 없이 종료.")
                    print("⏹️ 돌파 없이 사이클 종료.")
                print("   다음 사이클까지 대기합니다...")
                wait_until_next_cycle()
                return  # run_bot의 while True가 다시 호출

            # 현재가 조회
            current_price = upbit_broker.get_current_price(MARKET)
            if current_price is None:
                time.sleep(10)
                continue

            # ── 대기 상태: 돌파 감시 ──
            if state == "WAITING":
                # 수동 매수 감지
                if check_manual:
                    actual_qty = upbit_broker.get_holding_quantity(
                        UPBIT_ACCESS_KEY, UPBIT_SECRET_KEY, CURRENCY)
                    if actual_qty is not None and actual_qty > 0:
                        actual_price = upbit_broker.get_avg_buy_price(
                            UPBIT_ACCESS_KEY, UPBIT_SECRET_KEY, CURRENCY)
                        bought_price = actual_price if actual_price > 0 else current_price
                        holding_qty = actual_qty
                        highest_price = current_price  # 트레일링 고점 초기화
                        notify(notifier, "🔍 <b>수동 매수 감지</b>",
                               f"{holding_qty:.8f} ETH (매수가 {bought_price:,.0f}원)\n청산 관리를 이어받습니다.")
                        print(f"🔍 수동 매수 감지: {holding_qty:.8f} ETH → BOUGHT")
                        state = "BOUGHT"
                        time.sleep(CHECK_INTERVAL)
                        continue

                print(f"[{now.strftime('%H:%M:%S')}] 현재가: {current_price:,.0f}원 | "
                      f"목표가: {target_price:,.0f}원 | 대기 중")

                if current_price >= target_price:
                    # 슬리피지 체크
                    slippage = (current_price - target_price) / target_price
                    if slippage > MAX_SLIPPAGE:
                        print(f"   ⚠️ 슬리피지 초과! +{slippage:.2%} > 한도 {MAX_SLIPPAGE:.0%}")
                        notify(notifier, "⚠️ <b>돌파 감지했으나 스킵</b>",
                               f"현재가: {current_price:,.0f}원\n목표가: {target_price:,.0f}원\n"
                               f"슬리피지: +{slippage:.2%} > 한도 {MAX_SLIPPAGE:.0%}")
                        state = "SOLD"
                        time.sleep(CHECK_INTERVAL)
                        continue

                    # 매수!
                    cash = upbit_broker.get_balance(UPBIT_ACCESS_KEY, UPBIT_SECRET_KEY)
                    buy_amount = int(cash * POSITION_RATIO)  # KRW 금액

                    if buy_amount < 5000:  # 업비트 최소 주문 금액
                        notify(notifier, "⚠️ <b>잔고 부족</b>", f"현금: {cash:,.0f}원")
                        print(f"⚠️ 잔고 부족 (현금: {cash:,.0f}원)")
                        state = "SOLD"
                        time.sleep(CHECK_INTERVAL)
                        continue

                    print(f"\n🔥 돌파! {current_price:,.0f}원 ≥ {target_price:,.0f}원")
                    print(f"   매수 금액: {buy_amount:,}원")

                    res = upbit_broker.post_buy_order(
                        UPBIT_ACCESS_KEY, UPBIT_SECRET_KEY, MARKET, price=buy_amount)

                    if "uuid" in res:
                        # 체결 확인 (20초 대기)
                        order_uuid = res["uuid"]
                        bought_price = 0
                        holding_qty = 0
                        for _ in range(10):
                            time.sleep(2)
                            qty = upbit_broker.get_holding_quantity(
                                UPBIT_ACCESS_KEY, UPBIT_SECRET_KEY, CURRENCY)
                            if qty is not None and qty > 0:
                                holding_qty = qty
                                avg = upbit_broker.get_avg_buy_price(
                                    UPBIT_ACCESS_KEY, UPBIT_SECRET_KEY, CURRENCY)
                                bought_price = avg if avg > 0 else current_price
                                break

                        if holding_qty > 0:
                            highest_price = bought_price  # 트레일링 고점 초기화
                            log_trade("매수", bought_price, holding_qty,
                                      reason=f"돌파(목표 {target_price:,.0f}원)")
                            notify(notifier, "📈 <b>돌파 매수!</b>",
                                   f"가격: {bought_price:,.0f}원\n수량: {holding_qty:.8f} ETH\n"
                                   f"목표가: {target_price:,.0f}원\n"
                                   f"트레일링: 고점 대비 -{TRAILING_STOP_PCT*100:.0f}%")
                            print(f"✅ 매수 체결! {bought_price:,.0f}원 × {holding_qty:.8f} ETH")
                            state = "BOUGHT"
                        else:
                            notify(notifier, "⚠️ <b>미체결 감지</b>",
                                   f"20초 내 잔고 미확인\n당일 매매를 포기합니다")
                            print(f"⚠️ 미체결: 20초 내 잔고 확인 실패.")
                            state = "SOLD"
                    else:
                        error_msg = res.get("error", {}).get("message", str(res))
                        notify(notifier, "❌ <b>매수 실패</b>", error_msg)
                        print(f"❌ 매수 실패: {error_msg}")

            # ── 보유 상태: 청산 대기 ──
            elif state == "BOUGHT":
                # 수동 매도 감지
                if check_manual:
                    actual_qty = upbit_broker.get_holding_quantity(
                        UPBIT_ACCESS_KEY, UPBIT_SECRET_KEY, CURRENCY)
                    if actual_qty is None:
                        print(f"⚠️ 잔고 조회 실패 → 기존 수량 유지")
                        zero_qty_count = 0
                    elif actual_qty == 0:
                        zero_qty_count += 1
                        print(f"⚠️ 잔고 0 감지 ({zero_qty_count}/2회)")
                        if zero_qty_count >= 2:
                            notify(notifier, "🔍 <b>수동 매도 감지</b>",
                                   f"2회 연속 0 확인\n당일 추가 매매를 하지 않습니다.")
                            print(f"🔍 수동 매도 감지 → SOLD")
                            state = "SOLD"
                            time.sleep(CHECK_INTERVAL)
                            continue
                        time.sleep(CHECK_INTERVAL)
                        continue
                    else:
                        zero_qty_count = 0
                        holding_qty = actual_qty

                # 고점 갱신
                if current_price > highest_price:
                    highest_price = current_price

                profit_rate = (current_price * (1 - SELL_FEE) / (bought_price * (1 + BUY_FEE)) - 1) * 100
                trail_line = highest_price * (1 - TRAILING_STOP_PCT)
                drop_from_high = (highest_price - current_price) / highest_price * 100

                print(f"[{now.strftime('%H:%M:%S')}] 현재가: {current_price:,.0f}원 | "
                      f"수익률: {profit_rate:+.2f}% | 고점: {highest_price:,.0f} | "
                      f"청산선: {trail_line:,.0f} | 보유 ({holding_qty:.6f} ETH)")

                # 트레일링 스탑 발동
                if current_price <= trail_line:
                    print(f"\n📉 트레일링 스탑! 고점 {highest_price:,.0f}원 대비 -{drop_from_high:.1f}%")
                    res = upbit_broker.post_sell_order(
                        UPBIT_ACCESS_KEY, UPBIT_SECRET_KEY, MARKET, volume=holding_qty)

                    if "uuid" in res:
                        profit_rate = (current_price * (1 - SELL_FEE) / (bought_price * (1 + BUY_FEE)) - 1) * 100
                        log_trade("매도", current_price, holding_qty, profit=profit_rate,
                                  reason=f"트레일링(고점 {highest_price:,.0f}원 대비 -{drop_from_high:.1f}%)")
                        notify(notifier, "📉 <b>트레일링 스탑 청산!</b>",
                               f"가격: {current_price:,.0f}원\n수량: {holding_qty:.8f} ETH\n"
                               f"수익률: {profit_rate:+.2f}%\n"
                               f"고점: {highest_price:,.0f}원 대비 -{drop_from_high:.1f}%")
                        print(f"✅ 트레일링 청산! 수익률: {profit_rate:+.2f}%")
                        state = "SOLD"
                    else:
                        error_msg = res.get("error", {}).get("message", str(res))
                        print(f"⚠️ 트레일링 매도 실패: {error_msg} → 다음 루프 재시도")

            # ── 청산 완료 ──
            elif state == "SOLD":
                print(f"[{now.strftime('%H:%M:%S')}] 청산 완료. 다음 사이클 대기 중...")

            time.sleep(CHECK_INTERVAL)

        except Exception as e:
            error_msg = f"에러: {str(e)}"
            notify(notifier, "❌ <b>에러 발생</b>", error_msg)
            print(f"⚠️ {error_msg}")
            import traceback
            traceback.print_exc()
            time.sleep(60)


def is_sell_time(now):
    """청산 시각인지 확인합니다 (08:55~08:59)."""
    return now.hour == SELL_HOUR and now.minute >= SELL_MINUTE


def is_next_cycle(now):
    """다음 사이클 전환 시점인지 확인합니다.
    WAITING 상태에서 다음날 08:55 이후 = 사이클 종료
    """
    return now.hour == SELL_HOUR and now.minute >= SELL_MINUTE


def wait_until_next_cycle():
    """다음 09:00까지 대기합니다."""
    while True:
        now = datetime.now(KST)
        # 현재 09:00 이전이면 오늘 09:00까지, 아니면 내일 09:00까지
        if now.hour < CYCLE_START_HOUR:
            target = now.replace(hour=CYCLE_START_HOUR, minute=CYCLE_START_MINUTE,
                                 second=0, microsecond=0)
        else:
            # 내일 09:00
            tomorrow = now + timedelta(days=1)
            target = tomorrow.replace(hour=CYCLE_START_HOUR, minute=CYCLE_START_MINUTE,
                                      second=0, microsecond=0)

        remaining = (target - now).total_seconds()
        if remaining <= 0:
            return

        if remaining > 120:
            print(f"   다음 사이클까지 {int(remaining // 60)}분 남음...")
            time.sleep(60)
        elif remaining > 10:
            time.sleep(10)
        else:
            time.sleep(1)


if __name__ == "__main__":
    run_bot()
