"""Inline query handler - @bot_username orqali quiz boshlash"""
import logging
from telegram import Update, InlineQueryResultArticle, InputTextMessageContent, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from bot.models import storage
from bot.utils.helpers import track_update

logger = logging.getLogger(__name__)


async def chosen_inline_result_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Chosen inline result handler - foydalanuvchi inline natijani tanlaganda
    
    Bu handler foydalanuvchi inline query natijasini tanlaganda chaqiriladi.
    Bu inline query statistika yoki boshqa tracking uchun foydali.
    """
    if not update.chosen_inline_result:
        return
    
    chosen_result = update.chosen_inline_result
    user_id = chosen_result.from_user.id
    result_id = chosen_result.result_id
    query = chosen_result.query
    
    logger.info(f"Chosen inline result: user_id={user_id}, result_id={result_id}, query={query}")
    
    # Foydalanuvchini tracking qilish
    try:
        track_update(update)
    except Exception as e:
        logger.warning(f"Track update xatolik: {e}")


async def inline_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inline query handler - @bot_username yozilganda
    
    Foydalanuvchi yaratgan quizlarni ko'rsatadi va quiz ID orqali chatga uzatish imkonini beradi.
    """
    try:
        query = update.inline_query.query.strip()
        user_id = update.inline_query.from_user.id
        
        logger.info(f"📥 Inline query received: user_id={user_id}, query='{query}'")
        
        # Foydalanuvchini tracking qilish
        track_update(update)
        
        results = []
        
        # Agar query bo'sh bo'lsa yoki "quiz" yozilsa, foydalanuvchi yaratgan quizlarni ko'rsatish
        if not query or query.lower() in ['quiz', 'quizzes', 'test']:
            # Foydalanuvchi yaratgan quizlarni olish
            user_quizzes = storage.get_user_quizzes(user_id)
            
            if user_quizzes:
                # Foydalanuvchi yaratgan quizlarni ko'rsatish
                for quiz in user_quizzes[:10]:  # Birinchi 10 tasini
                    quiz_id = quiz.get('quiz_id')
                    title = quiz.get('title', 'Quiz')
                    questions_count = len(quiz.get('questions', []))
                    
                    # Inline result yaratish - quiz ID orqali chatga uzatish
                    result = InlineQueryResultArticle(
                        id=quiz_id,
                        title=f"📝 {title}",
                        description=f"{questions_count} ta savol | ID: {quiz_id}",
                        input_message_content=InputTextMessageContent(
                            message_text=(
                                f"📝 **{title}**\n\n"
                                f"📋 Savollar: {questions_count} ta\n"
                                f"🆔 Quiz ID: `{quiz_id}`\n\n"
                                f"Quizni boshlash uchun tugmani bosing:"
                            ),
                            parse_mode=ParseMode.MARKDOWN
                        ),
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("🚀 Quizni boshlash", callback_data=f"select_time_{quiz_id}")
                        ]])
                    )
                    results.append(result)
            else:
                # Agar foydalanuvchi yaratgan quizlar yo'q bo'lsa, barcha quizlarni ko'rsatish
                all_quizzes = storage.get_all_quizzes()
                for quiz in all_quizzes[:10]:  # Birinchi 10 tasini
                    quiz_id = quiz.get('quiz_id')
                    title = quiz.get('title', 'Quiz')
                    questions_count = len(quiz.get('questions', []))
                    
                    result = InlineQueryResultArticle(
                        id=quiz_id,
                        title=f"📝 {title}",
                        description=f"{questions_count} ta savol",
                        input_message_content=InputTextMessageContent(
                            message_text=(
                                f"📝 **{title}**\n\n"
                                f"📋 Savollar: {questions_count} ta\n\n"
                                f"Quizni boshlash uchun tugmani bosing:"
                            ),
                            parse_mode=ParseMode.MARKDOWN
                        ),
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("🚀 Quizni boshlash", callback_data=f"select_time_{quiz_id}")
                        ]])
                    )
                    results.append(result)
        
        # Agar query quiz ID bo'lsa (to'g'ridan-to'g'ri ID yozilsa)
        elif query and len(query) >= 8:  # Quiz ID odatda 12-13 belgi
            # Aniq quiz ID ni qidirish
            quiz = storage.get_quiz(query)
            if quiz:
                quiz_id = quiz.get('quiz_id')
                title = quiz.get('title', 'Quiz')
                questions_count = len(quiz.get('questions', []))
                
                result = InlineQueryResultArticle(
                    id=quiz_id,
                    title=f"📝 {title}",
                    description=f"{questions_count} ta savol | ID: {quiz_id}",
                    input_message_content=InputTextMessageContent(
                        message_text=(
                            f"📝 **{title}**\n\n"
                            f"📋 Savollar: {questions_count} ta\n"
                            f"🆔 Quiz ID: `{quiz_id}`\n\n"
                            f"Quizni boshlash uchun tugmani bosing:"
                        ),
                        parse_mode=ParseMode.MARKDOWN
                    ),
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🚀 Quizni boshlash", callback_data=f"select_time_{quiz_id}")
                    ]])
                )
                results.append(result)
        
        # Agar query quiz nomi bo'lsa, qidirish
        elif query:
            # Avval foydalanuvchi yaratgan quizlarni qidirish
            user_quizzes = storage.get_user_quizzes(user_id)
            query_lower = query.lower()
            
            for quiz in user_quizzes:
                quiz_id = quiz.get('quiz_id')
                title = quiz.get('title', 'Quiz')
                
                # Quiz ID yoki nomida qidirish
                if query_lower in quiz_id.lower() or query_lower in title.lower():
                    questions_count = len(quiz.get('questions', []))
                    
                    result = InlineQueryResultArticle(
                        id=quiz_id,
                        title=f"📝 {title}",
                        description=f"{questions_count} ta savol | ID: {quiz_id}",
                        input_message_content=InputTextMessageContent(
                            message_text=(
                                f"📝 **{title}**\n\n"
                                f"📋 Savollar: {questions_count} ta\n"
                                f"🆔 Quiz ID: `{quiz_id}`\n\n"
                                f"Quizni boshlash uchun tugmani bosing:"
                            ),
                            parse_mode=ParseMode.MARKDOWN
                        ),
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("🚀 Quizni boshlash", callback_data=f"select_time_{quiz_id}")
                        ]])
                    )
                    results.append(result)
                    
                    if len(results) >= 10:  # Maksimal 10 ta natija
                        break
            
            # Agar foydalanuvchi quizlari orasida topilmasa, barcha quizlarni qidirish
            if not results:
                all_quizzes = storage.get_all_quizzes()
                for quiz in all_quizzes:
                    quiz_id = quiz.get('quiz_id')
                    title = quiz.get('title', 'Quiz')
                    
                    if query_lower in quiz_id.lower() or query_lower in title.lower():
                        questions_count = len(quiz.get('questions', []))
                        
                        result = InlineQueryResultArticle(
                            id=quiz_id,
                            title=f"📝 {title}",
                            description=f"{questions_count} ta savol",
                            input_message_content=InputTextMessageContent(
                                message_text=(
                                    f"📝 **{title}**\n\n"
                                    f"📋 Savollar: {questions_count} ta\n\n"
                                    f"Quizni boshlash uchun tugmani bosing:"
                                ),
                                parse_mode=ParseMode.MARKDOWN
                            ),
                            reply_markup=InlineKeyboardMarkup([[
                                InlineKeyboardButton("🚀 Quizni boshlash", callback_data=f"select_time_{quiz_id}")
                            ]])
                        )
                        results.append(result)
                        
                        if len(results) >= 10:  # Maksimal 10 ta natija
                            break
        
        # Agar natijalar bo'sh bo'lsa
        if not results:
            results.append(
                InlineQueryResultArticle(
                    id="no_results",
                    title="❌ Quiz topilmadi",
                    description="Boshqa so'z bilan qidiring yoki quiz ID yozing",
                    input_message_content=InputTextMessageContent(
                        message_text="❌ Quiz topilmadi. Boshqa so'z bilan qidiring yoki quiz ID yozing.\n\n"
                                    "Masalan: `@bot_username abc123def456`"
                    )
                )
            )
        
        try:
            # Switch inline query privacy - agar True bo'lsa, faqat user o'zining natijalarini ko'radi
            # False bo'lsa, barcha userlar barcha quizlarni ko'radi (lekin inline query privacy sozlanmagan bo'lsa ham ishlaydi)
            await update.inline_query.answer(results, cache_time=10, is_personal=False)
            logger.info(f"✅ Inline query answered: {len(results)} results sent")
        except Exception as e:
            logger.error(f"❌ Inline query answer xatolik: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"❌ Inline query handler xatolik: {e}", exc_info=True)
