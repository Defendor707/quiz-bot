# Migration Guide: JSON dan Database ga o'tish

Bu qo'llanma loyihani JSON fayldan PostgreSQL database ga o'tkazish uchun yaratilgan.

## 📋 Talablar

1. **PostgreSQL** (14 yoki yuqori)
2. **Python 3.10+**
3. **Barcha dependencies** (`requirements.txt`)

## 🚀 Migration qadamlari

### 1. Environment sozlash

`.env.example` faylini ko'chiring va `.env` nomiga o'zgartiring:

```bash
cp .env.example .env
```

`.env` faylida database sozlamalarini to'ldiring:

```env
USE_DATABASE=true
DATABASE_URL=postgresql://quizbot:quizbot123@localhost:5432/quizbot
```

### 2. PostgreSQL o'rnatish va sozlash

#### Docker orqali (Tavsiya):

```bash
docker-compose up -d postgres
```

#### Yoki qo'lda:

```bash
# PostgreSQL o'rnatish (Ubuntu/Debian)
sudo apt-get update
sudo apt-get install postgresql postgresql-contrib

# Database yaratish
sudo -u postgres psql
CREATE DATABASE quizbot;
CREATE USER quizbot WITH PASSWORD 'quizbot123';
GRANT ALL PRIVILEGES ON DATABASE quizbot TO quizbot;
\q
```

### 3. Python dependencies o'rnatish

```bash
pip install -r requirements.txt
```

### 4. Migration script ishga tushirish

```bash
python3 migrations/migrate_json_to_db.py
```

Bu script:
- ✅ Database jadvallarini yaratadi
- ✅ JSON fayldan ma'lumotlarni o'qiydi
- ✅ Barcha ma'lumotlarni PostgreSQL ga ko'chiradi
- ✅ Xatoliklarni log qiladi

### 5. Botni ishga tushirish

Migration tugagandan keyin, botni ishga tushiring:

```bash
python3 bot/main.py
```

Yoki Docker orqali:

```bash
docker-compose up -d
```

## 🔍 Tekshirish

Migration muvaffaqiyatli bo'lganini tekshirish:

```python
from bot.models.database import SessionLocal
from bot.models.schema import Quiz, User

db = SessionLocal()
quiz_count = db.query(Quiz).count()
user_count = db.query(User).count()
print(f"Quizzes: {quiz_count}, Users: {user_count}")
db.close()
```

## ⚠️ Muhim eslatmalar

1. **Backup yarating**: Migration oldidan `quizzes_storage.json` ni backup qiling
2. **Test qiling**: Production dan oldin test muhitida sinab ko'ring
3. **Ma'lumotlar saqlanadi**: JSON fayl o'chirilmaydi - ikkalasini birga ishlatish mumkin
4. **Rollback**: Agar muammo bo'lsa, `.env` da `USE_DATABASE=false` qiling

## 🔄 Orqaga qaytish (JSON ga)

Agar database ishlatmasangiz, faqat `.env` faylida:

```env
USE_DATABASE=false
```

Keyin bot avtomatik JSON storage ishlatadi.

## 📊 Database struktura

- **users** - Foydalanuvchilar
- **groups** - Guruhlar
- **quizzes** - Quizlar
- **questions** - Savollar (quizzes bilan bog'langan)
- **quiz_results** - Natijalar
- **group_quiz_allowlist** - Guruh uchun ruxsatlar
- **quiz_allowed_groups** - Private quiz uchun ruxsatlar
- **sudo_users** - Sudo foydalanuvchilar
- **vip_users** - VIP foydalanuvchilar
- **premium_users** - Premium foydalanuvchilar
- **premium_payments** - Premium to'lovlar
- **required_channels** - Majburiy kanallar

## 🆘 Yordam

Agar muammo bo'lsa:
1. Loglarni tekshiring: `logs/` papkada
2. Database connection ni tekshiring
3. Migration script xatoliklarini ko'ring
