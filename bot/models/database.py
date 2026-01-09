"""Database configuration and session management"""
import os
from sqlalchemy import create_engine, MetaData
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import NullPool
from typing import Generator
import logging

logger = logging.getLogger(__name__)

# Database URL - to'g'ridan-to'g'ri environment dan olish (circular import muammosini oldini olish uchun)
DATABASE_URL = os.getenv(
    'DATABASE_URL',
    f"postgresql://{os.getenv('DB_USER', 'quizbot')}:{os.getenv('DB_PASSWORD', 'quizbot123')}@"
    f"{os.getenv('DB_HOST', 'localhost')}:{os.getenv('DB_PORT', '5432')}/{os.getenv('DB_NAME', 'quizbot')}"
)

# Create engine
# Connection pool sozlamalari - concurrent requestlar uchun optimizatsiya
USE_POOL = os.getenv('DB_USE_POOL', '1').strip() in ['1', 'true', 'True']
POOL_SIZE = int(os.getenv('DB_POOL_SIZE', '10'))  # Default: 10 connection
MAX_OVERFLOW = int(os.getenv('DB_MAX_OVERFLOW', '20'))  # Default: 20 additional connections

if USE_POOL:
    # Connection pool bilan - concurrent requestlar uchun yaxshi
    from sqlalchemy.pool import QueuePool
    engine = create_engine(
        DATABASE_URL,
        poolclass=QueuePool,
        pool_size=POOL_SIZE,
        max_overflow=MAX_OVERFLOW,
        pool_pre_ping=True,  # Check connections before using
        pool_recycle=3600,  # 1 soatdan keyin connectionlarni yangilash
        echo=os.getenv('DB_ECHO', 'False').lower() == 'true'
    )
    logger.info(f"✅ Database connection pool ishlatilmoqda (pool_size={POOL_SIZE}, max_overflow={MAX_OVERFLOW})")
else:
    # NullPool - eski rejim (backward compatibility)
    engine = create_engine(
        DATABASE_URL,
        poolclass=NullPool,
        pool_pre_ping=True,
        echo=os.getenv('DB_ECHO', 'False').lower() == 'true'
    )
    logger.info("ℹ️ Database NullPool ishlatilmoqda (connection pool o'chirilgan)")

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()

# Metadata
metadata = MetaData()


def get_db() -> Generator[Session, None, None]:
    """Database session dependency for FastAPI-style dependency injection"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Initialize database - create all tables"""
    logger.info("Initializing database tables...")
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created successfully")


def drop_db():
    """Drop all database tables (USE WITH CAUTION!)"""
    logger.warning("Dropping all database tables...")
    Base.metadata.drop_all(bind=engine)
    logger.warning("All database tables dropped")