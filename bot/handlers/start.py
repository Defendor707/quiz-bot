"""Start va Help handlerlar"""
import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from bot.config import Config
from bot.models import storage
from bot.utils.helpers import is_vip_user
from bot.services.quiz_service import advance_due_sessions

logger = logging.getLogger(__name__)


def is_sudo_user(user_id: int) -> bool:
    """Sudo user tekshiruvi"""
    if Config.is_admin(user_id):
        return True
    try:
        return storage.is_sudo_user(user_id)
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
    if Config.is_admin(user_id):
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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command"""
    track_update(update)
    await advance_due_sessions(context)
    chat_type = update.effective_chat.type
    
    if chat_type in ['group', 'supergroup']:
        await update.message.reply_text(
            "❌ Bu buyruq guruhda ishlamaydi.\n\n"
            "📝 Guruhda /startquiz buyrug'ini ishlating."
        )
        return
    
    # Majburiy obuna kanallarini tekshirish
    required_channels = storage.get_required_channels()
    if required_channels:
        user_id = update.effective_user.id
        not_subscribed = []
        
        for ch in required_channels:
            channel_id = ch.get('channel_id')
            try:
                member = await context.bot.get_chat_member(channel_id, user_id)
                if member.status in ['left', 'kicked']:
                    not_subscribed.append(ch)
            except Exception as e:
                logger.error(f"Channel subscription check error: {e}")
                # Agar xatolik bo'lsa, kanalni not_subscribed ga qo'shamiz
                not_subscribed.append(ch)
        
        if not_subscribed:
            text = "📢 **Majburiy obuna**\n\n"
            text += "Botdan foydalanish uchun quyidagi kanallarga obuna bo'lishingiz kerak:\n\n"
            
            buttons = []
            for ch in not_subscribed:
                ch_id = ch.get('channel_id')
                ch_username = ch.get('channel_username', '')
                ch_title = ch.get('channel_title', '')
                
                if ch_username:
                    ch_link = f"https://t.me/{ch_username.lstrip('@')}"
                    ch_name = ch_title or ch_username
                else:
                    ch_link = f"https://t.me/c/{str(ch_id)[4:]}" if str(ch_id).startswith('-100') else f"https://t.me/c/{str(ch_id)[1:]}"
                    ch_name = ch_title or f"Channel {ch_id}"
                
                text += f"• {ch_name}\n"
                buttons.append([InlineKeyboardButton(f"📢 {ch_name}", url=ch_link)])
            
            text += "\nObuna bo'lgach, /start buyrug'ini qayta ishlating."
            buttons.append([InlineKeyboardButton("✅ Obuna bo'ldim", callback_data="check_subscription")])
            
            markup = InlineKeyboardMarkup(buttons)
            
            await update.message.reply_text(
                text,
                reply_markup=markup,
                parse_mode=ParseMode.MARKDOWN
            )
            return
    
    if is_sudo_user(update.effective_user.id):
        welcome_message = """
🎯 **Quiz Bot**ga xush kelibsiz!

📝 **Qanday ishlaydi (creator):**
1️⃣ Test faylini yuboring (TXT, PDF, DOCX)
2️⃣ AI tahlil qilib quiz tayyorlaydi
3️⃣ Guruhda /startquiz orqali o'ynaladi

📚 **Buyruqlar:**
/myquizzes - Mening quizlarim
/myresults - Mening natijalarim
/quizzes - Mavjud quizlar
/help - Yordam
"""
    else:
        welcome_message = """
🎯 **Quiz Bot**ga xush kelibsiz!

✨ **Qisqa yo'riqnoma:**
- 📚 Tayyor quizlardan birini tanlab ishlaysiz
- 🏅 Natijalaringizni saqlab boramiz

