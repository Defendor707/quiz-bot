# Load Test - Bot Performance Testi

Botning 100+ concurrent foydalanuvchilarni qanday kutib olishini test qilish.

## 📋 Talablar

```bash
pip install httpx  # load_test.py uchun
# internal_load_test.py uchun qo'shimcha kutubxona kerak emas
```

## 🚀 Test turlari

### 1. External Load Test (`load_test.py`)
**Real Telegram API orqali test** - haqiqiy foydalanuvchilar kabi ishlaydi
- ✅ Haqiqiy API so'rovlari
- ✅ Rate limiting tekshiriladi
- ❌ Bot token kerak
- ❌ Chat ID kerak

### 2. Internal Load Test (`internal_load_test.py`)
**Botning ichki funksiyalarini test** - tezroq va oson
- ✅ Bot token kerak emas
- ✅ Tezroq test
- ✅ Ichki logikani to'g'ridan-to'g'ri test qiladi
- ❌ Real API so'rovlari yo'q

### 3. Quiz Creation Load Test (`quiz_creation_load_test.py`)
**100+ foydalanuvchi bir vaqtda quiz yaratishni test qilish**
- ✅ Bot token kerak emas
- ✅ Tezroq test
- ✅ Quiz yaratish funksiyasini to'g'ridan-to'g'ri test qiladi
- ✅ Database connection pool tekshiriladi
- ❌ Real API so'rovlari yo'q

## 🚀 Ishlatish

### External Load Test (Real API)

#### 1. Sozlamalar (.env)

```env
# Bot token (majburiy)
BOT_TOKEN=your_bot_token

# Test parametrlari
LOAD_TEST_USERS=100  # Concurrent foydalanuvchilar soni (default: 100)
LOAD_TEST_CHAT_ID=your_chat_id  # Test chat ID (majburiy)
LOAD_TEST_QUIZ_ID=quiz_id  # Test quiz ID (ixtiyoriy)
```

#### 2. Test ishga tushirish

```bash
# Virtual environment aktiv qiling
source venv/bin/activate

# Test ishga tushirish
python3 tests/load_test.py
```

### Internal Load Test (Ichki funksiyalar)

#### 1. Sozlamalar (.env)

```env
# Test parametrlari
LOAD_TEST_USERS=100  # Concurrent foydalanuvchilar soni (default: 100)
LOAD_TEST_QUIZ_ID=quiz_id  # Test quiz ID (majburiy)
```

#### 2. Quiz ID topish

```bash
# Mavjud quiz ID ni topish
python3 -c "from bot.models import storage; quizzes = storage.get_all_quizzes(); print(list(quizzes)[0]['id'] if quizzes else 'No quizzes')"
```

#### 3. Test ishga tushirish

```bash
# Virtual environment aktiv qiling
source venv/bin/activate

# Test ishga tushirish
python3 tests/internal_load_test.py
```

### Quiz Creation Load Test (Quiz yaratish)

#### 1. Test ishga tushirish

```bash
# Virtual environment aktiv qiling
source venv/bin/activate

# 100 ta foydalanuvchi bilan test
python3 tests/quiz_creation_load_test.py --users 100

# 200 ta foydalanuvchi bilan test
python3 tests/quiz_creation_load_test.py --users 200
```

#### 2. Natijalar

**100 ta foydalanuvchi:**
- ✅ Muvaffaqiyat darajasi: 100%
- ✅ O'rtacha vaqt: ~0.009 sekund
- ✅ Sekundiga so'rovlar: ~116 req/s

**200 ta foydalanuvchi:**
- ✅ Muvaffaqiyat darajasi: 100%
- ✅ O'rtacha vaqt: ~0.008 sekund
- ✅ Sekundiga so'rovlar: ~122 req/s

### 3. Natijalar

Test yakunlanganda:
- Console'da statistika ko'rsatiladi
- JSON hisobot `tests/load_test_report_*.json` faylida saqlanadi

## 📊 Test nima qiladi?

### External Load Test
1. **Parallel API requestlar**: Telegram API ga parallel so'rovlar yuboradi
2. **Response time**: Har bir API requestning vaqtini o'lchaydi
3. **Success rate**: Muvaffaqiyatli/xatoliklar foizini hisoblaydi
4. **Performance metrics**: 
   - O'rtacha response time
   - Min/Max response time
   - P95, P99 (percentile)
   - Requests per second

### Internal Load Test
1. **Parallel quiz start**: Botning ichki funksiyalarini parallel chaqiradi
2. **Session management**: Session yaratish va boshqarishni test qiladi
3. **Memory usage**: Bot memory ishlatilishini kuzatadi
4. **Database connections**: Database connection pool ishlatilishini tekshiradi

## 📈 Natijalar tahlili

- **Success rate >= 95%**: ✅ Bot yaxshi ishlayapti
- **Success rate >= 80%**: ⚠️ Optimizatsiya kerak
- **Success rate < 80%**: ❌ Jiddiy optimizatsiya kerak

## 💡 Maslahatlar

1. **Kichikdan boshlang**: Avval 10-20 ta foydalanuvchi bilan test qiling
2. **Real chat ID ishlating**: O'z chat ID nizni ishlating (bot sizga xabar yuboradi)
3. **Server resurslarini kuzating**: Test paytida CPU, RAM, Network ishlatilishini kuzating
4. **Bot loglarini kuzating**: `sudo journalctl -u quiz-bot -f` bilan loglarni kuzating

## 🔍 Monitoring

Test paytida bot holatini kuzatish:

```bash
# Bot loglari
sudo journalctl -u quiz-bot -f

# System resurslari
htop

# Database connections
sudo -u postgres psql -c "SELECT count(*) FROM pg_stat_activity WHERE datname='quizbot';"
```
