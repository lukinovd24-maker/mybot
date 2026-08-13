import os
import logging
import asyncpg
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
                    topic_id INT
                );
                ALTER TABLE users ADD COLUMN IF NOT EXISTS topic_id INT;
                ALTER TABLE users ADD COLUMN IF NOT EXISTS is_banned BOOLEAN DEFAULT FALSE;

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

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
async def get_user_role(user_id: int) -> str:
    if user_id == OWNER_ID:
        return "owner"
    if not db_pool:
        return "user"
    try:
        async with db_pool.acquire() as conn:
            role = await conn.fetchval("SELECT role FROM users WHERE user_id = $1;", user_id)
            return role or "user"
    except Exception:
        return "user"

async def is_admin(user_id: int) -> bool:
    role = await get_user_role(user_id)
    return role in ["owner", "director", "admin", "intern"]

async def is_top_admin(user_id: int) -> bool:
    role = await get_user_role(user_id)
    return role in ["owner", "director"]

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

# --- КОМАНДА /HELP ---
@dp.message(Command("help"))
async def help_cmd(message: types.Message):
    user_id = message.from_user.id
    user_is_admin = await is_admin(user_id)
    user_is_top = await is_top_admin(user_id)
    
    text = "📌 <b>Список доступных команд:</b>\n\n"
    text += "👤 <b>Пользователям:</b>\n"
    text += "├ /start — Запустить бота\n"
    text += "└ /help — Справка по командам\n\n"
    
    if user_is_admin:
        text += "🛡 <b>Администрации:</b>\n"
        text += "├ /stats — Статистика бота\n"
        text += "├ /ban [ID] — Заблокировать пользователя\n"
        text += "├ /unban [ID] — Разблокировать пользователя\n"
        text += "├ /broadcast [текст] — Рассылка пользователям\n"
        text += "├ /setdirector [ID] — Назначить директора\n"
        text += "├ /setadmin [ID] — Назначить администратора\n"
        text += "├ /setintern [ID] — Назначить стажёра\n"
        text += "└ /demote [ID] — Снять роль до пользователя\n\n"

    if user_is_top:
        text += "🔑 <b>Владельцу и Директору:</b>\n"
        text += "└ <code>.ид юз</code> или <code>.ид @username</code> — Узнать ID пользователя\n\n"
        
    if user_id == OWNER_ID:
        text += "👑 <b>Владельцу:</b>\n"
        text += "└ /setowner — Подтвердить права Владельца в БД\n"

    await message.reply(text, parse_mode=ParseMode.HTML)

# --- КОМАНДА УЗНАТЬ ID (ДЛЯ ВЛАДЕЛЬЦА И ДИРЕКТОРОВ) ---
@dp.message(F.text.lower().startswith(".ид") | Command("id"))
async def get_user_id_cmd(message: types.Message):
    if not await is_top_admin(message.from_user.id):
        await message.reply("❌ Эта команда доступна только Владельцу и Директорам!")
        return

    target_user_id = None
    target_username = None

    # 1. Поиск по юзернейму из текста (.ид @username)
    args = message.text.split()
    if len(args) > 1 and args[1].startswith("@"):
        target_username = args[1].replace("@", "").strip()

    # 2. Поиск по ответу на сообщение (Reply)
    elif message.reply_to_message:
        # Если ответили на пересланное сообщение от пользователя
        if message.reply_to_message.forward_from:
            target_user_id = message.reply_to_message.forward_from.id
            target_username = message.reply_to_message.forward_from.username
        # Если ответили в топике админ-чата
        elif message.message_thread_id and db_pool:
            async with db_pool.acquire() as conn:
                target_user_id = await conn.fetchval("SELECT user_id FROM users WHERE topic_id = $1;", message.message_thread_id)

    # 3. Если команда отправлена в топике без ответа
    elif message.message_thread_id and db_pool:
        async with db_pool.acquire() as conn:
            target_user_id = await conn.fetchval("SELECT user_id FROM users WHERE topic_id = $1;", message.message_thread_id)

    # Ищем в базе данных
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
            "Используйте команду в нужным топике, либо ответьте на сообщение юзера, или напишите: <code>.ид @username</code>", 
            parse_mode=ParseMode.HTML
        )

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
        await message.reply(f"✅ Пользователю <code>{target_id}</code> выдан статус: <b>{role_name}</b>", parse_mode=ParseMode.HTML)

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

# --- ПЕРЕСЫЛКА СООБЩЕНИЙ С СОЗДАНИЕМ ТОПИКА ---
@dp.message(F.chat.type == "private")
async def forward_user_message(message: types.Message):
    if not ADMIN_CHAT_ID:
        return

    user_id = message.from_user.id
    username = message.from_user.username or "нет"
    full_name = message.from_user.full_name

    topic_id = None

    if db_pool:
        async with db_pool.acquire() as conn:
            # Проверка бана
            is_banned = await conn.fetchval("SELECT is_banned FROM users WHERE user_id = $1;", user_id)
            if is_banned:
                await message.reply("🚫 Вы заблокированы и не можете отправлять сообщения.")
                return

            # Получаем id топика
            topic_id = await conn.fetchval("SELECT topic_id FROM users WHERE user_id = $1;", user_id)

            # Если топика нет — создаем новый
            if not topic_id:
                try:
                    topic_title = f"{full_name} (@{username})"[:128]
                    new_topic = await bot.create_forum_topic(chat_id=ADMIN_CHAT_ID, name=topic_title)
                    topic_id = new_topic.message_thread_id

                    # Сохраняем topic_id в базу
                    await conn.execute("""
                        INSERT INTO users (user_id, username, topic_id) 
                        VALUES ($1, $2, $3)
                        ON CONFLICT (user_id) DO UPDATE SET topic_id = $3, username = $2;
                    """, user_id, username, topic_id)
                except Exception as e:
                    logging.error(f"Ошибка создания топика: {e}")
                    topic_id = None

            # Фиксируем сообщение в базе
            await conn.execute("INSERT INTO messages (user_id, sender_type) VALUES ($1, 'user');", user_id)

    # Пересылаем сообщение в топик или в общий чат (если топик создать не удалось)
    try:
        if topic_id:
            await bot.copy_message(chat_id=ADMIN_CHAT_ID, message_thread_id=topic_id, from_chat_id=message.chat.id, message_id=message.message_id)
        else:
            header = f"📩 <b>Новое сообщение</b>\nОт: {full_name} (@{username})\nID: <code>{user_id}</code>\n\n"
            await bot.send_message(ADMIN_CHAT_ID, header + (message.text or "[Медиафайл]"), parse_mode=ParseMode.HTML)
    except Exception as e:
        logging.error(f"Ошибка пересылки сообщения: {e}")

# --- ОТВЕТ АДМИНА ИЗ ТОПИКА ПОЛЬЗОВАТЕЛЮ ---
@dp.message(F.chat.id == ADMIN_CHAT_ID)
async def reply_from_topic(message: types.Message):
    # Игнорируем служебные сообщения и команды
    if not message.message_thread_id or (message.text and (message.text.startswith("/") or message.text.startswith("."))):
        return

    if not db_pool:
        return

    async with db_pool.acquire() as conn:
        # Находим пользователя по ID его топика
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