📚 **Buyruqlar:**
/quizzes - Mavjud quizlar
/myresults - Mening natijalarim
/help - Yordam
"""
    await update.message.reply_text(
        welcome_message,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=private_main_keyboard(update.effective_user.id)
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Yordam"""
    track_update(update)
    await advance_due_sessions(context)
    help_text = """
📖 **Yordam**

**Qo'llab-quvvatlanadigan formatlar:**
• TXT - Matn fayllari
• PDF - PDF hujjatlar  
• DOCX - Word hujjatlar

**Buyruqlar:**
/start - Botni ishga tushirish
/myresults - Mening natijalarim
/startquiz - Guruhda quiz boshlash
/finishquiz - Shaxsiy chatda quizni yakunlash
/help - Yordam

**Guruhda:**
1. Shaxsiy chatda quiz yarating
2. Botni guruhga qo'shing va admin qiling
3. /startquiz buyrug'ini ishlating
"""
    if is_sudo_user(update.effective_user.id):
        help_text += "\n**Creator:** fayl yuborib quiz yaratishingiz mumkin (private chatda).\n/myquizzes - yaratgan quizlaringiz\n"
    if Config.is_admin(update.effective_user.id):
        help_text += "\n**Admin:**\n/admin - Admin panel\n/sudo - Sudo userlarni boshqarish\n"
    await update.message.reply_text(
        help_text, 
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=private_main_keyboard(update.effective_user.id)
    )


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Jarayonlarni bekor qilish"""
    track_update(update)
    user_id = update.effective_user.id
    
    # File processing bekor qilish
    if context.user_data.get('file_processing'):
        if context.user_data.get('file_processing_user') == user_id:
            context.user_data['cancel_file_processing'] = True
            await update.message.reply_text("✅ Fayl tahlil qilish jarayoni bekor qilindi.")
            return
    
    # Boshqa jarayonlarni bekor qilish
    cancelled = []
    if context.user_data.get('admin_action'):
        context.user_data.pop('admin_action', None)
        cancelled.append("Admin amali")
    if context.user_data.get('quiz_add_group_action'):
        context.user_data.pop('quiz_add_group_action', None)
        cancelled.append("Guruh qo'shish")
    if context.user_data.get('championship_action'):
        context.user_data.pop('championship_action', None)
        context.user_data.pop('championship_group_id', None)
        context.user_data.pop('championship_time_seconds', None)
        context.user_data.pop('championship_quiz_id', None)
        cancelled.append("Chempionat rejalashtirish")
    
    if cancelled:
        await update.message.reply_text(f"✅ Bekor qilindi: {', '.join(cancelled)}")
    else:
        await update.message.reply_text("ℹ️ Bekor qilinadigan jarayon topilmadi.")


async def myresults_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchining oxirgi natijalari"""
    track_update(update)
    await advance_due_sessions(context)
    
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    
    # Guruhda - faqat guruhdagi natijalar
    if chat_type in ['group', 'supergroup']:
        results = storage.get_user_results_in_group(user_id, chat_id, limit=15)
        if not results:
            await update.message.reply_text("📭 Bu guruhda hozircha natijalaringiz yo'q.")
            return
        
        # Statistika
        total_quizzes = len(results)
        total_correct = sum(r.get('correct_count', 0) for r in results)
        total_questions = sum(r.get('total_count', 0) for r in results)
        avg_percentage = sum(r.get('percentage', 0) for r in results) / len(results) if results else 0
        best_result = max(results, key=lambda x: x.get('percentage', 0)) if results else None
        
        text = f"🏅 **Mening natijalarim (bu guruhda):**\n\n"
        text += f"📊 **Statistika:**\n"
        text += f"• Bajarilgan quizlar: **{total_quizzes}** ta\n"
        text += f"• Jami to'g'ri javoblar: **{total_correct}/{total_questions}**\n"
        text += f"• O'rtacha natija: **{avg_percentage:.1f}%**\n"
        if best_result:
            quiz = storage.get_quiz(best_result.get('quiz_id', ''))
            quiz_title = quiz.get('title', 'Quiz') if quiz else 'Quiz'
            text += f"• Eng yaxshi natija: **{best_result.get('percentage', 0):.1f}%** ({quiz_title})\n"
        text += "\n📋 **Oxirgi natijalar:**\n\n"
        
        for r in results[:10]:  # Faqat 10 ta ko'rsatamiz
            quiz_id = r.get('quiz_id')
            quiz = storage.get_quiz(quiz_id) if quiz_id else None
            title = (quiz or {}).get('title') or quiz_id or "Quiz"
            correct = r.get('correct_count', 0)
            total = r.get('total_count', 0)
            pct = r.get('percentage', 0)
            when = str(r.get('completed_at', ''))[:19].replace("T", " ")
            # Vaqt statistikasi
            avg_time = r.get('avg_time', 0)
            time_text = f" ⏱ {avg_time:.1f}s" if avg_time > 0 else ""
            
            text += f"• 📝 {title[:30]} — **{correct}/{total}** ({pct:.0f}%){time_text}\n  📅 {when}\n"
        
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
        return
    
    # Shaxsiy chatda - barcha natijalar
    results = storage.get_user_results(user_id, limit=15)
    if not results:
        await update.message.reply_text("📭 Hozircha natijalaringiz yo'q.")
        return

    text = "🏅 **Mening natijalarim (oxirgilar):**\n\n"
    for r in results:
        quiz_id = r.get('quiz_id')
        quiz = storage.get_quiz(quiz_id) if quiz_id else None
        title = (quiz or {}).get('title') or quiz_id or "Quiz"
        correct = r.get('correct_count', 0)
        total = r.get('total_count', 0)
        pct = r.get('percentage', 0)
        when = str(r.get('completed_at', ''))[:19].replace("T", " ")
        
        # Vaqt statistikasi
        avg_time = r.get('avg_time', 0)
        time_text = f" ⏱ {avg_time:.1f}s" if avg_time > 0 else ""
        
        text += f"- 📝 {title[:28]} — **{correct}/{total}** ({pct:.0f}%){time_text}\n  📅 {when}\n"

    await update.message.reply_text(
        text, 
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=private_main_keyboard(update.effective_user.id)
    )


