import os
import logging
import asyncpg
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ParseMode

# --- НАСТРОЙКА ЛОГИРОВАНИЯ ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", 0)) if os.getenv("ADMIN_CHAT_ID") else None

# ID топика «Пользователи без админа»
UNASSIGNED_TOPIC_ID = 765

OWNER_ID = 8674242517

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

db_pool = None

# --- СОСТОЯНИЯ ДЛЯ FSM ---
class ChangeAdminState(StatesGroup):
    waiting_for_reason = State()

# --- ИНИЦИАЛИЗАЦИЯ БАЗЫ ---
async def init_db():
    global db_pool
    if not DATABASE_URL:
        return
    try:
        db_pool = await asyncpg.create_pool(DATABASE_URL)
        async with db_pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, username TEXT, role TEXT DEFAULT 'user', is_banned BOOLEAN DEFAULT FALSE, topic_id INT, rest_until TIMESTAMP);
                CREATE TABLE IF NOT EXISTS messages (id SERIAL PRIMARY KEY, user_id BIGINT, sender_type TEXT, user_msg_id INT, admin_msg_id INT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS admin_actions (id SERIAL PRIMARY KEY, admin_id BIGINT, admin_username TEXT, target_user_id BIGINT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
            """)
    except Exception as e:
        logger.error(f"Ошибка БД: {e}")

# --- ФУНКЦИИ ПРОВЕРКИ РОЛЕЙ ---
async def get_user_role(user_id: int) -> str:
    if user_id == OWNER_ID:
        return "owner"
    if not db_pool:
        return "user"
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT role, rest_until FROM users WHERE user_id = $1;", user_id)
            if not row:
                return "user"
            if row["rest_until"] and row["rest_until"] > datetime.now():
                return "user"
            return row["role"] or "user"
    except:
        return "user"

async def is_admin(user_id: int) -> bool:
    role = await get_user_role(user_id)
    return str(role).lower() in ["owner", "director", "admin", "intern"]

async def is_director_or_owner(user_id: int) -> bool:
    role = await get_user_role(user_id)
    return str(role).lower() in ["owner", "director"]

async def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID or (await get_user_role(user_id)) == "owner"

# --- ПОИСК ПОЛЬЗОВАТЕЛЯ ДЛЯ КОМАНД ---
async def get_target_user_id(conn, arg: str) -> int:
    arg = arg.strip()
    if arg.isdigit():
        return int(arg)
    if arg.startswith("@"):
        arg = arg[1:]
    row = await conn.fetchrow("SELECT user_id FROM users WHERE LOWER(username) = LOWER($1);", arg)
    return row["user_id"] if row else None

# --- КОМАНДА /START ---
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    role = "owner" if message.from_user.id == OWNER_ID else "user"
    if db_pool:
        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO users (user_id, username, role) 
                VALUES ($1, $2, $3)
                ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username;
            """, message.from_user.id, message.from_user.username, role)
            
    start_text = (
        "приветствую путник ты попал в прекрасный бот под названием \"вечернее сияние\".\n"
        "перед тем как начать общение, прошу заглянуть в наш тгк: https://t.me/eve_ning_glow\n"
        "там вся важная информация.\n"
        "Прочитал? тогда пиши \"привет общение/поддержка/уни\" и к тебе придет админ.\n\n"
        "🔄 Чтобы запросить смену администратора, отправьте команду: /change_admin"
    )
    await message.reply(start_text, disable_web_page_preview=False)

# --- КОМАНДА /HELP ---
@dp.message(Command("help"))
async def help_cmd(message: types.Message):
    text = (
        "📌 <b>Список доступных команд:</b>\n\n"
        "👑 <b>Владелец:</b>\n"
        "├ /stats — Статистика бота\n"
        "├ /adminstats (или .астат) — Статистика взятых ПЗ\n"
        "├ /check или .чек — Проверить пользователя\n"
        "├ /ban /unban [ID] — Управление банами\n"
        "├ /broadcast [текст] — Рассылка\n"
        "├ /rest [юз/ID] [дни] — Отправить в отпуск\n"
        "├ .ид юз — Узнать ID пользователя\n"
        "├ /setdirector [ID] — Назначить директора\n"
        "├ /setadmin [ID] — Назначить администратора\n"
        "├ /setintern [ID] — Назначить стажёра\n"
        "├ /demote [ID] — Понизить до пользователя\n"
        "└ /setowner — Подтвердить права Владельца"
    )
    await message.reply(text, parse_mode=ParseMode.HTML)

# --- ДОПОЛНИТЕЛЬНЫЕ КОМАНДЫ ДЛЯ АДМИНИСТРАЦИИ И ВЛАДЕЛЬЦА ---

@dp.message(Command("stats"))
async def stats_cmd(message: types.Message):
    if not await is_admin(message.from_user.id):
        return
    if not db_pool:
        await message.reply("База данных недоступна.")
        return
    
    async with db_pool.acquire() as conn:
        users_count = await conn.fetchval("SELECT COUNT(*) FROM users;")
        banned_count = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_banned = TRUE;")
        active_count = users_count - banned_count
        
        owner_count = await conn.fetchval("SELECT COUNT(*) FROM users WHERE role = 'owner' OR user_id = $1;", OWNER_ID)
        director_count = await conn.fetchval("SELECT COUNT(*) FROM users WHERE role = 'director';")
        admin_count = await conn.fetchval("SELECT COUNT(*) FROM users WHERE role = 'admin';")
        intern_count = await conn.fetchval("SELECT COUNT(*) FROM users WHERE role = 'intern';")
        user_role_count = await conn.fetchval("SELECT COUNT(*) FROM users WHERE role = 'user' OR role IS NULL;")
        
        user_msgs = await conn.fetchval("SELECT COUNT(*) FROM messages WHERE sender_type = 'user';")
        admin_msgs = await conn.fetchval("SELECT COUNT(*) FROM messages WHERE sender_type = 'admin';")
        total_msgs = user_msgs + admin_msgs

    text = (
        "📊 <b>Полная статистика бота:</b>\n\n"
        "👥 <b>Пользователи:</b>\n"
        f"├ Всего пользователей: {users_count}\n"
        f"├ 🍏 Активных (чистых): {active_count}\n"
        f"└ 🚫 Забаненных: {banned_count}\n\n"
        "🎭 <b>Разделение по ролям:</b>\n"
        f"├ 👑 Владелец: {owner_count}\n"
        f"├ 💼 Директоров: {director_count}\n"
        f"├ 🛡 Администраторов: {admin_count}\n"
        f"├ 🔰 Стажёров: {intern_count}\n"
        f"└ 👤 Пользователей: {user_role_count}\n\n"
        "✉️ <b>Сообщения и активность:</b>\n"
        f"├ 📩 От пользователей: {user_msgs}\n"
        f"├ 📤 От администраторов: {admin_msgs}\n"
        f"└ 💬 Всего сообщений: {total_msgs}"
    )
    await message.reply(text, parse_mode=ParseMode.HTML)

@dp.message(Command("adminstats"), F.chat.id == ADMIN_CHAT_ID)
async def adminstats_cmd(message: types.Message):
    if not await is_admin(message.from_user.id):
        return
    if not db_pool:
        return
    
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)
    month_start = now - timedelta(days=30)

    async with db_pool.acquire() as conn:
        today_rows = await conn.fetch("""
            SELECT admin_username, COUNT(*) as cnt 
            FROM admin_actions 
            WHERE created_at >= $1 
            GROUP BY admin_username 
            ORDER BY cnt DESC LIMIT 10;
        """, today_start)

        week_rows = await conn.fetch("""
            SELECT admin_username, COUNT(*) as cnt 
            FROM admin_actions 
            WHERE created_at >= $1 
            GROUP BY admin_username 
            ORDER BY cnt DESC LIMIT 10;
        """, week_start)

        month_rows = await conn.fetch("""
            SELECT admin_username, COUNT(*) as cnt 
            FROM admin_actions 
            WHERE created_at >= $1 
            GROUP BY admin_username 
            ORDER BY cnt DESC LIMIT 10;
        """, month_start)

        all_rows = await conn.fetch("""
            SELECT admin_username, COUNT(*) as cnt 
            FROM admin_actions 
            GROUP BY admin_username 
            ORDER BY cnt DESC LIMIT 10;
        """)

    text = "📊 <b>Статистика работы администрации (взятые ПЗ):</b>\n\n"
    
    text += "📅 <b>За сегодня:</b>\n"
    if today_rows:
        for idx, r in enumerate(today_rows, 1):
            text += f"{idx}. @{r['admin_username']} — {r['cnt']}\n"
    else:
        text += "Пока нет данных.\n"
    
    text += "\n📈 <b>За неделю (7 дней):</b>\n"
    if week_rows:
        for idx, r in enumerate(week_rows, 1):
            text += f"{idx}. @{r['admin_username']} — {r['cnt']}\n"
    else:
        text += "Пока нет данных.\n"

    text += "\n🗓 <b>За месяц (30 дней):</b>\n"
    if month_rows:
        for idx, r in enumerate(month_rows, 1):
            text += f"{idx}. @{r['admin_username']} — {r['cnt']}\n"
    else:
        text += "Пока нет данных.\n"

    text += "\n🏆 <b>За всё время:</b>\n"
    if all_rows:
        for idx, r in enumerate(all_rows, 1):
            text += f"{idx}. @{r['admin_username']} — {r['cnt']}\n"
    else:
        text += "Пока нет данных."

    await message.reply(text, parse_mode=ParseMode.HTML)

