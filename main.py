import os
import logging
import asyncpg
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.enums import ParseMode

# --- НАСТРОЙКА ЛОГИРОВАНИЯ ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", 0)) if os.getenv("ADMIN_CHAT_ID") else None

OWNER_ID = 8674242517

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

db_pool = None

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
                CREATE TABLE IF NOT EXISTS messages (id SERIAL PRIMARY KEY, user_id BIGINT, sender_type TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS admin_actions (id SERIAL PRIMARY KEY, admin_id BIGINT, admin_username TEXT, target_user_id BIGINT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
            """)
    except Exception as e:
        logger.error(f"Ошибка БД: {e}")

# --- ФУНКЦИИ ПРОВЕРКИ ---
async def get_user_role(user_id: int) -> str:
    if user_id == OWNER_ID: return "owner"
    if not db_pool: return "user"
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT role, rest_until FROM users WHERE user_id = $1;", user_id)
            if not row: return "user"
            if row["rest_until"] and row["rest_until"] > datetime.now(): return "user"
            return row["role"] or "user"
    except: return "user"

async def is_admin(user_id: int) -> bool:
    return str(await get_user_role(user_id)).lower() in ["owner", "director", "admin", "intern"]

async def is_director_or_owner(user_id: int) -> bool:
    return str(await get_user_role(user_id)).lower() in ["owner", "director"]

# --- СТАТИСТИКА (ИСПРАВЛЕННАЯ) ---
async def process_admin_stats(message: types.Message):
    try:
        if not await is_admin(message.from_user.id): return
        if not db_pool: return

        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = now - timedelta(days=7)
        month_start = now - timedelta(days=30)

        async with db_pool.acquire() as conn:
            day_rows = await conn.fetch("SELECT admin_id, admin_username, COUNT(*) as count FROM admin_actions WHERE created_at >= $1 GROUP BY admin_id, admin_username ORDER BY count DESC;", today_start)
            week_rows = await conn.fetch("SELECT admin_id, admin_username, COUNT(*) as count FROM admin_actions WHERE created_at >= $1 GROUP BY admin_id, admin_username ORDER BY count DESC;", week_start)
            month_rows = await conn.fetch("SELECT admin_id, admin_username, COUNT(*) as count FROM admin_actions WHERE created_at >= $1 GROUP BY admin_id, admin_username ORDER BY count DESC;", month_start)
            total_rows = await conn.fetch("SELECT admin_id, admin_username, COUNT(*) as count FROM admin_actions GROUP BY admin_id, admin_username ORDER BY count DESC;")

        def format_rows(rows):
            if not rows: return "<i>Пока нет данных</i>\n"
            res = ""
            for idx, r in enumerate(rows, 1):
                d = dict(r)
                name = f"@{d.get('admin_username')}" if d.get('admin_username') else f"ID: {d.get('admin_id')}"
                res += f"{idx}. {name} — <b>{d.get('count')}</b>\n"
            return res

        text = (
            "📊 <b>Статистика работы администрации:</b>\n\n"
            f"📅 <b>За сегодня:</b>\n{format_rows(day_rows)}\n"
            f"📈 <b>За неделю:</b>\n{format_rows(week_rows)}\n"
            f"🗓 <b>За месяц:</b>\n{format_rows(month_rows)}\n"
            f"🏆 <b>Всего:</b>\n{format_rows(total_rows)}"
        )
        await message.reply(text, parse_mode=ParseMode.HTML)
    except Exception as e:
        await message.reply(f"❌ Ошибка: {str(e)}")

@dp.message(Command("adminstats"))
async def admin_stats_cmd(message: types.Message): await process_admin_stats(message)

@dp.message(F.text.lower().startswith(".астат"))
async def admin_stats_dot(message: types.Message): await process_admin_stats(message)

# --- БАЗОВЫЕ КОМАНДЫ ---
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    if db_pool:
        async with db_pool.acquire() as conn:
            await conn.execute("INSERT INTO users (user_id, username, role) VALUES ($1, $2, 'user') ON CONFLICT (user_id) DO NOTHING;", message.from_user.id, message.from_user.username)
    await message.reply("Привет! Пиши \"привет общение/поддержка/уни\" и к тебе придет админ.")

# --- ЗАПУСК ---
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())