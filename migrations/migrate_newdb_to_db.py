#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Migration script: newdb papkadagi JSON export dan professional PostgreSQL database ga ma'lumot ko'chirish
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
            if dt.tzinfo is not None:
                dt = dt.replace(tzinfo=None)
            return dt
    except Exception as e:
        logger.warning(f"Datetime parse xatolik: {date_str}, {e}")
    return datetime.utcnow()


def migrate_users(db, json_data):
    """Users ma'lumotlarini ko'chirish"""
    logger.info("Users ma'lumotlarini ko'chirish...")
    storage_json = json_data.get('storage_json', {})
    meta = storage_json.get('meta', {})
    users = meta.get('users', {})
    count = 0
    updated = 0
    created = 0
    
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
                updated += 1
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
                created += 1
            
            count += 1
            if count % 100 == 0:
                db.commit()
                logger.info(f"  {count} ta user ko'chirildi... (created: {created}, updated: {updated})")
        except Exception as e:
            logger.error(f"User ko'chirishda xatolik (user_id={user_id_str}): {e}")
            db.rollback()
            continue
    
    db.commit()
    logger.info(f"✅ {count} ta user ko'chirildi (created: {created}, updated: {updated})")


def migrate_groups(db, json_data):
    """Groups ma'lumotlarini ko'chirish"""
    logger.info("Groups ma'lumotlarini ko'chirish...")
    storage_json = json_data.get('storage_json', {})
    meta = storage_json.get('meta', {})
    groups = meta.get('groups', {})
    count = 0
    updated = 0
    created = 0
    
    for chat_id_str, group_data in groups.items():
        try:
            chat_id = int(chat_id_str)
            
            existing = db.query(Group).filter(Group.chat_id == chat_id).first()
            if existing:
                existing.title = group_data.get('title')
                existing.chat_type = group_data.get('chat_type')
                existing.bot_status = group_data.get('bot_status')
                existing.bot_is_admin = group_data.get('bot_is_admin', False)
                if group_data.get('last_seen'):
                    existing.last_seen = parse_iso_datetime(group_data['last_seen'])
                updated += 1
            else:
                group = Group(
                    chat_id=chat_id,
                    title=group_data.get('title'),
                    chat_type=group_data.get('chat_type'),
                    bot_status=group_data.get('bot_status'),
                    bot_is_admin=group_data.get('bot_is_admin', False),
                    last_seen=parse_iso_datetime(group_data.get('last_seen', datetime.utcnow().isoformat()))
                )
                db.add(group)
                created += 1
            
            # Allowed quiz IDs
            allowed_quiz_ids = group_data.get('allowed_quiz_ids', [])
            if isinstance(allowed_quiz_ids, list):
                for quiz_id in allowed_quiz_ids:
                    if quiz_id:
                        try:
                            # Tekshirish - mavjud bo'lmasa qo'shish
                            existing_allowlist = db.query(GroupQuizAllowlist).filter(
                                GroupQuizAllowlist.chat_id == chat_id,
                                GroupQuizAllowlist.quiz_id == str(quiz_id)
                            ).first()
                            
                            if not existing_allowlist:
                                allowlist = GroupQuizAllowlist(
                                    chat_id=chat_id,
                                    quiz_id=str(quiz_id)
                                )
                                db.add(allowlist)
                        except Exception as e:
                            logger.warning(f"Allowlist qo'shishda xatolik (chat_id={chat_id}, quiz_id={quiz_id}): {e}")
            
            count += 1
            if count % 50 == 0:
                db.commit()
                logger.info(f"  {count} ta group ko'chirildi... (created: {created}, updated: {updated})")
        except Exception as e:
            logger.error(f"Group ko'chirishda xatolik (chat_id={chat_id_str}): {e}")
            db.rollback()
            continue
    
    db.commit()
    logger.info(f"✅ {count} ta group ko'chirildi (created: {created}, updated: {updated})")


