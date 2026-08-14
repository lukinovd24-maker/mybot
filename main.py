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

# ID топика "Пользователи без админа" (замени на свой актуальный ID)
UNASSIGNED_TOPIC_ID = 765 
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

# --- ОБРАБОТКА СТАРТА И СООБЩЕНИЙ В ЛИЧКЕ ---
@dp.message(F.chat.type == "private")
async def private_msg(message: types.Message):
    user_id = message.from_user.id
    
    async with db_pool.acquire() as conn:
        # Проверяем, есть ли пользователь в базе
        user = await conn.fetchrow("SELECT topic_id, is_banned FROM users WHERE user_id = $1;", user_id)
        
        if user and user['is_banned']: 
            return

        topic_id = user['topic_id'] if user else None

        # ЕСЛИ ПОЛЬЗОВАТЕЛЬ НОВЫЙ (нет топика) — СРАЗУ СОЗДАЕМ ЕМУ ТОПИК
        if not topic_id:
            username_str = f"@{message.from_user.username}" if message.from_user.username else f"ID: {user_id}"
            first_name = message.from_user.first_name or "Без имени"
            
            try:
                # 1. Создаем отдельный топик под этого пользователя
                forum_topic = await bot.create_forum_topic(
                    chat_id=ADMIN_CHAT_ID, 
                    name=f"ПЗ: {first_name}"
                )
                topic_id = forum_topic.message_thread_id
                
                # 2. Сохраняем топик в базу
                await conn.execute(
                    "INSERT INTO users (user_id, username, topic_id) VALUES ($1, $2, $3) ON CONFLICT (user_id) DO UPDATE SET topic_id = $3, username = $2;", 
                    user_id, message.from_user.username, topic_id
                )
                
                # 3. Первое сообщение ВНУТРИ СОЗДАННОГО ТОПИКА — карточка с информацией о пользователе
                await bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    message_thread_id=topic_id,
                    text=f"📋 <b>Информация о новом пользователе:</b>\n"
                         f"├ Имя: {first_name}\n"
                         f"├ Юзернейм: {username_str}\n"
                         f"└ ID: <code>{user_id}</code>",
                    parse_mode=ParseMode.HTML
                )

                # 4. Уведомление в топик "Пользователи без админа" с кнопкой взять ПЗ
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Взять ПЗ", callback_data=f"take_pz_{user_id}")]
                ])
                await bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    message_thread_id=UNASSIGNED_TOPIC_ID,
                    text=f"🆕 <b>Новый запрос (ПЗ: {first_name})</b>\n👤 Пользователь: {username_str} (<code>{user_id}</code>)",
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML
                )

            except Exception as e:
                logger.error(f"Ошибка при создании топика для нового юзера: {e}")
                return

        # Если это просто команда /start — дальше ничего не делаем
        if message.text and message.text.startswith("/start"):
            return

        # Если это обычное текстовое сообщение / медиа — пересылаем в личный топик пользователя
        if topic_id and message.text and not message.text.startswith("/"):
            try:
                await bot.forward_message(
                    chat_id=ADMIN_CHAT_ID,
                    from_chat_id=user_id,
                    message_id=message.message_id,
                    message_thread_id=topic_id
                )
            except Exception as e:
                logger.error(f"Ошибка пересылки сообщения в топик: {e}")

# --- КНОПКА ВЗЯТИЯ ПЗ ---
@dp.callback_query(F.data.startswith("take_pz_"))
async def take_pz(callback: types.CallbackQuery):
    target_id = int(callback.data.split("_")[2])
    admin_name = callback.from_user.username or callback.from_user.first_name
    
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO admin_actions (admin_id, admin_username, target_user_id) VALUES ($1, $2, $3);", 
            callback.from_user.id, callback.from_user.username, target_id
        )
        
    await callback.message.edit_text(f"✅ ПЗ взял администратор @{admin_name}")
    await callback.answer("Вы успешно взяли ПЗ!")

# --- ОТВЕТ АДМИНА ИЗ ЛИЧНОГО ТОПИКА ПОЛЬЗОВАТЕЛЯ ---
@dp.message(F.chat.id == ADMIN_CHAT_ID)
async def reply_from_topic(message: types.Message):
    # Игнорируем сообщения из топика "без админа" и общих тем, если они не привязаны к юзеру
    if not message.message_thread_id or message.message_thread_id == UNASSIGNED_TOPIC_ID: 
        return
    if message.text and message.text.startswith("/"): 
        return
        
    async with db_pool.acquire() as conn:
        user_id = await conn.fetchval("SELECT user_id FROM users WHERE topic_id = $1;", message.message_thread_id)
        if user_id:
            tag = await conn.fetchval("SELECT admin_tag FROM users WHERE user_id = $1;", message.from_user.id) or f"@{message.from_user.username}"
            text = f"<b>[{tag}]</b> {message.text}" if message.text else message.caption
            try:
                await bot.send_message(user_id, text, parse_mode=ParseMode.HTML)
            except Exception as e:
                logger.error(f"Ошибка отправки пользователю: {e}")

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())