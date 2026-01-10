"""Premium subscription va Telegram Stars to'lov handlerlari - Tariflar: Free, Core, Pro"""
import json
import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, PreCheckoutQueryHandler
from telegram.constants import ParseMode

from bot.models import storage
from bot.services.subscription import (
    PLAN_FREE, PLAN_CORE, PLAN_PRO,
    PLAN_PRICES, PLAN_FEATURES,
    get_user_plan, get_plan_features, get_plan_info_text
)
from bot.utils.helpers import track_update, safe_reply_text

logger = logging.getLogger(__name__)


async def premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tariflar sahifasi - Free, Core, Pro"""
    track_update(update)
    user_id = update.effective_user.id
    
    # Foydalanuvchi tarifini olish
    current_plan = get_user_plan(user_id)
    plan_features = get_plan_features(current_plan)
    premium_info = storage.get_premium_user(user_id)
    
    # Tarif ma'lumotlari
    text = get_plan_info_text(user_id)
    
    # Agar premium faol bo'lsa, muddati ko'rsatish
    if premium_info and premium_info.get('premium_until'):
        try:
            premium_until = datetime.fromisoformat(premium_info['premium_until']) if isinstance(premium_info['premium_until'], str) else premium_info['premium_until']
            days_left = (premium_until - datetime.now()).days
            if days_left > 0:
                text += f"\n\n📅 Tarif muddati: <b>{premium_until.strftime('%d.%m.%Y')}</b>"
                text += f"\n⏰ Qolgan kunlar: <b>{days_left} kun</b>"
        except (ValueError, AttributeError, TypeError, KeyError) as e:
            logger.debug(f"Premium until date parsing xatolik (premium_info={premium_info}): {e}")
    
    # Tariflar ro'yxati
    if current_plan == PLAN_FREE:
        text += f"\n\n💎 <b>Mavjud Tariflar:</b>\n\n"
        
        # Core tarif
        core_features = get_plan_features(PLAN_CORE)
        text += f"📦 <b>Core Tarif</b>\n"
        text += f"💰 Narx: 50 ⭐/oy\n"
        text += f"✅ Imkoniyatlar:\n"
        text += f"• Quizlar: oyiga {core_features['quizzes_per_month']} ta\n"
        text += f"• AI parsing: ✅\n"
        text += f"• Fayl formatlar: {', '.join(core_features['allowed_file_types'])}\n"
        text += f"• Statistika: ✅\n"
        text += f"• Export: ✅\n\n"
        
        # Pro tarif
        pro_features = get_plan_features(PLAN_PRO)
        text += f"⭐ <b>Pro Tarif</b>\n"
        text += f"💰 Narx: 100 ⭐/oy\n"
        text += f"✅ Imkoniyatlar:\n"
        text += f"• Quizlar: oyiga {pro_features['quizzes_per_month']} ta (de-facto cheksiz)\n"
        text += f"• AI parsing: ✅\n"
        text += f"• Fayl formatlar: {', '.join(pro_features['allowed_file_types'])}\n"
        text += f"• Statistika: ✅\n"
        text += f"• Export: ✅\n"
        text += f"• Priority support: ✅\n"
        text += f"• Custom branding: ✅\n"
        text += f"• API access: ✅\n"
    
    # Keyboard - tariflar tanlash
    keyboard = []
    
    if current_plan == PLAN_FREE:
        # Core tarif paketlari
        keyboard.append([InlineKeyboardButton("📦 Core Tarif", callback_data="plan_select:core")])
        # Pro tarif paketlari
        keyboard.append([InlineKeyboardButton("⭐ Pro Tarif", callback_data="plan_select:pro")])
    elif current_plan == PLAN_CORE:
        # Pro tarifga o'tish
        keyboard.append([InlineKeyboardButton("⭐ Pro Tarifga O'tish", callback_data="plan_select:pro")])
        # Core tarifni uzaytirish
        keyboard.append([InlineKeyboardButton("📦 Core Tarifni Uzaytirish", callback_data="plan_select:core")])
    elif current_plan == PLAN_PRO:
        # Pro tarifni uzaytirish
        keyboard.append([InlineKeyboardButton("⭐ Pro Tarifni Uzaytirish", callback_data="plan_select:pro")])
    
    keyboard.append([InlineKeyboardButton("❌ Bekor qilish", callback_data="premium_cancel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await safe_reply_text(
        update.message,
        text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )


async def plan_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tarif tanlash callback"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "premium_cancel":
        await query.edit_message_text("❌ Tarif tanlash bekor qilindi.")
        return
    
    if not query.data.startswith("plan_select:"):
        return
    
    plan = query.data.split(":")[1]  # 'core' yoki 'pro'
    
    if plan not in [PLAN_CORE, PLAN_PRO]:
        await query.edit_message_text("❌ Xatolik: Noto'g'ri tarif.")
        return
    
    plan_features = get_plan_features(plan)
    plan_prices = PLAN_PRICES.get(plan, {})
    
    # Tarif paketlarini ko'rsatish
    text = f"""💎 <b>{plan_features['name_uz']} Tarif</b>