def migrate_quizzes(db, json_data):
    """Quizzes va questions ma'lumotlarini ko'chirish"""
    logger.info("Quizzes va Questions ma'lumotlarini ko'chirish...")
    storage_json = json_data.get('storage_json', {})
    quizzes = storage_json.get('quizzes', {})
    count = 0
    updated = 0
    created = 0
    
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
                updated += 1
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
                created += 1
            
            db.flush()  # ID ni olish uchun
            
            # Eski questions ni o'chirish (yangi ma'lumot bilan almashtirish)
            db.query(Question).filter(Question.quiz_id == quiz_id).delete()
            
            # Questions yaratish
            questions = quiz_data.get('questions', [])
            question_count = 0
            skipped_questions = 0
            for idx, question_data in enumerate(questions):
                try:
                    # correct_answer ni olish - None bo'lishi mumkin (oddiy poll uchun)
                    correct_answer = question_data.get('correct_answer')
                    # Agar string "None" yoki "null" bo'lsa, None ga o'girish
                    if correct_answer == "None" or correct_answer == "null" or correct_answer == "":
                        correct_answer = None
                    
                    question = Question(
                        quiz_id=quiz_id,
                        question_index=idx,
                        question_text=question_data.get('question', ''),
                        options=question_data.get('options', []),
                        correct_answer=correct_answer,  # None bo'lishi mumkin
                        explanation=question_data.get('explanation', '') or None
                    )
                    db.add(question)
                    question_count += 1
                except Exception as e:
                    logger.warning(f"Question qo'shishda xatolik (quiz_id={quiz_id}, index={idx}): {e}")
                    skipped_questions += 1
                    continue
            
            if skipped_questions > 0:
                logger.warning(f"⚠️ Quiz {quiz_id}: {skipped_questions} ta savol o'tkazib yuborildi")
            
            # Allowed groups (private quiz uchun)
            allowed_groups = quiz_data.get('allowed_groups', [])
            if isinstance(allowed_groups, list) and allowed_groups:
                for group_id in allowed_groups:
                    try:
                        existing_allowed = db.query(QuizAllowedGroup).filter(
                            QuizAllowedGroup.quiz_id == quiz_id,
                            QuizAllowedGroup.group_id == group_id
                        ).first()
                        
                        if not existing_allowed:
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
                logger.info(f"  {count} ta quiz ko'chirildi... (created: {created}, updated: {updated}, questions: {question_count})")
        except Exception as e:
            logger.error(f"Quiz ko'chirishda xatolik (quiz_id={quiz_id}): {e}")
            db.rollback()
            continue
    
    db.commit()
    logger.info(f"✅ {count} ta quiz ko'chirildi (created: {created}, updated: {updated})")


def migrate_results(db, json_data):
    """Quiz results ma'lumotlarini ko'chirish"""
    logger.info("Quiz Results ma'lumotlarini ko'chirish...")
    storage_json = json_data.get('storage_json', {})
    results = storage_json.get('results', [])
    count = 0
    created = 0
    skipped = 0
    missing_quiz = 0
    
    # Avval barcha mavjud quiz_id larni yig'ib olamiz (tezroq tekshirish uchun)
    existing_quiz_ids = set(db.query(Quiz.quiz_id).all())
    existing_quiz_ids = {quiz_id[0] for quiz_id in existing_quiz_ids}
    
    for result_data in results:
        try:
            quiz_id = result_data.get('quiz_id')
            
            # Quiz mavjudligini tekshirish
            if quiz_id not in existing_quiz_ids:
                missing_quiz += 1
                if missing_quiz <= 10:  # Faqat birinchi 10 tasini log qilish
                    logger.warning(f"⚠️ Result skipped: quiz_id={quiz_id} mavjud emas (quiz o'chirilgan bo'lishi mumkin)")
                continue
            
            # Duplicate tekshirish (agar mavjud bo'lsa, o'tkazib yuborish)
            existing = db.query(QuizResult).filter(
                QuizResult.quiz_id == quiz_id,
                QuizResult.user_id == result_data.get('user_id'),
                QuizResult.chat_id == result_data.get('chat_id'),
                QuizResult.completed_at == parse_iso_datetime(result_data.get('completed_at', datetime.utcnow().isoformat()))
            ).first()
            
            if existing:
                skipped += 1
                continue
            
            # Answers ni to'g'ri formatga o'girish (agar string keys bo'lsa)
            answers = result_data.get('answers', {})
            if answers and isinstance(answers, dict):
                # String keys ni int ga o'girish
                try:
                    answers = {int(k): v for k, v in answers.items() if str(k).isdigit()}
                except (ValueError, TypeError):
                    pass  # Agar xato bo'lsa, asl holatida qoldiramiz
            
            result = QuizResult(
                quiz_id=quiz_id,
                user_id=result_data.get('user_id'),
                chat_id=result_data.get('chat_id'),
                answers=answers,
                correct_count=result_data.get('correct_count', 0),
                total_count=result_data.get('total_count', 0),
                percentage=result_data.get('percentage', 0.0),
                answer_times=result_data.get('answer_times'),
                total_time=result_data.get('total_time'),
                avg_time=result_data.get('avg_time'),
                min_time=result_data.get('min_time'),
                max_time=result_data.get('max_time'),
                completed_at=parse_iso_datetime(result_data.get('completed_at', datetime.utcnow().isoformat()))
            )
            db.add(result)
            created += 1
            
            count += 1
            if count % 100 == 0:
                db.commit()
                logger.info(f"  {count} ta result ko'chirildi... (created: {created}, skipped: {skipped}, missing_quiz: {missing_quiz})")
        except Exception as e:
            logger.error(f"Result ko'chirishda xatolik (quiz_id={result_data.get('quiz_id', 'unknown')}): {e}")
            db.rollback()
            continue
    
    db.commit()
    logger.info(f"✅ {count} ta result ko'chirildi (created: {created}, skipped: {skipped}, missing_quiz: {missing_quiz})")


