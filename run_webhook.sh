#!/bin/bash
cd /home/azureuser/quiz-bot
source venv/bin/activate
export PYTHONPATH=/home/azureuser/quiz-bot:$PYTHONPATH
python3 bot/main.py
