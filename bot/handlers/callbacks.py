"""Callback va poll handlerlar"""
import time
import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from bot.config import Config
from bot.models import storage
from bot.utils.helpers import (
    track_update, is_admin_user, is_sudo_user,
    safe_edit_text, TIME_OPTIONS
)
from bot.services.quiz_service import start_quiz_session, send_quiz_question, advance_due_sessions
from bot.handlers.admin import (
    show_admin_menu, _admin_gq_show_groups, _admin_gq_show_group_menu,
    _admin_gq_show_allowed_list, _admin_gq_show_pick_latest
)

logger = logging.getLogger(__name__)


async def poll_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Poll javobini qabul qilish"""
    try:
        if update.poll_answer and update.poll_answer.user:
            u = update.poll_answer.user
            storage.track_user(user_id=u.id, username=getattr(u, "username", None), first_name=getattr(u, "first_name", None), last_name=getattr(u, "last_name", None))
    except Exception:
        pass
    
    await advance_due_sessions(context)
    poll_answer = update.poll_answer
    user_id = poll_answer.user.id
    poll_id = poll_answer.poll_id
    selected_option = poll_answer.option_ids[0] if poll_answer.option_ids else None
    
    logger.info(f"Poll answer: user_id={user_id}, poll_id={poll_id}, selected={selected_option}")
    
    # Voting javobini tekshirish
    from bot.services.voting import handle_voting_answer
    if await handle_voting_answer(update, context):
        # Voting yakunlangan, quiz boshlangan yoki to'xtatilgan
        return
    
    if 'polls' not in context.bot_data or poll_id not in context.bot_data['polls']:
        logger.warning(f"Poll {poll_id} not found in bot_data")
        return
    
    poll_info = context.bot_data['polls'][poll_id]
    quiz_id = poll_info['quiz_id']
    question_index = poll_info['question_index']
    chat_id = poll_info['chat_id']
    session_key = poll_info.get('session_key')
    
    logger.info(f"Poll info: quiz_id={quiz_id}, q_index={question_index}, session_key={session_key}, chat_id={chat_id}")
    
    if 'sessions' not in context.bot_data:
        context.bot_data['sessions'] = {}
    
    if session_key not in context.bot_data['sessions']:
        logger.warning(f"Session {session_key} not found in bot_data")
        return
    
    # Save answer
    if 'answers' not in context.bot_data['sessions'][session_key]:
        context.bot_data['sessions'][session_key]['answers'] = {}
    
    if 'user_answers' not in context.bot_data['sessions'][session_key]:
        context.bot_data['sessions'][session_key]['user_answers'] = {}
    
    if user_id not in context.bot_data['sessions'][session_key]['user_answers']:
        context.bot_data['sessions'][session_key]['user_answers'][user_id] = {}
    
    context.bot_data['sessions'][session_key]['user_answers'][user_id][question_index] = selected_option
    context.bot_data['sessions'][session_key]['answers'][question_index] = selected_option
    
    # Javob berilganligini belgilash (pauza uchun)
    context.bot_data['sessions'][session_key]['last_answered_question'] = question_index
    # Consecutive counter'ni reset qilish
    context.bot_data['sessions'][session_key]['consecutive_no_answers'] = 0
    
    # Vaqtni hisoblash va saqlash
    import time
    current_time = time.time()
    question_times = context.bot_data['sessions'][session_key].get('question_times', {})
    if question_index in question_times:
        sent_at = question_times[question_index].get('sent_at')
        if sent_at:
            answer_time = current_time - sent_at  # soniyalarda
            # Har bir user uchun vaqtni saqlash
            if 'user_times' not in question_times[question_index]:
                question_times[question_index]['user_times'] = {}
            question_times[question_index]['user_times'][user_id] = answer_time
            logger.info(f"Answer time saved: user={user_id}, q_index={question_index}, time={answer_time:.2f}s")
    
    logger.info(f"Answer saved: user={user_id}, q_index={question_index}, selected={selected_option}")

    # Early advance for private chat
    try:
        starter_id = int(poll_info.get('user_id'))
    except Exception:
        starter_id = None

    sess = context.bot_data['sessions'].get(session_key, {})
    if starter_id is not None and user_id == starter_id and sess.get('is_active', False) and sess.get('chat_type') == 'private':
        current_q = sess.get('current_question', 0)
        if current_q == question_index:
            try:
                msg_id = poll_info.get('message_id')
                if msg_id:
                    await context.bot.stop_poll(chat_id=chat_id, message_id=int(msg_id))
            except Exception as e:
                logger.warning(f"stop_poll failed: {e}")

            next_idx = question_index + 1
            sess['current_question'] = next_idx
            sess['next_due_at'] = time.time() + 10.0
            logger.info(f"early_advance: starter answered, moving to q={next_idx} session={session_key}")
            await send_quiz_question(None, context, quiz_id, chat_id, starter_id, next_idx)


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback handler"""
    track_update(update)
    await advance_due_sessions(context)
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    
    # ADMIN PANEL
    if data.startswith("admin_"):
        if not (is_admin_user(user_id) or is_sudo_user(user_id)):
            await query.answer("❌ Siz admin yoki sudo user emassiz.", show_alert=True)
            return

        if query.message.chat.type in ['group', 'supergroup']:
            await query.answer("Admin panel faqat shaxsiy chatda.", show_alert=True)
            return

        if data == "admin_menu":
            await show_admin_menu(query, context, as_edit=True)
            return

        if data == "admin_group_quiz":
            await _admin_gq_show_groups(query.message, context)
            return

        if data.startswith("admin_gq_select_"):
            gid = int(data.replace("admin_gq_select_", ""))
            await _admin_gq_show_group_menu(query.message, context, gid)
            return

        if data.startswith("admin_gq_list_"):
            parts = data.replace("admin_gq_list_", "").split("_")
            gid = int(parts[0])
            page = int(parts[1]) if len(parts) > 1 else 0
            await _admin_gq_show_allowed_list(query.message, context, gid, page)
            return

        if data.startswith("admin_gq_pick_"):
            parts = data.replace("admin_gq_pick_", "").split("_")
            gid = int(parts[0])
            page = int(parts[1]) if len(parts) > 1 else 0
            await _admin_gq_show_pick_latest(query.message, context, gid, page)
            return

        if data.startswith("admin_gq_addid_"):
            parts = data.replace("admin_gq_addid_", "").split("_", 1)
            gid = int(parts[0])
            quiz_id = parts[1]
            quiz = storage.get_quiz(quiz_id)
            if quiz:
                storage.add_group_allowed_quiz(gid, quiz_id)
                await query.answer(f"✅ Quiz qo'shildi: {quiz.get('title', quiz_id)[:20]}", show_alert=True)
            await _admin_gq_show_pick_latest(query.message, context, gid, 0)
            return

        if data.startswith("admin_gq_rm_"):
            parts = data.replace("admin_gq_rm_", "").split("_", 1)
            gid = int(parts[0])
            quiz_id = parts[1]
            storage.remove_group_allowed_quiz(gid, quiz_id)
            await query.answer("✅ Olib tashlandi")
            await _admin_gq_show_allowed_list(query.message, context, gid, 0)
            return

        if data.startswith("admin_gq_off_"):
            gid = int(data.replace("admin_gq_off_", ""))
            storage.set_group_allowed_quiz_ids(gid, [])
            await query.answer("✅ Filtr o'chirildi")
            await _admin_gq_show_group_menu(query.message, context, gid)
            return

        if data.startswith("admin_gq_add_"):
            gid = int(data.replace("admin_gq_add_", ""))
            context.user_data['admin_action'] = 'gq_add'
            context.user_data['admin_target_group_id'] = gid
            await safe_edit_text(
                query.message,
                "➕ **Quiz ID kiriting**\n\n"
                "Quiz ID yuboring (masalan: `b672034fe4b4`).\n"
                "Bekor qilish: `cancel`",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Orqaga", callback_data=f"admin_gq_select_{gid}")]]),
                parse_mode=ParseMode.MARKDOWN
            )
            return

        # Admin panel asosiy tugmalar
        if data == "admin_quizzes":
            from bot.handlers.admin import admin_quizzes_command
            class FakeUpdate:
                def __init__(self, q):
                    self.message = q.message
                    self.effective_user = q.from_user
                    self.effective_chat = q.message.chat
            fake_update = FakeUpdate(query)
            await admin_quizzes_command(fake_update, context)
            return

        if data == "admin_stats":
            from bot.handlers.admin import admin_stats_command
            class FakeUpdate:
                def __init__(self, q):
                    self.message = q.message
                    self.effective_user = q.from_user
                    self.effective_chat = q.message.chat
            fake_update = FakeUpdate(query)
            await admin_stats_command(fake_update, context)
            return

        if data == "admin_users":
            from bot.handlers.admin import admin_users_command
            class FakeUpdate:
                def __init__(self, q):
                    self.message = q.message
                    self.effective_user = q.from_user
                    self.effective_chat = q.message.chat if q.message else None
                    self.effective_message = q.message
            try:
                fake_update = FakeUpdate(query)
                await admin_users_command(fake_update, context, page=0)
            except Exception as e:
                logger.error(f"admin_users_command error: {e}", exc_info=True)
                # Fallback: to'g'ridan-to'g'ri edit qilish
                users = storage.get_users()
                text = "👤 **Bot foydalanuvchilari (oxirgilar):**\n\n"
                if not users:
                    text += "Hali userlar yo'q."
                else:
                    for u in users[:15]:
                        uname = f"@{u.get('username')}" if u.get('username') else "-"
                        last_seen = u.get('last_seen', '')[:19] if u.get('last_seen') else '-'
                        text += f"- `{u.get('user_id')}` {uname} — {u.get('first_name') or ''} (last: {last_seen})\n"
                keyboard = [[InlineKeyboardButton("⬅️ Admin", callback_data="admin_menu")]]
                await safe_edit_text(query.message, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
            return

        # Users pagination
        if data.startswith("admin_users_page_"):
            page = int(data.replace("admin_users_page_", ""))
            from bot.handlers.admin import admin_users_command
            class FakeUpdate:
                def __init__(self, q):
                    self.message = q.message
                    self.effective_user = q.from_user
                    self.effective_chat = q.message.chat if q.message else None
                    self.effective_message = q.message
            try:
                fake_update = FakeUpdate(query)
                await admin_users_command(fake_update, context, page=page)
            except Exception as e:
                logger.error(f"admin_users_command pagination error: {e}", exc_info=True)
                await query.answer("❌ Xatolik yuz berdi.", show_alert=True)
            return

        if data == "admin_groups":
            from bot.handlers.admin import admin_groups_command
            class FakeUpdate:
                def __init__(self, q):
                    self.message = q.message
                    self.effective_user = q.from_user
                    self.effective_chat = q.message.chat
            fake_update = FakeUpdate(query)
            await admin_groups_command(fake_update, context)
            return

        if data == "admin_broadcast":
            from bot.handlers.admin import admin_broadcast_command
            class FakeUpdate:
                def __init__(self, q):
                    self.message = q.message
                    self.effective_user = q.from_user
                    self.effective_chat = q.message.chat
            fake_update = FakeUpdate(query)
            await admin_broadcast_command(fake_update, context)
            return

        if data == "admin_cleanup":
            from bot.handlers.admin import admin_cleanup_command
            class FakeUpdate:
                def __init__(self, q):
                    self.message = q.message
                    self.effective_user = q.from_user
                    self.effective_chat = q.message.chat
            fake_update = FakeUpdate(query)
            await admin_cleanup_command(fake_update, context)
            return

        if data == "admin_sudo":
            from bot.handlers.admin import admin_sudo_command
            class FakeUpdate:
                def __init__(self, q):
                    self.message = q.message
                    self.effective_user = q.from_user
                    self.effective_chat = q.message.chat
            fake_update = FakeUpdate(query)
            await admin_sudo_command(fake_update, context)
            return

        if data == "admin_vip":
            from bot.handlers.admin import admin_vip_command
            class FakeUpdate:
                def __init__(self, q):
                    self.message = q.message
                    self.effective_user = q.from_user
                    self.effective_chat = q.message.chat
            fake_update = FakeUpdate(query)
            await admin_vip_command(fake_update, context)
            return

        if data == "admin_channels":
            from bot.handlers.admin import admin_channels_command
            class FakeUpdate:
                def __init__(self, q):
                    self.message = q.message
                    self.effective_user = q.from_user
                    self.effective_chat = q.message.chat
            fake_update = FakeUpdate(query)
            await admin_channels_command(fake_update, context)
            return

        if data == "admin_channel_add":
            await query.answer("📢 Kanal ID yoki username yuboring.")
            context.user_data['admin_action'] = 'add_channel'
            await query.message.reply_text(
                "📢 **Kanal qo'shish**\n\n"
                "Kanal ID yoki username yuboring:\n"
                "• Kanal ID: `-1001234567890`\n"
                "• Username: `@channel_username`\n\n"
                "Bekor qilish: `/cancel`",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        if data == "admin_channel_remove":
            channels = storage.get_required_channels()
            if not channels:
                await query.answer("📭 Kanallar yo'q.", show_alert=True)
                return
            
            text = "➖ **Kanal o'chirish**\n\n"
            text += "O'chirish uchun kanal ID ni tanlang:\n\n"
            
            keyboard = []
            for ch in channels:
                ch_id = ch.get('channel_id')
                ch_username = ch.get('channel_username', '')
                ch_title = ch.get('channel_title', '')
                ch_name = ch_title or ch_username or f"Channel {ch_id}"
                keyboard.append([InlineKeyboardButton(
                    f"➖ {ch_name}",
                    callback_data=f"remove_channel_{ch_id}"
                )])
            
            keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="admin_channels")])
            
            await safe_edit_text(query.message, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("remove_channel_"):
            channel_id = int(data.replace("remove_channel_", ""))
            success = storage.remove_required_channel(channel_id)
            
            if success:
                await query.answer("✅ Kanal o'chirildi.")
                from bot.handlers.admin import admin_channels_command
                class FakeUpdate:
                    def __init__(self, q):
                        self.message = q.message
                        self.effective_user = q.from_user
                        self.effective_chat = q.message.chat
                fake_update = FakeUpdate(query)
                await admin_channels_command(fake_update, context)
            else:
                await query.answer("❌ Kanal topilmadi.", show_alert=True)
            return

        if data == "admin_create_quiz":
            from bot.handlers.admin import admin_create_quiz_command
            class FakeUpdate:
                def __init__(self, q):
                    self.message = q.message
                    self.effective_user = q.from_user
                    self.effective_chat = q.message.chat
            fake_update = FakeUpdate(query)
            await admin_create_quiz_command(fake_update, context)
            return

        if data == "admin_group_quiz":
            await _admin_gq_show_groups(query.message, context)
            return

        if data == "admin_broadcast_users":
            context.user_data['admin_action'] = 'broadcast_users'
            await safe_edit_text(
                query.message,
                "📨 **Users ga yuborish**\n\n"
                "Yuboriladigan xabarni yuboring.\n"
                "Bekor qilish: `cancel`",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Admin", callback_data="admin_menu")]]),
                parse_mode=ParseMode.MARKDOWN
            )
            return

        if data == "admin_broadcast_groups":
            context.user_data['admin_action'] = 'broadcast_groups'
            await safe_edit_text(
                query.message,
                "👥 **Guruhlarga yuborish**\n\n"
                "Yuboriladigan xabarni yuboring.\n"
                "Bekor qilish: `cancel`",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Admin", callback_data="admin_menu")]]),
                parse_mode=ParseMode.MARKDOWN
            )
            return

        if data == "admin_create_quiz_file":
            context.user_data['admin_action'] = 'create_quiz_file'
            await safe_edit_text(
                query.message,
                "📄 **Fayl yuborish**\n\n"
                "Quiz yaratish uchun fayl yuboring:\n"
                "• TXT, DOCX, PDF formatlarida\n"
                "• Faylda test savollari bo'lishi kerak\n\n"
                "Faylni yuboring:",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Admin", callback_data="admin_menu")]]),
                parse_mode=ParseMode.MARKDOWN
            )
            return

        if data == "admin_create_quiz_topic":
            context.user_data['admin_action'] = 'create_quiz_topic'
            await safe_edit_text(
                query.message,
                "💬 **Mavzu aytish**\n\n"
                "Quiz yaratish uchun mavzuni yuboring.\n"
                "Masalan: \"Matematika - Algebra\", \"Tarix - O'rta asrlar\" va hokazo.\n\n"
                "Mavzuni yuboring:",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Admin", callback_data="admin_menu")]]),
                parse_mode=ParseMode.MARKDOWN
            )
            return

        # Broadcast tasdiqlash
        if data.startswith("admin_broadcast_yes_"):
            admin_action = data.replace("admin_broadcast_yes_", "")
            pending_text = context.user_data.get('admin_pending_text')
            logger.info(f"Broadcast yes clicked: action={admin_action}, has_text={bool(pending_text)}")
            if not pending_text:
                await query.answer("❌ Xabar topilmadi. Qayta urinib ko'ring.", show_alert=True)
                # Admin action ni o'chirish
                context.user_data.pop('admin_action', None)
                return
            
            await query.answer("🚀 Yuborish boshlandi...")
            
            # Xabarni o'chirish (agar mavjud bo'lsa)
            try:
                if query.message:
                    await query.message.delete()
            except Exception as e:
                logger.warning(f"Message delete failed: {e}")
            
            # Chat ID ni olish
            chat_id = query.message.chat.id if query.message and query.message.chat else query.from_user.id
            
            sent = 0
            failed = 0
            logger.info(f"Broadcast starting: action={admin_action}, text_length={len(pending_text) if pending_text else 0}")
            
            if admin_action == "broadcast_users":
                users = storage.get_users()
                targets = [int(u['user_id']) for u in users if u.get('last_chat_type') == 'private'][:2000]
                logger.info(f"Broadcast users: found {len(users)} total users, {len(targets)} private users")
            else:
                bot_id = context.bot.id
                groups = storage.get_groups()
                targets = []
                for g in groups:
                    gid = int(g['chat_id'])
                    try:
                        m = await context.bot.get_chat_member(gid, bot_id)
                        if m.status in ['administrator', 'creator']:
                            targets.append(gid)
                    except Exception as e:
                        logger.debug(f"Group {gid} check failed: {e}")
                        continue
                targets = targets[:500]
                logger.info(f"Broadcast groups: found {len(groups)} total groups, {len(targets)} valid groups")

            if not targets:
                await query.answer("❌ Hech qanday target topilmadi.", show_alert=True)
                context.user_data.pop('admin_action', None)
                context.user_data.pop('admin_pending_text', None)
                return

            status_msg = await context.bot.send_message(
                chat_id=chat_id,
                text=f"🚀 Yuborish boshlandi... target: {len(targets)} ta\n\n⏳ Kuting..."
            )
            
            # Background task sifatida yuborish
            async def send_broadcast():
                task_sent = 0
                task_failed = 0
                for i, tid in enumerate(targets):
                    try:
                        await context.bot.send_message(chat_id=tid, text=pending_text)
                        task_sent += 1
                        # Har 10 ta yuborilgandan keyin status yangilash
                        if (i + 1) % 10 == 0:
                            try:
                                await status_msg.edit_text(
                                    f"🚀 Yuborilmoqda...\n\n✅ Yuborildi: {task_sent}/{len(targets)}\n❌ Xatolik: {task_failed}"
                                )
                            except Exception as e:
                                logger.debug(f"Status message edit xatolik (broadcast): {e}")
                    except Exception as e:
                        logger.warning(f"Broadcast failed for {tid}: {e}")
                        task_failed += 1
                    await asyncio.sleep(0.05)  # Rate limit uchun
                
                # Yakuniy natija
                context.user_data.pop('admin_action', None)
                context.user_data.pop('admin_pending_text', None)
                keyboard = [[KeyboardButton("⬅️ Orqaga")]]
                markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                
                try:
                    await status_msg.edit_text(
                        f"✅ **Yakunlandi**\n\n✅ Yuborildi: **{task_sent}**\n❌ Xatolik: **{task_failed}**\n📊 Jami: **{len(targets)}** ta",
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception as e:
                    logger.warning(f"Status message edit failed: {e}")
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"✅ **Yakunlandi**\n\n✅ Yuborildi: **{task_sent}**\n❌ Xatolik: **{task_failed}**\n📊 Jami: **{len(targets)}** ta",
                        reply_markup=markup,
                        parse_mode=ParseMode.MARKDOWN
                    )
            
            # Background taskni ishga tushirish
            asyncio.create_task(send_broadcast())
            return

        # Other admin actions
        await query.answer("ℹ️ Bu funksiya hali ishlanmoqda")
        return

    # PAGINATION
    if data.startswith("page_myquizzes_"):
        page = int(data.replace("page_myquizzes_", ""))
        from bot.handlers.quiz import myquizzes_command
        # Emulate update for pagination
        class FakeUpdate:
            def __init__(self, q):
                self.message = q.message
                self.effective_user = q.from_user
                self.effective_chat = q.message.chat
        fake_update = FakeUpdate(query)
        await myquizzes_command(fake_update, context, page=page)
        return

    if data.startswith("page_quizzes_"):
        page = int(data.replace("page_quizzes_", ""))
        from bot.handlers.quiz import quizzes_command
        class FakeUpdate:
            def __init__(self, q):
                self.message = q.message
                self.effective_user = q.from_user
                self.effective_chat = q.message.chat
        fake_update = FakeUpdate(query)
        await quizzes_command(fake_update, context, page=page)
        return

    # QUIZ MENU
    if data.startswith("quiz_menu_"):
        quiz_id = data.replace("quiz_menu_", "")
        quiz = storage.get_quiz(quiz_id)
        if not quiz:
            await query.answer("❌ Quiz topilmadi.", show_alert=True)
            return

        title = quiz.get('title', 'Quiz')
        count = len(quiz.get('questions', []))
        creator_id = quiz.get('created_by')
        
        is_owner = (creator_id == user_id)
        is_admin = is_admin_user(user_id)

        is_private = quiz.get('is_private', False)
        private_status = "🔒 Private" if is_private else "🌐 Public"
        
        keyboard = [
            [InlineKeyboardButton("🚀 Boshlash", callback_data=f"select_time_{quiz_id}")],
            [InlineKeyboardButton("📊 Ma'lumot", callback_data=f"quiz_info_{quiz_id}")],
            [InlineKeyboardButton("📤 Ulashish", callback_data=f"share_quiz_{quiz_id}")]
        ]

        if is_owner or is_admin:
            keyboard.append([InlineKeyboardButton("✏️ Qayta nomlash", callback_data=f"rename_quiz_{quiz_id}")])
            keyboard.append([InlineKeyboardButton(f"{private_status}", callback_data=f"toggle_private_{quiz_id}")])
            if is_private:
                keyboard.append([InlineKeyboardButton("👥 Guruhlar", callback_data=f"quiz_groups_{quiz_id}")])
            keyboard.append([InlineKeyboardButton("❌ O'chirish", callback_data=f"delete_{quiz_id}")])

        private_status_text = "🔒 Private" if is_private else "🌐 Public"
        await safe_edit_text(
            query.message,
            f"📝 **{title}**\n\n📊 Savollar: {count}\n🆔 ID: `{quiz_id}`\n{private_status_text}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # TOGGLE PRIVATE
    if data.startswith("toggle_private_"):
        quiz_id = data.replace("toggle_private_", "")
        quiz = storage.get_quiz(quiz_id)
        if not quiz:
            await query.answer("❌ Quiz topilmadi.", show_alert=True)
            return
        
        creator_id = quiz.get('created_by')
        is_owner = (creator_id == user_id)
        is_admin = is_admin_user(user_id)
        
        if not (is_owner or is_admin):
            await query.answer("❌ Siz bu quizni o'zgartira olmaysiz.", show_alert=True)
            return
        
        current_private = quiz.get('is_private', False)
        new_private = not current_private
        
        storage.set_quiz_private(quiz_id, new_private)
        
        status_text = "🔒 Private" if new_private else "🌐 Public"
        await query.answer(f"✅ Quiz {status_text} qilindi!")
        
        # Qayta ko'rsatish
        title = quiz.get('title', 'Quiz')
        count = len(quiz.get('questions', []))
        
        keyboard = [
            [InlineKeyboardButton("🚀 Boshlash", callback_data=f"select_time_{quiz_id}")],
            [InlineKeyboardButton("📊 Ma'lumot", callback_data=f"quiz_info_{quiz_id}")],
            [InlineKeyboardButton("📤 Ulashish", callback_data=f"share_quiz_{quiz_id}")]
        ]
        
        if is_owner or is_admin:
            keyboard.append([InlineKeyboardButton("✏️ Qayta nomlash", callback_data=f"rename_quiz_{quiz_id}")])
            keyboard.append([InlineKeyboardButton(f"{status_text}", callback_data=f"toggle_private_{quiz_id}")])
            if new_private:
                keyboard.append([InlineKeyboardButton("👥 Guruhlar", callback_data=f"quiz_groups_{quiz_id}")])
            keyboard.append([InlineKeyboardButton("❌ O'chirish", callback_data=f"delete_{quiz_id}")])
        
        await safe_edit_text(
            query.message,
            f"📝 **{title}**\n\n📊 Savollar: {count}\n🆔 ID: `{quiz_id}`\n{status_text}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # QUIZ GROUPS (Private quiz uchun guruhlar ro'yxati)
    if data.startswith("quiz_groups_"):
        quiz_id = data.replace("quiz_groups_", "")
        quiz = storage.get_quiz(quiz_id)
        if not quiz:
            await query.answer("❌ Quiz topilmadi.", show_alert=True)
            return
        
        creator_id = quiz.get('created_by')
        is_owner = (creator_id == user_id)
        is_admin = is_admin_user(user_id)
        
        if not (is_owner or is_admin):
            await query.answer("❌ Siz bu quizni o'zgartira olmaysiz.", show_alert=True)
            return
        
        if not quiz.get('is_private', False):
            await query.answer("❌ Bu quiz private emas!", show_alert=True)
            return
        
        allowed_groups = storage.get_quiz_allowed_groups(quiz_id)
        title = quiz.get('title', 'Quiz')
        
        text = f"👥 **Guruhlar ro'yxati**\n\n"
        text += f"📝 Quiz: {title}\n"
        text += f"🔒 Status: Private\n\n"
        
        keyboard = []  # Keyboard har doim yaratilishi kerak
        
        if allowed_groups:
            text += "✅ Ruxsat berilgan guruhlar:\n\n"
            for group_id in allowed_groups[:10]:  # Maksimum 10 ta
                try:
                    chat = await context.bot.get_chat(group_id)
                    group_name = chat.title or f"Group {group_id}"
                    keyboard.append([InlineKeyboardButton(
                        f"❌ {group_name}",
                        callback_data=f"quiz_remove_group_{quiz_id}_{group_id}"
                    )])
                    text += f"• {group_name}\n"
                except Exception as e:
                    logger.debug(f"Guruh ma'lumotlarini olishda xatolik (group_id={group_id}): {e}")
                    text += f"• Group {group_id} (topilmadi)\n"
                    keyboard.append([InlineKeyboardButton(
                        f"❌ Group {group_id}",
                        callback_data=f"quiz_remove_group_{quiz_id}_{group_id}"
                    )])
        else:
            text += "ℹ️ Hozircha ruxsat berilgan guruhlar yo'q.\n\n"
            text += "Guruh ID sini yuboring (masalan: -1001234567890)"
        
        keyboard.append([InlineKeyboardButton("➕ Guruh qo'shish", callback_data=f"quiz_add_group_{quiz_id}")])
        keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data=f"quiz_menu_{quiz_id}")])
        
        await safe_edit_text(
            query.message,
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    if data.startswith("quiz_add_group_"):
        quiz_id = data.replace("quiz_add_group_", "")
        quiz = storage.get_quiz(quiz_id)
        if not quiz:
            await query.answer("❌ Quiz topilmadi.", show_alert=True)
            return
        
        creator_id = quiz.get('created_by')
        is_owner = (creator_id == user_id)
        is_admin = is_admin_user(user_id)
        
        if not (is_owner or is_admin):
            await query.answer("❌ Siz bu quizni o'zgartira olmaysiz.", show_alert=True)
            return
        
        context.user_data['quiz_add_group_action'] = quiz_id
        
        await query.answer("📝 Guruh ID yoki username yuboring")
        await safe_edit_text(
            query.message,
            "👥 **Guruh qo'shish**\n\n"
            "Guruh ID yoki username'ni yuboring:\n"
            "• Format: `-1001234567890` (ID)\n"
            "• Yoki: `@guruh_username` (username)\n"
            "• Yoki bekor qilish: `cancel`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Orqaga", callback_data=f"quiz_groups_{quiz_id}")]]),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    if data.startswith("quiz_remove_group_"):
        parts = data.replace("quiz_remove_group_", "").split("_")
        quiz_id = parts[0]
        group_id = int(parts[1])
        
        quiz = storage.get_quiz(quiz_id)
        if not quiz:
            await query.answer("❌ Quiz topilmadi.", show_alert=True)
            return
        
        creator_id = quiz.get('created_by')
        is_owner = (creator_id == user_id)
        is_admin = is_admin_user(user_id)
        
        if not (is_owner or is_admin):
            await query.answer("❌ Siz bu quizni o'zgartira olmaysiz.", show_alert=True)
            return
        
        storage.remove_quiz_allowed_group(quiz_id, group_id)
        await query.answer("✅ Guruh olib tashlandi!")
        
        # Qayta ko'rsatish
        allowed_groups = storage.get_quiz_allowed_groups(quiz_id)
        title = quiz.get('title', 'Quiz')
        
        text = f"👥 **Guruhlar ro'yxati**\n\n"
        text += f"📝 Quiz: {title}\n"
        text += f"🔒 Status: Private\n\n"
        
        if allowed_groups:
            text += "✅ Ruxsat berilgan guruhlar:\n\n"
            keyboard = []
            for gid in allowed_groups[:10]:
                try:
                    chat = await context.bot.get_chat(gid)
                    group_name = chat.title or f"Group {gid}"
                    keyboard.append([InlineKeyboardButton(
                        f"❌ {group_name}",
                        callback_data=f"quiz_remove_group_{quiz_id}_{gid}"
                    )])
                    text += f"• {group_name}\n"
                except Exception as e:
                    logger.debug(f"Guruh ma'lumotlarini olishda xatolik (group_id={gid}): {e}")
                    text += f"• Group {gid} (topilmadi)\n"
                    keyboard.append([InlineKeyboardButton(
                        f"❌ Group {gid}",
                        callback_data=f"quiz_remove_group_{quiz_id}_{gid}"
                    )])
        else:
            text += "ℹ️ Hozircha ruxsat berilgan guruhlar yo'q.\n\n"
            text += "Guruh ID sini yuboring (masalan: -1001234567890)"
        
        keyboard.append([InlineKeyboardButton("➕ Guruh qo'shish", callback_data=f"quiz_add_group_{quiz_id}")])
        keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data=f"quiz_menu_{quiz_id}")])
        
        await safe_edit_text(
            query.message,
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # SHARE QUIZ (eski format - faqat quiz_id, quiz menu dan)
    if data.startswith("share_quiz_") and data.count("_") == 1:
        # share_quiz_{quiz_id} format (eski)
        quiz_id = data.replace("share_quiz_", "")
        quiz = storage.get_quiz(quiz_id)
        if not quiz:
            await query.answer("❌ Quiz topilmadi.", show_alert=True)
            return
        
        title = quiz.get('title', 'Quiz')
        count = len(quiz.get('questions', []))
        
        share_text = f"📝 **{title}**\n\n"
        share_text += f"📊 Savollar: {count} ta\n\n"
        share_text += f"Quizni boshlash uchun:\n"
        share_text += f"`/quiz {quiz_id}`"
        
        keyboard = [[InlineKeyboardButton("🚀 Quizni boshlash", callback_data=f"quiz_menu_{quiz_id}")]]
        
        await query.answer("📤 Quiz ulashildi!")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=share_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # QUIZ INFO
    if data.startswith("quiz_info_"):
        quiz_id = data.replace("quiz_info_", "")
        quiz = storage.get_quiz(quiz_id)
        if not quiz:
            await query.answer("❌ Quiz topilmadi.", show_alert=True)
            return

        title = quiz.get('title', 'Quiz')
        count = len(quiz.get('questions', []))
        created_by = quiz.get('created_by')
        created_at = str(quiz.get('created_at', ''))[:19].replace("T", " ")

        text = f"📊 **Quiz haqida**\n\n"
        text += f"🏷 Nomi: **{title}**\n"
        text += f"📝 Savollar: **{count}**\n"
        text += f"🆔 ID: `{quiz_id}`\n"
        text += f"👤 Creator: `{created_by}`\n"
        text += f"📅 Yaratilgan: {created_at}\n"

        keyboard = [[InlineKeyboardButton("⬅️ Orqaga", callback_data=f"quiz_menu_{quiz_id}")]]
        await safe_edit_text(query.message, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        return

    # DELETE QUIZ
    if data.startswith("delete_"):
        quiz_id = data.replace("delete_", "")
        quiz = storage.get_quiz(quiz_id)
        if not quiz:
            await query.answer("❌ Quiz topilmadi.", show_alert=True)
            return

        creator_id = quiz.get('created_by')
        if creator_id != user_id and not is_admin_user(user_id):
            await query.answer("❌ Siz bu quizni o'chira olmaysiz.", show_alert=True)
            return

        title = quiz.get('title') or quiz_id
        storage.delete_quiz(quiz_id)
        await safe_edit_text(
            query.message,
            f"✅ O'chirildi: **{title}**",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # RENAME QUIZ
    if data.startswith("rename_quiz_"):
        quiz_id = data.replace("rename_quiz_", "")
        quiz = storage.get_quiz(quiz_id)
        if not quiz:
            await query.answer("❌ Quiz topilmadi.", show_alert=True)
            return

        creator_id = quiz.get('created_by')
        if creator_id != user_id and not is_admin_user(user_id):
            await query.answer("❌ Siz bu quizni nomini o'zgartira olmaysiz.", show_alert=True)
            return

        # Set admin_action to wait for new title
        context.user_data['admin_action'] = 'rename_quiz'
        context.user_data['rename_quiz_id'] = quiz_id
        
        current_title = quiz.get('title', quiz_id)
        await safe_edit_text(
            query.message,
            f"✏️ **Quiz nomini o'zgartirish**\n\n"
            f"Joriy nom: **{current_title}**\n\n"
            f"Yangi nomni yuboring:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Bekor", callback_data=f"quiz_menu_{quiz_id}")]]),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # SELECT TIME
    if data.startswith("select_time_"):
        quiz_id = data.replace("select_time_", "")
        quiz = storage.get_quiz(quiz_id)
        if not quiz:
            await query.answer("❌ Quiz topilmadi.", show_alert=True)
            return

        title = quiz.get('title', 'Quiz')
        text = f"⏱ **Vaqt tanlang**\n\n📝 {title}\n\nHar bir savol uchun vaqt:"

        keyboard = []
        for label, seconds in TIME_OPTIONS.items():
            keyboard.append([InlineKeyboardButton(
                f"⏱ {label}",
                callback_data=f"start_{quiz_id}_{seconds}"
            )])
        keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data=f"quiz_menu_{quiz_id}")])

        await safe_edit_text(query.message, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        return

    # START GROUP WITH TIME (bu start_group_ dan oldin bo'lishi kerak!)
    if data.startswith("start_group_time_"):
        logger.info(f"📞 start_group_time_ callback: data={data}, chat_id={chat_id}, user_id={user_id}")
        try:
            # Remove prefix
            rest = data.replace("start_group_time_", "")
            # Split from right: last part is time_seconds, everything before is quiz_id
            # Quiz ID may contain underscores, so we split from right
            if "_" not in rest:
                logger.error(f"❌ start_group_time_ parse xatolik: no underscore in rest={rest}")
                await query.answer("❌ Xatolik: noto'g'ri format", show_alert=True)
                return
            
            # Split from right - last part is time_seconds
            parts = rest.rsplit("_", 1)
            if len(parts) != 2:
                logger.error(f"❌ start_group_time_ parse xatolik: parts={parts}, rest={rest}")
                await query.answer("❌ Xatolik: noto'g'ri format", show_alert=True)
                return
            
            quiz_id = parts[0]
            time_seconds = int(parts[1])
            
            logger.info(f"🚀 Guruhda quiz boshlash: quiz_id={quiz_id}, chat_id={chat_id}, user_id={user_id}, time={time_seconds}s")
            
            # Quiz mavjudligini tekshiramiz
            quiz = storage.get_quiz(quiz_id)
            if not quiz:
                logger.error(f"❌ Quiz topilmadi: {quiz_id}")
                await query.answer("❌ Quiz topilmadi", show_alert=True)
                return
            
            # Voting qo'shish (guruhda, lekin adminlar uchun emas)
            if query.message.chat.type in ['group', 'supergroup']:
                # Admin tekshiruvi
                is_admin = False
                try:
                    member = await context.bot.get_chat_member(chat_id, user_id)
                    is_admin = member.status in ['administrator', 'creator']
                except Exception:
                    pass
                
                # Agar admin bo'lsa, voting'siz to'g'ridan-to'g'ri boshlaymiz
                if not is_admin:
                    from bot.services.voting import create_start_voting
                    poll_id = await create_start_voting(context, chat_id, quiz_id, time_seconds, user_id)
                    if poll_id:
                        await query.answer("📊 Voting yaratildi! Ovoz bering...")
                        await query.message.delete()
                        return
                    # Agar voting yaratib bo'lmasa, to'g'ridan-to'g'ri boshlaymiz
                    logger.warning("Voting yaratib bo'lmadi, to'g'ridan-to'g'ri boshlaymiz")
                else:
                    logger.info(f"Admin {user_id} voting'siz quizni boshlayapti")
            
            await query.answer("🚀 Quiz boshlanmoqda...")
            await start_quiz_session(query.message, context, quiz_id, chat_id, user_id, time_seconds)
            logger.info(f"✅ Quiz sessiyasi boshlandi: quiz_id={quiz_id}, chat_id={chat_id}")
        except ValueError as e:
            logger.error(f"❌ start_group_time_ ValueError: {e}, data={data}")
            await query.answer(f"❌ Xatolik: noto'g'ri format", show_alert=True)
        except Exception as e:
            logger.error(f"❌ Quiz boshlashda xatolik: {e}", exc_info=True)
            await query.answer(f"❌ Xatolik: {str(e)[:50]}", show_alert=True)
        return

    # START QUIZ (private)
    if data.startswith("start_") and not data.startswith("start_group_"):
        parts = data.replace("start_", "").rsplit("_", 1)
        quiz_id = parts[0]
        time_seconds = int(parts[1])

        await start_quiz_session(query.message, context, quiz_id, chat_id, user_id, time_seconds)
        return

    # START QUIZ (group) - vaqt tanlash menyusini ko'rsatish
    if data.startswith("start_group_"):
        quiz_id = data.replace("start_group_", "")
        quiz = storage.get_quiz(quiz_id)
        if not quiz:
            await query.answer("❌ Quiz topilmadi.", show_alert=True)
            return

        title = quiz.get('title', 'Quiz')
        text = f"⏱ **Vaqt tanlang**\n\n📝 {title}\n\nHar bir savol uchun vaqt:"

        keyboard = []
        for label, seconds in TIME_OPTIONS.items():
            keyboard.append([InlineKeyboardButton(
                f"⏱ {label}",
                callback_data=f"start_group_time_{quiz_id}_{seconds}"
            )])

        await safe_edit_text(query.message, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        return

    # SHARE QUIZ TO FRIEND va JOIN QUIZ callback lari olib tashlandi (mutloq yaroqsiz)

    # RESTART QUIZ
    if data.startswith("restart_"):
        quiz_id = data.replace("restart_", "")
        quiz = storage.get_quiz(quiz_id)
        if not quiz:
            await query.answer("❌ Quiz topilmadi.", show_alert=True)
            return

        title = quiz.get('title', 'Quiz')
        text = f"🔄 **Qayta boshlash**\n\n📝 {title}\n\nVaqt tanlang:"

        keyboard = []
        for label, seconds in TIME_OPTIONS.items():
            # Guruhda bo'lsa, voting bilan boshlash uchun
            if query.message.chat.type in ['group', 'supergroup']:
                keyboard.append([InlineKeyboardButton(
                    f"⏱ {label}",
                    callback_data=f"start_group_time_{quiz_id}_{seconds}"
                )])
            else:
                keyboard.append([InlineKeyboardButton(
                    f"⏱ {label}",
                    callback_data=f"start_{quiz_id}_{seconds}"
                )])

        # Guruhda bo'lsa, yangi xabar yuborish (edit_text emas)
        if query.message.chat.type in ['group', 'supergroup']:
            try:
                await query.answer("🔄 Quiz qayta boshlanmoqda...")
                await query.message.reply_text(
                    text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as e:
                logger.error(f"Restart message send error: {e}")
                await query.answer("❌ Xatolik yuz berdi.", show_alert=True)
        else:
            await safe_edit_text(query.message, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        return

    # RESUME QUIZ (pauzadan keyin davom etish)
    if data.startswith("resume_"):
        quiz_id = data.replace("resume_", "")
        chat_id = query.message.chat.id
        user_id = query.from_user.id
        session_key = f"quiz_{chat_id}_{user_id}_{quiz_id}"
        
        if 'sessions' not in context.bot_data or session_key not in context.bot_data['sessions']:
            await query.answer("❌ Quiz topilmadi.", show_alert=True)
            return
        
        session = context.bot_data['sessions'][session_key]
        
        if not session.get('is_paused', False):
            await query.answer("ℹ️ Quiz pauzada emas.", show_alert=True)
            return
        
        if not session.get('is_active', False):
            await query.answer("❌ Quiz yakunlangan.", show_alert=True)
            return
        
        # 6 soat tekshiruvi (21600 sekund)
        import time
        current_time = time.time()
        paused_at = session.get('paused_at', 0)
        PAUSE_MAX_AGE = 6 * 60 * 60  # 6 soat
        
        if paused_at > 0 and (current_time - paused_at) > PAUSE_MAX_AGE:
            # 6 soatdan o'tgan, sesiya tozalanadi
            session['is_active'] = False
            session['is_paused'] = False
            await query.answer("❌ Quiz sesiyasi 6 soatdan o'tgan. Yangi quizni boshlang.", show_alert=True)
            return
        
        # Pauzani olib tashlash
        session['is_paused'] = False
        paused_at_question = session.get('paused_at_question', 0)
        session['consecutive_no_answers'] = 0  # Reset counter
        session.pop('paused_at', None)  # Pauza vaqtini olib tashlash
        
        # Keyingi savolga o'tish
        next_question = paused_at_question + 1
        
        await query.answer("▶️ Quiz davom etmoqda...")
        
        # Davom etish xabari
        try:
            await query.message.reply_text(
                "▶️ **Quiz davom etmoqda...**",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass
        
        # Keyingi savolni yuborish
        session['current_question'] = next_question
        await send_quiz_question(query.message, context, quiz_id, chat_id, user_id, next_question)
        return

    # CHECK SUBSCRIPTION (obuna tekshiruvi)
    if data == "check_subscription":
        from bot.handlers.start import start
        # Obunani tekshirish va start command'ni qayta ishlatish
        fake_update = type('FakeUpdate', (), {
            'message': query.message,
            'effective_user': query.from_user,
            'effective_chat': query.message.chat
        })()
        await query.answer("🔍 Obuna tekshirilmoqda...")
        await start(fake_update, context)
        return

    # GROUP QUIZZES PAGINATION
    if data.startswith("page_group_quizzes_"):
        parts = data.replace("page_group_quizzes_", "").split("_")
        group_chat_id = int(parts[0])
        page = int(parts[1])

        all_quizzes = storage.get_all_quizzes()
        allowed_ids = storage.get_group_allowed_quiz_ids(group_chat_id)
        if allowed_ids:
            allowed_set = set(allowed_ids)
            all_quizzes = [q for q in all_quizzes if str(q.get('quiz_id')) in allowed_set]

        QUIZZES_PER_PAGE = 10
        total_quizzes = len(all_quizzes)
        total_pages = (total_quizzes + QUIZZES_PER_PAGE - 1) // QUIZZES_PER_PAGE
        page = max(0, min(page, total_pages - 1))

        start_idx = page * QUIZZES_PER_PAGE
        end_idx = min(start_idx + QUIZZES_PER_PAGE, total_quizzes)
        page_quizzes = all_quizzes[start_idx:end_idx]

        text = ("📚 **Guruhda tanlangan quizlar:**\n\n" if allowed_ids else "📚 **Mavjud quizlar:**\n\n")
        if total_pages > 1:
            text += f"(Sahifa {page + 1}/{total_pages})\n\n"
        keyboard = []

        for i, quiz in enumerate(page_quizzes, 1):
            global_idx = start_idx + i
            count = len(quiz.get('questions', []))
            title = quiz.get('title', f"Quiz {global_idx}")[:20]
            text += f"{global_idx}. 📝 {title} ({count} savol)\n"

            keyboard.append([InlineKeyboardButton(
                f"🚀 {title} ({count} savol)",
                callback_data=f"start_group_{quiz['quiz_id']}"
            )])

        pagination_buttons = []
        if total_pages > 1:
            if page > 0:
                pagination_buttons.append(InlineKeyboardButton("⬅️ Oldingi", callback_data=f"page_group_quizzes_{group_chat_id}_{page - 1}"))
            if page < total_pages - 1:
                pagination_buttons.append(InlineKeyboardButton("Keyingi ➡️", callback_data=f"page_group_quizzes_{group_chat_id}_{page + 1}"))
            if pagination_buttons:
                keyboard.append(pagination_buttons)

        text += "\n🎯 Quizni tanlang!"

        await safe_edit_text(query.message, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        return

    # CHAMPIONSHIP
    if data.startswith("championship_start_"):
        group_chat_id = int(data.replace("championship_start_", ""))
        
        # Admin tekshiruvi
        try:
            member = await context.bot.get_chat_member(group_chat_id, user_id)
            if member.status not in ['administrator', 'creator']:
                await query.answer("❌ Faqat adminlar chempionat boshlay oladi!", show_alert=True)
                return
        except Exception:
            await query.answer("❌ Admin tekshiruvida xatolik!", show_alert=True)
            return
        
        # Chempionat aktivligini tekshirish
        championship_key = f"championship_{group_chat_id}"
        if 'championships' in context.bot_data and championship_key in context.bot_data['championships']:
            championship = context.bot_data['championships'][championship_key]
            if championship.get('is_active', False):
                await query.answer("❌ Guruhda allaqachon aktiv chempionat bor!", show_alert=True)
                return
        
        # Quizlar ro'yxatini ko'rsatish (tanlash uchun - faqat bitta quiz)
        all_quizzes = storage.get_all_quizzes()
        allowed_ids = storage.get_group_allowed_quiz_ids(group_chat_id)
        if allowed_ids:
            allowed_set = set(allowed_ids)
            all_quizzes = [q for q in all_quizzes if str(q.get('quiz_id')) in allowed_set]
        
        if not all_quizzes:
            await query.answer("❌ Quizlar topilmadi!", show_alert=True)
            return
        
        text = "🏆 **Chempionat boshlash**\n\n"
        text += "Quyidagi quizlardan BIRTA quizni tanlang:\n\n"
        
        keyboard = []
        selected_quiz = context.user_data.get('championship_selected_quiz')
        
        for quiz in all_quizzes[:20]:  # Maksimum 20 ta quiz
            quiz_id = quiz['quiz_id']
            title = quiz.get('title', f"Quiz {quiz_id}")[:30]
            count = len(quiz.get('questions', []))
            is_selected = selected_quiz == quiz_id
            
            emoji = "✅" if is_selected else "☐"
            keyboard.append([InlineKeyboardButton(
                f"{emoji} {title} ({count} savol)",
                callback_data=f"championship_select_{group_chat_id}_{quiz_id}"
            )])
        
        if selected_quiz:
            keyboard.append([InlineKeyboardButton(
                f"⏱ Vaqtni tanlang",
                callback_data=f"championship_time_select_{group_chat_id}"
            )])
            keyboard.append([InlineKeyboardButton("🗑️ Tozalash", callback_data=f"championship_clear_{group_chat_id}")])
        
        keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data=f"page_group_quizzes_{group_chat_id}_0")])
        
        await safe_edit_text(query.message, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        return
    
    if data.startswith("championship_select_"):
        parts = data.replace("championship_select_", "").split("_", 1)
        group_chat_id = int(parts[0])
        quiz_id = parts[1]
        
        # Quizni tanlash (faqat bitta)
        context.user_data['championship_selected_quiz'] = quiz_id
        
        await query.answer("✅ Quiz tanlandi!")
        
        # Qayta ko'rsatish
        all_quizzes = storage.get_all_quizzes()
        allowed_ids = storage.get_group_allowed_quiz_ids(group_chat_id)
        if allowed_ids:
            allowed_set = set(allowed_ids)
            all_quizzes = [q for q in all_quizzes if str(q.get('quiz_id')) in allowed_set]
        
        text = "🏆 **Chempionat boshlash**\n\n"
        text += "Quyidagi quizlardan BIRTA quizni tanlang:\n\n"
        
        keyboard = []
        selected_quiz = context.user_data.get('championship_selected_quiz')
        
        for quiz in all_quizzes[:20]:
            quiz_id_item = quiz['quiz_id']
            title = quiz.get('title', f"Quiz {quiz_id_item}")[:30]
            count = len(quiz.get('questions', []))
            is_selected = selected_quiz == quiz_id_item
            
            emoji = "✅" if is_selected else "☐"
            keyboard.append([InlineKeyboardButton(
                f"{emoji} {title} ({count} savol)",
                callback_data=f"championship_select_{group_chat_id}_{quiz_id_item}"
            )])
        
        if selected_quiz:
            keyboard.append([InlineKeyboardButton(
                f"⏱ Vaqtni tanlang",
                callback_data=f"championship_time_select_{group_chat_id}"
            )])
            keyboard.append([InlineKeyboardButton("🗑️ Tozalash", callback_data=f"championship_clear_{group_chat_id}")])
        
        keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data=f"page_group_quizzes_{group_chat_id}_0")])
        
        await safe_edit_text(query.message, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        return
    
    if data.startswith("championship_time_select_"):
        group_chat_id = int(data.replace("championship_time_select_", ""))
        selected_quiz = context.user_data.get('championship_selected_quiz')
        
        if not selected_quiz:
            await query.answer("❌ Avval quizni tanlang!", show_alert=True)
            return
        
        # Vaqt tanlash
        text = "⏱ **Vaqt tanlang**\n\nHar bir savol uchun vaqt:"
        keyboard = []
        for label, seconds in TIME_OPTIONS.items():
            keyboard.append([InlineKeyboardButton(
                f"⏱ {label}",
                callback_data=f"championship_time_{group_chat_id}_{seconds}"
            )])
        
        keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data=f"championship_start_{group_chat_id}")])
        
        await safe_edit_text(query.message, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        return
    
    if data.startswith("championship_time_"):
        parts = data.replace("championship_time_", "").split("_")
        group_chat_id = int(parts[0])
        time_seconds = int(parts[1])
        selected_quiz = context.user_data.get('championship_selected_quiz')
        
        if not selected_quiz:
            await query.answer("❌ Avval quizni tanlang!", show_alert=True)
            return
        
        # Boshlanish vaqtini so'rash
        text = "📅 **Boshlanish vaqtini tanlang**\n\n"
        text += "Chempionat qachon boshlansin?\n\n"
        text += "⚠️ **Eslatma:** Chempionat vaqtida guruhda boshqa quizlar o'tkazilmaydi!"
        
        keyboard = [
            [InlineKeyboardButton("🚀 Hozir boshlash", callback_data=f"championship_start_now_{group_chat_id}_{time_seconds}")],
            [InlineKeyboardButton("⏰ Vaqt belgilash", callback_data=f"championship_schedule_{group_chat_id}_{time_seconds}")],
            [InlineKeyboardButton("⬅️ Orqaga", callback_data=f"championship_time_select_{group_chat_id}")]
        ]
        
        await safe_edit_text(query.message, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        return
    
    if data.startswith("championship_start_now_"):
        parts = data.replace("championship_start_now_", "").split("_")
        group_chat_id = int(parts[0])
        time_seconds = int(parts[1])
        selected_quiz = context.user_data.get('championship_selected_quiz')
        
        if not selected_quiz:
            await query.answer("❌ Avval quizni tanlang!", show_alert=True)
            return
        
        # Chempionatni hozir boshlash
        from bot.services.championship import start_championship
        success = await start_championship(context, group_chat_id, [selected_quiz], user_id, time_seconds, start_time=None)
        
        if success:
            await query.answer("🏆 Chempionat boshlanmoqda...")
            await query.message.delete()
            context.user_data.pop('championship_selected_quiz', None)
        else:
            await query.answer("❌ Chempionatni boshlashda xatolik!", show_alert=True)
        return
    
    if data.startswith("championship_schedule_"):
        parts = data.replace("championship_schedule_", "").split("_")
        group_chat_id = int(parts[0])
        time_seconds = int(parts[1])
        selected_quiz = context.user_data.get('championship_selected_quiz')
        
        if not selected_quiz:
            await query.answer("❌ Avval quizni tanlang!", show_alert=True)
            return
        
        # Vaqt belgilash uchun matn so'rash
        context.user_data['championship_action'] = 'schedule'
        context.user_data['championship_group_id'] = group_chat_id
        context.user_data['championship_time_seconds'] = time_seconds
        context.user_data['championship_quiz_id'] = selected_quiz
        
        text = "📅 **Boshlanish vaqtini kiriting**\n\n"
        text += "Format: `DD.MM.YYYY HH:MM`\n"
        text += "Masalan: `05.01.2026 15:30`\n\n"
        text += "Yoki bekor qilish: `cancel`"
        
        keyboard = [[InlineKeyboardButton("⬅️ Orqaga", callback_data=f"championship_time_{group_chat_id}_{time_seconds}")]]
        
        await safe_edit_text(query.message, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        return
    
    if data.startswith("championship_clear_"):
        context.user_data.pop('championship_selected_quiz', None)
        await query.answer("✅ Tozalandi")
        # Qayta ko'rsatish
        group_chat_id = int(data.replace("championship_clear_", ""))
        all_quizzes = storage.get_all_quizzes()
        allowed_ids = storage.get_group_allowed_quiz_ids(group_chat_id)
        if allowed_ids:
            allowed_set = set(allowed_ids)
            all_quizzes = [q for q in all_quizzes if str(q.get('quiz_id')) in allowed_set]
        
        text = "🏆 **Chempionat boshlash**\n\n"
        text += "Quyidagi quizlardan BIRTA quizni tanlang:\n\n"
        
        keyboard = []
        for quiz in all_quizzes[:20]:
            quiz_id = quiz['quiz_id']
            title = quiz.get('title', f"Quiz {quiz_id}")[:30]
            count = len(quiz.get('questions', []))
            keyboard.append([InlineKeyboardButton(
                f"☐ {title} ({count} savol)",
                callback_data=f"championship_select_{group_chat_id}_{quiz_id}"
            )])
        
        keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data=f"page_group_quizzes_{group_chat_id}_0")])
        
        await safe_edit_text(query.message, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        return

    await query.answer("ℹ️ Noma'lum buyruq")

