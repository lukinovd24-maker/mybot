import os
import logging
import asyncpg
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

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

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
async def init_db():
    global db_pool
    if not DATABASE_URL: return
    try:
        db_pool = await asyncpg.create_pool(DATABASE_URL)
        async with db_pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY, username TEXT, role TEXT DEFAULT 'user', 
                    is_banned BOOLEAN DEFAULT FALSE, topic_id INT, rest_until TIMESTAMP, admin_tag TEXT
                );
                CREATE TABLE IF NOT EXISTS messages (id SERIAL PRIMARY KEY, user_id BIGINT, sender_type TEXT, user_msg_id INT, admin_msg_id INT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS admin_actions (id SERIAL PRIMARY KEY, admin_id BIGINT, admin_username TEXT, target_user_id BIGINT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
            """)
            try: await conn.execute("ALTER TABLE users ADD COLUMN admin_tag TEXT;")
            except: pass
    except Exception as e: logger.error(f"Ошибка БД: {e}")

async def get_user_role(user_id: int) -> str:
    if user_id == OWNER_ID: return "owner"
    if not db_pool: return "user"
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT role, rest_until FROM users WHERE user_id = $1;", user_id)
            if not row: return "user"
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

# --- КОМАНДЫ И ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO users (user_id, username) VALUES ($1, $2) ON CONFLICT (user_id) DO NOTHING;", message.from_user.id, message.from_user.username)
    await message.reply("Привет! Пиши запрос в бот, и админ тебе ответит.")

@dp.message(F.chat.type == "private")
async def private_msg(message: types.Message):
    if message.text and message.text.startswith("/"): return
    user_id = message.from_user.id
    
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT topic_id FROM users WHERE user_id = $1;", user_id)
        
        # Если это новое сообщение (нет топика)
        if not user or not user['topic_id']:
            # Создаем клавиатуру "Взять ПЗ"
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Взять ПЗ", callback_data=f"take_pz_{user_id}")]
            ])
            
            # Отправляем в админ-чат уведомление
            await bot.send_message(
                ADMIN_CHAT_ID, 
                f"🆕 <b>Новый запрос!</b>\n👤 Пользователь: @{message.from_user.username or 'Без ника'} (<code>{user_id}</code>)\n💬 Сообщение: {message.text or 'Вложение'}",
                reply_markup=keyboard, parse_mode=ParseMode.HTML
            )
            await message.reply("Ваш запрос принят, ожидайте ответа оператора.")
        else:
            # Если топик уже есть - пересылаем
            await bot.forward_message(ADMIN_CHAT_ID, user_id, message.message_id, message_thread_id=user['topic_id'])

# --- КНОПКА "ВЗЯТЬ ПЗ" ---
@dp.callback_query(F.data.startswith("take_pz_"))
async def take_pz(callback: types.CallbackQuery):
    target_id = int(callback.data.split("_")[2])
    admin_id = callback.from_user.id
    
    async with db_pool.acquire() as conn:
        # Создаем топик
        forum_topic = await bot.create_forum_topic(ADMIN_CHAT_ID, name=f"User {target_id}")
        await conn.execute("UPDATE users SET topic_id = $1 WHERE user_id = $2;", forum_topic.message_thread_id, target_id)
        await conn.execute("INSERT INTO admin_actions (admin_id, admin_username, target_user_id) VALUES ($1, $2, $3);", admin_id, callback.from_user.username, target_id)
        
    await callback.message.edit_text(f"✅ ПЗ взял администратор @{callback.from_user.username}")
    await callback.answer("Вы взяли ПЗ!")

# --- ЗАПУСК ---
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())