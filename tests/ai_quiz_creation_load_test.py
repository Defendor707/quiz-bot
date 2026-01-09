#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Quiz Creation Load Test - AI parsing orqali quiz yaratishni test qilish
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
from bot.services.ai_parser import AIParser
from telegram.ext import Application


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


def generate_sample_text() -> str:
    """Namuna matn yaratish (AI parsing uchun)"""
    return """Test savollari:

1. Python qaysi dasturlash tili?
A) Java
B) Python
C) C++
D) JavaScript
To'g'ri javob: B

2. SQL nima?
A) Database query language
B) Programming language
C) Markup language
D) Scripting language
To'g'ri javob: A

3. HTTP nima?
A) HyperText Transfer Protocol
B) File transfer protocol
C) Network protocol
D) Communication protocol
To'g'ri javob: A

4. REST API nima?
A) Representational State Transfer
B) Remote State Transfer
C) Resource State Transfer
D) Request State Transfer
To'g'ri javob: A

5. JSON nima?
A) JavaScript Object Notation
B) Java Object Notation
C) JavaScript Object Network
D) Java Object Network
To'g'ri javob: A"""


async def simulate_ai_quiz_creation(user_id: int, result: LoadTestResult):
    """AI parsing orqali quiz yaratishni simulyatsiya qilish"""
    start_time = time.time()
    
    try:
        # AI API key tekshirish
        if not Config.DEEPSEEK_API_KEY:
            response_time = time.time() - start_time
            result.add_result(False, response_time, "DEEPSEEK_API_KEY topilmadi")
            return
        
        # AI Parser yaratish
        ai_parser = AIParser(Config.DEEPSEEK_API_KEY, Config.DEEPSEEK_API_URL)
        
        # Namuna matn
        text = generate_sample_text()
        
        # AI parsing
        result_data = await ai_parser.analyze_with_ai(
            text,
            progress_callback=None,
            strict_correct=False,
            max_concurrent=2,  # Concurrent requests cheklash
            timeout=60
        )
        
        if not result_data or not result_data.get('questions'):
            response_time = time.time() - start_time
            result.add_result(False, response_time, "AI parsing natija bermadi")
            return
        
        # Quiz ma'lumotlarini yaratish
        questions = result_data.get('questions', [])
        quiz_content = json.dumps(questions, sort_keys=True)
        quiz_id = hashlib.md5(f"{quiz_content}_{user_id}_{time.time()}".encode()).hexdigest()[:12]
        title = result_data.get('title', f'AI Quiz {user_id}')
        
        # Quiz saqlash
        chat_id = 1000000 + user_id  # Simulyatsiya qilingan chat ID
        storage.save_quiz(
            quiz_id=quiz_id,
            questions=questions,
            created_by=user_id,
            created_in_chat=chat_id,
            title=title
        )
        
        # Quiz mavjudligini tekshirish
        saved_quiz = storage.get_quiz(quiz_id)
        if saved_quiz and saved_quiz.get('quiz_id') == quiz_id:
            response_time = time.time() - start_time
            result.add_result(True, response_time)
        else:
            response_time = time.time() - start_time
            result.add_result(False, response_time, "Quiz saqlanmadi")
    
    except Exception as e:
        response_time = time.time() - start_time
        error_msg = f"{type(e).__name__}: {str(e)[:100]}"
        result.add_result(False, response_time, error_msg)


async def run_ai_quiz_creation_load_test(concurrent_users: int = 10):
    """AI quiz yaratish load test ishga tushirish"""
    print(f"\n{'='*60}")
    print(f"🤖 AI Quiz Creation Load Test ishga tushmoqda...")
    print(f"{'='*60}")
    print(f"📊 Concurrent users: {concurrent_users}")
    print(f"⏰ Vaqt: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # AI API key tekshirish
    if not Config.DEEPSEEK_API_KEY:
        print(f"❌ DEEPSEEK_API_KEY topilmadi!")
        print(f"   .env faylida DEEPSEEK_API_KEY=your_api_key qo'shing")
        return
    
    print(f"✅ AI API key topildi")
    print(f"🌐 AI API URL: {Config.DEEPSEEK_API_URL}")
    print(f"⚠️  Eslatma: AI API rate limiting bo'lishi mumkin")
    print(f"{'='*60}\n")
    
    result = LoadTestResult()
    result.start_time = datetime.now()
    
    print(f"⏳ {concurrent_users} ta parallel AI quiz yaratilmoqda...")
    print(f"   (Bu biroz vaqt olishi mumkin, chunki AI API ga so'rovlar yuborilmoqda...)\n")
    
    # Parallel tasklar yaratish (lekin semaphore orqali cheklash)
    tasks = []
    for i in range(concurrent_users):
        user_id = 2000000 + i  # Simulyatsiya qilingan user ID
        task = simulate_ai_quiz_creation(user_id, result)
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
    print(f"📈 Muvaffaqiyat darajasi: {stats.get('success_rate', 0):.2f}%")
    print(f"\n⏱️  Vaqt statistikasi:")
    print(f"   • Umumiy vaqt: {stats.get('duration', 0):.2f} sekund")
    print(f"   • O'rtacha vaqt: {stats.get('avg_response_time', 0):.2f} sekund")
    print(f"   • Minimal vaqt: {stats.get('min_response_time', 0):.2f} sekund")
    print(f"   • Maksimal vaqt: {stats.get('max_response_time', 0):.2f} sekund")
    print(f"   • Median vaqt: {stats.get('median_response_time', 0):.2f} sekund")
    print(f"   • P95 vaqt: {stats.get('p95_response_time', 0):.2f} sekund")
    print(f"   • P99 vaqt: {stats.get('p99_response_time', 0):.2f} sekund")
    if stats.get('duration', 0) > 0:
        print(f"   • Sekundiga so'rovlar: {stats.get('total', 0) / stats.get('duration', 1):.2f} req/s")
    
    if result.errors:
        print(f"\n❌ Xatoliklar ({len(result.errors)} ta):")
        error_counts = {}
        for error in result.errors[:10]:  # Faqat birinchi 10 tasini ko'rsatish
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
    
    parser = argparse.ArgumentParser(description='AI Quiz Creation Load Test')
    parser.add_argument('--users', type=int, default=10, help='Concurrent users soni (default: 10, max: 20)')
    
    args = parser.parse_args()
    
    # AI API rate limiting uchun cheklash
    if args.users > 20:
        print(f"⚠️  AI API rate limiting uchun maksimal 20 ta concurrent user qo'llab-quvvatlanadi")
        print(f"   {args.users} o'rniga 20 ta ishlatilmoqda...")
        args.users = 20
    
    asyncio.run(run_ai_quiz_creation_load_test(args.users))
