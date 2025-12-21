"""Callback va poll handlerlar"""
import time
import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from bot.config import Config
from bot.models import storage
from bot.utils.helpers import (
    track_update, is_admin_user, is_sudo_user,
    safe_edit_text, TIME_OPTIONS
)
from bot.services.quiz_service import start_quiz_session, send_quiz_question, advance_due_sessions
from bot.handlers.admin import (
    show_admin_menu, _admin_gq_show_groups, _admin_gq_show_group_menu,
    _admin_gq_show_allowed_list, _admin_gq_show_pick_latest
)

logger = logging.getLogger(__name__)


async def poll_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Poll javobini qabul qilish"""
    try:
        if update.poll_answer and update.poll_answer.user:
            u = update.poll_answer.user
            storage.track_user(user_id=u.id, username=getattr(u, "username", None), first_name=getattr(u, "first_name", None), last_name=getattr(u, "last_name", None))
    except Exception:
        pass
    
    await advance_due_sessions(context)
    poll_answer = update.poll_answer
    user_id = poll_answer.user.id
    poll_id = poll_answer.poll_id
    selected_option = poll_answer.option_ids[0] if poll_answer.option_ids else None
    
    logger.info(f"Poll answer: user_id={user_id}, poll_id={poll_id}, selected={selected_option}")
    
    if 'polls' not in context.bot_data or poll_id not in context.bot_data['polls']:
        logger.warning(f"Poll {poll_id} not found in bot_data")
        return
    
    poll_info = context.bot_data['polls'][poll_id]
    quiz_id = poll_info['quiz_id']
    question_index = poll_info['question_index']
    chat_id = poll_info['chat_id']
    session_key = poll_info.get('session_key')
    
    logger.info(f"Poll info: quiz_id={quiz_id}, q_index={question_index}, session_key={session_key}, chat_id={chat_id}")
    
    if 'sessions' not in context.bot_data:
        context.bot_data['sessions'] = {}
    
    if session_key not in context.bot_data['sessions']:
        logger.warning(f"Session {session_key} not found in bot_data")
        return
    
    # Save answer
    if 'answers' not in context.bot_data['sessions'][session_key]:
        context.bot_data['sessions'][session_key]['answers'] = {}
    
    if 'user_answers' not in context.bot_data['sessions'][session_key]:
        context.bot_data['sessions'][session_key]['user_answers'] = {}
    
    if user_id not in context.bot_data['sessions'][session_key]['user_answers']:
        context.bot_data['sessions'][session_key]['user_answers'][user_id] = {}
    
    context.bot_data['sessions'][session_key]['user_answers'][user_id][question_index] = selected_option
    context.bot_data['sessions'][session_key]['answers'][question_index] = selected_option
    
    logger.info(f"Answer saved: user={user_id}, q_index={question_index}, selected={selected_option}")

    # Early advance for private chat
    try:
        starter_id = int(poll_info.get('user_id'))
    except Exception:
        starter_id = None

    sess = context.bot_data['sessions'].get(session_key, {})
    if starter_id is not None and user_id == starter_id and sess.get('is_active', False) and sess.get('chat_type') == 'private':
        current_q = sess.get('current_question', 0)
        if current_q == question_index:
            try:
                msg_id = poll_info.get('message_id')
                if msg_id:
                    await context.bot.stop_poll(chat_id=chat_id, message_id=int(msg_id))
            except Exception as e:
                logger.warning(f"stop_poll failed: {e}")

            next_idx = question_index + 1
            sess['current_question'] = next_idx
            sess['next_due_at'] = time.time() + 10.0
            logger.info(f"early_advance: starter answered, moving to q={next_idx} session={session_key}")
            await send_quiz_question(None, context, quiz_id, chat_id, starter_id, next_idx)


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback handler"""
    track_update(update)
    await advance_due_sessions(context)
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    
    # ADMIN PANEL
    if data.startswith("admin_"):
        if not is_admin_user(user_id):
            await query.answer("❌ Siz admin emassiz.", show_alert=True)
            return

        if query.message.chat.type in ['group', 'supergroup']:
            await query.answer("Admin panel faqat shaxsiy chatda.", show_alert=True)
            return

        if data == "admin_menu":
            await show_admin_menu(query, context, as_edit=True)
            return

        if data == "admin_group_quiz":
            await _admin_gq_show_groups(query.message, context)
            return

        if data.startswith("admin_gq_select_"):
            gid = int(data.replace("admin_gq_select_", ""))
            await _admin_gq_show_group_menu(query.message, context, gid)
            return

        if data.startswith("admin_gq_list_"):
            parts = data.replace("admin_gq_list_", "").split("_")
            gid = int(parts[0])
            page = int(parts[1]) if len(parts) > 1 else 0
            await _admin_gq_show_allowed_list(query.message, context, gid, page)
            return

        if data.startswith("admin_gq_pick_"):
            parts = data.replace("admin_gq_pick_", "").split("_")
            gid = int(parts[0])
            page = int(parts[1]) if len(parts) > 1 else 0
            await _admin_gq_show_pick_latest(query.message, context, gid, page)
            return

        if data.startswith("admin_gq_addid_"):
            parts = data.replace("admin_gq_addid_", "").split("_", 1)
            gid = int(parts[0])
            quiz_id = parts[1]
            quiz = storage.get_quiz(quiz_id)
            if quiz:
                storage.add_group_allowed_quiz(gid, quiz_id)
                await query.answer(f"✅ Quiz qo'shildi: {quiz.get('title', quiz_id)[:20]}", show_alert=True)
            await _admin_gq_show_pick_latest(query.message, context, gid, 0)
            return

        if data.startswith("admin_gq_rm_"):
            parts = data.replace("admin_gq_rm_", "").split("_", 1)
            gid = int(parts[0])
            quiz_id = parts[1]
            storage.remove_group_allowed_quiz(gid, quiz_id)
            await query.answer("✅ Olib tashlandi")
            await _admin_gq_show_allowed_list(query.message, context, gid, 0)
            return

        if data.startswith("admin_gq_off_"):
            gid = int(data.replace("admin_gq_off_", ""))
            storage.set_group_allowed_quiz_ids(gid, [])
            await query.answer("✅ Filtr o'chirildi")
            await _admin_gq_show_group_menu(query.message, context, gid)
            return

        if data.startswith("admin_gq_add_"):
            gid = int(data.replace("admin_gq_add_", ""))
            context.user_data['admin_action'] = 'gq_add'
            context.user_data['admin_target_group_id'] = gid
            await safe_edit_text(
                query.message,
                "➕ **Quiz ID kiriting**\n\n"
                "Quiz ID yuboring (masalan: `b672034fe4b4`).\n"
                "Bekor qilish: `cancel`",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Orqaga", callback_data=f"admin_gq_select_{gid}")]]),
                parse_mode=ParseMode.MARKDOWN
            )
            return

        # Admin panel asosiy tugmalar
        if data == "admin_quizzes":
            from bot.handlers.admin import admin_quizzes_command
            class FakeUpdate:
                def __init__(self, q):
                    self.message = q.message
                    self.effective_user = q.from_user
                    self.effective_chat = q.message.chat
            fake_update = FakeUpdate(query)
            await admin_quizzes_command(fake_update, context)
            return

        if data == "admin_stats":
            from bot.handlers.admin import admin_stats_command
            class FakeUpdate:
                def __init__(self, q):
                    self.message = q.message
                    self.effective_user = q.from_user
                    self.effective_chat = q.message.chat
            fake_update = FakeUpdate(query)
            await admin_stats_command(fake_update, context)
            return

        if data == "admin_users":
            from bot.handlers.admin import admin_users_command
            class FakeUpdate:
                def __init__(self, q):
                    self.message = q.message
                    self.effective_user = q.from_user
                    self.effective_chat = q.message.chat
            fake_update = FakeUpdate(query)
            await admin_users_command(fake_update, context)
            return

        if data == "admin_groups":
            from bot.handlers.admin import admin_groups_command
            class FakeUpdate:
                def __init__(self, q):
                    self.message = q.message
                    self.effective_user = q.from_user
                    self.effective_chat = q.message.chat
            fake_update = FakeUpdate(query)
            await admin_groups_command(fake_update, context)
            return

        if data == "admin_broadcast":
            from bot.handlers.admin import admin_broadcast_command
            class FakeUpdate:
                def __init__(self, q):
                    self.message = q.message
                    self.effective_user = q.from_user
                    self.effective_chat = q.message.chat
            fake_update = FakeUpdate(query)
            await admin_broadcast_command(fake_update, context)
            return

        if data == "admin_cleanup":
            from bot.handlers.admin import admin_cleanup_command
            class FakeUpdate:
                def __init__(self, q):
                    self.message = q.message
                    self.effective_user = q.from_user
                    self.effective_chat = q.message.chat
            fake_update = FakeUpdate(query)
            await admin_cleanup_command(fake_update, context)
            return

        if data == "admin_sudo":
            from bot.handlers.admin import admin_sudo_command
            class FakeUpdate:
                def __init__(self, q):
                    self.message = q.message
                    self.effective_user = q.from_user
                    self.effective_chat = q.message.chat
            fake_update = FakeUpdate(query)
            await admin_sudo_command(fake_update, context)
            return

        if data == "admin_create_quiz":
            from bot.handlers.admin import admin_create_quiz_command
            class FakeUpdate:
                def __init__(self, q):
                    self.message = q.message
                    self.effective_user = q.from_user
                    self.effective_chat = q.message.chat
            fake_update = FakeUpdate(query)
            await admin_create_quiz_command(fake_update, context)
            return

        if data == "admin_group_quiz":
            await _admin_gq_show_groups(query.message, context)
            return

        if data == "admin_broadcast_users":
            context.user_data['admin_action'] = 'broadcast_users'
            await safe_edit_text(
                query.message,
                "📨 **Users ga yuborish**\n\n"
                "Yuboriladigan xabarni yuboring.\n"
                "Bekor qilish: `cancel`",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Admin", callback_data="admin_menu")]]),
                parse_mode=ParseMode.MARKDOWN
            )
            return

        if data == "admin_broadcast_groups":
            context.user_data['admin_action'] = 'broadcast_groups'
            await safe_edit_text(
                query.message,
                "👥 **Guruhlarga yuborish**\n\n"
                "Yuboriladigan xabarni yuboring.\n"
                "Bekor qilish: `cancel`",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Admin", callback_data="admin_menu")]]),
                parse_mode=ParseMode.MARKDOWN
            )
            return

        if data == "admin_create_quiz_file":
            context.user_data['admin_action'] = 'create_quiz_file'
            await safe_edit_text(
                query.message,
                "📄 **Fayl yuborish**\n\n"
                "Quiz yaratish uchun fayl yuboring:\n"
                "• TXT, DOCX, PDF formatlarida\n"
                "• Faylda test savollari bo'lishi kerak\n\n"
                "Faylni yuboring:",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Admin", callback_data="admin_menu")]]),
                parse_mode=ParseMode.MARKDOWN
            )
            return

        if data == "admin_create_quiz_topic":
            context.user_data['admin_action'] = 'create_quiz_topic'
            await safe_edit_text(
                query.message,
                "💬 **Mavzu aytish**\n\n"
                "Quiz yaratish uchun mavzuni yuboring.\n"
                "Masalan: \"Matematika - Algebra\", \"Tarix - O'rta asrlar\" va hokazo.\n\n"
                "Mavzuni yuboring:",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Admin", callback_data="admin_menu")]]),
                parse_mode=ParseMode.MARKDOWN
            )
            return

        # Broadcast tasdiqlash
        if data.startswith("admin_broadcast_yes_"):
            admin_action = data.replace("admin_broadcast_yes_", "")
            pending_text = context.user_data.get('admin_pending_text')
            if not pending_text:
                await query.answer("❌ Xabar topilmadi. Qayta urinib ko'ring.", show_alert=True)
                return
            
            await query.answer("🚀 Yuborish boshlandi...")
            await query.message.delete()
            
            sent = 0
            failed = 0
            if admin_action == "broadcast_users":
                users = storage.get_users()
                targets = [int(u['user_id']) for u in users if u.get('last_chat_type') == 'private'][:2000]
            else:
                bot_id = context.bot.id
                groups = storage.get_groups()
                targets = []
                for g in groups:
                    gid = int(g['chat_id'])
                    try:
                        m = await context.bot.get_chat_member(gid, bot_id)
                        if m.status in ['administrator', 'creator']:
                            targets.append(gid)
                    except Exception:
                        continue
                targets = targets[:500]

            status_msg = await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"🚀 Yuborish boshlandi... target: {len(targets)} ta"
            )
            
            for tid in targets:
                try:
                    await context.bot.send_message(chat_id=tid, text=pending_text)
                    sent += 1
                except Exception:
                    failed += 1
                await asyncio.sleep(0.05)

            context.user_data.pop('admin_action', None)
            context.user_data.pop('admin_pending_text', None)
            keyboard = [[KeyboardButton("⬅️ Orqaga")]]
            markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await status_msg.edit_text(
                f"✅ Yakunlandi.\n\nYuborildi: {sent}\nXatolik: {failed}"
            )
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="✅ Yakunlandi.",
                reply_markup=markup
            )
            return

        # Other admin actions
        await query.answer("ℹ️ Bu funksiya hali ishlanmoqda")
        return

    # PAGINATION
    if data.startswith("page_myquizzes_"):
        page = int(data.replace("page_myquizzes_", ""))
        from bot.handlers.quiz import myquizzes_command
        # Emulate update for pagination
        class FakeUpdate:
            def __init__(self, q):
                self.message = q.message
                self.effective_user = q.from_user
                self.effective_chat = q.message.chat
        fake_update = FakeUpdate(query)
        await myquizzes_command(fake_update, context, page=page)
        return

    if data.startswith("page_quizzes_"):
        page = int(data.replace("page_quizzes_", ""))
        from bot.handlers.quiz import quizzes_command
        class FakeUpdate:
            def __init__(self, q):
                self.message = q.message
                self.effective_user = q.from_user
                self.effective_chat = q.message.chat
        fake_update = FakeUpdate(query)
        await quizzes_command(fake_update, context, page=page)
        return

    # QUIZ MENU
    if data.startswith("quiz_menu_"):
        quiz_id = data.replace("quiz_menu_", "")
        quiz = storage.get_quiz(quiz_id)
        if not quiz:
            await query.answer("❌ Quiz topilmadi.", show_alert=True)
            return

        title = quiz.get('title', 'Quiz')
        count = len(quiz.get('questions', []))
        creator_id = quiz.get('created_by')
        
        is_owner = (creator_id == user_id)
        is_admin = is_admin_user(user_id)

        keyboard = [
            [InlineKeyboardButton("🚀 Boshlash", callback_data=f"select_time_{quiz_id}")],
            [InlineKeyboardButton("📊 Ma'lumot", callback_data=f"quiz_info_{quiz_id}")]
        ]

        if is_owner or is_admin:
            keyboard.append([InlineKeyboardButton("✏️ Qayta nomlash", callback_data=f"rename_quiz_{quiz_id}")])
            keyboard.append([InlineKeyboardButton("❌ O'chirish", callback_data=f"delete_{quiz_id}")])

        await safe_edit_text(
            query.message,
            f"📝 **{title}**\n\n📊 Savollar: {count}\n🆔 ID: `{quiz_id}`",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # QUIZ INFO
    if data.startswith("quiz_info_"):
        quiz_id = data.replace("quiz_info_", "")
        quiz = storage.get_quiz(quiz_id)
        if not quiz:
            await query.answer("❌ Quiz topilmadi.", show_alert=True)
            return

        title = quiz.get('title', 'Quiz')
        count = len(quiz.get('questions', []))
        created_by = quiz.get('created_by')
        created_at = str(quiz.get('created_at', ''))[:19].replace("T", " ")

        text = f"📊 **Quiz haqida**\n\n"
        text += f"🏷 Nomi: **{title}**\n"
        text += f"📝 Savollar: **{count}**\n"
        text += f"🆔 ID: `{quiz_id}`\n"
        text += f"👤 Creator: `{created_by}`\n"
        text += f"📅 Yaratilgan: {created_at}\n"

        keyboard = [[InlineKeyboardButton("⬅️ Orqaga", callback_data=f"quiz_menu_{quiz_id}")]]
        await safe_edit_text(query.message, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        return

    # DELETE QUIZ
    if data.startswith("delete_"):
        quiz_id = data.replace("delete_", "")
        quiz = storage.get_quiz(quiz_id)
        if not quiz:
            await query.answer("❌ Quiz topilmadi.", show_alert=True)
            return

        creator_id = quiz.get('created_by')
        if creator_id != user_id and not is_admin_user(user_id):
            await query.answer("❌ Siz bu quizni o'chira olmaysiz.", show_alert=True)
            return

        title = quiz.get('title') or quiz_id
        storage.delete_quiz(quiz_id)
        await safe_edit_text(
            query.message,
            f"✅ O'chirildi: **{title}**",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # RENAME QUIZ
    if data.startswith("rename_quiz_"):
        quiz_id = data.replace("rename_quiz_", "")
        quiz = storage.get_quiz(quiz_id)
        if not quiz:
            await query.answer("❌ Quiz topilmadi.", show_alert=True)
            return

        creator_id = quiz.get('created_by')
        if creator_id != user_id and not is_admin_user(user_id):
            await query.answer("❌ Siz bu quizni nomini o'zgartira olmaysiz.", show_alert=True)
            return

        # Set admin_action to wait for new title
        context.user_data['admin_action'] = 'rename_quiz'
        context.user_data['rename_quiz_id'] = quiz_id
        
        current_title = quiz.get('title', quiz_id)
        await safe_edit_text(
            query.message,
            f"✏️ **Quiz nomini o'zgartirish**\n\n"
            f"Joriy nom: **{current_title}**\n\n"
            f"Yangi nomni yuboring:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Bekor", callback_data=f"quiz_menu_{quiz_id}")]]),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # SELECT TIME
    if data.startswith("select_time_"):
        quiz_id = data.replace("select_time_", "")
        quiz = storage.get_quiz(quiz_id)
        if not quiz:
            await query.answer("❌ Quiz topilmadi.", show_alert=True)
            return

        title = quiz.get('title', 'Quiz')
        text = f"⏱ **Vaqt tanlang**\n\n📝 {title}\n\nHar bir savol uchun vaqt:"

        keyboard = []
        for label, seconds in TIME_OPTIONS.items():
            keyboard.append([InlineKeyboardButton(
                f"⏱ {label}",
                callback_data=f"start_{quiz_id}_{seconds}"
            )])
        keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data=f"quiz_menu_{quiz_id}")])

        await safe_edit_text(query.message, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        return

    # START GROUP WITH TIME (bu start_group_ dan oldin bo'lishi kerak!)
    if data.startswith("start_group_time_"):
        logger.info(f"📞 start_group_time_ callback: data={data}, chat_id={chat_id}, user_id={user_id}")
        try:
            # Remove prefix
            rest = data.replace("start_group_time_", "")
            # Split from right: last part is time_seconds, everything before is quiz_id
            # Quiz ID may contain underscores, so we split from right
            if "_" not in rest:
                logger.error(f"❌ start_group_time_ parse xatolik: no underscore in rest={rest}")
                await query.answer("❌ Xatolik: noto'g'ri format", show_alert=True)
                return
            
            # Split from right - last part is time_seconds
            parts = rest.rsplit("_", 1)
            if len(parts) != 2:
                logger.error(f"❌ start_group_time_ parse xatolik: parts={parts}, rest={rest}")
                await query.answer("❌ Xatolik: noto'g'ri format", show_alert=True)
                return
            
            quiz_id = parts[0]
            time_seconds = int(parts[1])
            
            logger.info(f"🚀 Guruhda quiz boshlash: quiz_id={quiz_id}, chat_id={chat_id}, user_id={user_id}, time={time_seconds}s")
            
            # Quiz mavjudligini tekshiramiz
            quiz = storage.get_quiz(quiz_id)
            if not quiz:
                logger.error(f"❌ Quiz topilmadi: {quiz_id}")
                await query.answer("❌ Quiz topilmadi", show_alert=True)
                return
            
            await query.answer("🚀 Quiz boshlanmoqda...")
            await start_quiz_session(query.message, context, quiz_id, chat_id, user_id, time_seconds)
            logger.info(f"✅ Quiz sessiyasi boshlandi: quiz_id={quiz_id}, chat_id={chat_id}")
        except ValueError as e:
            logger.error(f"❌ start_group_time_ ValueError: {e}, data={data}")
            await query.answer(f"❌ Xatolik: noto'g'ri format", show_alert=True)
        except Exception as e:
            logger.error(f"❌ Quiz boshlashda xatolik: {e}", exc_info=True)
            await query.answer(f"❌ Xatolik: {str(e)[:50]}", show_alert=True)
        return

    # START QUIZ (private)
    if data.startswith("start_") and not data.startswith("start_group_"):
        parts = data.replace("start_", "").rsplit("_", 1)
        quiz_id = parts[0]
        time_seconds = int(parts[1])

        await start_quiz_session(query.message, context, quiz_id, chat_id, user_id, time_seconds)
        return

    # START QUIZ (group) - vaqt tanlash menyusini ko'rsatish
    if data.startswith("start_group_"):
        quiz_id = data.replace("start_group_", "")
        quiz = storage.get_quiz(quiz_id)
        if not quiz:
            await query.answer("❌ Quiz topilmadi.", show_alert=True)
            return

        title = quiz.get('title', 'Quiz')
        text = f"⏱ **Vaqt tanlang**\n\n📝 {title}\n\nHar bir savol uchun vaqt:"

        keyboard = []
        for label, seconds in TIME_OPTIONS.items():
            keyboard.append([InlineKeyboardButton(
                f"⏱ {label}",
                callback_data=f"start_group_time_{quiz_id}_{seconds}"
            )])

        await safe_edit_text(query.message, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        return

    # RESTART QUIZ
    if data.startswith("restart_"):
        quiz_id = data.replace("restart_", "")
        quiz = storage.get_quiz(quiz_id)
        if not quiz:
            await query.answer("❌ Quiz topilmadi.", show_alert=True)
            return

        title = quiz.get('title', 'Quiz')
        text = f"🔄 **Qayta boshlash**\n\n📝 {title}\n\nVaqt tanlang:"

        keyboard = []
        for label, seconds in TIME_OPTIONS.items():
            keyboard.append([InlineKeyboardButton(
                f"⏱ {label}",
                callback_data=f"start_{quiz_id}_{seconds}"
            )])

        await safe_edit_text(query.message, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        return

    # GROUP QUIZZES PAGINATION
    if data.startswith("page_group_quizzes_"):
        parts = data.replace("page_group_quizzes_", "").split("_")
        group_chat_id = int(parts[0])
        page = int(parts[1])

        all_quizzes = storage.get_all_quizzes()
        allowed_ids = storage.get_group_allowed_quiz_ids(group_chat_id)
        if allowed_ids:
            allowed_set = set(allowed_ids)
            all_quizzes = [q for q in all_quizzes if str(q.get('quiz_id')) in allowed_set]

        QUIZZES_PER_PAGE = 10
        total_quizzes = len(all_quizzes)
        total_pages = (total_quizzes + QUIZZES_PER_PAGE - 1) // QUIZZES_PER_PAGE
        page = max(0, min(page, total_pages - 1))

        start_idx = page * QUIZZES_PER_PAGE
        end_idx = min(start_idx + QUIZZES_PER_PAGE, total_quizzes)
        page_quizzes = all_quizzes[start_idx:end_idx]

        text = ("📚 **Guruhda tanlangan quizlar:**\n\n" if allowed_ids else "📚 **Mavjud quizlar:**\n\n")
        if total_pages > 1:
            text += f"(Sahifa {page + 1}/{total_pages})\n\n"
        keyboard = []

        for i, quiz in enumerate(page_quizzes, 1):
            global_idx = start_idx + i
            count = len(quiz.get('questions', []))
            title = quiz.get('title', f"Quiz {global_idx}")[:20]
            text += f"{global_idx}. 📝 {title} ({count} savol)\n"

            keyboard.append([InlineKeyboardButton(
                f"🚀 {title} ({count} savol)",
                callback_data=f"start_group_{quiz['quiz_id']}"
            )])

        pagination_buttons = []
        if total_pages > 1:
            if page > 0:
                pagination_buttons.append(InlineKeyboardButton("⬅️ Oldingi", callback_data=f"page_group_quizzes_{group_chat_id}_{page - 1}"))
            if page < total_pages - 1:
                pagination_buttons.append(InlineKeyboardButton("Keyingi ➡️", callback_data=f"page_group_quizzes_{group_chat_id}_{page + 1}"))
            if pagination_buttons:
                keyboard.append(pagination_buttons)

        text += "\n🎯 Quizni tanlang!"

        await safe_edit_text(query.message, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        return

    await query.answer("ℹ️ Noma'lum buyruq")

