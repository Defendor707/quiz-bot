"""Admin panel handlers"""
import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from bot.models import storage
from bot.utils.helpers import (
    track_update, is_admin_user, collect_known_group_ids, safe_edit_text,
    admin_only, admin_or_sudo, reply_or_edit, get_webhook_status, get_chat_title_cached
)

logger = logging.getLogger(__name__)


@admin_only
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin panel"""
    track_update(update)
    await show_admin_menu(update, context, as_edit=False)


def _calculate_quiz_stats(all_quizzes: list, now: datetime) -> tuple[int, int, int]:
    """Quiz statistikalarini hisoblash"""
    today_start = datetime(now.year, now.month, now.day)
    week_start = today_start - timedelta(days=now.weekday())
    month_start = datetime(now.year, now.month, 1)
    
    quizzes_today = quizzes_this_week = quizzes_this_month = 0
    
    today_date = today_start.date()
    week_date = week_start.date()
    month_date = month_start.date()
    
    for quiz in all_quizzes:
        created_at_str = quiz.get('created_at')
        if not created_at_str:
            continue
        
        try:
            if isinstance(created_at_str, str):
                created_at = datetime.fromisoformat(created_at_str.replace('Z', ''))
            else:
                created_at = created_at_str
            
            if created_at.tzinfo is not None:
                created_at = created_at.replace(tzinfo=None)
            
            created_date = created_at.date()
            
            if created_date >= today_date:
                quizzes_today += 1
            if created_date >= week_date:
                quizzes_this_week += 1
            if created_date >= month_date:
                quizzes_this_month += 1
        except Exception as e:
            logger.debug(f"Quiz created_at parsing xatolik: {e}, value: {created_at_str}")
    
    return quizzes_today, quizzes_this_week, quizzes_this_month


async def show_admin_menu(update_or_query, context: ContextTypes.DEFAULT_TYPE, as_edit: bool):
    """Admin menyusini ko'rsatish"""
    # Asosiy statistikalar
    quizzes_count = storage.get_quizzes_count()
    results_count = storage.get_results_count()
    users_count = storage.get_users_count()
    groups_count = storage.get_groups_count()
    sessions = context.bot_data.get('sessions', {}) or {}
    active_sessions = sum(1 for s in sessions.values() if s.get('is_active', False))
    
    # Quiz statistikalarini hisoblash (cache qilinishi mumkin, lekin hozircha oddiy)
    all_quizzes = storage.get_all_quizzes()
    quizzes_today, quizzes_this_week, quizzes_this_month = _calculate_quiz_stats(all_quizzes, datetime.now())
    
    # User ID va huquqlar
    user_id = update_or_query.from_user.id if hasattr(update_or_query, 'from_user') else update_or_query.message.from_user.id
    is_creator = is_admin_user(user_id)
    
    # Webhook holati (cache bilan)
    webhook = await get_webhook_status(context)

    text = (
        "🛠 **Admin panel**\n\n"
        f"📚 Jami Quizlar: **{quizzes_count}**\n"
        f"📚 Bugungi Quizlar: **{quizzes_today}**\n"
        f"📚 Bu Hafta Quizlar: **{quizzes_this_week}**\n"
        f"📚 Bu Oy Quizlar: **{quizzes_this_month}**\n"
        f"🧾 Natijalar: **{results_count}**\n"
        f"👤 Bot users: **{users_count}**\n"
        f"👥 Guruhlar: **{groups_count}**\n"
        f"🟢 Aktiv session: **{active_sessions}**\n"
        f"{webhook['icon']} Bot rejimi: **{webhook['mode']}**\n"
    )

    # Keyboard yaratish
    keyboard = [
        [InlineKeyboardButton("📚 Quizlar", callback_data="admin_quizzes"),
         InlineKeyboardButton("📊 Statistika", callback_data="admin_stats")],
        [InlineKeyboardButton("👤 Users", callback_data="admin_users"),
         InlineKeyboardButton("👥 Guruhlar", callback_data="admin_groups")],
        [InlineKeyboardButton("📣 Broadcast", callback_data="admin_broadcast"),
         InlineKeyboardButton("🧹 Cleanup", callback_data="admin_cleanup")],
    ]
    
    if is_creator:
        keyboard.append([InlineKeyboardButton("🛡 Sudo", callback_data="admin_sudo")])
        keyboard.append([InlineKeyboardButton("⭐ VIP", callback_data="admin_vip")])
    
    keyboard.append([InlineKeyboardButton("➕ Create Quiz", callback_data="admin_create_quiz")])
    keyboard.append([InlineKeyboardButton("🎛 Guruh quizlari", callback_data="admin_group_quiz")])
    keyboard.append([InlineKeyboardButton("📢 Majburiy kanallar", callback_data="admin_channels")])
    
    markup = InlineKeyboardMarkup(keyboard)
    await reply_or_edit(update_or_query, text, reply_markup=markup, as_edit=as_edit)


