import os
import logging
import asyncpg
from datetime import datetime, timedelta, timezone
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.enums import ParseMode

# --- НАСТРОЙКА ЛОГИРОВАНИЯ ---
logging.basicConfig(level=logging.INFO)

# --- ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", 0)) if os.getenv("ADMIN_CHAT_ID") else None

# 👑 ТВОЙ TELEGRAM ID
OWNER_ID = 8674242517

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

db_pool = None
db_error_msg = ""

# --- ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ ---
async def init_db():
    global db_pool, db_error_msg
    if not DATABASE_URL:
        db_error_msg = "Переменная DATABASE_URL не задана в Railway!"
        logging.error(db_error_msg)
        return

    try:
        db_pool = await asyncpg.create_pool(DATABASE_URL)
        async with db_pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    role TEXT DEFAULT 'user',
                    is_banned BOOLEAN DEFAULT FALSE,
                    topic_id INT,
                    rest_until TIMESTAMP
                );
                ALTER TABLE users ADD COLUMN IF NOT EXISTS topic_id INT;
                ALTER TABLE users ADD COLUMN IF NOT EXISTS is_banned BOOLEAN DEFAULT FALSE;
                ALTER TABLE users ADD COLUMN IF NOT EXISTS rest_until TIMESTAMP;

                CREATE TABLE IF NOT EXISTS messages (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    sender_type TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
        logging.info("База данных PostgreSQL успешно инициализирована.")
        db_error_msg = ""
    except Exception as e:
        db_error_msg = str(e)
        logging.error(f"Ошибка подключения к БД: {e}")

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ И ПРОВЕРКА ОТПУСКА ---
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
            
            # Проверяем, не на отдыхе ли пользователь
            rest_until = row["rest_until"]
            if rest_until:
                # Сравниваем с текущим временем (UTC)
                if rest_until > datetime.now(timezone.utc):
                    # Если в отпуске, то для системы прав он временно обычный юзер
                    return "user"
                else:
                    # Отпуск закончился — очищаем поле в базе
                    await conn.execute("UPDATE users SET rest_until = NULL WHERE user_id = $1;", user_id)

            return row["role"] or "user"
    except Exception as e:
        logging.error(f"❌ Ошибка при получении роли для {user_id}: {e}")
        return "user"

async def is_admin(user_id: int) -> bool:
    role = await get_user_role(user_id)
    return str(role).lower() in ["owner", "director", "admin", "intern"]

async def is_director_or_owner(user_id: int) -> bool:
    role = await get_user_role(user_id)
    return str(role).lower() in ["owner", "director"]

async def is_top_admin(user_id: int) -> bool:
    return await is_director_or_owner(user_id)

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
        "Прочитал? тогда пиши \"привет общение/поддержка/уни\" и к тебе придет админ.\n"
        "удачи тебе солнышко"
    )
    await message.reply(start_text, disable_web_page_preview=False)

