"""Quiz CRUD va file handling handlers"""
import os
import json
import hashlib
import time
import asyncio
import logging
from io import BytesIO
from typing import List, Dict

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from bot.config import Config
from bot.models import storage
from bot.utils.helpers import (
    track_update, is_sudo_user, is_admin_user, 
    private_main_keyboard, safe_reply_text
)
from bot.utils.validators import (
    sanitize_ai_input, extract_answer_key_map, apply_answer_key_to_questions,
    validate_questions, quick_has_quiz_patterns, parse_tilde_quiz, parse_numbered_quiz
)
from bot.services.file_parser import FileAnalyzer
from bot.services.ai_parser import AIParser
from bot.services.quiz_service import show_quiz_results, advance_due_sessions

logger = logging.getLogger(__name__)

# Limits
MIN_QUESTIONS_REQUIRED = Config.MIN_QUESTIONS_REQUIRED
MAX_QUESTIONS_PER_QUIZ = Config.MAX_QUESTIONS_PER_QUIZ
TARGET_QUESTIONS_PER_QUIZ = Config.TARGET_QUESTIONS_PER_QUIZ
MAX_AI_SECONDS = Config.MAX_AI_SECONDS
REQUIRE_CORRECT_ANSWER = Config.REQUIRE_CORRECT_ANSWER


