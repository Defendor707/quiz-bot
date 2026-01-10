"""Admin panel handlers"""
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from bot.models import storage
from bot.utils.helpers import track_update, is_admin_user, collect_known_group_ids, safe_edit_text

logger = logging.getLogger(__name__)


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin panel"""
    track_update(update)
    if update.effective_chat.type in ['group', 'supergroup']:
        return
    if not is_admin_user(update.effective_user.id):
        return
    await show_admin_menu(update, context, as_edit=False)


async def show_admin_menu(update_or_query, context: ContextTypes.DEFAULT_TYPE, as_edit: bool):
    """Admin menyusini ko'rsatish"""
    from datetime import datetime, timedelta
    
    quizzes_count = storage.get_quizzes_count()
    results_count = storage.get_results_count()
    users_count = storage.get_users_count()
    groups_count = storage.get_groups_count()
    sessions = context.bot_data.get('sessions', {}) or {}
    active_sessions = sum(1 for s in sessions.values() if s.get('is_active', False))
    
    # Quiz statistikalarini yig'ish
    now = datetime.now()
    today_start = datetime(now.year, now.month, now.day)
    week_start = today_start - timedelta(days=now.weekday())
    month_start = datetime(now.year, now.month, 1)
    
    quizzes_today = 0
    quizzes_this_week = 0
    quizzes_this_month = 0
    
    # Barcha quizlarni olish va sanalarni tekshirish
    all_quizzes = storage.get_all_quizzes()
    for quiz in all_quizzes:
        created_at_str = quiz.get('created_at')
        if created_at_str:
            try:
                if isinstance(created_at_str, str):
                    # ISO formatdan datetime ga o'tkazish
                    created_at = datetime.fromisoformat(created_at_str.replace('Z', ''))
                else:
                    created_at = created_at_str
                
                # Timezone ni olib tashlash va faqat date qismini solishtirish
                if created_at.tzinfo is not None:
                    created_at = created_at.replace(tzinfo=None)
                
                # Faqat sana qismini solishtirish (vaqtni e'tiborsiz qoldirish)
                created_date = created_at.date()
                today_date = today_start.date()
                week_date = week_start.date()
                month_date = month_start.date()
                
                if created_date >= today_date:
                    quizzes_today += 1
                if created_date >= week_date:
                    quizzes_this_week += 1
                if created_date >= month_date:
                    quizzes_this_month += 1
            except Exception as e:
                logger.debug(f"Quiz created_at parsing xatolik: {e}, value: {created_at_str}")

    user_id = update_or_query.from_user.id if hasattr(update_or_query, 'from_user') else update_or_query.message.from_user.id
    is_creator = is_admin_user(user_id)

    # Webhook holatini tekshirish
    webhook_status_icon = "🔄"
    webhook_mode_text = "Polling"
    try:
        webhook_info = await context.bot.get_webhook_info()
        if webhook_info.url:
            webhook_mode_text = "Webhook"
            if webhook_info.last_error_message:
                webhook_status_icon = "⚠️"
            elif webhook_info.pending_update_count > 0:
                webhook_status_icon = "🟡"
            else:
                webhook_status_icon = "🟢"
        else:
            webhook_status_icon = "🔄"
    except Exception as e:
        logger.error(f"Webhook holatini olishda xatolik: {e}", exc_info=True)
        webhook_status_icon = "❓"

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
        f"{webhook_status_icon} Bot rejimi: **{webhook_mode_text}**\n"
    )

    # InlineKeyboardMarkup yaratish
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

    # InlineKeyboardMarkup uchun edit yoki reply ishlatamiz
    if as_edit and hasattr(update_or_query, 'message'):
        # Callback query dan kelganda edit qilamiz
        await safe_edit_text(
            update_or_query.message,
            text,
            reply_markup=markup,
            parse_mode=ParseMode.MARKDOWN
        )
    elif hasattr(update_or_query, 'message'):
        # Callback query dan kelganda, lekin edit emas
        message = update_or_query.message
        try:
            await message.delete()
        except Exception:
            pass
        await message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    elif hasattr(update_or_query, 'reply_text'):
        # Bu oddiy Update obyekti
        await update_or_query.reply_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    else:
        # Fallback
        if hasattr(update_or_query, 'effective_message'):
            await update_or_query.effective_message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)