{plan_features['description_uz']}

✅ <b>Imkoniyatlar:</b>
• Quizlar: oyiga {plan_features['quizzes_per_month']} ta
• Savollar: quiz uchun {plan_features['max_questions_per_quiz']} ta
• AI parsing: {'✅' if plan_features['ai_parsing'] else '❌'}
• Fayl formatlar: {', '.join(plan_features['allowed_file_types'])}
• Fayl hajmi: {plan_features['max_file_size_mb']} MB
• Statistika: {'✅' if plan_features['advanced_statistics'] else '❌'}
• Export: {'✅' if plan_features['export_results'] else '❌'}
"""
    
    if plan == PLAN_PRO:
        text += f"• Priority support: ✅\n"
        text += f"• Custom branding: ✅\n"
        text += f"• API access: ✅\n"
    
    text += f"\n📦 <b>Paketlar:</b>"
    
    # Paketlar keyboard
    keyboard = []
    for key, info in plan_prices.items():
        label = f"{info['months']} oy - {info['price_text']}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"plan_buy:{plan}:{key}")])
    
    keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="premium_back")])
    keyboard.append([InlineKeyboardButton("❌ Bekor qilish", callback_data="premium_cancel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )


async def premium_buy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tarif buyurtma callback (eski format - backward compatibility)"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "premium_cancel":
        await query.edit_message_text("❌ Tarif buyurtma bekor qilindi.")
        return
    
    if query.data == "premium_back":
        # Orqaga qaytish
        await premium_command(update, context)
        return
    
    if not query.data.startswith("plan_buy:"):
        return
    
    # plan_buy:core:1_month yoki plan_buy:pro:1_month
    parts = query.data.split(":")
    if len(parts) < 3:
        await query.edit_message_text("❌ Xatolik: Noto'g'ri format.")
        return
    
    plan = parts[1]  # 'core' yoki 'pro'
    package_key = parts[2]  # '1_month', '3_months', etc.
    
    plan_prices = PLAN_PRICES.get(plan)
    if not plan_prices:
        await query.edit_message_text("❌ Xatolik: Tarif topilmadi.")
        return
    
    package_info = plan_prices.get(package_key)
    if not package_info:
        await query.edit_message_text("❌ Xatolik: Paket topilmadi.")
        return
    
    user_id = query.from_user.id
    username = query.from_user.username
    first_name = query.from_user.first_name
    
    # Telegram Stars invoice yuborish
    try:
        plan_name = get_plan_features(plan)['name_uz']
        await context.bot.send_invoice(
            chat_id=query.from_user.id,
            title=f"{plan_name} Tarif - {package_info['months']} oy",
            description=f"Quiz Bot {plan_name} tarif - {package_info['months']} oy davomida",
            payload=f"plan_{plan}_{user_id}_{package_key}",
            provider_token="",  # Stars uchun bo'sh string
            currency="XTR",  # Telegram Stars currency
            prices=[{"label": f"{package_info['months']} oy {plan_name}", "amount": package_info['stars']}],
            max_tip_amount=0,
            suggested_tip_amounts=[],
            start_parameter=f"plan_{plan}_{package_key}",
            provider_data=json.dumps({"plan": plan, "package": package_key, "user_id": user_id})
        )
        
        # Xabar yuborish
        text = f"""💳 <b>{plan_name} Tarif - To'lov</b>

📦 Paket: <b>{package_info['months']} oy</b>
💰 Narx: <b>{package_info['price_text']}</b>

Yuqorida invoice yuborildi. Uni ochib Telegram Stars bilan to'lang."""
        
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML
        )
        
    except Exception as e:
        logger.error(f"Tarif invoice yaratishda xatolik: {e}", exc_info=True)
        error_msg = str(e)
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
        if not payload.startswith("plan_"):
            await query.answer(ok=False, error_message="Noto'g'ri to'lov ma'lumotlari")
            return
        
        # plan_core_123456_1_month yoki plan_pro_123456_1_month
        parts = payload.split("_")
        if len(parts) < 4:
            await query.answer(ok=False, error_message="Noto'g'ri to'lov ma'lumotlari")
            return
        
        plan = parts[1]  # 'core' yoki 'pro'
        user_id = int(parts[2])
        package_key = "_".join(parts[3:])  # '1_month', '3_months', etc.
        
        # User ID tekshirish
        if query.from_user.id != user_id:
            await query.answer(ok=False, error_message="Foydalanuvchi ID mos kelmadi")
            return
        
        # Paket tekshirish
        plan_prices = PLAN_PRICES.get(plan)
        if not plan_prices:
            await query.answer(ok=False, error_message="Tarif topilmadi")
            return
        
        if package_key not in plan_prices:
            await query.answer(ok=False, error_message="Paket topilmadi")
            return
        
        # To'lov summasini tekshirish
        package_info = plan_prices[package_key]
        if query.total_amount != package_info['stars']:
            await query.answer(ok=False, error_message="To'lov summasi noto'g'ri")
            return
        
        # Barcha tekshiruvlar o'tdi
        await query.answer(ok=True)
        
    except Exception as e:
        logger.error(f"Pre-checkout xatolik: {e}")
        await query.answer(ok=False, error_message=f"Xatolik: {str(e)}")