# --- РАЗДЕЛЕННЫЙ /HELP ---
@dp.message(Command("help"))
async def help_cmd(message: types.Message):
    user_id = message.from_user.id
    
    # Определяем реальную роль для показа корректной справки
    role = "user"
    if user_id == OWNER_ID:
        role = "owner"
    elif db_pool:
        async with db_pool.acquire() as conn:
            r = await conn.fetchval("SELECT role FROM users WHERE user_id = $1;", user_id)
            if r:
                role = str(r).lower()

    text = "📌 <b>Список доступных команд:</b>\n\n"

    # 1. Меню для обычных пользователей
    if role == "user":
        text += "👤 <b>Пользователям:</b>\n"
        text += "├ /start — Запустить бота\n"
        text += "└ /help — Справка по командам\n"

    # 2. Меню для стажёров и администраторов
    elif role in ["admin", "intern"]:
        text += "🛡 <b>Администрации:</b>\n"
        text += "├ /stats — Статистика бота\n"
        text += "├ /check или .чек — Проверить пользователя\n"
        text += "├ /ban [ID] — Заблокировать пользователя\n"
        text += "└ /unban [ID] — Разблокировать пользователя\n"

    # 3. Меню для директоров
    elif role == "director":
        text += "💼 <b>Директорат:</b>\n"
        text += "├ /stats — Статистика бота\n"
        text += "├ /check или .чек — Проверить пользователя\n"
        text += "├ /ban /unban [ID] — Управление банами\n"
        text += "├ /broadcast [текст] — Рассылка пользователям\n"
        text += "├ /rest [юз/ID] [дни] — Отправить админа в отпуск\n"
        text += "└ <code>.ид юз</code> — Узнать ID пользователя\n"

    # 4. Меню для главного владельца
    elif role == "owner":
        text += "👑 <b>Владелец:</b>\n"
        text += "├ /stats — Статистика бота\n"
        text += "├ /check или .чек — Проверить пользователя\n"
        text += "├ /ban /unban [ID] — Управление банами\n"
        text += "├ /broadcast [текст] — Рассылка\n"
        text += "├ /rest [юз/ID] [дни] — Отправить в отпуск\n"
        text += "├ <code>.ид юз</code> — Узнать ID пользователя\n"
        text += "├ /setdirector [ID] — Назначить директора\n"
        text += "├ /setadmin [ID] — Назначить администратора\n"
        text += "├ /setintern [ID] — Назначить стажёра\n"
        text += "├ /demote [ID] — Понизить до пользователя\n"
        text += "└ /setowner — Подтвердить права Владельца\n"

    await message.reply(text, parse_mode=ParseMode.HTML)

