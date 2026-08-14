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

UNASSIGNED_TOPIC_ID = 765 
OWNER_ID = 8674242517

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
db_pool = None

# --- ИНИЦИАЛИЗАЦИЯ БД И МИГРАЦИИ ---
async def init_db():
    global db_pool
    if not DATABASE_URL: return
    try:
        db_pool = await asyncpg.create_pool(DATABASE_URL)
        async with db_pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY, 
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
            # Безопасные миграции колонок на случай старых баз
            for col, col_type in [
                ("admin_tag", "TEXT"), 
                ("rest_until", "TIMESTAMP"), 
                ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
            ]:
                try:
                    await conn.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type};")
                except asyncpg.exceptions.DuplicateColumnError:
                    pass
    except Exception as e: 
        logger.error(f"Ошибка БД: {e}")

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


# --- КОМАНДА /help ---
@dp.message(Command("help", "хелп"))
async def help_cmd(message: types.Message):
    if not await is_admin(message.from_user.id) and not await is_owner(message.from_user.id):
        return

    help_text = (
        "📌 <b>Список доступных команд:</b>\n\n"
        "👑 <b>Владелец / Администрация:</b>\n"
        "├ /stats — Статистика бота\n"
        "├ /adminstats (или .астат) — Статистика взятых ПЗ\n"
        "├ /adminlist (или .админы) — Список состава и тегов\n"
        "├ /check или .чек — Проверить пользователя\n"
        "├ /ban /unban [ID] — Управление банами\n"
        "├ /broadcast [текст] — Рассылка\n"
        "├ /rest [юз/ID] [дни] — Отправить в отпуск\n"
        "├ /addmins [юз/ID] [тег] — Установить админ-тег и назначить\n"
        "├ .ид юз — Узнать ID пользователя\n"
        "├ /setdirector [ID] — Назначить директора\n"
        "├ /setadmin [ID] — Назначить администратора\n"
        "├ /setintern [ID] — Назначить стажёра\n"
        "├ /demote [ID] — Понизить до пользователя\n"
        "└ /setowner — Подтвердить права Владельца"
    )
    await message.reply(help_text, parse_mode=ParseMode.HTML)


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