async def _admin_gq_get_title(context: ContextTypes.DEFAULT_TYPE, gid: int) -> str:
    """Guruh title olish"""
    try:
        chat_obj = await context.bot.get_chat(gid)
        return (getattr(chat_obj, "title", None) or str(gid))[:40]
    except Exception:
        return str(gid)


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


async def admin_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin statistika"""
    if not is_admin_user(update.effective_user.id):
        return
    if update.effective_chat.type in ['group', 'supergroup']:
        return
    
    quizzes_count = storage.get_quizzes_count()
    results_count = storage.get_results_count()
    users_count = storage.get_users_count()
    groups_count = storage.get_groups_count()
    sessions = context.bot_data.get('sessions', {}) or {}
    active_sessions = sum(1 for s in sessions.values() if s.get('is_active', False))

    # Webhook holatini tekshirish
    webhook_status = "❓ Noma'lum"
    webhook_mode = "❓ Noma'lum"
    webhook_error = None
    try:
        webhook_info = await context.bot.get_webhook_info()
        if webhook_info.url:
            webhook_mode = "🟢 Webhook"
            if webhook_info.last_error_message:
                webhook_status = f"⚠️ Xatolik: {webhook_info.last_error_message[:50]}"
                webhook_error = webhook_info.last_error_message
            elif webhook_info.pending_update_count > 0:
                webhook_status = f"🟡 Kutmoqda: {webhook_info.pending_update_count} update"
            else:
                webhook_status = "✅ Ishlayapti"
        else:
            webhook_mode = "🔄 Polling"
            webhook_status = "✅ Ishlayapti"
    except Exception as e:
        logger.error(f"Webhook holatini olishda xatolik: {e}", exc_info=True)
        webhook_status = "❌ Xatolik"
        webhook_mode = "❓ Noma'lum"

    text = (
        "📊 **Statistika**\n\n"
        f"📚 Quizlar: **{quizzes_count}**\n"
        f"🧾 Natijalar: **{results_count}**\n"
        f"👤 Bot users: **{users_count}**\n"
        f"👥 Guruhlar (known): **{groups_count}**\n"
        f"🟢 Aktiv session: **{active_sessions}**\n"
        f"\n**Bot rejimi:**\n"
        f"{webhook_mode}: {webhook_status}\n"
    )
    
    if webhook_error:
        text += f"\n⚠️ **Webhook xatolik:**\n`{webhook_error[:100]}`\n"
    
    keyboard = [[InlineKeyboardButton("⬅️ Admin", callback_data="admin_menu")]]
    markup = InlineKeyboardMarkup(keyboard)
    # Update yoki message ekanligini tekshiramiz
    if hasattr(update, 'message') and update.message:
        await update.message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    elif hasattr(update, 'effective_message'):
        await update.effective_message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)


async def admin_group_quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Guruh quizlari"""
    if not is_admin_user(update.effective_user.id):
        return
    if update.effective_chat.type in ['group', 'supergroup']:
        return
    
    await _admin_gq_show_groups(update.message, context)


async def admin_quizzes_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin quizlar ro'yxati"""
    if not is_admin_user(update.effective_user.id):
        return
    if update.effective_chat.type in ['group', 'supergroup']:
        return
    
    from bot.handlers.quiz import quizzes_command
    await quizzes_command(update, context)


