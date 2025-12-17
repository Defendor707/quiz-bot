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


async def post_init(application):
    """Bot ishga tushgandan keyin sozlamalar"""
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

