"""Handlers registratsiyasi"""
from telegram.ext import (
    CommandHandler, MessageHandler, CallbackQueryHandler,
    PollAnswerHandler, ChatMemberHandler, filters
)

from bot.handlers.start import start, help_command, myresults_command
from bot.handlers.quiz import (
    myquizzes_command, sudo_command, quizzes_command,
    searchquiz_command, quiz_command, deletequiz_command,
    finishquiz_command, handle_text_message, handle_file
)
from bot.handlers.group import (
    my_chat_member_handler, allowquiz_command, disallowquiz_command,
    allowedquizzes_command, startquiz_command, stopquiz_command
)
from bot.handlers.admin import admin_command
from bot.handlers.callbacks import callback_handler, poll_answer_handler


def register_handlers(application):
    """Barcha handlerlarni ro'yxatdan o'tkazish"""
    
    # Start va asosiy buyruqlar
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("myresults", myresults_command))
    
    # Quiz buyruqlari
    application.add_handler(CommandHandler("myquizzes", myquizzes_command))
    application.add_handler(CommandHandler("sudo", sudo_command))
    application.add_handler(CommandHandler("quizzes", quizzes_command))
    application.add_handler(CommandHandler("searchquiz", searchquiz_command))
    application.add_handler(CommandHandler("quiz", quiz_command))
    application.add_handler(CommandHandler("deletequiz", deletequiz_command))
    application.add_handler(CommandHandler("finishquiz", finishquiz_command))
    
    # Guruh buyruqlari
    application.add_handler(CommandHandler("allowquiz", allowquiz_command))
    application.add_handler(CommandHandler("disallowquiz", disallowquiz_command))
    application.add_handler(CommandHandler("allowedquizzes", allowedquizzes_command))
    application.add_handler(CommandHandler("startquiz", startquiz_command))
    application.add_handler(CommandHandler("stopquiz", stopquiz_command))
    
    # Admin
    application.add_handler(CommandHandler("admin", admin_command))
    
    # Fayl handler
    application.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    
    # Matn xabarlar (klaviatura tugmalari)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    
    # Callback va poll handlerlar
    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_handler(PollAnswerHandler(poll_answer_handler))
    application.add_handler(ChatMemberHandler(my_chat_member_handler, ChatMemberHandler.MY_CHAT_MEMBER))