@dp.message(F.text.startswith(".астат"), F.chat.id == ADMIN_CHAT_ID)
async def adminstats_dot_cmd(message: types.Message):
    await adminstats_cmd(message)

@dp.message(Command("check"), F.chat.id == ADMIN_CHAT_ID)
async def check_cmd(message: types.Message, command: CommandObject):
    if not await is_admin(message.from_user.id):
        return
    if not db_pool:
        return
    
    target_id = None
    if command.args:
        async with db_pool.acquire() as conn:
            target_id = await get_target_user_id(conn, command.args)
    elif message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
        if message.reply_to_message.from_user.id == bot.id and message.reply_to_message.text:
            import re
            match = re.search(r"ID:\s*<code>(\d+)<\/code>", message.reply_to_message.text)
            if match:
                target_id = int(match.group(1))

    if not target_id:
        await message.reply("❌ Укажите ID, юзернейм или ответьте на сообщение пользователя.")
        return

    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1;", target_id)
    
    if not user:
        await message.reply("❌ Пользователь не найден в базе данных.")
        return

    text = (
        "🔍 <b>Информация о пользователе:</b>\n\n"
        f"🆔 ID: <code>{user['user_id']}</code>\n"
        f"👤 Юзернейм: @{user['username'] or 'отсутствует'}\n"
        f"🛡 Роль: <b>{user['role']}</b>\n"
        f"🚫 Забанен: <b>{'Да' if user['is_banned'] else 'Нет'}</b>\n"
        f"🌴 Отпуск до: {user['rest_until'] or 'Нет'}"
    )
    await message.reply(text, parse_mode=ParseMode.HTML)

