#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quiz created_at maydonlarini JSON dan database ga to'g'ri import qilish
"""
import os
import sys
import json
import logging
from datetime import datetime
from pathlib import Path

# Root papkaga qo'shish
root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))

# Environment variables yuklash
from dotenv import load_dotenv
load_dotenv()

from bot.models.database import SessionLocal
from bot.models.schema import Quiz

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def parse_iso_datetime(date_str: str) -> datetime:
    """ISO format datetime string ni datetime object ga o'girish"""
    try:
        if isinstance(date_str, str):
            # Z ni olib tashlash va timezone ni tuzatish
            date_str_clean = date_str.replace('Z', '').replace('+00:00', '')
            # ISO formatdan parse qilish
            dt = datetime.fromisoformat(date_str_clean)
            # Timezone ni olib tashlash (UTC deb hisoblaymiz)
            if dt.tzinfo is not None:
                dt = dt.replace(tzinfo=None)
            return dt
    except Exception as e:
        logger.warning(f"Datetime parse xatolik: {date_str}, {e}")
    return datetime.utcnow()


def fix_quiz_created_at():
    """Quiz created_at maydonlarini JSON dan to'g'ri yangilash"""
    json_file = root_dir / 'quizzes_storage.json'
    
    if not json_file.exists():
        logger.error(f"❌ JSON fayl topilmadi: {json_file}")
        return
    
    logger.info("🚀 Quiz created_at maydonlarini yangilash...")
    logger.info(f"📁 JSON fayl: {json_file}")
    
    # JSON ma'lumotlarini yuklash
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            json_data = json.load(f)
        logger.info("✅ JSON fayl yuklandi")
    except Exception as e:
        logger.error(f"❌ JSON fayl yuklashda xatolik: {e}")
        return
    
    # Database session yaratish
    db = SessionLocal()
    
    try:
        quizzes = json_data.get('quizzes', {})
        logger.info(f"📚 {len(quizzes)} ta quiz topildi")
        
        updated_count = 0
        not_found_count = 0
        error_count = 0
        
        for quiz_id, quiz_data in quizzes.items():
            try:
                # Database dan quizni topish
                quiz = db.query(Quiz).filter(Quiz.quiz_id == quiz_id).first()
                
                if not quiz:
                    not_found_count += 1
                    if not_found_count <= 5:  # Faqat birinchi 5 tasini ko'rsatish
                        logger.warning(f"⚠️ Quiz topilmadi: {quiz_id}")
                    continue
                
                # created_at ni yangilash
                if quiz_data.get('created_at'):
                    new_created_at = parse_iso_datetime(quiz_data['created_at'])
                    old_created_at = quiz.created_at
                    
                    # Agar created_at o'zgarmagan bo'lsa, yangilash
                    if old_created_at != new_created_at:
                        quiz.created_at = new_created_at
                        updated_count += 1
                        
                        if updated_count % 50 == 0:
                            db.commit()
                            logger.info(f"  {updated_count} ta quiz yangilandi...")
                    else:
                        logger.debug(f"Quiz {quiz_id} created_at o'zgarmagan")
                else:
                    logger.warning(f"Quiz {quiz_id} da created_at maydoni yo'q")
                    
            except Exception as e:
                error_count += 1
                logger.error(f"Quiz {quiz_id} yangilashda xatolik: {e}")
                continue
        
        # Qolgan o'zgarishlarni commit qilish
        db.commit()
        
        logger.info("=" * 60)
        logger.info(f"✅ Yangilash yakunlandi!")
        logger.info(f"📊 Statistika:")
        logger.info(f"   • Yangilangan: {updated_count}")
        logger.info(f"   • Topilmagan: {not_found_count}")
        logger.info(f"   • Xatoliklar: {error_count}")
        logger.info(f"   • Jami: {len(quizzes)}")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"❌ Yangilash xatoligi: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()


if __name__ == '__main__':
    fix_quiz_created_at()
