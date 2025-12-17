# Modullash rejasi

## Hozirgi holat
- Backup: ✅ backups/ papkada
- Yangi struktura: ✅ bot/ papkada
- Ma'lumotlar: ✅ saqlanadi (quizzes_storage.json, bot_persistence.pickle)

## Bajarilgan
- [x] bot/config.py - sozlamalar
- [x] bot/services/ai_parser.py - AI logikasi
- [x] bot/services/file_parser.py - fayl o'qish
- [x] bot/utils/validators.py - validation
- [x] bot/models/storage.py - ma'lumot saqlash
- [x] bot/handlers/start.py - start, help, myresults
- [x] .env - tokenlar yashirilgan
- [x] systemd yangilangan - .env'dan o'qiydi

## Qolgan ishlar (~ 3500 qator ko'chirish kerak)

### bot/handlers/quiz.py
- myquizzes_command (pagination)
- quizzes_command (pagination)  
- searchquiz_command
- quiz_command
- deletequiz_command
- finishquiz_command
- handle_file (AI bilan)
- handle_text_message

### bot/handlers/group.py
- startquiz_command (guruh)
- stopquiz_command
- allowquiz_command
- disallowquiz_command
- allowedquizzes_command

### bot/handlers/admin.py
- admin_command
- sudo_command
- show_admin_menu
- _admin_gq_* (12 ta funksiya)

### bot/handlers/callbacks.py
- callback_handler (asosiy)
- poll_answer_handler
- my_chat_member_handler

### bot/services/quiz_service.py
- start_quiz_session
- send_quiz_question
- show_quiz_results
- advance_due_sessions

## Xavfsizlik
- Tokenlar .env da (chmod 600)
- Systemd .env'dan o'qiydi
- Ma'lumotlar backup qilingan

## Keyingi qadam
Barcha handlerlarni ajratish va main.py'da ro'yxatdan o'tkazish.
