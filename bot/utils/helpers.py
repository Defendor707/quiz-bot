"""Yordamchi funksiyalar"""
import re
import logging
from typing import Optional
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.error import BadRequest
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

