#!/bin/bash
cd /home/azureuser/quiz-bot
source venv/bin/activate
export $(cat .env | grep -v '^#' | xargs)
python3 bot/main.py
