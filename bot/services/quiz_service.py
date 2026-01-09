"""Quiz session va poll management"""
import asyncio
import time
import logging
from typing import Optional
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.config import Config
from bot.models import storage
from bot.utils.helpers import safe_send_markdown, _markdown_to_plain

logger = logging.getLogger(__name__)

# Safety limits
MAX_ACTIVE_QUIZZES_PER_GROUP = Config.MAX_ACTIVE_QUIZZES_PER_GROUP
MAX_ACTIVE_QUIZZES_PER_USER_IN_GROUP = Config.MAX_ACTIVE_QUIZZES_PER_USER_IN_GROUP
MAX_ACTIVE_QUIZZES_PER_USER_PRIVATE = Config.MAX_ACTIVE_QUIZZES_PER_USER_PRIVATE


async def start_quiz_session(message, context, quiz_id: str, chat_id: int, user_id: int, time_seconds: int, force_start: bool = False):
    """Quiz sessiyasini boshlash
    
    Args:
        force_start: Agar True bo'lsa, aktiv sessionlarni tozalab yangi quizni boshlaydi (voting uchun)
    """
    logger.info(f"start_quiz_session: quiz_id={quiz_id}, chat_id={chat_id}, user_id={user_id}, time={time_seconds}s, force_start={force_start}")
    
    quiz = storage.get_quiz(quiz_id)
    
    if not quiz:
        logger.warning(f"Quiz topilmadi: {quiz_id}")
        try:
            await message.reply_text("❌ Quiz topilmadi!")
        except AttributeError:
            await context.bot.send_message(chat_id=chat_id, text="❌ Quiz topilmadi!")
        return
    
    questions = quiz.get('questions', [])
    if not questions:
        logger.warning(f"Quizda savollar yo'q: {quiz_id}")
        try:
            await message.reply_text("❌ Quizda savollar yo'q!")
        except AttributeError:
            await context.bot.send_message(chat_id=chat_id, text="❌ Quizda savollar yo'q!")
        return
    
    session_key = f"quiz_{chat_id}_{user_id}_{quiz_id}"

    # Chat type
    try:
        chat_type = message.chat.type
        logger.info(f"Chat type from message: {chat_type}")
    except Exception:
        try:
            chat_obj = await context.bot.get_chat(chat_id)
            chat_type = chat_obj.type
            logger.info(f"Chat type from API: {chat_type}")
        except Exception as e:
            logger.warning(f"Chat type aniqlashda xatolik: {e}")
            chat_type = 'private'

    # GROUP allowlist check
    if chat_type in ['group', 'supergroup'] and (not storage.group_allows_quiz(chat_id, quiz_id)):
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "⛔️ Bu quiz ushbu guruhda yoqilmagan.\n\n"
                "✅ Guruh admini: `/allowquiz <quiz_id>`\n"
                "📋 Ruxsat berilganlar: /allowedquizzes"
            ),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Private quiz check (faqat guruhlar uchun)
    if chat_type in ['group', 'supergroup']:
        if not storage.is_quiz_allowed_in_group(quiz_id, chat_id):
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    "🔒 **Bu quiz private!**\n\n"
                    "Bu quiz faqat ruxsat berilgan guruhlarda ishlatiladi.\n"
                    "Quiz yaratuvchisi yoki admin quiz sozlamalaridan guruh qo'shishi kerak."
                ),
                parse_mode=ParseMode.MARKDOWN
            )
            return
    # Shaxsiy chatda private quiz ham ishlaydi

    # PRIVATE CHAT LIMITS
    if chat_type == 'private':
        sessions = context.bot_data.setdefault('sessions', {})
        # Check per-user limit in private chat
        active_for_user_private = 0
        prefix = f"quiz_{chat_id}_{user_id}_"
        for k, s in sessions.items():
            if k.startswith(prefix) and s.get('is_active', False):
                active_for_user_private += 1
        if active_for_user_private >= MAX_ACTIVE_QUIZZES_PER_USER_PRIVATE:
            try:
                await message.reply_text(
                    f"⛔️ Sizda allaqachon {MAX_ACTIVE_QUIZZES_PER_USER_PRIVATE} ta aktiv quiz bor.\n"
                    "Tugagandan keyin yangisini boshlang yoki /finishquiz bilan yakunlang.",
                )
            except AttributeError:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"⛔️ Sizda allaqachon {MAX_ACTIVE_QUIZZES_PER_USER_PRIVATE} ta aktiv quiz bor.\n"
                         "Tugagandan keyin yangisini boshlang yoki /finishquiz bilan yakunlang.",
                )
            return

    # GROUP CONCURRENCY LIMITS
    if chat_type in ['group', 'supergroup']:
        # Chempionat tekshiruvi - agar aktiv chempionat bo'lsa, boshqa quizlar o'tkazilmaydi
        championship_key = f"championship_{chat_id}"
        if 'championships' in context.bot_data:
            championship = context.bot_data['championships'].get(championship_key)
            if championship and championship.get('is_active', False):
                # Agar bu chempionat quiz'i bo'lsa, ruxsat beramiz
                if championship.get('quiz_id') != quiz_id:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=(
                            "⛔️ **Chempionat davom etmoqda!**\n\n"
                            "Chempionat vaqtida guruhda boshqa quizlar o'tkazilmaydi.\n"
                            "Chempionat tugagandan keyin yangi quizni boshlang."
                        ),
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return
        
        sessions = context.bot_data.setdefault('sessions', {})
        group_locks = context.bot_data.setdefault('group_locks', {})
        
        # Agar force_start=True bo'lsa, aktiv sessionlarni tozalash va natijalarni e'lon qilish
        if force_start:
            logger.info(f"force_start=True: aktiv sessionlarni tozalash, chat_id={chat_id}")
            
            # Stuck sessionlarni tozalash
            await advance_due_sessions(context)
            
            # Guruhdagi barcha aktiv sessionlarni tozalash va natijalarni e'lon qilish
            group_prefix = f"quiz_{chat_id}_"
            cleaned = 0
            for k, s in list(sessions.items()):
                if k.startswith(group_prefix) and s.get('is_active', False):
                    logger.info(f"force_start: aktiv session tozalanmoqda va natijalar e'lon qilinmoqda: {k}")
                    
                    # Natijalarni e'lon qilish
                    old_quiz_id = s.get('quiz_id')
                    old_user_id = s.get('user_id')
                    if old_quiz_id and old_user_id:
                        try:
                            await show_quiz_results(None, context, old_quiz_id, chat_id, old_user_id)
                            logger.info(f"force_start: natijalar e'lon qilindi: quiz_id={old_quiz_id}")
                        except Exception as e:
                            logger.error(f"force_start: natijalarni e'lon qilishda xatolik: {e}")
                    
                    s['is_active'] = False
                    cleaned += 1
            
            # Lock bo'shatish
            if chat_id in group_locks:
                logger.info(f"force_start: lock tozalanmoqda: chat_id={chat_id}")
                group_locks.pop(chat_id)
            
            if cleaned > 0:
                logger.info(f"force_start: {cleaned} ta aktiv session tozalandi va natijalar e'lon qilindi, chat_id={chat_id}")
        
        # Check active quizzes in group
        active_in_group = 0
        group_prefix = f"quiz_{chat_id}_"
        for k, s in sessions.items():
            if k.startswith(group_prefix) and s.get('is_active', False):
                active_in_group += 1
        if active_in_group >= MAX_ACTIVE_QUIZZES_PER_GROUP:
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"⛔️ Guruhda allaqachon {MAX_ACTIVE_QUIZZES_PER_GROUP} ta aktiv quiz bor.\n"
                    "Tugagandan keyin yangisini boshlang (yoki admin /stopquiz)."
                )
            )
            return

        # Check per-user limit
        active_for_user = 0
        prefix = f"quiz_{chat_id}_{user_id}_"
        for k, s in sessions.items():
            if k.startswith(prefix) and s.get('is_active', False):
                active_for_user += 1
        if active_for_user >= MAX_ACTIVE_QUIZZES_PER_USER_IN_GROUP:
            await context.bot.send_message(
                chat_id=chat_id,
                text="⛔️ Sizda guruhda allaqachon aktiv quiz bor. Tugagandan keyin yangisini boshlang.",
            )
            return
    
    # Create session
    if 'sessions' not in context.bot_data:
        context.bot_data['sessions'] = {}
    
    context.bot_data['sessions'][session_key] = {
        'quiz_id': quiz_id,
        'current_question': 0,
        'answers': {},
        'time_seconds': time_seconds,
        'started_at': time.time(),
        'is_active': True,
        'chat_id': chat_id,
        'user_id': user_id,
        'chat_type': chat_type,
        'last_question_sent_at': None,
        'last_question_index': None,
        'next_due_at': None
    }
    
    # Backward compatibility
    if context.chat_data is not None:
        context.chat_data[session_key] = context.bot_data['sessions'][session_key]

    # Set group lock
    if chat_type in ['group', 'supergroup']:
        group_locks = context.bot_data.setdefault('group_locks', {})
        group_locks[chat_id] = session_key
    
    title = quiz.get('title', 'Quiz')
    time_text = f"{time_seconds}s" if time_seconds < 60 else f"{time_seconds//60}min"
    
    start_text = (
        f"🎯 **{title}** boshlanmoqda!\n\n"
        f"📋 Savollar: {len(questions)}\n"
        f"⏱ Vaqt: {time_text} har bir savol uchun\n\n"
        f"Birinchi savol kelmoqda..."
    )
    
    try:
        await message.reply_text(start_text, parse_mode=ParseMode.MARKDOWN)
    except AttributeError:
        # FakeMessage uchun
        await context.bot.send_message(
            chat_id=chat_id,
            text=start_text,
            parse_mode=ParseMode.MARKDOWN
        )
    
    await asyncio.sleep(2)
    await send_quiz_question(message, context, quiz_id, chat_id, user_id, 0)


