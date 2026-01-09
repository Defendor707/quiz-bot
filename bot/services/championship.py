"""Championship service - guruhda chempionat o'tkazish"""
import logging
import asyncio
import time
from typing import Dict, List, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from bot.config import Config
from bot.models import storage

logger = logging.getLogger(__name__)


async def start_championship(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    quiz_id: str,
    user_id: int,
    time_seconds: int = 30,
    start_time: Optional[float] = None
) -> bool:
    """Chempionatni boshlash (faqat bitta quiz)
    
    Args:
        context: Bot context
        chat_id: Guruh ID
        quiz_id: Quiz ID (faqat bitta)
        user_id: Boshlovchi user ID
        time_seconds: Har bir savol uchun vaqt
        start_time: Boshlanish vaqti (Unix timestamp) yoki None (hozir)
        
    Returns:
        True agar muvaffaqiyatli boshlangan bo'lsa
    """
    try:
        if not quiz_id:
            return False
        
        # Chempionat ma'lumotlarini saqlash
        championship_key = f"championship_{chat_id}"
        
        if 'championships' not in context.bot_data:
            context.bot_data['championships'] = {}
        
        # Agar start_time belgilangan bo'lsa, uni saqlaymiz
        if start_time is None:
            start_time = time.time()
        
        context.bot_data['championships'][championship_key] = {
            'quiz_id': quiz_id,  # Faqat bitta quiz
            'chat_id': chat_id,
            'user_id': user_id,
            'time_seconds': time_seconds,
            'scores': {},  # {user_id: {'total_correct': 0, 'total_questions': 0}}
            'is_active': True,
            'start_time': start_time,
            'scheduled': start_time > time.time()  # Kelajakda boshlanishi kerakmi
        }
        
        # Agar kelajakda boshlanishi kerak bo'lsa, scheduler qo'shamiz
        if start_time > time.time():
            delay = start_time - time.time()
            quiz = storage.get_quiz(quiz_id)
            title = quiz.get('title', 'Quiz') if quiz else 'Quiz'
            
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"🏆 **Chempionat rejalashtirildi!**\n\n"
                     f"📝 Quiz: {title}\n"
                     f"⏰ Boshlanish vaqti: <t:{int(start_time)}:F>\n"
                     f"⏱ Vaqt: {time_seconds}s har bir savol uchun\n\n"
                     f"⚠️ **Eslatma:** Chempionat vaqtida guruhda boshqa quizlar o'tkazilmaydi!",
                parse_mode=ParseMode.MARKDOWN
            )
            
            # Scheduler qo'shish
            async def scheduled_start():
                await asyncio.sleep(delay)
                await _actually_start_championship(context, chat_id, quiz_id, user_id, time_seconds)
            
            asyncio.create_task(scheduled_start())
            logger.info(f"Championship rejalashtirildi: chat_id={chat_id}, start_time={start_time}, delay={delay}s")
            return True
        else:
            # Hozir boshlash
            await _actually_start_championship(context, chat_id, quiz_id, user_id, time_seconds)
            return True
        
    except Exception as e:
        logger.error(f"Championship boshlashda xatolik: {e}", exc_info=True)
        return False