async def admin_users_command(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    """Admin foydalanuvchilar ro'yxati (pagination bilan)"""
    if not is_admin_user(update.effective_user.id):
        return
    
    # Chat type tekshiruvi
    chat_type = None
    if hasattr(update, 'effective_chat') and update.effective_chat:
        chat_type = update.effective_chat.type
    elif hasattr(update, 'message') and update.message and hasattr(update.message, 'chat'):
        chat_type = update.message.chat.type
    
    if chat_type in ['group', 'supergroup']:
        return
    
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
    markup = InlineKeyboardMarkup(keyboard)
    
    # Update yoki message ekanligini tekshiramiz
    if hasattr(update, 'message') and update.message:
        await update.message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    elif hasattr(update, 'effective_message') and update.effective_message:
        await update.effective_message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    else:
        # Callback query uchun edit qilish
        if hasattr(update, 'message') and update.message:
            from bot.utils.helpers import safe_edit_text
            await safe_edit_text(update.message, text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)


async def admin_groups_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin guruhlar ro'yxati"""
    if not is_admin_user(update.effective_user.id):
        return
    if update.effective_chat.type in ['group', 'supergroup']:
        return
    
    bot_id = context.bot.id
    group_ids = list(collect_known_group_ids(context))
    if not group_ids:
        keyboard = [[InlineKeyboardButton("⬅️ Admin", callback_data="admin_menu")]]
        markup = InlineKeyboardMarkup(keyboard)
        # Update yoki message ekanligini tekshiramiz
        if hasattr(update, 'message') and update.message:
            await update.message.reply_text(
                "👥 Guruhlar topilmadi.\n\n"
                "Sabab: bot hali guruhlardan update olmagan bo'lishi mumkin.\n"
                "Yechim: guruhda botga bir marta /startquiz yuboring yoki botni qayta qo'shib admin qiling.",
                reply_markup=markup
            )
        elif hasattr(update, 'effective_message'):
            await update.effective_message.reply_text(
                "👥 Guruhlar topilmadi.\n\n"
                "Sabab: bot hali guruhlardan update olmagan bo'lishi mumkin.\n"
                "Yechim: guruhda botga bir marta /startquiz yuboring yoki botni qayta qo'shib admin qiling.",
                reply_markup=markup
            )
        return

    rows = []
    shown = 0
    for gid in group_ids:
        if shown >= 15:
            break
        shown += 1

        title = str(gid)
        chat_type = None
        try:
            chat_obj = await context.bot.get_chat(gid)
            title = (getattr(chat_obj, "title", None) or str(gid))[:28]
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
    markup = InlineKeyboardMarkup(keyboard)
    text = "👥 **Guruhlar (discovered):**\n\n" + "\n".join(rows)
    # Update yoki message ekanligini tekshiramiz
    if hasattr(update, 'message') and update.message:
        await update.message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    elif hasattr(update, 'effective_message'):
        await update.effective_message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)


async def admin_broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin broadcast"""
    if not is_admin_user(update.effective_user.id):
        return
    if update.effective_chat.type in ['group', 'supergroup']:
        return
    
    # Broadcast wizard boshlash
    context.user_data['admin_action'] = 'broadcast_choice'
    keyboard = [
        [InlineKeyboardButton("📨 Users ga yuborish", callback_data="admin_broadcast_users"),
         InlineKeyboardButton("👥 Guruhlarga yuborish", callback_data="admin_broadcast_groups")],
        [InlineKeyboardButton("⬅️ Admin", callback_data="admin_menu")]
    ]
    markup = InlineKeyboardMarkup(keyboard)
    # Update yoki message ekanligini tekshiramiz
    if hasattr(update, 'message') and update.message:
        await update.message.reply_text("📣 Qayerga yuboramiz?", reply_markup=markup)
    elif hasattr(update, 'effective_message'):
        await update.effective_message.reply_text("📣 Qayerga yuboramiz?", reply_markup=markup)


async def admin_cleanup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin cleanup stuck sessions"""
    if not is_admin_user(update.effective_user.id):
        return
    if update.effective_chat.type in ['group', 'supergroup']:
        return
    
    sessions = context.bot_data.setdefault('sessions', {})
    group_locks = context.bot_data.setdefault('group_locks', {})
    cleared_sessions = 0
    for s in sessions.values():
        if s.get('is_active', False):
            s['is_active'] = False
            cleared_sessions += 1
    cleared_locks = len(group_locks)
    group_locks.clear()
    
    keyboard = [[InlineKeyboardButton("⬅️ Admin", callback_data="admin_menu")]]
    markup = InlineKeyboardMarkup(keyboard)
    text = f"🧹 Tozalandi.\n\nSession yopildi: {cleared_sessions}\nLock: {cleared_locks}"
    # Update yoki message ekanligini tekshiramiz
    if hasattr(update, 'message') and update.message:
        await update.message.reply_text(text, reply_markup=markup)
    elif hasattr(update, 'effective_message'):
        await update.effective_message.reply_text(text, reply_markup=markup)