async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muvaffaqiyatli to'lovdan keyin tarif aktivlashtirish"""
    message = update.message
    payment = message.successful_payment
    
    try:
        payload = payment.invoice_payload
        if not payload.startswith("plan_"):
            logger.warning(f"Noto'g'ri payload: {payload}")
            return
        
        # plan_core_123456_1_month yoki plan_pro_123456_1_month
        parts = payload.split("_")
        if len(parts) < 4:
            logger.warning(f"Noto'g'ri payload format: {payload}")
            return
        
        plan = parts[1]  # 'core' yoki 'pro'
        user_id = int(parts[2])
        package_key = "_".join(parts[3:])  # '1_month', '3_months', etc.
        
        # User ID tekshirish
        if message.from_user.id != user_id:
            logger.warning(f"User ID mos kelmadi: {message.from_user.id} != {user_id}")
            return
        
        # Paket ma'lumotlarini olish
        plan_prices = PLAN_PRICES.get(plan)
        if not plan_prices:
            logger.warning(f"Tarif topilmadi: {plan}")
            await message.reply_text("❌ Xatolik: Tarif topilmadi. Admin bilan bog'laning.")
            return
        
        package_info = plan_prices.get(package_key)
        if not package_info:
            logger.warning(f"Paket topilmadi: {package_key}")
            await message.reply_text("❌ Xatolik: Paket topilmadi. Admin bilan bog'laning.")
            return
        
        # Tarif aktivlashtirish
        username = message.from_user.username
        first_name = message.from_user.first_name
        
        storage.add_premium_user(
            user_id=user_id,
            stars_amount=payment.total_amount,
            months=package_info['months'],
            username=username,
            first_name=first_name,
            subscription_plan=plan
        )
        
        premium_info = storage.get_premium_user(user_id)
        plan_features = get_plan_features(plan)
        
        text = f"""✅ <b>{plan_features['name_uz']} Tarif Aktivlashtirildi!</b>

🎉 Tabriklaymiz! Sizning {plan_features['name_uz']} tarifingiz muvaffaqiyatli aktivlashtirildi.

📦 Paket: <b>{package_info['months']} oy</b>
💰 To'langan: <b>{payment.total_amount} ⭐</b>
"""
        
        if premium_info and premium_info.get('premium_until'):
            try:
                premium_until = datetime.fromisoformat(premium_info['premium_until']) if isinstance(premium_info['premium_until'], str) else premium_info['premium_until']
                text += f"📅 Tarif muddati: <b>{premium_until.strftime('%d.%m.%Y')}</b>\n"
            except (ValueError, AttributeError, TypeError) as e:
                logger.debug(f"Premium until date parsing xatolik (premium_info={premium_info}): {e}")
        
        text += f"\n💎 Endi siz:\n"
        text += f"• Oyiga {plan_features['quizzes_per_month']} ta quiz yarata olasiz\n"
        text += f"• AI parsing: {'✅' if plan_features['ai_parsing'] else '❌'}\n"
        text += f"• Statistika: {'✅' if plan_features['advanced_statistics'] else '❌'}\n"
        text += f"• Export: {'✅' if plan_features['export_results'] else '❌'}\n"
        
        if plan == PLAN_PRO:
            text += f"• Priority support: ✅\n"
            text += f"• Custom branding: ✅\n"
            text += f"• API access: ✅\n"
        
        text += f"\nRahmat! 🎊"
        
        await message.reply_text(text, parse_mode=ParseMode.HTML)
        
        logger.info(f"Tarif aktivlashtirildi: user_id={user_id}, plan={plan}, package={package_key}, stars={payment.total_amount}")
        
    except Exception as e:
        logger.error(f"Tarif aktivlashtirishda xatolik: {e}", exc_info=True)
        await message.reply_text(
            f"❌ Tarif aktivlashtirishda xatolik yuz berdi. "
            f"Iltimos, admin bilan bog'laning.\n\nXatolik: {str(e)}"
        )


def is_premium_or_has_quota(user_id: int) -> tuple[bool, str]:
    """Premium yoki quota borligini tekshirish (backward compatibility)
    
    Returns:
        (is_allowed, message) - ruxsat berilganmi va xabar
    """
    from bot.services.subscription import can_create_quiz
    return can_create_quiz(user_id)
