import os
import logging
import asyncio
import asyncpg
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

# --- НАСТРОЙКА ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", 0)) if os.getenv("ADMIN_CHAT_ID") else None
UNASSIGNED_TOPIC_ID = 765 
OWNER_ID = 8674242517

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
db_pool = None

# --- СОСТОЯНИЯ ---
class BroadcastState(StatesGroup):
    waiting_for_content = State()
    waiting_for_confirm = State()

broadcast_data_cache = {}

# --- БД ---
async def init_db():
    global db_pool
    if not DATABASE_URL: return
    try:
        db_pool = await asyncpg.create_pool(DATABASE_URL)
        async with db_pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT UNIQUE, 
                    username TEXT, 
                    role TEXT DEFAULT 'user', 
                    is_banned BOOLEAN DEFAULT FALSE, 
                    topic_id INT, 
                    admin_tag TEXT, 
                    rest_until TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS messages (id SERIAL PRIMARY KEY, user_id BIGINT, sender_type TEXT, user_msg_id INT, admin_msg_id INT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS admin_actions (id SERIAL PRIMARY KEY, admin_id BIGINT, admin_username TEXT, target_user_id BIGINT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
            """)
    except Exception as e: logger.error(f"Ошибка БД: {e}")

async def get_user_role(user_id: int) -> str:
    if user_id == OWNER_ID: return "owner"
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT role FROM users WHERE user_id = $1;", user_id)
            return row["role"] if row else "user"
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

@dp.message(Command("id", "ид"))
async def get_id_cmd(message: types.Message, command: CommandObject):
    if not await is_admin(message.from_user.id): return
    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
    elif command.args:
        async with db_pool.acquire() as conn:
            target_id = await get_target_user_id(conn, command.args)
    else:
        target_id = message.from_user.id
    
    await message.reply(f"🆔 ID пользователя: <code>{target_id}</code>", parse_mode=ParseMode.HTML)

@dp.message(Command("check", "чек"))
async def check_cmd(message: types.Message, command: CommandObject):
    if not await is_admin(message.from_user.id): return
    target_arg = command.args or (message.reply_to_message.from_user.username if message.reply_to_message else None)
    if not target_arg: return await message.reply("Укажите пользователя.")
    
    async with db_pool.acquire() as conn:
        uid = await get_target_user_id(conn, target_arg)
        user = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1;", uid)
    
    if not user: return await message.reply("Пользователь не найден.")
    await message.reply(f"👤 <b>Проверка:</b>\n├ ID: <code>{user['user_id']}</code>\n├ Роль: {user['role']}\n└ Бан: {'Да' if user['is_banned'] else 'Нет'}", parse_mode=ParseMode.HTML)

@dp.message(Command("help"))
async def help_cmd(message: types.Message):
    if not await is_admin(message.from_user.id): return
    await message.reply("📌 <b>Команды:</b>\n/stats /adminstats /adminlist /broadcast /id /check /addmins", parse_mode=ParseMode.HTML)

@dp.message(Command("broadcast"))
async def broadcast_start(message: types.Message):
    if not await is_admin(message.from_user.id): return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Всем", callback_data="bc_target_all")],
        [InlineKeyboardButton(text="🔥 Активным", callback_data="bc_target_active")]
    ])
    await message.reply("Выберите аудиторию:", reply_markup=kb)

@dp.callback_query(F.data.startswith("bc_target_"))
async def broadcast_select(callback: types.CallbackQuery, state: FSMContext):
    target = callback.data.split("_")[2]
    broadcast_data_cache[callback.from_user.id] = {"target": target}
    await state.set_state(BroadcastState.waiting_for_content)
    await callback.message.edit_text("Отправьте контент для рассылки:")

@dp.message(BroadcastState.waiting_for_content)
async def broadcast_get(message: types.Message, state: FSMContext):
    broadcast_data_cache[message.from_user.id]["message"] = message
    await state.set_state(BroadcastState.waiting_for_confirm)
    await message.reply("Контент принят. Отправьте /send для запуска.")

@dp.message(Command("send"), BroadcastState.waiting_for_confirm)
async def broadcast_execute(message: types.Message, state: FSMContext):
    data = broadcast_data_cache.get(message.from_user.id)
    msg = data["message"]
    async with db_pool.acquire() as conn:
        users = await conn.fetch("SELECT user_id FROM users WHERE is_banned = FALSE;")
    for u in users:
        try: await msg.send_copy(chat_id=u["user_id"])
        except: pass
    await message.reply("Рассылка завершена!")
    await state.clear()

# --- ПЕРЕСЫЛКА ---
@dp.message(F.chat.type == "private")
async def private_msg(message: types.Message):
    user_id = message.from_user.id
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT topic_id FROM users WHERE user_id = $1;", user_id)
        if not user:
            topic = await bot.create_forum_topic(chat_id=ADMIN_CHAT_ID, name=f"ПЗ: {message.from_user.first_name}")
            await conn.execute("INSERT INTO users (user_id, topic_id, username) VALUES ($1, $2, $3);", user_id, topic.message_thread_id, message.from_user.username)
            topic_id = topic.message_thread_id
        else: topic_id = user['topic_id']
        if not message.text or not message.text.startswith("/"):
            await bot.forward_message(ADMIN_CHAT_ID, user_id, message.message_id, message_thread_id=topic_id)

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())