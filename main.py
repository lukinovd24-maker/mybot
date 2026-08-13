import os
import logging
import asyncpg
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.enums import ParseMode

# --- НАСТРОЙКА ЛОГИРОВАНИЯ ---
logging.basicConfig(level=logging.INFO)

# --- ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

# ⚠️ УКАЖИ ЗДЕСЬ СВОЙ TELEGRAM ID (например: 1234567890)
OWNER_ID = 8674242517  # Замени эти цифры на свой ID в Telegram!

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
            # Таблица пользователей
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
            """)
            
            # Таблица сообщений
            await conn.execute("""
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

# --- ПОЛУЧЕНИЕ РОЛИ ПОЛЬЗОВАТЕЛЯ ---
async def get_user_role(user_id: int) -> str:
    # 1. Если это твой ID — ты ВСЕГДА владелец
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

# --- КОМАНДА /START ---
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    role = "owner" if message.from_user.id == OWNER_ID else "user"
    
    if db_pool:
        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO users (user_id, username, role) 
                VALUES ($1, $2, $3)
                ON CONFLICT (user_id) DO UPDATE SET 
                    username = EXCLUDED.username,
                    role = CASE WHEN users.user_id = $1 AND $3 = 'owner' THEN 'owner' ELSE users.role END;
            """, message.from_user.id, message.from_user.username, role)
            
    await message.reply("👋 Привет! Бот работает и готов к приёму сообщений.")

# --- КОМАНДА ДЛЯ ВЫДАЧИ ВЛАДЕЛЬЦА СЕБЕ В БазеДанных ---
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
        await message.reply("👑 Ваша роль 'Владелец' успешно записана в базу данных!")
    else:
        await message.reply("⚠️ База данных недоступна.")

# --- КОМАНДА /STATS ---
@dp.message(Command("stats"))
async def stats_cmd(message: types.Message):
    user_role = await get_user_role(message.from_user.id)
    if user_role not in ["owner", "director", "admin"]:
        await message.reply("❌ Просматривать статистику могут только Администраторы, Директора и Владелец!")
        return

    if not db_pool:
        await message.reply(f"⚠️ <b>База данных недоступна!</b>\n<code>{db_error_msg}</code>", parse_mode=ParseMode.HTML)
        return

    try:
        async with db_pool.acquire() as conn:
            # 1. Пользователи и баны
            total_users = await conn.fetchval("SELECT COUNT(*) FROM users;") or 0
            banned_users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_banned = TRUE;") or 0
            clean_users = total_users - banned_users

            # 2. Роли
            owners = await conn.fetchval("SELECT COUNT(*) FROM users WHERE role = 'owner';") or 1
            directors = await conn.fetchval("SELECT COUNT(*) FROM users WHERE role = 'director';") or 0
            admins = await conn.fetchval("SELECT COUNT(*) FROM users WHERE role = 'admin';") or 0
            interns = await conn.fetchval("SELECT COUNT(*) FROM users WHERE role = 'intern';") or 0
            simple_users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE role = 'user';") or 0

            # 3. Сообщения
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

    except Exception as e:
        logging.error(f"Ошибка при запросе статистики: {e}")
        await message.reply(f"⚠️ Ошибка запроса к БД:\n<code>{e}</code>", parse_mode=ParseMode.HTML)

# --- ЗАПУСК БОТА ---
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())