def migrate_sudo_users(db, json_data):
    """Sudo users ma'lumotlarini ko'chirish"""
    logger.info("Sudo Users ma'lumotlarini ko'chirish...")
    storage_json = json_data.get('storage_json', {})
    meta = storage_json.get('meta', {})
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
    storage_json = json_data.get('storage_json', {})
    meta = storage_json.get('meta', {})
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
    """Premium users va payments ma'lumotlarini ko'chirish"""
    logger.info("Premium Users ma'lumotlarini ko'chirish...")
    storage_json = json_data.get('storage_json', {})
    meta = storage_json.get('meta', {})
    premium_users = meta.get('premium_users', {})
    count = 0
    
    if not premium_users:
        logger.info("ℹ️ Premium users ma'lumotlari export da yo'q")
        return
    
    for user_id_str, premium_data in premium_users.items():
        try:
            user_id = int(user_id_str)
            premium_until = parse_iso_datetime(premium_data.get('premium_until', datetime.utcnow().isoformat()))
            
            # Premium user
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
    
    # Premium payments
    payments = meta.get('premium_payments', [])
    payment_count = 0
    if payments:
        for payment_data in payments:
            try:
                payment = PremiumPayment(
                    user_id=payment_data.get('user_id'),
                    stars_amount=payment_data.get('stars_amount', 0),
                    months=payment_data.get('months', 1),
                    premium_until=parse_iso_datetime(payment_data.get('premium_until', datetime.utcnow().isoformat())),
                    paid_at=parse_iso_datetime(payment_data.get('paid_at', datetime.utcnow().isoformat()))
                )
                db.add(payment)
                payment_count += 1
            except Exception as e:
                logger.error(f"Premium payment ko'chirishda xatolik: {e}")
    else:
        logger.info("ℹ️ Premium payments ma'lumotlari export da yo'q")
    
    db.commit()
    logger.info(f"✅ {count} ta premium user va {payment_count} ta payment ko'chirildi")


def migrate_required_channels(db, json_data):
    """Required channels ma'lumotlarini ko'chirish"""
    logger.info("Required Channels ma'lumotlarini ko'chirish...")
    storage_json = json_data.get('storage_json', {})
    meta = storage_json.get('meta', {})
    channels = meta.get('required_channels', [])
    count = 0
    
    for channel_data in channels:
        try:
            channel_id = channel_data.get('channel_id')
            if not channel_id:
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
    
    db.commit()
    logger.info(f"✅ {count} ta required channel ko'chirildi")


def cleanup_all_data(db):
    """Barcha eski ma'lumotlarni tozalash (newdb ma'lumotlari bilan almashtirish uchun)"""
    logger.warning("⚠️ BARCHA ESKI MA'LUMOTLAR O'CHIRILMOQDA...")
    logger.warning("⚠️ Bu operatsiya qaytarib bo'lmaydi!")
    
    counts = {}
    
    try:
        # Foreign key constraintlar tufayli, jadvallarni to'g'ri tartibda o'chirish
        # Child jadvallardan boshlash kerak
        
        # 1. QuizResults (eng ko'p foreign key'larga bog'liq)
        count = db.query(QuizResult).delete()
        counts['quiz_results'] = count
        logger.info(f"   - {count} ta quiz_result o'chirildi")
        
        # 2. Questions
        count = db.query(Question).delete()
        counts['questions'] = count
        logger.info(f"   - {count} ta question o'chirildi")
        
        # 3. QuizAllowedGroup
        count = db.query(QuizAllowedGroup).delete()
        counts['quiz_allowed_groups'] = count
        logger.info(f"   - {count} ta quiz_allowed_group o'chirildi")
        
        # 4. GroupQuizAllowlist
        count = db.query(GroupQuizAllowlist).delete()
        counts['group_quiz_allowlist'] = count
        logger.info(f"   - {count} ta group_quiz_allowlist o'chirildi")
        
        # 5. PremiumPayment
        count = db.query(PremiumPayment).delete()
        counts['premium_payments'] = count
        logger.info(f"   - {count} ta premium_payment o'chirildi")
        
        # 6. PremiumUser
        count = db.query(PremiumUser).delete()
        counts['premium_users'] = count
        logger.info(f"   - {count} ta premium_user o'chirildi")
        
        # 7. VipUser
        count = db.query(VipUser).delete()
        counts['vip_users'] = count
        logger.info(f"   - {count} ta vip_user o'chirildi")
        
        # 8. SudoUser
        count = db.query(SudoUser).delete()
        counts['sudo_users'] = count
        logger.info(f"   - {count} ta sudo_user o'chirildi")
        
        # 9. RequiredChannel
        count = db.query(RequiredChannel).delete()
        counts['required_channels'] = count
        logger.info(f"   - {count} ta required_channel o'chirildi")
        
        # 10. Quizzes (user'ga bog'liq, lekin questions allaqachon o'chirilgan)
        count = db.query(Quiz).delete()
        counts['quizzes'] = count
        logger.info(f"   - {count} ta quiz o'chirildi")
        
        # 11. Groups
        count = db.query(Group).delete()
        counts['groups'] = count
        logger.info(f"   - {count} ta group o'chirildi")
        
        # 12. Users (oxirgi, chunki boshqa jadvallar unga bog'liq)
        count = db.query(User).delete()
        counts['users'] = count
        logger.info(f"   - {count} ta user o'chirildi")
        
        db.commit()
        
        total = sum(counts.values())
        logger.warning(f"✅ Barcha eski ma'lumotlar o'chirildi (jami: {total} ta yozuv)")
        logger.info(f"📊 O'chirilgan jadvallar:")
        for table, count in counts.items():
            if count > 0:
                logger.info(f"   - {table}: {count} ta")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Ma'lumotlarni tozalashda xatolik: {e}", exc_info=True)
        db.rollback()
        return False


