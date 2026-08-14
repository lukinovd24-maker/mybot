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
            
            # Безопасное добавление колонки admin_tag, если её еще нет
            try:
                await conn.execute("ALTER TABLE users ADD COLUMN admin_tag TEXT;")
            except asyncpg.exceptions.DuplicateColumnError:
                pass
                
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
            await conn.execute(
                "INSERT INTO users (user_id, username, role) VALUES ($1, $2, $3) ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username;", 
                message.from_user.id, message.from_user.username, role
            )
    await message.reply("Привет! Пиши запрос в бот, и админ тебе ответит.")

@dp.message(Command("help", "хелп"))
async def help_cmd(message: types.Message):
    if not await is_admin(message.from_user.id) and not await is_owner(message.from_user.id):
        return

    help_text = (
        "📌 <b>Список доступных команд:</b>\n\n"
        "👑 <b>Владелец:</b>\n"
        "├ /stats — Статистика бота\n"
        "├ /adminstats (или .астат) — Статистика взятых ПЗ\n"
        "├ /check или .чек — Проверить пользователя\n"
        "├ /ban /unban [ID] — Управление банами\n"
        "├ /broadcast [текст] — Рассылка\n"
        "├ /rest [юз/ID] [дни] — Отправить в отпуск\n"
        "├ /addmins [юз/ID] [тег] — Установить админ-тег\n"
        "├ .ид юз — Узнать ID пользователя\n"
        "├ /setdirector [ID] — Назначить директора\n"
        "├ /setadmin [ID] — Назначить администратора\n"
        "├ /setintern [ID] — Назначить стажёра\n"
        "├ /demote [ID] — Понизить до пользователя\n"
        "└ /setowner — Подтвердить права Владельца"
    )
    await message.reply(help_text, parse_mode=ParseMode.HTML)

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

# --- ОБРАБОТЧИК СООБЩЕНИЙ ИЗ АДМИН-ЧАТА (ТОПИКОВ) ---
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
                logger.error(f"Ошибка отправки пользователю: {e}")

# --- ОБРАБОТЧИК ЛИЧНЫХ СООБЩЕНИЙ ОТ ПОЛЬЗОВАТЕЛЕЙ ---
@dp.message(F.chat.type == "private")
async def private_msg(message: types.Message):
    if message.text and message.text.startswith("/"):
        return
        
    user_id = message.from_user.id
    if not db_pool:
        return

    async with db_pool.acquire() as conn:
        is_banned = await conn.fetchval("SELECT is_banned FROM users WHERE user_id = $1;", user_id)
        if is_banned:
            return

        topic_id = await conn.fetchval("SELECT topic_id FROM users WHERE user_id = $1;", user_id)
        
        if not topic_id and ADMIN_CHAT_ID:
            try:
                username_str = f"@{message.from_user.username}" if message.from_user.username else f"ID: {user_id}"
                forum_topic = await bot.create_forum_topic(chat_id=ADMIN_CHAT_ID, name=f"{message.from_user.first_name} ({username_str})")
                topic_id = forum_topic.message_thread_id
                
                await conn.execute("UPDATE users SET topic_id = $1 WHERE user_id = $2;", topic_id, user_id)
            except Exception as e:
                logger.error(f"Не удалось создать топик: {e}")
                topic_id = UNASSIGNED_TOPIC_ID

        if ADMIN_CHAT_ID and topic_id:
            try:
                forwarded = await bot.forward_message(
                    chat_id=ADMIN_CHAT_ID,
                    from_chat_id=user_id,
                    message_id=message.message_id,
                    message_thread_id=topic_id
                )
                await conn.execute(
                    "INSERT INTO messages (user_id, sender_type, user_msg_id, admin_msg_id) VALUES ($1, 'user', $2, $3);",
                    user_id, message.message_id, forwarded.message_id
                )
            except Exception as e:
                logger.error(f"Ошибка пересылки сообщения в админ-чат: {e}")

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())