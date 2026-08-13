import os
import logging
import asyncpg
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.enums import ParseMode

# --- НАСТРОЙКА ЛОГИРОВАНИЯ ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", 0)) if os.getenv("ADMIN_CHAT_ID") else None

# ID топика «Пользователи без админа»
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
                CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, username TEXT, role TEXT DEFAULT 'user', is_banned BOOLEAN DEFAULT FALSE, topic_id INT, rest_until TIMESTAMP);
                CREATE TABLE IF NOT EXISTS messages (id SERIAL PRIMARY KEY, user_id BIGINT, sender_type TEXT, user_msg_id INT, admin_msg_id INT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS admin_actions (id SERIAL PRIMARY KEY, admin_id BIGINT, admin_username TEXT, target_user_id BIGINT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
            """)
            await conn.execute("""
                ALTER TABLE messages ADD COLUMN IF NOT EXISTS user_msg_id INT;
                ALTER TABLE messages ADD COLUMN IF NOT EXISTS admin_msg_id INT;
            """)
    except Exception as e:
        logger.error(f"Ошибка БД: {e}")

# --- ФУНКЦИИ ПРОВЕРКИ РОЛЕЙ ---
async def get_user_role(user_id: int) -> str:
    if user_id == OWNER_ID:
        return "owner"
    if not db_pool:
        return "user"
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT role, rest_until FROM users WHERE user_id = $1;", user_id)
            if not row:
                return "user"
            if row["rest_until"] and row["rest_until"] > datetime.now():
                return "user"
            return row["role"] or "user"
    except:
        return "user"

async def is_admin(user_id: int) -> bool:
    role = await get_user_role(user_id)
    return str(role).lower() in ["owner", "director", "admin", "intern"]

async def is_director_or_owner(user_id: int) -> bool:
    role = await get_user_role(user_id)
    return str(role).lower() in ["owner", "director"]

async def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID or (await get_user_role(user_id)) == "owner"

# --- КОМАНДА /START ---
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    role = "owner" if message.from_user.id == OWNER_ID else "user"
    if db_pool:
        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO users (user_id, username, role) 
                VALUES ($1, $2, $3)
                ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username;
            """, message.from_user.id, message.from_user.username, role)
            
    start_text = (
        "приветствую путник ты попал в прекрасный бот под названием \"вечернее сияние\".\n"
        "перед тем как начать общение, прошу заглянуть в наш тгк: https://t.me/eve_ning_glow\n"
        "там вся важная информация.\n"
        "Прочитал? тогда пиши \"привет общение/поддержка/уни\" и к тебе придет админ.\n"
        "удачи тебе солнышко"
    )
    await message.reply(start_text, disable_web_page_preview=False)

# --- КОМАНДА /HELP ---
@dp.message(Command("help"))
async def help_cmd(message: types.Message):
    user_id = message.from_user.id
    role = await get_user_role(user_id)

    text = "📌 <b>Список доступных команд:</b>\n\n"
    if role == "user":
        text += "👤 <b>Пользователям:</b>\n├ /start — Запустить бота\n└ /help — Справка по командам\n"
    elif role in ["admin", "intern"]:
        text += "🛡 <b>Администрации:</b>\n├ /stats — Статистика бота\n├ /adminstats (или .астат) — Статистика взятых ПЗ\n├ /check или .чек — Проверить пользователя\n├ /ban [ID] — Заблокировать\n└ /unban [ID] — Разблокировать\n"
    elif role == "director":
        text += "💼 <b>Директорат:</b>\n├ /stats, /adminstats, /check\n├ /ban /unban [ID]\n├ /broadcast [текст]\n├ /rest [юз/ID] [дни]\n└ <code>.ид юз</code>\n"
    elif role == "owner":
        text += "👑 <b>Владелец:</b>\n├ Все права управления ботом и ролями (/setdirector, /setadmin, /setintern, /demote)\n"

    await message.reply(text, parse_mode=ParseMode.HTML)

# --- ПЕРЕСЫЛКА СООБЩЕНИЙ И ТОПИКИ ---
@dp.message(F.chat.type == "private")
async def forward_user_message(message: types.Message):
    if not ADMIN_CHAT_ID:
        return
    if message.text and message.text.startswith("/"):
        return

    user_id = message.from_user.id
    username = message.from_user.username or "отсутствует"
    full_name = message.from_user.full_name

    try:
        await message.react([types.ReactionTypeEmoji(emoji="👍")])
    except Exception as e:
        logger.error(f"Не удалось поставить реакцию: {e}")

    topic_id = None
    is_new_topic = False

    if db_pool:
        async with db_pool.acquire() as conn:
            is_banned = await conn.fetchval("SELECT is_banned FROM users WHERE user_id = $1;", user_id)
            if is_banned:
                await message.reply("🚫 Вы заблокированы.")
                return

            row = await conn.fetchrow("SELECT topic_id FROM users WHERE user_id = $1;", user_id)
            topic_id = row["topic_id"] if row else None

            if not topic_id:
                is_new_topic = True
                try:
                    topic_title = f"{full_name} (@{username})"[:128]
                    new_topic = await bot.create_forum_topic(chat_id=ADMIN_CHAT_ID, name=topic_title)
                    topic_id = new_topic.message_thread_id

                    await conn.execute("""
                        INSERT INTO users (user_id, username, topic_id) 
                        VALUES ($1, $2, $3)
                        ON CONFLICT (user_id) DO UPDATE SET topic_id = $3, username = $2;
                    """, user_id, username, topic_id)
                except Exception as e:
                    logger.error(f"Ошибка создания топика: {e}")
                    topic_id = None

    if topic_id:
        if is_new_topic:
            info_text = (
                "👤 <b>Информация о пользователе (ПЗ):</b>\n\n"
                f"📌 Имя: <b>{full_name}</b>\n"
                f"🔗 Юзернейм: @{username}\n"
                f"🆔 Telegram ID: <code>{user_id}</code>\n"
                f"❌ <b>Кто взял ПЗ:</b> Никто не взял"
            )
            keyboard = types.InlineKeyboardMarkup(
                inline_keyboard=[
                    [types.InlineKeyboardButton(text="🤝 Взять пользователя", callback_data=f"take_user_{user_id}")],
                    [types.InlineKeyboardButton(text="🔄 Сменить админа", callback_data=f"change_admin_{user_id}")]
                ]
            )
            try:
                sent_msg = await bot.send_message(chat_id=ADMIN_CHAT_ID, message_thread_id=topic_id, text=info_text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
                await bot.pin_chat_message(chat_id=ADMIN_CHAT_ID, message_id=sent_msg.message_id)
                
                # Отправка карточки в топик «Пользователи без админа»
                if UNASSIGNED_TOPIC_ID:
                    clean_chat_id = str(ADMIN_CHAT_ID).replace("-100", "")
                    topic_link = f"https://t.me/c/{clean_chat_id}/{topic_id}"
                    
                    unassigned_text = (
                        "🚨 <b>Новый пользователь!</b>\n\n"
                        f"👤 Имя: <b>{full_name}</b> (@{username})\n"
                        f"📌 Статус: <b>нету админа</b>\n"
                        f"🔗 <a href='{topic_link}'>Перейти в топик пользователя</a>"
                    )
                    await bot.send_message(
                        chat_id=ADMIN_CHAT_ID,
                        message_thread_id=UNASSIGNED_TOPIC_ID,
                        text=unassigned_text,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True
                    )
            except Exception as e:
                logger.error(f"Ошибка закрепа или отправки в общий топик: {e}")

        try:
            copied_msg = await bot.copy_message(chat_id=ADMIN_CHAT_ID, message_thread_id=topic_id, from_chat_id=message.chat.id, message_id=message.message_id)
            
            if db_pool:
                async with db_pool.acquire() as conn:
                    await conn.execute(
                        "INSERT INTO messages (user_id, sender_type, user_msg_id, admin_msg_id) VALUES ($1, 'user', $2, $3);",
                        user_id, message.message_id, copied_msg.message_id
                    )
        except Exception as e:
            logger.error(f"Ошибка пересылки: {e}")

# --- ОБРАБОТЧИК КНОПКИ «ВЗЯТЬ ПОЛЬЗОВАТЕЛЯ» ---
@dp.callback_query(F.data.startswith("take_user_"))
async def take_user_callback(callback: types.CallbackQuery):
    target_user_id = int(callback.data.split("_")[2])
    admin_user = callback.from_user
    admin_username = admin_user.username or "отсутствует"
    admin_name = f"@{admin_username}" if admin_username != "отсутствует" else admin_user.full_name
    admin_info = f"{admin_name} (ID: <code>{admin_user.id}</code>)"

    if db_pool:
        async with db_pool.acquire() as conn:
            await conn.execute("INSERT INTO admin_actions (admin_id, admin_username, target_user_id) VALUES ($1, $2, $3);", admin_user.id, admin_username, target_user_id)

    original_text = callback.message.html_text
    
    if "✅ <b>Кто взял ПЗ:</b>" in original_text:
        parts = original_text.split("✅ <b>Кто взял ПЗ:</b>")
        base_text = parts[0].strip()
        updated_text = f"{base_text}\n\n✅ <b>Кто взял ПЗ:</b> {admin_info}"
    elif "❌ <b>Кто взял ПЗ:</b> Никто не взял" in original_text:
        updated_text = original_text.replace("❌ <b>Кто взял ПЗ:</b> Никто не взял", f"✅ <b>Кто взял ПЗ:</b> {admin_info}")
    else:
        updated_text = original_text + f"\n\n✅ <b>Кто взял ПЗ:</b> {admin_info}"

    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="🤝 Взять пользователя", callback_data=f"take_user_{target_user_id}")],
            [types.InlineKeyboardButton(text="🔄 Сменить админа", callback_data=f"change_admin_{target_user_id}")]
        ]
    )

    try:
        await callback.message.edit_text(text=updated_text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
        await callback.answer("Вы успешно взяли пользователя!")
    except Exception as e:
        logger.error(f"Ошибка кнопки взять ПЗ: {e}")

# --- ОБРАБОТЧИК КНОПКИ «СМЕНИТЬ АДМИНА» ---
@dp.callback_query(F.data.startswith("change_admin_"))
async def change_admin_callback(callback: types.CallbackQuery):
    target_user_id = int(callback.data.split("_")[2])
    
    original_text = callback.message.html_text
    
    if "✅ <b>Кто взял ПЗ:</b>" in original_text:
        parts = original_text.split("✅ <b>Кто взял ПЗ:</b>")
        base_text = parts[0].strip()
        updated_text = f"{base_text}\n\n⚠️ <b>Кто взял ПЗ:</b> Запрошена смена администратора (Никто не взял)"
    else:
        updated_text = original_text + "\n\n⚠️ <b>Кто взял ПЗ:</b> Запрошена смена администратора"

    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="🤝 Взять пользователя", callback_data=f"take_user_{target_user_id}")],
            [types.InlineKeyboardButton(text="🔄 Сменить админа", callback_data=f"change_admin_{target_user_id}")]
        ]
    )

    try:
        await callback.message.edit_text(text=updated_text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
        
        await bot.send_message(
            chat_id=callback.message.chat.id,
            message_thread_id=callback.message.message_thread_id,
            text="🔔 <b>Внимание!</b> Запрошена смена администратора. ПЗ снова свободно!",
            parse_mode=ParseMode.HTML
        )

        if UNASSIGNED_TOPIC_ID:
            topic_id = callback.message.message_thread_id
            clean_chat_id = str(ADMIN_CHAT_ID).replace("-100", "")
            topic_link = f"https://t.me/c/{clean_chat_id}/{topic_id}"
            
            async with db_pool.acquire() as conn:
                user_row = await conn.fetchrow("SELECT username FROM users WHERE user_id = $1;", target_user_id)
                uname = user_row["username"] if user_row else "отсутствует"

            unassigned_text = (
                "🔄 <b>Смена администратора!</b>\n\n"
                f"👤 Пользователь: ID <code>{target_user_id}</code> (@{uname})\n"
                f"📌 Статус: <b>смена админа</b>\n"
                f"🔗 <a href='{topic_link}'>Перейти в топик пользователя</a>"
            )
            await bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                message_thread_id=UNASSIGNED_TOPIC_ID,
                text=unassigned_text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )
        
        await callback.answer("Запрос на смену администратора отправлен!")
    except Exception as e:
        logger.error(f"Ошибка смены админа: {e}")

