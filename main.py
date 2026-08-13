import asyncio
import logging
import os
import asyncpg
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart

# --- НАСТРОЙКИ И ПЕРЕМЕННЫЕ ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

# Исправление формата URL для asyncpg (если Railway выдал postgres://)
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Твой Telegram ID — Главный Владелец
OWNER_ID = 8674242517

# ID твоего чата администраторов
ADMIN_CHAT_ID = -1004404098187

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
db_error_msg = ""

# --- РАБОТА С БАЗОЙ ДАННЫХ ---
async def init_db():
    global db_pool, db_error_msg
    if not DATABASE_URL:
        db_error_msg = "Переменная DATABASE_URL не задана в Railway Variables!"
        logging.error(db_error_msg)
        return

    try:
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
    except Exception as e:
        db_error_msg = str(e)
        logging.error(f"Ошибка подключения к БД: {e}")

async def set_user_role(user_id: int, username: str | None, role: str):
    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO users (user_id, username, role)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (user_id) 
                    DO UPDATE SET role = EXCLUDED.role, username = COALESCE(EXCLUDED.username, users.username);
                """, user_id, username, role)
        except Exception as e:
            logging.error(f"Ошибка при сохранении пользователя: {e}")

async def get_user_role(user_id: int) -> str:
    if user_id == OWNER_ID:
        return "owner"
    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                row = await conn.fetchrow("SELECT role FROM users WHERE user_id = $1;", user_id)
                if row and row['role']:
                    return row['role']
        except Exception as e:
            logging.error(f"Ошибка получения роли: {e}")
    return "user"

def extract_target_user_id(message: types.Message) -> int | None:
    if message.reply_to_message:
        return message.reply_to_message.from_user.id
    args = message.text.split()
    if len(args) > 1 and args[1].isdigit():
        return int(args[1])
    return None

async def notify_user(user_id: int, text: str):
    try:
        await bot.send_message(chat_id=user_id, text=text, parse_mode="HTML")
    except Exception as e:
        logging.warning(f"Не удалось отправить уведомление пользователю {user_id}: {e}")

# --- ПОЛУЧЕНИЕ FILE_ID КАРТИНОК (Только для Владельца) ---
@dp.message(F.photo, F.from_user.id == OWNER_ID)
async def get_photo_file_id(message: types.Message):
    photo_id = message.photo[-1].file_id
    await message.reply(
        f"🖼 <b><code>file_id</code> твоей картинки:</b>\n\n"
        f"<code>{photo_id}</code>\n\n"
        f"📌 <i>Нажми на код выше, чтобы скопировать его!</i>",
        parse_mode="HTML"
    )

# --- КОМАНДА /START ---
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
        f"Твой статус в системе: <b>{role_names.get(role, '👤 Пользователь')}</b>\n\n"
        f"💬 <i>Если у вас есть вопрос — просто напишите его в этот чат, и наши администраторы вам ответят!</i>"
    )

    try:
        await message.answer_photo(photo=photo, caption=caption_text, parse_mode="HTML")
    except Exception as e:
        logging.error(f"Ошибка при отправке фото: {e}")
        await message.answer(caption_text, parse_mode="HTML")

# --- КОМАНДА /STATS (СТАТИСТИКА) ---
@dp.message(Command("stats"))
async def stats_cmd(message: types.Message):
    user_role = await get_user_role(message.from_user.id)
    if user_role not in ["owner", "director", "admin"]:
        await message.reply("❌ Просматривать статистику могут только Администраторы, Директора и Владелец!")
        return

    if not db_pool:
        await message.reply(f"⚠️ База данных недоступна.\nПричина: <code>{db_error_msg}</code>", parse_mode="HTML")
        return

    try:
        async with db_pool.acquire() as conn:
            total_users = await conn.fetchval("SELECT COUNT(*) FROM users;")
            directors = await conn.fetchval("SELECT COUNT(*) FROM users WHERE role = 'director';")
            admins = await conn.fetchval("SELECT COUNT(*) FROM users WHERE role = 'admin';")
            interns = await conn.fetchval("SELECT COUNT(*) FROM users WHERE role = 'intern';")
            users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE role = 'user';")

        text = (
            "📊 <b>Статистика пользователей бота:</b>\n\n"
            f"👥 Всего пользователей в БД: <b>{total_users}</b>\n\n"
            f"👑 Владелец: <b>1</b>\n"
            f"💼 Директоров: <b>{directors}</b>\n"
            f"🛡 Администраторов: <b>{admins}</b>\n"
            f"🔰 Стажёров: <b>{interns}</b>\n"
            f"👤 Обычных пользователей: <b>{users}</b>"
        )
        await message.reply(text, parse_mode="HTML")
    except Exception as e:
        await message.reply(f"⚠️ Ошибка выполнения запроса к БД: <code>{e}</code>", parse_mode="HTML")

# --- УПРАВЛЕНИЕ РОЛЯМИ ---
@dp.message(Command("set_director"))
async def set_director_cmd(message: types.Message):
    if message.from_user.id != OWNER_ID:
        await message.reply("❌ Назначать Директоров может только Владелец бота!")
        return
    target_id = extract_target_user_id(message)
    if not target_id:
        await message.reply("⚠️ Ответьте на сообщение или напишите: <code>/set_director 123456789</code>", parse_mode="HTML")
        return
    await set_user_role(target_id, None, "director")
    await message.reply(f"✅ Пользователю <code>{target_id}</code> присвоена роль <b>Директор</b> 💼", parse_mode="HTML")
    await notify_user(target_id, "🎉 <b>Поздравляем!</b> Вам присвоена должность <b>Директора</b> 💼")

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
    await notify_user(target_id, "🎉 <b>Поздравляем!</b> Вам присвоена должность <b>Администратора</b> 🛡")

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
    await notify_user(target_id, "🎉 <b>Поздравляем!</b> Вам присвоена должность <b>Стажёра</b> 🔰")

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
    await notify_user(target_id, "⚠️ <b>Уведомление:</b> Вы были сняты со своей должности в системе.")

# --- ПЕРЕСЫЛКА СООБЩЕНИЙ ПОЛЬЗОВАТЕЛЕЙ В АДМИН-ЧАТ ---
@dp.message(F.chat.type == "private", ~F.text.startswith("/"))
async def handle_user_messages(message: types.Message):
    user_role = await get_user_role(message.from_user.id)
    await set_user_role(message.from_user.id, message.from_user.username, user_role)
    
    try:
        # 1. Шлем шапку с инфой о пользователе в админ-чат
        header = (
            f"📩 <b>Новое обращение в техподдержку!</b>\n"
            f"👤 От: {message.from_user.full_name} (@{message.from_user.username or 'нет_юзернейма'})\n"
            f"🆔 ID: <code>{message.from_user.id}</code>"
        )
        await bot.send_message(chat_id=ADMIN_CHAT_ID, text=header, parse_mode="HTML")
        
        # 2. Дублируем само сообщение пользователя прямо в админ-чат
        await message.copy_message(chat_id=ADMIN_CHAT_ID)

        # 3. Отвечаем пользователю
        await message.reply("✅ Ваше сообщение отправлено администрации! Вам ответят в ближайшее время.")
    except Exception as e:
        logging.error(f"Ошибка при пересылке сообщения: {e}")
        await message.reply(f"⚠️ Не удалось переслать сообщение администрации: {e}")

# --- ЗАПУСК БОТА ---
async def main():
    logging.basicConfig(level=logging.INFO)
    await init_db()
    print("Бот успешно запущен!")
    await dp.start_polling(bot, allowed_updates=["message"])

if __name__ == "__main__":
    asyncio.run(main())