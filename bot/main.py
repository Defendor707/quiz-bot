#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram Quiz Bot - Asosiy fayl (Modullashtirilgan)
"""
import os
import logging
from dotenv import load_dotenv
from telegram.ext import Application, PicklePersistence
from telegram import MenuButtonCommands, BotCommand, BotCommandScopeDefault

# Load environment variables
load_dotenv()

# Logging sozlamalari
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Config yuklash
from bot.config import Config

# Handlerlarni import qilish
from bot.handlers import register_handlers

# Storage import
from bot.models import storage


async def periodic_cleanup(context):
    """Periodik tozalash - har 10 daqiqada bir marta"""
    try:
        from bot.services.quiz_service import cleanup_inactive_sessions, advance_due_sessions
        # JobQueue callback'da context.application qaytaradi
        application = context.application if hasattr(context, 'application') else context
        # Inactive sessionlarni tozalash
        await cleanup_inactive_sessions(application, max_age_seconds=3600)  # 1 soatdan eski sessionlar
        # Stuck sessionlarni ham tekshirish
        await advance_due_sessions(application)
        logger.info("🧹 Periodic cleanup: inactive sessionlar tozalandi va stuck sessionlar tekshirildi")
    except Exception as e:
        logger.error(f"❌ Periodic cleanup xatolik: {e}", exc_info=True)


async def periodic_status_report(context):
    """Periodik holat hisoboti - Gmail orqali yuborish"""
    try:
        from bot.services.status_report import send_status_report
        # JobQueue callback'da context.application qaytaradi
        application = context.application if hasattr(context, 'application') else context
        await send_status_report(application)
    except Exception as e:
        logger.error(f"❌ Periodic status report xatolik: {e}", exc_info=True)


async def post_init(application):
    """Bot ishga tushgandan keyin sozlamalar"""
    # Faol seanslarni tiklash va davom ettirish
    try:
        from bot.services.quiz_service import advance_due_sessions, cleanup_inactive_sessions
        # Birinchi marta cleanup va advance qilamiz
        await cleanup_inactive_sessions(application)
        await advance_due_sessions(application)
        logger.info("✅ Faol seanslar tekshirildi va tiklandi, eski sessionlar tozalandi")
    except Exception as e:
        logger.error(f"❌ Faol seanslarni tiklashda xatolik: {e}", exc_info=True)
    
    # Periodic cleanup task qo'shish (har 10 daqiqada)
    try:
        job_queue = application.job_queue
        if job_queue:
            job_queue.run_repeating(
                periodic_cleanup,
                interval=600,  # 10 daqiqa = 600 sekund
                first=600,  # Birinchi marta 10 daqiqadan keyin
                name="periodic_cleanup"
            )
            logger.info("✅ Periodic cleanup task qo'shildi (har 10 daqiqada)")
        else:
            logger.warning("⚠️ JobQueue topilmadi, periodic cleanup qo'shilmadi")
    except Exception as e:
        logger.error(f"❌ Periodic cleanup task qo'shishda xatolik: {e}", exc_info=True)
    
    # Periodic status report task qo'shish (Gmail orqali)
    # JobQueue post_init da hali tayyor bo'lmasligi mumkin, shuning uchun keyinroq qo'shish uchun flag qo'yamiz
    if Config.STATUS_REPORT_ENABLED:
        try:
            # JobQueue ni tekshirish - agar None bo'lsa, run_polling/run_webhook dan keyin qo'shamiz
            if application.job_queue is None:
                # Flag qo'yamiz, keyinroq qo'shish uchun
                application.bot_data['_status_report_pending'] = True
                logger.info("ℹ️ JobQueue hali tayyor emas, bot ishga tushgandan keyin qo'shiladi")
            else:
                interval = Config.STATUS_REPORT_INTERVAL
                application.job_queue.run_repeating(
                    periodic_status_report,
                    interval=interval,
                    first=interval,  # Birinchi marta interval dan keyin
                    name="periodic_status_report"
                )
                logger.info(f"✅ Periodic status report task qo'shildi (har {interval} sekundda, {interval/3600:.1f} soatda)")
        except Exception as e:
            logger.error(f"❌ Periodic status report task qo'shishda xatolik: {e}", exc_info=True)
    else:
        logger.info("ℹ️ Status report o'chirilgan (STATUS_REPORT_ENABLED=false)")
    
    # Bot commands ro'yxatini sozlash (avval)
    try:
        commands = [
            BotCommand("start", "Botni ishga tushirish"),
            BotCommand("help", "Yordam va qo'llanma"),
            BotCommand("quizzes", "Mavjud quizlar ro'yxati"),
            BotCommand("myresults", "Mening natijalarim"),
            BotCommand("myquizzes", "Mening quizlarim"),
            BotCommand("searchquiz", "Quiz qidirish"),
            BotCommand("startquiz", "Guruhda quiz boshlash"),
            BotCommand("admin", "Admin panel"),
        ]
        await application.bot.set_my_commands(
            commands=commands,
            scope=BotCommandScopeDefault()
        )
        logger.info("✅ Bot commands ro'yxati sozlandi")
    except Exception as e:
        logger.error(f"❌ Bot commands sozlashda xatolik: {e}", exc_info=True)
    
    # Menu button ni yoqish (commandlar ro'yxati) - commands dan keyin
    try:
        # Avval o'chirib, keyin qayta sozlaymiz (to'liq yangilash uchun)
        await application.bot.set_chat_menu_button(
            chat_id=None,  # None = barcha private chatlar uchun
            menu_button=MenuButtonCommands()
        )
        logger.info("✅ Menu button (commandlar ro'yxati) yoqildi")
        
        # Tekshirish
        current_menu = await application.bot.get_chat_menu_button()
        logger.info(f"📱 Menu button holati: {current_menu.type}")
    except Exception as e:
        logger.error(f"❌ Menu button sozlashda xatolik: {e}", exc_info=True)
    
    # Sardorbekni VIP user qilib qo'shish
    try:
        sardorbek_id = 6444578922
        if not storage.is_vip_user(sardorbek_id):
            storage.add_vip_user(sardorbek_id, nickname="Sardorbek ⭐")
            logger.info(f"✅ Sardorbek ({sardorbek_id}) VIP user qilib qo'shildi")
        else:
            logger.info(f"ℹ️ Sardorbek ({sardorbek_id}) allaqachon VIP user")
    except Exception as e:
        logger.error(f"❌ Sardorbekni VIP user qilib qo'shishda xatolik: {e}", exc_info=True)


def main():
    """Bot ishga tushirish"""
    logger.info("🚀 Quiz Bot ishga tushmoqda (Modullashtirilgan)...")
    
    if not Config.BOT_TOKEN:
        logger.error("❌ BOT_TOKEN topilmadi! .env faylni tekshiring.")
        return
    
    if not Config.DEEPSEEK_API_KEY:
        logger.warning("⚠️ DEEPSEEK_API_KEY topilmadi! AI funksiyalari ishlamaydi.")
    
    # Persistence
    persistence = PicklePersistence(filepath='bot_persistence.pickle')
    
    # Application yaratish
    application = Application.builder().token(Config.BOT_TOKEN).persistence(persistence).post_init(post_init).build()
    
    # Handlerlarni ro'yxatdan o'tkazish
    register_handlers(application)
    logger.info("✅ Barcha handlerlar ro'yxatdan o'tkazildi")
    
    # Status report job qo'shish (agar post_init da qo'shilmagan bo'lsa)
    # JobQueue run_polling/run_webhook dan oldin tayyor bo'lishi kerak
    if Config.STATUS_REPORT_ENABLED and application.bot_data.get('_status_report_pending'):
        try:
            # Application initialize qilish (JobQueue yaratish uchun)
            import asyncio
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            if not loop.is_running():
                # Agar loop ishlamayotgan bo'lsa, initialize qilamiz
                loop.run_until_complete(application.initialize())
                if application.job_queue:
                    interval = Config.STATUS_REPORT_INTERVAL
                    application.job_queue.run_repeating(
                        periodic_status_report,
                        interval=interval,
                        first=interval,
                        name="periodic_status_report"
                    )
                    logger.info(f"✅ Periodic status report task qo'shildi (har {interval} sekundda)")
                    application.bot_data.pop('_status_report_pending', None)
        except Exception as e:
            logger.error(f"❌ Status report job qo'shishda xatolik: {e}", exc_info=True)
    
    # Bot ishga tushirish
    if Config.USE_WEBHOOK:
        if not Config.WEBHOOK_URL:
            logger.warning("⚠️ USE_WEBHOOK=True, lekin WEBHOOK_URL sozlanmagan! Polling rejimiga o'tilmoqda...")
            logger.info("🔄 Bot polling rejimida ishlamoqda...")
            application.run_polling()
            return
        
        logger.info(f"🔄 Bot webhook rejimida ishlamoqda...")
        logger.info(f"📍 Webhook URL: {Config.WEBHOOK_URL}")
        logger.info(f"🔌 Port: {Config.WEBHOOK_PORT}, Path: {Config.WEBHOOK_PATH}")
        logger.info(f"🔒 SSL nginx reverse proxy orqali qilinadi. Bot HTTP da ishlaydi.")
        
        # Webhook server ni ishga tushiramiz
        # Agar xatolik bo'lsa, avtomatik polling rejimiga o'tamiz
        try:
            logger.info("🚀 Webhook server ishga tushmoqda...")
            application.run_webhook(
                listen=Config.WEBHOOK_LISTEN,
                port=Config.WEBHOOK_PORT,
                url_path=Config.WEBHOOK_PATH,
                webhook_url=Config.WEBHOOK_URL,
                # cert va key ni qo'shmasdan, nginx orqali SSL qilinadi
                secret_token=Config.WEBHOOK_SECRET_TOKEN if Config.WEBHOOK_SECRET_TOKEN else None,
            )
        except KeyboardInterrupt:
            logger.info("🛑 Bot to'xtatildi")
            raise
        except Exception as e:
            logger.error(f"❌ Webhook ishga tushirishda xatolik: {e}", exc_info=True)
            logger.warning("⚠️ Polling rejimiga o'tilmoqda...")
            # Webhook ni o'chiramiz
            try:
                import asyncio
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(application.bot.delete_webhook(drop_pending_updates=True))
                loop.close()
            except Exception as ex:
                logger.warning(f"⚠️ Webhook o'chirishda xatolik: {ex}")
            logger.info("🔄 Bot polling rejimida ishlamoqda...")
            application.run_polling()
    else:
        logger.info("🔄 Bot polling rejimida ishlamoqda...")
        application.run_polling()


if __name__ == '__main__':
    main()

