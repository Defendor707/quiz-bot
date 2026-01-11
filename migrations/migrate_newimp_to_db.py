#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Migration script: newimp papkasidagi yangi JSON formatdan PostgreSQL database ga ma'lumot ko'chirish
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

from bot.config import Config
from bot.models.database import SessionLocal, init_db, engine
from bot.models.schema import (
    User, Group, Quiz, Question, QuizResult,
    GroupQuizAllowlist, QuizAllowedGroup,
    SudoUser, VipUser, PremiumUser, PremiumPayment, RequiredChannel
)

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
            if dt.tzinfo:
                dt = dt.replace(tzinfo=None)
            return dt
    except Exception as e:
        logger.warning(f"Datetime parse xatolik: {date_str}, {e}")
    return datetime.utcnow()


def migrate_users(db, json_data):
    """Users ma'lumotlarini ko'chirish"""
    logger.info("Users ma'lumotlarini ko'chirish...")
    # Yangi format: storage_json.meta.users
    meta = json_data.get('storage_json', {}).get('meta', {})
    users = meta.get('users', {})
    count = 0
    
    for user_id_str, user_data in users.items():
        try:
            user_id = int(user_id_str)
            
            # User mavjudligini tekshirish
            existing = db.query(User).filter(User.user_id == user_id).first()
            if existing:
                # Yangilash
                existing.username = user_data.get('username')
                existing.first_name = user_data.get('first_name')
                existing.last_name = user_data.get('last_name')
                existing.last_chat_id = user_data.get('last_chat_id')
                existing.last_chat_type = user_data.get('last_chat_type')
                if user_data.get('last_seen'):
                    existing.last_seen = parse_iso_datetime(user_data['last_seen'])
            else:
                # Yangi yaratish
                user = User(
                    user_id=user_id,
                    username=user_data.get('username'),
                    first_name=user_data.get('first_name'),
                    last_name=user_data.get('last_name'),
                    last_chat_id=user_data.get('last_chat_id'),
                    last_chat_type=user_data.get('last_chat_type'),
                    last_seen=parse_iso_datetime(user_data.get('last_seen', datetime.utcnow().isoformat()))
                )
                db.add(user)
            
            count += 1
            if count % 100 == 0:
                db.commit()
                logger.info(f"  {count} ta user ko'chirildi...")
        except Exception as e:
            logger.error(f"User ko'chirishda xatolik (user_id={user_id_str}): {e}")
            db.rollback()
            continue
    
    db.commit()
    logger.info(f"✅ {count} ta user ko'chirildi")


def migrate_groups(db, json_data):
    """Groups ma'lumotlarini ko'chirish"""
    logger.info("Groups ma'lumotlarini ko'chirish...")
    # Yangi format: storage_json.meta.groups
    meta = json_data.get('storage_json', {}).get('meta', {})
    groups = meta.get('groups', {})
    count = 0
    
    for chat_id_str, group_data in groups.items():
        try:
            chat_id = int(chat_id_str)
            
            # Group mavjudligini tekshirish
            existing = db.query(Group).filter(Group.chat_id == chat_id).first()
            if existing:
                # Yangilash
                existing.title = group_data.get('title')
                if group_data.get('added_at'):
                    existing.created_at = parse_iso_datetime(group_data['added_at'])
            else:
                # Yangi yaratish
                group = Group(
                    chat_id=chat_id,
                    title=group_data.get('title'),
                    created_at=parse_iso_datetime(group_data.get('added_at', datetime.utcnow().isoformat()))
                )
                db.add(group)
            
            count += 1
            if count % 100 == 0:
                db.commit()
                logger.info(f"  {count} ta group ko'chirildi...")
        except Exception as e:
            logger.error(f"Group ko'chirishda xatolik (chat_id={chat_id_str}): {e}")
            db.rollback()
            continue
    
    db.commit()
    logger.info(f"✅ {count} ta group ko'chirildi")