@dp.message(F.text.startswith(".чек"), F.chat.id == ADMIN_CHAT_ID)
async def check_dot_cmd(message: types.Message, command: CommandObject):
    await check_cmd(message, command)

@dp.message(Command("ban"), F.chat.id == ADMIN_CHAT_ID)
async def ban_cmd(message: types.Message, command: CommandObject):
    if not await is_director_or_owner(message.from_user.id):
        return
    if not db_pool or not command.args:
        await message.reply("❌ Укажите ID или юзернейм для бана.")
        return
    async with db_pool.acquire() as conn:
        target_id = await get_target_user_id(conn, command.args)
        if not target_id:
            await message.reply("❌ Пользователь не найден.")
            return
        await conn.execute("UPDATE users SET is_banned = TRUE WHERE user_id = $1;", target_id)
        await message.reply(f"🚫 Пользователь <code>{target_id}</code> заблокирован.", parse_mode=ParseMode.HTML)

@dp.message(Command("unban"), F.chat.id == ADMIN_CHAT_ID)
async def unban_cmd(message: types.Message, command: CommandObject):
    if not await is_director_or_owner(message.from_user.id):
        return
    if not db_pool or not command.args:
        await message.reply("❌ Укажите ID или юзернейм для разбана.")
        return
    async with db_pool.acquire() as conn:
        target_id = await get_target_user_id(conn, command.args)
        if not target_id:
            await message.reply("❌ Пользователь не найден.")
            return
        await conn.execute("UPDATE users SET is_banned = FALSE WHERE user_id = $1;", target_id)
        await message.reply(f"✅ Пользователь <code>{target_id}</code> разблокирован.", parse_mode=ParseMode.HTML)

