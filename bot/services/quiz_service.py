"""Quiz session va poll management"""
import asyncio
import time
import logging
from typing import Optional
from telegram.constants import ParseMode
from telegram.error import BadRequest

from bot.config import Config
from bot.models import storage
from bot.utils.helpers import safe_send_markdown, _markdown_to_plain

logger = logging.getLogger(__name__)

# Safety limits
MAX_ACTIVE_QUIZZES_PER_GROUP = Config.MAX_ACTIVE_QUIZZES_PER_GROUP
MAX_ACTIVE_QUIZZES_PER_USER_IN_GROUP = Config.MAX_ACTIVE_QUIZZES_PER_USER_IN_GROUP


async def start_quiz_session(message, context, quiz_id: str, chat_id: int, user_id: int, time_seconds: int):
    """Quiz sessiyasini boshlash"""
    logger.info(f"start_quiz_session: quiz_id={quiz_id}, chat_id={chat_id}, user_id={user_id}, time={time_seconds}s")
    
    quiz = storage.get_quiz(quiz_id)
    
    if not quiz:
        logger.warning(f"Quiz topilmadi: {quiz_id}")
        await message.reply_text("❌ Quiz topilmadi!")
        return
    
    questions = quiz.get('questions', [])
    if not questions:
        logger.warning(f"Quizda savollar yo'q: {quiz_id}")
        await message.reply_text("❌ Quizda savollar yo'q!")
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

    # GROUP CONCURRENCY LIMITS
    if chat_type in ['group', 'supergroup']:
        sessions = context.bot_data.setdefault('sessions', {})
        
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
    
    await message.reply_text(
        f"🎯 **{title}** boshlanmoqda!\n\n"
        f"📋 Savollar: {len(questions)}\n"
        f"⏱ Vaqt: {time_text} har bir savol uchun\n\n"
        f"Birinchi savol kelmoqda...",
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
    
    # Get chat type from session
    chat_type = context.bot_data['sessions'][session_key].get('chat_type', 'private')
    
    if question_index >= len(questions):
        await show_quiz_results(message, context, quiz_id, chat_id, user_id)
        return
    
    q_data = questions[question_index]
    question_text = q_data.get('question', '')
    options = q_data.get('options', [])
    correct_answer = q_data.get('correct_answer')
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
    context.bot_data['sessions'][session_key]['last_question_sent_at'] = time.time()
    context.bot_data['sessions'][session_key]['last_question_index'] = question_index
    context.bot_data['sessions'][session_key]['next_due_at'] = time.time() + float(time_seconds) + 1.0
    
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
        
        if current_q == question_index:
            logger.info(f"auto_next: moving to next question {question_index + 1}")
            context.bot_data['sessions'][session_key]['current_question'] = question_index + 1
            await send_quiz_question(message, context, quiz_id, chat_id, user_id, question_index + 1)
        else:
            logger.info(f"auto_next: question already changed to {current_q}, skipping")
    
    asyncio.create_task(auto_next())


async def show_quiz_results(message, context, quiz_id: str, chat_id: int, user_id: int):
    """Natijalarni ko'rsatish"""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    
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
        context.bot_data['sessions'][session_key]['is_active'] = False
        user_answers_dict = context.bot_data['sessions'][session_key].get('user_answers', {})
        if not user_answers_dict:
            answers = context.bot_data['sessions'][session_key].get('answers', {})
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
        for uid, answers in user_answers_dict.items():
            correct_count = 0
            for i, q_data in enumerate(questions):
                correct_answer = q_data.get('correct_answer')
                user_answer = answers.get(i)
                if correct_answer is not None and user_answer == correct_answer:
                    correct_count += 1
            
            score_total = graded_total
            percentage = (correct_count / score_total * 100) if score_total > 0 else 0
            
            storage.save_result(quiz_id, uid, chat_id, answers, correct_count, score_total)
            
            user_results.append({
                'user_id': uid,
                'correct_count': correct_count,
                'total': score_total,
                'percentage': percentage
            })
            logger.info(f"User {uid}: {correct_count}/{score_total} ({percentage:.0f}%)")
        
        user_results.sort(key=lambda x: (x['percentage'], x['correct_count']), reverse=True)
        
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
                
                result_text += f"{medal} **{user_name}**: {result['correct_count']}/{result['total']} ({result['percentage']:.0f}%)\n"
        
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
        for i, q_data in enumerate(questions):
            correct_answer = q_data.get('correct_answer')
            user_answer = answers.get(i)
            if correct_answer is not None and user_answer == correct_answer:
                correct_count += 1
        
        score_total = graded_total
        percentage = (correct_count / score_total * 100) if score_total > 0 else 0
        
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
        result_text += f"📝 Baho: {grade}\n\n"
        result_text += "Qayta urinib ko'rmoqchimisiz?"
        
        keyboard = [[InlineKeyboardButton("🔄 Qayta", callback_data=f"restart_{quiz_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await context.bot.send_message(
            chat_id=chat_id,
            text=result_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
        try:
            storage.save_result(quiz_id, user_id, chat_id, answers, correct_count, score_total)
        except:
            pass


async def advance_due_sessions(context):
    """
    Restartdan keyin ham quizlar "osilib qolmasligi" uchun:
    har kelgan update'da due bo'lgan sessionlarni keyingi savolga o'tkazib yuboramiz.
    """
    try:
        sessions = context.bot_data.get('sessions', {})
        if not sessions:
            return
        now = time.time()

        checked = 0
        for session_key, sess in list(sessions.items()):
            if checked > 50:
                break
            checked += 1

            if not sess.get('is_active', False):
                continue
            due_at = sess.get('next_due_at')
            last_idx = sess.get('last_question_index')
            if due_at is None or last_idx is None:
                continue
            if now < float(due_at):
                continue

            current_q = sess.get('current_question', 0)
            if current_q != last_idx:
                continue

            quiz_id = sess.get('quiz_id')
            chat_id = sess.get('chat_id')
            user_id = sess.get('user_id')
            if not quiz_id or not chat_id or user_id is None:
                continue

            next_idx = int(last_idx) + 1
            sess['current_question'] = next_idx
            sess['next_due_at'] = now + 10.0
            logger.info(f"advance_due_sessions: advancing {session_key} to q={next_idx}")
            await send_quiz_question(None, context, quiz_id, int(chat_id), int(user_id), next_idx)
    except Exception as e:
        logger.error(f"advance_due_sessions error: {e}", exc_info=True)