# --- СИСТЕМА ОТПУСКОВ (/rest) ---
@dp.message(Command("rest"))
async def rest_cmd(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    
    # Только владелец или директор могут выдавать отпуск
    if not await is_director_or_owner(user_id):
        await message.reply("❌ У вас нет доступа к этой команде. Отправлять в отпуск может только руководство.")
        return

    args = (command.args or "").split()
    if len(args) < 2:
        await message.reply(
            "⚠️ Неверный формат команды.\n"
            "Используйте: <code>/rest @username дни</code> или <code>/rest ID дни</code>", 
            parse_mode=ParseMode.HTML
        )
        return

    target_raw = args[0]
    try:
        days = int(args[1])
    except ValueError:
        await message.reply("⚠️ Неверно указано количество дней. Пример: <code>/rest @user 5</code> или <code>/rest 12345678 5</code>", parse_mode=ParseMode.HTML)
        return

    if not db_pool:
        return

    async with db_pool.acquire() as conn:
        if target_raw.startswith("@"):
            username_clean = target_raw.replace("@", "").strip()
            row = await conn.fetchrow("SELECT user_id, username FROM users WHERE LOWER(username) = LOWER($1);", username_clean)
        elif target_raw.isdigit():
            target_id = int(target_raw)
            row = await conn.fetchrow("SELECT user_id, username FROM users WHERE user_id = $1;", target_id)
        else:
            row = None

        if not row:
            await message.reply("⚠️ Пользователь не найден в базе данных.")
            return
        
        target_id = row["user_id"]
        target_name = f"@{row['username']}" if row["username"] else f"ID: {target_id}"

        rest_until_date = datetime.now(timezone.utc) + timedelta(days=days)
        await conn.execute("UPDATE users SET rest_until = $1 WHERE user_id = $2;", rest_until_date, target_id)

    await message.reply(f"🏖 Пользователь <b>{target_name}</b> уходит в отпуск на <b>{days} дней</b>. Его полномочия временно заморожены.", parse_mode=ParseMode.HTML)

# --- ЛОГИКА УЗНАТЬ ID ---
async def process_get_user_id(message: types.Message):
    if not await is_top_admin(message.from_user.id):
        await message.reply("❌ Эта команда доступна только Владельцу и Директорам!")
        return

    target_user_id = None
    target_username = None

    args = message.text.split()
    if len(args) > 1 and args[1].startswith("@"):
        target_username = args[1].replace("@", "").strip()
    elif message.reply_to_message:
        if message.reply_to_message.forward_from:
            target_user_id = message.reply_to_message.forward_from.id
            target_username = message.reply_to_message.forward_from.username
        elif message.message_thread_id and db_pool:
            async with db_pool.acquire() as conn:
                target_user_id = await conn.fetchval("SELECT user_id FROM users WHERE topic_id = $1;", message.message_thread_id)
    elif message.message_thread_id and db_pool:
        async with db_pool.acquire() as conn:
            target_user_id = await conn.fetchval("SELECT user_id FROM users WHERE topic_id = $1;", message.message_thread_id)

    if db_pool:
        async with db_pool.acquire() as conn:
            if target_username and not target_user_id:
                row = await conn.fetchrow("SELECT user_id, username, role, is_banned FROM users WHERE LOWER(username) = LOWER($1);", target_username)
            elif target_user_id:
                row = await conn.fetchrow("SELECT user_id, username, role, is_banned FROM users WHERE user_id = $1;", target_user_id)
            else:
                row = None

            if row:
                status = "🚫 Забанен" if row["is_banned"] else "🍏 Активен"
                text = (
                    "👤 <b>Информация о пользователе:</b>\n\n"
                    f"🆔 Telegram ID: <code>{row['user_id']}</code>\n"
                    f"👤 Юзернейм: @{row['username'] or 'отсутствует'}\n"
                    f"🎭 Роль: <b>{row['role']}</b>\n"
                    f"📌 Статус: <b>{status}</b>"
                )
                await message.reply(text, parse_mode=ParseMode.HTML)
                return

    if target_user_id:
        await message.reply(f"🆔 Telegram ID пользователя: <code>{target_user_id}</code>", parse_mode=ParseMode.HTML)
    else:
        await message.reply(
            "⚠️ <b>Не удалось найти ID.</b>\n"
            "Используйте команду в нужном топике, либо ответьте на сообщение юзера, или напишите: <code>.ид @username</code>", 
            parse_mode=ParseMode.HTML
        )

@dp.message(F.text.lower().startswith(".ид"))
async def get_user_id_by_dot(message: types.Message):
    await process_get_user_id(message)

@dp.message(Command("id"))
async def get_user_id_by_command(message: types.Message):
    await process_get_user_id(message)

# --- ПРОВЕРКА ПОЛЬЗОВАТЕЛЯ (/check и .чек) ---
async def process_check_user(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.reply("❌ Эта команда доступна только администрации!")
        return

    target_user_id = None
    target_username = None

    args = message.text.split()
    if len(args) > 1 and args[1].startswith("@"):
        target_username = args[1].replace("@", "").strip()
    elif len(args) > 1 and args[1].isdigit():
        target_user_id = int(args[1])
    elif message.reply_to_message:
        if message.reply_to_message.forward_from:
            target_user_id = message.reply_to_message.forward_from.id
            target_username = message.reply_to_message.forward_from.username
        elif message.message_thread_id and db_pool:
            async with db_pool.acquire() as conn:
                target_user_id = await conn.fetchval("SELECT user_id FROM users WHERE topic_id = $1;", message.message_thread_id)
    elif message.message_thread_id and db_pool:
        async with db_pool.acquire() as conn:
            target_user_id = await conn.fetchval("SELECT user_id FROM users WHERE topic_id = $1;", message.message_thread_id)

    if not db_pool:
        await message.reply("⚠️ База данных недоступна!")
        return

    async with db_pool.acquire() as conn:
        if target_username and not target_user_id:
            row = await conn.fetchrow("SELECT user_id, username, role, is_banned, topic_id, rest_until FROM users WHERE LOWER(username) = LOWER($1);", target_username)
        elif target_user_id:
            row = await conn.fetchrow("SELECT user_id, username, role, is_banned, topic_id, rest_until FROM users WHERE user_id = $1;", target_user_id)
        else:
            row = None

        if not row:
            await message.reply("⚠️ Пользователь не найден в базе данных бота.", parse_mode=ParseMode.HTML)
            return

        user_msgs = await conn.fetchval("SELECT COUNT(*) FROM messages WHERE user_id = $1 AND sender_type = 'user';", row["user_id"]) or 0
        admin_msgs = await conn.fetchval("SELECT COUNT(*) FROM messages WHERE user_id = $1 AND sender_type = 'admin';", row["user_id"]) or 0

    status = "🚫 Забанен" if row["is_banned"] else "🍏 Активен"
    rest_info = f"🏖 В отпуске до {row['rest_until'].strftime('%Y-%m-%d %H:%M')}" if row["rest_until"] and row["rest_until"] > datetime.now(timezone.utc) else "Нет"
    
    text = (
        "🔍 👤 <b>Подробная проверка пользователя:</b>\n\n"
        f"🆔 Telegram ID: <code>{row['user_id']}</code>\n"
        f"👤 Юзернейм: @{row['username'] or 'отсутствует'}\n"
        f"🎭 Роль в боте: <b>{row['role']}</b>\n"
        f"📌 Статус: <b>{status}</b>\n"
        f"🏖 Отпуск: <b>{rest_info}</b>\n"
        f"📁 ID топика: <code>{row['topic_id'] or 'нет топика'}</code>\n\n"
        "✉️ <b>Статистика диалога:</b>\n"
        f"├ Сообщений от юзера: <b>{user_msgs}</b>\n"
        f"└ Ответов от админов: <b>{admin_msgs}</b>"
    )
    await message.reply(text, parse_mode=ParseMode.HTML)

@dp.message(F.text.lower().startswith(".чек"))
async def check_user_by_dot(message: types.Message):
    await process_check_user(message)

@dp.message(Command("check"))
async def check_user_by_command(message: types.Message):
    await process_check_user(message)

# --- УПРАВЛЕНИЕ РОЛЯМИ ---
async def change_role(message: types.Message, command: CommandObject, new_role: str, role_name: str):
    if not await is_admin(message.from_user.id):
        await message.reply("❌ У вас нет прав на управление ролями!")
        return
    if not command.args or not command.args.isdigit():
        await message.reply(f"⚠️ Укажите Telegram ID. Пример: <code>/{message.text.split()[0]} 12345678</code>", parse_mode=ParseMode.HTML)
        return
    
    target_id = int(command.args)
    if db_pool:
        async with db_pool.acquire() as conn:
            await conn.execute("UPDATE users SET role = $1 WHERE user_id = $2;", new_role, target_id)
            
            # Получаем имя/юзернейм пользователя для красивого отчета
            target_row = await conn.fetchrow("SELECT username FROM users WHERE user_id = $1;", target_id)
            target_name = f"@{target_row['username']}" if target_row and target_row["username"] else f"ID: {target_id}"

        # Отправляем сообщение в чат об изменении роли
        await message.reply(f"✅ Пользователь <b>{target_name}</b> (<code>{target_id}</code>) назначен на должность: <b>{role_name}</b>", parse_mode=ParseMode.HTML)

@dp.message(Command("setdirector"))
async def set_director_cmd(message: types.Message, command: CommandObject):
    await change_role(message, command, "director", "💼 Директор")

@dp.message(Command("setadmin"))
async def set_admin_cmd(message: types.Message, command: CommandObject):
    await change_role(message, command, "admin", "🛡 Администратор")

@dp.message(Command("setintern"))
async def set_intern_cmd(message: types.Message, command: CommandObject):
    await change_role(message, command, "intern", "🔰 Стажёр")

@dp.message(Command("demote"))
async def demote_cmd(message: types.Message, command: CommandObject):
    await change_role(message, command, "user", "👤 Обычный пользователь")

@dp.message(Command("setowner"))
async def set_owner_cmd(message: types.Message):
    if message.from_user.id != OWNER_ID:
        await message.reply("❌ Эта команда доступна только главному владельцу!")
        return
    if db_pool:
        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO users (user_id, username, role) 
                VALUES ($1, $2, 'owner')
                ON CONFLICT (user_id) DO UPDATE SET role = 'owner';
            """, message.from_user.id, message.from_user.username)
        await message.reply("👑 Ваша роль 'Владелец' успешно записана в БД!")

# --- РАССЫЛКА (/broadcast) ---
@dp.message(Command("broadcast"))
async def broadcast_cmd(message: types.Message, command: CommandObject):
    if not await is_admin(message.from_user.id):
        await message.reply("❌ У вас нет прав для рассылки!")
        return
    if not command.args:
        await message.reply("⚠️ Напишите текст рассылки. Пример:\n<code>/broadcast Всем привет!</code>", parse_mode=ParseMode.HTML)
        return

    text_to_send = command.args
    if not db_pool:
        await message.reply("⚠️ База данных недоступна!")
        return

    async with db_pool.acquire() as conn:
        users = await conn.fetch("SELECT user_id FROM users WHERE is_banned = FALSE;")
    
    count = 0
    for u in users:
        try:
            await bot.send_message(u["user_id"], text_to_send)
            count += 1
        except Exception:
            pass

    await message.reply(f"📢 Рассылка завершена! Успешно доставлено: <b>{count}</b> пользователям.", parse_mode=ParseMode.HTML)

# --- БАН / РАЗБАН ---
@dp.message(Command("ban"))
async def ban_cmd(message: types.Message, command: CommandObject):
    if not await is_admin(message.from_user.id):
        return
    if not command.args or not command.args.isdigit():
        await message.reply("⚠️ Укажите ID: <code>/ban 12345678</code>", parse_mode=ParseMode.HTML)
        return
    target_id = int(command.args)
    if db_pool:
        async with db_pool.acquire() as conn:
            await conn.execute("UPDATE users SET is_banned = TRUE WHERE user_id = $1;", target_id)
        await message.reply(f"🚫 Пользователь <code>{target_id}</code> забанен!", parse_mode=ParseMode.HTML)

@dp.message(Command("unban"))
async def unban_cmd(message: types.Message, command: CommandObject):
    if not await is_admin(message.from_user.id):
        return
    if not command.args or not command.args.isdigit():
        await message.reply("⚠️ Укажите ID: <code>/unban 12345678</code>", parse_mode=ParseMode.HTML)
        return
    target_id = int(command.args)
    if db_pool:
        async with db_pool.acquire() as conn:
            await conn.execute("UPDATE users SET is_banned = FALSE WHERE user_id = $1;", target_id)
        await message.reply(f"🍏 Пользователь <code>{target_id}</code> разбанен!", parse_mode=ParseMode.HTML)

# --- СТАТИСТИКА (/stats) ---
@dp.message(Command("stats"))
async def stats_cmd(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.reply("❌ Отказано в доступе!")
        return
    if not db_pool:
        await message.reply("⚠️ База данных недоступна!")
        return

    async with db_pool.acquire() as conn:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users;") or 0
        banned_users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_banned = TRUE;") or 0
        clean_users = total_users - banned_users

        owners = await conn.fetchval("SELECT COUNT(*) FROM users WHERE role = 'owner';") or 1
        directors = await conn.fetchval("SELECT COUNT(*) FROM users WHERE role = 'director';") or 0
        admins = await conn.fetchval("SELECT COUNT(*) FROM users WHERE role = 'admin';") or 0
        interns = await conn.fetchval("SELECT COUNT(*) FROM users WHERE role = 'intern';") or 0
        simple_users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE role = 'user';") or 0

        user_msgs = await conn.fetchval("SELECT COUNT(*) FROM messages WHERE sender_type = 'user';") or 0
        admin_msgs = await conn.fetchval("SELECT COUNT(*) FROM messages WHERE sender_type = 'admin';") or 0
        total_msgs = user_msgs + admin_msgs

    text = (
        "📊 <b>Полная статистика бота:</b>\n\n"
        "👥 <b>Пользователи:</b>\n"
        f"├ Всего пользователей: <b>{total_users}</b>\n"
        f"├ 🍏 Активных (чистых): <b>{clean_users}</b>\n"
        f"└ 🚫 Забаненных: <b>{banned_users}</b>\n\n"
        "🎭 <b>Разделение по ролям:</b>\n"
        f"├ 👑 Владелец: <b>{owners}</b>\n"
        f"├ 💼 Директоров: <b>{directors}</b>\n"
        f"├ 🛡 Администраторов: <b>{admins}</b>\n"
        f"├ 🔰 Стажёров: <b>{interns}</b>\n"
        f"└ 👤 Пользователей: <b>{simple_users}</b>\n\n"
        "✉️ <b>Сообщения и активность:</b>\n"
        f"├ 📩 От пользователей: <b>{user_msgs}</b>\n"
        f"├ 📤 От администраторов: <b>{admin_msgs}</b>\n"
        f"└ 💬 Всего сообщений: <b>{total_msgs}</b>"
    )
    await message.reply(text, parse_mode=ParseMode.HTML)

# --- ПЕРЕСЫЛКА СООБЩЕНИЙ С СОЗДАНИЕМ ТОПИКА И ЛОГАМИ ---
@dp.message(F.chat.type == "private")
async def forward_user_message(message: types.Message):
    if not ADMIN_CHAT_ID:
        logging.error("❌ ОШИБКА: ADMIN_CHAT_ID не задан в переменных окружения!")
        return

    if message.text and message.text.startswith("/"):
        return

    user_id = message.from_user.id
    username = message.from_user.username or "нет"
    full_name = message.from_user.full_name

    topic_id = None

    if db_pool:
        async with db_pool.acquire() as conn:
            is_banned = await conn.fetchval("SELECT is_banned FROM users WHERE user_id = $1;", user_id)
            if is_banned:
                await message.reply("🚫 Вы заблокированы и не можете отправлять сообщения.")
                return

            topic_id = await conn.fetchval("SELECT topic_id FROM users WHERE user_id = $1;", user_id)

            if not topic_id:
                try:
                    topic_title = f"{full_name} (@{username})"[:128]
                    logging.info(f"🔄 Создаем новый топик для {user_id} в чате {ADMIN_CHAT_ID}...")
                    
                    new_topic = await bot.create_forum_topic(chat_id=ADMIN_CHAT_ID, name=topic_title)
                    topic_id = new_topic.message_thread_id
                    logging.info(f"✅ Топик успешно создан! ID топика: {topic_id}")

                    await conn.execute("""
                        INSERT INTO users (user_id, username, topic_id) 
                        VALUES ($1, $2, $3)
                        ON CONFLICT (user_id) DO UPDATE SET topic_id = $3, username = $2;
                    """, user_id, username, topic_id)
                except Exception as e:
                    logging.error(f"❌ ОШИБКА СОЗДАНИЯ ТОПИКА: {e}")
                    topic_id = None

            await conn.execute("INSERT INTO messages (user_id, sender_type) VALUES ($1, 'user');", user_id)

    if topic_id:
        try:
            await bot.copy_message(
                chat_id=ADMIN_CHAT_ID, 
                message_thread_id=topic_id, 
                from_chat_id=message.chat.id, 
                message_id=message.message_id
            )
            logging.info(f"📨 Сообщение от {user_id} доставлено в топик {topic_id}")
        except Exception as e:
            logging.error(f"❌ ОШИБКА ОТПРАВКИ СООБЩЕНИЯ В ТОПИК {topic_id}: {e}")
    else:
        logging.error(f"⚠️ Сообщение не отправлено: topic_id равен None (проверьте права бота в чате).")

# --- ОТВЕТ АДМИНА ИЗ ТОПИКА ПОЛЬЗОВАТЕЛЮ ---
@dp.message(F.chat.id == ADMIN_CHAT_ID)
async def reply_from_topic(message: types.Message):
    if message.forum_topic_created or message.forum_topic_edited:
        return

    if not message.message_thread_id or (message.text and (message.text.startswith("/") or message.text.startswith("."))):
        return

    if not db_pool:
        return

    async with db_pool.acquire() as conn:
        user_id = await conn.fetchval("SELECT user_id FROM users WHERE topic_id = $1;", message.message_thread_id)

        if user_id:
            try:
                await bot.copy_message(chat_id=user_id, from_chat_id=ADMIN_CHAT_ID, message_id=message.message_id)
                await conn.execute("INSERT INTO messages (user_id, sender_type) VALUES ($1, 'admin');", user_id)
            except Exception as e:
                await message.reply(f"❌ Не удалось отправить сообщение пользователю: {e}")

# --- ЗАПУСК ---
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())