def migrate_quizzes(db, json_data):
    """Quizzes va questions ma'lumotlarini ko'chirish"""
    logger.info("Quizzes va Questions ma'lumotlarini ko'chirish...")
    # Yangi format: storage_json.quizzes
    storage_json = json_data.get('storage_json', {})
    quizzes = storage_json.get('quizzes', {})
    count = 0
    
    for quiz_id, quiz_data in quizzes.items():
        try:
            # Quiz yaratish
            existing_quiz = db.query(Quiz).filter(Quiz.quiz_id == quiz_id).first()
            
            if existing_quiz:
                # Mavjud quizni yangilash
                existing_quiz.title = quiz_data.get('title')
                existing_quiz.created_by = quiz_data.get('created_by')
                existing_quiz.created_in_chat = quiz_data.get('created_in_chat')
                existing_quiz.is_private = quiz_data.get('is_private', False)
                if quiz_data.get('created_at'):
                    existing_quiz.created_at = parse_iso_datetime(quiz_data['created_at'])
                quiz_obj = existing_quiz
            else:
                quiz_obj = Quiz(
                    quiz_id=quiz_id,
                    title=quiz_data.get('title'),
                    created_by=quiz_data.get('created_by'),
                    created_in_chat=quiz_data.get('created_in_chat'),
                    is_private=quiz_data.get('is_private', False),
                    created_at=parse_iso_datetime(quiz_data.get('created_at', datetime.utcnow().isoformat()))
                )
                db.add(quiz_obj)
            
            db.flush()  # ID ni olish uchun
            
            # Eski questions ni o'chirish (yangi ma'lumot bilan almashtirish)
            db.query(Question).filter(Question.quiz_id == quiz_id).delete()
            
            # Questions yaratish
            questions = quiz_data.get('questions', [])
            for idx, question_data in enumerate(questions):
                try:
                    question = Question(
                        quiz_id=quiz_id,
                        question_index=idx,
                        question_text=question_data.get('question', ''),
                        options=question_data.get('options', []),
                        correct_answer=question_data.get('correct_answer', 0),
                        explanation=question_data.get('explanation', '')
                    )
                    db.add(question)
                except Exception as e:
                    logger.warning(f"Question qo'shishda xatolik (quiz_id={quiz_id}, index={idx}): {e}")
            
            # Allowed groups (private quiz uchun)
            allowed_groups = quiz_data.get('allowed_groups', [])
            if isinstance(allowed_groups, list) and allowed_groups:
                # Eski allowed groups ni o'chirish
                db.query(QuizAllowedGroup).filter(QuizAllowedGroup.quiz_id == quiz_id).delete()
                
                for group_id in allowed_groups:
                    try:
                        allowed_group = QuizAllowedGroup(
                            quiz_id=quiz_id,
                            group_id=group_id
                        )
                        db.add(allowed_group)
                    except Exception as e:
                        logger.warning(f"Allowed group qo'shishda xatolik (quiz_id={quiz_id}, group_id={group_id}): {e}")
            
            count += 1
            if count % 50 == 0:
                db.commit()
                logger.info(f"  {count} ta quiz ko'chirildi...")
        except Exception as e:
            logger.error(f"Quiz ko'chirishda xatolik (quiz_id={quiz_id}): {e}")
            db.rollback()
            continue
    
    db.commit()
    logger.info(f"✅ {count} ta quiz ko'chirildi")


def migrate_results(db, json_data):
    """Quiz results ma'lumotlarini ko'chirish"""
    logger.info("Quiz Results ma'lumotlarini ko'chirish...")
    # Yangi format: storage_json.results (list)
    storage_json = json_data.get('storage_json', {})
    results = storage_json.get('results', [])
    count = 0
    
    for result_data in results:
        try:
            result = QuizResult(
                quiz_id=result_data.get('quiz_id'),
                user_id=result_data.get('user_id'),
                chat_id=result_data.get('chat_id'),
                answers=result_data.get('answers', {}),
                correct_count=result_data.get('correct_count', 0),
                total_count=result_data.get('total_count', 0),
                percentage=result_data.get('percentage', 0.0),
                completed_at=parse_iso_datetime(result_data.get('completed_at', datetime.utcnow().isoformat())),
                answer_times=result_data.get('answer_times', {}),
                total_time=result_data.get('total_time', 0.0),
                avg_time=result_data.get('avg_time', 0.0),
                min_time=result_data.get('min_time'),
                max_time=result_data.get('max_time')
            )
            db.add(result)
            count += 1
            
            if count % 500 == 0:
                db.commit()
                logger.info(f"  {count} ta result ko'chirildi...")
        except Exception as e:
            logger.warning(f"Result ko'chirishda xatolik: {e}")
            db.rollback()
            continue
    
    db.commit()
    logger.info(f"✅ {count} ta result ko'chirildi")