# --- ОТВЕТЫ ИЗ ТОПИКОВ АДМИНАМИ ---
@dp.message(F.chat.id == ADMIN_CHAT_ID)
async def reply_from_topic(message: types.Message):
    if message.forum_topic_created or message.forum_topic_edited:
        return
    if not message.message_thread_id or (message.text and message.text.startswith("/")):
        return
    if not db_pool:
        return

    async with db_pool.acquire() as conn:
        user_id = await conn.fetchval("SELECT user_id FROM users WHERE topic_id = $1;", message.message_thread_id)
        if user_id:
            try:
                sent_msg = await bot.copy_message(chat_id=user_id, from_chat_id=ADMIN_CHAT_ID, message_id=message.message_id)
                await conn.execute(
                    "INSERT INTO messages (user_id, sender_type, user_msg_id, admin_msg_id) VALUES ($1, 'admin', $2, $3);",
                    user_id, sent_msg.message_id, message.message_id
                )
            except Exception as e:
                await message.reply(f"❌ Ошибка отправки: {e}")

# --- СИНХРОНИЗАЦИЯ РЕАКЦИЙ ---
@dp.message_reaction()
async def handle_message_reaction(event: types.MessageReactionUpdated):
    if not db_pool:
        return

    chat_id = event.chat.id
    msg_id = event.message_id
    
    new_reactions = []
    for r in event.new_reaction:
        if isinstance(r, types.ReactionTypeEmoji):
            new_reactions.append(r.emoji)

    async with db_pool.acquire() as conn:
        if chat_id == ADMIN_CHAT_ID:
            row = await conn.fetchrow("SELECT user_id, user_msg_id FROM messages WHERE admin_msg_id = $1;", msg_id)
            if row and row["user_msg_id"]:
                try:
                    await bot.set_message_reaction(chat_id=row["user_id"], message_id=row["user_msg_id"], reaction=[types.ReactionTypeEmoji(emoji=e) for e in new_reactions])
                except Exception as e:
                    logger.error(f"Ошибка синхронизации реакции на юзера: {e}")
        else:
            row = await conn.fetchrow("SELECT topic_id, admin_msg_id FROM messages JOIN users ON messages.user_id = users.user_id WHERE messages.user_id = $1 AND messages.user_msg_id = $2;", chat_id, msg_id)
            if row and row["admin_msg_id"]:
                try:
                    await bot.set_message_reaction(chat_id=ADMIN_CHAT_ID, message_id=row["admin_msg_id"], reaction=[types.ReactionTypeEmoji(emoji=e) for e in new_reactions])
                except Exception as e:
                    logger.error(f"Ошибка синхронизации реакции в админ-чат: {e}")

