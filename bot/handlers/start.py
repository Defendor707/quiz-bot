"""Start va Help handlerlar"""
import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from bot.config import Config
from bot.models import storage

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
    chat_type = update.effective_chat.type
    
    if chat_type in ['group', 'supergroup']:
        await update.message.reply_text(
            "❌ Bu buyruq guruhda ishlamaydi.\n\n"
            "📝 Guruhda /startquiz buyrug'ini ishlating."
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


async def myresults_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchining oxirgi natijalari"""
    track_update(update)
    if update.effective_chat.type in ['group', 'supergroup']:
        await update.message.reply_text("ℹ️ Natijalarni ko'rish uchun botga shaxsiy chatda yozing.")
        return

    user_id = update.effective_user.id
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
        text += f"- 📝 {title[:28]} — **{correct}/{total}** ({pct:.0f}%)\n  ⏱ {when}\n"

    await update.message.reply_text(
        text, 
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=private_main_keyboard(update.effective_user.id)
    )

