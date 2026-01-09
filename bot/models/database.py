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
# Use NullPool for async operations with telegram-bot
engine = create_engine(
    DATABASE_URL,
    poolclass=NullPool,  # Important for async operations
    pool_pre_ping=True,  # Check connections before using
    echo=os.getenv('DB_ECHO', 'False').lower() == 'true'  # Log SQL queries in debug mode
)

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