@dp.message(Command("broadcast"), F.chat.id == ADMIN_CHAT_ID)
async def broadcast_cmd(message: types.Message, command: CommandObject):
    if not await is_owner(message.from_user.id) or not command.args:
        return
    if not db_pool:
        return
    
    text = command.args
    async with db_pool.acquire() as conn:
        users = await conn.fetch("SELECT user_id FROM users WHERE is_banned = FALSE;")
    
    success, failed = 0, 0
    for u in users:
        try:
            await bot.send_message(u["user_id"], text)
            success += 1
        except:
            failed += 1
    await message.reply(f"📢 Рассылка завершена!\n✅ Успешно: {success}\n❌ Ошибок: {failed}")

@dp.message(Command("rest"), F.chat.id == ADMIN_CHAT_ID)
async def rest_cmd(message: types.Message, command: CommandObject):
    if not await is_director_or_owner(message.from_user.id) or not command.args:
        return
    args = command.args.split()
    if len(args) < 2:
        await message.reply("❌ Формат: /rest [юз/ID] [дни]")
        return
    
    target_arg, days_arg = args[0], args[1]
    if not days_arg.isdigit():
        await message.reply("❌ Количество дней должно быть числом.")
        return
    
    days = int(days_arg)
    rest_until = datetime.now() + timedelta(days=days)

    async with db_pool.acquire() as conn:
        target_id = await get_target_user_id(conn, target_arg)
        if not target_id:
            await message.reply("❌ Пользователь не найден.")
            return
        await conn.execute("UPDATE users SET rest_until = $1 WHERE user_id = $2;", rest_until, target_id)
        await message.reply(f"🌴 Администратор <code>{target_id}</code> отправлен в отпуск на {days} дн.", parse_mode=ParseMode.HTML)

@dp.message(F.text.startswith(".ид"), F.chat.id == ADMIN_CHAT_ID)
async def get_id_dot_cmd(message: types.Message):
    if not await is_admin(message.from_user.id):
        return
    if message.reply_to_message:
        target = message.reply_to_message.from_user
        await message.reply(f"🆔 ID пользователя {target.full_name}: <code>{target.id}</code>", parse_mode=ParseMode.HTML)
    else:
        await message.reply("❌ Ответьте на сообщение пользователя.")