async def send_quiz_question(message, context, quiz_id: str, chat_id: int, user_id: int, question_index: int):
    """Savolni yuborish"""
    quiz = storage.get_quiz(quiz_id)
    
    if not quiz:
        logger.warning(f"Quiz {quiz_id} topilmadi")
        return
    
    questions = quiz.get('questions', [])
    session_key = f"quiz_{chat_id}_{user_id}_{quiz_id}"
    
    # Session check
    if 'sessions' not in context.bot_data or session_key not in context.bot_data['sessions']:
        logger.warning(f"Session {session_key} not found in bot_data")
        return
    
    if not context.bot_data['sessions'][session_key].get('is_active', False):
        logger.warning(f"Session {session_key} is not active")
        return
    
    # Agar pauzada bo'lsa, yangi savol yubormaslik
    if context.bot_data['sessions'][session_key].get('is_paused', False):
        logger.info(f"Session {session_key} is paused, not sending question")
        return
    
    # Get chat type from session
    chat_type = context.bot_data['sessions'][session_key].get('chat_type', 'private')
    
    if question_index >= len(questions):
        # Chempionat tekshiruvi
        from bot.services.championship import handle_championship_quiz_end
        is_championship = await handle_championship_quiz_end(context, chat_id, quiz_id)
        
        if not is_championship:
            # Oddiy quiz natijalarini ko'rsatish
            await show_quiz_results(message, context, quiz_id, chat_id, user_id)
        return
    
    q_data = questions[question_index]
    question_text = q_data.get('question', '')
    options = q_data.get('options', [])
    correct_answer = q_data.get('correct_answer')
    
    # Variantlarni shuffle qilish (aralashtirish)
    import random
    shuffle_mapping = None  # {new_index: original_index}
    if len(options) > 1:
        # To'g'ri javob indeksini saqlash
        original_correct = correct_answer
        # Indekslar ro'yxatini yaratish
        indices = list(range(len(options)))
        # Shuffle qilish
        random.shuffle(indices)
        # Variantlarni yangi tartibda qayta tartiblash
        shuffled_options = [options[i] for i in indices]
        # Shuffle mapping yaratish (new_index -> original_index)
        # Masalan: agar indices = [2, 0, 1] bo'lsa, demak:
        # new_index 0 -> original_index 2
        # new_index 1 -> original_index 0
        # new_index 2 -> original_index 1
        shuffle_mapping = {new_idx: orig_idx for new_idx, orig_idx in enumerate(indices)}
        # To'g'ri javob yangi indeksini topish
        if original_correct is not None and 0 <= original_correct < len(indices):
            correct_answer = indices.index(original_correct)
        options = shuffled_options
        
        # Shuffle mapping'ni session'da saqlash (user_answer yangi indeks, uni original indeksga o'girish uchun)
        if 'shuffle_mappings' not in context.bot_data['sessions'][session_key]:
            context.bot_data['sessions'][session_key]['shuffle_mappings'] = {}
        context.bot_data['sessions'][session_key]['shuffle_mappings'][question_index] = shuffle_mapping
    
    time_seconds = context.bot_data['sessions'][session_key].get('time_seconds', 30)
    
    if len(options) < 2:
        await send_quiz_question(message, context, quiz_id, chat_id, user_id, question_index + 1)
        return
    
    # Clean options (max 100 chars)
    cleaned_options = []
    for opt in options[:10]:
        if len(opt) > 100:
            cleaned_options.append(opt[:97] + "...")
        else:
            cleaned_options.append(opt)
    
    poll_question = f"❓ Savol {question_index + 1}/{len(questions)}\n\n{question_text}"
    
    if len(poll_question) > 300:
        poll_question = poll_question[:297] + "..."
    
    try:
        if correct_answer is not None and 0 <= correct_answer < len(cleaned_options):
            poll_message = await context.bot.send_poll(
                chat_id=chat_id,
                question=poll_question,
                options=cleaned_options,
                is_anonymous=False,
                type='quiz',
                correct_option_id=correct_answer,
                open_period=time_seconds
            )
        else:
            poll_message = await context.bot.send_poll(
                chat_id=chat_id,
                question=poll_question,
                options=cleaned_options,
                is_anonymous=False,
                allows_multiple_answers=False,
                open_period=time_seconds
            )
    except BadRequest as e:
        logger.error(f"❌ send_poll xatolik (BadRequest): {e} | chat_id={chat_id}, quiz_id={quiz_id}, q_index={question_index}, chat_type={chat_type}")
        # Guruhda poll yuborishda xatolik bo'lsa, foydalanuvchiga xabar beramiz
        if chat_type in ['group', 'supergroup']:
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ Poll yuborishda xatolik: {str(e)[:100]}\n\n"
                         "Ehtimol bot guruhda poll yuborish huquqiga ega emas.\n"
                         "Guruh sozlamalarida botga 'Post Messages' va 'Post Polls' huquqlarini bering."
                )
            except Exception:
                pass
        return
    except Exception as e:
        logger.error(f"❌ send_poll xatolik: {e} | chat_id={chat_id}, quiz_id={quiz_id}, q_index={question_index}, chat_type={chat_type}", exc_info=True)
        if chat_type in ['group', 'supergroup']:
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ Xatolik: {str(e)[:100]}"
                )
            except Exception:
                pass
        return
    
    # Save poll info (bu kod faqat muvaffaqiyatli yuborilgandan keyin ishlaydi)
    if 'polls' not in context.bot_data:
        context.bot_data['polls'] = {}
    
    context.bot_data['polls'][poll_message.poll.id] = {
        'quiz_id': quiz_id,
        'question_index': question_index,
        'user_id': user_id,
        'chat_id': chat_id,
        'explanation': q_data.get('explanation', ''),
        'session_key': session_key,
        'message_id': poll_message.message_id
    }

    # Update timing for restart resilience
    current_time = time.time()
    context.bot_data['sessions'][session_key]['last_question_sent_at'] = current_time
    context.bot_data['sessions'][session_key]['last_question_index'] = question_index
    context.bot_data['sessions'][session_key]['next_due_at'] = current_time + float(time_seconds) + 1.0
    
    # Har bir savol uchun vaqtni saqlash (userlar uchun)
    if 'question_times' not in context.bot_data['sessions'][session_key]:
        context.bot_data['sessions'][session_key]['question_times'] = {}
    if question_index not in context.bot_data['sessions'][session_key]['question_times']:
        context.bot_data['sessions'][session_key]['question_times'][question_index] = {}
    # Savol yuborilgan vaqtni saqlash
    context.bot_data['sessions'][session_key]['question_times'][question_index]['sent_at'] = current_time
    
    # Ketma-ket javob berilmagan savollar sonini kuzatish
    if 'consecutive_no_answers' not in context.bot_data['sessions'][session_key]:
        context.bot_data['sessions'][session_key]['consecutive_no_answers'] = 0
    if 'last_answered_question' not in context.bot_data['sessions'][session_key]:
        context.bot_data['sessions'][session_key]['last_answered_question'] = -1
    
    # Auto advance to next question
    async def auto_next():
        logger.info(f"auto_next started: waiting {time_seconds}s for question {question_index}")
        await asyncio.sleep(time_seconds)
        
        logger.info(f"auto_next woke up: checking session {session_key}")
        
        if 'sessions' not in context.bot_data or session_key not in context.bot_data['sessions']:
            logger.warning(f"auto_next: session {session_key} not found in bot_data")
            return
        
        if not context.bot_data['sessions'][session_key].get('is_active', False):
            logger.warning(f"auto_next: session {session_key} is not active")
            return
        
        current_q = context.bot_data['sessions'][session_key].get('current_question', 0)
        logger.info(f"auto_next: current_question={current_q}, expected={question_index}")
        
        # Javob berilganligini tekshirish
        last_answered = context.bot_data['sessions'][session_key].get('last_answered_question', -1)
        user_answers = context.bot_data['sessions'][session_key].get('user_answers', {})
        
        # Private chatda faqat starter javob berganligini tekshiramiz
        if chat_type == 'private':
            starter_answers = user_answers.get(user_id, {})
            has_answer = question_index in starter_answers
        else:
            # Guruhda hech bo'lmaganda bitta user javob berganligini tekshiramiz
            has_answer = any(question_index in answers for answers in user_answers.values())
        
        if not has_answer:
            # Javob berilmagan
            consecutive_no_answers = context.bot_data['sessions'][session_key].get('consecutive_no_answers', 0) + 1
            context.bot_data['sessions'][session_key]['consecutive_no_answers'] = consecutive_no_answers
            
            logger.info(f"auto_next: no answer for question {question_index}, consecutive={consecutive_no_answers}")
            
            # Birinchi marta javob berilmasa, ogohlantirish xabari yuborish
            if consecutive_no_answers == 1:
                warning_text = f"⚠️ **Ogohlantirish**\n\n"
                warning_text += f"❌ Savol {question_index + 1} ga javob berilmadi.\n\n"
                warning_text += f"📋 Agar keyingi savolga ham javob berilmasa, quiz to'xtatiladi."
                
                try:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=warning_text,
                        parse_mode=ParseMode.MARKDOWN
                    )
                    logger.info(f"auto_next: Ogohlantirish xabari yuborildi (question {question_index + 1})")
                except Exception as e:
                    logger.warning(f"auto_next: Ogohlantirish xabari yuborishda xatolik: {e}")
            
            # Agar ketma-ket 2 marta javob berilmasa, pauza qilish
            if consecutive_no_answers >= 2:
                logger.warning(f"auto_next: pausing quiz after {consecutive_no_answers} consecutive no answers (quiz_id={quiz_id}, chat_id={chat_id})")
                context.bot_data['sessions'][session_key]['is_paused'] = True
                context.bot_data['sessions'][session_key]['paused_at_question'] = question_index
                
                # Pauza xabari va davom etish tugmasi
                pause_text = "⏸️ **Quiz pauza qilindi**\n\n"
                pause_text += f"❌ Ketma-ket **{consecutive_no_answers}** marta javob berilmadi.\n\n"
                pause_text += "📋 Quiz to'xtatildi, lekin davom ettirish mumkin.\n\n"
                pause_text += "▶️ Davom etish uchun tugmani bosing:"
                
                keyboard = [[InlineKeyboardButton("▶️ Davom etish", callback_data=f"resume_{quiz_id}")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                # Bir necha marta urinib ko'rish
                message_sent = False
                for attempt in range(3):
                    try:
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=pause_text,
                            reply_markup=reply_markup,
                            parse_mode=ParseMode.MARKDOWN
                        )
                        message_sent = True
                        logger.info(f"auto_next: Pauza xabari muvaffaqiyatli yuborildi (attempt {attempt + 1})")
                        break
                    except Exception as e:
                        logger.warning(f"auto_next: Pauza xabari yuborishda xatolik (attempt {attempt + 1}): {e}")
                        if attempt < 2:
                            await asyncio.sleep(1)  # 1 soniya kutib, qayta urinib ko'rish
                
                if not message_sent:
                    logger.error(f"auto_next: CRITICAL - Pauza xabari yuborilmadi! Quiz to'xtatildi, lekin foydalanuvchiga bildirilmadi (chat_id={chat_id}, quiz_id={quiz_id})")
                    # Agar xabar yuborilmasa ham, quizni to'xtatish kerak (memory leak'ni oldini olish uchun)
                    # Lekin bu holatda foydalanuvchi quizni resume qilishi yoki yangi quiz boshlashi mumkin
                
                return
        else:
            # Javob berilgan, counter'ni reset qilish
            context.bot_data['sessions'][session_key]['consecutive_no_answers'] = 0
            context.bot_data['sessions'][session_key]['last_answered_question'] = question_index
        
        if current_q == question_index:
            logger.info(f"auto_next: moving to next question {question_index + 1}")
            context.bot_data['sessions'][session_key]['current_question'] = question_index + 1
            await send_quiz_question(message, context, quiz_id, chat_id, user_id, question_index + 1)
        else:
            logger.info(f"auto_next: question already changed to {current_q}, skipping")
    
    asyncio.create_task(auto_next())


async def show_quiz_results(message, context, quiz_id: str, chat_id: int, user_id: int):
    """Natijalarni ko'rsatish"""
    
    quiz = storage.get_quiz(quiz_id)
    
    if not quiz:
        try:
            await context.bot.send_message(chat_id=chat_id, text="❌ Quiz topilmadi!")
        except:
            pass
        return
    
    questions = quiz.get('questions', [])
    session_key = f"quiz_{chat_id}_{user_id}_{quiz_id}"
    total = len(questions)
    graded_total = sum(1 for q in questions if (isinstance(q, dict) and q.get('correct_answer') is not None))
    
    # Deactivate session and get answers
    user_answers_dict = {}
    if 'sessions' in context.bot_data and session_key in context.bot_data['sessions']:
        # Save answers before cleanup
        session_data = context.bot_data['sessions'][session_key]
        session_data['is_active'] = False
        session_data['finished_at'] = time.time()  # Finish vaqtini saqlash
        user_answers_dict = session_data.get('user_answers', {})
        if not user_answers_dict:
            answers = session_data.get('answers', {})
            if answers:
                user_answers_dict = {user_id: answers}
    
    logger.info(f"Calculating results: quiz_id={quiz_id}, total_questions={total}, users={list(user_answers_dict.keys())}")
    
    # Get chat type
    try:
        chat = await context.bot.get_chat(chat_id)
        chat_type = chat.type
    except:
        chat_type = 'private'
    
    # Announcement
    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text="📊 **Quiz yakunlandi!**\n\nNatijalar hisoblanyapti...",
            parse_mode=ParseMode.MARKDOWN
        )
        await asyncio.sleep(2)
    except:
        pass
    
    if chat_type in ['group', 'supergroup']:
        # Group results
        title = quiz.get('title', 'Quiz')
        result_text = f"🎉 **{title} - Yakuniy natijalar**\n\n"
        if graded_total != total:
            result_text += f"ℹ️ Baholanadigan savollar: **{graded_total}/{total}**\n\n"
        
        user_results = []
        session_data = context.bot_data.get('sessions', {}).get(session_key, {})
        question_times = session_data.get('question_times', {})
        
        for uid, answers in user_answers_dict.items():
            correct_count = 0
            # Shuffle mapping'larni olish
            shuffle_mappings = session_data.get('shuffle_mappings', {})
            
            # Vaqt ma'lumotlarini olish
            user_answer_times = {}
            
            for i, q_data in enumerate(questions):
                correct_answer = q_data.get('correct_answer')
                user_answer = answers.get(i)
                
                # Agar shuffle bo'lgan bo'lsa, user_answer'ni original indeksga o'girish
                if i in shuffle_mappings and user_answer is not None:
                    shuffle_mapping = shuffle_mappings[i]
                    # user_answer - bu yangi (shuffled) indeks
                    # Uni original indeksga o'girish kerak
                    if user_answer in shuffle_mapping:
                        user_answer = shuffle_mapping[user_answer]
                
                if correct_answer is not None and user_answer == correct_answer:
                    correct_count += 1
                
                # Vaqtni olish
                if i in question_times:
                    user_times = question_times[i].get('user_times', {})
                    if uid in user_times:
                        user_answer_times[i] = user_times[uid]
            
            score_total = graded_total
            percentage = (correct_count / score_total * 100) if score_total > 0 else 0
            
            storage.save_result(quiz_id, uid, chat_id, answers, correct_count, score_total, answer_times=user_answer_times)
            
            # Vaqt statistikasini hisoblash
            total_time = sum(user_answer_times.values()) if user_answer_times else 0
            avg_time = total_time / len(user_answer_times) if user_answer_times else 0
            
            user_results.append({
                'user_id': uid,
                'correct_count': correct_count,
                'total': score_total,
                'percentage': percentage,
                'total_time': total_time,
                'avg_time': avg_time
            })
            logger.info(f"User {uid}: {correct_count}/{score_total} ({percentage:.0f}%), avg_time={avg_time:.2f}s")
        
        # VIP userlar uchun maxsus tartiblash - VIP userlar birinchi o'rinda
        from bot.utils.helpers import is_vip_user
        user_results.sort(key=lambda x: (
            x['percentage'], 
            x['correct_count'],
            is_vip_user(x['user_id'])  # VIP userlar tie-breaker sifatida birinchi
        ), reverse=True)
        
        if user_results:
            result_text += "🏆 **Top 10 Ishtirokchilar:**\n\n"
            medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
            
            for i, result in enumerate(user_results[:10]):
                medal = medals[i] if i < len(medals) else f"{i+1}."
                try:
                    user = await context.bot.get_chat_member(chat_id, result['user_id'])
                    user_name = user.user.first_name if user.user else f"User {result['user_id']}"
                except:
                    user_name = f"User {result['user_id']}"
                
                # VIP user badge va maxsus format
                from bot.utils.helpers import is_vip_user
                is_vip = is_vip_user(result['user_id'])
                vip_badge = "⭐ " if is_vip else ""
                
                # Vaqt statistikasi
                avg_time = result.get('avg_time', 0)
                time_text = f" ⏱ {avg_time:.1f}s" if avg_time > 0 else ""
                
                # VIP userlar uchun maxsus format
                if is_vip:
                    result_text += f"{medal} {vip_badge}**{user_name}** ⭐: {result['correct_count']}/{result['total']} ({result['percentage']:.0f}%){time_text}\n"
                else:
                    result_text += f"{medal} {vip_badge}**{user_name}**: {result['correct_count']}/{result['total']} ({result['percentage']:.0f}%){time_text}\n"
        
        result_text += f"\n📊 Jami {len(user_results)} kishi ishtirok etdi"
        
        keyboard = [[InlineKeyboardButton("🔄 Qayta o'tkazish", callback_data=f"restart_{quiz_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Release group lock
        try:
            group_locks = context.bot_data.setdefault('group_locks', {})
            group_locks.pop(chat_id, None)
        except Exception:
            pass

        try:
            await safe_send_markdown(
                context=context,
                chat_id=chat_id,
                text=result_text,
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Natijani guruhga yuborishda xatolik: {e}", exc_info=True)
    else:
        # Private chat results
        answers = user_answers_dict.get(user_id, {})
        correct_count = 0
        
        # Shuffle mapping'larni olish
        session_data = context.bot_data.get('sessions', {}).get(session_key, {})
        shuffle_mappings = session_data.get('shuffle_mappings', {})
        question_times = session_data.get('question_times', {})
        
        # Vaqt ma'lumotlarini olish
        user_answer_times = {}
        
        for i, q_data in enumerate(questions):
            correct_answer = q_data.get('correct_answer')
            user_answer = answers.get(i)
            
            # Agar shuffle bo'lgan bo'lsa, user_answer'ni original indeksga o'girish
            if i in shuffle_mappings and user_answer is not None:
                shuffle_mapping = shuffle_mappings[i]
                # user_answer - bu yangi (shuffled) indeks
                # Uni original indeksga o'girish kerak
                if user_answer in shuffle_mapping:
                    user_answer = shuffle_mapping[user_answer]
            
            if correct_answer is not None and user_answer == correct_answer:
                correct_count += 1
            
            # Vaqtni olish
            if i in question_times:
                user_times = question_times[i].get('user_times', {})
                if user_id in user_times:
                    user_answer_times[i] = user_times[user_id]
        
        score_total = graded_total
        percentage = (correct_count / score_total * 100) if score_total > 0 else 0
        
        # Vaqt statistikasini hisoblash
        total_time = sum(user_answer_times.values()) if user_answer_times else 0
        avg_time = total_time / len(user_answer_times) if user_answer_times else 0
        min_time = min(user_answer_times.values()) if user_answer_times else None
        max_time = max(user_answer_times.values()) if user_answer_times else None
        
        if percentage >= 90:
            emoji = "🏆"
            grade = "A'lo!"
        elif percentage >= 70:
            emoji = "👍"
            grade = "Yaxshi!"
        elif percentage >= 50:
            emoji = "📚"
            grade = "O'rtacha"
        else:
            emoji = "💪"
            grade = "Yana harakat qiling"
        
        title = quiz.get('title', 'Quiz')
        result_text = f"{emoji} **{title} - Sizning natijangiz**\n\n"
        if graded_total != total:
            result_text += f"ℹ️ Baholanadigan savollar: **{graded_total}/{total}**\n"
        result_text += f"📊 To'g'ri javoblar: {correct_count}/{score_total}\n"
        result_text += f"📈 Foiz: {percentage:.0f}%\n"
        result_text += f"📝 Baho: {grade}\n"
        
        # Vaqt statistikasi
        if user_answer_times:
            result_text += f"\n⏱ **Vaqt statistikasi:**\n"
            result_text += f"• O'rtacha vaqt: **{avg_time:.1f}s**\n"
            if min_time is not None:
                result_text += f"• Eng tez javob: **{min_time:.1f}s**\n"
            if max_time is not None:
                result_text += f"• Eng sekin javob: **{max_time:.1f}s**\n"
            result_text += f"• Jami vaqt: **{total_time:.1f}s**\n"
        
        result_text += "\nQayta urinib ko'rmoqchimisiz?"
        
        keyboard = [[InlineKeyboardButton("🔄 Qayta", callback_data=f"restart_{quiz_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await context.bot.send_message(
            chat_id=chat_id,
            text=result_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
        try:
            storage.save_result(quiz_id, user_id, chat_id, answers, correct_count, score_total, answer_times=user_answer_times)
        except:
            pass


async def cleanup_inactive_sessions(context_or_app, max_age_seconds: int = 7200):
    """
    Inactive (yoki tugagan) sessionlarni to'liq tozalash.
    Memory leak'ni oldini olish uchun eski sessionlarni olib tashlaydi.
    
    Args:
        context_or_app: Bot context yoki Application object
        max_age_seconds: Maksimal yoshi (sekundlarda) - default 2 soat
    """
    try:
        # Context yoki Application object'ni tekshirish
        if hasattr(context_or_app, 'bot_data'):
            bot_data = context_or_app.bot_data
        elif hasattr(context_or_app, 'application') and hasattr(context_or_app.application, 'bot_data'):
            bot_data = context_or_app.application.bot_data
        else:
            logger.warning("cleanup_inactive_sessions: bot_data topilmadi")
            return
        
        sessions = bot_data.get('sessions', {})
        if not sessions:
            return
        
        now = time.time()
        group_locks = bot_data.setdefault('group_locks', {})
        polls = bot_data.get('polls', {})
        
        removed_sessions = 0
        removed_locks = 0
        
        # Inactive sessionlarni olib tashlash
        for session_key, sess in list(sessions.items()):
            # Faqat inactive sessionlarni tekshiramiz
            if sess.get('is_active', False):
                continue
            
            # Session yoshini tekshirish
            started_at = sess.get('started_at', 0)
            last_activity = sess.get('last_question_sent_at', started_at)
            
            # Agar session juda eski bo'lsa (max_age_seconds dan ko'p), olib tashlaymiz
            if started_at > 0 and now - last_activity > max_age_seconds:
                # Associated polls'larni ham tozalash
                session_polls = [poll_id for poll_id, poll_data in list(polls.items()) 
                               if poll_data.get('session_key') == session_key]
                for poll_id in session_polls:
                    polls.pop(poll_id, None)
                
                # Session'ni olib tashlash
                sessions.pop(session_key, None)
                removed_sessions += 1
                
                # Lock bo'shatish
                chat_id = sess.get('chat_id')
                if chat_id and chat_id in group_locks and group_locks[chat_id] == session_key:
                    group_locks.pop(chat_id)
                    removed_locks += 1
        
        if removed_sessions > 0:
            logger.info(f"cleanup_inactive_sessions: {removed_sessions} ta inactive session tozalandi, {removed_locks} ta lock olib tashlandi")
            
    except Exception as e:
        logger.error(f"cleanup_inactive_sessions error: {e}", exc_info=True)


async def advance_due_sessions(context):
    """
    Restartdan keyin ham quizlar "osilib qolmasligi" uchun:
    har kelgan update'da due bo'lgan sessionlarni keyingi savolga o'tkazib yuboramiz.
    Shuningdek, stuck sessionlarni tozalaydi.
    """
    try:
        # Avval inactive sessionlarni tozalash (memory leak'ni oldini olish uchun)
        await cleanup_inactive_sessions(context)
        
        sessions = context.bot_data.get('sessions', {})
        if not sessions:
            return
        now = time.time()
        group_locks = context.bot_data.setdefault('group_locks', {})

        checked = 0
        stuck_cleaned = 0
        max_check = 500  # Limit'ni 50 dan 500 ga oshirdik
        
        for session_key, sess in list(sessions.items()):
            if checked >= max_check:
                logger.warning(f"advance_due_sessions: {max_check} ta limit yetib keldi, qolgan sessionlar keyingi update'da tekshiriladi")
                break
            checked += 1

            if not sess.get('is_active', False):
                continue
            
            # Stuck sessionlarni tozalash - agar session juda eski bo'lsa (30 daqiqadan ko'p)
            started_at = sess.get('started_at', 0)
            if started_at > 0 and now - started_at > 1800:  # 30 daqiqa (3600 dan 1800 ga qisqartirdik)
                logger.warning(f"Stuck session topildi va tozalandi: {session_key} (started: {started_at}, age: {now - started_at:.0f}s)")
                sess['is_active'] = False
                stuck_cleaned += 1
                
                # Lock bo'shatish
                chat_id = sess.get('chat_id')
                if chat_id and chat_id in group_locks and group_locks[chat_id] == session_key:
                    logger.warning(f"Stuck lock tozalandi: chat_id={chat_id}")
                    group_locks.pop(chat_id)
                continue
            
            # Agar pauzada bo'lsa, davom etmaslik
            if sess.get('is_paused', False):
                continue
            
            due_at = sess.get('next_due_at')
            last_idx = sess.get('last_question_index')
            current_q = sess.get('current_question', 0)
            
            if due_at is None or last_idx is None:
                continue
            
            # Vaqt o'tgan bo'lsa va hali keyingi savolga o'tmagan bo'lsa
            if now >= float(due_at):
                # Agar current_question hali last_question_index ga teng bo'lsa, keyingi savolga o'tish kerak
                if current_q == last_idx:
                    quiz_id = sess.get('quiz_id')
                    chat_id = sess.get('chat_id')
                    user_id = sess.get('user_id')
                    if not quiz_id or not chat_id or user_id is None:
                        continue
                    
                    # Javob berilganligini tekshirish
                    user_answers = sess.get('user_answers', {})
                    chat_type = sess.get('chat_type', 'private')
                    
                    # Agar javob berilgan bo'lsa, keyingi savolga o'tish
                    has_answer = False
                    if chat_type == 'private':
                        starter_answers = user_answers.get(user_id, {})
                        has_answer = last_idx in starter_answers
                    else:
                        has_answer = any(last_idx in answers for answers in user_answers.values())
                    
                    if has_answer:
                        # Javob berilgan, keyingi savolga o'tish
                        next_idx = int(last_idx) + 1
                        sess['current_question'] = next_idx
                        sess['next_due_at'] = now + 10.0
                        sess['consecutive_no_answers'] = 0  # Reset counter
                        logger.info(f"advance_due_sessions: advancing {session_key} to q={next_idx} (answer received)")
                        await send_quiz_question(None, context, quiz_id, int(chat_id), int(user_id), next_idx)
                    else:
                        # Javob berilmagan, consecutive counter'ni oshirish
                        consecutive_no_answers = sess.get('consecutive_no_answers', 0) + 1
                        sess['consecutive_no_answers'] = consecutive_no_answers
                        
                        logger.info(f"advance_due_sessions: no answer for q={last_idx}, consecutive={consecutive_no_answers}")
                        
                        # Birinchi marta javob berilmasa, ogohlantirish xabari yuborish
                        if consecutive_no_answers == 1:
                            warning_text = f"⚠️ **Ogohlantirish**\n\n"
                            warning_text += f"❌ Savol {last_idx + 1} ga javob berilmadi.\n\n"
                            warning_text += f"📋 Agar keyingi savolga ham javob berilmasa, quiz to'xtatiladi."
                            
                            try:
                                await context.bot.send_message(
                                    chat_id=chat_id,
                                    text=warning_text,
                                    parse_mode=ParseMode.MARKDOWN
                                )
                                logger.info(f"advance_due_sessions: Ogohlantirish xabari yuborildi (question {last_idx + 1})")
                            except Exception as e:
                                logger.warning(f"advance_due_sessions: Ogohlantirish xabari yuborishda xatolik: {e}")
                        
                        # Agar ketma-ket 2 marta javob berilmasa, pauza qilish
                        if consecutive_no_answers >= 2:
                            logger.warning(f"advance_due_sessions: pausing quiz after {consecutive_no_answers} consecutive no answers (quiz_id={quiz_id}, chat_id={chat_id})")
                            sess['is_paused'] = True
                            sess['paused_at_question'] = last_idx
                            
                            # Pauza xabari va davom etish tugmasi
                            pause_text = "⏸️ **Quiz pauza qilindi**\n\n"
                            pause_text += f"❌ Ketma-ket **{consecutive_no_answers}** marta javob berilmadi.\n\n"
                            pause_text += "📋 Quiz to'xtatildi, lekin davom ettirish mumkin.\n\n"
                            pause_text += "▶️ Davom etish uchun tugmani bosing:"
                            
                            keyboard = [[InlineKeyboardButton("▶️ Davom etish", callback_data=f"resume_{quiz_id}")]]
                            reply_markup = InlineKeyboardMarkup(keyboard)
                            
                            # Bir necha marta urinib ko'rish
                            message_sent = False
                            for attempt in range(3):
                                try:
                                    await context.bot.send_message(
                                        chat_id=chat_id,
                                        text=pause_text,
                                        reply_markup=reply_markup,
                                        parse_mode=ParseMode.MARKDOWN
                                    )
                                    message_sent = True
                                    logger.info(f"advance_due_sessions: Pauza xabari muvaffaqiyatli yuborildi (attempt {attempt + 1})")
                                    break
                                except Exception as e:
                                    logger.warning(f"advance_due_sessions: Pauza xabari yuborishda xatolik (attempt {attempt + 1}): {e}")
                                    if attempt < 2:
                                        await asyncio.sleep(1)  # 1 soniya kutib, qayta urinib ko'rish
                            
                            if not message_sent:
                                logger.error(f"advance_due_sessions: CRITICAL - Pauza xabari yuborilmadi! Quiz to'xtatildi, lekin foydalanuvchiga bildirilmadi (chat_id={chat_id}, quiz_id={quiz_id})")
                        else:
                            # Hali 2 marta emas, keyingi savolga o'tish (lekin counter oshirilgan)
                            next_idx = int(last_idx) + 1
                            sess['current_question'] = next_idx
                            sess['next_due_at'] = now + 10.0
                            logger.info(f"advance_due_sessions: advancing {session_key} to q={next_idx} (no answer, but continuing)")
                            await send_quiz_question(None, context, quiz_id, int(chat_id), int(user_id), next_idx)
        
        if stuck_cleaned > 0:
            logger.info(f"advance_due_sessions: {stuck_cleaned} ta stuck session tozalandi")
            
    except Exception as e:
        logger.error(f"advance_due_sessions error: {e}", exc_info=True)