async def myquizzes_command(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    """Foydalanuvchining quizlari"""
    track_update(update)
    user_id = update.effective_user.id
    user_quizzes = storage.get_user_quizzes(user_id)
    
    if not user_quizzes:
        await update.message.reply_text(
            "📭 Sizda quizlar yo'q.\n\n"
            "📝 Test faylini yuborib quiz yarating!"
        )
        return
    
    # Pagination
    QUIZZES_PER_PAGE = 10
    total_quizzes = len(user_quizzes)
    total_pages = (total_quizzes + QUIZZES_PER_PAGE - 1) // QUIZZES_PER_PAGE
    page = max(0, min(page, total_pages - 1))
    
    start_idx = page * QUIZZES_PER_PAGE
    end_idx = min(start_idx + QUIZZES_PER_PAGE, total_quizzes)
    page_quizzes = user_quizzes[start_idx:end_idx]
    
    text = f"📚 **Mening quizlarim:** (Sahifa {page + 1}/{total_pages})\n\n"
    keyboard = []
    
    for i, quiz in enumerate(page_quizzes, 1):
        global_idx = start_idx + i
        count = len(quiz.get('questions', []))
        title = quiz.get('title', f"Quiz {global_idx}")[:20]
        text += f"{global_idx}. 📝 {title} ({count} savol)\n"
        
        keyboard.append([InlineKeyboardButton(
            f"📝 {title} ({count} savol)",
            callback_data=f"quiz_menu_{quiz['quiz_id']}"
        )])
    
    # Pagination buttons
    pagination_buttons = []
    if total_pages > 1:
        if page > 0:
            pagination_buttons.append(InlineKeyboardButton("⬅️ Oldingi", callback_data=f"page_myquizzes_{page - 1}"))
        if page < total_pages - 1:
            pagination_buttons.append(InlineKeyboardButton("Keyingi ➡️", callback_data=f"page_myquizzes_{page + 1}"))
        if pagination_buttons:
            keyboard.append(pagination_buttons)
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await safe_reply_text(update.message, text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    
    try:
        await update.message.reply_text(
            "💡 Quyidagi tugmalardan foydalaning:",
            reply_markup=private_main_keyboard(update.effective_user.id)
        )
    except Exception:
        pass


async def sudo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: sudo userlarni boshqarish"""
    track_update(update)
    if update.effective_chat.type in ['group', 'supergroup']:
        await update.message.reply_text("ℹ️ /sudo faqat shaxsiy chatda.")
        return

    admin_id = update.effective_user.id
    if not is_admin_user(admin_id):
        return

    if not context.args:
        await update.message.reply_text(
            "Foydalanish:\n"
            "- `/sudo list`\n"
            "- `/sudo add 123456789`\n"
            "- `/sudo remove 123456789`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    action = context.args[0].lower().strip()
    if action == "list":
        sudo_users = storage.get_sudo_users()
        if not sudo_users:
            await update.message.reply_text("📭 Sudo userlar yo'q.")
            return
        text = "🛡 **Sudo userlar:**\n\n"
        for u in sudo_users[:50]:
            uname = f"@{u.get('username')}" if u.get('username') else "-"
            text += f"- `{u.get('user_id')}` {uname} {u.get('first_name') or ''}\n"
        await safe_reply_text(update.message, text, parse_mode=ParseMode.MARKDOWN)
        return

    if action in ["add", "remove", "del", "delete"]:
        if len(context.args) < 2:
            await update.message.reply_text("❌ user_id kiriting. Masalan: `/sudo add 123`", parse_mode=ParseMode.MARKDOWN)
            return
        try:
            target_id = int(context.args[1])
        except Exception:
            await update.message.reply_text("❌ user_id raqam bo'lishi kerak.")
            return

        if action == "add":
            username = None
            first_name = None
            try:
                for u in storage.get_users():
                    if int(u.get('user_id')) == target_id:
                        username = u.get('username')
                        first_name = u.get('first_name')
                        break
            except Exception:
                pass
            storage.add_sudo_user(target_id, username=username, first_name=first_name)
            await safe_reply_text(update.message, f"✅ Sudo berildi: `{target_id}`", parse_mode=ParseMode.MARKDOWN)
            return

        ok = storage.remove_sudo_user(target_id)
        await safe_reply_text(
            update.message,
            ("✅ Sudo olib tashlandi: " if ok else "ℹ️ Sudo topilmadi: ") + f"`{target_id}`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    await update.message.reply_text("❌ Noma'lum buyruq. `/sudo list` deb ko'ring.", parse_mode=ParseMode.MARKDOWN)


async def quizzes_command(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    """Barcha quizlar"""
    track_update(update)
    chat_type = update.effective_chat.type
    if chat_type in ['group', 'supergroup']:
        await update.message.reply_text(
            "ℹ️ Barcha quizlarni ko'rish uchun botga shaxsiy chatda yozing.\n\n"
            "Guruhda esa /startquiz ishlating."
        )
        return

    all_quizzes = storage.get_all_quizzes()
    if not all_quizzes:
        await update.message.reply_text("📭 Hozircha quizlar yo'q.")
        return

    all_quizzes.sort(key=lambda q: q.get('created_at', ''), reverse=True)
    
    # Pagination
    QUIZZES_PER_PAGE = 10
    total_quizzes = len(all_quizzes)
    total_pages = (total_quizzes + QUIZZES_PER_PAGE - 1) // QUIZZES_PER_PAGE
    page = max(0, min(page, total_pages - 1))
    
    start_idx = page * QUIZZES_PER_PAGE
    end_idx = min(start_idx + QUIZZES_PER_PAGE, total_quizzes)
    page_quizzes = all_quizzes[start_idx:end_idx]
    
    text = f"📚 **Mavjud quizlar:** (Sahifa {page + 1}/{total_pages})\n\n"
    keyboard = []
    for i, quiz in enumerate(page_quizzes, 1):
        global_idx = start_idx + i
        count = len(quiz.get('questions', []))
        title = (quiz.get('title') or f"Quiz {global_idx}")[:30]
        text += f"{global_idx}. 📝 {title} ({count} savol)\n"
        keyboard.append([InlineKeyboardButton(
            f"📝 {title} ({count})",
            callback_data=f"quiz_menu_{quiz['quiz_id']}"
        )])
    
    # Pagination buttons
    pagination_buttons = []
    if total_pages > 1:
        if page > 0:
            pagination_buttons.append(InlineKeyboardButton("⬅️ Oldingi", callback_data=f"page_quizzes_{page - 1}"))
        if page < total_pages - 1:
            pagination_buttons.append(InlineKeyboardButton("Keyingi ➡️", callback_data=f"page_quizzes_{page + 1}"))
        if pagination_buttons:
            keyboard.append(pagination_buttons)
    
    await safe_reply_text(
        update.message,
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )
    
    try:
        await update.message.reply_text(
            "💡 Quyidagi tugmalardan foydalaning:",
            reply_markup=private_main_keyboard(update.effective_user.id)
        )
    except Exception:
        pass


async def searchquiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quizlarni qidirish"""
    track_update(update)
    chat_type = update.effective_chat.type
    if chat_type in ['group', 'supergroup']:
        await update.message.reply_text("ℹ️ Qidirish uchun botga shaxsiy chatda yozing.")
        return

    query = " ".join(context.args).strip() if context.args else ""
    if len(query) < 2:
        await update.message.reply_text("🔎 Foydalanish: `/searchquiz matematika`", parse_mode=ParseMode.MARKDOWN)
        return

    q_lower = query.lower()
    all_quizzes = storage.get_all_quizzes()
    matches = []
    for quiz in all_quizzes:
        title = (quiz.get('title') or '').lower()
        if q_lower in title:
            matches.append(quiz)

    if not matches:
        await update.message.reply_text("❌ Hech narsa topilmadi.")
        return

    matches.sort(key=lambda q: q.get('created_at', ''), reverse=True)
    text = f"🔎 **Qidiruv:** `{query}`\n\n"
    keyboard = []
    for i, quiz in enumerate(matches[:10], 1):
        count = len(quiz.get('questions', []))
        title = (quiz.get('title') or f"Quiz {i}")[:30]
        text += f"{i}. 📝 {title} ({count} savol)\n"
        keyboard.append([InlineKeyboardButton(
            f"📝 {title} ({count})",
            callback_data=f"quiz_menu_{quiz['quiz_id']}"
        )])
    await safe_reply_text(update.message, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)


async def quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quiz ID orqali menyu"""
    track_update(update)
    quiz_id = (context.args[0].strip() if context.args else "").strip()
    if not quiz_id:
        await update.message.reply_text("Foydalanish: `/quiz b672034fe4b4`", parse_mode=ParseMode.MARKDOWN)
        return

    quiz = storage.get_quiz(quiz_id)
    if not quiz:
        await update.message.reply_text("❌ Quiz topilmadi.")
        return

    count = len(quiz.get('questions', []))
    title = quiz.get('title', 'Quiz')

    keyboard = []
    try:
        chat_type = update.effective_chat.type
        chat_id = update.effective_chat.id
    except Exception:
        chat_type = None
        chat_id = None

    if chat_type in ['group', 'supergroup'] and chat_id is not None and (not storage.group_allows_quiz(chat_id, quiz_id)):
        keyboard.append([InlineKeyboardButton("📊 Ma'lumot", callback_data=f"quiz_info_{quiz_id}")])
    else:
        keyboard.extend([
            [InlineKeyboardButton("🚀 Boshlash", callback_data=f"select_time_{quiz_id}")],
            [InlineKeyboardButton("📊 Ma'lumot", callback_data=f"quiz_info_{quiz_id}")]
        ])
    await safe_reply_text(
        update.message,
        f"📝 **{title}**\n\n📊 Savollar: {count}\n🆔 ID: `{quiz_id}`",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


async def deletequiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quizni o'chirish"""
    track_update(update)
    chat_type = update.effective_chat.type
    if chat_type in ['group', 'supergroup']:
        await update.message.reply_text("ℹ️ /deletequiz faqat shaxsiy chatda ishlaydi.")
        return

    user_id = update.effective_user.id
    quiz_id = (context.args[0].strip() if context.args else "").strip()
    if not quiz_id:
        await update.message.reply_text("Foydalanish: `/deletequiz b672034fe4b4`", parse_mode=ParseMode.MARKDOWN)
        return

    quiz = storage.get_quiz(quiz_id)
    if not quiz:
        await update.message.reply_text("❌ Quiz topilmadi.")
        return

    # Only owner or admin can delete
    if (quiz.get('created_by') != user_id) and (not is_admin_user(user_id)):
        await update.message.reply_text("❌ Siz bu quizni o'chira olmaysiz (faqat egasi yoki admin).")
        return

    title = quiz.get('title') or quiz_id
    ok = storage.delete_quiz(quiz_id)
    if ok:
        await safe_reply_text(update.message, f"✅ O'chirildi: **{title}** (`{quiz_id}`)", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("❌ O'chirishda xatolik.")


async def finishquiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shaxsiy chatda quizni yakunlash"""
    track_update(update)
    chat = update.effective_chat
    if chat.type in ['group', 'supergroup']:
        await update.message.reply_text("ℹ️ Bu buyruq faqat shaxsiy chatda ishlaydi.\n\nGuruhda /stopquiz ishlating.")
        return
    
    await advance_due_sessions(context)
    
    chat_id = chat.id
    user_id = update.effective_user.id
    
    sessions = context.bot_data.setdefault('sessions', {})
    
    stopped = 0
    finished_quizzes = []
    
    user_prefix = f"quiz_{chat_id}_{user_id}_"
    for k, s in list(sessions.items()):
        if k.startswith(user_prefix) and s.get('is_active', False):
            quiz_id = s.get('quiz_id')
            if quiz_id:
                finished_quizzes.append(quiz_id)
            s['is_active'] = False
            stopped += 1
    
    if stopped == 0:
        await update.message.reply_text("ℹ️ Hozir sizda aktiv quiz yo'q.")
        return
    
    if finished_quizzes:
        quiz_id = finished_quizzes[-1]
        await show_quiz_results(update.message, context, quiz_id, chat_id, user_id)
    else:
        await update.message.reply_text(
            f"✅ Quiz yakunlandi: {stopped} ta session yopildi."
        )


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Matnli xabarlarni qayta ishlash (klaviatura tugmalari)"""
    track_update(update)
    text = update.message.text.strip()
    user_id = update.effective_user.id
    
    # Asosiy klaviatura tugmalari
    if text == "📚 Mavjud quizlar":
        await quizzes_command(update, context)
    elif text == "🏅 Mening natijalarim":
        from bot.handlers.start import myresults_command
        await myresults_command(update, context)
    elif text == "📚 Mening quizlarim":
        await myquizzes_command(update, context)
    elif text == "🔎 Qidirish":
        await update.message.reply_text(
            "🔎 Qidirish uchun: `/searchquiz nom`",
            parse_mode=ParseMode.MARKDOWN
        )
    elif text == "ℹ️ Yordam":
        from bot.handlers.start import help_command
        await help_command(update, context)
    elif text == "🛠 Admin":
        from bot.handlers.admin import admin_command
        await admin_command(update, context)
    # Admin menyu tugmalari
    elif text == "📚 Quizlar":
        from bot.handlers.admin import admin_quizzes_command
        await admin_quizzes_command(update, context)
    elif text == "📊 Statistika":
        from bot.handlers.admin import admin_stats_command
        await admin_stats_command(update, context)
    elif text == "👤 Users":
        from bot.handlers.admin import admin_users_command
        await admin_users_command(update, context)
    elif text == "👥 Guruhlar":
        from bot.handlers.admin import admin_groups_command
        await admin_groups_command(update, context)
    elif text == "📣 Broadcast":
        from bot.handlers.admin import admin_broadcast_command
        await admin_broadcast_command(update, context)
    elif text == "🧹 Cleanup":
        from bot.handlers.admin import admin_cleanup_command
        await admin_cleanup_command(update, context)
    elif text == "🛡 Sudo":
        from bot.handlers.admin import admin_sudo_command
        await admin_sudo_command(update, context)
    elif text == "➕ Create Quiz":
        from bot.handlers.admin import admin_create_quiz_command
        await admin_create_quiz_command(update, context)
    elif text == "📄 Fayl yuborish":
        if is_admin_user(user_id) and update.effective_chat.type == 'private':
            context.user_data['admin_action'] = 'create_quiz_file'
            keyboard = [[KeyboardButton("⬅️ Orqaga")]]
            markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(
                "📄 **Fayl yuborish**\n\n"
                "Quiz yaratish uchun fayl yuboring:\n"
                "• TXT, DOCX, PDF formatlarida\n"
                "• Faylda test savollari bo'lishi kerak\n\n"
                "Faylni yuboring:",
                reply_markup=markup,
                parse_mode=ParseMode.MARKDOWN
            )
    elif text == "💬 Mavzu aytish":
        if is_admin_user(user_id) and update.effective_chat.type == 'private':
            context.user_data['admin_action'] = 'create_quiz_topic'
            keyboard = [[KeyboardButton("⬅️ Orqaga")]]
            markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(
                "💬 **Mavzu aytish**\n\n"
                "Quiz yaratish uchun mavzuni yuboring.\n"
                "Masalan: \"Matematika - Algebra\", \"Tarix - O'rta asrlar\" va hokazo.\n\n"
                "Mavzuni yuboring:",
                reply_markup=markup,
                parse_mode=ParseMode.MARKDOWN
            )
    elif text == "🎛 Guruh quizlari":
        from bot.handlers.admin import admin_group_quiz_command
        await admin_group_quiz_command(update, context)
    elif text == "⬅️ Orqaga":
        from bot.utils.helpers import is_admin_user, private_main_keyboard
        if is_admin_user(user_id) and update.effective_chat.type == 'private':
            keyboard = private_main_keyboard(user_id)
            await update.message.reply_text(
                "🏠 Asosiy menyu",
                reply_markup=keyboard
            )
    # Broadcast wizard tugmalari
    elif text == "📨 Users ga yuborish":
        if context.user_data.get('admin_action') == 'broadcast_choice' and is_admin_user(user_id) and update.effective_chat.type == 'private':
            context.user_data['admin_action'] = 'broadcast_users'
            context.user_data.pop('admin_pending_text', None)
            keyboard = [[KeyboardButton("⬅️ Orqaga")]]
            markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text("✍️ Yuboriladigan xabar matnini jo'nating (keyin tasdiqlaysiz).", reply_markup=markup)
    elif text == "👥 Guruhlarga yuborish":
        if context.user_data.get('admin_action') == 'broadcast_choice' and is_admin_user(user_id) and update.effective_chat.type == 'private':
            context.user_data['admin_action'] = 'broadcast_groups'
            context.user_data.pop('admin_pending_text', None)
            keyboard = [[KeyboardButton("⬅️ Orqaga")]]
            markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text("✍️ Yuboriladigan xabar matnini jo'nating (keyin tasdiqlaysiz).", reply_markup=markup)
    # Admin wizard: group quiz allowlist (gq_add)
    elif context.user_data.get('admin_action') == 'gq_add':
        if not is_admin_user(user_id):
            context.user_data.pop('admin_action', None)
            context.user_data.pop('admin_target_group_id', None)
            return
        if update.effective_chat.type in ['group', 'supergroup']:
            await update.message.reply_text("ℹ️ Bu amal faqat shaxsiy chatda.")
            return

        gid = context.user_data.get('admin_target_group_id')
        raw = text.strip()
        if not gid:
            context.user_data.pop('admin_action', None)
            await update.message.reply_text("❌ Guruh tanlanmagan. /admin dan qayta kiring.")
            return

        # cancel/exit
        if raw.lower() in ['cancel', 'bekor', 'stop', '/cancel']:
            context.user_data.pop('admin_action', None)
            context.user_data.pop('admin_target_group_id', None)
            from telegram import InlineKeyboardMarkup, InlineKeyboardButton
            await update.message.reply_text("✅ Bekor qilindi.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Admin", callback_data="admin_menu")]]))
            return

        quiz_id = raw.split()[0]
        quiz = storage.get_quiz(quiz_id)
        if not quiz:
            await update.message.reply_text("❌ Quiz topilmadi. ID ni tekshiring (yoki `cancel`).", parse_mode=ParseMode.MARKDOWN)
            return

        storage.add_group_allowed_quiz(int(gid), quiz_id)
        context.user_data.pop('admin_action', None)
        context.user_data.pop('admin_target_group_id', None)
        title = quiz.get('title') or quiz_id
        from telegram import InlineKeyboardMarkup, InlineKeyboardButton
        await safe_reply_text(
            update.message,
            f"✅ Qo'shildi: **{title}** (`{quiz_id}`)\n\nEndi /startquiz faqat tanlanganlarni ko'rsatadi.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎛 Guruh quizlari", callback_data=f"admin_gq_select_{gid}")]]),
            parse_mode=ParseMode.MARKDOWN
        )
    # Broadcast text qabul qilish
    elif context.user_data.get('admin_action') in ['broadcast_users', 'broadcast_groups']:
        if is_admin_user(user_id) and update.effective_chat.type == 'private':
            admin_action = context.user_data.get('admin_action')
            pending_text = text.strip()
            if len(pending_text) < 1:
                await update.message.reply_text("❌ Xabar bo'sh bo'lmasin.")
                return

            context.user_data['admin_pending_text'] = pending_text
            
            target_name = "foydalanuvchilarga" if admin_action == "broadcast_users" else "guruh(lar)ga"
            from telegram import InlineKeyboardMarkup, InlineKeyboardButton
            keyboard = [
                [InlineKeyboardButton("✅ Yuborish", callback_data=f"admin_broadcast_yes_{admin_action}")],
                [InlineKeyboardButton("❌ Bekor", callback_data="admin_menu")],
            ]
            await update.message.reply_text(
                f"⚠️ {target_name} yuboriladigan xabar:\n\n{pending_text}\n\nTasdiqlaysizmi?",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
    # Create quiz from topic
    elif context.user_data.get('admin_action') == 'create_quiz_topic':
        if is_admin_user(user_id) and update.effective_chat.type == 'private':
            topic = text.strip()
            if len(topic) < 3:
                await update.message.reply_text("❌ Mavzu juda qisqa. Kamida 3 belgi bo'lishi kerak.")
                return
            
            context.user_data.pop('admin_action', None)
            context.user_data['admin_action'] = 'create_quiz_topic_processing'
            context.user_data['admin_topic'] = topic
            
            status_msg = await update.message.reply_text(
                f"💬 **Mavzu:** {topic}\n\n"
                "🤖 AI quiz yaratmoqda..."
            )
            
            try:
                # AI orqali quiz yaratish
                ai_parser = AIParser()
                
                # Mavzu asosida prompt yaratish
                prompt_text = f"""Quyidagi mavzu bo'yicha test savollarini yarating:

Mavzu: {topic}

Har bir savol uchun:
- Savol matni
- 4 ta javob varianti
- To'g'ri javob
- Qisqa tushuntirish (ixtiyoriy)

Kamida 10 ta savol yarating."""

                await status_msg.edit_text(
                    f"💬 **Mavzu:** {topic}\n\n"
                    "🤖 AI ga so'rov yuborilmoqda..."
                )
                
                async def progress_callback(percent, text):
                    try:
                        await status_msg.edit_text(
                            f"💬 **Mavzu:** {topic}\n\n"
                            f"🤖 {text}"
                        )
                    except Exception:
                        pass
                
                result = await ai_parser.analyze_with_ai(
                    prompt_text,
                    progress_callback=progress_callback,
                    strict_correct=False
                )
                
                if not result or not result.get('questions'):
                    await status_msg.edit_text(
                        f"❌ Mavzu bo'yicha quiz yaratib bo'lmadi.\n\n"
                        f"💡 Boshqa mavzu yuborib ko'ring."
                    )
                    context.user_data.pop('admin_action', None)
                    context.user_data.pop('admin_topic', None)
                    return
                
                questions = result.get('questions', [])
                ai_title = result.get('title', topic[:50])
                
                # Quiz saqlash
                quiz_content = json.dumps(questions, sort_keys=True)
                quiz_id = hashlib.md5(quiz_content.encode()).hexdigest()[:12]
                
                user_id = update.effective_user.id
                chat_id = update.effective_chat.id
                
                storage.save_quiz(quiz_id, questions, user_id, chat_id, ai_title)
                
                keyboard = [
                    [KeyboardButton("⬅️ Orqaga")],
                    [KeyboardButton("🛠 Admin")]
                ]
                markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                
                await status_msg.edit_text(
                    f"✅ **Quiz tayyor!**\n\n"
                    f"🏷 Nomi: {ai_title}\n"
                    f"📝 Savollar: {len(questions)}\n"
                    f"🆔 ID: `{quiz_id}`",
                    reply_markup=markup,
                    parse_mode=ParseMode.MARKDOWN
                )
                
                context.user_data.pop('admin_action', None)
                context.user_data.pop('admin_topic', None)
                
            except Exception as e:
                logger.error(f"Topic quiz creation error: {e}", exc_info=True)
                await status_msg.edit_text(
                    f"❌ Xatolik: {str(e)}\n\n"
                    f"💡 Qayta urinib ko'ring."
                )
                context.user_data.pop('admin_action', None)
                context.user_data.pop('admin_topic', None)


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fayl qabul qilish va quiz yaratish"""
    track_update(update)
    message = update.message
    chat_type = update.effective_chat.type
    
    if chat_type in ['group', 'supergroup']:
        # Guruhda fayl qabul qilinmaydi
        return

    # Faqat createquiz jarayonida fayl qabul qilinadi
    is_admin_file_action = (
        context.user_data.get('admin_action') == 'create_quiz_file' and
        is_admin_user(message.from_user.id)
    )
    
    # Agar createquiz jarayonida bo'lmasa, fayl qabul qilinmaydi
    if not is_admin_file_action:
        return
    
    # Admin file action bo'lsa, action ni o'chirish
    if is_admin_file_action:
        context.user_data.pop('admin_action', None)
    
    if not message.document:
        await message.reply_text("❌ Iltimos, fayl yuboring!")
        return
    
    file = await context.bot.get_file(message.document.file_id)
    file_name = message.document.file_name
    file_extension = os.path.splitext(file_name)[1]
    
    status_msg = await message.reply_text(
        f"📥 **Fayl:** {file_name}\n\n🔄 Tahlil qilinmoqda..."
    )

    last_percent = -1
    last_ts = 0.0
    
    async def update_progress(percent, text):
        nonlocal last_percent, last_ts
        try:
            now = time.time()
            percent = int(max(percent, last_percent))
            if percent == last_percent and (now - last_ts) < 2.0:
                return
            last_percent = percent
            last_ts = now
            bar = "█" * (percent // 5) + "░" * (20 - percent // 5)
            await status_msg.edit_text(
                f"📥 **Fayl:** {file_name}\n\n[{bar}] {percent}%\n{text}"
            )
        except Exception:
            pass
    
    try:
        await update_progress(10, "📂 Yuklanmoqda...")
        file_bytes = BytesIO()
        await file.download_to_memory(file_bytes)
        file_content = file_bytes.getvalue()
        
        await update_progress(20, "📖 O'qilmoqda...")
        analyzer = FileAnalyzer()
        text = analyzer.extract_text(bytes(file_content), file_extension)
        
        if not text or len(text.strip()) < 10:
            await status_msg.edit_text("❌ Fayldan matn o'qib bo'lmadi.")
            return

        # Extract answer key if present
        try:
            answer_key_map = extract_answer_key_map(text)
        except Exception:
            answer_key_map = {}
        
        # Quick precheck
        await update_progress(25, "🔎 Faylda test borligini tekshirish...")
        has_patterns = quick_has_quiz_patterns(text)
        target_limit = max(1, min(int(TARGET_QUESTIONS_PER_QUIZ or 50), int(MAX_QUESTIONS_PER_QUIZ or 100)))
        
        if not has_patterns:
            algo_check: List[Dict] = []
            try:
                algo_check.extend(parse_tilde_quiz(text)[:5])
            except Exception:
                pass
            try:
                algo_check.extend(parse_numbered_quiz(text)[:5])
            except Exception:
                pass
            has_patterns = len(algo_check) >= 2
        
        if not has_patterns:
            await status_msg.edit_text(
                "❌ Bu faylda test savollari aniqlanmadi.\n\n"
                "✅ Namuna format:\n"
                "1) Savol matni?\n"
                "A) Variant 1\nB) Variant 2\nC) Variant 3\nD) Variant 4\n\n"
                "ℹ️ Agar fayl juda katta bo'lsa, uni 2-3 qismga bo'lib yuboring."
            )
            return
        
        # AI analysis
        ai_text = sanitize_ai_input(text)
        await update_progress(30, "🤖 AI savollarni ajratmoqda...")
        ai_parser = AIParser()
        ai_started_at = time.time()
        heartbeat_stop = False

        async def heartbeat():
            while not heartbeat_stop:
                elapsed = int(time.time() - ai_started_at)
                await update_progress(50, f"⏳ AI tahlil qilmoqda... ({elapsed}s)")
                await asyncio.sleep(8)

        hb_task = asyncio.create_task(heartbeat())
        
        ai_result = None
        ai_title = ""
        
        # Try deepseek-chat first
        try:
            ai_result = await asyncio.wait_for(
                ai_parser.analyze_with_ai(ai_text, progress_callback=update_progress, strict_correct=True, model="deepseek-chat"),
                timeout=MAX_AI_SECONDS
            )
        except asyncio.TimeoutError:
            logger.error(f"AI (chat) timeout after {MAX_AI_SECONDS}s for file={file_name}")
            ai_result = None
        except Exception as e:
            logger.error(f"AI (chat) error: {e}")
            ai_result = None
        
        # Try deepseek-reasoner if needed
        if not ai_result or len(ai_result.get("questions", [])) < MIN_QUESTIONS_REQUIRED:
            await update_progress(45, "🧠 AI (reasoner) savollarni ajratmoqda...")
            ai_started_at = time.time()
            try:
                ai_result = await asyncio.wait_for(
                    ai_parser.analyze_with_ai(ai_text, progress_callback=update_progress, strict_correct=True, model="deepseek-reasoner"),
                    timeout=MAX_AI_SECONDS + 60
                )
            except asyncio.TimeoutError:
                logger.error(f"AI (reasoner) timeout for file={file_name}")
                ai_result = None
            except Exception as e:
                logger.error(f"AI (reasoner) error: {e}")
                ai_result = None
        
        heartbeat_stop = True
        try:
            hb_task.cancel()
        except Exception:
            pass
        
        if not ai_result or not ai_result.get("questions"):
            await status_msg.edit_text(
                "❌ AI fayldan savollarni ajrata olmadi.\n\n"
                "ℹ️ Iltimos, quyidagilarni tekshiring:\n"
                "• Savollar va variantlar aniq ko'rinib turadimi?\n"
                "• Fayl juda katta bo'lsa, 2-3 qismga bo'lib yuboring\n"
                "• Format: 1) Savol? A) ... B) ... C) ... D) ..."
            )
            return
        
        ai_title = (ai_result.get("title") or "").strip()
        questions = validate_questions(ai_result.get("questions", []), require_correct=False)
        
        if len(questions) < MIN_QUESTIONS_REQUIRED:
            await status_msg.edit_text(
                "❌ AI yetarli savollarni ajrata olmadi.\n\n"
                f"Topildi: {len(questions)} ta (minimum: {MIN_QUESTIONS_REQUIRED})\n\n"
                "ℹ️ Formatni aniqroq qilib qayta yuboring."
            )
            return
        
        # Apply limit
        if target_limit > 0 and len(questions) > target_limit:
            questions = questions[:target_limit]
        
        await update_progress(70, f"✅ {len(questions)} ta savol topildi")
        
        # Apply answer key
        try:
            applied = apply_answer_key_to_questions(questions, answer_key_map)
            if applied:
                logger.info(f"answer_key applied: {applied}/{len(questions)} file={file_name}")
        except Exception:
            pass

        # Fill missing correct answers with AI
        missing_idxs = [i for i, q in enumerate(questions) if q.get("correct_answer") is None]
        
        if missing_idxs:
            await update_progress(75, f"🧠 To'g'ri javoblar aniqlanmoqda... ({len(missing_idxs)} ta)")
            
            chunk_size = 10
            total_missing = len(missing_idxs)
            solved = 0
            
            for start in range(0, total_missing, chunk_size):
                chunk_indices = missing_idxs[start:start + chunk_size]
                chunk_questions = [questions[i] for i in chunk_indices]

                answers = await AIParser.pick_correct_answers(chunk_questions, model="deepseek-chat")
                if not answers or len(answers) != len(chunk_indices):
                    answers = await AIParser.pick_correct_answers(chunk_questions, model="deepseek-reasoner")

                if answers and len(answers) == len(chunk_indices):
                    for local_i, ans_idx in enumerate(answers):
                        gi = chunk_indices[local_i]
                        opts = questions[gi].get("options") or []
                        if isinstance(opts, list) and ans_idx is not None and 0 <= ans_idx < len(opts):
                            questions[gi]["correct_answer"] = ans_idx
                            solved += 1

                try:
                    done = min(start + len(chunk_indices), total_missing)
                    pct = 75 + int(15 * (done / max(1, total_missing)))
                    await update_progress(pct, f"🧠 To'g'ri javoblar: {solved}/{total_missing}")
                except Exception:
                    pass

        # Check REQUIRE_CORRECT_ANSWER
        if REQUIRE_CORRECT_ANSWER:
            with_correct = [q for q in questions if q.get("correct_answer") is not None]
            if len(with_correct) >= MIN_QUESTIONS_REQUIRED:
                dropped = len(questions) - len(with_correct)
                questions = with_correct
                if dropped > 0:
                    try:
                        await context.bot.send_message(
                            chat_id=message.chat_id,
                            text=f"ℹ️ {dropped} ta savolda to'g'ri javob topilmadi — ular olib tashlandi."
                        )
                    except Exception:
                        pass
            else:
                await status_msg.edit_text(
                    "❌ To'g'ri javoblarni topib bo'lmadi.\n\n"
                    "✅ Yechimlar:\n"
                    "1) Fayl oxiriga javoblar kalitini qo'shing (masalan: `Javoblar: 1-A, 2-C, 3-B`)\n"
                    "2) To'g'ri variant boshiga `✅` yoki `*` qo'ying\n"
                    "3) Yoki savollarni qisqartirib qayta yuboring\n"
                )
                return

        if len(questions) < MIN_QUESTIONS_REQUIRED:
            await status_msg.edit_text(
                "❌ Fayldan yetarli test savollari topilmadi.\n\n"
                "Iltimos, savollar+variantlar aniq ko'rinadigan formatda yuboring."
            )
            return

        # Apply max limit
        if len(questions) > MAX_QUESTIONS_PER_QUIZ:
            questions = questions[:MAX_QUESTIONS_PER_QUIZ]
            try:
                await context.bot.send_message(
                    chat_id=message.chat_id,
                    text=f"ℹ️ Juda ko'p savol topildi. Cheklov: {MAX_QUESTIONS_PER_QUIZ} ta savol saqlandi."
                )
            except Exception:
                pass
        
        user_id = message.from_user.id
        chat_id = message.chat_id
        
        quiz_content = json.dumps(questions, sort_keys=True)
        quiz_id = hashlib.md5(quiz_content.encode()).hexdigest()[:12]
        
        title_to_save = (ai_title[:100] if ai_title else file_name)
        storage.save_quiz(quiz_id, questions, user_id, chat_id, title_to_save)
        
        keyboard = [
            [InlineKeyboardButton("🚀 Quizni boshlash", callback_data=f"quiz_menu_{quiz_id}")],
            [InlineKeyboardButton("📊 Ma'lumot", callback_data=f"quiz_info_{quiz_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await status_msg.edit_text(
            f"✅ **Quiz tayyor!**\n\n"
            f"🏷 Nomi: {title_to_save[:50]}\n"
            f"📝 Savollar: {len(questions)}\n"
            f"🆔 ID: `{quiz_id}`",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        logger.error(f"Fayl tahlil xatolik: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Xatolik: {str(e)}")

