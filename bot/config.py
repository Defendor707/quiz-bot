"""Bot sozlamalari va environment variables"""
import os
from typing import Optional


class Config:
    """Bot konfiguratsiyasi"""
    
    # ==================== BOT TOKENS ====================
    BOT_TOKEN: str = os.getenv('BOT_TOKEN', '')
    DEEPSEEK_API_KEY: str = os.getenv('DEEPSEEK_API_KEY', '')
    DEEPSEEK_API_URL: str = 'https://api.deepseek.com/v1/chat/completions'
    
    # ==================== AI MODELS ====================
    DEEPSEEK_MODEL_PRIMARY: str = os.getenv('DEEPSEEK_MODEL_PRIMARY', 'deepseek-chat')
    DEEPSEEK_MODEL_FALLBACK: str = os.getenv('DEEPSEEK_MODEL_FALLBACK', 'deepseek-reasoner')
    
    # ==================== SAFETY / LIMITS ====================
    MAX_ACTIVE_QUIZZES_PER_GROUP: int = int(os.getenv('MAX_ACTIVE_QUIZZES_PER_GROUP', '2'))
    MAX_ACTIVE_QUIZZES_PER_USER_IN_GROUP: int = int(os.getenv('MAX_ACTIVE_QUIZZES_PER_USER_IN_GROUP', '1'))
    MAX_ACTIVE_QUIZZES_PER_USER_PRIVATE: int = int(os.getenv('MAX_ACTIVE_QUIZZES_PER_USER_PRIVATE', '3'))  # Shaxsiy chatda limit
    
    # ==================== FILE VALIDATION / LIMITS ====================
    MIN_QUESTIONS_REQUIRED: int = int(os.getenv('MIN_QUESTIONS_REQUIRED', '2'))
    MAX_QUESTIONS_PER_QUIZ: int = int(os.getenv('MAX_QUESTIONS_PER_QUIZ', '100'))
    TARGET_QUESTIONS_PER_QUIZ: int = int(os.getenv('TARGET_QUESTIONS_PER_QUIZ', '50'))
    MAX_TEXT_CHARS_FOR_AI: int = int(os.getenv('MAX_TEXT_CHARS_FOR_AI', '35000'))
    REQUIRE_CORRECT_ANSWER: bool = os.getenv('REQUIRE_CORRECT_ANSWER', '1').strip() not in ['0', 'false', 'False']
    
    # ==================== AI TIMEOUTS ====================
    MAX_AI_SECONDS: int = int(os.getenv('MAX_AI_SECONDS', '180'))
    MAX_CONCURRENT_AI_REQUESTS: int = int(os.getenv('MAX_CONCURRENT_AI_REQUESTS', '2'))
    
    # ==================== ANSWER KEY ====================
    ANSWER_KEY_TAIL_CHARS: int = int(os.getenv('ANSWER_KEY_TAIL_CHARS', '12000'))
    ANSWER_KEY_OVERRIDE: bool = os.getenv('ANSWER_KEY_OVERRIDE', '1').strip() not in ['0', 'false', 'False']
    
    # ==================== ADMIN ====================
    ADMIN_USER_IDS: set[int] = set()
    
    @classmethod
    def load_admin_ids(cls):
        """Admin user ID larni yuklash"""
        raw = os.getenv('ADMIN_USER_IDS', '')
        if not raw:
            return
        for part in raw.split(','):
            part = part.strip()
            if part:
                try:
                    cls.ADMIN_USER_IDS.add(int(part))
                except ValueError:
                    pass
    
    @classmethod
    def is_admin(cls, user_id: int) -> bool:
        """User admin ekanligini tekshirish"""
        return user_id in cls.ADMIN_USER_IDS
    
    @classmethod
    def get_env(cls, key: str, default: str = '') -> str:
        """Environment variable olish (backward compatibility)"""
        return os.getenv(key, default)
    
    # ==================== PAGINATION ====================
    QUIZZES_PER_PAGE: int = 10
    
    # ==================== TIME OPTIONS ====================
    TIME_OPTIONS = {
        '10s': 10,
        '30s': 30,
        '1min': 60,
        '3min': 180,
        '5min': 300
    }
    
    # ==================== VOTING SETTINGS ====================
    VOTING_ENABLED: bool = os.getenv('VOTING_ENABLED', '1').strip() in ['1', 'true', 'True']
    VOTING_MIN_VOTES_TO_START: int = int(os.getenv('VOTING_MIN_VOTES_TO_START', '2'))  # Minimum ovozlar quizni boshlash uchun
    VOTING_MIN_VOTES_TO_STOP: int = int(os.getenv('VOTING_MIN_VOTES_TO_STOP', '3'))  # Minimum ovozlar quizni to'xtatish uchun
    VOTING_TIMEOUT_SECONDS: int = int(os.getenv('VOTING_TIMEOUT_SECONDS', '60'))  # Voting poll muddati
    
    # ==================== WEBHOOK SETTINGS ====================
    WEBHOOK_URL: str = os.getenv('WEBHOOK_URL', '')
    WEBHOOK_PORT: int = int(os.getenv('WEBHOOK_PORT', '8443'))
    WEBHOOK_PATH: str = os.getenv('WEBHOOK_PATH', '/webhook')
    WEBHOOK_LISTEN: str = os.getenv('WEBHOOK_LISTEN', '0.0.0.0')
    WEBHOOK_SECRET_TOKEN: str = os.getenv('WEBHOOK_SECRET_TOKEN', '')
    USE_WEBHOOK: bool = os.getenv('USE_WEBHOOK', '0').strip() in ['1', 'true', 'True']
    WEBHOOK_CERT_PATH: str = os.getenv('WEBHOOK_CERT_PATH', '/etc/nginx/ssl/telegram_bot.crt')
    WEBHOOK_KEY_PATH: str = os.getenv('WEBHOOK_KEY_PATH', '/etc/nginx/ssl/telegram_bot.key')
    
    # ==================== DATABASE SETTINGS ====================
    USE_DATABASE: bool = os.getenv('USE_DATABASE', '1').strip() in ['1', 'true', 'True']  # Default: Database ishlatish
    DATABASE_URL: str = os.getenv(
        'DATABASE_URL',
        f"postgresql://{os.getenv('DB_USER', 'quizbot')}:{os.getenv('DB_PASSWORD', 'quizbot123')}@"
        f"{os.getenv('DB_HOST', 'localhost')}:{os.getenv('DB_PORT', '5432')}/{os.getenv('DB_NAME', 'quizbot')}"
    )
    DB_ECHO: bool = os.getenv('DB_ECHO', 'False').lower() == 'true'  # SQL query logging
    # Connection pool (concurrent requestlar uchun)
    DB_USE_POOL: bool = os.getenv('DB_USE_POOL', '1').strip() in ['1', 'true', 'True']  # Default: Pool ishlatish
    DB_POOL_SIZE: int = int(os.getenv('DB_POOL_SIZE', '10'))  # Default: 10 connection
    DB_MAX_OVERFLOW: int = int(os.getenv('DB_MAX_OVERFLOW', '20'))  # Default: 20 additional connections
    
    # ==================== EMAIL SETTINGS (Gmail) ====================
    GMAIL_SMTP_SERVER: str = os.getenv('GMAIL_SMTP_SERVER', 'smtp.gmail.com')
    GMAIL_SMTP_PORT: int = int(os.getenv('GMAIL_SMTP_PORT', '587'))
    GMAIL_SENDER_EMAIL: str = os.getenv('GMAIL_SENDER_EMAIL', '')
    GMAIL_SENDER_PASSWORD: str = os.getenv('GMAIL_SENDER_PASSWORD', '')  # App Password yoki o'rniga OAuth token
    GMAIL_RECIPIENT_EMAIL: str = os.getenv('GMAIL_RECIPIENT_EMAIL', '')
    # Status report yuborish intervali (sekundlarda, default: 24 soat = 86400)
    STATUS_REPORT_INTERVAL: int = int(os.getenv('STATUS_REPORT_INTERVAL', '86400'))
    # Status report yoqish/o'chirish
    STATUS_REPORT_ENABLED: bool = os.getenv('STATUS_REPORT_ENABLED', '0').strip() in ['1', 'true', 'True']
    
    # ==================== ENVIRONMENT ====================
    ENVIRONMENT: str = os.getenv('ENVIRONMENT', 'development').lower()  # development, production, staging
    LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO').upper()  # DEBUG, INFO, WARNING, ERROR
    
    @classmethod
    def validate_production(cls):
        """Production uchun kerakli sozlamalarni tekshirish"""
        import logging
        logger = logging.getLogger(__name__)
        errors = []
        warnings = []
        
        # Critical checks
        if not cls.BOT_TOKEN:
            errors.append("❌ BOT_TOKEN topilmadi! Production uchun BOT_TOKEN kerak.")
        
        if not cls.DEEPSEEK_API_KEY:
            warnings.append("⚠️ DEEPSEEK_API_KEY topilmadi (AI funksiyalari ishlamaydi)")
        
        # Default parol tekshiruvi
        if 'quizbot123' in cls.DATABASE_URL:
            errors.append("❌ XAVFLI: Default database parol ('quizbot123') ishlatilmoqda! Production da kuchli parol ishlating!")
        
        # Production environment tekshiruvi
        if cls.ENVIRONMENT == 'production':
            if cls.DB_ECHO:
                warnings.append("⚠️ DB_ECHO=True production da tavsiya etilmaydi (performance muammosi)")
            
            if cls.LOG_LEVEL not in ['WARNING', 'ERROR']:
                warnings.append(f"⚠️ LOG_LEVEL={cls.LOG_LEVEL} production uchun WARNING yoki ERROR bo'lishi tavsiya etiladi")
            
            # Admin IDs tekshiruvi
            if not cls.ADMIN_USER_IDS:
                warnings.append("⚠️ ADMIN_USER_IDS bo'sh. Production da admin ID lar sozlanishi tavsiya etiladi.")
        
        # Errors ko'rsatish
        if errors:
            for error in errors:
                logger.error(error)
            if any('❌' in e for e in errors):
                raise ValueError("Production validation failed! Check errors above.")
        
        # Warnings ko'rsatish
        if warnings:
            for warning in warnings:
                logger.warning(warning)
        
        return len(errors) == 0


# Konfiguratsiyani yuklash
Config.load_admin_ids()

# Production validation (agar ENVIRONMENT=production bo'lsa)
if os.getenv('ENVIRONMENT', '').lower() == 'production':
    try:
        Config.validate_production()
    except ValueError as e:
        import sys
        print(f"❌ Production validation failed: {e}", file=sys.stderr)
        sys.exit(1)
