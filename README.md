# Telegram Quiz Bot

Telegram bot - fayl tahlil qilib quiz yaratadigan bot.

## Struktura

```
telegram_bot/
├── telegram_poll_bot.py    # Asosiy bot fayli
├── database.py              # Database moduli
├── requirements.txt         # Python dependencies
├── telegram-bot.service    # Systemd service fayli
├── bot_database.db         # SQLite database
├── venv/                    # Virtual environment
└── logs/                    # Log fayllar
```

## Database

SQLite database quyidagi jadvallarni o'z ichiga oladi:
- `quizzes` - Quizlar ro'yxati
- `quiz_results` - Quiz natijalari

## Systemd Service

Bot systemd xizmati sifatida ishga tushiriladi:

```bash
# Service holatini ko'rish
sudo systemctl status telegram-bot.service

# Service ni qayta ishga tushirish
sudo systemctl restart telegram-bot.service

# Service ni to'xtatish
sudo systemctl stop telegram-bot.service

# Service ni ishga tushirish
sudo systemctl start telegram-bot.service

# Loglarni ko'rish
sudo journalctl -u telegram-bot.service -f
```

## Environment Variables

Service faylida quyidagi environment variables sozlangan:
- `BOT_TOKEN` - Telegram bot token
- `DEEPSEEK_API_KEY` - DeepSeek API kaliti

## Qo'llash

1. Botni ishga tushirish: Service avtomatik ishga tushadi
2. Telegram'da botga fayl yuborish (TXT, PDF, DOCX)
3. Bot faylni tahlil qilib quiz yaratadi
4. Quizni boshlash va natijalarni ko'rish