async def _admin_gq_get_title(context: ContextTypes.DEFAULT_TYPE, gid: int) -> str:
    """Guruh title olish (cache bilan)"""
    return await get_chat_title_cached(context, gid)


async def _admin_gq_show_groups(message, context: ContextTypes.DEFAULT_TYPE):
    """Guruhlar ro'yxati"""
    group_ids = list(collect_known_group_ids(context))
    if not group_ids:
        keyboard = [[InlineKeyboardButton("⬅️ Admin", callback_data="admin_menu")]]
        await safe_edit_text(
            message,
            "👥 Guruhlar topilmadi.\n\n"
            "Bot guruhlardan update olishi uchun guruhda bir marta /startquiz yuboring.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    rows = []
    keyboard = []
    shown = 0
    for gid in group_ids:
        if shown >= 18:
            break
        shown += 1
        title = await _admin_gq_get_title(context, gid)
        allowed_count = 0
        try:
            allowed_count = len(storage.get_group_allowed_quiz_ids(gid))
        except Exception:
            allowed_count = 0
        mode = "ON" if allowed_count > 0 else "OFF"
        rows.append(f"- **{title}** (`{gid}`) — filter: **{mode}** ({allowed_count})")
        keyboard.append([InlineKeyboardButton(f"🎛 {title}", callback_data=f"admin_gq_select_{gid}")])

    if len(group_ids) > shown:
        rows.append(f"\n... va yana {len(group_ids) - shown} ta")

    keyboard.append([InlineKeyboardButton("⬅️ Admin", callback_data="admin_menu")])
    text = "🎛 **Guruh quizlari**\n\nGuruhni tanlang:\n\n" + "\n".join(rows)
    await safe_edit_text(message, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)


async def _admin_gq_show_group_menu(message, context: ContextTypes.DEFAULT_TYPE, gid: int):
    """Guruh menyu"""
    title = await _admin_gq_get_title(context, gid)
    allowed_ids = storage.get_group_allowed_quiz_ids(gid)
    mode = "ON" if allowed_ids else "OFF"
    text = (
        f"🎛 **Guruh quizlari**\n\n"
        f"👥 Guruh: **{title}**\n"
        f"🆔 ID: `{gid}`\n"
        f"🔒 Filtr: **{mode}**\n"
        f"📋 Tanlanganlar: **{len(allowed_ids)}**\n\n"
        "Filtr **ON** bo'lsa, guruhda /startquiz faqat tanlangan quizlarni ko'rsatadi."
    )
    keyboard = [
        [InlineKeyboardButton("📋 Tanlanganlar ro'yxati", callback_data=f"admin_gq_list_{gid}")],
        [InlineKeyboardButton("➕ Oxirgilaridan qo'shish", callback_data=f"admin_gq_pick_{gid}")],
        [InlineKeyboardButton("➕ ID bilan qo'shish", callback_data=f"admin_gq_add_{gid}")],
        [InlineKeyboardButton("♻️ Filtr OFF (hamma quizlar)", callback_data=f"admin_gq_off_{gid}")],
        [InlineKeyboardButton("⬅️ Guruhlar", callback_data="admin_group_quiz")],
        [InlineKeyboardButton("⬅️ Admin", callback_data="admin_menu")],
    ]
    await safe_edit_text(message, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)


async def _admin_gq_show_allowed_list(message, context: ContextTypes.DEFAULT_TYPE, gid: int, page: int = 0):
    """Tanlangan quizlar ro'yxati"""
    title = await _admin_gq_get_title(context, gid)
    allowed_ids = storage.get_group_allowed_quiz_ids(gid)
    rows = []
    keyboard = []
    if not allowed_ids:
        rows.append("Hozir filtr **OFF** (tanlanganlar yo'q).")
    else:
        QUIZZES_PER_PAGE = 10
        total_quizzes = len(allowed_ids)
        total_pages = (total_quizzes + QUIZZES_PER_PAGE - 1) // QUIZZES_PER_PAGE
        page = max(0, min(page, total_pages - 1))
        
        start_idx = page * QUIZZES_PER_PAGE
        end_idx = min(start_idx + QUIZZES_PER_PAGE, total_quizzes)
        page_ids = allowed_ids[start_idx:end_idx]
        
        for qid in page_ids:
            quiz = storage.get_quiz(qid)
            if not quiz:
                continue
            qtitle = (quiz.get('title') or qid)[:28]
            qcount = len(quiz.get('questions', []))
            rows.append(f"- **{qtitle}** (`{qid}`) — {qcount} savol")
            keyboard.append([InlineKeyboardButton(f"❌ {qtitle}", callback_data=f"admin_gq_rm_{gid}_{qid}")])
        
        pagination_buttons = []
        if total_pages > 1:
            if page > 0:
                pagination_buttons.append(InlineKeyboardButton("⬅️ Oldingi", callback_data=f"admin_gq_list_{gid}_{page - 1}"))
            if page < total_pages - 1:
                pagination_buttons.append(InlineKeyboardButton("Keyingi ➡️", callback_data=f"admin_gq_list_{gid}_{page + 1}"))
            if pagination_buttons:
                keyboard.append(pagination_buttons)

    text = f"📋 **Tanlangan quizlar**\n\n👥 **{title}** (`{gid}`)\n"
    if allowed_ids and len(allowed_ids) > 10:
        total_pages = (len(allowed_ids) + 10 - 1) // 10
        text += f"(Sahifa {page + 1}/{total_pages})\n"
    text += "\n" + "\n".join(rows)
    keyboard.extend([
        [InlineKeyboardButton("➕ Oxirgilaridan qo'shish", callback_data=f"admin_gq_pick_{gid}")],
        [InlineKeyboardButton("➕ ID bilan qo'shish", callback_data=f"admin_gq_add_{gid}")],
        [InlineKeyboardButton("⬅️ Orqaga", callback_data=f"admin_gq_select_{gid}")],
    ])
    await safe_edit_text(message, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)


async def _admin_gq_show_pick_latest(message, context: ContextTypes.DEFAULT_TYPE, gid: int, page: int = 0):
    """Oxirgi quizlardan tanlash"""
    title = await _admin_gq_get_title(context, gid)
    all_quizzes = storage.get_all_quizzes()
    all_quizzes.sort(key=lambda q: q.get('created_at', ''), reverse=True)
    
    QUIZZES_PER_PAGE = 10
    total_quizzes = len(all_quizzes)
    total_pages = (total_quizzes + QUIZZES_PER_PAGE - 1) // QUIZZES_PER_PAGE
    page = max(0, min(page, total_pages - 1))
    
    start_idx = page * QUIZZES_PER_PAGE
    end_idx = min(start_idx + QUIZZES_PER_PAGE, total_quizzes)
    page_quizzes = all_quizzes[start_idx:end_idx]
    
    rows = []
    keyboard = []
    for i, quiz in enumerate(page_quizzes, 1):
        global_idx = start_idx + i
        qid = quiz.get('quiz_id')
        if not qid:
            continue
        qtitle = (quiz.get('title') or f"Quiz {global_idx}")[:28]
        qcount = len(quiz.get('questions', []))
        rows.append(f"{global_idx}. **{qtitle}** (`{qid}`) — {qcount} savol")
        keyboard.append([InlineKeyboardButton(f"➕ {qtitle}", callback_data=f"admin_gq_addid_{gid}_{qid}")])
    
    pagination_buttons = []
    if total_pages > 1:
        if page > 0:
            pagination_buttons.append(InlineKeyboardButton("⬅️ Oldingi", callback_data=f"admin_gq_pick_{gid}_{page - 1}"))
        if page < total_pages - 1:
            pagination_buttons.append(InlineKeyboardButton("Keyingi ➡️", callback_data=f"admin_gq_pick_{gid}_{page + 1}"))
        if pagination_buttons:
            keyboard.append(pagination_buttons)
    
    text = f"➕ **Guruhga quiz qo'shish**\n\n👥 **{title}** (`{gid}`)\n"
    if total_pages > 1:
        text += f"(Sahifa {page + 1}/{total_pages})\n"
    text += "\n" + "\n".join(rows)
    keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data=f"admin_gq_select_{gid}")])
    await safe_edit_text(message, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)


