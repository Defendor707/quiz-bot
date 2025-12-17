"""AI parser - DeepSeek integratsiyasi"""
import json
import re
import logging
import asyncio
from typing import Dict, List, Optional
import httpx

logger = logging.getLogger(__name__)


class AIParser:
    """DeepSeek AI orqali test savollarini tahlil qilish"""
    
    def __init__(self, api_key: str, api_url: str):
        self.api_key = api_key
        self.api_url = api_url
        self.semaphore: Optional[asyncio.Semaphore] = None
    
    def _get_semaphore(self, max_concurrent: int = 2) -> asyncio.Semaphore:
        """AI so'rovlari uchun semaphore"""
        if self.semaphore is None:
            self.semaphore = asyncio.Semaphore(max(1, max_concurrent))
        return self.semaphore
    
    @staticmethod
    def extract_json_dict(text: str) -> Optional[Dict]:
        """AI javobidan birinchi valid JSON dict'ni ajratib olish.
        
        Regex (greedy) ko'pincha 1-chi `{` dan oxirgi `}` gacha olib, JSON'ni buzib qo'yadi.
        Shu sabab `json.JSONDecoder().raw_decode()` orqali har bir `{` joyidan boshlab o'qib ko'ramiz.
        """
        if not text:
            return None

        raw = (text or "").strip()
        # Tezkor: agar to'liq JSON bo'lsa
        try:
            if raw.startswith("{") and raw.endswith("}"):
                obj = json.loads(raw)
                if isinstance(obj, dict):
                    return obj
        except Exception:
            pass

        decoder = json.JSONDecoder()
        for idx, ch in enumerate(text):
            if ch != "{":
                continue
            try:
                obj, _ = decoder.raw_decode(text[idx:])
                if isinstance(obj, dict):
                    return obj
            except Exception:
                continue
        return None
    
    async def precheck_has_questions(
        self, 
        text: str, 
        model: Optional[str] = None,
        max_concurrent: int = 2
    ) -> Dict:
        """Faylda test savollari borligini AI orqali tekshirish.
        
        Returns:
            {"has_questions": true/false, "reason": "..."}
        """
        try:
            prompt = f"""Quyidagi matnda test/quiz savollari mavjudmi?
Qoidalar:
- Faqat tekshiring, savollarni ajratmang.
- Agar savol + variantlar strukturasi ko'rinmasa, has_questions=false qiling.
- Variantlar A)/1)/~ bilan yoki raqamsiz ketma-ket qisqa qatorlar ko'rinishida bo'lishi mumkin.
- Javobni faqat JSON qaytaring: {{"has_questions": true/false, "reason": "..."}}.

Matn:
{text}
"""
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.api_key}'
            }
            data = {
                'model': (model or 'deepseek-chat'),
                'messages': [
                    {'role': 'system', 'content': 'Siz faqat tekshiruvchi. Faqat JSON qaytaring.'},
                    {'role': 'user', 'content': prompt}
                ],
                'temperature': 0.0,
                'max_tokens': 300
            }
            
            sem = self._get_semaphore(max_concurrent)
            await sem.acquire()
            try:
                async with httpx.AsyncClient(timeout=40.0) as client:
                    response = await client.post(self.api_url, headers=headers, json=data)
                    response.raise_for_status()
                    result = response.json()
                    ai_response = result.get('choices', [{}])[0].get('message', {}).get('content', '')
                    parsed = self.extract_json_dict(ai_response)
                    if not parsed:
                        return {"has_questions": False, "reason": "AI javobi JSON emas"}
                    return {
                        "has_questions": bool(parsed.get("has_questions", False)),
                        "reason": str(parsed.get("reason", "")).strip()[:300]
                    }
            finally:
                try:
                    sem.release()
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"AI precheck error: {e}")
            return {"has_questions": False, "reason": f"AI precheck xatolik: {str(e)}"}
    
    async def analyze_with_ai(
        self,
        text: str,
        progress_callback=None,
        strict_correct: bool = True,
        model: Optional[str] = None,
        max_concurrent: int = 2,
        timeout: int = 120
    ) -> Optional[Dict]:
        """AI orqali savollarni ajratish.
        
        Returns:
            {"title": "...", "questions": [...]}
        """
        try:
            if progress_callback:
                await progress_callback(30, "🤖 AI ga so'rov yuborilmoqda...")
            
            correct_rule = (
                "4) correct_answer har doim bo'lsin va 0..(options-1) oraliqda bo'lsin. Agar aniqlab bo'lmasa, questions ni bo'sh qaytaring."
                if strict_correct
                else
                "4) correct_answer imkon qadar belgilang. Agar aniqlab bo'lmasa, correct_answer=null qiling (ammo savolni baribir qaytaring)."
            )

            prompt = f"""Quyidagi matndan faqat ANIQ ko'rinib turgan test savollarini va javob variantlarini ajratib oling.
Muhim qoidalar:
1) Agar matnda test savollari yo'q bo'lsa yoki variantlar aniq bo'lmasa, {{"questions": []}} qaytaring.
2) Hech qachon taxmin qilmang, o'ylab topmang (hallucination qilmang).
3) Har bir savolda kamida 2 ta variant bo'lsin.
{correct_rule}
5) Variantlar ba'zan raqamsiz bo'ladi (A/B/1/2 belgilarsiz): savoldan keyingi ketma-ket qisqa qatorlarni variant deb oling (keyingi savol boshlanguncha yoki bo'sh satrgacha).
6) Variantlar ba'zan "~" bilan boshlanadi (misol: "~ variant"). Bunda "~" ni olib tashlab, variant matnini options ga yozing.
7) Quiz uchun qisqa nom (title) ham bering (2-5 so'z, 32 belgigacha).

Matn:
{text}

Javobni JSON formatida qaytaring:
{{
  "title": "Qisqa nom",
  "questions": [
    {{
      "question": "Savol matni",
      "options": ["Variant 1", "Variant 2", "Variant 3"],
      "correct_answer": 0,
      "explanation": "Tushuntirish"
    }}
  ]
}}

Faqat JSON qaytaring. JSON dan boshqa matn yozmang."""

            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.api_key}'
            }
            
            data = {
                'model': (model or 'deepseek-chat'),
                'messages': [
                    {'role': 'system', 'content': 'Siz test tahlilchisiz. Faqat JSON qaytaring.'},
                    {'role': 'user', 'content': prompt}
                ],
                'temperature': 0.0,
                'max_tokens': 8000
            }
            
            if progress_callback:
                await progress_callback(60, "⏳ AI tahlil qilmoqda...")
            
            sem = self._get_semaphore(max_concurrent)
            await sem.acquire()
            try:
                async with httpx.AsyncClient(timeout=float(timeout)) as client:
                    response = await client.post(self.api_url, headers=headers, json=data)
                    response.raise_for_status()

                    if progress_callback:
                        await progress_callback(90, "📊 Savollar qayta ishlanmoqda...")

                    result = response.json()
                    ai_response = result.get('choices', [{}])[0].get('message', {}).get('content', '')

                    parsed_data = self.extract_json_dict(ai_response)
                    if parsed_data:
                        title = (parsed_data.get('title') or '').strip()
                        questions = parsed_data.get('questions', [])

                        cleaned_questions = []
                        for q in questions:
                            if not isinstance(q, dict):
                                continue
                            raw_opts = q.get('options', [])
                            if not isinstance(raw_opts, list):
                                raw_opts = []
                            if 'question' in q and len(raw_opts) >= 2:
                                cleaned_questions.append({
                                    'question': str(q.get('question', '')).strip(),
                                    'options': [str(opt) for opt in raw_opts],
                                    'correct_answer': q.get('correct_answer'),
                                    'explanation': str(q.get('explanation', '')).strip()
                                })

                        if progress_callback:
                            await progress_callback(100, f"✅ {len(cleaned_questions)} ta savol topildi!")

                        return {"title": title[:64], "questions": cleaned_questions}

                return None
            finally:
                try:
                    sem.release()
                except Exception:
                    pass
                
        except Exception as e:
            logger.error(f"AI xatolik: {e}")
            return None
    
    async def pick_correct_answers(
        self,
        questions: List[Dict],
        model: Optional[str] = None,
        max_concurrent: int = 2
    ) -> Optional[List[int]]:
        """AI orqali savollarning to'g'ri javoblarini aniqlash.
        
        Args:
            questions: Savollar ro'yxati
            model: AI model nomi
            
        Returns:
            To'g'ri javoblar indekslari ro'yxati yoki None
        """
        if not questions:
            return None
        
        try:
            questions_str = json.dumps(questions, ensure_ascii=False, indent=2)
            prompt = f"""Quyidagi test savollarining to'g'ri javoblarini aniqlang.

Savollar:
{questions_str}

Har bir savol uchun to'g'ri javob variant indeksini (0-based) qaytaring.
Agar aniqlay olmasangiz, null qaytaring.

Javobni JSON formatida qaytaring: {{"answers": [0, 2, null, 1, ...]}}

Faqat JSON qaytaring."""

            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.api_key}'
            }
            
            data = {
                'model': (model or 'deepseek-chat'),
                'messages': [
                    {'role': 'system', 'content': 'Siz test ekspertisiz. Faqat JSON qaytaring.'},
                    {'role': 'user', 'content': prompt}
                ],
                'temperature': 0.0,
                'max_tokens': 1000
            }
            
            sem = self._get_semaphore(max_concurrent)
            await sem.acquire()
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.post(self.api_url, headers=headers, json=data)
                    response.raise_for_status()
                    result = response.json()
                    ai_response = result.get('choices', [{}])[0].get('message', {}).get('content', '')
                    
                    parsed = self.extract_json_dict(ai_response)
                    if parsed and 'answers' in parsed:
                        answers = parsed['answers']
                        if isinstance(answers, list):
                            return answers
                    return None
            finally:
                try:
                    sem.release()
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"pick_correct_answers error: {e}")
            return None

