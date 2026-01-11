#!/bin/bash
# Botni ishga tushirish (polling rejimi)

cd /home/azureuser/quiz-bot

echo "🚀 Botni ishga tushirish..."

# Mavjud jarayonlarni to'xtatish
pkill -f "python.*bot/main.py" || true
sleep 1

# Polling rejimiga sozlash
sed -i 's/^USE_WEBHOOK=.*/USE_WEBHOOK=0/' .env

# Virtual environment
source venv/bin/activate 2>/dev/null || true
export PYTHONPATH=/home/azureuser/quiz-bot:$PYTHONPATH

# data/ papkasini yaratish
mkdir -p data

# Botni ishga tushirish
nohup python3 bot/main.py > logs/bot.log 2>&1 &
echo $! > data/bot.pid

sleep 2

if ps aux | grep -q "[p]ython.*bot/main.py"; then
    echo "✅ Bot ishga tushdi!"
    echo "📝 Log: tail -f logs/bot.log"
else
    echo "❌ Bot ishga tushmadi! Logni tekshiring: tail logs/bot.log"
    exit 1
fi
