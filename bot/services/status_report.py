#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bot holat hisoboti yaratish va yuborish
"""
import logging
from datetime import datetime
from typing import Optional
from telegram.ext import Application
from bot.models import storage
from bot.services.email_service import email_service

logger = logging.getLogger(__name__)


async def generate_status_report(application: Application) -> str:
    """
    Bot holat hisobotini yaratish
    
    Args:
        application: Telegram Application instance
    
    Returns:
        Hisobot matni (HTML formatda)
    """
    try:
        # Statistikani yig'ish
        quizzes_count = storage.get_quizzes_count()
        results_count = storage.get_results_count()
        users_count = storage.get_users_count()
        groups_count = storage.get_groups_count()
        
        # Quiz statistikalarini yig'ish
        from datetime import datetime, timedelta
        now = datetime.now()
        today_start = datetime(now.year, now.month, now.day)
        week_start = today_start - timedelta(days=now.weekday())
        month_start = datetime(now.year, now.month, 1)
        
        # Bugungi quizlar
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
        
        # Aktiv sessionlarni hisoblash
        sessions = application.bot_data.get('sessions', {}) or {}
        active_sessions = sum(1 for s in sessions.values() if s.get('is_active', False))
        
        # Webhook holatini tekshirish
        webhook_status = "❓ Noma'lum"
        webhook_mode = "❓ Noma'lum"
        webhook_error = None
        pending_updates = 0
        
        try:
            webhook_info = await application.bot.get_webhook_info()
            if webhook_info.url:
                webhook_mode = "🟢 Webhook"
                pending_updates = webhook_info.pending_update_count
                if webhook_info.last_error_message:
                    webhook_status = f"⚠️ Xatolik: {webhook_info.last_error_message[:100]}"
                    webhook_error = webhook_info.last_error_message
                elif pending_updates > 0:
                    webhook_status = f"🟡 Kutmoqda: {pending_updates} update"
                else:
                    webhook_status = "✅ Ishlayapti"
            else:
                webhook_mode = "🔄 Polling"
                webhook_status = "✅ Ishlayapti"
        except Exception as e:
            logger.error(f"Webhook holatini olishda xatolik: {e}", exc_info=True)
            webhook_status = "❌ Xatolik"
            webhook_mode = "❓ Noma'lum"
        
        # Vaqt
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # HTML formatda hisobot yaratish
        html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{
            font-family: Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
        }}
        .header {{
            background-color: #4CAF50;
            color: white;
            padding: 20px;
            border-radius: 5px;
            margin-bottom: 20px;
        }}
        .section {{
            background-color: #f9f9f9;
            padding: 15px;
            margin: 10px 0;
            border-radius: 5px;
            border-left: 4px solid #4CAF50;
        }}
        .stat {{
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid #ddd;
        }}
        .stat:last-child {{
            border-bottom: none;
        }}
        .stat-label {{
            font-weight: bold;
        }}
        .stat-value {{
            color: #4CAF50;
        }}
        .status-ok {{
            color: #4CAF50;
        }}
        .status-warning {{
            color: #ff9800;
        }}
        .status-error {{
            color: #f44336;
        }}
        .footer {{
            margin-top: 20px;
            padding-top: 20px;
            border-top: 1px solid #ddd;
            color: #666;
            font-size: 0.9em;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>📊 Quiz Bot Holat Hisoboti</h1>
        <p>Vaqt: {current_time}</p>
    </div>
    
    <div class="section">
        <h2>📈 Umumiy Statistika</h2>
        <div class="stat">
            <span class="stat-label">📚 Jami Quizlar:</span>
            <span class="stat-value">{quizzes_count}</span>
        </div>
        <div class="stat">
            <span class="stat-label">📚 Bugungi Quizlar:</span>
            <span class="stat-value">{quizzes_today}</span>
        </div>
        <div class="stat">
            <span class="stat-label">📚 Bu Hafta Quizlar:</span>
            <span class="stat-value">{quizzes_this_week}</span>
        </div>
        <div class="stat">
            <span class="stat-label">📚 Bu Oy Quizlar:</span>
            <span class="stat-value">{quizzes_this_month}</span>
        </div>
        <div class="stat">
            <span class="stat-label">🧾 Natijalar:</span>
            <span class="stat-value">{results_count}</span>
        </div>
        <div class="stat">
            <span class="stat-label">👤 Bot foydalanuvchilar:</span>
            <span class="stat-value">{users_count}</span>
        </div>
        <div class="stat">
            <span class="stat-label">👥 Guruhlar:</span>
            <span class="stat-value">{groups_count}</span>
        </div>
        <div class="stat">
            <span class="stat-label">🟢 Aktiv sessionlar:</span>
            <span class="stat-value">{active_sessions}</span>
        </div>
    </div>
    
    <div class="section">
        <h2>🔧 Bot Holati</h2>
        <div class="stat">
            <span class="stat-label">Rejim:</span>
            <span class="stat-value">{webhook_mode}</span>
        </div>
        <div class="stat">
            <span class="stat-label">Holat:</span>
            <span class="stat-value {'status-ok' if '✅' in webhook_status else 'status-warning' if '⚠️' in webhook_status or '🟡' in webhook_status else 'status-error'}">{webhook_status}</span>
        </div>
        {f'<div class="stat"><span class="stat-label">Kutilayotgan updatelar:</span><span class="stat-value">{pending_updates}</span></div>' if pending_updates > 0 else ''}
        {f'<div class="stat"><span class="stat-label">⚠️ Xatolik:</span><span class="stat-value status-error">{webhook_error[:200]}</span></div>' if webhook_error else ''}
    </div>
    
    <div class="footer">
        <p>Bu avtomatik hisobot. Quiz Bot tomonidan yuborilgan.</p>
    </div>
</body>
</html>
        """
        
        return html_body
        
    except Exception as e:
        logger.error(f"❌ Status report yaratishda xatolik: {e}", exc_info=True)
        return f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
