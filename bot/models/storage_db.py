"""Database-based storage implementation"""
import os
import logging
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_, or_

from bot.models.database import SessionLocal
from bot.models.schema import (
    User, Group, Quiz, Question, QuizResult,
    GroupQuizAllowlist, QuizAllowedGroup,
    SudoUser, VipUser, PremiumUser, PremiumPayment, RequiredChannel
)

logger = logging.getLogger(__name__)


class StorageDB:
    """PostgreSQL database bilan ishlaydigan Storage klass"""
    
    def __init__(self):
        """StorageDB init"""
        pass
    
    def _get_session(self) -> Session:
        """Database session olish"""
        return SessionLocal()
    
    def _to_dict(self, obj):
        """SQLAlchemy object ni dict ga o'girish"""
        if obj is None:
            return None
        if isinstance(obj, dict):
            return obj
        if hasattr(obj, '__dict__'):
            return {k: v for k, v in obj.__dict__.items() if not k.startswith('_')}
        return obj
    
    # ===== Quiz Methods =====
    
    def save_quiz(self, quiz_id: str, questions: List[Dict], created_by: int, created_in_chat: int, title: str = None):
        """Quizni saqlash"""
        db = self._get_session()
        try:
            # User mavjudligini tekshirish/yaratish
            user = db.query(User).filter(User.user_id == created_by).first()
            if not user:
                user = User(user_id=created_by)
                db.add(user)
                db.flush()
            
            # Quiz yaratish/yangilash
            quiz = db.query(Quiz).filter(Quiz.quiz_id == quiz_id).first()
            if quiz:
                quiz.title = title
                # Eski questions ni o'chirish
                db.query(Question).filter(Question.quiz_id == quiz_id).delete()
            else:
                quiz = Quiz(
                    quiz_id=quiz_id,
                    title=title,
                    created_by=created_by,
                    created_in_chat=created_in_chat,
                    is_private=False
                )
                db.add(quiz)
            
            db.flush()
            
            # Questions qo'shish
            for idx, question_data in enumerate(questions):
                question = Question(
                    quiz_id=quiz_id,
                    question_index=idx,
                    question_text=question_data.get('question', ''),
                    options=question_data.get('options', []),
                    correct_answer=question_data.get('correct_answer', 0),
                    explanation=question_data.get('explanation', '')
                )
                db.add(question)
            
            db.commit()
        except Exception as e:
            logger.error(f"Quiz saqlashda xatolik: {e}", exc_info=True)
            db.rollback()
            raise
        finally:
            db.close()
    
    def get_quiz(self, quiz_id: str) -> Optional[Dict]:
        """Quizni olish"""
        db = self._get_session()
        try:
            quiz = db.query(Quiz).filter(Quiz.quiz_id == quiz_id).first()
            if not quiz:
                return None
            
            # Questions ni yuklash
            questions = db.query(Question).filter(
                Question.quiz_id == quiz_id
            ).order_by(Question.question_index).all()
            
            # Dict formatga o'girish
            quiz_dict = {
                'quiz_id': quiz.quiz_id,
                'title': quiz.title,
                'questions': [
                    {
                        'question': q.question_text,
                        'options': q.options,
                        'correct_answer': q.correct_answer,
                        'explanation': q.explanation or ''
                    }
                    for q in questions
                ],
                'created_by': quiz.created_by,
                'created_in_chat': quiz.created_in_chat,
                'created_at': quiz.created_at.isoformat() if quiz.created_at else datetime.utcnow().isoformat(),
                'is_private': quiz.is_private,
                'allowed_groups': [ag.group_id for ag in quiz.allowed_groups]
            }
            
            return quiz_dict
        except Exception as e:
            logger.error(f"Quiz olishda xatolik: {e}", exc_info=True)
            return None
        finally:
            db.close()
    
    def get_all_quizzes(self) -> List[Dict]:
        """Barcha quizlarni olish"""
        db = self._get_session()
        try:
            from sqlalchemy import func
            # Quiz va questions sonini birga olish
            quizzes_with_counts = db.query(
                Quiz,
                func.count(Question.id).label('questions_count')
            ).outerjoin(
                Question, Quiz.quiz_id == Question.quiz_id
            ).group_by(Quiz.quiz_id).order_by(desc(Quiz.created_at)).all()
            
            result = []
            for quiz, questions_count in quizzes_with_counts:
                quiz_dict = {
                    'quiz_id': quiz.quiz_id,
                    'title': quiz.title,
                    'created_by': quiz.created_by,
                    'created_in_chat': quiz.created_in_chat,
                    'created_at': quiz.created_at.isoformat() if quiz.created_at else datetime.utcnow().isoformat(),
                    'is_private': quiz.is_private,
                    'questions': [{}] * questions_count  # Questions sonini ko'rsatish uchun placeholder
                }
                result.append(quiz_dict)
            
            return result
        except Exception as e:
            logger.error(f"Barcha quizlarni olishda xatolik: {e}", exc_info=True)
            return []
        finally:
            db.close()
    
    def get_user_quizzes(self, user_id: int) -> List[Dict]:
        """Foydalanuvchining quizlarini olish"""
        db = self._get_session()
        try:
            from sqlalchemy import func
            # Quiz va questions sonini birga olish
            quizzes_with_counts = db.query(
                Quiz,
                func.count(Question.id).label('questions_count')
            ).outerjoin(
                Question, Quiz.quiz_id == Question.quiz_id
            ).filter(
                Quiz.created_by == user_id
            ).group_by(Quiz.quiz_id).order_by(desc(Quiz.created_at)).all()
            
            result = []
            for quiz, questions_count in quizzes_with_counts:
                quiz_dict = {
                    'quiz_id': quiz.quiz_id,
                    'title': quiz.title,
                    'created_by': quiz.created_by,
                    'created_in_chat': quiz.created_in_chat,
                    'created_at': quiz.created_at.isoformat() if quiz.created_at else datetime.utcnow().isoformat(),
                    'is_private': quiz.is_private,
                    'questions': [{}] * questions_count  # Questions sonini ko'rsatish uchun placeholder
                }
                result.append(quiz_dict)
            
            return result
        except Exception as e:
            logger.error(f"User quizzes olishda xatolik: {e}", exc_info=True)
            return []
        finally:
            db.close()
    
    def delete_quiz(self, quiz_id: str) -> bool:
        """Quizni o'chirish"""
        db = self._get_session()
        try:
            quiz = db.query(Quiz).filter(Quiz.quiz_id == quiz_id).first()
            if quiz:
                db.delete(quiz)
                db.commit()
                return True
            return False
        except Exception as e:
            logger.error(f"Quiz o'chirishda xatolik: {e}", exc_info=True)
            db.rollback()
            return False
        finally:
            db.close()
    
    def update_quiz_title(self, quiz_id: str, new_title: str) -> bool:
        """Quiz nomini yangilash"""
        db = self._get_session()
        try:
            quiz = db.query(Quiz).filter(Quiz.quiz_id == quiz_id).first()
            if quiz:
                quiz.title = new_title
                db.commit()
                return True
            return False
        except Exception as e:
            logger.error(f"Quiz nomini yangilashda xatolik: {e}", exc_info=True)
            db.rollback()
            return False
        finally:
            db.close()
    
    def set_quiz_private(self, quiz_id: str, is_private: bool) -> bool:
        """Quizni private/public qilish"""
        db = self._get_session()
        try:
            quiz = db.query(Quiz).filter(Quiz.quiz_id == quiz_id).first()
            if quiz:
                quiz.is_private = is_private
                if not is_private:
                    # Public qilinganda allowed_groups ni o'chirish
                    db.query(QuizAllowedGroup).filter(QuizAllowedGroup.quiz_id == quiz_id).delete()
                db.commit()
                return True
            return False
        except Exception as e:
            logger.error(f"Quiz private/public qilishda xatolik: {e}", exc_info=True)
            db.rollback()
            return False
        finally:
            db.close()
    
    def add_quiz_allowed_group(self, quiz_id: str, group_id: int) -> bool:
        """Private quiz uchun guruh qo'shish"""
        db = self._get_session()
        try:
            quiz = db.query(Quiz).filter(Quiz.quiz_id == quiz_id).first()
            if not quiz or not quiz.is_private:
                return False
            
            existing = db.query(QuizAllowedGroup).filter(
                QuizAllowedGroup.quiz_id == quiz_id,
                QuizAllowedGroup.group_id == group_id
            ).first()
            
            if not existing:
                allowed_group = QuizAllowedGroup(
                    quiz_id=quiz_id,
                    group_id=group_id
                )
                db.add(allowed_group)
                db.commit()
                return True
            return True  # Allaqachon mavjud
        except Exception as e:
            logger.error(f"Quiz allowed group qo'shishda xatolik: {e}", exc_info=True)
            db.rollback()
            return False
        finally:
            db.close()
    
    def remove_quiz_allowed_group(self, quiz_id: str, group_id: int) -> bool:
        """Private quiz uchun guruhni olib tashlash"""
        db = self._get_session()
        try:
            allowed_group = db.query(QuizAllowedGroup).filter(
                QuizAllowedGroup.quiz_id == quiz_id,
                QuizAllowedGroup.group_id == group_id
            ).first()
            
            if allowed_group:
                db.delete(allowed_group)
                db.commit()
                return True
            return False
        except Exception as e:
            logger.error(f"Quiz allowed group o'chirishda xatolik: {e}", exc_info=True)
            db.rollback()
            return False
        finally:
            db.close()
    
    def get_quiz_allowed_groups(self, quiz_id: str) -> List[int]:
        """Private quiz uchun ruxsat berilgan guruhlar ro'yxati"""
        db = self._get_session()
        try:
            allowed_groups = db.query(QuizAllowedGroup).filter(
                QuizAllowedGroup.quiz_id == quiz_id
            ).all()
            return [ag.group_id for ag in allowed_groups]
        except Exception as e:
            logger.error(f"Quiz allowed groups olishda xatolik: {e}", exc_info=True)
            return []
        finally:
            db.close()
    
    def is_quiz_allowed_in_group(self, quiz_id: str, group_id: int) -> bool:
        """Quiz guruhda ruxsat berilganmi tekshirish"""
        db = self._get_session()
        try:
            quiz = db.query(Quiz).filter(Quiz.quiz_id == quiz_id).first()
            if not quiz:
                return False
            
            # Agar quiz public bo'lsa, barcha guruhlarda ishlaydi
            if not quiz.is_private:
                return True
            
            # Private quiz uchun ruxsat berilganmi tekshirish
            allowed = db.query(QuizAllowedGroup).filter(
                QuizAllowedGroup.quiz_id == quiz_id,
                QuizAllowedGroup.group_id == group_id
            ).first()
            
            return allowed is not None
        except Exception as e:
            logger.error(f"Quiz allowed in group tekshirishda xatolik: {e}", exc_info=True)
            return False
        finally:
            db.close()
    
    # ===== User Methods =====
    
    def track_user(self, user_id: int, username: str = None, first_name: str = None, last_name: str = None,
                   last_chat_id: int = None, last_chat_type: str = None):
        """Foydalanuvchini tracking qilish"""
        db = self._get_session()
        try:
            user = db.query(User).filter(User.user_id == user_id).first()
            if user:
                user.username = username
                user.first_name = first_name
                user.last_name = last_name
                user.last_chat_id = last_chat_id
                user.last_chat_type = last_chat_type
                user.last_seen = datetime.utcnow()
            else:
                user = User(
                    user_id=user_id,
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                    last_chat_id=last_chat_id,
                    last_chat_type=last_chat_type
                )
                db.add(user)
            
            db.commit()
        except Exception as e:
            logger.error(f"User tracking xatolik: {e}", exc_info=True)
            db.rollback()
        finally:
            db.close()
    
    def get_users(self) -> List[Dict]:
        """Foydalanuvchilar ro'yxati"""
        db = self._get_session()
        try:
            users = db.query(User).order_by(desc(User.last_seen)).all()
            return [
                {
                    'user_id': u.user_id,
                    'username': u.username,
                    'first_name': u.first_name,
                    'last_name': u.last_name,
                    'last_chat_id': u.last_chat_id,
                    'last_chat_type': u.last_chat_type,
                    'last_seen': u.last_seen.isoformat() if u.last_seen else None
                }
                for u in users
            ]
        except Exception as e:
            logger.error(f"Users olishda xatolik: {e}", exc_info=True)
            return []
        finally:
            db.close()
    
    def get_users_count(self) -> int:
        """Foydalanuvchilar soni"""
        db = self._get_session()
        try:
            return db.query(User).count()
        except Exception as e:
            logger.error(f"Users count xatolik: {e}", exc_info=True)
            return 0
        finally:
            db.close()
    
    # ===== Group Methods =====
    
    def track_group(self, chat_id: int, title: str = None, chat_type: str = None, bot_status: str = None, bot_is_admin: bool = None):
        """Guruh/superguruhni tracking qilish"""
        db = self._get_session()
        try:
            group = db.query(Group).filter(Group.chat_id == chat_id).first()
            if group:
                if title is not None:
                    group.title = title
                if chat_type is not None:
                    group.chat_type = chat_type
                if bot_status is not None:
                    group.bot_status = bot_status
                if bot_is_admin is not None:
                    group.bot_is_admin = bot_is_admin
                group.last_seen = datetime.utcnow()
            else:
                group = Group(
                    chat_id=chat_id,
                    title=title,
                    chat_type=chat_type,
                    bot_status=bot_status,
                    bot_is_admin=bot_is_admin
                )
                db.add(group)
            
            db.commit()
        except Exception as e:
            logger.error(f"Group tracking xatolik: {e}", exc_info=True)
            db.rollback()
        finally:
            db.close()
    
    def get_groups(self) -> List[Dict]:
        """Guruhlar ro'yxati"""
        db = self._get_session()
        try:
            groups = db.query(Group).order_by(desc(Group.last_seen)).all()
            result = []
            
            for g in groups:
                # Allowed quiz IDs ni yuklash
                allowed = db.query(GroupQuizAllowlist).filter(
                    GroupQuizAllowlist.chat_id == g.chat_id
                ).all()
                
                group_dict = {
                    'chat_id': g.chat_id,
                    'title': g.title,
                    'chat_type': g.chat_type,
                    'bot_status': g.bot_status,
                    'bot_is_admin': g.bot_is_admin,
                    'last_seen': g.last_seen.isoformat() if g.last_seen else None,
                    'allowed_quiz_ids': [a.quiz_id for a in allowed]
                }
                result.append(group_dict)
            
            return result
        except Exception as e:
            logger.error(f"Groups olishda xatolik: {e}", exc_info=True)
            return []
        finally:
            db.close()
    
    def get_groups_count(self) -> int:
        """Guruhlar soni"""
        db = self._get_session()
        try:
            return db.query(Group).count()
        except Exception as e:
            logger.error(f"Groups count xatolik: {e}", exc_info=True)
            return 0
        finally:
            db.close()
    
    # ===== Group Quiz Allowlist =====
    
    def get_group_allowed_quiz_ids(self, chat_id: int) -> List[str]:
        """Guruh uchun ruxsat berilgan quiz IDs"""
        db = self._get_session()
        try:
            allowlist = db.query(GroupQuizAllowlist).filter(
                GroupQuizAllowlist.chat_id == chat_id
            ).all()
            return [a.quiz_id for a in allowlist]
        except Exception as e:
            logger.error(f"Group allowed quiz IDs olishda xatolik: {e}", exc_info=True)
            return []
        finally:
            db.close()
    
    def set_group_allowed_quiz_ids(self, chat_id: int, quiz_ids: List[str]):
        """Guruh uchun ruxsat berilgan quiz IDs ni sozlash"""
        db = self._get_session()
        try:
            # Eski allowlist ni o'chirish
            db.query(GroupQuizAllowlist).filter(
                GroupQuizAllowlist.chat_id == chat_id
            ).delete()
            
            # Yangi allowlist qo'shish
            for quiz_id in quiz_ids:
                if quiz_id:
                    allowlist = GroupQuizAllowlist(
                        chat_id=chat_id,
                        quiz_id=str(quiz_id)
                    )
                    db.add(allowlist)
            
            db.commit()
        except Exception as e:
            logger.error(f"Group allowed quiz IDs sozlashda xatolik: {e}", exc_info=True)
            db.rollback()
        finally:
            db.close()
    
    def add_group_allowed_quiz(self, chat_id: int, quiz_id: str) -> bool:
        """Guruh uchun quiz ruxsati qo'shish"""
        db = self._get_session()
        try:
            existing = db.query(GroupQuizAllowlist).filter(
                GroupQuizAllowlist.chat_id == chat_id,
                GroupQuizAllowlist.quiz_id == quiz_id
            ).first()
            
            if not existing:
                allowlist = GroupQuizAllowlist(
                    chat_id=chat_id,
                    quiz_id=quiz_id
                )
                db.add(allowlist)
                db.commit()
                return True
            return False  # Allaqachon mavjud
        except Exception as e:
            logger.error(f"Group allowed quiz qo'shishda xatolik: {e}", exc_info=True)
            db.rollback()
            return False
        finally:
            db.close()
    
    def remove_group_allowed_quiz(self, chat_id: int, quiz_id: str) -> bool:
        """Guruh uchun quiz ruxsatini olib tashlash"""
        db = self._get_session()
        try:
            allowlist = db.query(GroupQuizAllowlist).filter(
                GroupQuizAllowlist.chat_id == chat_id,
                GroupQuizAllowlist.quiz_id == quiz_id
            ).first()
            
            if allowlist:
                db.delete(allowlist)
                db.commit()
                return True
            return False
        except Exception as e:
            logger.error(f"Group allowed quiz o'chirishda xatolik: {e}", exc_info=True)
            db.rollback()
            return False
        finally:
            db.close()
    
    def group_allows_quiz(self, chat_id: int, quiz_id: str) -> bool:
        """Guruhda quiz ruxsat berilganmi tekshirish"""
        db = self._get_session()
        try:
            allowed = db.query(GroupQuizAllowlist).filter(
                GroupQuizAllowlist.chat_id == chat_id,
                GroupQuizAllowlist.quiz_id == quiz_id
            ).first()
            
            # Agar allowlist bo'sh bo'lsa, barcha quizlar ruxsat berilgan
            all_allowed = db.query(GroupQuizAllowlist).filter(
                GroupQuizAllowlist.chat_id == chat_id
            ).count()
            
            if all_allowed == 0:
                return True  # Hech qanday cheklov yo'q
            
            return allowed is not None
        except Exception as e:
            logger.error(f"Group allows quiz tekshirishda xatolik: {e}", exc_info=True)
            return True  # Default: ruxsat berilgan
        finally:
            db.close()
    
    # ===== Quiz Results =====
    
    def save_result(self, quiz_id: str, user_id: int, chat_id: int, answers: Dict, correct_count: int, 
                   total_count: int, answer_times: Dict = None):
        """Quiz natijasini saqlash"""
        db = self._get_session()
        try:
            percentage = (correct_count / total_count * 100) if total_count > 0 else 0
            
            # Vaqt statistikasini hisoblash
            total_time = 0.0
            avg_time = 0.0
            min_time = None
            max_time = None
            
            if answer_times:
                times_list = [t for t in answer_times.values() if t is not None]
                if times_list:
                    total_time = sum(times_list)
                    avg_time = total_time / len(times_list)
                    min_time = min(times_list)
                    max_time = max(times_list)
            
            result = QuizResult(
                quiz_id=quiz_id,
                user_id=user_id,
                chat_id=chat_id,
                answers=answers,
                correct_count=correct_count,
                total_count=total_count,
                percentage=percentage,
                answer_times=answer_times or {},
                total_time=total_time,
                avg_time=avg_time,
                min_time=min_time,
                max_time=max_time
            )
            
            db.add(result)
            db.commit()
        except Exception as e:
            logger.error(f"Result saqlashda xatolik: {e}", exc_info=True)
            db.rollback()
        finally:
            db.close()
    
    def get_user_results(self, user_id: int, limit: int = 20) -> List[Dict]:
        """Foydalanuvchining oxirgi natijalari"""
        db = self._get_session()
        try:
            results = db.query(QuizResult).filter(
                QuizResult.user_id == user_id
            ).order_by(desc(QuizResult.completed_at)).limit(limit).all()
            
            return [
                {
                    'quiz_id': r.quiz_id,
                    'user_id': r.user_id,
                    'chat_id': r.chat_id,
                    'answers': r.answers,
                    'correct_count': r.correct_count,
                    'total_count': r.total_count,
                    'percentage': r.percentage,
                    'answer_times': r.answer_times,
                    'total_time': r.total_time,
                    'avg_time': r.avg_time,
                    'min_time': r.min_time,
                    'max_time': r.max_time,
                    'completed_at': r.completed_at.isoformat() if r.completed_at else None
                }
                for r in results
            ]
        except Exception as e:
            logger.error(f"User results olishda xatolik: {e}", exc_info=True)
            return []
        finally:
            db.close()
    
    def get_user_results_in_group(self, user_id: int, chat_id: int, limit: int = 20) -> List[Dict]:
        """Foydalanuvchining guruhdagi natijalari"""
        db = self._get_session()
        try:
            results = db.query(QuizResult).filter(
                and_(QuizResult.user_id == user_id, QuizResult.chat_id == chat_id)
            ).order_by(desc(QuizResult.completed_at)).limit(limit).all()
            
            return [
                {
                    'quiz_id': r.quiz_id,
                    'user_id': r.user_id,
                    'chat_id': r.chat_id,
                    'answers': r.answers,
                    'correct_count': r.correct_count,
                    'total_count': r.total_count,
                    'percentage': r.percentage,
                    'answer_times': r.answer_times,
                    'total_time': r.total_time,
                    'avg_time': r.avg_time,
                    'min_time': r.min_time,
                    'max_time': r.max_time,
                    'completed_at': r.completed_at.isoformat() if r.completed_at else None
                }
                for r in results
            ]
        except Exception as e:
            logger.error(f"User results in group olishda xatolik: {e}", exc_info=True)
            return []
        finally:
            db.close()
    
    def get_top_results(self, chat_id: int, limit: int = 10) -> List[Dict]:
        """Top natijalarni olish"""
        db = self._get_session()
        try:
            results = db.query(QuizResult).filter(
                QuizResult.chat_id == chat_id
            ).order_by(desc(QuizResult.percentage), desc(QuizResult.correct_count)).limit(limit).all()
            
            return [
                {
                    'quiz_id': r.quiz_id,
                    'user_id': r.user_id,
                    'chat_id': r.chat_id,
                    'answers': r.answers,
                    'correct_count': r.correct_count,
                    'total_count': r.total_count,
                    'percentage': r.percentage,
                    'completed_at': r.completed_at.isoformat() if r.completed_at else None
                }
                for r in results
            ]
        except Exception as e:
            logger.error(f"Top results olishda xatolik: {e}", exc_info=True)
            return []
        finally:
            db.close()
    
    def get_all_group_results(self, chat_id: int) -> List[Dict]:
        """Guruhdagi barcha natijalarni olish"""
        db = self._get_session()
        try:
            results = db.query(QuizResult).filter(
                QuizResult.chat_id == chat_id
            ).all()
            
            return [
                {
                    'quiz_id': r.quiz_id,
                    'user_id': r.user_id,
                    'chat_id': r.chat_id,
                    'answers': r.answers,
                    'correct_count': r.correct_count,
                    'total_count': r.total_count,
                    'percentage': r.percentage,
                    'completed_at': r.completed_at.isoformat() if r.completed_at else None
                }
                for r in results
            ]
        except Exception as e:
            logger.error(f"All group results olishda xatolik: {e}", exc_info=True)
            return []
        finally:
            db.close()
    
    def get_results_count(self) -> int:
        """Natijalar soni"""
        db = self._get_session()
        try:
            return db.query(QuizResult).count()
        except Exception as e:
            logger.error(f"Results count xatolik: {e}", exc_info=True)
            return 0
        finally:
            db.close()
    
    def get_quizzes_count(self) -> int:
        """Quizlar soni"""
        db = self._get_session()
        try:
            return db.query(Quiz).count()
        except Exception as e:
            logger.error(f"Quizzes count xatolik: {e}", exc_info=True)
            return 0
        finally:
            db.close()
    
    # ===== Sudo Users =====
    
    def add_sudo_user(self, user_id: int, username: str = None, first_name: str = None):
        """Sudo user qo'shish"""
        db = self._get_session()
        try:
            existing = db.query(SudoUser).filter(SudoUser.user_id == user_id).first()
            if not existing:
                sudo_user = SudoUser(
                    user_id=user_id,
                    username=username,
                    first_name=first_name
                )
                db.add(sudo_user)
                db.commit()
                return True
            return False
        except Exception as e:
            logger.error(f"Sudo user qo'shishda xatolik: {e}", exc_info=True)
            db.rollback()
            return False
        finally:
            db.close()
    
    def remove_sudo_user(self, user_id: int) -> bool:
        """Sudo user olib tashlash"""
        db = self._get_session()
        try:
            sudo_user = db.query(SudoUser).filter(SudoUser.user_id == user_id).first()
            if sudo_user:
                db.delete(sudo_user)
                db.commit()
                return True
            return False
        except Exception as e:
            logger.error(f"Sudo user o'chirishda xatolik: {e}", exc_info=True)
            db.rollback()
            return False
        finally:
            db.close()
    
    def get_sudo_users(self) -> List[Dict]:
        """Sudo users ro'yxati"""
        db = self._get_session()
        try:
            sudo_users = db.query(SudoUser).order_by(desc(SudoUser.added_at)).all()
            return [
                {
                    'user_id': u.user_id,
                    'username': u.username,
                    'first_name': u.first_name,
                    'added_at': u.added_at.isoformat() if u.added_at else None
                }
                for u in sudo_users
            ]
        except Exception as e:
            logger.error(f"Sudo users olishda xatolik: {e}", exc_info=True)
            return []
        finally:
            db.close()
    
    def is_sudo_user(self, user_id: int) -> bool:
        """Sudo user tekshiruvi"""
        db = self._get_session()
        try:
            sudo_user = db.query(SudoUser).filter(SudoUser.user_id == user_id).first()
            return sudo_user is not None
        except Exception as e:
            logger.error(f"Sudo user tekshirishda xatolik: {e}", exc_info=True)
            return False
        finally:
            db.close()
    
    # ===== VIP Users =====
    
    def add_vip_user(self, user_id: int, username: str = None, first_name: str = None, nickname: str = None):
        """VIP user qo'shish"""
        db = self._get_session()
        try:
            existing = db.query(VipUser).filter(VipUser.user_id == user_id).first()
            if existing:
                existing.username = username
                existing.first_name = first_name
                existing.nickname = nickname
            else:
                vip_user = VipUser(
                    user_id=user_id,
                    username=username,
                    first_name=first_name,
                    nickname=nickname or first_name or 'VIP User'
                )
                db.add(vip_user)
            db.commit()
            return True
        except Exception as e:
            logger.error(f"VIP user qo'shishda xatolik: {e}", exc_info=True)
            db.rollback()
            return False
        finally:
            db.close()
    
    def remove_vip_user(self, user_id: int) -> bool:
        """VIP user olib tashlash"""
        db = self._get_session()
        try:
            vip_user = db.query(VipUser).filter(VipUser.user_id == user_id).first()
            if vip_user:
                db.delete(vip_user)
                db.commit()
                return True
            return False
        except Exception as e:
            logger.error(f"VIP user o'chirishda xatolik: {e}", exc_info=True)
            db.rollback()
            return False
        finally:
            db.close()
    
    def get_vip_users(self) -> List[Dict]:
        """VIP users ro'yxati"""
        db = self._get_session()
        try:
            vip_users = db.query(VipUser).order_by(desc(VipUser.added_at)).all()
            return [
                {
                    'user_id': u.user_id,
                    'username': u.username,
                    'first_name': u.first_name,
                    'nickname': u.nickname,
                    'added_at': u.added_at.isoformat() if u.added_at else None
                }
                for u in vip_users
            ]
        except Exception as e:
            logger.error(f"VIP users olishda xatolik: {e}", exc_info=True)
            return []
        finally:
            db.close()
    
    def is_vip_user(self, user_id: int) -> bool:
        """VIP user tekshiruvi"""
        db = self._get_session()
        try:
            vip_user = db.query(VipUser).filter(VipUser.user_id == user_id).first()
            return vip_user is not None
        except Exception as e:
            logger.error(f"VIP user tekshirishda xatolik: {e}", exc_info=True)
            return False
        finally:
            db.close()
    
    def get_vip_user(self, user_id: int) -> Optional[Dict]:
        """VIP user ma'lumotlarini olish"""
        db = self._get_session()
        try:
            vip_user = db.query(VipUser).filter(VipUser.user_id == user_id).first()
            if vip_user:
                return {
                    'user_id': vip_user.user_id,
                    'username': vip_user.username,
                    'first_name': vip_user.first_name,
                    'nickname': vip_user.nickname,
                    'added_at': vip_user.added_at.isoformat() if vip_user.added_at else None
                }
            return None
        except Exception as e:
            logger.error(f"VIP user olishda xatolik: {e}", exc_info=True)
            return None
        finally:
            db.close()
    
    # ===== Premium Users =====
    
    def add_premium_user(self, user_id: int, stars_amount: int, months: int = 1, username: str = None, first_name: str = None, subscription_plan: str = 'pro'):
        """Premium user qo'shish yoki yangilash
        
        Args:
            subscription_plan: 'free', 'core', 'pro'
        """
        db = self._get_session()
        try:
            existing = db.query(PremiumUser).filter(PremiumUser.user_id == user_id).first()
            
            # Premium muddati (free tarif uchun None)
            if subscription_plan == 'free':
                new_until = None
            else:
                if existing and existing.premium_until and existing.premium_until > datetime.utcnow():
                    # Premium hali davom etmoqda, muddatni uzaytiramiz
                    new_until = existing.premium_until + timedelta(days=30 * months)
                else:
                    # Yangi premium yoki muddati tugagan
                    new_until = datetime.utcnow() + timedelta(days=30 * months)
            
            if existing:
                existing.username = username
                existing.first_name = first_name
                existing.subscription_plan = subscription_plan
                existing.premium_until = new_until
                existing.stars_paid = stars_amount
                existing.months = months
                existing.last_updated = datetime.utcnow()
            else:
                premium_user = PremiumUser(
                    user_id=user_id,
                    username=username,
                    first_name=first_name,
                    subscription_plan=subscription_plan,
                    premium_until=new_until,
                    stars_paid=stars_amount,
                    months=months
                )
                db.add(premium_user)
            
            # Payment tarixini saqlash
            payment = PremiumPayment(
                user_id=user_id,
                stars_amount=stars_amount,
                months=months,
                premium_until=new_until
            )
            db.add(payment)
            
            db.commit()
            return True
        except Exception as e:
            logger.error(f"Premium user qo'shishda xatolik: {e}", exc_info=True)
            db.rollback()
            return False
        finally:
            db.close()
    
    def is_premium_user(self, user_id: int) -> bool:
        """Premium user tekshiruvi (Core yoki Pro tarif)"""
        db = self._get_session()
        try:
            premium_user = db.query(PremiumUser).filter(PremiumUser.user_id == user_id).first()
            if premium_user:
                # Free tarif emas va muddati tugamagan
                if premium_user.subscription_plan == 'free':
                    return False
                if premium_user.premium_until:
                    return premium_user.premium_until > datetime.utcnow()
            return False
        except Exception as e:
            logger.error(f"Premium user tekshirishda xatolik: {e}", exc_info=True)
            return False
        finally:
            db.close()
    
    def get_premium_user(self, user_id: int) -> Optional[Dict]:
        """Premium user ma'lumotlarini olish"""
        db = self._get_session()
        try:
            premium_user = db.query(PremiumUser).filter(PremiumUser.user_id == user_id).first()
            if premium_user:
                # Free tarif bo'lsa ham ma'lumotlarni qaytarish
                if premium_user.subscription_plan == 'free':
                    return {
                        'user_id': premium_user.user_id,
                        'username': premium_user.username,
                        'first_name': premium_user.first_name,
                        'subscription_plan': premium_user.subscription_plan,
                        'premium_until': None,
                        'stars_paid': premium_user.stars_paid,
                        'months': premium_user.months,
                        'activated_at': premium_user.activated_at.isoformat() if premium_user.activated_at else None
                    }
                # Core yoki Pro tarif - muddati tekshirish
                if premium_user.premium_until and premium_user.premium_until > datetime.utcnow():
                    return {
                        'user_id': premium_user.user_id,
                        'username': premium_user.username,
                        'first_name': premium_user.first_name,
                        'subscription_plan': premium_user.subscription_plan,
                        'premium_until': premium_user.premium_until.isoformat(),
                        'stars_paid': premium_user.stars_paid,
                        'months': premium_user.months,
                        'activated_at': premium_user.activated_at.isoformat() if premium_user.activated_at else None
                    }
            return None
        except Exception as e:
            logger.error(f"Premium user olishda xatolik: {e}", exc_info=True)
            return None
        finally:
            db.close()
    
    def get_premium_users_count(self) -> int:
        """Faol premium userlar soni"""
        db = self._get_session()
        try:
            now = datetime.utcnow()
            return db.query(PremiumUser).filter(PremiumUser.premium_until > now).count()
        except Exception as e:
            logger.error(f"Premium users count xatolik: {e}", exc_info=True)
            return 0
        finally:
            db.close()
    
    def get_user_quizzes_count_this_month(self, user_id: int) -> int:
        """Foydalanuvchining shu oyda yaratgan quizlari soni"""
        db = self._get_session()
        try:
            now = datetime.utcnow()
            month_start = datetime(now.year, now.month, 1)
            
            return db.query(Quiz).filter(
                and_(
                    Quiz.created_by == user_id,
                    Quiz.created_at >= month_start
                )
            ).count()
        except Exception as e:
            logger.error(f"User quizzes count this month xatolik: {e}", exc_info=True)
            return 0
        finally:
            db.close()
    
    # ===== Required Channels =====
    
    def get_required_channels(self) -> List[Dict]:
        """Majburiy obuna kanallari ro'yxati"""
        db = self._get_session()
        try:
            channels = db.query(RequiredChannel).all()
            return [
                {
                    'channel_id': ch.channel_id,
                    'channel_username': ch.channel_username,
                    'channel_title': ch.channel_title,
                    'added_at': ch.added_at.isoformat() if ch.added_at else None
                }
                for ch in channels
            ]
        except Exception as e:
            logger.error(f"Required channels olishda xatolik: {e}", exc_info=True)
            return []
        finally:
            db.close()
    
    def add_required_channel(self, channel_id: int, channel_username: str = None, channel_title: str = None) -> bool:
        """Majburiy obuna kanalini qo'shish"""
        db = self._get_session()
        try:
            existing = db.query(RequiredChannel).filter(RequiredChannel.channel_id == channel_id).first()
            if existing:
                existing.channel_username = channel_username
                existing.channel_title = channel_title
            else:
                channel = RequiredChannel(
                    channel_id=channel_id,
                    channel_username=channel_username,
                    channel_title=channel_title
                )
                db.add(channel)
            db.commit()
            return True
        except Exception as e:
            logger.error(f"Required channel qo'shishda xatolik: {e}", exc_info=True)
            db.rollback()
            return False
        finally:
            db.close()
    
    def remove_required_channel(self, channel_id: int) -> bool:
        """Majburiy obuna kanalini olib tashlash"""
        db = self._get_session()
        try:
            channel = db.query(RequiredChannel).filter(RequiredChannel.channel_id == channel_id).first()
            if channel:
                db.delete(channel)
                db.commit()
                return True
            return False
        except Exception as e:
            logger.error(f"Required channel o'chirishda xatolik: {e}", exc_info=True)
            db.rollback()
            return False
        finally:
            db.close()
