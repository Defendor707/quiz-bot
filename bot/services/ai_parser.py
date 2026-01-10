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
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.debug(f"Full JSON parse xatolik: {e}")
        except Exception as e:
            logger.debug(f"Full JSON parse kutilmagan xatolik: {e}")

        decoder = json.JSONDecoder()
        for idx, ch in enumerate(text):
            if ch != "{":
                continue
            try:
                obj, _ = decoder.raw_decode(text[idx:])
                if isinstance(obj, dict):
                    return obj
            except (json.JSONDecodeError, ValueError, TypeError):
                # JSON parsing xatolik - keyingi { pozitsiyasiga o'tish
                continue
            except Exception as e:
                logger.debug(f"JSON decode kutilmagan xatolik (pozitsiya {idx}): {e}")
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
                except (ValueError, RuntimeError) as e:
                    logger.debug(f"Semaphore release xatolik (precheck): {e}")
                except Exception as e:
                    logger.debug(f"Semaphore release kutilmagan xatolik (precheck): {e}")
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
        timeout: int = 120,
        cancel_check=None
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
                await progress_callback(40, "🤖 AI ga so'rov yuborilmoqda...")
            
            # Cancel tekshiruvi
            if cancel_check and cancel_check():
                return None
            
            sem = self._get_semaphore(max_concurrent)
            await sem.acquire()
            try:
                # Cancel tekshiruvi
                if cancel_check and cancel_check():
                    return None
                
                # AI so'rov yuborishdan oldin progress
                if progress_callback:
                    await progress_callback(50, "⏳ AI javob kutmoqda...")
                
                # Cancel tekshiruvi
                if cancel_check and cancel_check():
                    return None
                
                async with httpx.AsyncClient(timeout=float(timeout)) as client:
                    try:
                        response = await client.post(self.api_url, headers=headers, json=data)
                        response.raise_for_status()
                    except httpx.TimeoutException as e:
                        logger.error(f"AI timeout: {e}")
                        if progress_callback:
                            await progress_callback(50, "⚠️ AI javob kutish vaqti tugadi...")
                        return None
                    except httpx.HTTPStatusError as e:
                        logger.error(f"AI HTTP xatolik ({e.response.status_code}): {e.response.text[:200]}")
                        if progress_callback:
                            await progress_callback(50, f"⚠️ AI server xatolik ({e.response.status_code})...")
                        return None
                    except Exception as e:
                        logger.error(f"AI so'rov xatolik: {e}")
                        if progress_callback:
                            await progress_callback(50, "⚠️ AI so'rov xatolik...")
                        return None
                    
                    # Cancel tekshiruvi javobdan keyin
                    if cancel_check and cancel_check():
                        return None

                    if progress_callback:
                        await progress_callback(85, "📊 AI javobini qayta ishlanmoqda...")

                    try:
                        result = response.json()
                        ai_response = result.get('choices', [{}])[0].get('message', {}).get('content', '')
                        
                        # AI javob bo'sh bo'lsa
                        if not ai_response or not ai_response.strip():
                            logger.warning("AI javob bo'sh")
                            if progress_callback:
                                await progress_callback(50, "⚠️ AI javob bo'sh...")
                            return None
                    except Exception as e:
                        logger.error(f"AI javobni parse qilish xatolik: {e}")
                        if progress_callback:
                            await progress_callback(50, "⚠️ AI javobni parse qilish xatolik...")
                        return None

                    parsed_data = self.extract_json_dict(ai_response)
                    if not parsed_data:
                        # JSON parse qilinmadi, lekin AI javob bergan
                        logger.warning(f"AI javob JSON parse qilinmadi. Response uzunligi: {len(ai_response)}, preview: {ai_response[:200]}")
                        
                        # Yana bir bor urinish - ba'zida AI javob ichida JSON bor
                        if 'questions' in ai_response.lower() or 'question' in ai_response.lower():
                            # Ehtimol JSON ichida yoki code block ichida
                            # Code block ichidagi JSON ni topish
                            code_block_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', ai_response, re.DOTALL)
                            if code_block_match:
                                try:
                                    parsed_data = json.loads(code_block_match.group(1))
                                    logger.info("Code block ichidan JSON topildi")
                                except Exception as e:
                                    logger.debug(f"Code block JSON parse xatolik: {e}")
                            
                            # Agar hali ham topilmasa, regex bilan qidirish
                            if not parsed_data:
                                json_match = re.search(r'\{[^{}]*"questions"[^{}]*\[[^\]]*\][^{}]*\}', ai_response, re.DOTALL)
                                if json_match:
                                    try:
                                        parsed_data = json.loads(json_match.group(0))
                                        logger.info("Regex bilan JSON topildi")
                                    except Exception as e:
                                        logger.debug(f"Regex JSON parse xatolik: {e}")
                        
                        # Agar hali ham topilmasa, butun javobni JSON sifatida sinab ko'rish
                        if not parsed_data:
                            try:
                                # Butun javobni JSON sifatida sinab ko'rish
                                parsed_data = json.loads(ai_response)
                                logger.info("Butun javob JSON sifatida parse qilindi")
                            except (json.JSONDecodeError, ValueError, TypeError) as e:
                                logger.debug(f"Butun javobni JSON sifatida parse qilishda xatolik: {e}")
                                pass
                    
                    if parsed_data:
                        title = (parsed_data.get('title') or '').strip()
                        questions = parsed_data.get('questions', [])
                        
                        # Agar questions bo'sh bo'lsa yoki None bo'lsa
                        if not questions:
                            logger.warning(f"AI questions bo'sh. Parsed data: {parsed_data}")
                            return None

                        cleaned_questions = []
                        total_questions = len(questions)
                        for idx, q in enumerate(questions):
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
                                
                                # Real-time: har bir savol topilganda darhol progress yangilash
                                if progress_callback:
                                    # Cancel tekshiruvi
                                    if cancel_check and cancel_check():
                                        return None
                                    # Har bir savol topilganda darhol yangilash
                                    progress_percent = 40 + int((len(cleaned_questions) / max(1, total_questions)) * 40)
                                    await progress_callback(
                                        progress_percent,
                                        f"✅ {len(cleaned_questions)} ta savol topildi! ({len(cleaned_questions)}/{total_questions})"
                                    )
                                    # Event loop'ga boshqa task'larga imkoniyat berish
                                    await asyncio.sleep(0)

                        if progress_callback:
                            # Final: topilgan savollar sonini ko'rsatish
                            await progress_callback(100, f"✅ {len(cleaned_questions)} ta savol topildi!")

                        return {"title": title[:64], "questions": cleaned_questions}
                    
                    # Agar JSON parse qilinmasa, xatolik
                    if progress_callback:
                        await progress_callback(50, "⚠️ AI javobini qayta ishlashda muammo...")

                return None
            finally:
                try:
                    sem.release()
                except (ValueError, RuntimeError) as e:
                    logger.debug(f"Semaphore release xatolik (analyze_with_ai): {e}")
                except Exception as e:
                    logger.debug(f"Semaphore release kutilmagan xatolik (analyze_with_ai): {e}")
                
        except Exception as e:
            logger.error(f"AI xatolik: {e}")
            return None
    
    async def pick_correct_answers(
        self,
        questions: List[Dict],
        model: Optional[str] = None,
        max_concurrent: int = 2,
        detailed_prompt: bool = False,
        progress_callback=None,
        cancel_check=None
    ) -> Optional[List[int]]:
        """AI orqali savollarning to'g'ri javoblarini aniqlash.
        
        Args:
            questions: Savollar ro'yxati
            model: AI model nomi
            detailed_prompt: Agar True bo'lsa, har bir savolni aniqroq formada ko'rsatadi
            
        Returns:
            To'g'ri javoblar indekslari ro'yxati yoki None
        """
        if not questions:
            return None
        
        try:
            if detailed_prompt:
                # Har bir savolni aniqroq formada yozish
                questions_text = ""
                for idx, q in enumerate(questions):
                    question_text = q.get("question", "").strip()
                    options = q.get("options", [])
                    questions_text += f"\n{idx + 1}. Savol: {question_text}\n"
                    questions_text += "   Variantlar:\n"
                    for opt_idx, opt in enumerate(options):
                        opt_text = str(opt).strip() if opt else ""
                        # Maxsus belgilarni olib tashlash (variant matnini tozalash)
                        opt_clean = re.sub(r'^[~*\-•·▪▫]\s*', '', opt_text)
                        opt_clean = re.sub(r'^[A-Za-z][).:\-]\s*', '', opt_clean)
                        opt_clean = re.sub(r'^\d+[).:\-]\s*', '', opt_clean)
                        questions_text += f"   [{opt_idx}] {opt_clean}\n"
                
                prompt = f"""Quyidagi test savollarining to'g'ri javoblarini aniqlang.

MUHIM QOIDALAR:
1. Har bir savol uchun ENG TO'G'RI va ANIQ variantni tanlang
2. Variant indekslari 0 dan boshlanadi (0, 1, 2, 3, ...)
3. Maxsus belgilar (:, ?, 1, @, *, &, ~, -, • va boshqalar) javob tanlashga ta'sir qilmasin
4. Faqat variant matnini hisobga oling - belgilarni e'tiborsiz qoldiring
5. Agar savol aniq bo'lmasa yoki barcha variantlar teng darajada to'g'ri bo'lsa, eng birinchi variantni (0) tanlang
6. NULL qaytarmang - har doim aniq javob bering
7. Javobni aniq tekshiring - faqat variant matniga qarab, savol mazmuniga mos keladigan javobni tanlang
8. Agar savol shubhali yoki ikkilangan bo'lsa, "uncertain" ro'yxatiga qo'shing

Savollar va variantlar:
{questions_text}

Javobni JSON formatida qaytaring: {{"answers": [0, 2, 1, ...], "uncertain": [1, 3]}}
"uncertain" - shubhali yoki ikkilangan savollar indekslari (0-based).

Har bir savol uchun aniq va to'g'ri javob indeksini qaytaring. Faqat JSON qaytaring."""
            else:
                questions_str = json.dumps(questions, ensure_ascii=False, indent=2)
                prompt = f"""Quyidagi test savollarining to'g'ri javoblarini aniqlang.

MUHIM QOIDALAR:
1. Har bir savol uchun ENG TO'G'RI va ANIQ variantni tanlang
2. Variant indekslari 0 dan boshlanadi (0, 1, 2, 3, ...)
3. Maxsus belgilar (:, ?, 1, @, *, &, ~, -, • va boshqalar) javob tanlashga ta'sir qilmasin
4. Faqat variant matnini hisobga oling - belgilarni e'tiborsiz qoldiring
5. Agar savol aniq bo'lmasa yoki barcha variantlar teng darajada to'g'ri bo'lsa, eng birinchi variantni (0) tanlang
6. NULL qaytarmang - har doim aniq javob bering
7. Javobni aniq tekshiring - faqat variant matniga qarab, savol mazmuniga mos keladigan javobni tanlang
8. Agar savol shubhali yoki ikkilangan bo'lsa, "uncertain" ro'yxatiga qo'shing

Savollar:
{questions_str}

Javobni JSON formatida qaytaring: {{"answers": [0, 2, 1, ...], "uncertain": [1, 3]}}
"uncertain" - shubhali yoki ikkilangan savollar indekslari (0-based).

Har bir savol uchun aniq va to'g'ri javob indeksini qaytaring. Faqat JSON qaytaring."""

            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.api_key}'
            }
            
            data = {
                'model': (model or 'deepseek-chat'),
                'messages': [
                    {'role': 'system', 'content': 'Siz test ekspertisiz. Har bir savol uchun ENG TO\'G\'RI va ANIQ javobni tanlang. Faqat variant matniga qarab, savol mazmuniga mos keladigan javobni tanlang. Faqat JSON qaytaring. NULL qaytarmang.'},
                    {'role': 'user', 'content': prompt}
                ],
                'temperature': 0.0,  # Aniqlik uchun 0.0 ga qaytardik
                'max_tokens': max(1000, len(questions) * 50)  # Har bir savol uchun yetarli token
            }
            
            # Cancel tekshiruvi
            if cancel_check and cancel_check():
                return None
            
            sem = self._get_semaphore(max_concurrent)
            await sem.acquire()
            try:
                # Cancel tekshiruvi
                if cancel_check and cancel_check():
                    return None
                
                # Progress: AI javob kutmoqda
                if progress_callback:
                    await progress_callback(50, f"⏳ AI javob kutmoqda... ({len(questions)} ta savol)")
                
                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.post(self.api_url, headers=headers, json=data)
                    response.raise_for_status()
                    
                    # Cancel tekshiruvi javobdan keyin
                    if cancel_check and cancel_check():
                        return None
                    
                    # Progress: AI javobni qayta ishlanmoqda
                    if progress_callback:
                        await progress_callback(80, f"📊 AI javobni qayta ishlanmoqda...")
                    
                    result = response.json()
                    ai_response = result.get('choices', [{}])[0].get('message', {}).get('content', '')
                    
                    parsed = self.extract_json_dict(ai_response)
                    if parsed and 'answers' in parsed:
                        answers = parsed['answers']
                        uncertain_indices = parsed.get('uncertain', [])  # Shubhali savollar indekslari
                        
                        if isinstance(answers, list):
                            # Null qiymatlarni tekshirish va tozalash
                            cleaned_answers = []
                            for i, ans in enumerate(answers):
                                if ans is None:
                                    # Agar null bo'lsa, eng birinchi variantni tanlash (fallback)
                                    logger.warning(f"Savol {i+1} uchun null javob - fallback: 0")
                                    cleaned_answers.append(0)
                                elif isinstance(ans, int) and 0 <= ans < len(questions[i].get('options', [])):
                                    cleaned_answers.append(ans)
                                else:
                                    # Noto'g'ri indeks - fallback
                                    logger.warning(f"Savol {i+1} uchun noto'g'ri indeks {ans} - fallback: 0")
                                    cleaned_answers.append(0)
                            
                            # Agar javoblar soni savollar soniga mos kelmasa
                            if len(cleaned_answers) != len(questions):
                                logger.warning(f"Javoblar soni ({len(cleaned_answers)}) savollar soniga ({len(questions)}) mos kelmaydi")
                                # Yetishmayotgan javoblarni to'ldirish
                                while len(cleaned_answers) < len(questions):
                                    cleaned_answers.append(0)  # Fallback
                            
                            # Shubhali savollar indekslarini qaytarish (reasoner uchun)
                            result_dict = {
                                'answers': cleaned_answers[:len(questions)],
                                'uncertain': uncertain_indices if isinstance(uncertain_indices, list) else []
                            }
                            return result_dict
                    else:
                        # Agar answers list bo'lmasa, oddiy list sifatida qaytarish (backward compatibility)
                        return answers if isinstance(answers, list) else None
                    
                    # Agar JSON parse qilinmasa, yana bir bor urinish
                    logger.warning(f"pick_correct_answers: JSON parse qilinmadi. Response: {ai_response[:300]}")
                    return None
            finally:
                try:
                    sem.release()
                except (ValueError, RuntimeError) as e:
                    logger.debug(f"Semaphore release xatolik (pick_correct_answers): {e}")
                except Exception as e:
                    logger.debug(f"Semaphore release kutilmagan xatolik (pick_correct_answers): {e}")
        except Exception as e:
            logger.error(f"pick_correct_answers error: {e}")
            return None