@admin_only
async def admin_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin statistika"""
    quizzes_count = storage.get_quizzes_count()
    results_count = storage.get_results_count()
    users_count = storage.get_users_count()
    groups_count = storage.get_groups_count()
    sessions = context.bot_data.get('sessions', {}) or {}
    active_sessions = sum(1 for s in sessions.values() if s.get('is_active', False))

    webhook = await get_webhook_status(context)

    text = (
        "📊 **Statistika**\n\n"
        f"📚 Quizlar: **{quizzes_count}**\n"
        f"🧾 Natijalar: **{results_count}**\n"
        f"👤 Bot users: **{users_count}**\n"
        f"👥 Guruhlar (known): **{groups_count}**\n"
        f"🟢 Aktiv session: **{active_sessions}**\n"
        f"\n**Bot rejimi:**\n"
        f"{webhook['mode']}: {webhook['status']}\n"
    )
    
    if webhook['error']:
        text += f"\n⚠️ **Webhook xatolik:**\n`{webhook['error'][:100]}`\n"
    
    keyboard = [[InlineKeyboardButton("⬅️ Admin", callback_data="admin_menu")]]
    await reply_or_edit(update, text, reply_markup=InlineKeyboardMarkup(keyboard))


@admin_only
async def admin_group_quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Guruh quizlari"""
    await _admin_gq_show_groups(update.message, context)


