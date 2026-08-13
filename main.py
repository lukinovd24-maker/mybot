import os
import logging
import asyncpg
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.enums import ParseMode

# --- НАСТРОЙКА ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
OWNER_ID = 8674242517

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
db_pool = None

async def init_db():
    global db_pool
    if not DATABASE_URL: return
    db_pool = await asyncpg.create_pool(DATABASE_URL)
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, username TEXT, role TEXT DEFAULT 'user', is_banned BOOLEAN DEFAULT FALSE, topic_id INT, rest_until TIMESTAMP);
            CREATE TABLE IF NOT EXISTS messages (id SERIAL PRIMARY KEY, user_id BIGINT, sender_type TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS admin_actions (id SERIAL PRIMARY KEY, admin_id BIGINT, admin_username TEXT, target_user_id BIGINT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        """)

async def is_admin(user_id: int) -> bool:
    if user_id == OWNER_ID: return True
    if not db_pool: return False
    try:
        async with db_pool.acquire() as conn:
            role = await conn.fetchval("SELECT role FROM users WHERE user_id = $1;", user_id)
            return str(role).lower() in ["director", "admin", "intern"]
    except: return False

# --- СТАТИСТИКА БОТА (/stats) ---
@dp.message(Command("stats"))
async def stats_cmd(message: types.Message):
    if not db_pool: return
    async with db_pool.acquire() as conn:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users;") or 0
        banned = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_banned = TRUE;") or 0
        owners = await conn.fetchval("SELECT COUNT(*) FROM users WHERE role = 'owner';") or 0
        dirs = await conn.fetchval("SELECT COUNT(*) FROM users WHERE role = 'director';") or 0
        admins = await conn.fetchval("SELECT COUNT(*) FROM users WHERE role = 'admin';") or 0
        interns = await conn.fetchval("SELECT COUNT(*) FROM users WHERE role = 'intern';") or 0
        users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE role = 'user';") or 0
        
        u_msgs = await conn.fetchval("SELECT COUNT(*) FROM messages WHERE sender_type = 'user';") or 0
        a_msgs = await conn.fetchval("SELECT COUNT(*) FROM messages WHERE sender_type = 'admin';") or 0
        
    text = (
        "📊 <b>Полная статистика бота:</b>\n\n"
        "👥 <b>Пользователи:</b>\n"
        f"├ Всего пользователей: <b>{total_users}</b>\n"
        f"├ 🍏 Активных (чистых): <b>{total_users - banned}</b>\n"
        f"└ 🚫 Забаненных: <b>{banned}</b>\n\n"
        "🎭 <b>Разделение по ролям:</b>\n"
        f"├ 👑 Владелец: <b>{owners}</b>\n"
        f"├ 💼 Директоров: <b>{dirs}</b>\n"
        f"├ 🛡 Администраторов: <b>{admins}</b>\n"
        f"├ 🔰 Стажёров: <b>{interns}</b>\n"
        f"└ 👤 Пользователей: <b>{users}</b>\n\n"
        "✉️ <b>Сообщения и активность:</b>\n"
        f"├ 📩 От пользователей: <b>{u_msgs}</b>\n"
        f"├ 📤 От администраторов: <b>{a_msgs}</b>\n"
        f"└ 💬 Всего сообщений: <b>{u_msgs + a_msgs}</b>"
    )
    await message.reply(text, parse_mode=ParseMode.HTML)

# --- АДМИН СТАТИСТИКА ---
async def process_admin_stats(message: types.Message):
    if not await is_admin(message.from_user.id): return
    try:
        now = datetime.now()
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("SELECT admin_id, admin_username, COUNT(*) as count FROM admin_actions WHERE created_at >= $1 GROUP BY admin_id, admin_username ORDER BY count DESC;", today)
        res = "📊 <b>Статистика админов (ПЗ) за сегодня:</b>\n"
        for idx, r in enumerate(rows, 1):
            d = dict(r)
            res += f"{idx}. @{d['admin_username'] or 'ID:'+str(d['admin_id'])} — <b>{d['count']}</b>\n"
        await message.reply(res or "Данных нет", parse_mode=ParseMode.HTML)
    except Exception as e:
        await message.reply(f"Ошибка: {e}")

@dp.message(Command("adminstats"))
async def admin_stats_cmd(message: types.Message): await process_admin_stats(message)
@dp.message(F.text.lower().startswith(".астат"))
async def admin_stats_dot(message: types.Message): await process_admin_stats(message)

# --- ЗАПУСК ---
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    await message.reply("Привет! Пиши \"привет общение/поддержка/уни\" и к тебе придет админ.")

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())