"""Premium subscription va Telegram Stars to'lov handlerlari"""
import json
import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, PreCheckoutQueryHandler
from telegram.constants import ParseMode

from bot.models import storage
from bot.utils.helpers import track_update, safe_reply_text

logger = logging.getLogger(__name__)

# Premium narxlar (Telegram Stars)
PREMIUM_PRICES = {
    '1_month': {'stars': 100, 'months': 1, 'price_text': '100 ⭐'},
    '3_months': {'stars': 250, 'months': 3, 'price_text': '250 ⭐ (10% chegirma)'},
    '6_months': {'stars': 450, 'months': 6, 'price_text': '450 ⭐ (25% chegirma)'},
    '12_months': {'stars': 800, 'months': 12, 'price_text': '800 ⭐ (33% chegirma)'}
}

# Premium limitlar
FREE_QUIZZES_PER_MONTH = 5  # Bepul foydalanuvchilar uchun oyiga 5 ta quiz
PREMIUM_QUIZZES_PER_MONTH = 100  # Premium foydalanuvchilar uchun oyiga 100 ta quiz


async def premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Premium buyurtma sahifasi"""
    track_update(update)
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    
    # Premium holatini tekshirish
    is_premium = storage.is_premium_user(user_id)
    premium_info = storage.get_premium_user(user_id)
    
    # Foydalanuvchining shu oyda yaratgan quizlari soni
    quizzes_this_month = storage.get_user_quizzes_count_this_month(user_id)
    
    if is_premium and premium_info:
        premium_until = datetime.fromisoformat(premium_info['premium_until'])
        days_left = (premium_until - datetime.now()).days
        
        text = f"""⭐ <b>Premium Obuna</b>

✅ Sizning Premium obunangiz faol!

📅 Premium muddati: <b>{premium_until.strftime('%d.%m.%Y')}</b>
⏰ Qolgan kunlar: <b>{days_left} kun</b>

📊 Statistika:
• Yaratilgan quizlar (bu oy): {quizzes_this_month}/{PREMIUM_QUIZZES_PER_MONTH}
• To'langan Stars: {premium_info.get('stars_paid', 0)} ⭐

💎 Premium imtiyozlari:
• Cheksiz quiz yaratish (oyiga {PREMIUM_QUIZZES_PER_MONTH} ta)
• Tezkor AI tahlil
• Barcha funksiyalar

Obunani uzaytirish uchun quyidagi paketlardan birini tanlang:"""
    else:
        text = f"""⭐ <b>Premium Obuna</b>

📊 Sizning holatingiz:
• Yaratilgan quizlar (bu oy): {quizzes_this_month}/{FREE_QUIZZES_PER_MONTH}
• Premium: ❌ Faol emas

💎 Premium obuna orqali:
• Cheksiz quiz yaratish (oyiga {PREMIUM_QUIZZES_PER_MONTH} ta)
• Tezkor AI tahlil
• Barcha funksiyalar

📦 Premium paketlar:"""
    
    # Premium paketlar keyboard
    keyboard = []
    for key, info in PREMIUM_PRICES.items():
        label = f"{info['months']} oy - {info['price_text']}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"premium_buy:{key}")])
    
    keyboard.append([InlineKeyboardButton("❌ Bekor qilish", callback_data="premium_cancel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await safe_reply_text(
        update,
        text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )


async def premium_buy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Premium buyurtma callback"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "premium_cancel":
        await query.edit_message_text("❌ Premium buyurtma bekor qilindi.")
        return
    
    if not query.data.startswith("premium_buy:"):
        return
    
    package_key = query.data.split(":")[1]
    package_info = PREMIUM_PRICES.get(package_key)
    
    if not package_info:
        await query.edit_message_text("❌ Xatolik: Paket topilmadi.")
        return
    
    user_id = query.from_user.id
    username = query.from_user.username
    first_name = query.from_user.first_name
    
    # Telegram Stars invoice yuborish
    try:
        # Stars invoice yuborish (send_invoice)
        await context.bot.send_invoice(
            chat_id=query.from_user.id,
            title=f"Premium Obuna - {package_info['months']} oy",
            description=f"Quiz Bot Premium obuna - {package_info['months']} oy davomida cheksiz quiz yaratish imkoniyati",
            payload=f"premium_{user_id}_{package_key}",
            provider_token="",  # Stars uchun bo'sh string
            currency="XTR",  # Telegram Stars currency
            prices=[{"label": f"{package_info['months']} oy Premium", "amount": package_info['stars']}],
            max_tip_amount=0,
            suggested_tip_amounts=[],
            start_parameter=f"premium_{package_key}",
            provider_data=json.dumps({"package": package_key, "user_id": user_id})
        )
        
        # Xabar yuborish
        text = f"""💳 <b>Premium Obuna - To'lov</b>

📦 Paket: <b>{package_info['months']} oy</b>
💰 Narx: <b>{package_info['price_text']}</b>

Yuqorida invoice yuborildi. Uni ochib Telegram Stars bilan to'lang."""
        
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML
        )
        
    except Exception as e:
        logger.error(f"Premium invoice yaratishda xatolik: {e}", exc_info=True)
        error_msg = str(e)
        # Telegram Stars uchun maxsus xatolik xabarlari
        if "payment provider" in error_msg.lower() or "not configured" in error_msg.lower():
            error_msg = "❌ Bot payment provider sifatida sozlangan emas.\n\n@BotFather ga o'tib, /mybots → Payments → Enable Payments qiling."
        elif "currency" in error_msg.lower():
            error_msg = "❌ Currency xatolik. Telegram Stars (XTR) sozlangan emas."
        else:
            error_msg = f"❌ Xatolik: {error_msg}\n\nIltimos, admin bilan bog'laning."
        
        await query.edit_message_text(error_msg)


