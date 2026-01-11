"""Yordamchi funksiyalar"""
import re
import logging
import time
import functools
from typing import Optional
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.error import BadRequest
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from bot.config import Config
from bot.models import storage

logger = logging.getLogger(__name__)

# Quiz vaqt variantlari (soniyalarda)
TIME_OPTIONS = {
    '10s': 10,
    '30s': 30,
    '1min': 60,
    '3min': 180,
    '5min': 300
}


def is_admin_user(user_id: int) -> bool:
    """Admin user tekshiruvi"""
    return Config.is_admin(user_id)


def is_sudo_user(user_id: int) -> bool:
    """Sudo user (quiz yaratuvchi) tekshiruvi"""
    if Config.is_admin(user_id):
        return True
    try:
        return storage.is_sudo_user(user_id)
    except Exception:
        return False


def is_vip_user(user_id: int) -> bool:
    """VIP user tekshiruvi"""
    try:
        return storage.is_vip_user(user_id)
    except Exception:
        return False


def private_main_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    """Shaxsiy chat uchun asosiy klaviatura"""
    keyboard = [
        [KeyboardButton("📚 Mavjud quizlar"), KeyboardButton("🏅 Mening natijalarim")],
        [KeyboardButton("🔎 Qidirish"), KeyboardButton("ℹ️ Yordam")],
    ]
    if is_sudo_user(user_id):
        keyboard.insert(1, [KeyboardButton("📚 Mening quizlarim")])
    if is_admin_user(user_id):
        keyboard.append([KeyboardButton("🛠 Admin")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def track_update(update: Update):
    """Foydalanuvchi va guruhni tracking qilish"""
    try:
        user = update.effective_user
        chat = update.effective_chat
        if user:
            storage.track_user(
                user_id=user.id,
                username=getattr(user, "username", None),
                first_name=getattr(user, "first_name", None),
                last_name=getattr(user, "last_name", None),
                last_chat_id=chat.id if chat else None,
                last_chat_type=getattr(chat, "type", None) if chat else None,
            )
        if chat and getattr(chat, "type", None) in ['group', 'supergroup']:
            storage.track_group(
                chat_id=chat.id,
                title=getattr(chat, "title", None),
                chat_type=getattr(chat, "type", None),
            )
    except Exception:
        pass


def collect_known_group_ids(context) -> set[int]:
    """
    Telegram API botga 'men qaysi guruhlardaman' ro'yxatini bermaydi.
    Shuning uchun storage + runtime sessions/polls dan guruh chat_id larni yig'amiz.
    """
    ids: set[int] = set()
    try:
        for g in storage.get_groups():
            try:
                ids.add(int(g.get('chat_id')))
            except Exception:
                pass
    except Exception:
        pass

    try:
        sessions = context.bot_data.get('sessions', {}) or {}
        for s in sessions.values():
            try:
                cid = int(s.get('chat_id'))
                ctype = s.get('chat_type')
                if ctype in ['group', 'supergroup'] or cid < 0:
                    ids.add(cid)
            except Exception:
                pass
    except Exception:
        pass

    try:
        polls = context.bot_data.get('polls', {}) or {}
        for p in polls.values():
            try:
                cid = int(p.get('chat_id'))
                if cid < 0:
                    ids.add(cid)
            except Exception:
                pass
    except Exception:
        pass

    return ids


def _markdown_to_plain(text: str) -> str:
    """Markdown belgilarini olib tashlash (fallback)"""
    try:
        return re.sub(r"[*_`\\[\\]()]", "", text)
    except Exception:
        return text


async def safe_reply_text(message, text: str, reply_markup=None, parse_mode=ParseMode.MARKDOWN):
    """Markdown parsing xatolarini ushlovchi reply"""
    try:
        return await message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except BadRequest as e:
        if "Can't parse entities" in str(e):
            return await message.reply_text(_markdown_to_plain(text), reply_markup=reply_markup)
        raise


async def safe_edit_text(message, text: str, reply_markup=None, parse_mode=ParseMode.MARKDOWN):
    """Markdown parsing xatolarini ushlovchi edit"""
    try:
        return await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except BadRequest as e:
        if "Can't parse entities" in str(e):
            return await message.edit_text(_markdown_to_plain(text), reply_markup=reply_markup)
        raise


async def safe_send_markdown(context, chat_id: int, text: str, reply_markup=None):
    """Markdown parsing xatolarini ushlovchi send_message"""
    try:
        return await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    except BadRequest as e:
        if "Can't parse entities" in str(e):
            return await context.bot.send_message(
                chat_id=chat_id,
                text=_markdown_to_plain(text),
                reply_markup=reply_markup
            )
        raise


def admin_only(func):
    """Admin command decorator - faqat adminlar va shaxsiy chatda"""
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.type in ['group', 'supergroup']:
            return
        if not is_admin_user(update.effective_user.id):
            return
        return await func(update, context)
    return wrapper


def admin_or_sudo(func):
    """Admin yoki sudo user decorator"""
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.type in ['group', 'supergroup']:
            return
        if not (is_admin_user(update.effective_user.id) or is_sudo_user(update.effective_user.id)):
            return
        return await func(update, context)
    return wrapper


async def reply_or_edit(update_or_query, text: str, reply_markup=None, parse_mode=ParseMode.MARKDOWN, as_edit: bool = False):
    """Message reply yoki edit qilish - universal funksiya"""
    if as_edit and hasattr(update_or_query, 'message') and update_or_query.message:
        await safe_edit_text(update_or_query.message, text, reply_markup=reply_markup, parse_mode=parse_mode)
    elif hasattr(update_or_query, 'message') and update_or_query.message:
        try:
            await update_or_query.message.delete()
        except Exception:
            pass
        await update_or_query.message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    elif hasattr(update_or_query, 'reply_text'):
        await update_or_query.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    elif hasattr(update_or_query, 'effective_message'):
        await update_or_query.effective_message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)


async def get_webhook_status(context: ContextTypes.DEFAULT_TYPE) -> dict:
    """Webhook holatini olish va cache qilish"""
    cache_key = '_webhook_status_cache'
    cache_time_key = '_webhook_status_cache_time'
    
    # Cache tekshirish (5 daqiqa)
    if cache_key in context.bot_data:
        cache_time = context.bot_data.get(cache_time_key, 0)
        if time.time() - cache_time < 300:  # 5 daqiqa
            return context.bot_data[cache_key]
    
    try:
        webhook_info = await context.bot.get_webhook_info()
        status = {
            'icon': "🔄",
            'mode': "Polling",
            'status': "✅ Ishlayapti",
            'error': None
        }
        
        if webhook_info.url:
            status['mode'] = "Webhook"
            if webhook_info.last_error_message:
                status['icon'] = "⚠️"
                status['status'] = f"⚠️ Xatolik: {webhook_info.last_error_message[:50]}"
                status['error'] = webhook_info.last_error_message
            elif webhook_info.pending_update_count > 0:
                status['icon'] = "🟡"
                status['status'] = f"🟡 Kutmoqda: {webhook_info.pending_update_count} update"
            else:
                status['icon'] = "🟢"
                status['status'] = "✅ Ishlayapti"
        
        # Cache ga saqlash
        context.bot_data[cache_key] = status
        context.bot_data[cache_time_key] = time.time()
        return status
    except Exception as e:
        logger.error(f"Webhook holatini olishda xatolik: {e}", exc_info=True)
        return {
            'icon': "❓",
            'mode': "❓ Noma'lum",
            'status': "❌ Xatolik",
            'error': str(e)
        }


async def get_chat_title_cached(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> str:
    """Chat title olish va cache qilish"""
    cache_key = f'_chat_title_{chat_id}'
    
    if cache_key in context.bot_data:
        return context.bot_data[cache_key]
    
    try:
        chat_obj = await context.bot.get_chat(chat_id)
        title = (getattr(chat_obj, "title", None) or str(chat_id))[:40]
        context.bot_data[cache_key] = title
        return title
    except Exception:
        title = str(chat_id)
        context.bot_data[cache_key] = title
        return title


async def _is_group_admin(update: Update, context) -> bool:
    """Foydalanuvchi guruhda admin ekanligini tekshirish"""
    try:
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        chat_member = await context.bot.get_chat_member(chat_id, user_id)
        return chat_member.status in ['administrator', 'creator']
    except Exception as e:
        logger.error(f"Admin tekshiruvida xatolik: {e}")
        return False

