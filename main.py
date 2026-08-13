import asyncio
import logging
import os
import asyncpg
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart

# --- НАСТРОЙКИ И ПЕРЕМЕННЫЕ ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

# Твой Telegram ID — Главный Владелец
OWNER_ID = 8674242517

if not BOT_TOKEN:
    raise ValueError("Ошибка: Переменная BOT_TOKEN не задана!")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
db_pool = None

# --- РАБОТА С БАЗОЙ ДАННЫХ ---
async def init_db():
    global db_pool
    if DATABASE_URL:
        db_pool = await asyncpg.create_pool(DATABASE_URL)
        async with db_pool.acquire() as conn:
            # Создаем таблицу пользователей с полем роли, если её ещё нет
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    role TEXT DEFAULT 'user'
                );
            """)
        logging.info("База данных PostgreSQL успешно инициализирована.")

async def set_user_role(user_id: int, username: str | None, role: str):
    if db_pool:
        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO users (user_id, username, role)
                VALUES ($1, $2, $3)
                ON CONFLICT (user_id) 
                DO UPDATE SET role = EXCLUDED.role, username = COALESCE(EXCLUDED.username, users.username);
            """, user_id, username, role)

async def get_user_role(user_id: int) -> str:
    if user_id == OWNER_ID:
        return "owner"
    if db_pool:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT role FROM users WHERE user_id = $1;", user_id)
            if row and row['role']:
                return row['role']
    return "user"

# Вспомогательная функция для получения target_id из текста или Reply
def extract_target_user_id(message: types.Message) -> int | None:
    if message.reply_to_message:
        return message.reply_to_message.from_user.id
    
    args = message.text.split()
    if len(args) > 1 and args[1].isdigit():
        return int(args[1])
    
    return None

# --- КОМАНДЫ ДЛЯ ВСЕХ ---
@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    role = await get_user_role(message.from_user.id)
    # Автоматически сохраняем пользователя в базу при старте
    await set_user_role(message.from_user.id, message.from_user.username, role)
    
    role_names = {
        "owner": "👑 Владелец",
        "director": "💼 Директор",
        "admin": "🛡 Администратор",
        "intern": "🔰 Стажёр",
        "user": "👤 Пользователь"
    }
    
    await message.answer(
        f"👋 **Привет, {message.from_user.full_name}!**\n\n"
        f"Твой статус в системе: **{role_names.get(role, '👤 Пользователь')}**"
    )

# --- УПРАВЛЕНИЕ РОЛЯМИ ---

# 👑 1. Назначить ДИРЕКТОРА (Только Владелец)
@dp.message(Command("set_director"))
async def set_director_cmd(message: types.Message):
    if message.from_user.id != OWNER_ID:
        await message.reply("❌ Назначать Директоров может только Владелец бота!")
        return

    target_id = extract_target_user_id(message)
    if not target_id:
        await message.reply("⚠️ Ответьте на сообщение пользователя или напишите: `/set_director 123456789`")
        return

    await set_user_role(target_id, None, "director")
    await message.reply(f"✅ Пользователю `{target_id}` успешно присвоена роль **Директор** 💼")

# ⭐️ 2. Назначить АДМИНА (Владелец и Директора)
@dp.message(Command("set_admin"))
async def set_admin_cmd(message: types.Message):
    user_role = await get_user_role(message.from_user.id)
    
    if user_role not in ["owner", "director"]:
        await message.reply("❌ Назначать Администраторов могут только Директора и Владелец!")
        return

    target_id = extract_target_user_id(message)
    if not target_id:
        await message.reply("⚠️ Ответьте на сообщение пользователя или напишите: `/set_admin 123456789`")
        return

    await set_user_role(target_id, None, "admin")
    await message.reply(f"✅ Пользователю `{target_id}` успешно присвоена роль **Администратор** 🛡")

# 🔰 3. Назначить СТАЖЁРА (Владелец и Директора)
@dp.message(Command("set_intern"))
async def set_intern_cmd(message: types.Message):
    user_role = await get_user_role(message.from_user.id)
    
    if user_role not in ["owner", "director"]:
        await message.reply("❌ Назначать Стажёров могут только Директора и Владелец!")
        return

    target_id = extract_target_user_id(message)
    if not target_id:
        await message.reply("⚠️ Ответьте на сообщение пользователя или напишите: `/set_intern 123456789`")
        return

    await set_user_role(target_id, None, "intern")
    await message.reply(f"✅ Пользователю `{target_id}` успешно присвоена роль **Стажёр** 🔰")

# 🚫 4. Снять роль (Разжаловать до обычного пользователя)
@dp.message(Command("demote"))
async def demote_cmd(message: types.Message):
    user_role = await get_user_role(message.from_user.id)
    
    if user_role not in ["owner", "director"]:
        await message.reply("❌ Снимать роли могут только Директора и Владелец!")
        return

    target_id = extract_target_user_id(message)
    if not target_id:
        await message.reply("⚠️ Ответьте на сообщение пользователя или напишите: `/demote 123456789`")
        return

    if target_id == OWNER_ID:
        await message.reply("❌ Нельзя снять роль с Владельца бота!")
        return

    await set_user_role(target_id, None, "user")
    await message.reply(f"🗑 Роль с пользователя `{target_id}` снята. Теперь он обычный пользователь.")

# --- ЗАПУСК БОТА ---
async def main():
    logging.basicConfig(level=logging.INFO)
    await init_db()
    print("Бот успешно запущен!")
    await dp.start_polling(bot, allowed_updates=["message"])

if __name__ == "__main__":
    asyncio.run(main())