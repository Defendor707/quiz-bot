"""Guruh uchun handlerlar"""
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from bot.models import storage
from bot.utils.helpers import track_update, safe_reply_text, _is_group_admin
from bot.services.quiz_service import advance_due_sessions

logger = logging.getLogger(__name__)


async def my_chat_member_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Botni guruhga qo'shish / admin qilish eventlari"""
    try:
        cmu = update.my_chat_member
        if not cmu or not cmu.chat:
            return
        chat = cmu.chat
        if chat.type not in ['group', 'supergroup']:
            return

        new_status = getattr(cmu.new_chat_member, "status", None)
        is_admin = new_status in ['administrator', 'creator']
        storage.track_group(
            chat_id=chat.id,
            title=getattr(chat, "title", None),
            chat_type=getattr(chat, "type", None),
            bot_status=new_status,
            bot_is_admin=is_admin,
        )
    except Exception as e:
        logger.error(f"my_chat_member_handler error: {e}", exc_info=True)


async def allowquiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Guruhda boshlash mumkin bo'lgan quizni 'tanlangan' ro'yxatga qo'shish"""
    track_update(update)
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("ℹ️ Bu buyruq faqat guruhda ishlaydi.")
        return

    if not await _is_group_admin(update, context):
        await update.message.reply_text("❌ Faqat guruh adminlari /allowquiz qila oladi.")
        return

    arg = " ".join(context.args).strip() if context.args else ""
    if not arg:
        await update.message.reply_text(
            "Foydalanish: `/allowquiz <quiz_id>`\n"
            "Filtrni o'chirish: `/allowquiz off`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if arg.lower() in ['off', 'disable', 'all', 'reset', 'clear']:
        storage.set_group_allowed_quiz_ids(chat.id, [])
        await update.message.reply_text("✅ Filtr o'chirildi. Endi guruhda hamma quizlar ko'rinadi.")
        return

    quiz_id = arg.split()[0]
    quiz = storage.get_quiz(quiz_id)
    if not quiz:
        await update.message.reply_text("❌ Quiz topilmadi. ID ni tekshiring.")
        return

    added = storage.add_group_allowed_quiz(chat.id, quiz_id)
    title = quiz.get('title') or quiz_id
    if added:
        await safe_reply_text(update.message, f"✅ Guruhga ruxsat berildi: **{title}** (`{quiz_id}`)", parse_mode=ParseMode.MARKDOWN)
    else:
        await safe_reply_text(update.message, f"ℹ️ Allaqachon ruxsat berilgan: **{title}** (`{quiz_id}`)", parse_mode=ParseMode.MARKDOWN)


async def disallowquiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Guruhda boshlash mumkin bo'lgan quizni 'tanlangan' ro'yxatdan olib tashlash"""
    track_update(update)
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("ℹ️ Bu buyruq faqat guruhda ishlaydi.")
        return

    if not await _is_group_admin(update, context):
        await update.message.reply_text("❌ Faqat guruh adminlari /disallowquiz qila oladi.")
        return

    arg = " ".join(context.args).strip() if context.args else ""
    if not arg:
        await update.message.reply_text("Foydalanish: `/disallowquiz <quiz_id>`", parse_mode=ParseMode.MARKDOWN)
        return

    if arg.lower() in ['all', 'reset', 'clear']:
        storage.set_group_allowed_quiz_ids(chat.id, [])
        await update.message.reply_text("✅ Tanlangan quizlar tozalandi (filtr o'chdi).")
        return

    quiz_id = arg.split()[0]
    ok = storage.remove_group_allowed_quiz(chat.id, quiz_id)
    await update.message.reply_text("✅ Olib tashlandi." if ok else "ℹ️ Bu quiz ro'yxatda yo'q.")


async def allowedquizzes_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Guruhda ruxsat berilgan quizlar ro'yxati"""
    track_update(update)
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("ℹ️ Bu buyruq faqat guruhda ishlaydi.")
        return

    allowed_ids = storage.get_group_allowed_quiz_ids(chat.id)
    if not allowed_ids:
        await update.message.reply_text(
            "ℹ️ Hozir filtr yoqilmagan — guruhda hamma quizlar boshlanadi.\n\n"
            "✅ Tanlash uchun: `/allowquiz <quiz_id>`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    items = []
    for qid in allowed_ids[:30]:
        quiz = storage.get_quiz(qid)
        if not quiz:
            continue
        title = quiz.get('title') or qid
        count = len(quiz.get('questions', []))
        items.append(f"- **{title}** (`{qid}`) — {count} savol")

    text = "📋 **Guruhda ruxsat berilgan quizlar:**\n\n" + ("\n".join(items) if items else "_(ro'yxat bo'sh)_")
    text += "\n\n♻️ Filtrni o'chirish: `/allowquiz off`"
    await safe_reply_text(update.message, text, parse_mode=ParseMode.MARKDOWN)


async def startquiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Guruhda quiz boshlash"""
    track_update(update)
    await advance_due_sessions(context)

    chat_type = update.effective_chat.type
    chat_id = update.effective_chat.id
    
    if chat_type not in ['group', 'supergroup']:
        await update.message.reply_text(
            "❌ Bu buyruq faqat guruhlarda ishlaydi.\n\n"
            "💡 Shaxsiy chatda /myquizzes buyrug'ini ishlating."
        )
        return
    
    # Bot admin check
    try:
        bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
        is_admin = bot_member.status in ['administrator', 'creator']
        
        if not is_admin:
            await update.message.reply_text(
                "❌ Bot guruhda admin emas!\n\n"
                "1. Guruh sozlamalari → Administratorlar\n"
                "2. Botni qo'shing va admin qiling"
            )
            return
    except Exception as e:
        await update.message.reply_text("❌ Xatolik yuz berdi.")
        return
    
    all_quizzes = storage.get_all_quizzes()

    # Group allowlist filter
    allowed_ids = storage.get_group_allowed_quiz_ids(chat_id)
    if allowed_ids:
        allowed_set = set(allowed_ids)
        all_quizzes = [q for q in all_quizzes if str(q.get('quiz_id')) in allowed_set]
    
    if not all_quizzes:
        await update.message.reply_text(
            ("📭 Bu guruhda hozircha tanlangan quizlar yo'q.\n\n"
             "✅ Admin: `/allowquiz <quiz_id>` bilan ruxsat bering.\n"
             "♻️ Filtrni o'chirish: `/allowquiz off` (hamma quizlar ochiladi).")
            if allowed_ids else
            ("📭 Quizlar yo'q.\n\n"
             "💡 Shaxsiy chatda fayl yuborib quiz yarating!")
        )
        return
    
    # Pagination
    QUIZZES_PER_PAGE = 10
    total_quizzes = len(all_quizzes)
    total_pages = (total_quizzes + QUIZZES_PER_PAGE - 1) // QUIZZES_PER_PAGE
    page = 0
    
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
    
    # Pagination buttons
    pagination_buttons = []
    if total_pages > 1:
        if page < total_pages - 1:
            pagination_buttons.append(InlineKeyboardButton("Keyingi ➡️", callback_data=f"page_group_quizzes_{chat_id}_{page + 1}"))
        if pagination_buttons:
            keyboard.append(pagination_buttons)
    
    text += "\n🎯 Quizni tanlang!"
    
    # Chempionat tugmasini olib tashlash - endi /startchemp command bor
    # Chempionatni alohida command orqali boshlash mumkin
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)


async def stopquiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Guruhda aktiv quizni to'xtatish (adminlar uchun)"""
    track_update(update)
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("ℹ️ Bu buyruq faqat guruhda ishlaydi.\n\nShaxsiy chatda /finishquiz ishlating.")
        return

    await advance_due_sessions(context)

    chat_id = chat.id
    user_id = update.effective_user.id

    # Admin check
    is_admin = False
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        is_admin = member.status in ['administrator', 'creator']
        if not is_admin:
            await update.message.reply_text("❌ Faqat adminlar /stopquiz qila oladi.")
            return
    except Exception:
        await update.message.reply_text("❌ Admin tekshiruvida xatolik.")
        return

    # Adminlar uchun voting kerak emas - to'g'ridan-to'g'ri to'xtatamiz
    # Oddiy foydalanuvchilar uchun voting qo'shish (kelajakda)
    # Hozircha faqat adminlar to'xtata oladi

    # Agar voting yaratib bo'lmasa, to'g'ridan-to'g'ri to'xtatamiz
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

    if stopped > 0:
        await update.message.reply_text(f"✅ {stopped} ta aktiv quiz to'xtatildi.")
    else:
        await update.message.reply_text("ℹ️ Guruhda aktiv quiz yo'q.")


async def startchemp_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Guruhda chempionat boshlash (adminlar uchun)"""
    track_update(update)
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("ℹ️ Bu buyruq faqat guruhda ishlaydi.")
        return
    
    await advance_due_sessions(context)
    
    chat_id = chat.id
    user_id = update.effective_user.id
    
    # Admin check
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status not in ['administrator', 'creator']:
            await update.message.reply_text("❌ Faqat adminlar /startchemp qila oladi.")
            return
    except Exception:
        await update.message.reply_text("❌ Admin tekshiruvida xatolik.")
        return
    
    # Chempionat aktivligini tekshirish
    from bot.services.championship import get_championship_status
    championship = await get_championship_status(context, chat_id)
    if championship:
        quiz_id = championship.get('quiz_id', '')
        quiz = storage.get_quiz(quiz_id)
        title = quiz.get('title', 'Quiz') if quiz else 'Quiz'
        await update.message.reply_text(
            f"⛔️ **Chempionat allaqachon davom etmoqda!**\n\n"
            f"📝 Quiz: {title}\n\n"
            f"Chempionatni to'xtatish uchun: `/stopchemp`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Quizlar ro'yxatini ko'rsatish
    all_quizzes = storage.get_all_quizzes()
    allowed_ids = storage.get_group_allowed_quiz_ids(chat_id)
    if allowed_ids:
        allowed_set = set(allowed_ids)
        all_quizzes = [q for q in all_quizzes if str(q.get('quiz_id')) in allowed_set]
    
    if not all_quizzes:
        await update.message.reply_text(
            "📭 Quizlar topilmadi.\n\n"
            "💡 Avval quiz yarating yoki `/allowquiz <quiz_id>` bilan ruxsat bering."
        )
        return
    
    # Agar argument bo'lsa, quiz ID ni olish
    if context.args:
        quiz_id = context.args[0]
        quiz = storage.get_quiz(quiz_id)
        if not quiz:
            await update.message.reply_text("❌ Quiz topilmadi.")
            return
        
        # Vaqtni olish (agar berilgan bo'lsa)
        time_seconds = 30
        if len(context.args) > 1:
            try:
                time_seconds = int(context.args[1])
                if time_seconds < 5 or time_seconds > 300:
                    time_seconds = 30
            except:
                pass
        
        # Chempionatni boshlash
        from bot.services.championship import start_championship
        success = await start_championship(context, chat_id, quiz_id, user_id, time_seconds)
        
        if success:
            await update.message.reply_text(
                f"✅ **Chempionat boshlanmoqda!**\n\n"
                f"📝 Quiz: {quiz.get('title', 'Quiz')}\n"
                f"⏱ Vaqt: {time_seconds}s har bir savol uchun\n\n"
                f"⚠️ Chempionat vaqtida guruhda boshqa quizlar o'tkazilmaydi!",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text("❌ Chempionatni boshlashda xatolik!")
        return
    
    # Quizlar ro'yxatini ko'rsatish
    text = "🏆 **Chempionat boshlash**\n\n"
    text += "Quyidagi formatda yuboring:\n"
    text += "`/startchemp <quiz_id> [vaqt_soniyada]`\n\n"
    text += "Masalan:\n"
    text += "`/startchemp mlktoxQz 30`\n\n"
    text += "📋 **Mavjud quizlar:**\n\n"
    
    keyboard = []
    for quiz in all_quizzes[:10]:
        quiz_id = quiz['quiz_id']
        title = quiz.get('title', f"Quiz {quiz_id}")[:30]
        count = len(quiz.get('questions', []))
        keyboard.append([InlineKeyboardButton(
            f"📝 {title} ({count} savol)",
            callback_data=f"championship_start_{chat_id}"
        )])
    
    if keyboard:
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def stopchemp_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Guruhda chempionatni to'xtatish (adminlar uchun)"""
    track_update(update)
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("ℹ️ Bu buyruq faqat guruhda ishlaydi.")
        return
    
    await advance_due_sessions(context)
    
    chat_id = chat.id
    user_id = update.effective_user.id
    
    # Admin check
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status not in ['administrator', 'creator']:
            await update.message.reply_text("❌ Faqat adminlar /stopchemp qila oladi.")
            return
    except Exception:
        await update.message.reply_text("❌ Admin tekshiruvida xatolik.")
        return
    
    # Chempionatni to'xtatish
    from bot.services.championship import stop_championship
    success = await stop_championship(context, chat_id)
    
    if success:
        await update.message.reply_text(
            "✅ **Chempionat to'xtatildi!**\n\n"
            "Endi guruhda boshqa quizlar o'tkazilishi mumkin.",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text("ℹ️ Guruhda aktiv chempionat yo'q.")


async def statistika_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Guruhdagi eng faol 100 ta foydalanuvchining statistikasi"""
    track_update(update)
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("ℹ️ Bu buyruq faqat guruhda ishlaydi.")
        return
    
    chat_id = chat.id
    
    # Guruhdagi barcha natijalarni olish
    group_results = storage.get_all_group_results(chat_id)
    
    if not group_results:
        await update.message.reply_text(
            "📊 **Statistika**\n\n"
            "ℹ️ Hozircha guruhda quiz natijalari yo'q.\n\n"
            "Quiz boshlash uchun: `/startquiz`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Foydalanuvchilar bo'yicha statistikani hisoblash
    user_stats = {}
    users_data = storage.get_users()
    users_dict = {u.get('user_id'): u for u in users_data}
    
    for result in group_results:
        user_id = result.get('user_id')
        if not user_id:
            continue
        
        if user_id not in user_stats:
            user_stats[user_id] = {
                'total_quizzes': 0,
                'total_correct': 0,
                'total_questions': 0,
                'percentages': []
            }
        
        stats = user_stats[user_id]
        stats['total_quizzes'] += 1
        stats['total_correct'] += result.get('correct_count', 0)
        stats['total_questions'] += result.get('total_count', 0)
        percentage = result.get('percentage', 0)
        if percentage is not None:
            stats['percentages'].append(percentage)
    
    # Faollik bo'yicha saralash (quizlar soni)
    sorted_users = sorted(
        user_stats.items(),
        key=lambda x: (x[1]['total_quizzes'], x[1]['total_correct']),
        reverse=True
    )[:100]  # Top 100
    
    if not sorted_users:
        await update.message.reply_text(
            "📊 **Statistika**\n\n"
            "ℹ️ Hozircha guruhda quiz natijalari yo'q.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Statistikani formatlash
    text = "📊 **Guruh statistikasi**\n\n"
    text += f"👥 Eng faol **{len(sorted_users)}** ta foydalanuvchi:\n\n"
    
    for rank, (user_id, stats) in enumerate(sorted_users, 1):
        user_info = users_dict.get(user_id, {})
        username = user_info.get('username', '')
        first_name = user_info.get('first_name', '')
        
        # Foydalanuvchi nomini formatlash
        if username:
            display_name = f"@{username}"
        elif first_name:
            display_name = first_name
        else:
            display_name = f"User {user_id}"
        
        # O'rtacha foizni hisoblash
        avg_percentage = 0
        if stats['percentages']:
            avg_percentage = sum(stats['percentages']) / len(stats['percentages'])
        
        # Umumiy to'g'ri javoblar foizi
        total_percentage = 0
        if stats['total_questions'] > 0:
            total_percentage = (stats['total_correct'] / stats['total_questions']) * 100
        
        text += f"{rank}. **{display_name}**\n"
        text += f"   📝 Quizlar: {stats['total_quizzes']} ta\n"
        text += f"   ✅ To'g'ri: {stats['total_correct']}/{stats['total_questions']}\n"
        text += f"   📊 O'rtacha: {avg_percentage:.1f}%\n\n"
        
        # Telegram xabar uzunligi chegarasi (4096 belgi)
        if len(text) > 3500:
            text += f"\n... va yana {len(sorted_users) - rank} ta foydalanuvchi"
            break
    
    text += f"\n📈 Jami quizlar: {len(group_results)} ta"
    
    await safe_reply_text(update.message, text, parse_mode=ParseMode.MARKDOWN)