</head>
<body>
    <h1>❌ Xatolik</h1>
    <p>Status report yaratishda xatolik yuz berdi: {str(e)}</p>
    <p>Vaqt: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
</body>
</html>
        """


async def send_status_report(application: Application) -> bool:
    """
    Bot holat hisobotini email orqali yuborish va admin ga ham yuborish
    
    Args:
        application: Telegram Application instance
    
    Returns:
        True agar muvaffaqiyatli, False aks holda
    """
    try:
        # Hisobot yaratish
        report_html = await generate_status_report(application)
        
        # Email mavzusi
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        subject = f"📊 Quiz Bot Holat Hisoboti - {current_time}"
        
        # Email yuborish
        email_success = email_service.send_email(
            subject=subject,
            body=report_html,
            is_html=True
        )
        
        # Admin ga ham xabar yuborish (Telegram orqali)
        telegram_success = await send_status_report_to_admin(application, report_html, current_time)
        
        if email_success:
            logger.info("✅ Status report email orqali muvaffaqiyatli yuborildi")
        else:
            logger.warning("⚠️ Status report email yuborilmadi")
        
        if telegram_success:
            logger.info("✅ Status report admin ga Telegram orqali muvaffaqiyatli yuborildi")
        else:
            logger.warning("⚠️ Status report admin ga Telegram yuborilmadi")
        
        return email_success or telegram_success
        
    except Exception as e:
        logger.error(f"❌ Status report yuborishda xatolik: {e}", exc_info=True)
        return False


async def send_status_report_to_admin(application: Application, report_html: str, current_time: str) -> bool:
    """
    Admin ga status report yuborish (Telegram orqali)
    
    Args:
        application: Telegram Application instance
        report_html: HTML formatdagi hisobot
        current_time: Vaqt matni
    
    Returns:
        True agar muvaffaqiyatli, False aks holda
    """
    try:
        from bot.config import Config
        from telegram.constants import ParseMode
        from bot.models import storage
        
        # Admin ID larni olish
        admin_ids = Config.ADMIN_USER_IDS
        if not admin_ids:
            logger.warning("⚠️ Admin ID lar topilmadi, Telegram xabar yuborilmadi")
            return False
        
        # Statistikani yig'ish (qisqa formatda)
        quizzes_count = storage.get_quizzes_count()
        results_count = storage.get_results_count()
        users_count = storage.get_users_count()
        groups_count = storage.get_groups_count()
        
        sessions = application.bot_data.get('sessions', {}) or {}
        active_sessions = sum(1 for s in sessions.values() if s.get('is_active', False))
        
        # Quiz statistikalarini yig'ish
        from datetime import datetime, timedelta
        now = datetime.now()
        today_start = datetime(now.year, now.month, now.day)
        week_start = today_start - timedelta(days=now.weekday())
        month_start = datetime(now.year, now.month, 1)
        
        quizzes_today = 0
        quizzes_this_week = 0
        quizzes_this_month = 0
        
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
                except Exception:
                    pass
        
        # Webhook holatini tekshirish
        webhook_status = "✅ Ishlayapti"
        webhook_mode = "🔄 Polling"
        try:
            webhook_info = await application.bot.get_webhook_info()
            if webhook_info.url:
                webhook_mode = "🟢 Webhook"
                if webhook_info.last_error_message:
                    webhook_status = f"⚠️ Xatolik"
                elif webhook_info.pending_update_count > 0:
                    webhook_status = f"🟡 {webhook_info.pending_update_count} update kutmoqda"
                else:
                    webhook_status = "✅ Ishlayapti"
        except Exception:
            pass
        
        # Telegram xabar matni (qisqa va chiroyli formatda)
        telegram_text = (
            f"📊 <b>Quiz Bot Holat Hisoboti</b>\n\n"
            f"⏰ Vaqt: {current_time}\n\n"
            f"<b>📈 Umumiy Statistika:</b>\n"
            f"📚 Jami Quizlar: <b>{quizzes_count}</b>\n"
            f"📚 Bugungi Quizlar: <b>{quizzes_today}</b>\n"
            f"📚 Bu Hafta Quizlar: <b>{quizzes_this_week}</b>\n"
            f"📚 Bu Oy Quizlar: <b>{quizzes_this_month}</b>\n"
            f"🧾 Natijalar: <b>{results_count}</b>\n"
            f"👤 Bot foydalanuvchilar: <b>{users_count}</b>\n"
            f"👥 Guruhlar: <b>{groups_count}</b>\n"
            f"🟢 Aktiv sessionlar: <b>{active_sessions}</b>\n\n"
            f"<b>🔧 Bot Holati:</b>\n"
            f"{webhook_mode} - {webhook_status}\n\n"
            f"📧 To'liq hisobot email ga yuborildi."
        )
        
        # Barcha admin larga yuborish
        success_count = 0
        for admin_id in admin_ids:
            try:
                await application.bot.send_message(
                    chat_id=admin_id,
                    text=telegram_text,
                    parse_mode=ParseMode.HTML
                )
                success_count += 1
                logger.debug(f"✅ Status report admin {admin_id} ga yuborildi")
            except Exception as e:
                logger.error(f"❌ Admin {admin_id} ga xabar yuborishda xatolik: {e}", exc_info=True)
        
        return success_count > 0
        
    except Exception as e:
        logger.error(f"❌ Admin ga status report yuborishda xatolik: {e}", exc_info=True)
        return False
