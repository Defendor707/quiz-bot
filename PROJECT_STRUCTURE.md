# Project Structure - Professional Architecture

## 📁 Toza Struktura

```
quiz-bot/
├── bot/                          # 🎯 Asosiy bot kodi
│   ├── __init__.py
│   ├── main.py                  # Entry point
│   ├── config.py                # Configuration management
│   │
│   ├── handlers/                # 📱 Telegram handlers
│   │   ├── __init__.py         # Handler registration
│   │   ├── start.py            # /start, /help commands
│   │   ├── quiz.py             # Quiz CRUD operations
│   │   ├── admin.py            # Admin panel
│   │   └── premium.py          # Premium features
│   │
│   ├── services/                # 🔧 Business logic
│   │   ├── __init__.py
│   │   ├── ai_parser.py        # DeepSeek AI integration
│   │   ├── file_parser.py      # File parsing (PDF, DOCX, TXT)
│   │   └── quiz_service.py     # Quiz session management
│   │
│   ├── models/                  # 💾 Data models
│   │   ├── __init__.py         # Storage instance
│   │   ├── database.py         # Database config & session
│   │   ├── schema.py           # SQLAlchemy ORM models
│   │   ├── storage.py          # JSON storage (fallback)
│   │   └── storage_db.py       # Database storage (PostgreSQL)
│   │
│   └── utils/                   # 🛠️ Utilities
│       ├── __init__.py
│       ├── validators.py       # Validation functions
│       └── helpers.py          # Helper functions
│
├── migrations/                   # 🔄 Migration scripts
│   ├── __init__.py
│   └── migrate_json_to_db.py  # JSON → PostgreSQL migration
│
├── backups/                      # 💾 Backups (git-ignored)
│
├── archives/                     # 📦 Old files (archived, git-ignored)
│   ├── docs/                    # Old documentation
│   └── [old files]              # Old code files
│
├── docker-compose.yml           # 🐳 Docker Compose config
├── Dockerfile                   # 🐳 Docker image
├── requirements.txt             # 📦 Python dependencies
├── .env.example                 # 🔐 Environment variables template
├── .gitignore                   # 🚫 Git ignore rules
│
├── README.md                    # 📖 Main documentation
├── MIGRATION_GUIDE.md          # 🔄 Migration guide
└── PROJECT_STRUCTURE.md        # 📁 This file
```

## 🎯 Modullar Tushuntirishi

### `bot/main.py`
- Bot ishga tushirish
- Application builder
- Handler registration
- Post-init hooks

### `bot/config.py`
- Environment variables
- Configuration management
- Settings validation

### `bot/handlers/`
- Telegram command handlers
- Callback handlers
- Message handlers
- Separation by feature

### `bot/services/`
- Business logic
- AI integration
- File processing
- Quiz session management

### `bot/models/`
- Database models (SQLAlchemy)
- Storage abstraction
- Data access layer

### `bot/utils/`
- Helper functions
- Validators
- Common utilities

## 🔄 Data Flow

```
User Message → Handler → Service → Model → Database
                                    ↓
                              Storage (DB/JSON)
```

## 📊 Database Schema

PostgreSQL jadvallari:
- `users` - Users table
- `groups` - Groups/supergroups
- `quizzes` - Quizzes
- `questions` - Questions (FK: quizzes)
- `quiz_results` - Results
- `premium_users` - Premium subscriptions
- va boshqalar...

Batafsil: `bot/models/schema.py`

## 🚀 Deployment

### Development
```bash
python3 bot/main.py
```

### Production (Docker)
```bash
docker-compose up -d
```

## 📝 Best Practices

1. **Separation of Concerns** - Har bir modul o'z vazifasini bajaradi
2. **Dependency Injection** - Loose coupling
3. **Repository Pattern** - Database abstraction
4. **Service Layer** - Business logic
5. **Error Handling** - Comprehensive error handling
6. **Logging** - Structured logging

## 🔧 Maintenance

### Ortiqcha fayllar

- ✅ Eski fayllar `archives/` ga ko'chirildi
- ✅ Ortiqcha README fayllar birlashtirildi
- ✅ Clean root directory

### Code Organization

- ✅ Modullashtirilgan
- ✅ Clean architecture
- ✅ Easy to maintain
- ✅ Scalable