def main():
    """Asosiy migration funksiyasi"""
    # newdb papkasidagi export faylini topish
    newdb_dir = root_dir / 'newdb'
    json_files = list(newdb_dir.glob('*.json'))
    
    if not json_files:
        logger.error(f"❌ JSON fayl topilmadi: {newdb_dir}")
        return
    
    # Eng so'nggi faylni tanlash
    json_file = max(json_files, key=lambda p: p.stat().st_mtime)
    logger.info(f"📁 Topilgan JSON fayl: {json_file}")
    
    logger.info("🚀 Migration boshlanmoqda...")
    logger.info(f"📁 JSON fayl: {json_file}")
    
    # JSON ma'lumotlarini yuklash
    try:
        logger.info("📖 JSON faylni yuklash...")
        with open(json_file, 'r', encoding='utf-8') as f:
            json_data = json.load(f)
        logger.info("✅ JSON fayl yuklandi")
        
        # Statistikani ko'rsatish
        stats = json_data.get('statistics', {}).get('storage_json', {})
        if stats:
            logger.info(f"📊 Export statistikasi:")
            logger.info(f"   - Quizzes: {stats.get('quizzes_count', 0)}")
            logger.info(f"   - Results: {stats.get('results_count', 0)}")
            logger.info(f"   - Users: {stats.get('users_count', 0)}")
            logger.info(f"   - Groups: {stats.get('groups_count', 0)}")
    except Exception as e:
        logger.error(f"❌ JSON fayl yuklashda xatolik: {e}")
        return
    
    # Database jadvallarini yaratish
    logger.info("📊 Database jadvallarini yaratish/yangilash...")
    try:
        init_db()
        logger.info("✅ Database jadvallari tayyor")
    except Exception as e:
        logger.error(f"❌ Database jadvallarini yaratishda xatolik: {e}")
        return
    
    # Database session yaratish
    db = SessionLocal()
    
    try:
        # AVVAL BARCHA ESKI MA'LUMOTLARNI TOZALASH
        logger.info("\n" + "="*60)
        logger.info("🗑️  Eski ma'lumotlarni tozalash...")
        logger.info("="*60)
        
        if not cleanup_all_data(db):
            logger.error("❌ Ma'lumotlarni tozalashda xatolik yuz berdi!")
            return
        
        logger.info("\n" + "="*60)
        logger.info("📥 Yangi ma'lumotlarni ko'chirish...")
        logger.info("="*60 + "\n")
        
        # Migration bosqichlari (tartib bilan)
        migrate_users(db, json_data)
        migrate_groups(db, json_data)
        migrate_quizzes(db, json_data)
        migrate_results(db, json_data)
        migrate_sudo_users(db, json_data)
        migrate_vip_users(db, json_data)
        migrate_premium_users(db, json_data)
        migrate_required_channels(db, json_data)
        
        logger.info("\n" + "="*60)
        logger.info("🎉 Migration muvaffaqiyatli yakunlandi!")
        logger.info("="*60)
        
    except Exception as e:
        logger.error(f"❌ Migration xatoligi: {e}", exc_info=True)
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == '__main__':
    main()