# --- УПРАВЛЕНИЕ РОЛЯМИ (Только Владелец) ---
@dp.message(Command("setdirector"))
async def set_director_cmd(message: types.Message, command: CommandObject):
    if not await is_owner(message.from_user.id) or not command.args:
        return
    if db_pool:
        async with db_pool.acquire() as conn:
            target_id = await get_target_user_id(conn, command.args)
            if not target_id:
                await message.reply("❌ Пользователь не найден в базе данных.")
                return
            await conn.execute("UPDATE users SET role = 'director' WHERE user_id = $1;", target_id)
            await message.reply(f"💼 Пользователь <code>{target_id}</code> назначен <b>Директором</b>.", parse_mode=ParseMode.HTML)

@dp.message(Command("setadmin"))
async def set_admin_cmd(message: types.Message, command: CommandObject):
    if not await is_owner(message.from_user.id) or not command.args:
        return
    if db_pool:
        async with db_pool.acquire() as conn:
            target_id = await get_target_user_id(conn, command.args)
            if not target_id:
                await message.reply("❌ Пользователь не найден в базе данных.")
                return
            await conn.execute("UPDATE users SET role = 'admin' WHERE user_id = $1;", target_id)
            await message.reply(f"🛡 Пользователь <code>{target_id}</code> назначен <b>Администратором</b>.", parse_mode=ParseMode.HTML)

@dp.message(Command("setintern"))
async def set_intern_cmd(message: types.Message, command: CommandObject):
    if not await is_owner(message.from_user.id) or not command.args:
        return
    if db_pool:
        async with db_pool.acquire() as conn:
            target_id = await get_target_user_id(conn, command.args)
            if not target_id:
                await message.reply("❌ Пользователь не найден в базе данных.")
                return
            await conn.execute("UPDATE users SET role = 'intern' WHERE user_id = $1;", target_id)
            await message.reply(f"🔰 Пользователь <code>{target_id}</code> назначен <b>Стажером</b>.", parse_mode=ParseMode.HTML)

@dp.message(Command("demote"))
async def demote_cmd(message: types.Message, command: CommandObject):
    if not await is_owner(message.from_user.id) or not command.args:
        return
    if db_pool:
        async with db_pool.acquire() as conn:
            target_id = await get_target_user_id(conn, command.args)
            if not target_id:
                await message.reply("❌ Пользователь не найден в базе данных.")
                return
            await conn.execute("UPDATE users SET role = 'user' WHERE user_id = $1;", target_id)
            await message.reply(f"👤 Пользователь <code>{target_id}</code> разжалован до обычного пользователя.", parse_mode=ParseMode.HTML)

@dp.message(Command("setowner"))
async def set_owner_cmd(message: types.Message):
    if message.from_user.id == OWNER_ID:
        await message.reply("👑 Ваши права Владельца подтверждены.")
    else:
        await message.reply("⛔️ У вас нет прав Владельца.")

# --- ЗАПРОС СМЕНЫ АДМИНА ПОЛЬЗОВАТЕЛЕМ ---
@dp.message(Command("change_admin"))
async def user_request_change_admin(message: types.Message, state: FSMContext):
    if message.chat.type != "private":
        return
    
    user_id = message.from_user.id
    if db_pool:
        async with db_pool.acquire() as conn:
            topic_id = await conn.fetchval("SELECT topic_id FROM users WHERE user_id = $1;", user_id)
            if not topic_id:
                await message.reply("У вас еще нет активного диалога с администрацией. Сначала напишите сообщение в бот.")
                return

    await state.set_state(ChangeAdminState.waiting_for_reason)
    await message.reply("🔄 Пожалуйста, напишите <b>причину</b>, по которой вы хотите сменить администратора:")

