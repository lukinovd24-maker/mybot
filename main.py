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
                CREATE TABLE IF NOT EXISTS messages (id SERIAL PRIMARY KEY, user_id BIGINT, sender_type TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS admin_actions (id SERIAL PRIMARY KEY, admin_id BIGINT, admin_username TEXT, target_user_id BIGINT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
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

async def is_top_admin(user_id: int) -> bool:
    return await is_director_or_owner(user_id)

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
        text += "👤 <b>Пользователям:</b>\n"
        text += "├ /start — Запустить бота\n"
        text += "└ /help — Справка по командам\n"

    elif role in ["admin", "intern"]:
        text += "🛡 <b>Администрации:</b>\n"
        text += "├ /stats — Статистика бота\n"
        text += "├ /adminstats (или .астат) — Статистика взятых ПЗ\n"
        text += "├ /check или .чек — Проверить пользователя\n"
        text += "├ /ban [ID] — Заблокировать пользователя\n"
        text += "└ /unban [ID] — Разблокировать пользователя\n"

    elif role == "director":
        text += "💼 <b>Директорат:</b>\n"
        text += "├ /stats — Статистика бота\n"
        text += "├ /adminstats (или .астат) — Статистика взятых ПЗ\n"
        text += "├ /check или .чек — Проверить пользователя\n"
        text += "├ /ban /unban [ID] — Управление банами\n"
        text += "├ /broadcast [текст] — Рассылка пользователям\n"
        text += "├ /rest [юз/ID] [дни] — Отправить админа в отпуск\n"
        text += "└ <code>.ид юз</code> — Узнать ID пользователя\n"

    elif role == "owner":
        text += "👑 <b>Владелец:</b>\n"
        text += "├ /stats — Статистика бота\n"
        text += "├ /adminstats (или .астат) — Статистика взятых ПЗ\n"
        text += "├ /check или .чек — Проверить пользователя\n"
        text += "├ /ban /unban [ID] — Управление банами\n"
        text += "├ /broadcast [текст] — Рассылка\n"
        text += "├ /rest [юз/ID] [дни] — Отправить в отпуск\n"
        text += "├ <code>.ид юз</code> — Узнать ID пользователя\n"
        text += "├ /setdirector [ID] — Назначить директора\n"
        text += "├ /setadmin [ID] — Назначить администратора\n"
        text += "├ /setintern [ID] — Назначить стажёра\n"
        text += "├ /demote [ID] — Понизить до пользователя\n"
        text += "└ /setowner — Подтвердить права Владельца\n"

    await message.reply(text, parse_mode=ParseMode.HTML)

# --- ПРОВЕРКА ПОЛЬЗОВАТЕЛЯ (/check и .чек) ---
async def process_check_user(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.reply("❌ Эта команда доступна только администрации!")
        return

    target_user_id = None
    target_username = None

    args = message.text.split()
    if len(args) > 1 and args[1].startswith("@"):
        target_username = args[1].replace("@", "").strip()
    elif len(args) > 1 and args[1].isdigit():
        target_user_id = int(args[1])
    elif message.reply_to_message:
        if message.reply_to_message.forward_from:
            target_user_id = message.reply_to_message.forward_from.id
            target_username = message.reply_to_message.forward_from.username
        elif message.message_thread_id and db_pool:
            async with db_pool.acquire() as conn:
                target_user_id = await conn.fetchval("SELECT user_id FROM users WHERE topic_id = $1;", message.message_thread_id)
    elif message.message_thread_id and db_pool:
        async with db_pool.acquire() as conn:
            target_user_id = await conn.fetchval("SELECT user_id FROM users WHERE topic_id = $1;", message.message_thread_id)

    if not db_pool:
        await message.reply("⚠️ База данных недоступна!")
        return

    async with db_pool.acquire() as conn:
        if target_username and not target_user_id:
            row = await conn.fetchrow("SELECT user_id, username, role, is_banned, topic_id, rest_until FROM users WHERE LOWER(username) = LOWER($1);", target_username)
        elif target_user_id:
            row = await conn.fetchrow("SELECT user_id, username, role, is_banned, topic_id, rest_until FROM users WHERE user_id = $1;", target_user_id)
        else:
            row = None

        if not row:
            await message.reply("⚠️ Пользователь не найден в базе данных бота.", parse_mode=ParseMode.HTML)
            return

        user_msgs = await conn.fetchval("SELECT COUNT(*) FROM messages WHERE user_id = $1 AND sender_type = 'user';", row["user_id"]) or 0
        admin_msgs = await conn.fetchval("SELECT COUNT(*) FROM messages WHERE user_id = $1 AND sender_type = 'admin';", row["user_id"]) or 0

    status = "🚫 Забанен" if row["is_banned"] else "🍏 Активен"
    rest_info = f"🏖 В отпуске до {row['rest_until'].strftime('%Y-%m-%d %H:%M')}" if row["rest_until"] and row["rest_until"] > datetime.now() else "Нет"
    
    text = (
        "🔍 👤 <b>Подробная проверка пользователя:</b>\n\n"
        f"🆔 Telegram ID: <code>{row['user_id']}</code>\n"
        f"👤 Юзернейм: @{row['username'] or 'отсутствует'}\n"
        f"🎭 Роль в боте: <b>{row['role']}</b>\n"
        f"📌 Статус: <b>{status}</b>\n"
        f"🏖 Отпуск: <b>{rest_info}</b>\n"
        f"📁 ID топика: <code>{row['topic_id'] or 'нет топика'}</code>\n\n"
        "✉️ <b>Статистика диалога:</b>\n"
        f"├ Сообщений от юзера: <b>{user_msgs}</b>\n"
        f"└ Ответов от админов: <b>{admin_msgs}</b>"
    )
    await message.reply(text, parse_mode=ParseMode.HTML)

@dp.message(F.text.lower().startswith(".чек"))
async def check_user_by_dot(message: types.Message):
    await process_check_user(message)

@dp.message(Command("check"))
async def check_user_by_command(message: types.Message):
    await process_check_user(message)

# --- ПОЛНАЯ СТАТИСТИКА БОТА (/stats) ---
@dp.message(Command("stats"))
async def stats_cmd(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.reply("❌ Отказано в доступе!")
        return
    if not db_pool:
        await message.reply("⚠️ База данных недоступна!")
        return

    async with db_pool.acquire() as conn:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users;") or 0
        banned_users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_banned = TRUE;") or 0
        clean_users = total_users - banned_users

        owners = await conn.fetchval("SELECT COUNT(*) FROM users WHERE role = 'owner';") or 1
        directors = await conn.fetchval("SELECT COUNT(*) FROM users WHERE role = 'director';") or 0
        admins = await conn.fetchval("SELECT COUNT(*) FROM users WHERE role = 'admin';") or 0
        interns = await conn.fetchval("SELECT COUNT(*) FROM users WHERE role = 'intern';") or 0
        simple_users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE role = 'user';") or 0

        user_msgs = await conn.fetchval("SELECT COUNT(*) FROM messages WHERE sender_type = 'user';") or 0
        admin_msgs = await conn.fetchval("SELECT COUNT(*) FROM messages WHERE sender_type = 'admin';") or 0
        total_msgs = user_msgs + admin_msgs

    text = (
        "📊 <b>Полная статистика бота:</b>\n\n"
        "👥 <b>Пользователи:</b>\n"
        f"├ Всего пользователей: <b>{total_users}</b>\n"
        f"├ 🍏 Активных (чистых): <b>{clean_users}</b>\n"
        f"└ 🚫 Забаненных: <b>{banned_users}</b>\n\n"
        "🎭 <b>Разделение по ролям:</b>\n"
        f"├ 👑 Владелец: <b>{owners}</b>\n"
        f"├ 💼 Директоров: <b>{directors}</b>\n"
        f"├ 🛡 Администраторов: <b>{admins}</b>\n"
        f"├ 🔰 Стажёров: <b>{interns}</b>\n"
        f"└ 👤 Пользователей: <b>{simple_users}</b>\n\n"
        "✉️ <b>Сообщения и активность:</b>\n"
        f"├ 📩 От пользователей: <b>{user_msgs}</b>\n"
        f"├ 📤 От администраторов: <b>{admin_msgs}</b>\n"
        f"└ 💬 Всего сообщений: <b>{total_msgs}</b>"
    )
    await message.reply(text, parse_mode=ParseMode.HTML)

# --- СТАТИСТИКА АДМИНОВ ПО ВЗЯТЫМ ПЗ (/adminstats) ---
async def process_admin_stats(message: types.Message):
    try:
        if not await is_admin(message.from_user.id):
            await message.reply("❌ Эта команда доступна только администрации!")
            return

        if not db_pool:
            await message.reply("⚠️ База данных недоступна!")
            return

        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = now - timedelta(days=7)
        month_start = now - timedelta(days=30)

        async with db_pool.acquire() as conn:
            day_rows = await conn.fetch("SELECT admin_id, admin_username, COUNT(*) as count FROM admin_actions WHERE created_at >= $1 GROUP BY admin_id, admin_username ORDER BY count DESC;", today_start)
            week_rows = await conn.fetch("SELECT admin_id, admin_username, COUNT(*) as count FROM admin_actions WHERE created_at >= $1 GROUP BY admin_id, admin_username ORDER BY count DESC;", week_start)
            month_rows = await conn.fetch("SELECT admin_id, admin_username, COUNT(*) as count FROM admin_actions WHERE created_at >= $1 GROUP BY admin_id, admin_username ORDER BY count DESC;", month_start)
            total_rows = await conn.fetch("SELECT admin_id, admin_username, COUNT(*) as count FROM admin_actions GROUP BY admin_id, admin_username ORDER BY count DESC;")

        def format_rows(rows):
            if not rows:
                return "<i>Пока нет данных</i>\n"
            res = ""
            for idx, r in enumerate(rows, 1):
                d = dict(r)
                uname = d.get('admin_username')
                uid = d.get('admin_id')
                cnt = d.get('count', 0)
                name = f"@{uname}" if uname and uname != 'отсутствует' else f"ID: {uid}"
                res += f"{idx}. {name} — <b>{cnt}</b>\n"
            return res

        text = (
            "📊 <b>Статистика работы администрации (взятые ПЗ):</b>\n\n"
            f"📅 <b>За сегодня:</b>\n{format_rows(day_rows)}\n"
            f"📈 <b>За неделю (7 дней):</b>\n{format_rows(week_rows)}\n"
            f"🗓 <b>За месяц (30 дней):</b>\n{format_rows(month_rows)}\n"
            f"🏆 <b>За всё время:</b>\n{format_rows(total_rows)}"
        )
        await message.reply(text, parse_mode=ParseMode.HTML)

    except Exception as e:
        logger.exception("Ошибка в admin_stats")
        await message.reply(f"❌ Ошибка: {str(e)}")

@dp.message(Command("adminstats"))
async def admin_stats_cmd(message: types.Message):
    await process_admin_stats(message)

@dp.message(F.text.lower().startswith(".астат"))
async def admin_stats_dot(message: types.Message):
    await process_admin_stats(message)

# --- РАССЫЛКА (/broadcast) ---
@dp.message(Command("broadcast"))
async def broadcast_cmd(message: types.Message, command: CommandObject):
    if not await is_admin(message.from_user.id):
        await message.reply("❌ У вас нет прав для рассылки!")
        return
    if not command.args:
        await message.reply("⚠️ Напишите текст рассылки. Пример:\n<code>/broadcast Всем привет!</code>", parse_mode=ParseMode.HTML)
        return

    text_to_send = command.args
    if not db_pool:
        await message.reply("⚠️ База данных недоступна!")
        return

    async with db_pool.acquire() as conn:
        users = await conn.fetch("SELECT user_id FROM users WHERE is_banned = FALSE;")
    
    count = 0
    for u in users:
        try:
            await bot.send_message(u["user_id"], text_to_send)
            count += 1
        except Exception:
            pass

    await message.reply(f"📢 Рассылка завершена! Успешно доставлено: <b>{count}</b> пользователям.", parse_mode=ParseMode.HTML)

# --- БАН / РАЗБАН ---
@dp.message(Command("ban"))
async def ban_cmd(message: types.Message, command: CommandObject):
    if not await is_admin(message.from_user.id):
        return
    if not command.args or not command.args.isdigit():
        await message.reply("⚠️ Укажите ID: <code>/ban 12345678</code>", parse_mode=ParseMode.HTML)
        return
    target_id = int(command.args)
    if db_pool:
        async with db_pool.acquire() as conn:
            await conn.execute("UPDATE users SET is_banned = TRUE WHERE user_id = $1;", target_id)
        await message.reply(f"🚫 Пользователь <code>{target_id}</code> забанен!", parse_mode=ParseMode.HTML)

@dp.message(Command("unban"))
async def unban_cmd(message: types.Message, command: CommandObject):
    if not await is_admin(message.from_user.id):
        return
    if not command.args or not command.args.isdigit():
        await message.reply("⚠️ Укажите ID: <code>/unban 12345678</code>", parse_mode=ParseMode.HTML)
        return
    target_id = int(command.args)
    if db_pool:
        async with db_pool.acquire() as conn:
            await conn.execute("UPDATE users SET is_banned = FALSE WHERE user_id = $1;", target_id)
        await message.reply(f"🍏 Пользователь <code>{target_id}</code> разбанен!", parse_mode=ParseMode.HTML)

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

            await conn.execute("INSERT INTO messages (user_id, sender_type) VALUES ($1, 'user');", user_id)

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
                inline_keyboard=[[types.InlineKeyboardButton(text="🤝 Взять пользователя", callback_data=f"take_user_{user_id}")]]
            )
            try:
                sent_msg = await bot.send_message(chat_id=ADMIN_CHAT_ID, message_thread_id=topic_id, text=info_text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
                await bot.pin_chat_message(chat_id=ADMIN_CHAT_ID, message_id=sent_msg.message_id)
            except Exception as e:
                logger.error(f"Ошибка закрепа: {e}")

        try:
            await bot.copy_message(chat_id=ADMIN_CHAT_ID, message_thread_id=topic_id, from_chat_id=message.chat.id, message_id=message.message_id)
        except Exception as e:
            logger.error(f"Ошибка пересылки: {e}")

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
    if "❌ <b>Кто взял ПЗ:</b>" in original_text:
        updated_text = original_text.replace("❌ <b>Кто взял ПЗ:</b> Никто не взял", f"✅ <b>Кто взял ПЗ:</b> {admin_info}")
    else:
        updated_text = original_text + f"\n\n✅ <b>Кто взял ПЗ:</b> {admin_info}"

    try:
        await callback.message.edit_text(text=updated_text, reply_markup=None, parse_mode=ParseMode.HTML)
        await callback.answer("Вы успешно взяли пользователя!")
    except Exception as e:
        logger.error(f"Ошибка кнопки взять ПЗ: {e}")

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
                await bot.copy_message(chat_id=user_id, from_chat_id=ADMIN_CHAT_ID, message_id=message.message_id)
                await conn.execute("INSERT INTO messages (user_id, sender_type) VALUES ($1, 'admin');", user_id)
            except Exception as e:
                await message.reply(f"❌ Ошибка отправки: {e}")

# --- ЗАПУСК ---
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())