# --- ДОП КОМАНДЫ (СТАТИСТИКА, БАНЫ И Т.Д.) ---
@dp.message(Command("stats"))
async def stats_cmd(message: types.Message):
    if not await is_admin(message.from_user.id):
        return
    if not db_pool:
        return
    async with db_pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM users;") or 0
        banned = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_banned = TRUE;") or 0
    await message.reply(f"📊 Всего пользователей: <b>{total}</b>\n🚫 Забанено: <b>{banned}</b>", parse_mode=ParseMode.HTML)

@dp.message(Command("ban"))
async def ban_cmd(message: types.Message, command: CommandObject):
    if not await is_admin(message.from_user.id) or not command.args or not command.args.isdigit():
        return
    if db_pool:
        async with db_pool.acquire() as conn:
            await conn.execute("UPDATE users SET is_banned = TRUE WHERE user_id = $1;", int(command.args))
        await message.reply(f"🚫 Пользователь забанен.")

@dp.message(Command("unban"))
async def unban_cmd(message: types.Message, command: CommandObject):
    if not await is_admin(message.from_user.id) or not command.args or not command.args.isdigit():
        return
    if db_pool:
        async with db_pool.acquire() as conn:
            await conn.execute("UPDATE users SET is_banned = FALSE WHERE user_id = $1;", int(command.args))
        await message.reply(f"🍏 Пользователь разбанен.")

# --- ЗАПУСК ---
async def main():
    await init_db()
    await dp.start_polling(bot, allowed_updates=["message", "callback_query", "message_reaction"])

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())