@dp.message(ChangeAdminState.waiting_for_reason, F.chat.type == "private")
async def process_change_reason(message: types.Message, state: FSMContext):
    reason = message.text
    user_id = message.from_user.id
    full_name = message.from_user.full_name
    username = message.from_user.username or "отсутствует"

    await state.clear()
    await message.reply("✅ Ваш запрос на смену администратора отправлен руководству. Ожидайте одобрения.")

    if not db_pool or not ADMIN_CHAT_ID or not UNASSIGNED_TOPIC_ID:
        return

    async with db_pool.acquire() as conn:
        topic_id = await conn.fetchval("SELECT topic_id FROM users WHERE user_id = $1;", user_id)

    if topic_id:
        clean_chat_id = str(ADMIN_CHAT_ID).replace("-100", "")
        topic_link = f"https://t.me/c/{clean_chat_id}/{topic_id}"

        keyboard = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(text="✅ Одобрить смену", callback_data=f"approve_change_{user_id}"),
                    types.InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_change_{user_id}")
                ]
            ]
        )

        request_text = (
            "🔄 <b>Запрос на смену администратора!</b>\n\n"
            f"👤 Пользователь: <b>{full_name}</b> (@{username}) [ID: <code>{user_id}</code>]\n"
            f"💬 <b>Причина:</b> {reason}\n"
            f"🔗 <a href='{topic_link}'>Перейти в топик пользователя</a>"
        )

        try:
            await bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                message_thread_id=UNASSIGNED_TOPIC_ID,
                text=request_text,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )
        except Exception as e:
            logger.error(f"Ошибка отправки запроса смены админа в общий топик: {e}")

# --- ОБРАБОТЧИК КНОПОК ОДОБРЕНИЯ / ОТКЛОНЕНИЯ СМЕНЫ ---
@dp.callback_query(F.data.startswith("approve_change_") | F.data.startswith("reject_change_"))
async def handle_change_decision(callback: types.CallbackQuery):
    actor_id = callback.from_user.id
    
    if not await is_director_or_owner(actor_id):
        await callback.answer("⛔️ Одобрять или отклонять смену администратора могут только Директора и Владелец!", show_alert=True)
        return

    action, target_user_id_str = callback.data.split("_")[0], callback.data.split("_")[2]
    target_user_id = int(target_user_id_str)
    original_text = callback.message.html_text

    if action == "approve":
        updated_text = original_text + "\n\n✅ <b>Статус:</b> Смена админа одобрена. <b>ПЗ снова свободно</b>"
        
        try:
            await bot.send_message(target_user_id, "✅ Руководство одобрило смену вашего администратора. Скоро к вам подключится новый специалист!")
        except:
            pass

        try:
            await callback.message.edit_text(text=updated_text, parse_mode=ParseMode.HTML)
            await callback.answer("Смена администратора одобрена!")
        except Exception as e:
            logger.error(f"Ошибка одобрения смены: {e}")

    else:
        updated_text = original_text + "\n\n❌ <b>Статус:</b> Запрос на смену админа отклонен руководством."
        
        try:
            await bot.send_message(target_user_id, "❌ Руководство отклонило ваш запрос на смену администратора.")
        except:
            pass

        try:
            await callback.message.edit_text(text=updated_text, parse_mode=ParseMode.HTML)
            await callback.answer("Запрос отклонен.")
        except Exception as e:
            logger.error(f"Ошибка отклонения смены: {e}")

