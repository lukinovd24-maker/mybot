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

# --- FILE_ID КАРТИНОК ДЛЯ КАЖДОЙ РОЛИ ---
ROLE_IMAGES = {
    "owner": "AgACAgEAAyEFAAMBBfhjBAADAmp9dVI8vdVmrsan-2KbKw6VSnhNAALODGsbVX3xR6JqNvy31JNfAQADAgADeAADPQQ",
    "director": "AgACAgEAAyEFAAMBBfhjBAADA2p9dVITraxlKk80Pjsmo4BcFRRaAALPDGsbVX3xRz6rUFLATrZUAQADAgADeAADPQQ",
    "admin": "AgACAgEAAyEFAAMBBfhjBAADBGp9dVLL-nSsXqZHigTHjc_WaYy-AALQDGsbVX3xR-swwTZ6AAGZoAEAAwIAA3gAAz0E",
    "intern": "AgACAgEAAyEFAAMBBfhjBAADBWp9dVKOSnt5hdtpqHBmepXxOi-mAALRDGsbVX3xRzjICoP46KtYAQADAgADeAADPQQ",
    "user": "AgACAgEAAyEFAAMBBfhjBAADBWp9dVKOSnt5hdtpqHBmepXxOi-mAALRDGsbVX3xRzjICoP46KtYAQADAgADeAADPQQ"
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

# Вспомогательная функция для отправки уведомлений пользователю
async def notify_user(user_id: int, text: str):
    try:
        await bot.send_message(chat_id=user_id, text=text, parse_mode="HTML")
    except Exception as e:
        logging.warning(f"Не удалось отправить уведомление пользователю {user_id}: {e}")

# --- ПОЛУЧЕНИЕ FILE_ID КАРТИНОК В ЛИЧКЕ БОТА (Только для Владельца) ---
@dp.message(F.photo, F.from_user.id == OWNER_ID)
async def get_photo_file_id(message: types.Message):
    photo_id = message.photo[-1].file_id
    await message.reply(
        f"🖼 <b><code>file_id</code> твоей картинки:</b>\n\n"
        f"<code>{photo_id}</code>\n\n"
        f"📌 <i>Нажми на код выше, чтобы скопировать его!</i>",
        parse_mode="HTML"
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
    
    photo = ROLE_IMAGES.get(role, ROLE_IMAGES["user"])
    
    full_name = message.from_user.full_name.replace("<", "&lt;").replace(">", "&gt;")
    
    caption_text = (
        f"👋 <b>Привет, {full_name}!</b>\n\n"
        f"Твой статус в системе: <b>{role_names.get(role, '👤 Пользователь')}</b>"
    )

    try:
        await message.answer_photo(photo=photo, caption=caption_text, parse_mode="HTML")
    except Exception as e:
        logging.error(f"Ошибка при отправке фото: {e}")
        await message.answer(caption_text, parse_mode="HTML")

# --- УПРАВЛЕНИЕ РОЛЯМИ С УВЕДОМЛЕНИЯМИ ---

# 1. Назначение Директора
@dp.message(Command("set_director"))
async def set_director_cmd(message: types.Message):
    if message.from_user.id != OWNER_ID:
        await message.reply("❌ На назначать Директоров может только Владелец бота!")
        return

    target_id = extract_target_user_id(message)
    if not target_id:
        await message.reply("⚠️ Ответьте на сообщение или напишите: <code>/set_director 123456789</code>", parse_mode="HTML")
        return

    await set_user_role(target_id, None, "director")
    await message.reply(f"✅ Пользователю <code>{target_id}</code> присвоена роль <b>Директор</b> 💼", parse_mode="HTML")
    
    # Уведомление пользователю
    await notify_user(target_id, "🎉 <b>Поздравляем!</b> Вам присвоена должность <b>Директора</b> 💼")

# 2. Назначение Администратора
@dp.message(Command("set_admin"))
async def set_admin_cmd(message: types.Message):
    user_role = await get_user_role(message.from_user.id)
    if user_role not in ["owner", "director"]:
        await message.reply("❌ Назначать Администраторов могут только Директора и Владелец!")
        return

    target_id = extract_target_user_id(message)
    if not target_id:
        await message.reply("⚠️ Ответьте на сообщение или напишите: <code>/set_admin 123456789</code>", parse_mode="HTML")
        return

    await set_user_role(target_id, None, "admin")
    await message.reply(f"✅ Пользователю <code>{target_id}</code> присвоена роль <b>Администратор</b> 🛡", parse_mode="HTML")
    
    # Уведомление пользователю
    await notify_user(target_id, "🎉 <b>Поздравляем!</b> Вам присвоена должность <b>Администратора</b> 🛡")

# 3. Назначение Стажёра
@dp.message(Command("set_intern"))
async def set_intern_cmd(message: types.Message):
    user_role = await get_user_role(message.from_user.id)
    if user_role not in ["owner", "director"]:
        await message.reply("❌ Назначать Стажёров могут только Директора и Владелец!")
        return

    target_id = extract_target_user_id(message)
    if not target_id:
        await message.reply("⚠️ Ответьте на сообщение или напишите: <code>/set_intern 123456789</code>", parse_mode="HTML")
        return

    await set_user_role(target_id, None, "intern")
    await message.reply(f"✅ Пользователю <code>{target_id}</code> присвоена роль <b>Стажёр</b> 🔰", parse_mode="HTML")
    
    # Уведомление пользователю
    await notify_user(target_id, "🎉 <b>Поздравляем!</b> Вам присвоена должность <b>Стажёра</b> 🔰")

# 4. Снятие роли (Увольнение)
@dp.message(Command("demote"))
async def demote_cmd(message: types.Message):
    user_role = await get_user_role(message.from_user.id)
    if user_role not in ["owner", "director"]:
        await message.reply("❌ Снимать роли могут только Директора и Владелец!")
        return

    target_id = extract_target_user_id(message)
    if not target_id:
        await message.reply("⚠️ Ответьте на сообщение или напишите: <code>/demote 123456789</code>", parse_mode="HTML")
        return

    if target_id == OWNER_ID:
        await message.reply("❌ Нельзя снять роль с Владельца бота!")
        return

    await set_user_role(target_id, None, "user")
    await message.reply(f"🗑 Роль с пользователя <code>{target_id}</code> снята.", parse_mode="HTML")
    
    # Уведомление об увольнении
    await notify_user(target_id, "⚠️ <b>Уведомление:</b> Вы были сняты со своей должности в системе.")

# --- ЗАПУСК БОТА ---
async def main():
    logging.basicConfig(level=logging.INFO)
    await init_db()
    print("Бот успешно запущен!")
    await dp.start_polling(bot, allowed_updates=["message"])

if __name__ == "__main__":
    asyncio.run(main())