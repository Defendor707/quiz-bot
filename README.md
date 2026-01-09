# Quiz Bot - Professional Telegram Bot

Professional darajadagi Telegram Quiz Bot - PostgreSQL database bilan ishlaydi, AI orqali fayllardan quiz yaratadi.

## ✨ Xususiyatlar

- 🤖 **AI-powered** - DeepSeek AI orqali fayllardan quiz yaratish (PDF, DOCX, TXT)
- 💾 **PostgreSQL Database** - Professional database integratsiyasi
- 🐳 **Docker Support** - Docker Compose bilan oson deployment
- 📦 **Modullashtirilgan** - Clean architecture, maintainable kod
- 🔄 **Migration Tools** - JSON dan Database ga o'tish uchun
- ⚙️ **Flexible Storage** - Database yoki JSON (fallback)

## 📋 Talablar

- Python 3.10+
- PostgreSQL 14+ (yoki Docker)
- Docker & Docker Compose (tavsiya)

## 🚀 Tez Boshlash

### 1. Repository ni klonlash

```bash
git clone <repository-url>
cd quiz-bot
```

### 2. Environment sozlash

```bash
cp .env.example .env
# .env faylini tahrirlang va BOT_TOKEN, DEEPSEEK_API_KEY ni kiriting
```

### 3. Docker orqali ishga tushirish (Tavsiya)

```bash
# PostgreSQL va Bot ni birga ishga tushirish
docker-compose up -d

# Loglarni ko'rish
docker-compose logs -f bot
```

### 4. Yoki qo'lda o'rnatish

```bash
# Dependencies o'rnatish
pip install -r requirements.txt

# PostgreSQL sozlash (qo'lda)
# Database yaratish va migration
python3 migrations/migrate_json_to_db.py

# Botni ishga tushirish
python3 bot/main.py
```

## 📁 Loyiha Struktura

```
quiz-bot/
├── bot/                          # Asosiy bot kodi
│   ├── main.py                  # Entry point
│   ├── config.py                # Configuration
│   ├── handlers/                # Telegram handlers
│   │   ├── start.py            # /start, /help
│   │   ├── quiz.py             # Quiz CRUD operations
│   │   ├── admin.py            # Admin panel
│   │   └── premium.py          # Premium features
│   ├── services/                # Business logic
│   │   ├── ai_parser.py        # AI integration
│   │   ├── file_parser.py      # File parsing
│   │   └── quiz_service.py     # Quiz session management
│   ├── models/                  # Data models
│   │   ├── database.py         # Database config
│   │   ├── schema.py           # SQLAlchemy models
│   │   ├── storage.py          # JSON storage (fallback)
│   │   └── storage_db.py       # Database storage
│   └── utils/                   # Utilities
│       ├── validators.py       # Validation
│       └── helpers.py          # Helper functions
├── migrations/                   # Migration scripts
│   └── migrate_json_to_db.py   # JSON → PostgreSQL
├── backups/                      # Backups
├── archives/                     # Eski fayllar (archived)
├── docker-compose.yml           # Docker Compose
├── Dockerfile                   # Docker image
├── requirements.txt             # Dependencies
├── .env                         # Environment variables (create from .env.example)
└── README.md                    # Bu fayl
```

## 🔧 Konfiguratsiya

### Environment Variables (.env)

Asosiy sozlamalar:

```env
# Bot Tokens
BOT_TOKEN=your_telegram_bot_token
DEEPSEEK_API_KEY=your_deepseek_api_key

# Database (PostgreSQL)
USE_DATABASE=true
DATABASE_URL=postgresql://user:password@host:port/database

# Yoki alohida parametrlar:
DB_USER=quizbot
DB_PASSWORD=quizbot123
DB_HOST=postgres
DB_PORT=5432
DB_NAME=quizbot

# Database Connection Pool (100+ concurrent userlar uchun)
DB_USE_POOL=true  # Connection pool yoqish (tavsiya)
DB_POOL_SIZE=10  # Asosiy connectionlar soni
DB_MAX_OVERFLOW=20  # Qo'shimcha connectionlar (jami: 30 connection)

# Gmail Email (Status Report uchun)
GMAIL_SENDER_EMAIL=your_email@gmail.com
GMAIL_SENDER_PASSWORD=your_app_password  # Gmail App Password (2FA yoqilgan bo'lishi kerak)
GMAIL_RECIPIENT_EMAIL=recipient@gmail.com  # Hisobot yuboriladigan email
STATUS_REPORT_ENABLED=true  # Status report yoqish/o'chirish
STATUS_REPORT_INTERVAL=86400  # Hisobot intervali (sekundlarda, default: 24 soat)
```

