# get_chat_id.py
# Telegram Chat ID를 쉽게 받는 스크립트

import requests
import sys

print("=" * 60)
print("📱 Telegram Chat ID 확인 도구")
print("=" * 60)

# Bot Token 입력 받기
bot_token = input("\nBot Token을 입력하세요: ").strip()

if not bot_token:
    print("❌ Bot Token이 비어있습니다.")
    sys.exit(1)

# getUpdates API 호출
url = f"https://api.telegram.org/bot{bot_token}/getUpdates"

print(f"\n🔍 업데이트 확인 중...")
print(f"📌 먼저 Telegram 앱에서 봇에게 /start 메시지를 보내세요!\n")

try:
    response = requests.get(url, timeout=10)
    data = response.json()

    if not data.get('ok'):
        print(f"❌ API 오류: {data}")
        sys.exit(1)

    results = data.get('result', [])

    if not results:
        print("⚠️  메시지가 없습니다!")
        print("\n📌 해결 방법:")
        print("   1. Telegram 앱에서 봇을 찾으세요")
        print("   2. 봇과의 대화창에서 /start를 입력하고 전송")
        print("   3. 이 스크립트를 다시 실행하세요")
        sys.exit(0)

    # Chat ID 찾기
    print("✅ 메시지를 찾았습니다!\n")
    print("-" * 60)

    for update in results:
        if 'message' in update:
            chat_id = update['message']['chat']['id']
            username = update['message']['chat'].get('username', 'N/A')
            first_name = update['message']['chat'].get('first_name', 'N/A')
            text = update['message'].get('text', '')

            print(f"📱 Chat ID: {chat_id}")
            print(f"👤 이름: {first_name}")
            print(f"🔖 유저네임: @{username}")
            print(f"💬 메시지: {text}")
            print("-" * 60)

    print(f"\n✅ .env 파일에 다음과 같이 추가하세요:")
    print(f"\nTELEGRAM_BOT_TOKEN={bot_token}")
    if results and 'message' in results[0]:
        print(f"TELEGRAM_CHAT_ID={results[0]['message']['chat']['id']}")

except requests.exceptions.RequestException as e:
    print(f"❌ 네트워크 오류: {e}")
    sys.exit(1)
