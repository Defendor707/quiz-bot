# Quiz Bot - Modullashtirilgan Versiya

## 📋 O'zgarishlar

Loyiha to'liq modullashtirildi! Eski **4198 qatorli** `telegram_poll_bot.py` fayl endi toza modullar bo'yicha ajratilgan:

### 🗂 Yangi Struktura

```
bot/
├── __init__.py
├── main.py                    # Asosiy ishga tushirish fayli
├── config.py                  # Sozlamalar va environment variables
│
├── handlers/                  # Telegram handlerlar
│   ├── __init__.py           # Handlerlarni registratsiya qilish
│   ├── start.py              # /start, /help, /myresults
│   ├── quiz.py               # Quiz CRUD, file handling
│   ├── group.py              # Guruh buyruqlari
│   ├── admin.py              # Admin panel
│   └── callbacks.py          # Callback va poll handlerlar
│
├── services/                  # Biznes logika
│   ├── __init__.py
│   ├── ai_parser.py          # DeepSeek AI integratsiyasi
│   ├── file_parser.py        # Fayl o'qish (PDF, DOCX, TXT)
│   └── quiz_service.py       # Quiz session management
│
├── models/                    # Ma'lumot modellari
│   ├── __init__.py
│   └── storage.py            # JSON storage
│
└── utils/                     # Yordamchi funksiyalar
    ├── __init__.py
    ├── helpers.py            # Umumiy yordamchi funksiyalar
    └── validators.py         # Validation va parsing
```

## ✨ Afzalliklari

1. **Modullar ajratilgan** - har bir modul o'z vazifasini bajaradi
2. **Oson test qilish** - har bir modulni alohida test qilish mumkin
3. **Oson rivojlantirish** - yangi funksiya qo'shish oson
4. **Kod qayta ishlatiladi** - DRY prinsipi
5. **Xatolarni tezda topish** - kichik modullar debuging oson
6. **Kattalashtirish mumkin** - yangi xususiyatlar qo'shish oson

## 🚀 Ishga Tushirish

### 1. Modullashtirilgan versiya (Yangi)

```bash
# Aktivlashtirish
source venv/bin/activate

# Ishga tushirish
python3 -m bot.main
```

### 2. Systemd service (Production)

```bash
# Service faylini yangilash
sudo cp telegram-bot.service.new /etc/systemd/system/telegram-bot.service
sudo systemctl daemon-reload

# Eski botni to'xtatish
sudo systemctl stop telegram-bot

# Yangi botni ishga tushirish
sudo systemctl start telegram-bot
sudo systemctl status telegram-bot

# Loglarni ko'rish
sudo journalctl -u telegram-bot -f
```

### 3. Eski versiya (Backup)

Eski `telegram_poll_bot.py` fayl saqlanib qoldi:

```bash
python3 telegram_poll_bot.py
```

## 📊 Statistika

| Metrika | Eski | Yangi |
|---------|------|------|
| Fayllar soni | 1 | 15+ |
| Qatorlar (main) | 4198 | ~50 |
| Funksiyalar | 51 | 51 (taqsimlangan) |
| Modullar | 0 | 4 (handlers, services, models, utils) |

## 🔧 Texnik Tafsilotlar

### Environment Variables (.env)

```env
BOT_TOKEN=your_bot_token_here
DEEPSEEK_API_KEY=your_deepseek_api_key_here
ADMIN_USER_IDS=123456789,987654321
MIN_QUESTIONS_REQUIRED=2
MAX_QUESTIONS_PER_QUIZ=100
TARGET_QUESTIONS_PER_QUIZ=50
```

### Dependencies

Barcha kerakli paketlar `requirements.txt` da:

```bash
pip install -r requirements.txt
```

## 🧪 Testing

```bash
# Import test
python3 -c "from bot.main import main; print('✅ Import muvaffaqiyatli')"

# Config test
python3 -c "from bot.config import Config; print(f'Token: {Config.BOT_TOKEN[:10]}...')"

# Handlerlar test
python3 -c "from bot.handlers import register_handlers; print('✅ Handlerlar tayyor')"
```

## 📝 Keyingi Qadamlar

1. ✅ Modullashtirilgan
2. ✅ Barcha funksiyalar ajratilgan
3. ✅ Handlerlar ro'yxatdan o'tkazilgan
4. 🔄 Production testda
5. 📊 Monitoring qo'shish (opsional)

## 🆘 Muammolar

Agar muammo bo'lsa:

1. **Botni qayta ishga tushiring**:
   ```bash
   sudo systemctl restart telegram-bot
   ```

2. **Loglarni tekshiring**:
   ```bash
   sudo journalctl -u telegram-bot -n 100 --no-pager
   ```

3. **Eski versiyaga qaytish** (zarur bo'lsa):
   ```bash
   sudo systemctl stop telegram-bot
   python3 telegram_poll_bot.py
   ```

## 📞 Qo'llab-quvvatlash

Savol yoki muammolar bo'lsa, eski `telegram_poll_bot.py` fayl backup sifatida saqlanib qolgan.

---

**Yaratildi:** 2025-12-17  
**Versiya:** 2.0 (Modullashtirilgan)  
**Status:** ✅ Tayyor

