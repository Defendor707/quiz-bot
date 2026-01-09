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
    track_update, is_sudo_user, is_admin_user, is_vip_user,
    private_main_keyboard, safe_reply_text
)
from bot.handlers.premium import is_premium_or_has_quota
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
    
    # Faqat shaxsiy chatda reply keyboard ko'rsatish
    if update.effective_chat.type == 'private':
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


async def vip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: VIP userlarni boshqarish"""
    track_update(update)
    if update.effective_chat.type in ['group', 'supergroup']:
        await update.message.reply_text("ℹ️ /vip faqat shaxsiy chatda.")
        return

    admin_id = update.effective_user.id
    if not is_admin_user(admin_id):
        return

    if not context.args:
        await update.message.reply_text(
            "Foydalanish:\n"
            "- `/vip list`\n"
            "- `/vip add 123456789`\n"
            "- `/vip remove 123456789`\n"
            "- `/vip addme` - O'zingizni VIP qilish",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    action = context.args[0].lower().strip()
    if action == "list":
        vip_users = storage.get_vip_users()
        if not vip_users:
            await update.message.reply_text("📭 VIP userlar yo'q.")
            return
        text = "⭐ **VIP userlar:**\n\n"
        for u in vip_users[:50]:
            uname = f"@{u.get('username')}" if u.get('username') else "-"
            nickname = u.get('nickname', '')
            text += f"- `{u.get('user_id')}` {uname} {nickname or u.get('first_name') or ''}\n"
        await safe_reply_text(update.message, text, parse_mode=ParseMode.MARKDOWN)
        return

    if action == "addme":
        # Admin o'zini VIP qilish
        username = update.effective_user.username
        first_name = update.effective_user.first_name
        storage.add_vip_user(admin_id, username=username, first_name=first_name, nickname=f"{first_name} ⭐")
        await safe_reply_text(update.message, f"✅ Siz VIP user qilib tayinlandingiz! ⭐", parse_mode=ParseMode.MARKDOWN)
        return

    if action in ["add", "remove", "del", "delete"]:
        if len(context.args) < 2:
            await update.message.reply_text("❌ user_id kiriting. Masalan: `/vip add 123`", parse_mode=ParseMode.MARKDOWN)
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
            storage.add_vip_user(target_id, username=username, first_name=first_name, nickname=f"{first_name or 'VIP User'} ⭐")
            await safe_reply_text(update.message, f"✅ VIP berildi: `{target_id}` ⭐", parse_mode=ParseMode.MARKDOWN)
            return

        ok = storage.remove_vip_user(target_id)
        await safe_reply_text(
            update.message,
            ("✅ VIP olib tashlandi: " if ok else "ℹ️ VIP topilmadi: ") + f"`{target_id}`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    await update.message.reply_text("❌ Noma'lum buyruq. `/vip list` deb ko'ring.", parse_mode=ParseMode.MARKDOWN)


async def channels_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: Majburiy obuna kanallarini boshqarish"""
    track_update(update)
    if update.effective_chat.type in ['group', 'supergroup']:
        await update.message.reply_text("ℹ️ /channels faqat shaxsiy chatda.")
        return

    admin_id = update.effective_user.id
    if not is_admin_user(admin_id):
        return

    if not context.args:
        await update.message.reply_text(
            "Foydalanish:\n"
            "- `/channels list` - Kanallar ro'yxati\n"
            "- `/channels add <channel_id>` yoki `/channels add @username` - Kanal qo'shish\n"
            "- `/channels remove <channel_id>` - Kanal o'chirish",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    action = context.args[0].lower().strip()
    if action == "list":
        channels = storage.get_required_channels()
        if not channels:
            await update.message.reply_text("📭 Majburiy kanallar yo'q.")
            return
        text = "📢 **Majburiy obuna kanallari:**\n\n"
        for i, ch in enumerate(channels, 1):
            ch_id = ch.get('channel_id')
            ch_username = ch.get('channel_username', '')
            ch_title = ch.get('channel_title', '')
            
            if ch_username:
                ch_link = f"@{ch_username}"
            else:
                ch_link = f"Channel {ch_id}"
            
            text += f"{i}. {ch_link}"
            if ch_title:
                text += f" - {ch_title}"
            text += f"\n   🆔 ID: `{ch_id}`\n\n"
        await safe_reply_text(update.message, text, parse_mode=ParseMode.MARKDOWN)
        return

    if action in ["add", "remove", "del", "delete"]:
        if len(context.args) < 2:
            await update.message.reply_text(
                "❌ Kanal ID yoki username kiriting.\n"
                "Masalan: `/channels add -1001234567890` yoki `/channels add @channel_username`",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        channel_input = " ".join(context.args[1:]).strip()
        
        if action == "add":
            channel_id = None
            channel_username = None
            channel_title = None
            
            # ID yoki username sifatida tekshirish
            try:
                # ID sifatida
                channel_id = int(channel_input)
            except ValueError:
                # Username sifatida
                username = channel_input.lstrip('@')
                try:
                    chat = await context.bot.get_chat(f"@{username}")
                    if chat.type not in ['channel', 'supergroup']:
                        await update.message.reply_text("❌ Bu kanal emas!")
                        return
                    channel_id = chat.id
                    channel_username = chat.username
                    channel_title = chat.title
                except Exception as e:
                    await update.message.reply_text(
                        f"❌ Kanal topilmadi!\n\n"
                        f"Kanal ID yoki username'ni to'g'ri kiriting.\n"
                        f"Masalan: `-1001234567890` yoki `@channel_username`",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return
            
            # Agar ID bo'lsa, kanal ma'lumotlarini olish
            if channel_id and not channel_title:
                try:
                    chat = await context.bot.get_chat(channel_id)
                    if chat.type not in ['channel', 'supergroup']:
                        await update.message.reply_text("❌ Bu kanal emas!")
                        return
                    channel_username = chat.username
                    channel_title = chat.title
                except Exception as e:
                    await update.message.reply_text(
                        f"❌ Kanal topilmadi: {str(e)[:100]}\n\n"
                        f"Kanal ID yoki username'ni to'g'ri kiriting.",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return
            
            # Kanalni qo'shish
            success = storage.add_required_channel(channel_id, channel_username, channel_title)
            if success:
                ch_name = channel_title or channel_username or f"Channel {channel_id}"
                await safe_reply_text(
                    update.message,
                    f"✅ Kanal qo'shildi: **{ch_name}** (`{channel_id}`)",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await update.message.reply_text("❌ Xatolik yuz berdi.")
            return

        # Remove action
        try:
            channel_id = int(channel_input)
        except ValueError:
            await update.message.reply_text(
                "❌ Kanal ID raqam bo'lishi kerak.\n"
                "Masalan: `/channels remove -1001234567890`",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        ok = storage.remove_required_channel(channel_id)
        await safe_reply_text(
            update.message,
            ("✅ Kanal o'chirildi: " if ok else "ℹ️ Kanal topilmadi: ") + f"`{channel_id}`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    await update.message.reply_text("❌ Noma'lum buyruq. `/channels list` deb ko'ring.", parse_mode=ParseMode.MARKDOWN)


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
    
    # Faqat shaxsiy chatda reply keyboard ko'rsatish
    if update.effective_chat.type == 'private':
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
    # Har bir update'da quiz session'larni tekshirish
    await advance_due_sessions(context)
    
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
    elif text == "⭐ VIP":
        from bot.handlers.admin import admin_vip_command
        await admin_vip_command(update, context)
    elif text == "➕ Create Quiz":
        from bot.handlers.admin import admin_create_quiz_command
        await admin_create_quiz_command(update, context)
    elif text == "📄 Fayl yuborish":
        if (is_admin_user(user_id) or is_sudo_user(user_id)) and update.effective_chat.type == 'private':
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
        if (is_admin_user(user_id) or is_sudo_user(user_id)) and update.effective_chat.type == 'private':
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
        return
    
    # Admin action'lar uchun tekshirish (avval, boshqa text handler'lardan oldin)
    if context.user_data.get('admin_action') == 'add_channel':
        logger.info(f"add_channel action detected: user_id={user_id}, text={text[:50]}")
        if update.effective_chat.type == 'private' and is_admin_user(user_id):
            channel_input = text.strip()
            
            if channel_input.lower() in ['cancel', 'bekor', 'stop', '/cancel']:
                context.user_data.pop('admin_action', None)
                await update.message.reply_text("❌ Bekor qilindi.")
                return
            
            channel_id = None
            channel_username = None
            channel_title = None
            
            # ID yoki username sifatida tekshirish
            try:
                # ID sifatida
                channel_id = int(channel_input)
            except ValueError:
                # Username sifatida
                username = channel_input.lstrip('@')
                try:
                    chat = await context.bot.get_chat(f"@{username}")
                    if chat.type not in ['channel', 'supergroup']:
                        await update.message.reply_text("❌ Bu kanal emas!")
                        return
                    channel_id = chat.id
                    channel_username = chat.username
                    channel_title = chat.title
                except Exception as e:
                    logger.error(f"Kanal topishda xatolik: {e}")
                    await update.message.reply_text(
                        f"❌ Kanal topilmadi!\n\n"
                        f"Kanal ID yoki username'ni to'g'ri kiriting.\n"
                        f"Masalan: `-1001234567890` yoki `@channel_username`",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return
            
            # Agar ID bo'lsa, kanal ma'lumotlarini olish
            if channel_id and not channel_title:
                try:
                    chat = await context.bot.get_chat(channel_id)
                    if chat.type not in ['channel', 'supergroup']:
                        await update.message.reply_text("❌ Bu kanal emas!")
                        return
                    channel_username = chat.username
                    channel_title = chat.title
                except Exception as e:
                    logger.error(f"Kanal ma'lumotlarini olishda xatolik: {e}")
                    await update.message.reply_text(
                        f"❌ Kanal topilmadi: {str(e)[:100]}\n\n"
                        f"Kanal ID yoki username'ni to'g'ri kiriting.",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return
            
            # Kanalni qo'shish
            success = storage.add_required_channel(channel_id, channel_username, channel_title)
            if success:
                ch_name = channel_title or channel_username or f"Channel {channel_id}"
                await update.message.reply_text(
                    f"✅ **Kanal qo'shildi!**\n\n"
                    f"📢 Kanal: {ch_name}\n"
                    f"🆔 ID: `{channel_id}`",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await update.message.reply_text("❌ Xatolik yuz berdi.")
            
            context.user_data.pop('admin_action', None)
            return
    
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
    # Championship schedule text qabul qilish
    elif context.user_data.get('championship_action') == 'schedule':
        try:
            from datetime import datetime
            import time as time_module
            
            if text.lower() == 'cancel':
                context.user_data.pop('championship_action', None)
                context.user_data.pop('championship_group_id', None)
                context.user_data.pop('championship_time_seconds', None)
                context.user_data.pop('championship_quiz_id', None)
                await update.message.reply_text("❌ Bekor qilindi.")
                return
            
            # Vaqt formatini parse qilish: DD.MM.YYYY HH:MM
            try:
                dt = datetime.strptime(text.strip(), "%d.%m.%Y %H:%M")
                start_time = dt.timestamp()
                
                if start_time <= time_module.time():
                    await update.message.reply_text("❌ Vaqt o'tmishda bo'lmasligi kerak!")
                    return
                
                group_chat_id = context.user_data.get('championship_group_id')
                time_seconds = context.user_data.get('championship_time_seconds')
                quiz_id = context.user_data.get('championship_quiz_id')
                
                if not all([group_chat_id, time_seconds, quiz_id]):
                    await update.message.reply_text("❌ Xatolik: ma'lumotlar topilmadi.")
                    return
                
                # Chempionatni rejalashtirish
                from bot.services.championship import start_championship
                success = await start_championship(context, group_chat_id, quiz_id, user_id, time_seconds, start_time)
                
                if success:
                    await update.message.reply_text(
                        f"✅ Chempionat rejalashtirildi!\n\n"
                        f"📅 Vaqt: {text}\n"
                        f"⚠️ Chempionat vaqtida guruhda boshqa quizlar o'tkazilmaydi!",
                        parse_mode=ParseMode.MARKDOWN
                    )
                else:
                    await update.message.reply_text("❌ Chempionatni rejalashtirishda xatolik!")
                
                context.user_data.pop('championship_action', None)
                context.user_data.pop('championship_group_id', None)
                context.user_data.pop('championship_time_seconds', None)
                context.user_data.pop('championship_quiz_id', None)
                return
                
            except ValueError:
                await update.message.reply_text(
                    "❌ Noto'g'ri format!\n\n"
                    "Format: `DD.MM.YYYY HH:MM`\n"
                    "Masalan: `05.01.2026 15:30`",
                    parse_mode=ParseMode.MARKDOWN
                )
                return
        except Exception as e:
            logger.error(f"Championship schedule xatolik: {e}", exc_info=True)
            await update.message.reply_text("❌ Xatolik yuz berdi.")
            return
    
    # Quiz add group action
    elif context.user_data.get('quiz_add_group_action'):
        quiz_id = context.user_data.get('quiz_add_group_action')
        quiz = storage.get_quiz(quiz_id)
        
        if not quiz:
            context.user_data.pop('quiz_add_group_action', None)
            await update.message.reply_text("❌ Quiz topilmadi.")
            return
        
        if text.lower() == 'cancel':
            context.user_data.pop('quiz_add_group_action', None)
            await update.message.reply_text("❌ Bekor qilindi.")
            return
        
        input_text = text.strip()
        group_id = None
        group_name = None
        
        # Avval ID sifatida tekshiramiz
        try:
            group_id = int(input_text)
        except ValueError:
            # Agar ID bo'lmasa, username sifatida qabul qilamiz
            # Username @ bilan boshlanadi yoki bo'lmasligi mumkin
            username = input_text.lstrip('@')
            
            try:
                # Username orqali guruhni topish
                chat = await context.bot.get_chat(f"@{username}")
                if chat.type not in ['group', 'supergroup']:
                    await update.message.reply_text("❌ Bu guruh emas!")
                    return
                
                group_id = chat.id
                group_name = chat.title or f"Group {group_id}"
            except Exception as e:
                await update.message.reply_text(
                    f"❌ Guruh topilmadi!\n\n"
                    f"Guruh ID yoki username'ni to'g'ri kiriting.\n"
                    f"Masalan: `-1001234567890` yoki `@guruh_username`",
                    parse_mode=ParseMode.MARKDOWN
                )
                return
        
        # Agar ID bo'lsa, guruh ma'lumotlarini olish
        if group_id and not group_name:
            try:
                chat = await context.bot.get_chat(group_id)
                if chat.type not in ['group', 'supergroup']:
                    await update.message.reply_text("❌ Bu guruh emas!")
                    return
                
                group_name = chat.title or f"Group {group_id}"
            except Exception as e:
                await update.message.reply_text(
                    f"❌ Guruh topilmadi: {str(e)[:100]}\n\n"
                    f"Guruh ID yoki username'ni to'g'ri kiriting.",
                    parse_mode=ParseMode.MARKDOWN
                )
                return
        
        # Guruhni qo'shish
        success = storage.add_quiz_allowed_group(quiz_id, group_id)
        if success:
            await update.message.reply_text(
                f"✅ Guruh qo'shildi!\n\n"
                f"📝 Quiz: {quiz.get('title', 'Quiz')}\n"
                f"👥 Guruh: {group_name}\n"
                f"🆔 ID: `{group_id}`",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text("❌ Xatolik: Quiz private emas yoki boshqa muammo.")
        
        context.user_data.pop('quiz_add_group_action', None)
        return
    
    # Broadcast text qabul qilish
    elif context.user_data.get('admin_action') in ['broadcast_users', 'broadcast_groups']:
        if is_admin_user(user_id) and update.effective_chat.type == 'private':
            # Cancel tekshiruvi
            if text.lower() in ['cancel', 'bekor', 'stop', '/cancel']:
                context.user_data.pop('admin_action', None)
                context.user_data.pop('admin_pending_text', None)
                from bot.utils.helpers import private_main_keyboard
                keyboard = private_main_keyboard(user_id)
                await update.message.reply_text("❌ Bekor qilindi.", reply_markup=keyboard)
                return
            
            admin_action = context.user_data.get('admin_action')
            pending_text = text.strip()
            if len(pending_text) < 1:
                await update.message.reply_text("❌ Xabar bo'sh bo'lmasin.")
                return

            context.user_data['admin_pending_text'] = pending_text
            # Debug log
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"Broadcast text saved: action={admin_action}, text_length={len(pending_text)}, user_data_keys={list(context.user_data.keys())}")
            
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
        if (is_admin_user(user_id) or is_sudo_user(user_id)) and update.effective_chat.type == 'private':
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
                ai_parser = AIParser(Config.DEEPSEEK_API_KEY, Config.DEEPSEEK_API_URL)
                
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
    # Rename quiz
    elif context.user_data.get('admin_action') == 'rename_quiz':
        if update.effective_chat.type == 'private':
            quiz_id = context.user_data.get('rename_quiz_id')
            if not quiz_id:
                context.user_data.pop('admin_action', None)
                await update.message.reply_text("❌ Quiz topilmadi. Qayta urinib ko'ring.")
                return
            
            quiz = storage.get_quiz(quiz_id)
            if not quiz:
                context.user_data.pop('admin_action', None)
                context.user_data.pop('rename_quiz_id', None)
                await update.message.reply_text("❌ Quiz topilmadi.")
                return
            
            creator_id = quiz.get('created_by')
            if creator_id != user_id and not is_admin_user(user_id):
                context.user_data.pop('admin_action', None)
                context.user_data.pop('rename_quiz_id', None)
                await update.message.reply_text("❌ Siz bu quizni nomini o'zgartira olmaysiz.")
                return
            
            new_title = text.strip()
            if len(new_title) < 1:
                await update.message.reply_text("❌ Nom bo'sh bo'lmasin.")
                return
            
            if len(new_title) > 200:
                await update.message.reply_text("❌ Nom juda uzun. Maksimum 200 belgi.")
                return
            
            # Update quiz title
            storage.update_quiz_title(quiz_id, new_title)
            
            context.user_data.pop('admin_action', None)
            context.user_data.pop('rename_quiz_id', None)
            
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            keyboard = [
                [InlineKeyboardButton("🚀 Boshlash", callback_data=f"quiz_menu_{quiz_id}")],
                [InlineKeyboardButton("📊 Ma'lumot", callback_data=f"quiz_info_{quiz_id}")]
            ]
            
            await safe_reply_text(
                update.message,
                f"✅ **Quiz nomi o'zgartirildi!**\n\n"
                f"Yangi nom: **{new_title}**\n"
                f"🆔 ID: `{quiz_id}`",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN
            )


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fayl qabul qilish va quiz yaratish"""
    track_update(update)
    message = update.message
    chat_type = update.effective_chat.type
    
    if chat_type in ['group', 'supergroup']:
        # Guruhda fayl qabul qilinmaydi
        return

    # Adminlar va sudo userlar uchun avtomatik tahlil qilish
    user_id = message.from_user.id
    is_admin = is_admin_user(user_id) or is_sudo_user(user_id)
    
    # Premium yoki quota tekshirish (adminlar va sudo userlar uchun emas)
    if not is_admin:
        is_allowed, error_msg = is_premium_or_has_quota(user_id)
        if not is_allowed:
            await message.reply_text(error_msg)
            return
    
    # Admin file action bo'lsa, action ni o'chirish
    if context.user_data.get('admin_action') == 'create_quiz_file':
        context.user_data.pop('admin_action', None)
    
    if not message.document:
        await message.reply_text("❌ Iltimos, fayl yuboring!")
        return
    
    # Cancel flag tekshiruvi
    if context.user_data.get('cancel_file_processing'):
        context.user_data.pop('cancel_file_processing', None)
        await message.reply_text("❌ Jarayon bekor qilindi.")
        return
    
    file = await context.bot.get_file(message.document.file_id)
    file_name = message.document.file_name
    file_extension = os.path.splitext(file_name)[1]
    
    # Cancel flag'ni o'rnatish
    context.user_data['file_processing'] = True
    context.user_data['file_processing_user'] = user_id
    
    status_msg = await message.reply_text(
        f"📥 **Fayl:** {file_name}\n\n🔄 Tahlil qilinmoqda...\n\n"
        f"❌ Bekor qilish: /cancel"
    )
    
    # Quiz yaratish jarayonini background task sifatida ishlatish
    # Bu botning boshqa commandlarni qabul qilishini ta'minlaydi
    asyncio.create_task(process_file_background(
        context, message, file, file_name, file_extension, status_msg, user_id
    ))


async def process_file_background(
    context: ContextTypes.DEFAULT_TYPE,
    message,
    file,
    file_name: str,
    file_extension: str,
    status_msg,
    user_id: int
):
    """Quiz yaratish jarayonini background'da bajarish"""

    last_percent = -1
    last_ts = 0.0
    
    async def update_progress(percent, text):
        nonlocal last_percent, last_ts
        try:
            # Cancel tekshiruvi
            if context.user_data.get('cancel_file_processing'):
                return
            
            now = time.time()
            percent = int(max(percent, last_percent))
            # Progress yangilanishini tezlashtirish - har 1 soniyada yoki foiz o'zgarganda
            if percent == last_percent and (now - last_ts) < 1.0:
                return
            last_percent = percent
            last_ts = now
            bar = "█" * (percent // 5) + "░" * (20 - percent // 5)
            await status_msg.edit_text(
                f"📥 **Fayl:** {file_name}\n\n[{bar}] {percent}%\n{text}\n\n"
                f"❌ Bekor qilish: /cancel"
            )
        except Exception as e:
            logger.debug(f"Progress update xatolik: {e}")
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
            # Algoritmik parser'larni sinab ko'rish
            algo_check: List[Dict] = []
            try:
                algo_check.extend(parse_tilde_quiz(text)[:5])
            except Exception as e:
                logger.debug(f"parse_tilde_quiz xatolik: {e}")
            try:
                algo_check.extend(parse_numbered_quiz(text)[:5])
            except Exception as e:
                logger.debug(f"parse_numbered_quiz xatolik: {e}")
            has_patterns = len(algo_check) >= 2
        
        # Agar hali ham pattern topilmasa, AI'ga yuborishga ruxsat berish
        # AI turli formatlarni aniqlay oladi
        if not has_patterns:
            # Fayl matnini tekshirish - ehtimol AI aniqlay oladi
            text_length = len(text) if text else 0
            if text_length > 100:  # Agar matn katta bo'lsa, AI'ga yuborishga ruxsat berish
                logger.info(f"Pattern topilmadi, lekin matn uzunligi {text_length} - AI'ga yuboriladi")
                has_patterns = True  # AI'ga yuborishga ruxsat berish
            else:
                await status_msg.edit_text(
                    "❌ Bu faylda test savollari aniqlanmadi.\n\n"
                    "✅ Qo'llab-quvvatlanadigan formatlar:\n"
                    "• 1) Savol? A) ... B) ... C) ... D) ...\n"
                    "• 1. Savol? 1) ... 2) ... 3) ... 4) ...\n"
                    "• Savol? ~ Variant1 ~ Variant2 ~ Variant3\n"
                    "• Savol? - Variant1 - Variant2 - Variant3\n"
                    "• Markdown, HTML va boshqa formatlar\n\n"
                    "ℹ️ Agar fayl juda katta bo'lsa, uni 2-3 qismga bo'lib yuboring.\n"
                    "💡 AI turli formatlarni aniqlay oladi - qayta urinib ko'ring."
                )
                context.user_data.pop('file_processing', None)
                return
        
        # AI analysis - check if we need to split into chunks
        # Chunk o'lchamini kamaytirish - 300 ta savol kamida 6 qismga bo'linishi uchun
        # 300 ta savol uchun kamida 6 qism: 300/6 = 50 savol per chunk
        # 50 savol * 600 belgi = 30000 belgi, lekin xavfsizlik uchun 10000 ga kamaytiramiz
        # Bu 300 ta savolni kamida 18 qismga bo'ladi (180000 / 10000 = 18)
        # Kichikroq chunk'lar AI timeout'larini kamaytiradi
        max_chars_per_chunk = min(Config.MAX_TEXT_CHARS_FOR_AI, 10000)  # Maksimal 10000 belgi per chunk
        text_length = len(text) if text else 0
        
        # If text is too large, split into chunks and process separately
        # Use a lower threshold to split more aggressively and avoid timeouts
        all_questions = []
        ai_title = ""
        chunk_results = []  # Track chunk processing results
        
        if text_length > max_chars_per_chunk:  # If larger than max, split it
            # Split text into chunks
            lines = text.splitlines()
            chunks = []
            current_chunk = []
            current_length = 0
            
            for line in lines:
                line_length = len(line) + 1  # +1 for newline
                if current_length + line_length > max_chars_per_chunk and current_chunk:
                    chunks.append("\n".join(current_chunk))
                    current_chunk = [line]
                    current_length = line_length
                else:
                    current_chunk.append(line)
                    current_length += line_length
            
            if current_chunk:
                chunks.append("\n".join(current_chunk))
            
            num_chunks = len(chunks)
            logger.info(f"Large file detected ({text_length} chars), splitting into {num_chunks} chunks")
            
            await update_progress(30, f"📦 Fayl {num_chunks} qismga bo'linmoqda...")
            
            ai_parser = AIParser(Config.DEEPSEEK_API_KEY, Config.DEEPSEEK_API_URL)
            
            # Process each chunk
            for chunk_idx, chunk_text in enumerate(chunks):
                # Cancel tekshiruvi
                if context.user_data.get('cancel_file_processing'):
                    await status_msg.edit_text("❌ Jarayon bekor qilindi.")
                    context.user_data.pop('cancel_file_processing', None)
                    context.user_data.pop('file_processing', None)
                    return
                
                base_progress = 30 + int((chunk_idx / num_chunks) * 40)
                await update_progress(
                    base_progress,
                    f"🤖 AI qism {chunk_idx + 1}/{num_chunks} ni tahlil qilmoqda..."
                )
                
                ai_started_at = time.time()
                heartbeat_stop = False
                
                async def chunk_progress_callback(percent, text):
                    """Progress callback for chunk processing"""
                    try:
                        if context.user_data.get('cancel_file_processing'):
                            return
                        # Map AI progress (0-100) to chunk progress range
                        chunk_progress = base_progress + int((percent / 100) * (40 / num_chunks))
                        display_text = f"🤖 Qism {chunk_idx + 1}/{num_chunks}: {text}"
                        await update_progress(chunk_progress, display_text)
                    except Exception as e:
                        logger.debug(f"Progress update xatolik: {e}")
                
                async def heartbeat():
                    while not heartbeat_stop:
                        if context.user_data.get('cancel_file_processing'):
                            return
                        elapsed = int(time.time() - ai_started_at)
                        # Update progress every 5 seconds
                        await asyncio.sleep(5)
                
                hb_task = asyncio.create_task(heartbeat())
                
                def cancel_check():
                    return context.user_data.get('cancel_file_processing', False)
                
                chunk_result = None
                
                # Try deepseek-chat first
                # Chunk'larda strict_correct=False - kichik chunk'larda to'g'ri javob topish qiyinroq
                try:
                    chunk_result = await asyncio.wait_for(
                        ai_parser.analyze_with_ai(
                            sanitize_ai_input(chunk_text),
                            progress_callback=chunk_progress_callback,  # Use progress callback
                            strict_correct=False,  # Chunk'larda qattiq tekshiruvni o'chirish
                            model="deepseek-chat",
                            cancel_check=cancel_check
                        ),
                        timeout=MAX_AI_SECONDS + 30  # Timeout'ni oshirish
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"AI (chat) timeout for chunk {chunk_idx + 1}/{num_chunks} (size: {len(chunk_text)} chars)")
                    await update_progress(
                        base_progress + int((40 / num_chunks) * 0.5),
                        f"🧠 Qism {chunk_idx + 1}/{num_chunks} uchun reasoner urinmoqda..."
                    )
                    # Try reasoner as fallback
                    try:
                        chunk_result = await asyncio.wait_for(
                            ai_parser.analyze_with_ai(
                                sanitize_ai_input(chunk_text),
                                progress_callback=chunk_progress_callback,
                                strict_correct=False,  # Chunk'larda qattiq tekshiruvni o'chirish
                                model="deepseek-reasoner",
                                cancel_check=cancel_check
                            ),
                            timeout=MAX_AI_SECONDS + 90  # Timeout'ni oshirish
                        )
                    except Exception as e:
                        logger.error(f"AI (reasoner) error for chunk {chunk_idx + 1}/{num_chunks}: {e}", exc_info=True)
                        chunk_result = None
                except Exception as e:
                    logger.error(f"AI (chat) error for chunk {chunk_idx + 1}/{num_chunks}: {e}", exc_info=True)
                    # Try reasoner as fallback even on error
                    try:
                        await update_progress(
                            base_progress + int((40 / num_chunks) * 0.5),
                            f"🧠 Qism {chunk_idx + 1}/{num_chunks} uchun reasoner urinmoqda..."
                        )
                        chunk_result = await asyncio.wait_for(
                            ai_parser.analyze_with_ai(
                                sanitize_ai_input(chunk_text),
                                progress_callback=chunk_progress_callback,
                                strict_correct=False,  # Chunk'larda qattiq tekshiruvni o'chirish
                                model="deepseek-reasoner",
                                cancel_check=cancel_check
                            ),
                            timeout=MAX_AI_SECONDS + 90  # Timeout'ni oshirish
                        )
                    except Exception as e2:
                        logger.error(f"AI (reasoner) error for chunk {chunk_idx + 1}/{num_chunks}: {e2}", exc_info=True)
                        chunk_result = None
                
                heartbeat_stop = True
                try:
                    hb_task.cancel()
                except Exception:
                    pass
                
                if chunk_result and chunk_result.get("questions"):
                    chunk_questions = validate_questions(chunk_result.get("questions", []), require_correct=False)
                    
                    # Har bir savol topilganda xabar berish
                    for q_idx, question in enumerate(chunk_questions, 1):
                        total_found = len(all_questions) + q_idx
                        await update_progress(
                            30 + int(((chunk_idx + 1) / num_chunks) * 40),
                            f"✅ {total_found} ta savol topildi! (Qism {chunk_idx + 1}/{num_chunks})"
                        )
                        await asyncio.sleep(0.1)  # Kichik kechikish - xabarlar ko'rinishi uchun
                    
                    all_questions.extend(chunk_questions)
                    if not ai_title and chunk_result.get("title"):
                        ai_title = chunk_result.get("title", "").strip()
                    logger.info(f"Chunk {chunk_idx + 1}/{num_chunks}: {len(chunk_questions)} questions extracted")
                    chunk_results.append({
                        'chunk': chunk_idx + 1,
                        'success': True,
                        'questions': len(chunk_questions),
                        'chunk_size': len(chunk_text)
                    })
                    await update_progress(
                        30 + int(((chunk_idx + 1) / num_chunks) * 40),
                        f"✅ Qism {chunk_idx + 1}/{num_chunks} tayyor ({len(chunk_questions)} savol, jami: {len(all_questions)} ta)"
                    )
                else:
                    # Log why chunk failed
                    if chunk_result is None:
                        reason = "AI javob bermadi"
                        # Chunk matnini tekshirish
                        chunk_preview = chunk_text[:200] if chunk_text else ""
                        logger.warning(f"Chunk {chunk_idx + 1}/{num_chunks} failed: {reason} (size: {len(chunk_text)} chars, preview: {chunk_preview[:100]}...)")
                    elif not chunk_result.get("questions"):
                        reason = "AI savollar topa olmadi"
                        logger.warning(f"Chunk {chunk_idx + 1}/{num_chunks} failed: {reason} (AI returned empty questions)")
                    else:
                        reason = "Noma'lum xatolik"
                        logger.warning(f"Chunk {chunk_idx + 1}/{num_chunks} failed: {reason} (result: {chunk_result})")
                    
                    chunk_results.append({
                        'chunk': chunk_idx + 1,
                        'success': False,
                        'questions': 0,
                        'reason': reason,
                        'chunk_size': len(chunk_text)
                    })
                    await update_progress(
                        30 + int(((chunk_idx + 1) / num_chunks) * 40),
                        f"⚠️ Qism {chunk_idx + 1}/{num_chunks} da savollar topilmadi"
                    )
            
            # Combine all questions
            questions = all_questions
            if not ai_title:
                ai_title = file_name
            
            logger.info(f"Large file processing complete: {len(questions)} questions from {num_chunks} chunks")
            
            # Check if we got any questions
            if not questions or len(questions) < MIN_QUESTIONS_REQUIRED:
                error_text = "❌ AI fayldan savollarni ajrata olmadi.\n\n"
                error_text += f"📊 Tahlil natijasi:\n"
                error_text += f"• Qismlar soni: {num_chunks}\n"
                error_text += f"• Topilgan savollar: {len(questions)} ta\n"
                error_text += f"• Minimum talab: {MIN_QUESTIONS_REQUIRED} ta\n\n"
                
                # Show chunk results
                if chunk_results:
                    error_text += "📋 Qismlar natijasi:\n"
                    for result in chunk_results:
                        if result['success']:
                            error_text += f"• Qism {result['chunk']}: ✅ {result['questions']} ta savol topildi\n"
                        else:
                            error_text += f"• Qism {result['chunk']}: ❌ {result.get('reason', 'Xatolik')}\n"
                    error_text += "\n"
                
                error_text += "ℹ️ Iltimos, quyidagilarni tekshiring:\n"
                error_text += "• Savollar va variantlar aniq ko'rinib turadimi?\n"
                error_text += "• Format: 1) Savol? A) ... B) ... C) ... D) ...\n"
                error_text += "• Fayl matnida test savollari borligini tekshiring\n"
                
                if len(questions) > 0:
                    error_text += f"\n💡 Topildi: {len(questions)} ta savol, lekin minimum {MIN_QUESTIONS_REQUIRED} ta kerak.\n"
                else:
                    error_text += "\n💡 AI hech qanday savol topa olmadi. Fayl formatini tekshiring.\n"
                    # Check if chunks have valid question patterns
                    has_patterns_in_chunks = False
                    try:
                        for result in chunk_results:
                            if result.get('chunk_size', 0) > 0:
                                # Check if chunk has question patterns - use text sample instead
                                chunk_idx_for_sample = result['chunk'] - 1
                                if chunk_idx_for_sample < len(chunks):
                                    chunk_text_sample = chunks[chunk_idx_for_sample][:500]
                                    if chunk_text_sample:
                                        import re
                                        question_patterns = [
                                            r'\d+[\)\.]\s*[^\n]+\?',
                                            r'[A-Z][\)\.]\s*[^\n]+',
                                            r'\d+\.\s*[^\n]+\?',
                                        ]
                                        for pattern in question_patterns:
                                            if re.search(pattern, chunk_text_sample, re.IGNORECASE):
                                                has_patterns_in_chunks = True
                                                break
                                        if has_patterns_in_chunks:
                                            break
                    except Exception as e:
                        logger.debug(f"Error checking chunk patterns: {e}")
                    
                    if has_patterns_in_chunks:
                        error_text += "\n⚠️ Faylda test savollari formati topildi, lekin AI ajrata olmadi.\n"
                        error_text += "   Ehtimol savollar juda noaniq yoki format noto'g'ri.\n"
                
                await status_msg.edit_text(error_text)
                context.user_data.pop('file_processing', None)
                return
            
            await update_progress(70, f"✅ {len(questions)} ta savol topildi ({num_chunks} qismdan)")
            
        else:
            # Normal processing for smaller files
            ai_text = sanitize_ai_input(text)
            await update_progress(30, "🤖 AI savollarni ajratmoqda...")
            ai_parser = AIParser(Config.DEEPSEEK_API_KEY, Config.DEEPSEEK_API_URL)
            ai_started_at = time.time()
            heartbeat_stop = False

            # Enhanced progress callback that shows real-time updates
            last_progress_update = {'percent': 30, 'text': 'AI savollarni ajratmoqda...', 'time': time.time()}
            
            async def enhanced_progress_callback(percent, text):
                """Enhanced progress callback with real-time updates"""
                try:
                    if context.user_data.get('cancel_file_processing'):
                        return
                    now = time.time()
                    # Update at least every 2 seconds or when percent changes significantly
                    if now - last_progress_update['time'] >= 2 or abs(percent - last_progress_update['percent']) >= 5:
                        # Map AI progress to our progress range (30-70%)
                        progress_percent = 30 + int((percent / 100) * 40)
                        await update_progress(progress_percent, f"🤖 {text}")
                        last_progress_update['percent'] = percent
                        last_progress_update['text'] = text
                        last_progress_update['time'] = now
                except Exception as e:
                    logger.debug(f"Progress update xatolik: {e}")

            async def heartbeat():
                while not heartbeat_stop:
                    # Cancel tekshiruvi
                    if context.user_data.get('cancel_file_processing'):
                        heartbeat_stop = True
                        break
                    
                    elapsed = int(time.time() - ai_started_at)
                    # Progress foizini dinamik ravishda oshirish (30% dan 90% gacha)
                    # Maksimum 180 soniya (3 daqiqa) deb hisoblaymiz
                    # Only update if AI callback hasn't updated recently
                    if time.time() - last_progress_update['time'] > 3:
                        progress_percent = min(30 + int((elapsed / 180) * 60), 90)
                        await update_progress(progress_percent, f"⏳ AI tahlil qilmoqda... ({elapsed}s)")
                    await asyncio.sleep(5)  # 5 soniyada bir marta yangilash

            hb_task = asyncio.create_task(heartbeat())
            
            ai_result = None
            
            # Cancel check funksiyasi
            def cancel_check():
                return context.user_data.get('cancel_file_processing', False)
            
            # Try deepseek-chat first
            try:
                # Cancel tekshiruvi
                if context.user_data.get('cancel_file_processing'):
                    heartbeat_stop = True
                    try:
                        hb_task.cancel()
                    except Exception:
                        pass
                    await status_msg.edit_text("❌ Jarayon bekor qilindi.")
                    context.user_data.pop('cancel_file_processing', None)
                    context.user_data.pop('file_processing', None)
                    return
                
                # Event loop'ga boshqa task'larga imkoniyat berish - bot boshqa commandlarni qabul qilishda davom etadi
                await asyncio.sleep(0)
                
                ai_result = await asyncio.wait_for(
                    ai_parser.analyze_with_ai(ai_text, progress_callback=enhanced_progress_callback, strict_correct=True, model="deepseek-chat", cancel_check=cancel_check),
                    timeout=MAX_AI_SECONDS
                )
            except asyncio.TimeoutError:
                logger.error(f"AI (chat) timeout after {MAX_AI_SECONDS}s for file={file_name}")
                await status_msg.edit_text(
                    f"❌ AI javob kutish vaqti tugadi ({MAX_AI_SECONDS}s).\n\n"
                    f"💡 Yechimlar:\n"
                    f"• Faylni kichikroq qismlarga bo'lib yuboring\n"
                    f"• Yoki qayta urinib ko'ring"
                )
                context.user_data.pop('file_processing', None)
                ai_result = None
            except Exception as e:
                logger.error(f"AI (chat) error: {e}", exc_info=True)
                await status_msg.edit_text(
                    f"❌ AI xatolik: {str(e)[:100]}\n\n"
                    f"💡 Qayta urinib ko'ring yoki faylni kichikroq qismlarga bo'ling."
                )
                context.user_data.pop('file_processing', None)
                ai_result = None
            
            # Cancel tekshiruvi
            if context.user_data.get('cancel_file_processing'):
                heartbeat_stop = True
                try:
                    hb_task.cancel()
                except Exception:
                    pass
                await status_msg.edit_text("❌ Jarayon bekor qilindi.")
                context.user_data.pop('cancel_file_processing', None)
                context.user_data.pop('file_processing', None)
                return
            
            # Try deepseek-reasoner if needed
            if not ai_result or len(ai_result.get("questions", [])) < MIN_QUESTIONS_REQUIRED:
                # Cancel tekshiruvi
                if context.user_data.get('cancel_file_processing'):
                    heartbeat_stop = True
                    try:
                        hb_task.cancel()
                    except Exception:
                        pass
                    await status_msg.edit_text("❌ Jarayon bekor qilindi.")
                    context.user_data.pop('cancel_file_processing', None)
                    context.user_data.pop('file_processing', None)
                    return
                
                await update_progress(45, "🧠 AI (reasoner) savollarni ajratmoqda...")
                ai_started_at = time.time()
                last_progress_update['time'] = time.time()  # Reset for reasoner
                try:
                    # Cancel check funksiyasi
                    def cancel_check():
                        return context.user_data.get('cancel_file_processing', False)
                    
                    async def reasoner_progress_callback(percent, text):
                        """Progress callback for reasoner"""
                        try:
                            if context.user_data.get('cancel_file_processing'):
                                return
                            now = time.time()
                            if now - last_progress_update['time'] >= 2 or abs(percent - last_progress_update['percent']) >= 5:
                                # Map AI progress to our progress range (45-70%)
                                progress_percent = 45 + int((percent / 100) * 25)
                                await update_progress(progress_percent, f"🧠 {text}")
                                last_progress_update['percent'] = percent
                                last_progress_update['text'] = text
                                last_progress_update['time'] = now
                        except Exception as e:
                            logger.debug(f"Progress update xatolik: {e}")
                    
                    ai_result = await asyncio.wait_for(
                        ai_parser.analyze_with_ai(ai_text, progress_callback=reasoner_progress_callback, strict_correct=True, model="deepseek-reasoner", cancel_check=cancel_check),
                        timeout=MAX_AI_SECONDS + 60
                    )
                except asyncio.TimeoutError:
                    logger.error(f"AI (reasoner) timeout for file={file_name}")
                    await status_msg.edit_text(
                        f"❌ AI (reasoner) javob kutish vaqti tugadi.\n\n"
                        f"💡 Yechimlar:\n"
                        f"• Faylni kichikroq qismlarga bo'lib yuboring\n"
                        f"• Yoki qayta urinib ko'ring"
                    )
                    context.user_data.pop('file_processing', None)
                    ai_result = None
                except Exception as e:
                    logger.error(f"AI (reasoner) error: {e}", exc_info=True)
                    await status_msg.edit_text(
                        f"❌ AI (reasoner) xatolik: {str(e)[:100]}\n\n"
                        f"💡 Qayta urinib ko'ring yoki faylni kichikroq qismlarga bo'ling."
                    )
                    context.user_data.pop('file_processing', None)
                    ai_result = None
            
            heartbeat_stop = True
            try:
                hb_task.cancel()
            except Exception:
                pass
            
            # Cancel tekshiruvi
            if context.user_data.get('cancel_file_processing'):
                await status_msg.edit_text("❌ Jarayon bekor qilindi.")
                context.user_data.pop('cancel_file_processing', None)
                context.user_data.pop('file_processing', None)
                return
            
            if not ai_result or not ai_result.get("questions"):
                # AI xatolik holatini aniqlash
                error_details = []
                if not ai_result:
                    error_details.append("• AI javob bermadi yoki timeout bo'ldi")
                elif ai_result.get("questions") == []:
                    error_details.append("• AI savollar topa olmadi")
                
                # Fayl matnini tekshirish
                text_preview = text[:200] if text else ""
                has_questions_pattern = False
                if text:
                    # Savol patternlarini tekshirish
                    import re
                    question_patterns = [
                        r'\d+[\)\.]\s*[^\n]+\?',  # 1) Savol?
                        r'[A-Z][\)\.]\s*[^\n]+',  # A) Variant
                        r'\d+\.\s*[^\n]+\?',      # 1. Savol?
                    ]
                    for pattern in question_patterns:
                        if re.search(pattern, text, re.IGNORECASE):
                            has_questions_pattern = True
                            break
                
                error_text = "❌ AI fayldan savollarni ajrata olmadi.\n\n"
                error_text += f"📊 Fayl ma'lumotlari:\n"
                error_text += f"• Fayl hajmi: {text_length:,} belgi\n"
                
                if error_details:
                    error_text += f"\n📋 Xatolik tafsilotlari:\n"
                    error_text += "\n".join(error_details) + "\n"
                
                error_text += "\nℹ️ Iltimos, quyidagilarni tekshiring:\n"
                error_text += "• Savollar va variantlar aniq ko'rinib turadimi?\n"
                
                if text_length > max_chars_per_chunk:
                    error_text += f"• Fayl juda katta ({text_length:,} belgi). Avtomatik bo'linishi kerak edi.\n"
                else:
                    error_text += "• Format: 1) Savol? A) ... B) ... C) ... D) ...\n"
                
                if not has_questions_pattern:
                    error_text += "• ⚠️ Faylda test savollari formatida ma'lumot topilmadi\n"
                    error_text += "  (Savollar raqam bilan boshlanishi va '?' bilan tugashi kerak)\n"
                else:
                    error_text += "• ✅ Faylda test savollari formati topildi, lekin AI ajrata olmadi\n"
                    error_text += "  (Ehtimol savollar juda noaniq yoki format noto'g'ri)\n"
                
                await status_msg.edit_text(error_text)
                context.user_data.pop('file_processing', None)
                return
            
            ai_title = (ai_result.get("title") or "").strip()
            raw_questions = ai_result.get("questions", [])
            
            # Har bir savol validate qilinganda xabar berish
            questions = []
            for q_idx, raw_q in enumerate(raw_questions, 1):
                try:
                    validated_q = validate_questions([raw_q], require_correct=False)
                    if validated_q:
                        questions.extend(validated_q)
                        await update_progress(
                            70,
                            f"✅ {len(questions)} ta savol topildi!"
                        )
                        await asyncio.sleep(0.1)  # Kichik kechikish - xabarlar ko'rinishi uchun
                except Exception as e:
                    logger.debug(f"Question validation error: {e}")
                    continue
            
            if len(questions) < MIN_QUESTIONS_REQUIRED:
                await status_msg.edit_text(
                    "❌ AI yetarli savollarni ajrata olmadi.\n\n"
                    f"Topildi: {len(questions)} ta (minimum: {MIN_QUESTIONS_REQUIRED})\n\n"
                    "ℹ️ Formatni aniqroq qilib qayta yuboring."
                )
                context.user_data.pop('file_processing', None)
                return
            
            # Don't truncate - we'll split into multiple quizzes if needed
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
            await update_progress(75, f"🧠 To'g'ri javoblar aniqlanmoqda... ({len(missing_idxs)} ta savol)")
            
            chunk_size = 10
            total_missing = len(missing_idxs)
            solved = 0
            
            # Birinchi bosqich: deepseek-chat bilan chunk bo'yicha javob qidirish
            for start in range(0, total_missing, chunk_size):
                chunk_indices = missing_idxs[start:start + chunk_size]
                chunk_questions = [questions[i] for i in chunk_indices]

                # Progress update - real-time update_progress ishlatiladi

                # Cancel tekshiruvi
                if context.user_data.get('cancel_file_processing'):
                    await status_msg.edit_text("❌ Jarayon bekor qilindi.")
                    context.user_data.pop('cancel_file_processing', None)
                    context.user_data.pop('file_processing', None)
                    return
                
                # Cancel check funksiyasi
                def cancel_check():
                    return context.user_data.get('cancel_file_processing', False)
                
                # Event loop'ga boshqa task'larga imkoniyat berish
                await asyncio.sleep(0)
                
                # Progress: deepseek-chat javob qidirmoqda
                await update_progress(
                    75 + int((solved / total_missing) * 10) if total_missing > 0 else 75,
                    f"🔍 {len(chunk_questions)} ta savol uchun javob qidirilmoqda... (chat)"
                )
                
                result = await ai_parser.pick_correct_answers(
                    chunk_questions, 
                    model="deepseek-chat", 
                    cancel_check=cancel_check,
                    progress_callback=lambda p, t: update_progress(
                        75 + int((solved / total_missing) * 10) if total_missing > 0 else 75,
                        t
                    )
                )
                
                # Javoblar topilganini tekshirish
                if result:
                    # result dict yoki list bo'lishi mumkin
                    if isinstance(result, dict):
                        answers = result.get('answers', [])
                        uncertain_indices = result.get('uncertain', [])  # Shubhali savollar
                    else:
                        answers = result
                        uncertain_indices = []

                    if answers and len(answers) == len(chunk_indices):
                        # Javoblar topildi, lekin None bo'lganlarini tekshirish kerak
                        failed_indices = []
                        for local_i, ans_idx in enumerate(answers):
                            # Cancel tekshiruvi
                            if context.user_data.get('cancel_file_processing'):
                                await status_msg.edit_text("❌ Jarayon bekor qilindi.")
                                context.user_data.pop('cancel_file_processing', None)
                                context.user_data.pop('file_processing', None)
                                return
                            
                            gi = chunk_indices[local_i]
                            opts = questions[gi].get("options") or []
                            
                            # Agar bu savol shubhali deb belgilangan bo'lsa, reasonerga uzatish
                            if local_i in uncertain_indices:
                                failed_indices.append((local_i, gi))
                                logger.info(f"Savol {gi+1} shubhali deb belgilandi - reasonerga uzatiladi")
                            elif isinstance(opts, list) and ans_idx is not None and 0 <= ans_idx < len(opts):
                                questions[gi]["correct_answer"] = ans_idx
                                solved += 1
                                # Real-time progress: har bir javob topilganda
                                await update_progress(
                                    75 + int((solved / total_missing) * 20) if total_missing > 0 else 75,
                                    f"✅ {solved} ta javob topildi! ({solved}/{total_missing})"
                                )
                            else:
                                failed_indices.append((local_i, gi))
                    else:
                        # Agar javoblar to'liq bo'lmasa, barchasini reasonerga uzatish
                        failed_indices = [(i, chunk_indices[i]) for i in range(len(chunk_indices))]
                    
                    # 2-bosqich: Agar ayrim savollarga javob topilmagan bo'lsa, deepseek-reasoner bilan urinish
                    if failed_indices:
                        failed_questions = [chunk_questions[local_i] for local_i, _ in failed_indices]
                        await update_progress(
                            75 + int((solved / total_missing) * 15) if total_missing > 0 else 75,
                            f"🔍 {len(failed_questions)} ta savol uchun reasoner urinmoqda..."
                        )
                        
                        # Cancel check funksiyasi
                        def cancel_check():
                            return context.user_data.get('cancel_file_processing', False)
                        
                        failed_answers = await ai_parser.pick_correct_answers(failed_questions, model="deepseek-reasoner", detailed_prompt=True, cancel_check=cancel_check)
                        
                        # Agar hali ham ba'zi javoblar topilmasa, har birini alohida yuborish
                        still_failed = []
                        # failed_answers dict yoki list bo'lishi mumkin
                        if failed_answers:
                            if isinstance(failed_answers, dict):
                                failed_answers_list = failed_answers.get('answers', [])
                            else:
                                failed_answers_list = failed_answers
                            
                            if failed_answers_list and len(failed_answers_list) == len(failed_indices):
                                for (local_i, gi), ans_idx in zip(failed_indices, failed_answers_list):
                                    # Cancel tekshiruvi
                                    if context.user_data.get('cancel_file_processing'):
                                        await status_msg.edit_text("❌ Jarayon bekor qilindi.")
                                        context.user_data.pop('cancel_file_processing', None)
                                        context.user_data.pop('file_processing', None)
                                        return
                                    
                                    opts = questions[gi].get("options") or []
                                    if isinstance(opts, list) and ans_idx is not None and 0 <= ans_idx < len(opts):
                                        questions[gi]["correct_answer"] = ans_idx
                                        solved += 1
                                        # Real-time progress: har bir javob topilganda
                                        await update_progress(
                                            75 + int((solved / total_missing) * 20) if total_missing > 0 else 75,
                                            f"✅ {solved} ta javob topildi! ({solved}/{total_missing})"
                                        )
                                    else:
                                        still_failed.append((local_i, gi))
                        else:
                            still_failed = failed_indices
                        
                        # 3-bosqich: Agar hali ham topilmagan savollar bo'lsa, har birini alohida yuborish
                        if still_failed:
                            await update_progress(
                                75 + int((solved / total_missing) * 15) if total_missing > 0 else 75,
                                f"🔍 {len(still_failed)} ta savol uchun alohida reasoner urinmoqda..."
                            )
                            
                        for local_i, gi in still_failed:
                            # Cancel tekshiruvi
                            if context.user_data.get('cancel_file_processing'):
                                await status_msg.edit_text("❌ Jarayon bekor qilindi.")
                                context.user_data.pop('cancel_file_processing', None)
                                context.user_data.pop('file_processing', None)
                                return
                            
                            single_question = [questions[gi]]
                            # Cancel check funksiyasi
                            def cancel_check():
                                return context.user_data.get('cancel_file_processing', False)
                            
                            single_answer = await ai_parser.pick_correct_answers(single_question, model="deepseek-reasoner", detailed_prompt=True, cancel_check=cancel_check)
                            if single_answer and len(single_answer) == 1:
                                ans_idx = single_answer[0]
                                opts = questions[gi].get("options") or []
                                if isinstance(opts, list) and ans_idx is not None and 0 <= ans_idx < len(opts):
                                    questions[gi]["correct_answer"] = ans_idx
                                    solved += 1
                                    # Real-time progress: har bir javob topilganda
                                    await update_progress(
                                        75 + int((solved / total_missing) * 20) if total_missing > 0 else 75,
                                        f"✅ {solved} ta javob topildi! ({solved}/{total_missing})"
                                    )
                            # Agar hali ham topilmasa, savol to'g'ri javobsiz qoladi (oddiy poll sifatida ishlaydi)
                else:
                    # 2-bosqich: Agar deepseek-chat umuman javob qaytarmasa yoki to'liq bo'lmasa, deepseek-reasoner bilan urinish
                    await update_progress(
                        75 + int((solved / total_missing) * 15) if total_missing > 0 else 75,
                        f"🔍 {len(chunk_questions)} ta savol uchun reasoner urinmoqda..."
                    )
                    
                    # Cancel check funksiyasi
                    def cancel_check():
                        return context.user_data.get('cancel_file_processing', False)
                    
                    answers = await ai_parser.pick_correct_answers(chunk_questions, model="deepseek-reasoner", detailed_prompt=True, cancel_check=cancel_check)
                    
                    if answers and len(answers) == len(chunk_indices):
                        failed_in_chunk = []
                        for local_i, ans_idx in enumerate(answers):
                            gi = chunk_indices[local_i]
                            opts = questions[gi].get("options") or []
                            if isinstance(opts, list) and ans_idx is not None and 0 <= ans_idx < len(opts):
                                questions[gi]["correct_answer"] = ans_idx
                                solved += 1
                                # Real-time progress: har bir javob topilganda
                                await update_progress(
                                    75 + int((solved / total_missing) * 20) if total_missing > 0 else 75,
                                    f"✅ {solved} ta javob topildi! ({solved}/{total_missing})"
                                )
                            else:
                                failed_in_chunk.append((local_i, gi))
                        
                        # 3-bosqich: Agar hali ham topilmagan savollar bo'lsa, har birini alohida yuborish
                        if failed_in_chunk:
                            await update_progress(
                                75 + int((solved / total_missing) * 15) if total_missing > 0 else 75,
                                f"🔍 {len(failed_in_chunk)} ta savol uchun alohida reasoner urinmoqda..."
                            )
                            
                        for local_i, gi in failed_in_chunk:
                            # Cancel tekshiruvi
                            if context.user_data.get('cancel_file_processing'):
                                await status_msg.edit_text("❌ Jarayon bekor qilindi.")
                                context.user_data.pop('cancel_file_processing', None)
                                context.user_data.pop('file_processing', None)
                                return
                            
                            single_question = [questions[gi]]
                            # Cancel check funksiyasi
                            def cancel_check():
                                return context.user_data.get('cancel_file_processing', False)
                            
                            single_answer = await ai_parser.pick_correct_answers(single_question, model="deepseek-reasoner", detailed_prompt=True, cancel_check=cancel_check)
                            if single_answer and len(single_answer) == 1:
                                ans_idx = single_answer[0]
                                opts = questions[gi].get("options") or []
                                if isinstance(opts, list) and ans_idx is not None and 0 <= ans_idx < len(opts):
                                    questions[gi]["correct_answer"] = ans_idx
                                    solved += 1
                                    # Real-time progress: har bir javob topilganda
                                    await update_progress(
                                        75 + int((solved / total_missing) * 20) if total_missing > 0 else 75,
                                        f"✅ {solved} ta javob topildi! ({solved}/{total_missing})"
                                    )
                            # Agar hali ham topilmasa, savol to'g'ri javobsiz qoladi (oddiy poll sifatida ishlaydi)
            
            # Final progress update
            await update_progress(95, f"✅ To'g'ri javoblar: {solved}/{total_missing} topildi")

        # Cancel tekshiruvi
        if context.user_data.get('cancel_file_processing'):
            await status_msg.edit_text("❌ Jarayon bekor qilindi.")
            context.user_data.pop('cancel_file_processing', None)
            context.user_data.pop('file_processing', None)
            return
        
        # Cancel tekshiruvi
        if context.user_data.get('cancel_file_processing'):
            await status_msg.edit_text("❌ Jarayon bekor qilindi.")
            context.user_data.pop('cancel_file_processing', None)
            context.user_data.pop('file_processing', None)
            return
        
        # To'g'ri javoblar statistikasi
        with_correct = [q for q in questions if q.get("correct_answer") is not None]
        without_correct = len(questions) - len(with_correct)
        
        # Agar ayrim savollarga javob topilmasa, oddiy poll sifatida yaratishga ruxsat berish
        if without_correct > 0:
            logger.info(f"Quiz yaratilmoqda: {len(with_correct)} ta to'g'ri javobli, {without_correct} ta javobsiz savol")
            # To'g'ri javobsiz savollar oddiy poll sifatida ishlaydi (send_quiz_question funksiyasida)
        
        # Agar barcha savollar to'g'ri javobsiz bo'lsa ham, oddiy poll sifatida yaratishga ruxsat berish
        # REQUIRE_CORRECT_ANSWER tekshiruvi o'chirildi - endi to'g'ri javobsiz savollar ham qabul qilinadi
        if without_correct > 0:
            try:
                await context.bot.send_message(
                    chat_id=message.chat_id,
                    text=f"ℹ️ {without_correct} ta savolda to'g'ri javob topilmadi — ular oddiy poll sifatida ishlaydi."
                )
            except Exception:
                pass

        if len(questions) < MIN_QUESTIONS_REQUIRED:
            await status_msg.edit_text(
                "❌ Fayldan yetarli test savollari topilmadi.\n\n"
                "Iltimos, savollar+variantlar aniq ko'rinadigan formatda yuboring."
            )
            return

        user_id = message.from_user.id
        chat_id = message.chat_id
        title_to_save = (ai_title[:100] if ai_title else file_name)
        
        # Check if we need to split into multiple quizzes
        chunk_size = TARGET_QUESTIONS_PER_QUIZ if TARGET_QUESTIONS_PER_QUIZ > 0 else 50
        # Ensure chunk_size doesn't exceed MAX_QUESTIONS_PER_QUIZ
        chunk_size = min(chunk_size, MAX_QUESTIONS_PER_QUIZ) if MAX_QUESTIONS_PER_QUIZ > 0 else chunk_size
        total_questions = len(questions)
        
        # If questions exceed target limit, split into multiple quizzes
        if total_questions > chunk_size:
            # Split questions into chunks
            num_chunks = (total_questions + chunk_size - 1) // chunk_size
            created_quizzes = []
            
            await update_progress(96, f"📦 {num_chunks} ta quiz yaratilmoqda...")
            
            for chunk_idx in range(num_chunks):
                # Cancel tekshiruvi
                if context.user_data.get('cancel_file_processing'):
                    await status_msg.edit_text("❌ Jarayon bekor qilindi.")
                    context.user_data.pop('cancel_file_processing', None)
                    context.user_data.pop('file_processing', None)
                    return
                
                start_idx = chunk_idx * chunk_size
                end_idx = min(start_idx + chunk_size, total_questions)
                chunk_questions = questions[start_idx:end_idx]
                
                # Create quiz for this chunk
                quiz_content = json.dumps(chunk_questions, sort_keys=True)
                quiz_id = hashlib.md5(quiz_content.encode()).hexdigest()[:12]
                
                # Create title with part number
                if num_chunks > 1:
                    chunk_title = f"{title_to_save} (Qism {chunk_idx + 1}/{num_chunks})"
                else:
                    chunk_title = title_to_save
                
                storage.save_quiz(quiz_id, chunk_questions, user_id, chat_id, chunk_title)
                created_quizzes.append({
                    'quiz_id': quiz_id,
                    'title': chunk_title,
                    'count': len(chunk_questions)
                })
                
                # Progress update
                await update_progress(
                    96 + int((chunk_idx + 1) / num_chunks * 3),
                    f"✅ Quiz {chunk_idx + 1}/{num_chunks} yaratildi ({len(chunk_questions)} savol)"
                )
            
            # Show all created quizzes
            text = f"✅ **{num_chunks} ta quiz yaratildi!**\n\n"
            text += f"📝 Jami savollar: {total_questions} ta\n"
            text += f"📦 Har bir quiz: {chunk_size} ta savol\n\n"
            text += "**Yaratilgan quizlar:**\n\n"
            
            keyboard = []
            for idx, quiz_info in enumerate(created_quizzes, 1):
                text += f"{idx}. {quiz_info['title']}\n"
                text += f"   📝 {quiz_info['count']} savol | 🆔 `{quiz_info['quiz_id']}`\n\n"
                
                # Add button for first quiz
                if idx == 1:
                    keyboard.append([
                        InlineKeyboardButton(
                            f"🚀 {quiz_info['title'][:30]}...",
                            callback_data=f"quiz_menu_{quiz_info['quiz_id']}"
                        )
                    ])
            
            # Add buttons for all quizzes
            if len(created_quizzes) > 1:
                for idx, quiz_info in enumerate(created_quizzes[1:6], 2):  # Show up to 5 more quizzes
                    keyboard.append([
                        InlineKeyboardButton(
                            f"📝 Quiz {idx} ({quiz_info['count']} savol)",
                            callback_data=f"quiz_menu_{quiz_info['quiz_id']}"
                        )
                    ])
            
            reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
            
            await status_msg.edit_text(
                text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
            
        else:
            # Single quiz - original behavior
            # Apply max limit check
            if total_questions > MAX_QUESTIONS_PER_QUIZ:
                questions = questions[:MAX_QUESTIONS_PER_QUIZ]
            try:
                await context.bot.send_message(
                    chat_id=message.chat_id,
                    text=f"ℹ️ Juda ko'p savol topildi. Cheklov: {MAX_QUESTIONS_PER_QUIZ} ta savol saqlandi."
                )
            except Exception:
                pass
        
        quiz_content = json.dumps(questions, sort_keys=True)
        quiz_id = hashlib.md5(quiz_content.encode()).hexdigest()[:12]
        
        storage.save_quiz(quiz_id, questions, user_id, chat_id, title_to_save)
        
        keyboard = [
            [InlineKeyboardButton("🚀 Quizni boshlash", callback_data=f"quiz_menu_{quiz_id}")],
            [InlineKeyboardButton("✏️ Qayta nomlash", callback_data=f"rename_quiz_{quiz_id}")],
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
        
        # File processing flag'ni o'chirish
        context.user_data.pop('file_processing', None)
        context.user_data.pop('file_processing_user', None)
        
    except Exception as e:
        logger.error(f"Fayl tahlil xatolik: {e}", exc_info=True)
        try:
            await status_msg.edit_text(f"❌ Xatolik: {str(e)}")
        except Exception:
            pass
        finally:
            # File processing flag'ni o'chirish
            context.user_data.pop('file_processing', None)
            context.user_data.pop('file_processing_user', None)
            context.user_data.pop('cancel_file_processing', None)

