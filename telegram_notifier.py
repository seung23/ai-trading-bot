# telegram_notifier.py
# Telegram으로 봇 실행 상태 및 매매 알림을 전송합니다.

import requests
import os
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))


class TelegramNotifier:
    def __init__(self, bot_token, chat_id):
        """
        Args:
            bot_token (str): Telegram Bot Token
            chat_id (str): Telegram Chat ID
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    def send_message(self, text):
        """Telegram으로 메시지를 전송합니다."""
        if not self.bot_token or not self.chat_id:
            return  # Telegram 미설정 시 무시

        try:
            payload = {
                'chat_id': self.chat_id,
                'text': text,
                'parse_mode': 'HTML'
            }
            response = requests.post(self.base_url, data=payload, timeout=10)
            if response.status_code != 200:
                print(f"⚠️ Telegram 전송 실패: {response.text}")
        except Exception as e:
            print(f"⚠️ Telegram 전송 에러: {e}")

    def notify_start(self, mode_label):
        """봇 실행 시작 알림"""
        msg = f"🚀 <b>트레이딩 봇 시작</b>\n\n"
        msg += f"모드: {mode_label}\n"
        msg += f"시작 시간: {datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')}"
        self.send_message(msg)

    def notify_ai_prediction(self, prob, signal, buy_threshold, mode_label):
        """AI 예측 결과 알림"""
        emoji = "🔥" if signal == "BUY" else "📭"
        msg = f"{emoji} <b>AI 예측 결과</b>\n\n"
        msg += f"모드: {mode_label}\n"
        msg += f"상승 확률: {prob:.1%}\n"
        msg += f"신호: {signal}\n"
        msg += f"매수 기준: ≥ {buy_threshold*100:.0f}%"
        self.send_message(msg)

    def notify_no_buy(self, prob, buy_threshold):
        """매수 조건 미충족 알림"""
        msg = f"📭 <b>오늘은 매수 없음</b>\n\n"
        msg += f"AI 확률: {prob:.1%}\n"
        msg += f"기준: {buy_threshold*100:.0f}% 이상\n"
        msg += f"프로그램 종료"
        self.send_message(msg)

    def notify_buy(self, price, quantity, prob):
        """매수 실행 알림"""
        msg = f"📈 <b>매수 체결!</b>\n\n"
        msg += f"가격: {price:,}원\n"
        msg += f"수량: {quantity}주\n"
        msg += f"AI 확률: {prob:.0%}\n"
        msg += f"시간: {datetime.now(KST).strftime('%H:%M:%S')}"
        self.send_message(msg)

    def notify_sell(self, price, quantity, profit_pct, reason):
        """매도 실행 알림"""
        emoji = "🎉" if profit_pct > 0 else "⚠️"
        msg = f"{emoji} <b>매도 체결!</b>\n\n"
        msg += f"가격: {price:,}원\n"
        msg += f"수량: {quantity}주\n"
        msg += f"수익률: {profit_pct:+.2f}%\n"
        msg += f"사유: {reason}\n"
        msg += f"시간: {datetime.now(KST).strftime('%H:%M:%S')}"
        self.send_message(msg)

    def notify_monitoring(self, current_price, bought_price, holding_qty, pnl_pct):
        """보유 중 모니터링 알림 (30분마다)"""
        msg = f"👀 <b>보유 현황</b>\n\n"
        msg += f"현재가: {current_price:,}원\n"
        msg += f"매수가: {bought_price:,}원\n"
        msg += f"보유: {holding_qty}주\n"
        msg += f"수익률: {pnl_pct:+.2f}%\n"
        msg += f"시간: {datetime.now(KST).strftime('%H:%M:%S')}"
        self.send_message(msg)

    def notify_market_closed(self, holding_qty, bought_price):
        """장 마감 알림"""
        msg = f"⏹️ <b>장 마감</b>\n\n"
        msg += f"보유 유지: {holding_qty}주\n"
        msg += f"매수단가: {bought_price:,}원\n"
        msg += f"내일 다시 실행됩니다."
        self.send_message(msg)

    def notify_error(self, error_msg):
        """에러 발생 알림"""
        msg = f"❌ <b>에러 발생!</b>\n\n"
        msg += f"{error_msg}\n\n"
        msg += f"시간: {datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')}"
        self.send_message(msg)

    def notify_finish(self):
        """봇 정상 종료 알림"""
        msg = f"✅ <b>봇 종료</b>\n\n"
        msg += f"종료 시간: {datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')}"
        self.send_message(msg)


# 간단한 사용 예시
if __name__ == "__main__":
    # .env에서 읽어오거나 직접 입력
    BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

    if BOT_TOKEN and CHAT_ID:
        notifier = TelegramNotifier(BOT_TOKEN, CHAT_ID)
        notifier.send_message("✅ Telegram 알림 테스트 성공!")
    else:
        print("⚠️ TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID가 설정되지 않았습니다.")