async def precheckout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pre-checkout query handler - to'lovdan oldin tekshirish"""
    query = update.pre_checkout_query
    
    try:
        # Payload dan ma'lumotlarni olish
        payload = query.invoice_payload
        if not payload.startswith("premium_"):
            await query.answer(ok=False, error_message="Noto'g'ri to'lov ma'lumotlari")
            return
        
        parts = payload.split("_")
        if len(parts) < 3:
            await query.answer(ok=False, error_message="Noto'g'ri to'lov ma'lumotlari")
            return
        
        user_id = int(parts[1])
        package_key = parts[2]
        
        # User ID tekshirish
        if query.from_user.id != user_id:
            await query.answer(ok=False, error_message="Foydalanuvchi ID mos kelmadi")
            return
        
        # Paket tekshirish
        if package_key not in PREMIUM_PRICES:
            await query.answer(ok=False, error_message="Paket topilmadi")
            return
        
        # To'lov summasini tekshirish
        package_info = PREMIUM_PRICES[package_key]
        if query.total_amount != package_info['stars']:
            await query.answer(ok=False, error_message="To'lov summasi noto'g'ri")
            return
        
        # Barcha tekshiruvlar o'tdi
        await query.answer(ok=True)
        
    except Exception as e:
        logger.error(f"Pre-checkout xatolik: {e}")
        await query.answer(ok=False, error_message=f"Xatolik: {str(e)}")


async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muvaffaqiyatli to'lovdan keyin premium aktivlashtirish"""
    message = update.message
    payment = message.successful_payment
    
    try:
        payload = payment.invoice_payload
        if not payload.startswith("premium_"):
            logger.warning(f"Noto'g'ri payload: {payload}")
            return
        
        parts = payload.split("_")
        if len(parts) < 3:
            logger.warning(f"Noto'g'ri payload format: {payload}")
            return
        
        user_id = int(parts[1])
        package_key = parts[2]
        
        # User ID tekshirish
        if message.from_user.id != user_id:
            logger.warning(f"User ID mos kelmadi: {message.from_user.id} != {user_id}")
            return
        
        # Paket ma'lumotlarini olish
        package_info = PREMIUM_PRICES.get(package_key)
        if not package_info:
            logger.warning(f"Paket topilmadi: {package_key}")
            await message.reply_text("❌ Xatolik: Paket topilmadi. Admin bilan bog'laning.")
            return
        
        # Premium aktivlashtirish
        username = message.from_user.username
        first_name = message.from_user.first_name
        
        storage.add_premium_user(
            user_id=user_id,
            stars_amount=payment.total_amount,
            months=package_info['months'],
            username=username,
            first_name=first_name
        )
        
        premium_info = storage.get_premium_user(user_id)
        premium_until = datetime.fromisoformat(premium_info['premium_until'])
        
        text = f"""✅ <b>Premium Obuna Aktivlashtirildi!</b>

🎉 Tabriklaymiz! Sizning Premium obunangiz muvaffaqiyatli aktivlashtirildi.

📦 Paket: <b>{package_info['months']} oy</b>
💰 To'langan: <b>{payment.total_amount} ⭐</b>
📅 Premium muddati: <b>{premium_until.strftime('%d.%m.%Y')}</b>

💎 Endi siz:
• Oyiga {PREMIUM_QUIZZES_PER_MONTH} ta quiz yarata olasiz
• Tezkor AI tahlildan foydalanasiz
• Barcha funksiyalardan foydalanasiz

Rahmat! 🎊"""
        
        await message.reply_text(text, parse_mode=ParseMode.HTML)
        
        logger.info(f"Premium aktivlashtirildi: user_id={user_id}, package={package_key}, stars={payment.total_amount}")
        
    except Exception as e:
        logger.error(f"Premium aktivlashtirishda xatolik: {e}", exc_info=True)
        await message.reply_text(
            f"❌ Premium aktivlashtirishda xatolik yuz berdi. "
            f"Iltimos, admin bilan bog'laning.\n\nXatolik: {str(e)}"
        )


def is_premium_or_has_quota(user_id: int) -> tuple[bool, str]:
    """Premium yoki quota borligini tekshirish
    
    Returns:
        (is_allowed, message) - ruxsat berilganmi va xabar
    """
    # Sudo va VIP userlar cheksiz
    if storage.is_sudo_user(user_id) or storage.is_vip_user(user_id):
        return True, ""
    
    # Premium tekshirish
    is_premium = storage.is_premium_user(user_id)
    quizzes_this_month = storage.get_user_quizzes_count_this_month(user_id)
    
    if is_premium:
        if quizzes_this_month >= PREMIUM_QUIZZES_PER_MONTH:
            return False, f"❌ Sizning Premium obunangizda oyiga {PREMIUM_QUIZZES_PER_MONTH} ta quiz limiti bor.\n\nSiz allaqachon {quizzes_this_month} ta quiz yaratdingiz.\n\nKeyingi oy yoki Premium obunani uzaytiring."
        return True, ""
    else:
        # Bepul foydalanuvchi
        if quizzes_this_month >= FREE_QUIZZES_PER_MONTH:
            return False, f"❌ Bepul versiyada oyiga {FREE_QUIZZES_PER_MONTH} ta quiz yaratish mumkin.\n\nSiz allaqachon {quizzes_this_month} ta quiz yaratdingiz.\n\n💎 Premium obuna orqali cheksiz quiz yarating:\n/premium"
        return True, ""
