"""Models moduli - Ma'lumot modellari"""
import logging
from bot.config import Config

logger = logging.getLogger(__name__)

# Config orqali JSON yoki Database ni tanlash
if Config.USE_DATABASE:
    try:
        from bot.models.storage_db import StorageDB
        storage = StorageDB()
        logger.info("✅ Database Storage ishlatilmoqda (PostgreSQL)")
    except Exception as e:
        logger.error(f"❌ Database Storage yuklashda xatolik: {e}")
        logger.warning("⚠️ JSON Storage ga o'tilmoqda...")
        from bot.models.storage import Storage
        storage = Storage()
else:
    from bot.models.storage import Storage
    storage = Storage()
    logger.info("✅ JSON Storage ishlatilmoqda")

