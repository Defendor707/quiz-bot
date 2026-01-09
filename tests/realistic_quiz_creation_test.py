#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Realistic Quiz Creation Test - Haqiqiy quiz yaratish jarayonini to'liq test qilish
(Barcha tekshiruvlar, premium/quota, storage, tracking)
"""
import asyncio
import time
import sys
import os
import hashlib
import json
from datetime import datetime
from typing import List, Dict
from dotenv import load_dotenv

# .env faylini yuklash
load_dotenv()

# Bot kodini import qilish
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.config import Config
from bot.models import storage
from bot.services.subscription import can_create_quiz, get_user_plan
from telegram.ext import Application


class LoadTestResult:
    """Test natijalari"""
    def __init__(self):
        self.total_requests = 0
        self.successful = 0
        self.failed = 0
        self.response_times = []
        self.errors = []
        self.quota_errors = 0
        self.start_time = None
        self.end_time = None
    
    def add_result(self, success: bool, response_time: float, error: str = None, is_quota_error: bool = False):
        self.total_requests += 1
        if success:
            self.successful += 1
        else:
            self.failed += 1
            if is_quota_error:
                self.quota_errors += 1
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
            'quota_errors': self.quota_errors,
            'success_rate': (self.successful / self.total_requests * 100) if self.total_requests > 0 else 0,
            'avg_response_time': sum(self.response_times) / len(self.response_times),
            'min_response_time': min(self.response_times),
            'max_response_time': max(self.response_times),
            'median_response_time': sorted_times[len(sorted_times) // 2],
            'p95_response_time': sorted_times[int(len(sorted_times) * 0.95)] if len(sorted_times) > 0 else 0,
            'p99_response_time': sorted_times[int(len(sorted_times) * 0.99)] if len(sorted_times) > 0 else 0,
            'duration': (self.end_time - self.start_time).total_seconds() if self.end_time and self.start_time else 0
        }


def generate_sample_quiz_questions(count: int = 10) -> List[Dict]:
    """Namuna quiz savollarini yaratish"""
    questions = []
    for i in range(count):
        questions.append({
            'question': f'Test savol {i+1}?',
            'options': ['Variant A', 'Variant B', 'Variant C', 'Variant D'],
            'correct_answer': i % 4,
            'explanation': f'Savol {i+1} tushuntirish'
        })
    return questions


async def simulate_realistic_quiz_creation(application: Application, chat_id: int, user_id: int, result: LoadTestResult):
    """Haqiqiy quiz yaratish jarayonini simulyatsiya qilish"""
    start_time = time.time()
    
    try:
        # 1. User tracking (haqiqiy jarayonda)
        storage.track_user(
            user_id=user_id,
            username=f"user_{user_id}",
            first_name=f"User {user_id}",
            last_name=None,
            last_chat_id=chat_id,
            last_chat_type='private'
        )
        
        # 2. Premium/quota tekshiruvi (haqiqiy jarayonda)
        can_create, error_msg = can_create_quiz(user_id)
        if not can_create:
            response_time = time.time() - start_time
            result.add_result(False, response_time, error_msg, is_quota_error=True)
            return
        
        # 3. Quiz ma'lumotlarini yaratish
        questions = generate_sample_quiz_questions(10)
        quiz_content = json.dumps(questions, sort_keys=True)
        quiz_id = hashlib.md5(f"{quiz_content}_{user_id}_{time.time()}".encode()).hexdigest()[:12]
        title = f"Test Quiz {user_id}"
        
        # 4. Quiz saqlash (haqiqiy jarayonda)
        storage.save_quiz(
            quiz_id=quiz_id,
            questions=questions,
            created_by=user_id,
            created_in_chat=chat_id,
            title=title
        )
        
        # 5. Quiz mavjudligini tekshirish
        saved_quiz = storage.get_quiz(quiz_id)
        if saved_quiz and saved_quiz.get('quiz_id') == quiz_id:
            # 6. User plan tekshiruvi (statistika uchun)
            plan = get_user_plan(user_id)
            
            response_time = time.time() - start_time
            result.add_result(True, response_time)
        else:
            response_time = time.time() - start_time
            result.add_result(False, response_time, "Quiz saqlanmadi")
    
    except Exception as e:
        response_time = time.time() - start_time
        error_msg = f"{type(e).__name__}: {str(e)[:100]}"
        result.add_result(False, response_time, error_msg)


async def run_realistic_quiz_creation_test(concurrent_users: int = 100):
    """Haqiqiy quiz yaratish test ishga tushirish"""
    print(f"\n{'='*60}")
    print(f"🎯 Realistic Quiz Creation Test ishga tushmoqda...")
    print(f"{'='*60}")
    print(f"📊 Concurrent users: {concurrent_users}")
    print(f"⏰ Vaqt: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")
    print(f"ℹ️  Bu test quyidagilarni tekshiradi:")
    print(f"   • User tracking")
    print(f"   • Premium/quota tekshiruvi")
    print(f"   • Quiz saqlash")
    print(f"   • Database operations")
    print(f"{'='*60}\n")
    
    # Application yaratish
    if not Config.BOT_TOKEN:
        token = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
    else:
        token = Config.BOT_TOKEN
    
    application = Application.builder().token(token).build()
    application.bot_data = {'sessions': {}, 'group_locks': {}}
    
    try:
        await application.initialize()
    except Exception:
        pass
    
    result = LoadTestResult()
    result.start_time = datetime.now()
    
    print(f"⏳ {concurrent_users} ta parallel quiz yaratilmoqda...\n")
    
    # Parallel tasklar yaratish
    tasks = []
    for i in range(concurrent_users):
        chat_id = 1000000 + i
        user_id = 2000000 + i
        task = simulate_realistic_quiz_creation(application, chat_id, user_id, result)
        tasks.append(task)
    
    # Barcha tasklarni parallel ishga tushirish
    start = time.time()
    await asyncio.gather(*tasks, return_exceptions=True)
    result.end_time = datetime.now()
    total_time = time.time() - start
    
    # Natijalarni ko'rsatish
    stats = result.get_stats()
    
    print(f"\n{'='*60}")
    print(f"📊 TEST NATIJALARI")
    print(f"{'='*60}")
    print(f"✅ Muvaffaqiyatli: {stats.get('successful', 0)}/{stats.get('total', 0)}")
    print(f"❌ Muvaffaqiyatsiz: {stats.get('failed', 0)}/{stats.get('total', 0)}")
    if stats.get('quota_errors', 0) > 0:
        print(f"⚠️  Quota xatoliklari: {stats.get('quota_errors', 0)} (bu normal, chunki Free tarif limiti bor)")
    print(f"📈 Muvaffaqiyat darajasi: {stats.get('success_rate', 0):.2f}%")
    print(f"\n⏱️  Vaqt statistikasi:")
    print(f"   • Umumiy vaqt: {stats.get('duration', 0):.2f} sekund")
    print(f"   • O'rtacha vaqt: {stats.get('avg_response_time', 0):.3f} sekund")
    print(f"   • Minimal vaqt: {stats.get('min_response_time', 0):.3f} sekund")
    print(f"   • Maksimal vaqt: {stats.get('max_response_time', 0):.3f} sekund")
    print(f"   • Median vaqt: {stats.get('median_response_time', 0):.3f} sekund")
    print(f"   • P95 vaqt: {stats.get('p95_response_time', 0):.3f} sekund")
    print(f"   • P99 vaqt: {stats.get('p99_response_time', 0):.3f} sekund")
    if stats.get('duration', 0) > 0:
        print(f"   • Sekundiga so'rovlar: {stats.get('total', 0) / stats.get('duration', 1):.2f} req/s")
    
    if result.errors and stats.get('quota_errors', 0) < len(result.errors):
        print(f"\n❌ Xatoliklar ({len(result.errors) - stats.get('quota_errors', 0)} ta):")
        error_counts = {}
        for error in result.errors:
            if "limit" not in error.lower() and "quota" not in error.lower():
                error_type = error.split(':')[0] if ':' in error else error
                error_counts[error_type] = error_counts.get(error_type, 0) + 1
        
        for error_type, count in list(error_counts.items())[:5]:
            print(f"   • {error_type}: {count} marta")
    
    print(f"\n{'='*60}")
    print(f"✅ Test yakunlandi!")
    print(f"{'='*60}\n")
    
    return result


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Realistic Quiz Creation Test')
    parser.add_argument('--users', type=int, default=100, help='Concurrent users soni (default: 100)')
    
    args = parser.parse_args()
    
    asyncio.run(run_realistic_quiz_creation_test(args.users))