async def admin_sudo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin sudo userlar"""
    if not is_admin_user(update.effective_user.id):
        return
    if update.effective_chat.type in ['group', 'supergroup']:
        return
    
    from bot.utils.helpers import is_sudo_user
    sudo_users = storage.get_sudo_users()
    text = "🛡 **Sudo userlar:**\n\n"
    if not sudo_users:
        text += "📭 Sudo userlar yo'q."
    else:
        for u in sudo_users[:50]:
            uname = f"@{u.get('username')}" if u.get('username') else "-"
            text += f"- `{u.get('user_id')}` {uname} {u.get('first_name') or ''}\n"
    
    keyboard = [[InlineKeyboardButton("⬅️ Admin", callback_data="admin_menu")]]
    markup = InlineKeyboardMarkup(keyboard)
    # Update yoki message ekanligini tekshiramiz
    if hasattr(update, 'message') and update.message:
        await update.message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    elif hasattr(update, 'effective_message'):
        await update.effective_message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)


async def admin_vip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin VIP userlar"""
    if not is_admin_user(update.effective_user.id):
        return
    if update.effective_chat.type in ['group', 'supergroup']:
        return
    
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
    markup = InlineKeyboardMarkup(keyboard)
    # Update yoki message ekanligini tekshiramiz
    if hasattr(update, 'message') and update.message:
        await update.message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    elif hasattr(update, 'effective_message'):
        await update.effective_message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)


async def admin_channels_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin majburiy obuna kanallari"""
    if not is_admin_user(update.effective_user.id):
        return
    if update.effective_chat.type in ['group', 'supergroup']:
        return
    
    channels = storage.get_required_channels()
    text = "📢 **Majburiy obuna kanallari**\n\n"
    
    if not channels:
        text += "📭 Majburiy kanallar yo'q.\n\n"
    else:
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
    
    text += "💡 **Command'lar:**\n"
    text += "• `/channels list` - Ro'yxat\n"
    text += "• `/channels add <channel_id>` yoki `/channels add @username` - Qo'shish\n"
    text += "• `/channels remove <channel_id>` - O'chirish"
    
    keyboard = [[InlineKeyboardButton("⬅️ Admin", callback_data="admin_menu")]]
    markup = InlineKeyboardMarkup(keyboard)
    
    if hasattr(update, 'message') and update.message:
        await update.message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    elif hasattr(update, 'effective_message'):
        await update.effective_message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)


async def admin_create_quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin va sudo userlar quiz yaratish"""
    from bot.utils.helpers import is_sudo_user
    if not (is_admin_user(update.effective_user.id) or is_sudo_user(update.effective_user.id)):
        return
    if update.effective_chat.type in ['group', 'supergroup']:
        return
    
    keyboard = [
        [InlineKeyboardButton("📄 Fayl yuborish", callback_data="admin_create_quiz_file"),
         InlineKeyboardButton("💬 Mavzu aytish", callback_data="admin_create_quiz_topic")],
        [InlineKeyboardButton("⬅️ Admin", callback_data="admin_menu")]
    ]
    markup = InlineKeyboardMarkup(keyboard)
    # Update yoki message ekanligini tekshiramiz
    if hasattr(update, 'message') and update.message:
        await update.message.reply_text(
            "➕ **Quiz yaratish**\n\n"
            "Quiz yaratish usulini tanlang:",
            reply_markup=markup,
            parse_mode=ParseMode.MARKDOWN
        )
    elif hasattr(update, 'effective_message'):
        await update.effective_message.reply_text(
            "➕ **Quiz yaratish**\n\n"
            "Quiz yaratish usulini tanlang:",
            reply_markup=markup,
            parse_mode=ParseMode.MARKDOWN
        )