# --- СПИСОК АДМИНИСТРАТОРОВ (/adminlist /admins .админы) ---
@dp.message(F.text.in_({"/adminlist", "/admins", ".админы"}))
@dp.message(Command("adminlist", "admins"))
async def adminlist_cmd(message: types.Message):
    if not await is_admin(message.from_user.id): 
        return
    
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT username, user_id, role, admin_tag, 
                   EXTRACT(DAY FROM (NOW() - created_at))::INT as days_in_base
            FROM users 
            WHERE role IN ('owner', 'director', 'admin', 'intern') OR admin_tag IS NOT NULL
            ORDER BY 
                CASE role 
                    WHEN 'owner' THEN 1 
                    WHEN 'director' THEN 2 
                    WHEN 'admin' THEN 3 
                    WHEN 'intern' THEN 4 
                    ELSE 5 
                END;
        """)
        
    if not rows:
        await message.reply("❌ В базе данных пока нет администраторов.")
        return

    text_lines = ["🛡 <b>Список состава администрации:</b>\n"]
    for r in rows:
        uname = f"@{r['username']}" if r['username'] else f"ID: <code>{r['user_id']}</code>"
        tag = r['admin_tag'] if r['admin_tag'] else "без тега"
        days = r['days_in_base'] if r['days_in_base'] is not None else 0
        role = r['role'].upper()
        
        text_lines.append(f"• {uname} — <b>{tag}</b> — [{role}] — <b>{days} дн.</b> в базе")

    await message.reply("\n".join(text_lines), parse_mode=ParseMode.HTML)

# --- СТАТИСТИКА БОТА (/stats) ---
@dp.message(Command("stats"))
async def stats_cmd(message: types.Message):
    if not await is_admin(message.from_user.id): return
    async with db_pool.acquire() as conn:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users;")
        banned_users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_banned = TRUE;")
        active_users = total_users - banned_users
        
        owners = await conn.fetchval("SELECT COUNT(*) FROM users WHERE role = 'owner';")
        directors = await conn.fetchval("SELECT COUNT(*) FROM users WHERE role = 'director';")
        admins = await conn.fetchval("SELECT COUNT(*) FROM users WHERE role = 'admin';")
        interns = await conn.fetchval("SELECT COUNT(*) FROM users WHERE role = 'intern';")
        regular_users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE role = 'user' OR role IS NULL;")
        
        user_msgs = await conn.fetchval("SELECT COUNT(*) FROM messages WHERE sender_type = 'user';")
        admin_msgs = await conn.fetchval("SELECT COUNT(*) FROM messages WHERE sender_type = 'admin';")
        total_msgs = user_msgs + admin_msgs

    stats_text = (
        "📊 <b>Полная статистика бота:</b>\n\n"
        "👥 <b>Пользователи:</b>\n"
        f"├ Всего пользователей: {total_users}\n"
        f"├ 🍏 Активных (чистых): {active_users}\n"
        f"└ 🚫 Забаненных: {banned_users}\n\n"
        "🎭 <b>Разделение по ролям:</b>\n"
        f"├ 👑 Владелец: {owners if owners else 1}\n"
        f"├ 💼 Директоров: {directors}\n"
        f"├ 🛡 Администраторов: {admins}\n"
        f"├ 🔰 Стажёров: {interns}\n"
        f"└ 👤 Пользователей: {regular_users}\n\n"
        "✉️ <b>Сообщения и активность:</b>\n"
        f"├ 📩 От пользователей: {user_msgs}\n"
        f"├ 📤 От администраторов: {admin_msgs}\n"
        f"└ 💬 Всего сообщений: {total_msgs}"
    )
    await message.reply(stats_text, parse_mode=ParseMode.HTML)

# --- СТАТИСТИКА АДМИНИСТРАЦИИ (/adminstats или .астат) ---
@dp.message(F.text.in_({"/adminstats", ".астат"}))
@dp.message(Command("adminstats"))
async def adminstats_cmd(message: types.Message):
    if not await is_admin(message.from_user.id): return
    
    async with db_pool.acquire() as conn:
        async def get_top(days=None):
            time_clause = f"WHERE created_at >= NOW() - INTERVAL '{days} days'" if days else ""
            rows = await conn.fetch(f"""
                SELECT admin_username, COUNT(*) as cnt 
                FROM admin_actions 
                {time_clause} 
                GROUP BY admin_username 
                ORDER BY cnt DESC LIMIT 5;
            """)
            return rows

        today_rows = await get_top(1)
        week_rows = await get_top(7)
        month_rows = await get_top(30)
        all_rows = await get_top(None)

    def format_rows(rows):
        if not rows:
            return "<i>Нет данных</i>"
        out = []
        for idx, r in enumerate(rows, 1):
            uname = f"@{r['admin_username']}" if r['admin_username'] else "Неизвестно"
            out.append(f"{idx}. {uname} — {r['cnt']}")
        return "\n".join(out)

    text = (
        "📊 <b>Статистика работы администрации (взятые ПЗ):</b>\n\n"
        "📅 <b>За сегодня:</b>\n"
        f"{format_rows(today_rows)}\n\n"
        "📈 <b>За неделю (7 дней):</b>\n"
        f"{format_rows(week_rows)}\n\n"
        "🗓 <b>За месяц (30 дней):</b>\n"
        f"{format_rows(month_rows)}\n\n"
        "🏆 <b>За всё время:</b>\n"
        f"{format_rows(all_rows)}"
    )
    await message.reply(text, parse_mode=ParseMode.HTML)

# --- ОБРАБОТКА ЛИЧНЫХ СООБЩЕНИЙ ПОЛЬЗОВАТЕЛЕЙ ---
@dp.message(F.chat.type == "private")
async def private_msg(message: types.Message):
    user_id = message.from_user.id
    
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT topic_id, is_banned FROM users WHERE user_id = $1;", user_id)
        if user and user['is_banned']: 
            return

        topic_id = user['topic_id'] if user else None

        if not topic_id:
            username_str = f"@{message.from_user.username}" if message.from_user.username else f"ID: {user_id}"
            first_name = message.from_user.first_name or "Без имени"
            
            try:
                forum_topic = await bot.create_forum_topic(
                    chat_id=ADMIN_CHAT_ID, 
                    name=f"ПЗ: {first_name}"
                )
                topic_id = forum_topic.message_thread_id
                
                await conn.execute(
                    "INSERT INTO users (user_id, username, topic_id) VALUES ($1, $2, $3) ON CONFLICT (user_id) DO UPDATE SET topic_id = $3, username = $2;", 
                    user_id, message.from_user.username, topic_id
                )
                
                await bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    message_thread_id=topic_id,
                    text=f"📋 <b>Информация о новом пользователе:</b>\n"
                         f"├ Имя: {first_name}\n"
                         f"├ Юзернейм: {username_str}\n"
                         f"└ ID: <code>{user_id}</code>",
                    parse_mode=ParseMode.HTML
                )

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

        if message.text and message.text.startswith("/"):
            return

        if topic_id and message.text and not message.text.startswith("/"):
            try:
                forwarded = await bot.forward_message(
                    chat_id=ADMIN_CHAT_ID,
                    from_chat_id=user_id,
                    message_id=message.message_id,
                    message_thread_id=topic_id
                )
                await conn.execute(
                    "INSERT INTO messages (user_id, sender_type, user_msg_id, admin_msg_id) VALUES ($1, 'user', $2, $3);",
                    user_id, message.message_id, forwarded.message_id
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
                sent_msg = await bot.send_message(user_id, text, parse_mode=ParseMode.HTML)
                await conn.execute(
                    "INSERT INTO messages (user_id, sender_type, user_msg_id, admin_msg_id) VALUES ($1, 'admin', $2, $3);",
                    user_id, message.message_id, sent_msg.message_id
                )
            except Exception as e:
                logger.error(f"Ошибка отправки пользователю: {e}")

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())