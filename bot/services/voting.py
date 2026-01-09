"""Voting service - quiz boshlash va to'xtatish uchun voting"""
import logging
import asyncio
import time
from typing import Dict, Optional
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from bot.config import Config

logger = logging.getLogger(__name__)

# Voting sozlamalari
VOTING_ENABLED = Config.VOTING_ENABLED
VOTING_MIN_VOTES_TO_START = Config.VOTING_MIN_VOTES_TO_START
VOTING_MIN_VOTES_TO_STOP = Config.VOTING_MIN_VOTES_TO_STOP
VOTING_TIMEOUT_SECONDS = Config.VOTING_TIMEOUT_SECONDS


async def create_start_voting(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    quiz_id: str,
    time_seconds: int,
    user_id: int
) -> Optional[str]:
    """Quiz boshlash uchun voting yaratish
    
    Returns:
        poll_id yoki None
    """
    if not VOTING_ENABLED:
        return None
    
    try:
        quiz = context.bot_data.get('quizzes', {}).get(quiz_id)
        if not quiz:
            from bot.models import storage
            quiz = storage.get_quiz(quiz_id)
        
        title = quiz.get('title', 'Quiz') if quiz else 'Quiz'
        question = f"🚀 Quizni boshlash?\n\n📝 {title}\n\n⏱ Vaqt: {time_seconds}s har bir savol uchun\n\n✅ {VOTING_MIN_VOTES_TO_START} ta ovoz kerak"
        
        poll = await context.bot.send_poll(
            chat_id=chat_id,
            question=question,
            options=["✅ Ha", "❌ Yo'q"],
            is_anonymous=False,
            allows_multiple_answers=False,
            open_period=VOTING_TIMEOUT_SECONDS
        )
        
        poll_id = poll.poll.id
        
        # Voting ma'lumotlarini saqlash
        if 'votings' not in context.bot_data:
            context.bot_data['votings'] = {}
        
        context.bot_data['votings'][poll_id] = {
            'type': 'start',
            'quiz_id': quiz_id,
            'chat_id': chat_id,
            'user_id': user_id,
            'time_seconds': time_seconds,
            'min_votes': VOTING_MIN_VOTES_TO_START,
            'votes': {'yes': 0, 'no': 0},
            'voters_list': [],
            'message_id': poll.message_id
        }
        
        logger.info(f"Voting yaratildi: poll_id={poll_id}, type=start, quiz_id={quiz_id}, chat_id={chat_id}")
        return poll_id
    except Exception as e:
        logger.error(f"Voting yaratishda xatolik: {e}", exc_info=True)
        return None


async def create_stop_voting(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int
) -> Optional[str]:
    """Quizni to'xtatish uchun voting yaratish
    
    Returns:
        poll_id yoki None
    """
    if not VOTING_ENABLED:
        return None
    
    try:
        question = f"🛑 Quizni to'xtatish?\n\n✅ {VOTING_MIN_VOTES_TO_STOP} ta ovoz kerak"
        
        poll = await context.bot.send_poll(
            chat_id=chat_id,
            question=question,
            options=["✅ Ha", "❌ Yo'q"],
            is_anonymous=False,
            allows_multiple_answers=False,
            open_period=VOTING_TIMEOUT_SECONDS
        )
        
        poll_id = poll.poll.id
        
        # Voting ma'lumotlarini saqlash
        if 'votings' not in context.bot_data:
            context.bot_data['votings'] = {}
        
        context.bot_data['votings'][poll_id] = {
            'type': 'stop',
            'chat_id': chat_id,
            'user_id': user_id,
            'min_votes': VOTING_MIN_VOTES_TO_STOP,
            'votes': {'yes': 0, 'no': 0},
            'voters_list': [],
            'message_id': poll.message_id
        }
        
        logger.info(f"Voting yaratildi: poll_id={poll_id}, type=stop, chat_id={chat_id}")
        return poll_id
    except Exception as e:
        logger.error(f"Voting yaratishda xatolik: {e}", exc_info=True)
        return None


