#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI API Concurrent Test - AI API ga bir vaqtda 100 ta so'rov yuborishni test qilish
"""
import asyncio
import time
import sys
import os
from datetime import datetime
from typing import List, Dict
from dotenv import load_dotenv
import httpx

# Environment variable dan API key ni olish (agar berilgan bo'lsa)
# Bu test uchun muhim - environment variable orqali API key berilganda ishlashi kerak

# .env faylini yuklash
load_dotenv()

# Bot kodini import qilish
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Environment variable dan API key ni olish (agar berilgan bo'lsa)
# Bu test uchun muhim - environment variable orqali API key berilganda ishlashi kerak
if 'DEEPSEEK_API_KEY' in os.environ:
    # Environment variable dan olish
    api_key_from_env = os.environ['DEEPSEEK_API_KEY']
    # Config ga qo'shish (agar Config.DEEPSEEK_API_KEY bo'sh bo'lsa)
    if not api_key_from_env.startswith('sk-'):
        # Ehtimol .env fayldan o'qilgan
        pass
    else:
        # Environment variable dan to'g'ridan-to'g'ri olish
        os.environ['DEEPSEEK_API_KEY'] = api_key_from_env

from bot.config import Config
from bot.services.ai_parser import AIParser

# Agar environment variable orqali API key berilgan bo'lsa, Config ga qo'shish
if 'DEEPSEEK_API_KEY' in os.environ and not Config.DEEPSEEK_API_KEY:
    Config.DEEPSEEK_API_KEY = os.environ['DEEPSEEK_API_KEY']


class LoadTestResult:
    """Test natijalari"""
    def __init__(self):
        self.total_requests = 0
        self.successful = 0
        self.failed = 0
        self.response_times = []
        self.errors = []
        self.rate_limit_errors = 0
        self.timeout_errors = 0
        self.start_time = None
        self.end_time = None
        self.total_tokens = 0
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
    
    def add_result(self, success: bool, response_time: float, error: str = None, error_type: str = None, tokens: int = 0, prompt_tokens: int = 0, completion_tokens: int = 0):
        self.total_requests += 1
        if success:
            self.successful += 1
            self.total_tokens += tokens
            self.total_prompt_tokens += prompt_tokens
            self.total_completion_tokens += completion_tokens
        else:
            self.failed += 1
            if error_type == 'rate_limit':
                self.rate_limit_errors += 1
            elif error_type == 'timeout':
                self.timeout_errors += 1
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
            'rate_limit_errors': self.rate_limit_errors,
            'timeout_errors': self.timeout_errors,
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
    """Namuna matn yaratish"""
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
To'g'ri javob: A"""