**Gmail App Password olish:**
1. Google Account → Security → 2-Step Verification yoqing
2. App passwords → Create app password
3. "Mail" va "Other (Custom name)" ni tanlang
4. Olingan 16 raqamli parolni `GMAIL_SENDER_PASSWORD` ga qo'ying

Batafsil sozlamalar uchun `.env.example` faylini ko'ring.

## 📊 Database

PostgreSQL database quyidagi jadvallarni o'z ichiga oladi:

- **users** - Foydalanuvchilar
- **groups** - Guruhlar/superguruhlar
- **quizzes** - Quizlar
- **questions** - Savollar (quizzes bilan bog'langan)
- **quiz_results** - Quiz natijalari
- **premium_users** - Premium foydalanuvchilar
- va boshqalar...

Batafsil ma'lumot: `bot/models/schema.py`

### Migration (JSON → Database)

Eski JSON ma'lumotlarni database ga ko'chirish:

```bash
# 1. PostgreSQL ishlayotganini tekshiring
docker-compose ps postgres

# 2. Migration script ishga tushiring
python3 migrations/migrate_json_to_db.py
```

Batafsil qo'llanma: [MIGRATION_GUIDE.md](MIGRATION_GUIDE.md)

## 🐳 Docker Deployment

### Barcha servislarni ishga tushirish:

```bash
docker-compose up -d
```

### Faqat PostgreSQL:

```bash
docker-compose up -d postgres
```

### Loglarni ko'rish:

```bash
docker-compose logs -f bot
docker-compose logs -f postgres
```

### To'xtatish:

```bash
docker-compose down
```

## 🔄 Development

### Kod struktura

Loyiha professional clean architecture bilan yaratilgan:

- **Separation of Concerns** - Har bir modul o'z vazifasini bajaradi
- **Dependency Injection** - Loose coupling
- **Repository Pattern** - Database abstraction
- **Service Layer** - Business logic

### Yangi funksiya qo'shish

1. Handlerlar: `bot/handlers/`
2. Business logic: `bot/services/`
3. Models: `bot/models/`
4. Utilities: `bot/utils/`

## 🧪 Testing

Database connection ni tekshirish:

```python
from bot.models.database import SessionLocal, init_db
from bot.models.schema import Quiz, User

# Database jadvallarini yaratish
init_db()

# Test query
db = SessionLocal()
quiz_count = db.query(Quiz).count()
print(f"Quizzes: {quiz_count}")
db.close()
```

## 🔍 Troubleshooting

### Database connection xatoligi

1. PostgreSQL ishlayotganini tekshiring:
```bash
docker-compose ps postgres
# yoki
sudo systemctl status postgresql
```

2. Connection ni test qiling:
```bash
psql -h localhost -U quizbot -d quizbot
```

### Bot ishlamayapti

- `.env` faylda `BOT_TOKEN` to'g'ri ekanligini tekshiring
- Database connection ni tekshiring
- Dependencies o'rnatilganini tekshiring: `pip install -r requirements.txt`
- Loglarni ko'ring: `logs/` papkada

## 📚 Qo'shimcha Ma'lumot

- [Migration Guide](MIGRATION_GUIDE.md) - JSON dan Database ga o'tish qo'llanmasi
- [Archives](archives/) - Eski fayllar va dokumentatsiya

## 🤝 Yordam

Muammo bo'lsa:
1. Loglarni tekshiring: `logs/`
2. Database connection ni tekshiring
3. Environment variables ni tekshiring
4. Issues oching (agar GitHub bo'lsa)

## 📄 License

[License ma'lumotlari]

## 🎯 Features Roadmap

- [ ] Alembic migrations
- [ ] Unit tests
- [ ] CI/CD pipeline
- [ ] Monitoring & Logging
- [ ] API documentation

---

**Professional Quiz Bot** - PostgreSQL + Docker + Clean Architecture