def migrate_sudo_users(db, json_data):
    """Sudo users ma'lumotlarini ko'chirish"""
    logger.info("Sudo Users ma'lumotlarini ko'chirish...")
    # Yangi format: storage_json.meta.sudo_users
    meta = json_data.get('storage_json', {}).get('meta', {})
    sudo_users = meta.get('sudo_users', {})
    count = 0
    
    for user_id_str, sudo_data in sudo_users.items():
        try:
            user_id = int(user_id_str)
            
            existing = db.query(SudoUser).filter(SudoUser.user_id == user_id).first()
            if not existing:
                sudo_user = SudoUser(
                    user_id=user_id,
                    username=sudo_data.get('username'),
                    first_name=sudo_data.get('first_name'),
                    added_at=parse_iso_datetime(sudo_data.get('added_at', datetime.utcnow().isoformat()))
                )
                db.add(sudo_user)
                count += 1
        except Exception as e:
            logger.error(f"Sudo user ko'chirishda xatolik (user_id={user_id_str}): {e}")
    
    db.commit()
    logger.info(f"✅ {count} ta sudo user ko'chirildi")


def migrate_vip_users(db, json_data):
    """VIP users ma'lumotlarini ko'chirish"""
    logger.info("VIP Users ma'lumotlarini ko'chirish...")
    # Yangi format: storage_json.meta.vip_users
    meta = json_data.get('storage_json', {}).get('meta', {})
    vip_users = meta.get('vip_users', {})
    count = 0
    
    for user_id_str, vip_data in vip_users.items():
        try:
            user_id = int(user_id_str)
            
            existing = db.query(VipUser).filter(VipUser.user_id == user_id).first()
            if not existing:
                vip_user = VipUser(
                    user_id=user_id,
                    username=vip_data.get('username'),
                    first_name=vip_data.get('first_name'),
                    nickname=vip_data.get('nickname'),
                    added_at=parse_iso_datetime(vip_data.get('added_at', datetime.utcnow().isoformat()))
                )
                db.add(vip_user)
                count += 1
        except Exception as e:
            logger.error(f"VIP user ko'chirishda xatolik (user_id={user_id_str}): {e}")
    
    db.commit()
    logger.info(f"✅ {count} ta VIP user ko'chirildi")


def migrate_premium_users(db, json_data):
    """Premium users ma'lumotlarini ko'chirish"""
    logger.info("Premium Users ma'lumotlarini ko'chirish...")
    # Yangi format: storage_json.meta.premium_users (agar mavjud bo'lsa)
    meta = json_data.get('storage_json', {}).get('meta', {})
    premium_users = meta.get('premium_users', {})
    count = 0
    
    for user_id_str, premium_data in premium_users.items():
        try:
            user_id = int(user_id_str)
            premium_until = parse_iso_datetime(premium_data.get('premium_until', datetime.utcnow().isoformat()))
            
            existing = db.query(PremiumUser).filter(PremiumUser.user_id == user_id).first()
            if existing:
                existing.username = premium_data.get('username')
                existing.first_name = premium_data.get('first_name')
                existing.premium_until = premium_until
                existing.stars_paid = premium_data.get('stars_paid', 0)
                existing.months = premium_data.get('months', 1)
                existing.last_updated = datetime.utcnow()
            else:
                premium_user = PremiumUser(
                    user_id=user_id,
                    username=premium_data.get('username'),
                    first_name=premium_data.get('first_name'),
                    premium_until=premium_until,
                    stars_paid=premium_data.get('stars_paid', 0),
                    months=premium_data.get('months', 1),
                    activated_at=parse_iso_datetime(premium_data.get('activated_at', datetime.utcnow().isoformat()))
                )
                db.add(premium_user)
                count += 1
        except Exception as e:
            logger.error(f"Premium user ko'chirishda xatolik (user_id={user_id_str}): {e}")
    
    db.commit()
    logger.info(f"✅ {count} ta premium user ko'chirildi")