async def make_ai_request(request_id: int, result: LoadTestResult, use_semaphore: bool = True):
    """AI API ga so'rov yuborish"""
    start_time = time.time()
    
    try:
        # AI API key olish (avval environment variable, keyin Config)
        api_key = os.environ.get('DEEPSEEK_API_KEY') or Config.DEEPSEEK_API_KEY
        api_url = Config.DEEPSEEK_API_URL
        
        if not api_key:
            response_time = time.time() - start_time
            result.add_result(False, response_time, "DEEPSEEK_API_KEY topilmadi")
            return
        
        # AI Parser yaratish
        ai_parser = AIParser(api_key, api_url)
        
        # Namuna matn
        text = generate_sample_text()
        
        # AI parsing (semaphore bilan yoki semaphoresiz)
        if use_semaphore:
            # Semaphore bilan (botning default xatti-harakati)
            result_data = await ai_parser.analyze_with_ai(
                text,
                progress_callback=None,
                strict_correct=False,
                max_concurrent=2,  # Bot default: 2 ta parallel
                timeout=60
            )
            
            # Semaphore bilan ishlatganda usage ma'lumotlarini olish qiyin
            # Chunki AIParser ichida usage qaytarilmaydi
            # Shuning uchun semaphore bilan ishlatganda tokens = 0
            if result_data and result_data.get('questions'):
                response_time = time.time() - start_time
                result.add_result(True, response_time, tokens=0, prompt_tokens=0, completion_tokens=0)
            else:
                response_time = time.time() - start_time
                result.add_result(False, response_time, "AI parsing natija bermadi")
            return
        else:
            # Semaphoresiz - to'g'ridan-to'g'ri API ga so'rov
            # Bu haqiqiy concurrent test
            async with httpx.AsyncClient(timeout=60.0) as client:
                prompt = f"""Quyidagi matndan test savollarini ajratib oling.
Matn:
{text}

Javobni JSON formatida qaytaring:
{{
  "title": "Qisqa nom",
  "questions": [
    {{
      "question": "Savol matni",
      "options": ["Variant 1", "Variant 2", "Variant 3"],
      "correct_answer": 0
    }}
  ]
}}"""
                
                headers = {
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {api_key}'
                }
                
                data = {
                    'model': 'deepseek-chat',
                    'messages': [
                        {'role': 'system', 'content': 'Siz test tahlilchisiz. Faqat JSON qaytaring.'},
                        {'role': 'user', 'content': prompt}
                    ],
                    'temperature': 0.0,
                    'max_tokens': 2000
                }
                
                # Debug: API key va URL ni ko'rsatish (faqat birinchi so'rov uchun)
                if request_id == 0:
                    print(f"   [DEBUG] API Key: {api_key[:20]}...")
                    print(f"   [DEBUG] API URL: {api_url}")
                
                response = await client.post(
                    api_url,
                    headers=headers,
                    json=data
                )
                
                if response.status_code == 429:
                    # Rate limit
                    response_time = time.time() - start_time
                    result.add_result(False, response_time, f"Rate limit (429)", error_type='rate_limit')
                    return
                
                if response.status_code != 200:
                    response_time = time.time() - start_time
                    result.add_result(False, response_time, f"HTTP {response.status_code}: {response.text[:100]}")
                    return
                
                result_json = response.json()
                
                # Usage ma'lumotlarini olish
                usage = result_json.get('usage', {})
                total_tokens = usage.get('total_tokens', 0)
                prompt_tokens = usage.get('prompt_tokens', 0)
                completion_tokens = usage.get('completion_tokens', 0)
                
                # Debug: birinchi so'rov uchun to'liq ma'lumotlarni ko'rsatish
                if request_id == 0:
                    print(f"   [DEBUG Request 0] Response ID: {result_json.get('id', 'N/A')}")
                    print(f"   [DEBUG Request 0] Model: {result_json.get('model', 'N/A')}")
                    print(f"   [DEBUG Request 0] Usage: {usage}")
                
                if 'choices' in result_json and len(result_json['choices']) > 0:
                    content = result_json['choices'][0]['message']['content']
                    result_data = ai_parser.extract_json_dict(content)
                else:
                    result_data = None
                
                if result_data and result_data.get('questions'):
                    response_time = time.time() - start_time
                    result.add_result(True, response_time, tokens=total_tokens, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
                else:
                    # Agar parsing natija bermasa ham, so'rov muvaffaqiyatli bo'lsa, usage ni qaytarish
                    if response.status_code == 200 and total_tokens > 0:
                        response_time = time.time() - start_time
                        result.add_result(True, response_time, tokens=total_tokens, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
                    else:
                        response_time = time.time() - start_time
                        result.add_result(False, response_time, "AI parsing natija bermadi")
                        return
    
    except asyncio.TimeoutError:
        response_time = time.time() - start_time
        result.add_result(False, response_time, "Timeout", error_type='timeout')
    except httpx.HTTPStatusError as e:
        response_time = time.time() - start_time
        if e.response.status_code == 429:
            result.add_result(False, response_time, f"Rate limit (429)", error_type='rate_limit')
        else:
            result.add_result(False, response_time, f"HTTP {e.response.status_code}")
    except Exception as e:
        response_time = time.time() - start_time
        error_msg = f"{type(e).__name__}: {str(e)[:100]}"
        result.add_result(False, response_time, error_msg)


async def run_ai_api_concurrent_test(concurrent_requests: int = 100, use_semaphore: bool = False):
    """AI API concurrent test ishga tushirish"""
    print(f"\n{'='*60}")
    print(f"🤖 AI API Concurrent Test ishga tushmoqda...")
    print(f"{'='*60}")
    print(f"📊 Concurrent requests: {concurrent_requests}")
    semaphore_status = '✅ Ishlatilmoqda (max 2)' if use_semaphore else '❌ O\'chirilgan (haqiqiy concurrent)'
    print(f"🔒 Semaphore: {semaphore_status}")
    print(f"⏰ Vaqt: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # AI API key olish (avval environment variable, keyin Config)
    api_key = os.environ.get('DEEPSEEK_API_KEY') or Config.DEEPSEEK_API_KEY
    
    if not api_key:
        print(f"❌ DEEPSEEK_API_KEY topilmadi!")
        print(f"   .env faylida DEEPSEEK_API_KEY=your_api_key qo'shing")
        print(f"   yoki environment variable orqali: export DEEPSEEK_API_KEY=your_api_key")
        return
    
    print(f"✅ AI API key topildi")
    print(f"🔑 API Key: {api_key[:20]}...{api_key[-10:] if len(api_key) > 30 else ''}")
    print(f"🌐 AI API URL: {Config.DEEPSEEK_API_URL}")
    print(f"⚠️  Eslatma: Bu haqiqiy API ga so'rovlar yuboriladi!")
    print(f"⚠️  Rate limiting yoki timeout bo'lishi mumkin")
    print(f"{'='*60}\n")
    
    result = LoadTestResult()
    result.start_time = datetime.now()
    
    print(f"⏳ {concurrent_requests} ta parallel AI API so'rovlari yuborilmoqda...")
    print(f"   (Bu biroz vaqt olishi mumkin...)\n")
    
    # Parallel tasklar yaratish
    tasks = []
    for i in range(concurrent_requests):
        task = make_ai_request(i, result, use_semaphore=use_semaphore)
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
    if stats.get('rate_limit_errors', 0) > 0:
        print(f"🚫 Rate limit xatoliklari: {stats.get('rate_limit_errors', 0)}")
    if stats.get('timeout_errors', 0) > 0:
        print(f"⏱️  Timeout xatoliklari: {stats.get('timeout_errors', 0)}")
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
    
    # Usage statistikasi
    if result.total_tokens > 0:
        print(f"\n💰 Token statistikasi:")
        print(f"   • Jami tokens: {result.total_tokens:,}")
        print(f"   • Prompt tokens: {result.total_prompt_tokens:,}")
        print(f"   • Completion tokens: {result.total_completion_tokens:,}")
        print(f"   • O'rtacha tokens/so'rov: {result.total_tokens / result.successful:.1f}")
    
    if result.errors and stats.get('rate_limit_errors', 0) + stats.get('timeout_errors', 0) < len(result.errors):
        print(f"\n❌ Boshqa xatoliklar ({len(result.errors) - stats.get('rate_limit_errors', 0) - stats.get('timeout_errors', 0)} ta):")
        error_counts = {}
        for error in result.errors:
            if "rate limit" not in error.lower() and "timeout" not in error.lower():
                error_type = error.split(':')[0] if ':' in error else error
                error_counts[error_type] = error_counts.get(error_type, 0) + 1
        
        for error_type, count in list(error_counts.items())[:5]:
            print(f"   • {error_type}: {count} marta")
    
    print(f"\n{'='*60}")
    print(f"💡 Xulosa:")
    if stats.get('success_rate', 0) >= 90:
        print(f"   ✅ AI API yaxshi ishlayapti - {stats.get('success_rate', 0):.1f}% muvaffaqiyat")
    elif stats.get('success_rate', 0) >= 70:
        print(f"   ⚠️  AI API o'rtacha ishlayapti - {stats.get('success_rate', 0):.1f}% muvaffaqiyat")
        print(f"   💡 Rate limiting yoki timeout muammolari bo'lishi mumkin")
    else:
        print(f"   ❌ AI API muammoli - {stats.get('success_rate', 0):.1f}% muvaffaqiyat")
        print(f"   💡 Rate limiting yoki API key muammosi bo'lishi mumkin")
    
    if stats.get('rate_limit_errors', 0) > 0:
        print(f"   ⚠️  Rate limiting: {stats.get('rate_limit_errors', 0)} ta so'rov bloklandi")
        print(f"   💡 Semaphore ishlatish yoki so'rovlar sonini kamaytirish kerak")
    
    print(f"{'='*60}\n")
    
    return result


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='AI API Concurrent Test')
    parser.add_argument('--requests', type=int, default=100, help='Concurrent requests soni (default: 100)')
    parser.add_argument('--semaphore', action='store_true', help='Semaphore ishlatish (botning default xatti-harakati)')
    
    args = parser.parse_args()
    
    print(f"⚠️  Eslatma: Bu haqiqiy AI API ga so'rovlar yuboradi!")
    print(f"⚠️  Rate limiting yoki API limitlariga duch kelishingiz mumkin!")
    print(f"⚠️  Davom etishni xohlaysizmi? (y/n): ", end='', flush=True)
    
    # Auto-confirm for testing (comment out for interactive)
    try:
        confirm = input().strip().lower()
    except:
        confirm = 'y'  # Fallback for non-interactive mode
    
    if confirm != 'y':
        print("❌ Test bekor qilindi.")
        sys.exit(0)
    
    asyncio.run(run_ai_api_concurrent_test(args.requests, use_semaphore=args.semaphore))