async def sardorbek_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sardorbek haqida maxsus ma'lumot va statistika"""
    track_update(update)
    
    sardorbek_id = 6444578922
    user_id = update.effective_user.id
    
    # Sardorbekning o'zi yoki VIP userlar ko'ra oladi
    if user_id != sardorbek_id and not is_vip_user(user_id) and not Config.is_admin(user_id):
        await update.message.reply_text(
            "🔒 Bu buyruq faqat maxsus foydalanuvchilar uchun!",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Sardorbek ma'lumotlarini olish
    vip_info = storage.get_vip_user(sardorbek_id)
    if not vip_info:
        # Agar VIP user bo'lmasa, qo'shamiz
        storage.add_vip_user(sardorbek_id, nickname="Sardorbek ⭐")
        vip_info = storage.get_vip_user(sardorbek_id)
    
    # Statistika
    results = storage.get_user_results(sardorbek_id, limit=100)
    quizzes = storage.get_user_quizzes(sardorbek_id)
    
    total_quizzes = len(quizzes)
    total_results = len(results)
    
    if results:
        total_correct = sum(r.get('correct_count', 0) for r in results)
        total_questions = sum(r.get('total_count', 0) for r in results)
        avg_percentage = sum(r.get('percentage', 0) for r in results) / len(results) if results else 0
        best_result = max(results, key=lambda x: x.get('percentage', 0))
    else:
        total_correct = 0
        total_questions = 0
        avg_percentage = 0
        best_result = None
    
    text = f"⭐ **{vip_info.get('nickname', 'Sardorbek')} - VIP User** ⭐\n\n"
    text += "📊 **Statistika:**\n"
    text += f"• Yaratilgan quizlar: **{total_quizzes}** ta\n"
    text += f"• Bajarilgan quizlar: **{total_results}** ta\n"
    
    if results:
        text += f"• Jami to'g'ri javoblar: **{total_correct}/{total_questions}**\n"
        text += f"• O'rtacha natija: **{avg_percentage:.1f}%**\n"
        if best_result:
            quiz = storage.get_quiz(best_result.get('quiz_id', ''))
            quiz_title = quiz.get('title', 'Quiz') if quiz else 'Quiz'
            text += f"• Eng yaxshi natija: **{best_result.get('percentage', 0):.1f}%** ({quiz_title})\n"
    
    text += "\n🌟 **Maxsus imkoniyatlar:**\n"
    text += "• ⭐ VIP badge quiz natijalarida\n"
    text += "• 📝 Quiz yaratish imkoniyati\n"
    text += "• 🎯 Maxsus statistika\n"
    text += "• 💎 Premium funksiyalar\n"
    
    text += "\n💬 **Sardorbek haqida:**\n"
    text += "Bu botning maxsus VIP foydalanuvchisi! 🎉"
    
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=private_main_keyboard(update.effective_user.id)
    )