async def handle_voting_answer(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """Voting javobini qayta ishlash
    
    Returns:
        True agar voting yakunlangan bo'lsa
    """
    if not update.poll_answer:
        return False
    
    poll_answer = update.poll_answer
    poll_id = poll_answer.poll_id
    user_id = poll_answer.user.id
    option_ids = poll_answer.option_ids
    
    if 'votings' not in context.bot_data or poll_id not in context.bot_data['votings']:
        return False
    
    voting = context.bot_data['votings'][poll_id]
    
    # Agar foydalanuvchi allaqachon ovoz bergan bo'lsa, e'tiborsiz qoldiramiz
    # voters set'ni list'ga o'girish (pickle uchun)
    if 'voters_list' not in voting:
        if 'voters' in voting:
            voting['voters_list'] = list(voting.get('voters', set()))
            voting.pop('voters', None)
        else:
            voting['voters_list'] = []
    
    if user_id in voting['voters_list']:
        return False
    
    # Ovoz qo'shish
    if option_ids:
        option_id = option_ids[0]
        if option_id == 0:  # "✅ Ha"
            voting['votes']['yes'] += 1
        elif option_id == 1:  # "❌ Yo'q"
            voting['votes']['no'] += 1
    
    voting['voters_list'].append(user_id)
    
    yes_votes = voting['votes']['yes']
    min_votes = voting['min_votes']
    
    logger.info(f"Voting javob: poll_id={poll_id}, user_id={user_id}, yes={yes_votes}/{min_votes}")
    
    # Voting natijasini tekshirish
    if yes_votes >= min_votes:
        # Voting muvaffaqiyatli
        voting_type = voting['type']
        chat_id = voting['chat_id']
        
        try:
            if voting_type == 'start':
                # Quizni boshlash
                quiz_id = voting['quiz_id']
                time_seconds = voting['time_seconds']
                user_id = voting['user_id']
                
                # Quiz boshlashdan oldin stuck sessionlarni tozalash
                from bot.services.quiz_service import advance_due_sessions
                await advance_due_sessions(context)
                
                from bot.services.quiz_service import start_quiz_session
                
                # Fake message yaratish
                class FakeMessage:
                    def __init__(self, chat_id, message_id):
                        self.chat_id = chat_id
                        self.message_id = message_id
                        self.chat = type('Chat', (), {'id': chat_id, 'type': 'supergroup'})()

                fake_message = FakeMessage(chat_id, voting['message_id'])
                
                try:
                    # force_start=True - voting orqali quiz boshlashda aktiv sessionlarni tozalash
                    await start_quiz_session(fake_message, context, quiz_id, chat_id, user_id, time_seconds, force_start=True)
                    logger.info(f"Voting orqali quiz boshlandi: quiz_id={quiz_id}, chat_id={chat_id}, user_id={user_id}")
                    
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"✅ Voting muvaffaqiyatli! {yes_votes} ta ovoz bilan quiz boshlanmoqda...",
                        reply_to_message_id=voting['message_id']
                    )
                except Exception as e:
                    logger.error(f"Voting orqali quiz boshlashda xatolik: {e}", exc_info=True)
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"❌ Quiz boshlashda xatolik: {str(e)[:100]}\n\nIltimos, qayta urinib ko'ring.",
                        reply_to_message_id=voting['message_id']
                    )
                    # Voting ni o'chirmasdan qoldiramiz, chunki xatolik bo'ldi
                    return True
                
            elif voting_type == 'stop':
                # Quizni to'xtatish
                from bot.services.quiz_service import advance_due_sessions
                await advance_due_sessions(context)
                
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
                
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"✅ Voting muvaffaqiyatli! {yes_votes} ta ovoz bilan {stopped} ta quiz to'xtatildi.",
                    reply_to_message_id=voting['message_id']
                )
            
            # Voting ni o'chirish
            context.bot_data['votings'].pop(poll_id, None)
            return True
            
        except Exception as e:
            logger.error(f"Voting natijasini qayta ishlashda xatolik: {e}", exc_info=True)
    
    return False

