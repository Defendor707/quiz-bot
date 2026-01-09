#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Load Test - Bot performance testi (100+ concurrent userlar)
"""
import asyncio
import time
import httpx
import json
import os
from typing import List, Dict
from datetime import datetime
import sys

# Bot token va sozlamalar
BOT_TOKEN = os.getenv('BOT_TOKEN', '')
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Test sozlamalari
CONCURRENT_USERS = int(os.getenv('LOAD_TEST_USERS', '100'))  # Default: 100 ta foydalanuvchi
TEST_CHAT_ID = int(os.getenv('LOAD_TEST_CHAT_ID', '0'))  # Test chat ID
QUIZ_ID = os.getenv('LOAD_TEST_QUIZ_ID', '')  # Test quiz ID


class LoadTestResult:
    """Test natijalari"""
    def __init__(self):
        self.total_requests = 0
        self.successful = 0
        self.failed = 0
        self.response_times = []
        self.errors = []
        self.start_time = None
        self.end_time = None
    
    def add_result(self, success: bool, response_time: float, error: str = None):
        self.total_requests += 1
        if success:
            self.successful += 1
        else:
            self.failed += 1
            if error:
                self.errors.append(error)
        self.response_times.append(response_time)
    
    def get_stats(self) -> Dict:
        if not self.response_times:
            return {}
        
        sorted_times = sorted(self.response_times)
        return {
            'total': self.total_requests,
            'successful': self.successful,
            'failed': self.failed,
            'success_rate': (self.successful / self.total_requests * 100) if self.total_requests > 0 else 0,
            'avg_response_time': sum(self.response_times) / len(self.response_times),
            'min_response_time': min(self.response_times),
            'max_response_time': max(self.response_times),
            'median_response_time': sorted_times[len(sorted_times) // 2],
            'p95_response_time': sorted_times[int(len(sorted_times) * 0.95)] if len(sorted_times) > 0 else 0,
            'p99_response_time': sorted_times[int(len(sorted_times) * 0.99)] if len(sorted_times) > 0 else 0,
            'duration': (self.end_time - self.start_time).total_seconds() if self.end_time and self.start_time else 0
        }


async def send_message(client: httpx.AsyncClient, chat_id: int, text: str, user_id: int) -> tuple[bool, float, str]:
    """Botga xabar yuborish"""
    start_time = time.time()
    try:
        response = await client.post(
            f"{BASE_URL}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown"
            },
            timeout=30.0
        )
        response_time = time.time() - start_time
        
        if response.status_code == 200:
            return True, response_time, None
        else:
            error_text = f"HTTP {response.status_code}: {response.text[:100]}"
            return False, response_time, error_text
    except Exception as e:
        response_time = time.time() - start_time
        return False, response_time, str(e)[:100]


async def simulate_user(user_id: int, chat_id: int, quiz_id: str, result: LoadTestResult):
    """Bir foydalanuvchini simulyatsiya qilish"""
    async with httpx.AsyncClient() as client:
        # 1. Quiz boshlash
        text = f"/startquiz {quiz_id}" if quiz_id else "/quizzes"
        success, resp_time, error = await send_message(client, chat_id, text, user_id)
        result.add_result(success, resp_time, error)
        
        # Kichik kechikish
        await asyncio.sleep(0.1)
        
        # 2. Quiz ro'yxatini ko'rish (agar quiz_id yo'q bo'lsa)
        if not quiz_id:
            success, resp_time, error = await send_message(client, chat_id, "/quizzes", user_id)
            result.add_result(success, resp_time, error)


async def run_load_test(concurrent_users: int, chat_id: int, quiz_id: str):
    """Load test ishga tushirish"""
    print(f"\n{'='*60}")
    print(f"🚀 Load Test ishga tushmoqda...")
    print(f"{'='*60}")
    print(f"📊 Concurrent users: {concurrent_users}")
    print(f"💬 Chat ID: {chat_id}")
    print(f"📝 Quiz ID: {quiz_id if quiz_id else 'N/A (quizzes list)'}")
    print(f"⏰ Vaqt: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")
    
    result = LoadTestResult()
    result.start_time = datetime.now()
    
    # Parallel tasklar yaratish
    tasks = []
    for i in range(concurrent_users):
        user_id = 1000000 + i  # Simulyatsiya qilingan user ID
        task = simulate_user(user_id, chat_id, quiz_id, result)
        tasks.append(task)
    
    # Barcha tasklarni parallel ishga tushirish
    print(f"⏳ {concurrent_users} ta parallel request yuborilmoqda...")
    start = time.time()
    
    await asyncio.gather(*tasks, return_exceptions=True)
    
    result.end_time = datetime.now()
    total_time = time.time() - start
    
    # Natijalarni ko'rsatish
    stats = result.get_stats()
    
    print(f"\n{'='*60}")
    print(f"✅ Test yakunlandi!")
    print(f"{'='*60}")
    print(f"📊 Umumiy statistika:")
    print(f"   • Jami requestlar: {stats.get('total', 0)}")
    print(f"   • Muvaffaqiyatli: {stats.get('successful', 0)}")
    print(f"   • Xatoliklar: {stats.get('failed', 0)}")
    print(f"   • Muvaffaqiyat foizi: {stats.get('success_rate', 0):.2f}%")
    print(f"\n⏱ Response time:")
    print(f"   • O'rtacha: {stats.get('avg_response_time', 0):.3f}s")
    print(f"   • Minimum: {stats.get('min_response_time', 0):.3f}s")
    print(f"   • Maximum: {stats.get('max_response_time', 0):.3f}s")
    print(f"   • Median: {stats.get('median_response_time', 0):.3f}s")
    print(f"   • P95: {stats.get('p95_response_time', 0):.3f}s")
    print(f"   • P99: {stats.get('p99_response_time', 0):.3f}s")
    print(f"\n⏰ Test vaqti: {stats.get('duration', 0):.2f}s")
    print(f"   • Requests per second: {stats.get('total', 0) / stats.get('duration', 1):.2f}")
    
    if result.errors:
        print(f"\n❌ Xatoliklar ({len(result.errors)} ta):")
        unique_errors = {}
        for error in result.errors[:10]:  # Faqat birinchi 10 tasini ko'rsatish
            error_key = error[:50]
            unique_errors[error_key] = unique_errors.get(error_key, 0) + 1
        
        for error, count in list(unique_errors.items())[:5]:
            print(f"   • {error} ({count} marta)")
    
    print(f"{'='*60}\n")
    
    return result


async def monitor_bot_status():
    """Bot holatini monitoring qilish (parallel)"""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{BASE_URL}/getMe", timeout=5.0)
            if response.status_code == 200:
                data = response.json()
                if data.get('ok'):
                    bot_info = data.get('result', {})
                    print(f"🤖 Bot: @{bot_info.get('username', 'N/A')} ({bot_info.get('first_name', 'N/A')})")
                    return True
            return False
        except Exception as e:
            print(f"❌ Bot holatini tekshirishda xatolik: {e}")
            return False


def main():
    """Asosiy funksiya"""
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN topilmadi! .env faylini tekshiring.")
        sys.exit(1)
    
    # Bot holatini tekshirish
    print("🔍 Bot holatini tekshirilmoqda...")
    loop = asyncio.get_event_loop()
    bot_ok = loop.run_until_complete(monitor_bot_status())
    
    if not bot_ok:
        print("❌ Bot ishlamayapti yoki token noto'g'ri!")
        sys.exit(1)
    
    # Test parametrlarini olish
    concurrent_users = CONCURRENT_USERS
    chat_id = TEST_CHAT_ID
    quiz_id = QUIZ_ID
    
    if chat_id == 0:
        print("⚠️ LOAD_TEST_CHAT_ID sozlanmagan!")
        print("   .env faylida LOAD_TEST_CHAT_ID=your_chat_id qo'shing")
        sys.exit(1)
    
    # Load test ishga tushirish
    result = loop.run_until_complete(
        run_load_test(concurrent_users, chat_id, quiz_id)
    )
    
    # Natijalarni faylga saqlash
    stats = result.get_stats()
    report = {
        'timestamp': datetime.now().isoformat(),
        'concurrent_users': concurrent_users,
        'chat_id': chat_id,
        'quiz_id': quiz_id,
        'stats': stats,
        'errors_count': len(result.errors)
    }
    
    report_file = f"tests/load_test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    os.makedirs('tests', exist_ok=True)
    with open(report_file, 'w') as f:
        json.dump(report, f, indent=2)
    
    print(f"📄 Hisobot saqlandi: {report_file}")
    
    # Xulosa
    if stats.get('success_rate', 0) >= 95:
        print("\n✅ Test muvaffaqiyatli! Bot yaxshi ishlayapti.")
    elif stats.get('success_rate', 0) >= 80:
        print("\n⚠️ Test qisman muvaffaqiyatli. Optimizatsiya kerak.")
    else:
        print("\n❌ Test muvaffaqiyatsiz! Bot optimizatsiya qilinishi kerak.")


if __name__ == '__main__':
    main()