async def _actually_start_championship(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    quiz_id: str,
    user_id: int,
    time_seconds: int
):
    """Chempionatni haqiqatan boshlash"""
    try:
        from bot.services.quiz_service import start_quiz_session
        
        # Fake message yaratish
        class FakeMessage:
            def __init__(self, chat_id):
                self.chat_id = chat_id
                self.chat = type('Chat', (), {'id': chat_id, 'type': 'supergroup'})()
        
        fake_message = FakeMessage(chat_id)
        
        quiz = storage.get_quiz(quiz_id)
        title = quiz.get('title', 'Quiz') if quiz else 'Quiz'
        questions_count = len(quiz.get('questions', [])) if quiz else 0
        
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🏆 **Chempionat boshlanmoqda!**\n\n"
                 f"📝 Quiz: {title}\n"
                 f"📋 Savollar: {questions_count} ta\n"
                 f"⏱ Vaqt: {time_seconds}s har bir savol uchun\n\n"
                 f"⚠️ **Eslatma:** Chempionat vaqtida guruhda boshqa quizlar o'tkazilmaydi!\n\n"
                 f"Quiz boshlanmoqda...",
            parse_mode=ParseMode.MARKDOWN
        )
        
        await asyncio.sleep(2)
        await start_quiz_session(fake_message, context, quiz_id, chat_id, user_id, time_seconds)
        
        logger.info(f"Championship boshlandi: chat_id={chat_id}, quiz_id={quiz_id}")
        
    except Exception as e:
        logger.error(f"Championshipni boshlashda xatolik: {e}", exc_info=True)


async def handle_championship_quiz_end(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    quiz_id: str
) -> bool:
    """Chempionat quiz tugaganda natijalarni ko'rsatish (faqat bitta quiz)
    
    Returns:
        False (chunki faqat bitta quiz bor)
    """
    try:
        championship_key = f"championship_{chat_id}"
        
        if 'championships' not in context.bot_data:
            return False
        
        if championship_key not in context.bot_data['championships']:
            return False
        
        championship = context.bot_data['championships'][championship_key]
        
        if not championship.get('is_active', False):
            return False
        
        # Quiz natijalarini yig'ish
        quiz = storage.get_quiz(quiz_id)
        if not quiz:
            return False
        
        questions = quiz.get('questions', [])
        sessions = context.bot_data.get('sessions', {})
        
        # Barcha foydalanuvchilarning javoblarini yig'ish
        group_prefix = f"quiz_{chat_id}_"
        for session_key, session in sessions.items():
            if session_key.startswith(group_prefix) and session.get('quiz_id') == quiz_id:
                user_id_session = session.get('user_id')
                if not user_id_session:
                    continue
                
                # User javoblarini olish
                user_answers = session.get('user_answers', {})
                if not user_answers:
                    user_answers = {user_id_session: session.get('answers', {})}
                
                # Har bir foydalanuvchi uchun ball hisoblash
                for uid, answers in user_answers.items():
                    if uid not in championship['scores']:
                        championship['scores'][uid] = {
                            'total_correct': 0,
                            'total_questions': 0
                        }
                    
                    correct_count = 0
                    for i, q_data in enumerate(questions):
                        correct_answer = q_data.get('correct_answer')
                        user_answer = answers.get(i)
                        if correct_answer is not None and user_answer == correct_answer:
                            correct_count += 1
                    
                    championship['scores'][uid]['total_correct'] = correct_count
                    championship['scores'][uid]['total_questions'] = len([q for q in questions if q.get('correct_answer') is not None])
        
        # Chempionat yakunlandi (faqat bitta quiz)
        await show_championship_results(context, chat_id)
        return False
            
    except Exception as e:
        logger.error(f"Championship quiz tugaganda xatolik: {e}", exc_info=True)
        return False