# --- ПЕРЕСЫЛКА СООБЩЕНИЙ И ТОПИКИ ---
@dp.message(F.chat.type == "private")
async def forward_user_message(message: types.Message):
    if not ADMIN_CHAT_ID:
        return
    if message.text and message.text.startswith("/"):
        return

    user_id = message.from_user.id
    username = message.from_user.username or "отсутствует"
    full_name = message.from_user.full_name

    try:
        await message.react([types.ReactionTypeEmoji(emoji="👍")])
    except Exception as e:
        logger.error(f"Не удалось поставить реакцию: {e}")

    topic_id = None
    is_new_topic = False

    if db_pool:
        async with db_pool.acquire() as conn:
            is_banned = await conn.fetchval("SELECT is_banned FROM users WHERE user_id = $1;", user_id)
            if is_banned:
                await message.reply("🚫 Вы заблокированы.")
                return

            row = await conn.fetchrow("SELECT topic_id FROM users WHERE user_id = $1;", user_id)
            topic_id = row["topic_id"] if row else None

            if not topic_id:
                is_new_topic = True
                try:
                    topic_title = f"{full_name} (@{username})"[:128]
                    new_topic = await bot.create_forum_topic(chat_id=ADMIN_CHAT_ID, name=topic_title)
                    topic_id = new_topic.message_thread_id

                    await conn.execute("""
                        INSERT INTO users (user_id, username, topic_id) 
                        VALUES ($1, $2, $3)
                        ON CONFLICT (user_id) DO UPDATE SET topic_id = $3, username = $2;
                    """, user_id, username, topic_id)
                except Exception as e:
                    logger.error(f"Ошибка создания топика: {e}")
                    topic_id = None

    if topic_id:
        if is_new_topic:
            info_text = (
                "👤 <b>Информация о пользователе (ПЗ):</b>\n\n"
                f"📌 Имя: <b>{full_name}</b>\n"
                f"🔗 Юзернейм: @{username}\n"
                f"🆔 Telegram ID: <code>{user_id}</code>\n"
                f"❌ <b>Кто взял ПЗ:</b> Никто не взял"
            )
            keyboard = types.InlineKeyboardMarkup(
                inline_keyboard=[
                    [types.InlineKeyboardButton(text="🤝 Взять пользователя", callback_data=f"take_user_{user_id}")]
                ]
            )
            try:
                sent_msg = await bot.send_message(chat_id=ADMIN_CHAT_ID, message_thread_id=topic_id, text=info_text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
                await bot.pin_chat_message(chat_id=ADMIN_CHAT_ID, message_id=sent_msg.message_id)
                
                if UNASSIGNED_TOPIC_ID:
                    clean_chat_id = str(ADMIN_CHAT_ID).replace("-100", "")
                    topic_link = f"https://t.me/c/{clean_chat_id}/{topic_id}"
                    
                    unassigned_text = (
                        "🚨 <b>Новый пользователь!</b>\n\n"
                        f"👤 Имя: <b>{full_name}</b> (@{username})\n"
                        f"📌 Статус: <b>нету админа</b>\n"
                        f"🔗 <a href='{topic_link}'>Перейти в топик пользователя</a>"
                    )
                    await bot.send_message(
                        chat_id=ADMIN_CHAT_ID,
                        message_thread_id=UNASSIGNED_TOPIC_ID,
                        text=unassigned_text,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True
                    )
            except Exception as e:
                logger.error(f"Ошибка закрепа: {e}")

        try:
            copied_msg = await bot.copy_message(chat_id=ADMIN_CHAT_ID, message_thread_id=topic_id, from_chat_id=message.chat.id, message_id=message.message_id)
            
            if db_pool:
                async with db_pool.acquire() as conn:
                    await conn.execute(
                        "INSERT INTO messages (user_id, sender_type, user_msg_id, admin_msg_id) VALUES ($1, 'user', $2, $3);",
                        user_id, message.message_id, copied_msg.message_id
                    )
        except Exception as e:
            logger.error(f"Ошибка пересылки: {e}")

# --- ОБРАБОТЧИК КНОПКИ «ВЗЯТЬ ПОЛЬЗОВАТЕЛЯ» ---
@dp.callback_query(F.data.startswith("take_user_"))
async def take_user_callback(callback: types.CallbackQuery):
    target_user_id = int(callback.data.split("_")[2])
    admin_user = callback.from_user
    admin_username = admin_user.username or "отсутствует"
    admin_name = f"@{admin_username}" if admin_username != "отсутствует" else admin_user.full_name
    admin_info = f"{admin_name} (ID: <code>{admin_user.id}</code>)"

    if db_pool:
        async with db_pool.acquire() as conn:
            await conn.execute("INSERT INTO admin_actions (admin_id, admin_username, target_user_id) VALUES ($1, $2, $3);", admin_user.id, admin_username, target_user_id)

    original_text = callback.message.html_text
    
    if "✅ <b>Кто взял ПЗ:</b>" in original_text:
        parts = original_text.split("✅ <b>Кто взял ПЗ:</b>")
        base_text = parts[0].strip()
        updated_text = f"{base_text}\n\n✅ <b>Кто взял ПЗ:</b> {admin_info}"
    elif "❌ <b>Кто взял ПЗ:</b> Никто не взял" in original_text:
        updated_text = original_text.replace("❌ <b>Кто взял ПЗ:</b> Никто не взял", f"✅ <b>Кто взял ПЗ:</b> {admin_info}")
    else:
        updated_text = original_text + f"\n\n✅ <b>Кто взял ПЗ:</b> {admin_info}"

    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="🤝 Взять пользователя", callback_data=f"take_user_{target_user_id}")]
        ]
    )

    try:
        await callback.message.edit_text(text=updated_text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
        await callback.answer("Вы успешно взяли пользователя!")
    except Exception as e:
        logger.error(f"Ошибка кнопки взять ПЗ: {e}")

# --- ОТВЕТЫ ИЗ ТОПИКОВ АДМИНАМИ ---
@dp.message(F.chat.id == ADMIN_CHAT_ID)
async def reply_from_topic(message: types.Message):
    if message.forum_topic_created or message.forum_topic_edited:
        return
    if not message.message_thread_id or (message.text and message.text.startswith("/")):
        return
    if not db_pool:
        return

    async with db_pool.acquire() as conn:
        user_id = await conn.fetchval("SELECT user_id FROM users WHERE topic_id = $1;", message.message_thread_id)
        if user_id:
            try:
                sent_msg = await bot.copy_message(chat_id=user_id, from_chat_id=ADMIN_CHAT_ID, message_id=message.message_id)
                await conn.execute(
                    "INSERT INTO messages (user_id, sender_type, user_msg_id, admin_msg_id) VALUES ($1, 'admin', $2, $3);",
                    user_id, sent_msg.message_id, message.message_id
                )
            except Exception as e:
                await message.reply(f"❌ Ошибка отправки: {e}")

# --- СИНХРОНИЗАЦИЯ РЕАКЦИЙ ---
@dp.message_reaction()
async def handle_message_reaction(event: types.MessageReactionUpdated):
    if not db_pool:
        return

    chat_id = event.chat.id
    msg_id = event.message_id
    
    new_reactions = []
    for r in event.new_reaction:
        if isinstance(r, types.ReactionTypeEmoji):
            new_reactions.append(r.emoji)

    async with db_pool.acquire() as conn:
        if chat_id == ADMIN_CHAT_ID:
            row = await conn.fetchrow("SELECT user_id, user_msg_id FROM messages WHERE admin_msg_id = $1;", msg_id)
            if row and row["user_msg_id"]:
                try:
                    await bot.set_message_reaction(chat_id=row["user_id"], message_id=row["user_msg_id"], reaction=[types.ReactionTypeEmoji(emoji=e) for e in new_reactions])
                except Exception as e:
                    logger.error(f"Ошибка синхронизации реакции на юзера: {e}")
        else:
            row = await conn.fetchrow("SELECT topic_id, admin_msg_id FROM messages JOIN users ON messages.user_id = users.user_id WHERE messages.user_id = $1 AND messages.user_msg_id = $2;", chat_id, msg_id)
            if row and row["admin_msg_id"]:
                try:
                    await bot.set_message_reaction(chat_id=ADMIN_CHAT_ID, message_id=row["admin_msg_id"], reaction=[types.ReactionTypeEmoji(emoji=e) for e in new_reactions])
                except Exception as e:
                    logger.error(f"Ошибка синхронизации реакции в админ-чат: {e}")

# --- ЗАПУСК ---
async def main():
    await init_db()
    await dp.start_polling(bot, allowed_updates=["message", "callback_query", "message_reaction"])

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())