import os
import logging
import asyncpg
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# --- НАСТРОЙКА ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", 0)) if os.getenv("ADMIN_CHAT_ID") else None
OWNER_ID = 8674242517

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
db_pool = None

# --- ИНИЦИАЛИЗАЦИЯ БД ---
async def init_db():
    global db_pool
    if not DATABASE_URL: return
    try:
        db_pool = await asyncpg.create_pool(DATABASE_URL)
        async with db_pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY, username TEXT, role TEXT DEFAULT 'user', 
                    is_banned BOOLEAN DEFAULT FALSE, topic_id INT, admin_tag TEXT
                );
                CREATE TABLE IF NOT EXISTS messages (id SERIAL PRIMARY KEY, user_id BIGINT, sender_type TEXT, user_msg_id INT, admin_msg_id INT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS admin_actions (id SERIAL PRIMARY KEY, admin_id BIGINT, admin_username TEXT, target_user_id BIGINT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
            """)
            try: await conn.execute("ALTER TABLE users ADD COLUMN admin_tag TEXT;")
            except: pass
    except Exception as e: logger.error(f"Ошибка БД: {e}")

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
async def is_owner(user_id: int) -> bool:
    if user_id == OWNER_ID: return True
    async with db_pool.acquire() as conn:
        role = await conn.fetchval("SELECT role FROM users WHERE user_id = $1;", user_id)
        return role == "owner"

async def get_target_user_id(conn, arg: str) -> int:
    arg = arg.strip()
    if arg.isdigit(): return int(arg)
    if arg.startswith("@"): arg = arg[1:]
    row = await conn.fetchrow("SELECT user_id FROM users WHERE LOWER(username) = LOWER($1);", arg)
    return row["user_id"] if row else None

# --- КОМАНДА /addmins ---
@dp.message(Command("addmins"))
async def addmins_cmd(message: types.Message, command: CommandObject):
    if not await is_owner(message.from_user.id): return
    if not command.args or len(command.args.split(maxsplit=1)) < 2:
        await message.reply("❌ Формат: /addmins [юз/ID] [тег]\nПример: /addmins @user #helper")
        return
    
    args = command.args.split(maxsplit=1)
    target_arg, admin_tag = args[0], args[1].strip()
    if not admin_tag.startswith("#"): admin_tag = f"#{admin_tag}"

    async with db_pool.acquire() as conn:
        target_id = await get_target_user_id(conn, target_arg)
        if not target_id:
            await message.reply("❌ Пользователь не найден.")
            return
        await conn.execute("UPDATE users SET role = 'admin', admin_tag = $1 WHERE user_id = $2;", admin_tag, target_id)
        await message.reply(f"✅ Пользователь <code>{target_id}</code> теперь админ с тегом <b>{admin_tag}</b>", parse_mode=ParseMode.HTML)

# --- ОБРАБОТКА ЛИЧКИ ---
@dp.message(F.chat.type == "private")
async def private_msg(message: types.Message):
    if message.text and message.text.startswith("/"): return
    user_id = message.from_user.id
    
    async with db_pool.acquire() as conn:
        # Регистрируем пользователя, если новый
        await conn.execute("INSERT INTO users (user_id, username) VALUES ($1, $2) ON CONFLICT (user_id) DO NOTHING;", user_id, message.from_user.username)
        user = await conn.fetchrow("SELECT topic_id FROM users WHERE user_id = $1;", user_id)
        
        if not user or not user['topic_id']:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Взять ПЗ", callback_data=f"take_pz_{user_id}")]
            ])
            await bot.send_message(
                ADMIN_CHAT_ID, 
                f"🆕 <b>Новый запрос!</b>\n👤 Пользователь: @{message.from_user.username or 'Без ника'}\n💬 Сообщение: {message.text or 'Вложение'}",
                reply_markup=keyboard, parse_mode=ParseMode.HTML
            )
        else:
            await bot.forward_message(ADMIN_CHAT_ID, user_id, message.message_id, message_thread_id=user['topic_id'])

# --- КНОПКА ВЗЯТИЯ ПЗ ---
@dp.callback_query(F.data.startswith("take_pz_"))
async def take_pz(callback: types.CallbackQuery):
    target_id = int(callback.data.split("_")[2])
    
    async with db_pool.acquire() as conn:
        user_info = await conn.fetchrow("SELECT username FROM users WHERE user_id = $1;", target_id)
        name = user_info['username'] if user_info and user_info['username'] else f"ID {target_id}"
        
        forum_topic = await bot.create_forum_topic(ADMIN_CHAT_ID, name=f"ПЗ: {name}")
        await conn.execute("UPDATE users SET topic_id = $1 WHERE user_id = $2;", forum_topic.message_thread_id, target_id)
        await conn.execute("INSERT INTO admin_actions (admin_id, admin_username, target_user_id) VALUES ($1, $2, $3);", 
                           callback.from_user.id, callback.from_user.username, target_id)
        
    await callback.message.edit_text(f"✅ ПЗ взял администратор @{callback.from_user.username}\n📂 Создан топик: <b>ПЗ: {name}</b>", parse_mode=ParseMode.HTML)
    await callback.answer("Топик создан!")

# --- ОТВЕТ ИЗ ТОПИКА ---
@dp.message(F.chat.id == ADMIN_CHAT_ID)
async def reply_from_topic(message: types.Message):
    if not message.message_thread_id or (message.text and message.text.startswith("/")): return
    async with db_pool.acquire() as conn:
        user_id = await conn.fetchval("SELECT user_id FROM users WHERE topic_id = $1;", message.message_thread_id)
        if user_id:
            tag = await conn.fetchval("SELECT admin_tag FROM users WHERE user_id = $1;", message.from_user.id) or f"@{message.from_user.username}"
            text = f"<b>[{tag}]</b> {message.text}" if message.text else message.caption
            await bot.send_message(user_id, text, parse_mode=ParseMode.HTML)

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())