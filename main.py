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

# --- ССЫЛКИ ИЛИ FILE_ID КАРТИНОК ДЛЯ КАЖДОЙ РОЛИ ---
# Вставь сюда полученные file_id вместо текста в кавычках:
ROLE_IMAGES = {
    "owner": "https://via.placeholder.com/800x600.png?text=Owner",       # Картинка для Владельца
    "director": "https://via.placeholder.com/800x600.png?text=Director", # Картинка для Директора
    "admin": "https://via.placeholder.com/800x600.png?text=Admin",       # Картинка для Админа
    "intern": "https://via.placeholder.com/800x600.png?text=Intern",     # Картинка для Стажёра
    "user": "https://via.placeholder.com/800x600.png?text=User"          # Картинка для Пользователя
}

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

def extract_target_user_id(message: types.Message) -> int | None:
    if message.reply_to_message:
        return message.reply_to_message.from_user.id
    args = message.text.split()
    if len(args) > 1 and args[1].isdigit():
        return int(args[1])
    return None

# --- ПОЛУЧЕНИЕ FILE_ID КАРТИНОК (Только для тебя) ---
@dp.message(F.photo, F.from_user.id == OWNER_ID)
async def get_photo_file_id(message: types.Message):
    # Самое высокое качество фото всегда последнее в списке [-1]
    photo_id = message.photo[-1].file_id
    await message.reply(
        f"🖼 **`file_id` твоей картинки:**\n\n"
        f"`{photo_id}`\n\n"
        f"📌 *Нажми на код выше, чтобы скопировать его!*"
    )

# --- КОМАНДА /START С КАРТИНКАМИ ---
@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    role = await get_user_role(message.from_user.id)
    await set_user_role(message.from_user.id, message.from_user.username, role)
    
    role_names = {
        "owner": "👑 Владелец",
        "director": "💼 Директор",
        "admin": "🛡 Администратор",
        "intern": "🔰 Стажёр",
        "user": "👤 Пользователь"
    }
    
    # Берем нужную картинку
    photo = ROLE_IMAGES.get(role, ROLE_IMAGES["user"])
    
    caption_text = (
        f"👋 **Привет, {message.from_user.full_name}!**\n\n"
        f"Твой статус в системе: **{role_names.get(role, '👤 Пользователь')}**"
    )

    try:
        await message.answer_photo(photo=photo, caption=caption_text, parse_mode="Markdown")
    except Exception:
        # Если картинка не загрузилась — отправляем просто текст
        await message.answer(caption_text, parse_mode="Markdown")

# --- УПРАВЛЕНИЕ РОЛЯМИ ---
@dp.message(Command("set_director"))
async def set_director_cmd(message: types.Message):
    if message.from_user.id != OWNER_ID:
        await message.reply("❌ Назначать Директоров может только Владелец бота!")
        return

    target_id = extract_target_user_id(message)
    if not target_id:
        await message.reply("⚠️ Ответьте на сообщение или напишите: `/set_director 123456789`")
        return

    await set_user_role(target_id, None, "director")
    await message.reply(f"✅ Пользователю `{target_id}` присвоена роль **Директор** 💼")

@dp.message(Command("set_admin"))
async def set_admin_cmd(message: types.Message):
    user_role = await get_user_role(message.from_user.id)
    if user_role not in ["owner", "director"]:
        await message.reply("❌ Назначать Администраторов могут только Директора и Владелец!")
        return

    target_id = extract_target_user_id(message)
    if not target_id:
        await message.reply("⚠️ Ответьте на сообщение или напишите: `/set_admin 123456789`")
        return

    await set_user_role(target_id, None, "admin")
    await message.reply(f"✅ Пользователю `{target_id}` присвоена роль **Администратор** 🛡")

@dp.message(Command("set_intern"))
async def set_intern_cmd(message: types.Message):
    user_role = await get_user_role(message.from_user.id)
    if user_role not in ["owner", "director"]:
        await message.reply("❌ Назначать Стажёров могут только Директора и Владелец!")
        return

    target_id = extract_target_user_id(message)
    if not target_id:
        await message.reply("⚠️ Ответьте на сообщение или напишите: `/set_intern 123456789`")
        return

    await set_user_role(target_id, None, "intern")
    await message.reply(f"✅ Пользователю `{target_id}` присвоена роль **Стажёр** 🔰")

@dp.message(Command("demote"))
async def demote_cmd(message: types.Message):
    user_role = await get_user_role(message.from_user.id)
    if user_role not in ["owner", "director"]:
        await message.reply("❌ Снимать роли могут только Директора и Владелец!")
        return

    target_id = extract_target_user_id(message)
    if not target_id:
        await message.reply("⚠️ Ответьте на сообщение или напишите: `/demote 123456789`")
        return

    if target_id == OWNER_ID:
        await message.reply("❌ Нельзя снять роль с Владельца бота!")
        return

    await set_user_role(target_id, None, "user")
    await message.reply(f"🗑 Роль с пользователя `{target_id}` снята.")

# --- ЗАПУСК БОТА ---
async def main():
    logging.basicConfig(level=logging.INFO)
    await init_db()
    print("Бот успешно запущен!")
    await dp.start_polling(bot, allowed_updates=["message"])

if __name__ == "__main__":
    asyncio.run(main())