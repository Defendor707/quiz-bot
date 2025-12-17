# Quiz Bot - Yangi Struktura

## 📁 Fayl tuzilishi

```
quiz-bot/
├── bot/                              # Asosiy bot kodi (modullashtirilgan)
│   ├── __init__.py
│   ├── config.py                     # Sozlamalar va environment variables
│   ├── main.py                       # Bot ishga tushirish (yangi)
│   │
│   ├── handlers/                     # Telegram handlerlar
│   │   ├── __init__.py
│   │   ├── start.py                  # /start, /help
│   │   ├── quiz.py                   # Quiz yaratish, boshlash
│   │   ├── admin.py                  # Admin panel
│   │   └── callbacks.py              # Callback handlerlar
│   │
│   ├── services/                     # Biznes logika
│   │   ├── __init__.py
│   │   ├── ai_parser.py              # DeepSeek AI integratsiyasi ✅
│   │   └── file_parser.py            # Fayl o'qish (PDF, DOCX, TXT) ✅
│   │
│   ├── models/                       # Ma'lumot modellari
│   │   ├── __init__.py
│   │   └── storage.py                # JSON storage ✅
│   │
│   └── utils/                        # Yordamchi funksiyalar
│       ├── __init__.py
│       └── validators.py             # Validation funksiyalar ✅
│
├── .env                              # Maxfiy kalitlar (git'ga qo'shilmaydi) ✅
├── requirements-new.txt              # Python dependencies (yangi)
├── telegram-bot-new.service          # Systemd service (.env bilan) ✅
│
├── telegram_poll_bot.py              # Eski monolit fayl (hozir ishlatilmoqda)
├── storage.py                        # Eski storage
├── database.py                       # Eski database
└── quizzes_storage.json              # Ma'lumotlar bazasi
```

## ✅ Nima bajarildi

1. **Yangi papka strukturasi** yaratildi
2. **config.py** — barcha sozlamalar bir joyda
3. **ai_parser.py** — AI logikasi ajratilgan
4. **file_parser.py** — fayl o'qish ajratilgan
5. **validators.py** — validation logikasi ajratilgan
6. **.env** — tokenlar yashirilgan (chmod 600)
7. **systemd service** — .env'dan o'qiydi

## 🚧 Keyingi bosqichlar

1. **Handlerlarni ajratish** — telegram_poll_bot.py dan ajratib bot/handlers/ ga ko'chirish
2. **main.py'ni to'ldirish** — barcha handlerlarni ro'yxatdan o'tkazish
3. **Test qilish** — yangi struktura bilan ishlashini tekshirish
4. **Eski faylni arxivlash** — telegram_poll_bot.py zaxira

## 🔄 Hozirgi holat

- **Ishlatilmoqda**: `telegram_poll_bot.py` (eski monolit)
- **Tayyor**: Yangi modullar (ai_parser, file_parser, config, validators)
- **Keyingi**: Handlerlarni ajratish va yangi strukturaga to'liq o'tish

## 🎯 Maqsad

Kod modullashtirilgandan keyin:
- ✅ Oson rivojlantirish
- ✅ Test yozish mumkin
- ✅ Xatoliklarni tez topish
- ✅ Kattalashtirish mumkin
- ✅ Tokenlar xavfsiz

