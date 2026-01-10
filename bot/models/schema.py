"""Database models (SQLAlchemy ORM)"""
from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, JSON, Float, Text, Index, BigInteger
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid

from bot.models.database import Base


class User(Base):
    """Foydalanuvchilar jadvali"""
    __tablename__ = 'users'
    
    user_id = Column(BigInteger, primary_key=True, unique=True, nullable=False)
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    last_chat_id = Column(BigInteger, nullable=True)
    last_chat_type = Column(String(50), nullable=True)
    last_seen = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    quizzes = relationship("Quiz", back_populates="creator", cascade="all, delete-orphan")
    results = relationship("QuizResult", back_populates="user", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<User(user_id={self.user_id}, username={self.username})>"


class Group(Base):
    """Guruhlar/superguruhlar jadvali"""
    __tablename__ = 'groups'
    
    chat_id = Column(BigInteger, primary_key=True, unique=True, nullable=False)
    title = Column(String(255), nullable=True)
    chat_type = Column(String(50), nullable=True)  # 'group' or 'supergroup'
    bot_status = Column(String(50), nullable=True)  # 'member', 'administrator', 'left', etc.
    bot_is_admin = Column(Boolean, default=False)
    last_seen = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    allowed_quizzes = relationship("GroupQuizAllowlist", back_populates="group", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Group(chat_id={self.chat_id}, title={self.title})>"


class Quiz(Base):
    """Quizlar jadvali"""
    __tablename__ = 'quizzes'
    
    quiz_id = Column(String(50), primary_key=True, unique=True, nullable=False)
    title = Column(String(500), nullable=True)
    created_by = Column(BigInteger, ForeignKey('users.user_id'), nullable=False)
    created_in_chat = Column(BigInteger, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    is_private = Column(Boolean, default=False, nullable=False)
    
    # Relationships
    creator = relationship("User", back_populates="quizzes")
    questions = relationship("Question", back_populates="quiz", cascade="all, delete-orphan", order_by="Question.question_index")
    results = relationship("QuizResult", back_populates="quiz", cascade="all, delete-orphan")
    allowed_groups = relationship("QuizAllowedGroup", back_populates="quiz", cascade="all, delete-orphan")
    
    # Indexes
    __table_args__ = (
        Index('idx_quiz_created_by', 'created_by'),
        Index('idx_quiz_created_at', 'created_at'),
    )
    
    def __repr__(self):
        return f"<Quiz(quiz_id={self.quiz_id}, title={self.title})>"


class Question(Base):
    """Savollar jadvali"""
    __tablename__ = 'questions'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    quiz_id = Column(String(50), ForeignKey('quizzes.quiz_id', ondelete='CASCADE'), nullable=False)
    question_index = Column(Integer, nullable=False)  # 0, 1, 2, ...
    question_text = Column(Text, nullable=False)
    options = Column(JSON, nullable=False)  # List of strings: ["option1", "option2", ...]
    correct_answer = Column(Integer, nullable=True)  # Index of correct option (0-based), None bo'lsa oddiy poll
    explanation = Column(Text, nullable=True)
    
    # Relationships
    quiz = relationship("Quiz", back_populates="questions")
    
    # Indexes
    __table_args__ = (
        Index('idx_question_quiz_id', 'quiz_id'),
        Index('idx_question_quiz_index', 'quiz_id', 'question_index'),
    )
    
    def __repr__(self):
        return f"<Question(id={self.id}, quiz_id={self.quiz_id}, index={self.question_index})>"


class QuizResult(Base):
    """Quiz natijalari jadvali"""
    __tablename__ = 'quiz_results'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    quiz_id = Column(String(50), ForeignKey('quizzes.quiz_id', ondelete='CASCADE'), nullable=False)
    user_id = Column(BigInteger, ForeignKey('users.user_id'), nullable=False)
    chat_id = Column(BigInteger, nullable=False)
    answers = Column(JSON, nullable=False)  # {question_index: selected_answer_index}
    correct_count = Column(Integer, nullable=False)
    total_count = Column(Integer, nullable=False)
    percentage = Column(Float, nullable=False)
    answer_times = Column(JSON, nullable=True)  # {question_index: time_in_seconds}
    total_time = Column(Float, nullable=True)
    avg_time = Column(Float, nullable=True)
    min_time = Column(Float, nullable=True)
    max_time = Column(Float, nullable=True)
    completed_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    quiz = relationship("Quiz", back_populates="results")
    user = relationship("User", back_populates="results")
    
    # Indexes
    __table_args__ = (
        Index('idx_result_quiz_id', 'quiz_id'),
        Index('idx_result_user_id', 'user_id'),
        Index('idx_result_chat_id', 'chat_id'),
        Index('idx_result_completed_at', 'completed_at'),
        Index('idx_result_user_quiz', 'user_id', 'quiz_id'),
    )
    
    def __repr__(self):
        return f"<QuizResult(id={self.id}, quiz_id={self.quiz_id}, user_id={self.user_id}, percentage={self.percentage})>"


class GroupQuizAllowlist(Base):
    """Guruh uchun ruxsat berilgan quizlar"""
    __tablename__ = 'group_quiz_allowlist'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(BigInteger, ForeignKey('groups.chat_id', ondelete='CASCADE'), nullable=False)
    quiz_id = Column(String(50), nullable=False)
    added_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    group = relationship("Group", back_populates="allowed_quizzes")
    
    # Indexes - ensure uniqueness
    __table_args__ = (
        Index('idx_allowlist_chat_quiz', 'chat_id', 'quiz_id', unique=True),
    )
    
    def __repr__(self):
        return f"<GroupQuizAllowlist(chat_id={self.chat_id}, quiz_id={self.quiz_id})>"


class QuizAllowedGroup(Base):
    """Private quiz uchun ruxsat berilgan guruhlar"""
    __tablename__ = 'quiz_allowed_groups'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    quiz_id = Column(String(50), ForeignKey('quizzes.quiz_id', ondelete='CASCADE'), nullable=False)
    group_id = Column(BigInteger, nullable=False)
    added_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    quiz = relationship("Quiz", back_populates="allowed_groups")
    
    # Indexes - ensure uniqueness
    __table_args__ = (
        Index('idx_allowed_group_quiz_group', 'quiz_id', 'group_id', unique=True),
    )
    
    def __repr__(self):
        return f"<QuizAllowedGroup(quiz_id={self.quiz_id}, group_id={self.group_id})>"


class SudoUser(Base):
    """Sudo foydalanuvchilar"""
    __tablename__ = 'sudo_users'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, unique=True, nullable=False)
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    added_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    def __repr__(self):
        return f"<SudoUser(user_id={self.user_id})>"


class VipUser(Base):
    """VIP foydalanuvchilar"""
    __tablename__ = 'vip_users'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, unique=True, nullable=False)
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    nickname = Column(String(255), nullable=True)
    added_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    def __repr__(self):
        return f"<VipUser(user_id={self.user_id}, nickname={self.nickname})>"


class PremiumUser(Base):
    """Premium foydalanuvchilar (tariflar: Free, Core, Pro)"""
    __tablename__ = 'premium_users'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, unique=True, nullable=False)
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    subscription_plan = Column(String(20), nullable=False, default='free')  # 'free', 'core', 'pro'
    premium_until = Column(DateTime, nullable=True)  # None bo'lishi mumkin (free tarif uchun)
    stars_paid = Column(Integer, nullable=False, default=0)
    months = Column(Integer, nullable=False, default=1)
    activated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Indexes
    __table_args__ = (
        Index('idx_premium_user_id', 'user_id'),
        Index('idx_premium_until', 'premium_until'),
    )
    
    def __repr__(self):
        return f"<PremiumUser(user_id={self.user_id}, premium_until={self.premium_until})>"


class PremiumPayment(Base):
    """Premium to'lovlar tarixi"""
    __tablename__ = 'premium_payments'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False)
    stars_amount = Column(Integer, nullable=False)
    months = Column(Integer, nullable=False)
    premium_until = Column(DateTime, nullable=False)
    paid_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Indexes
    __table_args__ = (
        Index('idx_payment_user_id', 'user_id'),
        Index('idx_payment_paid_at', 'paid_at'),
    )
    
    def __repr__(self):
        return f"<PremiumPayment(id={self.id}, user_id={self.user_id}, stars={self.stars_amount})>"


class RequiredChannel(Base):
    """Majburiy obuna kanallari"""
    __tablename__ = 'required_channels'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(BigInteger, unique=True, nullable=False)
    channel_username = Column(String(255), nullable=True)
    channel_title = Column(String(255), nullable=True)
    added_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    def __repr__(self):
        return f"<RequiredChannel(channel_id={self.channel_id}, username={self.channel_username})>"