@admin_only
async def admin_quizzes_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin quizlar ro'yxati"""
    from bot.handlers.quiz import quizzes_command
    await quizzes_command(update, context)


@admin_only
async def admin_users_command(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    """Admin foydalanuvchilar ro'yxati (pagination bilan)"""
    
    users = storage.get_users()
    USERS_PER_PAGE = 15
    total_users = len(users)
    total_pages = (total_users + USERS_PER_PAGE - 1) // USERS_PER_PAGE if total_users > 0 else 1
    
    # Page tekshiruvi
    if page < 0:
        page = 0
    if page >= total_pages:
        page = total_pages - 1
    
    start_idx = page * USERS_PER_PAGE
    end_idx = start_idx + USERS_PER_PAGE
    page_users = users[start_idx:end_idx]
    
    text = f"👤 **Bot foydalanuvchilari**\n\n"
    text += f"📊 Jami: **{total_users}** ta\n"
    text += f"📄 Sahifa: **{page + 1}/{total_pages}**\n\n"
    
    if not page_users:
        text += "Hali userlar yo'q."
    else:
        for u in page_users:
            uname = f"@{u.get('username')}" if u.get('username') else "-"
            last_seen = u.get('last_seen', '')[:19] if u.get('last_seen') else '-'
            text += f"- `{u.get('user_id')}` {uname} — {u.get('first_name') or ''} (last: {last_seen})\n"
    
    # Pagination tugmalari
    keyboard = []
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Oldingi", callback_data=f"admin_users_page_{page - 1}"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("Keyingi ➡️", callback_data=f"admin_users_page_{page + 1}"))
    if nav_row:
        keyboard.append(nav_row)
    keyboard.append([InlineKeyboardButton("⬅️ Admin", callback_data="admin_menu")])
    await reply_or_edit(update, text, reply_markup=InlineKeyboardMarkup(keyboard))


@admin_only
async def admin_groups_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin guruhlar ro'yxati"""
    
    bot_id = context.bot.id
    group_ids = list(collect_known_group_ids(context))
    if not group_ids:
        keyboard = [[InlineKeyboardButton("⬅️ Admin", callback_data="admin_menu")]]
        text = (
            "👥 Guruhlar topilmadi.\n\n"
            "Sabab: bot hali guruhlardan update olmagan bo'lishi mumkin.\n"
            "Yechim: guruhda botga bir marta /startquiz yuboring yoki botni qayta qo'shib admin qiling."
        )
        await reply_or_edit(update, text, reply_markup=InlineKeyboardMarkup(keyboard))
        return

    rows = []
    shown = 0
    for gid in group_ids:
        if shown >= 15:
            break
        shown += 1

        title = await get_chat_title_cached(context, gid)
        chat_type = None
        try:
            chat_obj = await context.bot.get_chat(gid)
            chat_type = getattr(chat_obj, "type", None)
        except Exception:
            pass

        status = "unknown"
        is_admin = False
        try:
            m = await context.bot.get_chat_member(gid, bot_id)
            status = m.status
            is_admin = status in ['administrator', 'creator']
        except Exception:
            status = "no-access"

        try:
            storage.track_group(chat_id=gid, title=title, chat_type=chat_type, bot_status=status, bot_is_admin=is_admin)
        except Exception:
            pass

        badge = "✅ admin" if is_admin else status
        rows.append(f"- **{title}** (`{gid}`) — `{badge}`")

    if len(group_ids) > shown:
        rows.append(f"\n... va yana {len(group_ids) - shown} ta (bot update ko'rgan sari ko'payadi)")

    keyboard = [[InlineKeyboardButton("⬅️ Admin", callback_data="admin_menu")]]
    text = "👥 **Guruhlar (discovered):**\n\n" + "\n".join(rows)
    await reply_or_edit(update, text, reply_markup=InlineKeyboardMarkup(keyboard))


@admin_only
async def admin_broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin broadcast"""
    context.user_data['admin_action'] = 'broadcast_choice'
    keyboard = [
        [InlineKeyboardButton("📨 Users ga yuborish", callback_data="admin_broadcast_users"),
         InlineKeyboardButton("👥 Guruhlarga yuborish", callback_data="admin_broadcast_groups")],
        [InlineKeyboardButton("⬅️ Admin", callback_data="admin_menu")]
    ]
    await reply_or_edit(update, "📣 Qayerga yuboramiz?", reply_markup=InlineKeyboardMarkup(keyboard))


@admin_only
async def admin_cleanup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin cleanup stuck sessions"""
    sessions = context.bot_data.setdefault('sessions', {})
    group_locks = context.bot_data.setdefault('group_locks', {})
    cleared_sessions = sum(1 for s in sessions.values() if s.get('is_active', False))
    
    for s in sessions.values():
        if s.get('is_active', False):
            s['is_active'] = False
    
    cleared_locks = len(group_locks)
    group_locks.clear()
    
    keyboard = [[InlineKeyboardButton("⬅️ Admin", callback_data="admin_menu")]]
    text = f"🧹 Tozalandi.\n\nSession yopildi: {cleared_sessions}\nLock: {cleared_locks}"
    await reply_or_edit(update, text, reply_markup=InlineKeyboardMarkup(keyboard))


@admin_only
async def admin_sudo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin sudo userlar"""
    sudo_users = storage.get_sudo_users()
    text = "🛡 **Sudo userlar:**\n\n"
    if not sudo_users:
        text += "📭 Sudo userlar yo'q."
    else:
        for u in sudo_users[:50]:
            uname = f"@{u.get('username')}" if u.get('username') else "-"
            text += f"- `{u.get('user_id')}` {uname} {u.get('first_name') or ''}\n"
    
    keyboard = [[InlineKeyboardButton("⬅️ Admin", callback_data="admin_menu")]]
    await reply_or_edit(update, text, reply_markup=InlineKeyboardMarkup(keyboard))


@admin_only
async def admin_vip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin VIP userlar"""
    vip_users = storage.get_vip_users()
    text = "⭐ **VIP userlar:**\n\n"
    if not vip_users:
        text += "📭 VIP userlar yo'q."
    else:
        for u in vip_users[:50]:
            uname = f"@{u.get('username')}" if u.get('username') else "-"
            nickname = u.get('nickname', '')
            text += f"- `{u.get('user_id')}` {uname} {nickname or u.get('first_name') or ''}\n"
    
    text += "\n💡 `/vip list` - Ro'yxat\n"
    text += "💡 `/vip add <user_id>` - Qo'shish\n"
    text += "💡 `/vip remove <user_id>` - Olib tashlash\n"
    text += "💡 `/vip addme` - O'zingizni VIP qilish"
    
    keyboard = [[InlineKeyboardButton("⬅️ Admin", callback_data="admin_menu")]]
    await reply_or_edit(update, text, reply_markup=InlineKeyboardMarkup(keyboard))


@admin_only
async def admin_channels_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin majburiy obuna kanallari"""
    channels = storage.get_required_channels()
    text = "📢 **Majburiy obuna kanallari**\n\n"
    
    if not channels:
        text += "📭 Majburiy kanallar yo'q.\n\n"
    else:
        for i, ch in enumerate(channels, 1):
            ch_id = ch.get('channel_id')
            ch_username = ch.get('channel_username', '')
            ch_title = ch.get('channel_title', '')
            
            ch_link = f"@{ch_username}" if ch_username else f"Channel {ch_id}"
            text += f"{i}. {ch_link}"
            if ch_title:
                text += f" - {ch_title}"
            text += f"\n   🆔 ID: `{ch_id}`\n\n"
    
    text += "💡 **Command'lar:**\n"
    text += "• `/channels list` - Ro'yxat\n"
    text += "• `/channels add <channel_id>` yoki `/channels add @username` - Qo'shish\n"
    text += "• `/channels remove <channel_id>` - O'chirish"
    
    keyboard = [[InlineKeyboardButton("⬅️ Admin", callback_data="admin_menu")]]
    await reply_or_edit(update, text, reply_markup=InlineKeyboardMarkup(keyboard))


@admin_or_sudo
async def admin_create_quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin va sudo userlar quiz yaratish"""
    keyboard = [
        [InlineKeyboardButton("📄 Fayl yuborish", callback_data="admin_create_quiz_file"),
         InlineKeyboardButton("💬 Mavzu aytish", callback_data="admin_create_quiz_topic")],
        [InlineKeyboardButton("⬅️ Admin", callback_data="admin_menu")]
    ]
    text = "➕ **Quiz yaratish**\n\nQuiz yaratish usulini tanlang:"
    await reply_or_edit(update, text, reply_markup=InlineKeyboardMarkup(keyboard))

