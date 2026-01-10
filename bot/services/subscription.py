#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Subscription Plans - Free, Core, Pro tariflar tizimi
"""
import logging
from typing import Dict, Optional
from datetime import datetime, timedelta
from bot.models import storage

logger = logging.getLogger(__name__)

# Tariflar
PLAN_FREE = 'free'
PLAN_CORE = 'core'
PLAN_PRO = 'pro'

# Tariflar narxlari (Telegram Stars)
PLAN_PRICES = {
    PLAN_CORE: {
        '1_month': {'stars': 50, 'months': 1, 'price_text': '50 ⭐'},
        '3_months': {'stars': 120, 'months': 3, 'price_text': '120 ⭐ (20% chegirma)'},
        '6_months': {'stars': 200, 'months': 6, 'price_text': '200 ⭐ (33% chegirma)'},
        '12_months': {'stars': 350, 'months': 12, 'price_text': '350 ⭐ (42% chegirma)'}
    },
    PLAN_PRO: {
        '1_month': {'stars': 100, 'months': 1, 'price_text': '100 ⭐'},
        '3_months': {'stars': 250, 'months': 3, 'price_text': '250 ⭐ (17% chegirma)'},
        '6_months': {'stars': 450, 'months': 6, 'price_text': '450 ⭐ (25% chegirma)'},
        '12_months': {'stars': 800, 'months': 12, 'price_text': '800 ⭐ (33% chegirma)'}
    }
}

# Tariflar limitlari va imkoniyatlari
PLAN_FEATURES = {
    PLAN_FREE: {
        'name': 'Free',
        'name_uz': 'Bepul',
        'quizzes_per_month': 5,
        'max_questions_per_quiz': 20,
        'ai_parsing': False,
        'file_parsing': True,  # Faqat TXT
        'allowed_file_types': ['.txt'],
        'max_file_size_mb': 1,
        'priority_support': False,
        'advanced_statistics': False,
        'export_results': False,
        'custom_branding': False,
        'api_access': False,
        'description': 'Asosiy imkoniyatlar - bepul',
        'description_uz': 'Asosiy imkoniyatlar - bepul'
    },
    PLAN_CORE: {
        'name': 'Core',
        'name_uz': 'Core',
        'quizzes_per_month': 50,
        'max_questions_per_quiz': 50,
        'ai_parsing': True,
        'file_parsing': True,  # PDF, DOCX, TXT
        'allowed_file_types': ['.txt', '.pdf', '.docx'],
        'max_file_size_mb': 5,
        'priority_support': False,
        'advanced_statistics': True,
        'export_results': True,
        'custom_branding': False,
        'api_access': False,
        'description': 'Yuqori imkoniyatlar - professional ishlatish uchun',
        'description_uz': 'Yuqori imkoniyatlar - professional ishlatish uchun'
    },
    PLAN_PRO: {
        'name': 'Pro',
        'name_uz': 'Pro',
        'quizzes_per_month': 999,  # De-facto cheksiz
        'max_questions_per_quiz': 100,
        'ai_parsing': True,
        'file_parsing': True,  # Barcha formatlar
        'allowed_file_types': ['.txt', '.pdf', '.docx'],
        'max_file_size_mb': 10,
        'priority_support': True,
        'advanced_statistics': True,
        'export_results': True,
        'custom_branding': True,
        'api_access': True,
        'description': 'Premium imkoniyatlar - professional va enterprise',
        'description_uz': 'Premium imkoniyatlar - professional va enterprise'
    }
}


def get_user_plan(user_id: int) -> str:
    """Foydalanuvchi tarifini olish"""
    # Sudo va VIP userlar Pro tarifga ega
    if storage.is_sudo_user(user_id) or storage.is_vip_user(user_id):
        return PLAN_PRO
    
    # Premium user tekshirish
    premium_info = storage.get_premium_user(user_id)
    if premium_info:
        # Premium muddati tekshirish
        premium_until = premium_info.get('premium_until')
        if premium_until:
            try:
                until_date = datetime.fromisoformat(premium_until) if isinstance(premium_until, str) else premium_until
                if until_date > datetime.now():
                    # Premium faol, tarifni olish
                    return premium_info.get('subscription_plan', PLAN_PRO)  # Default: Pro (backward compatibility)
            except (ValueError, AttributeError, TypeError) as e:
                logger.debug(f"Premium until date parsing xatolik (premium_until={premium_until}): {e}")
                pass
    
    return PLAN_FREE


def get_plan_features(plan: str) -> Dict:
    """Tarif imkoniyatlarini olish"""
    return PLAN_FEATURES.get(plan, PLAN_FEATURES[PLAN_FREE])


def can_create_quiz(user_id: int) -> tuple[bool, str]:
    """Foydalanuvchi quiz yarata oladimi?"""
    plan = get_user_plan(user_id)
    features = get_plan_features(plan)
    
    # Bu oy yaratilgan quizlar soni
    quizzes_this_month = storage.get_user_quizzes_count_this_month(user_id)
    limit = features['quizzes_per_month']
    
    if quizzes_this_month >= limit:
        plan_name = features['name_uz']
        return False, (
            f"❌ Sizning {plan_name} tarifingizda oyiga {limit} ta quiz limiti bor.\n\n"
            f"Siz allaqachon {quizzes_this_month} ta quiz yaratdingiz.\n\n"
            f"💎 Tarifni yangilash uchun /premium buyrug'ini ishlating."
        )
    
    return True, ""


def can_parse_file(user_id: int, file_extension: str, file_size_mb: float) -> tuple[bool, str]:
    """Foydalanuvchi fayl parse qila oladimi?"""
    plan = get_user_plan(user_id)
    features = get_plan_features(plan)
    
    # Fayl tipi tekshirish
    if file_extension not in features['allowed_file_types']:
        plan_name = features['name_uz']
        allowed = ', '.join(features['allowed_file_types'])
        return False, (
            f"❌ {plan_name} tarifida {file_extension} format qo'llab-quvvatlanmaydi.\n\n"
            f"Ruxsat berilgan formatlar: {allowed}\n\n"
            f"💎 Pro tarifga o'ting: /premium"
        )
    
    # Fayl hajmi tekshirish
    if file_size_mb > features['max_file_size_mb']:
        plan_name = features['name_uz']
        max_size = features['max_file_size_mb']
        return False, (
            f"❌ {plan_name} tarifida maksimal fayl hajmi {max_size} MB.\n\n"
            f"Sizning faylingiz: {file_size_mb:.1f} MB\n\n"
            f"💎 Pro tarifga o'ting: /premium"
        )
    
    return True, ""


def can_use_ai_parsing(user_id: int) -> tuple[bool, str]:
    """Foydalanuvchi AI parsing ishlata oladimi?"""
    plan = get_user_plan(user_id)
    features = get_plan_features(plan)
    
    if not features['ai_parsing']:
        plan_name = features['name_uz']
        return False, (
            f"❌ {plan_name} tarifida AI parsing qo'llab-quvvatlanmaydi.\n\n"
            f"💎 Core yoki Pro tarifga o'ting: /premium"
        )
    
    return True, ""


def get_plan_info_text(user_id: int) -> str:
    """Foydalanuvchi tarif ma'lumotlarini matn ko'rinishida olish"""
    plan = get_user_plan(user_id)
    features = get_plan_features(plan)
    quizzes_this_month = storage.get_user_quizzes_count_this_month(user_id)
    
    text = f"📦 <b>Joriy Tarif: {features['name_uz']}</b>\n\n"
    text += f"📊 Bu oy yaratilgan quizlar: {quizzes_this_month}/{features['quizzes_per_month']}\n\n"
    
    text += f"✅ <b>Imkoniyatlar:</b>\n"
    text += f"• Quizlar: oyiga {features['quizzes_per_month']} ta\n"
    text += f"• Savollar: quiz uchun {features['max_questions_per_quiz']} ta\n"
    text += f"• Fayl formatlar: {', '.join(features['allowed_file_types'])}\n"
    text += f"• Fayl hajmi: {features['max_file_size_mb']} MB\n"
    text += f"• AI parsing: {'✅' if features['ai_parsing'] else '❌'}\n"
    text += f"• Statistika: {'✅' if features['advanced_statistics'] else '❌'}\n"
    text += f"• Export: {'✅' if features['export_results'] else '❌'}\n"
    
    if plan == PLAN_FREE:
        text += f"\n💎 <b>Tarifni yangilash:</b>\n"
        text += f"• Core: 50 ⭐/oy - Yuqori imkoniyatlar\n"
        text += f"• Pro: 100 ⭐/oy - Premium imkoniyatlar\n"
        text += f"\n/premium buyrug'i orqali tarifni yangilang!"
    
    return text