def migrate_required_channels(db, json_data):
    """Required channels ma'lumotlarini ko'chirish"""
    logger.info("Required Channels ma'lumotlarini ko'chirish...")
    # Yangi format: storage_json.meta.required_channels (list yoki dict)
    meta = json_data.get('storage_json', {}).get('meta', {})
    required_channels = meta.get('required_channels', [])
    count = 0
    
    # List yoki dict formatini qo'llab-quvvatlash
    if isinstance(required_channels, list):
        # List formatida - har bir element dict
        for channel_data in required_channels:
            try:
                channel_id = int(channel_data.get('channel_id') or channel_data.get('id', 0))
                if channel_id == 0:
                    continue
                
                existing = db.query(RequiredChannel).filter(RequiredChannel.channel_id == channel_id).first()
                if not existing:
                    channel = RequiredChannel(
                        channel_id=channel_id,
                        channel_username=channel_data.get('channel_username'),
                        channel_title=channel_data.get('channel_title'),
                        added_at=parse_iso_datetime(channel_data.get('added_at', datetime.utcnow().isoformat()))
                    )
                    db.add(channel)
                    count += 1
            except Exception as e:
                logger.error(f"Required channel ko'chirishda xatolik: {e}")
    elif isinstance(required_channels, dict):
        # Dict formatida
        for channel_id_str, channel_data in required_channels.items():
            try:
                channel_id = int(channel_id_str)
                
                existing = db.query(RequiredChannel).filter(RequiredChannel.channel_id == channel_id).first()
                if not existing:
                    channel = RequiredChannel(
                        channel_id=channel_id,
                        channel_username=channel_data.get('channel_username'),
                        channel_title=channel_data.get('channel_title'),
                        added_at=parse_iso_datetime(channel_data.get('added_at', datetime.utcnow().isoformat()))
                    )
                    db.add(channel)
                    count += 1
            except Exception as e:
                logger.error(f"Required channel ko'chirishda xatolik: {e}")
    
    db.commit()
    logger.info(f"✅ {count} ta required channel ko'chirildi")


def migrate_group_quiz_allowlist(db, json_data):
    """Group quiz allowlist ma'lumotlarini ko'chirish"""
    logger.info("Group Quiz Allowlist ma'lumotlarini ko'chirish...")
    # Yangi format: storage_json.meta.group_quiz_allowlist (agar mavjud bo'lsa)
    meta = json_data.get('storage_json', {}).get('meta', {})
    group_quiz_allowlist = meta.get('group_quiz_allowlist', {})
    count = 0
    
    for chat_id_str, allowed_quiz_ids in group_quiz_allowlist.items():
        try:
            chat_id = int(chat_id_str)
            
            # Eski allowlist ni o'chirish
            db.query(GroupQuizAllowlist).filter(GroupQuizAllowlist.chat_id == chat_id).delete()
            
            if allowed_quiz_ids:
                for quiz_id in allowed_quiz_ids:
                    try:
                        allowlist = GroupQuizAllowlist(
                            chat_id=chat_id,
                            quiz_id=quiz_id
                        )
                        db.add(allowlist)
                        count += 1
                    except Exception as e:
                        logger.warning(f"Allowlist qo'shishda xatolik (chat_id={chat_id}, quiz_id={quiz_id}): {e}")
        except Exception as e:
            logger.error(f"Group allowlist ko'chirishda xatolik (chat_id={chat_id_str}): {e}")
    
    db.commit()
    logger.info(f"✅ {count} ta group allowlist item ko'chirildi")


def main():
    """Asosiy migration funksiyasi"""
    # newimp papkasidagi fayl
    json_file = root_dir / 'newimp' / 'database_export_20260111_175946.json'
    
    if not json_file.exists():
        logger.error(f"❌ JSON fayl topilmadi: {json_file}")
        return
    
    logger.info("🚀 Migration boshlanmoqda...")
    logger.info(f"📁 JSON fayl: {json_file}")
    
    # JSON ma'lumotlarini yuklash
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            json_data = json.load(f)
        logger.info("✅ JSON fayl yuklandi")
    except Exception as e:
        logger.error(f"❌ JSON fayl yuklashda xatolik: {e}")
        return
    
    # Database jadvallarini yaratish
    logger.info("📊 Database jadvallarini yaratish...")
    try:
        init_db()
        logger.info("✅ Database jadvallari yaratildi")
    except Exception as e:
        logger.error(f"❌ Database jadvallarini yaratishda xatolik: {e}")
        return
    
    # Database session yaratish
    db = SessionLocal()
    
    try:
        # Migration bosqichlari
        migrate_users(db, json_data)
        migrate_groups(db, json_data)
        migrate_quizzes(db, json_data)
        migrate_results(db, json_data)
        migrate_sudo_users(db, json_data)
        migrate_vip_users(db, json_data)
        migrate_premium_users(db, json_data)
        migrate_required_channels(db, json_data)
        migrate_group_quiz_allowlist(db, json_data)
        
        logger.info("🎉 Migration muvaffaqiyatli yakunlandi!")
        
    except Exception as e:
        logger.error(f"❌ Migration xatoligi: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()


if __name__ == '__main__':
    main()
