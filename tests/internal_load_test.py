#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Internal Load Test - Botning ichki funksiyalarini test qilish
(Real API ga so'rov yubormasdan, botning ichki logikasini test qilish)
"""
import asyncio
import time
import sys
import os
from datetime import datetime
from typing import List, Dict
from dotenv import load_dotenv

# .env faylini yuklash
load_dotenv()

# Bot kodini import qilish
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.config import Config
from bot.models import storage
from telegram.ext import Application
from telegram import Update, Message, Chat, User
from telegram.ext import ContextTypes


class MockMessage:
    """Mock Message object"""
    def __init__(self, chat_id: int, user_id: int):
        self.chat_id = chat_id
        self.from_user = MockUser(user_id)
        self.text = ""
        self.message_id = 1
    
    async def reply_text(self, text: str, **kwargs):
        return MockMessage(self.chat_id, self.from_user.id)


class MockUser:
    """Mock User object"""
    def __init__(self, user_id: int):
        self.id = user_id
        self.username = f"user_{user_id}"
        self.first_name = f"User {user_id}"


class MockChat:
    """Mock Chat object"""
    def __init__(self, chat_id: int, chat_type: str = 'private'):
        self.id = chat_id
        self.type = chat_type


class MockUpdate:
    """Mock Update object"""
    def __init__(self, chat_id: int, user_id: int, text: str = ""):
        self.message = MockMessage(chat_id, user_id)
        self.effective_chat = MockChat(chat_id)
        self.effective_user = MockUser(user_id)
        self.update_id = user_id


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


async def simulate_quiz_start(application: Application, chat_id: int, user_id: int, quiz_id: str, result: LoadTestResult):
    """Quiz boshlashni simulyatsiya qilish"""
    try:
        from bot.services.quiz_service import start_quiz_session
        from telegram.ext import ContextTypes
        
        start_time = time.time()
        
        # Mock message yaratish
        message = MockMessage(chat_id, user_id)
        
        # Mock context yaratish
        class MockContext:
            def __init__(self, app):
                self.application = app
                self.bot = app.bot
                self.bot_data = app.bot_data
                self.chat_data = {}
                self.user_data = {}
        
        context = MockContext(application)
        
        # Quiz boshlash
        await start_quiz_session(
            message=message,
            context=context,
            quiz_id=quiz_id,
            chat_id=chat_id,
            user_id=user_id,
            time_seconds=30
        )
        
        response_time = time.time() - start_time
        result.add_result(True, response_time)
        
    except Exception as e:
        response_time = time.time() - start_time
        error_msg = f"{type(e).__name__}: {str(e)[:100]}"
        result.add_result(False, response_time, error_msg)


async def run_internal_load_test(concurrent_users: int, quiz_id: str):
    """Internal load test ishga tushirish"""
    print(f"\n{'='*60}")
    print(f"🚀 Internal Load Test ishga tushmoqda...")
    print(f"{'='*60}")
    print(f"📊 Concurrent users: {concurrent_users}")
    print(f"📝 Quiz ID: {quiz_id}")
    print(f"⏰ Vaqt: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")
    
    # Application yaratish
    if not Config.BOT_TOKEN:
        print("❌ BOT_TOKEN topilmadi!")
        print("   .env faylida BOT_TOKEN=your_bot_token qo'shing")
        return result
    
    print(f"✅ Bot token topildi")
    application = Application.builder().token(Config.BOT_TOKEN).build()
    
    try:
        await application.initialize()
    except Exception as e:
        print(f"❌ Application initialize qilishda xatolik: {e}")
        return result
    
    result = LoadTestResult()
    result.start_time = datetime.now()
    
    # Quiz mavjudligini tekshirish
    quiz = storage.get_quiz(quiz_id)
    if not quiz:
        print(f"❌ Quiz topilmadi: {quiz_id}")
        print("   Avval quiz yarating yoki mavjud quiz ID ni kiriting")
        return result
    
    print(f"✅ Quiz topildi: {quiz.get('title', 'N/A')}")
    print(f"⏳ {concurrent_users} ta parallel quiz boshlanmoqda...\n")
    
    # Parallel tasklar yaratish
    tasks = []
    for i in range(concurrent_users):
        chat_id = 1000000 + i  # Simulyatsiya qilingan chat ID
        user_id = 2000000 + i  # Simulyatsiya qilingan user ID
        task = simulate_quiz_start(application, chat_id, user_id, quiz_id, result)
        tasks.append(task)
    
    # Barcha tasklarni parallel ishga tushirish
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
    
    # Session statistika
    sessions = application.bot_data.get('sessions', {})
    active_sessions = sum(1 for s in sessions.values() if s.get('is_active', False))
    print(f"\n📈 Bot holati:")
    print(f"   • Jami sessionlar: {len(sessions)}")
    print(f"   • Aktiv sessionlar: {active_sessions}")
    
    if result.errors:
        print(f"\n❌ Xatoliklar ({len(result.errors)} ta):")
        unique_errors = {}
        for error in result.errors[:10]:
            error_key = error[:50]
            unique_errors[error_key] = unique_errors.get(error_key, 0) + 1
        
        for error, count in list(unique_errors.items())[:5]:
            print(f"   • {error} ({count} marta)")
    
    print(f"{'='*60}\n")
    
    await application.shutdown()
    return result


def main():
    """Asosiy funksiya"""
    concurrent_users = int(os.getenv('LOAD_TEST_USERS', '100'))
    quiz_id = os.getenv('LOAD_TEST_QUIZ_ID', '')
    
    if not quiz_id:
        print("❌ LOAD_TEST_QUIZ_ID topilmadi!")
        print("   .env faylida LOAD_TEST_QUIZ_ID=your_quiz_id qo'shing")
        print("\n   Yoki mavjud quiz ID ni topish:")
        print("   python3 -c \"from bot.models import storage; print(list(storage.get_all_quizzes())[0]['id'] if storage.get_all_quizzes() else 'No quizzes'))\"")
        sys.exit(1)
    
    # Load test ishga tushirish
    loop = asyncio.get_event_loop()
    result = loop.run_until_complete(
        run_internal_load_test(concurrent_users, quiz_id)
    )
    
    # Xulosa
    stats = result.get_stats()
    if stats.get('success_rate', 0) >= 95:
        print("\n✅ Test muvaffaqiyatli! Bot yaxshi ishlayapti.")
    elif stats.get('success_rate', 0) >= 80:
        print("\n⚠️ Test qisman muvaffaqiyatli. Optimizatsiya kerak.")
    else:
        print("\n❌ Test muvaffaqiyatsiz! Bot optimizatsiya qilinishi kerak.")


if __name__ == '__main__':
    main()
