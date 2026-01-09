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
            <span class="stat-label">📚 Quizlar:</span>
            <span class="stat-value">{quizzes_count}</span>
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
    Bot holat hisobotini email orqali yuborish
    
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
        success = email_service.send_email(
            subject=subject,
            body=report_html,
            is_html=True
        )
        
        if success:
            logger.info("✅ Status report email orqali muvaffaqiyatli yuborildi")
        else:
            logger.warning("⚠️ Status report yuborilmadi")
        
        return success
        
    except Exception as e:
        logger.error(f"❌ Status report yuborishda xatolik: {e}", exc_info=True)
        return False
