import os
import logging
import asyncpg
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ParseMode

# --- НАСТРОЙКА ЛОГИРОВАНИЯ ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", 0)) if os.getenv("ADMIN_CHAT_ID") else None

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
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY, 
                    username TEXT, 
                    role TEXT DEFAULT 'user', 
                    is_banned BOOLEAN DEFAULT FALSE, 
                    topic_id INT, 
                    rest_until TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS messages (id SERIAL PRIMARY KEY, user_id BIGINT, sender_type TEXT, user_msg_id INT, admin_msg_id INT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS admin_actions (id SERIAL PRIMARY KEY, admin_id BIGINT, admin_username TEXT, target_user_id BIGINT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
            """)
            
            try:
                await conn.execute("ALTER TABLE users ADD COLUMN admin_tag TEXT;")
            except asyncpg.exceptions.DuplicateColumnError:
                pass
                
    except Exception as e:
        logger.error(f"Ошибка БД: {e}")

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
async def get_user_role(user_id: int) -> str:
    if user_id == OWNER_ID: return "owner"
    if not db_pool: return "user"
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT role, rest_until FROM users WHERE user_id = $1;", user_id)
            if not row: return "user"
            if row["rest_until"] and row["rest_until"] > datetime.now(): return "user"
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

# --- КОМАНДЫ ---

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    role = "owner" if message.from_user.id == OWNER_ID else "user"
    if db_pool:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO users (user_id, username, role) VALUES ($1, $2, $3) ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username;", 
                message.from_user.id, message.from_user.username, role
            )
    await message.reply("Привет! Пиши запрос в бот, и админ тебе ответит.")

@dp.message(Command("help", "хелп"))
async def help_cmd(message: types.Message):
    if not await is_admin(message.from_user.id) and not await is_owner(message.from_user.id):
        return

    help_text = (
        "📌 <b>Список доступных команд:</b>\n\n"
        "👑 <b>Владелец:</b>\n"
        "├ /stats — Статистика бота\n"
        "├ /adminstats (или .астат) — Статистика взятых ПЗ\n"
        "├ /check или .чек — Проверить пользователя\n"
        "├ /ban /unban [ID] — Управление банами\n"
        "├ /broadcast [текст] — Рассылка\n"
        "├ /rest [юз/ID] [дни] — Отправить в отпуск\n"
        "├ /addmins [юз/ID] [тег] — Установить админ-тег\n"
        "├ .ид юз — Узнать ID пользователя\n"
        "├ /setdirector [ID] — Назначить директора\n"
        "├ /setadmin [ID] — Назначить администратора\n"
        "├ /setintern [ID] — Назначить стажёра\n"
        "├ /demote [ID] — Понизить до пользователя\n"
        "└ /setowner — Подтвердить права Владельца"
    )
    await message.reply(help_text, parse_mode=ParseMode.HTML)

@dp.message(Command("addmins"))
async def addmins_cmd(message: types.Message, command: CommandObject):
    if not await is_owner(message.from_user.id): 
        return
    if not db_pool or not command.args:
        await message.reply("❌ Формат: /addmins [юз/ID] [тег]\nПример: /addmins @new_admin #helper")
        return
    
    args = command.args.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("❌ Нужно указать пользователя и тег. Пример: /addmins @user #тег")
        return
    
    target_arg, admin_tag = args[0], args[1].strip()
    if not admin_tag.startswith("#"):
        admin_tag = f"#{admin_tag}"

    async with db_pool.acquire() as conn:
        target_id = await get_target_user_id(conn, target_arg)
        if not target_id:
            await message.reply("❌ Пользователь не найден в базе (он должен хотя бы раз написать в бот или /start).")
            return
            
        await conn.execute(
            "UPDATE users SET role = 'admin', admin_tag = $1 WHERE user_id = $2;", 
            admin_tag, target_id
        )
        
        await message.reply(
            f"✅ Пользователь <code>{target_id}</code> успешно назначен <b>администратором</b>!\n"
            f"🏷 Установлен тег: <b>{admin_tag}</b>", 
            parse_mode=ParseMode.HTML
        )

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

@dp.message(F.text.in_({"/check", ".чек"}))
@dp.message(Command("check"))
async def check_cmd(message: types.Message, command: CommandObject = None):
    if not await is_admin(message.from_user.id): return
    
    target_id = None
    if command and command.args:
        async with db_pool.acquire() as conn:
            target_id = await get_target_user_id(conn, command.args)
    elif message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
        
    if not target_id:
        await message.reply("❌ Укажите пользователя через аргумент или ответьте на его сообщение.")
        return
        
    async with db_pool.acquire() as conn:
        user_data = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1;", target_id)
        if not user_data:
            await message.reply("❌ Пользователь не найден в базе.")
            return
            
        msg_count = await conn.fetchval("SELECT COUNT(*) FROM messages WHERE user_id = $1;", target_id)

    info = (
        f"👤 <b>Информация о пользователе:</b>\n\n"
        f"🆔 ID: <code>{user_data['user_id']}</code>\n"
        f"ᴜsername: @{user_data['username'] or 'отсутствует'}\n"
        f"🎭 Роль: {user_data['role']}\n"
        f"🚫 Забанен: {'Да' if user_data['is_banned'] else 'Нет'}\n"
        f"💬 Сообщений отправлено: {msg_count}"
    )
    await message.reply(info, parse_mode=ParseMode.HTML)

# --- ОБРАБОТЧИК СООБЩЕНИЙ ИЗ АДМИН-ЧАТА (ТОПИКОВ) ---
@dp.message(F.chat.id == ADMIN_CHAT_ID)
async def reply_from_topic(message: types.Message):
    if not message.message_thread_id or (message.text and message.text.startswith("/")): return
    
    async with db_pool.acquire() as conn:
        user_id = await conn.fetchval("SELECT user_id FROM users WHERE topic_id = $1;", message.message_thread_id)
        if user_id:
            admin_tag = await conn.fetchval("SELECT admin_tag FROM users WHERE user_id = $1;", message.from_user.id)
            tag = admin_tag if admin_tag else f"@{message.from_user.username}"
            
            text = f"<b>[{tag}]</b> {message.text}" if message.text else message.caption
            try:
                await bot.send_message(user_id, text, parse_mode=ParseMode.HTML)
            except Exception as e:
                logger.error(f"Ошибка отправки пользователю: {e}")

# --- ОБРАБОТЧИК ЛИЧНЫХ СООБЩЕНИЙ ОТ ПОЛЬЗОВАТЕЛЕЙ ---
@dp.message(F.chat.type == "private")
async def private_msg(message: types.Message):
    if message.text and message.text.startswith("/"):
        return
        
    user_id = message.from_user.id
    if not db_pool:
        return

    async with db_pool.acquire() as conn:
        is_banned = await conn.fetchval("SELECT is_banned FROM users WHERE user_id = $1;", user_id)
        if is_banned:
            return

        topic_id = await conn.fetchval("SELECT topic_id FROM users WHERE user_id = $1;", user_id)
        
        if not topic_id and ADMIN_CHAT_ID:
            try:
                username_str = f"@{message.from_user.username}" if message.from_user.username else f"ID: {user_id}"
                forum_topic = await bot.create_forum_topic(chat_id=ADMIN_CHAT_ID, name=f"{message.from_user.first_name} ({username_str})")
                topic_id = forum_topic.message_thread_id
                
                await conn.execute("UPDATE users SET topic_id = $1 WHERE user_id = $2;", topic_id, user_id)
            except Exception as e:
                logger.error(f"Не удалось создать топик: {e}")
                topic_id = UNASSIGNED_TOPIC_ID

        if ADMIN_CHAT_ID and topic_id:
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
                logger.error(f"Ошибка пересылки сообщения в админ-чат: {e}")

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())