async def show_championship_results(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int
):
    """Chempionat natijalarini ko'rsatish"""
    try:
        championship_key = f"championship_{chat_id}"
        
        if 'championships' not in context.bot_data:
            return
        
        if championship_key not in context.bot_data['championships']:
            return
        
        championship = context.bot_data['championships'][championship_key]
        championship['is_active'] = False
        
        scores = championship['scores']
        
        if not scores:
            await context.bot.send_message(
                chat_id=chat_id,
                text="🏆 **Chempionat yakunlandi!**\n\n"
                     "ℹ️ Hech kim ishtirok etmadi.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # Natijalarni hisoblash va tartiblash
        results = []
        for user_id, score_data in scores.items():
            total_correct = score_data['total_correct']
            total_questions = score_data['total_questions']
            
            percentage = (total_correct / total_questions * 100) if total_questions > 0 else 0
            
            results.append({
                'user_id': user_id,
                'total_correct': total_correct,
                'total_questions': total_questions,
                'percentage': percentage
            })
        
        # Tartiblash: foiz, keyin to'g'ri javoblar soni
        results.sort(key=lambda x: (x['percentage'], x['total_correct']), reverse=True)
        
        # Natijalarni formatlash
        quiz = storage.get_quiz(championship.get('quiz_id', ''))
        quiz_title = quiz.get('title', 'Quiz') if quiz else 'Quiz'
        
        result_text = "🏆 **Chempionat yakunlandi!**\n\n"
        result_text += f"📝 Quiz: {quiz_title}\n\n"
        result_text += "📊 **Yakuniy natijalar:**\n\n"
        
        medals = ["🥇", "🥈", "🥉"]
        for i, result in enumerate(results[:10]):  # Top 10
            medal = medals[i] if i < 3 else f"{i+1}."
            user_id = result['user_id']
            
            # Foydalanuvchi ma'lumotlarini olish
            try:
                user = await context.bot.get_chat_member(chat_id, user_id)
                user_name = user.user.first_name or f"User {user_id}"
            except:
                user_name = f"User {user_id}"
            
            result_text += f"{medal} **{user_name}**\n"
            result_text += f"   📊 {result['total_correct']}/{result['total_questions']} ({result['percentage']:.0f}%)\n\n"
        
        await context.bot.send_message(
            chat_id=chat_id,
            text=result_text,
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Chempionatni o'chirish
        context.bot_data['championships'].pop(championship_key, None)
        
    except Exception as e:
        logger.error(f"Championship natijalarini ko'rsatishda xatolik: {e}", exc_info=True)


async def stop_championship(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int
) -> bool:
    """Chempionatni to'xtatish
    
    Args:
        context: Bot context
        chat_id: Guruh ID
        
    Returns:
        True agar muvaffaqiyatli to'xtatilgan bo'lsa
    """
    try:
        championship_key = f"championship_{chat_id}"
        
        if 'championships' not in context.bot_data:
            return False
        
        if championship_key not in context.bot_data['championships']:
            return False
        
        championship = context.bot_data['championships'][championship_key]
        
        if not championship.get('is_active', False):
            return False
        
        # Chempionatni to'xtatish
        championship['is_active'] = False
        
        # Aktiv quizlarni to'xtatish
        sessions = context.bot_data.setdefault('sessions', {})
        group_locks = context.bot_data.setdefault('group_locks', {})
        
        stopped = 0
        
        # Lock orqali topish
        session_key = group_locks.get(chat_id)
        if session_key and session_key in sessions and sessions[session_key].get('is_active', False):
            sessions[session_key]['is_active'] = False
            stopped += 1
        
        # Barcha aktiv sessionlarni topish
        prefix = f"quiz_{chat_id}_"
        for k, s in list(sessions.items()):
            if k.startswith(prefix) and s.get('is_active', False):
                s['is_active'] = False
                stopped += 1
        
        # Lock bo'shatish
        if chat_id in group_locks:
            group_locks.pop(chat_id)
        
        # Chempionatni o'chirish
        context.bot_data['championships'].pop(championship_key, None)
        
        logger.info(f"Championship to'xtatildi: chat_id={chat_id}")
        return True
        
    except Exception as e:
        logger.error(f"Championship to'xtatishda xatolik: {e}", exc_info=True)
        return False


async def get_championship_status(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int
) -> Optional[Dict]:
    """Chempionat holatini olish
    
    Returns:
        Championship ma'lumotlari yoki None
    """
    try:
        championship_key = f"championship_{chat_id}"
        
        if 'championships' not in context.bot_data:
            return None
        
        if championship_key not in context.bot_data['championships']:
            return None
        
        championship = context.bot_data['championships'][championship_key]
        
        if not championship.get('is_active', False):
            return None
        
        return championship
        
    except Exception as e:
        logger.error(f"Championship holatini olishda xatolik: {e}", exc_info=True)
        return None