async def vipstats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """VIP userlar uchun maxsus statistika sahifasi"""
    track_update(update)
    user_id = update.effective_user.id
    
    # Faqat VIP userlar va adminlar ko'ra oladi
    if not is_vip_user(user_id) and not Config.is_admin(user_id):
        await update.message.reply_text(
            "🔒 Bu buyruq faqat VIP userlar uchun!\n\n"
            "💡 VIP bo'lish uchun admin bilan bog'laning.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # VIP user ma'lumotlari
    vip_info = storage.get_vip_user(user_id)
    if not vip_info:
        # Agar VIP user bo'lmasa, lekin admin bo'lsa
        if Config.is_admin(user_id):
            vip_info = {'nickname': f"{update.effective_user.first_name} ⭐", 'user_id': user_id}
        else:
            await update.message.reply_text("❌ VIP user ma'lumotlari topilmadi.")
            return
    
    # Barcha natijalar
    all_results = storage.get_user_results(user_id, limit=1000)
    
    # Barcha quizlar
    all_quizzes = storage.get_user_quizzes(user_id)
    
    # Guruhlar bo'yicha statistika
    group_stats = {}
    for result in all_results:
        chat_id = result.get('chat_id')
        if chat_id:
            if chat_id not in group_stats:
                group_stats[chat_id] = {
                    'total_quizzes': 0,
                    'total_correct': 0,
                    'total_questions': 0,
                    'percentages': []
                }
            stats = group_stats[chat_id]
            stats['total_quizzes'] += 1
            stats['total_correct'] += result.get('correct_count', 0)
            stats['total_questions'] += result.get('total_count', 0)
            percentage = result.get('percentage', 0)
            if percentage is not None:
                stats['percentages'].append(percentage)
    
    # Umumiy statistika
    total_quizzes_created = len(all_quizzes)
    total_quizzes_completed = len(all_results)
    
    total_correct = sum(r.get('correct_count', 0) for r in all_results)
    total_questions = sum(r.get('total_count', 0) for r in all_results)
    overall_percentage = (total_correct / total_questions * 100) if total_questions > 0 else 0
    
    avg_percentage = sum(r.get('percentage', 0) for r in all_results) / len(all_results) if all_results else 0
    best_result = max(all_results, key=lambda x: x.get('percentage', 0)) if all_results else None
    
    # Vaqt statistikasi
    total_time = sum(r.get('total_time', 0) for r in all_results)
    avg_time = sum(r.get('avg_time', 0) for r in all_results) / len(all_results) if all_results else 0
    
    # Formatlash
    text = f"⭐ **{vip_info.get('nickname', 'VIP User')} - Maxsus Statistika** ⭐\n\n"
    
    text += "📊 **Umumiy Statistika:**\n"
    text += f"• Yaratilgan quizlar: **{total_quizzes_created}** ta\n"
    text += f"• Bajarilgan quizlar: **{total_quizzes_completed}** ta\n"
    
    if all_results:
        text += f"• Jami to'g'ri javoblar: **{total_correct}/{total_questions}**\n"
        text += f"• Umumiy foiz: **{overall_percentage:.1f}%**\n"
        text += f"• O'rtacha natija: **{avg_percentage:.1f}%**\n"
        if best_result:
            quiz = storage.get_quiz(best_result.get('quiz_id', ''))
            quiz_title = quiz.get('title', 'Quiz') if quiz else 'Quiz'
            text += f"• Eng yaxshi natija: **{best_result.get('percentage', 0):.1f}%** ({quiz_title})\n"
        if avg_time > 0:
            text += f"• O'rtacha javob vaqti: **{avg_time:.1f}s**\n"
            text += f"• Jami vaqt: **{total_time:.0f}s** ({total_time/60:.1f} min)\n"
    
    # Guruhlar bo'yicha statistika
    if group_stats:
        text += "\n👥 **Guruhlar bo'yicha:**\n"
        sorted_groups = sorted(
            group_stats.items(),
            key=lambda x: x[1]['total_quizzes'],
            reverse=True
        )[:5]  # Top 5 guruh
        
        for chat_id, stats in sorted_groups:
            try:
                chat = await context.bot.get_chat(chat_id)
                group_name = chat.title or f"Group {chat_id}"
            except:
                group_name = f"Group {chat_id}"
            
            group_avg = sum(stats['percentages']) / len(stats['percentages']) if stats['percentages'] else 0
            group_percentage = (stats['total_correct'] / stats['total_questions'] * 100) if stats['total_questions'] > 0 else 0
            
            text += f"• **{group_name[:30]}**: {stats['total_quizzes']} ta quiz, {group_percentage:.1f}%\n"
    
    text += "\n🌟 **VIP Imkoniyatlar:**\n"
    text += "• ⭐ VIP badge quiz natijalarida\n"
    text += "• 🥇 Tie-breaker: bir xil natijada birinchi o'rin\n"
    text += "• 📝 Quiz yaratish imkoniyati\n"
    text += "• 📊 Maxsus statistika sahifasi\n"
    text += "• 💎 Premium funksiyalar\n"
    
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=private_main_keyboard(user_id)
    )

