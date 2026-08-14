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

UNASSIGNED_TOPIC_ID = 765
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
            # 1. Создаем таблицу, если ее нет
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY, 
                    username TEXT, 
                    role TEXT DEFAULT 'user', 
                    is_banned BOOLEAN DEFAULT FALSE, 
                    topic_id INT, 
                    rest_until TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS messages (id SERIAL PRIMARY KEY, user_id BIGINT, sender_type TEXT, user_msg_id INT, admin_msg_id INT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS admin_actions (id SERIAL PRIMARY KEY, admin_id BIGINT, admin_username TEXT, target_user_id BIGINT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
            """)
            
            # 2. Безопасно добавляем колонку admin_tag, если её ещё нет в существующей таблице
            try:
                await conn.execute("ALTER TABLE users ADD COLUMN admin_tag TEXT;")
            except asyncpg.exceptions.DuplicateColumnError:
                pass # Колонка уже существует, всё в порядке
                
    except Exception as e:
        logger.error(f"Ошибка БД: {e}")

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
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
    return (await get_user_role(user_id)) in ["owner", "director", "admin", "intern"]

async def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID or (await get_user_role(user_id)) == "owner"

async def get_target_user_id(conn, arg: str) -> int:
    arg = arg.strip()
    if arg.isdigit(): return int(arg)
    if arg.startswith("@"): arg = arg[1:]
    row = await conn.fetchrow("SELECT user_id FROM users WHERE LOWER(username) = LOWER($1);", arg)
    return row["user_id"] if row else None

# --- КОМАНДЫ ---

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    role = "owner" if message.from_user.id == OWNER_ID else "user"
    if db_pool:
        async with db_pool.acquire() as conn:
            await conn.execute("INSERT INTO users (user_id, username, role) VALUES ($1, $2, $3) ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username;", message.from_user.id, message.from_user.username, role)
    await message.reply("Привет! Пиши запрос в бот, и админ тебе ответит.")

@dp.message(Command("addmins"))
async def addmins_cmd(message: types.Message, command: CommandObject):
    if not await is_owner(message.from_user.id): return
    if not db_pool or not command.args:
        await message.reply("❌ Формат: /addmins [юз/ID] [тег]")
        return
    
    args = command.args.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("❌ Нужно указать пользователя и тег. Пример: /addmins @user #тег")
        return
    
    target_arg, admin_tag = args[0], args[1].strip()
    async with db_pool.acquire() as conn:
        target_id = await get_target_user_id(conn, target_arg)
        if not target_id:
            await message.reply("❌ Пользователь не найден.")
            return
        await conn.execute("UPDATE users SET admin_tag = $1 WHERE user_id = $2;", admin_tag, target_id)
        await message.reply(f"✅ Установлен тег <b>{admin_tag}</b> для пользователя <code>{target_id}</code>", parse_mode=ParseMode.HTML)

@dp.message(Command("stats"))
async def stats_cmd(message: types.Message):
    if not await is_admin(message.from_user.id): return
    async with db_pool.acquire() as conn:
        users_count = await conn.fetchval("SELECT COUNT(*) FROM users;")
        await message.reply(f"📊 Всего пользователей: {users_count}")

# --- ОБРАБОТЧИК СООБЩЕНИЙ ---
@dp.message(F.chat.id == ADMIN_CHAT_ID)
async def reply_from_topic(message: types.Message):
    if not message.message_thread_id or (message.text and message.text.startswith("/")): return
    
    async with db_pool.acquire() as conn:
        user_id = await conn.fetchval("SELECT user_id FROM users WHERE topic_id = $1;", message.message_thread_id)
        if user_id:
            admin_tag = await conn.fetchval("SELECT admin_tag FROM users WHERE user_id = $1;", message.from_user.id)
            tag = admin_tag if admin_tag else f"@{message.from_user.username}"
            
            text = f"<b>[{tag}]</b> {message.text}" if message.text else message.caption
            try:
                await bot.send_message(user_id, text, parse_mode=ParseMode.HTML)
            except Exception as e:
                logger.error(f"Ошибка: {e}")

@dp.message(F.chat.type == "private")
async def private_msg(message: types.Message):
    # Здесь ваша логика личных сообщений (пересылка в чат администраторов)
    pass

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())