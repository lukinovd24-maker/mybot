import asyncio
import logging
import asyncpg
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# Настройки логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- НАСТРОЙКИ ---
BOT_TOKEN = "ТВОЙ_ТОКЕН_БОТА"
ADMIN_CHAT_ID = -1001234567890  # ID твоей админ-группы (форума)
UNASSIGNED_TOPIC_ID = 765       # ID топика «Неразобранные»
DB_DSN = "postgresql://user:password@localhost:5432/dbname"  # Твои данные БД

# ID владельца бота (для доступа к командам постинга и назначения высших ролей)
OWNER_ID = 123456789 

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

db_pool: asyncpg.Pool = None

# Состояния для постинга
class PostState(StatesGroup):
    waiting_for_post = State()

# --- ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ ---
async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(dsn=DB_DSN)
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                topic_id INT
            );
            CREATE TABLE IF NOT EXISTS admins (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                role TEXT CHECK (role IN ('owner', 'director', 'admin', 'intern'))
            );
            CREATE TABLE IF NOT EXISTS admin_actions (
                id SERIAL PRIMARY KEY,
                admin_id BIGINT,
                admin_username TEXT,
                target_user_id BIGINT,
                action_time TIMESTAMP DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS channel_posts (
                post_id SERIAL PRIMARY KEY,
                message_id INT,
                channel_id BIGINT,
                text TEXT
            );
        """)
    logger.info("База данных успешно инициализирована.")

# --- УТИЛИТА ПРОВЕРКИ РОЛЕЙ ---
async def get_admin_role(user_id: int) -> str:
    if user_id == OWNER_ID:
        return 'owner'
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT role FROM admins WHERE user_id = $1;", user_id)
        return row["role"] if row else None

# --- СПРАВКА ПО КОМАНДАМ ---
@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    if message.chat.type == "private":
        return await message.answer("ℹ️ Это бот технической поддержки. Напишите ваше сообщение, и оно автоматически создаст обращение для администраторов.")
    
    caller_id = message.from_user.id
    role = await get_admin_role(caller_id)
    
    if not role:
        return await message.answer("❌ У вас нет доступа к командам администратора.")

    help_text = (
        "📌 <b>Список доступных команд:</b>\n\n"
        "👑 <b>Администрация:</b>\n"
        "├ /stats — Статистика бота\n"
        "├ /adminstats (или .астат) — Статистика взятых ПЗ\n"
        "├ /adminlist (или .админы) — Список состава и дней\n"
        "├ /check или .чек — Проверить пользователя\n"
        "├ /broadcast — Меню рассылки\n"
        "├ /addmins [юз/ID] [тег] — Установить админ-тег\n"
        "├ /id или .ид — Узнать ID пользователя\n"
        "├ /setdirector [юз/ID] — Назначить директора\n"
        "├ /setadmin [юз/ID] — Назначить администратора\n"
        "├ /setintern [юз/ID] — Назначить стажёра\n"
        "└ /demote [юз/ID] — Понизить до пользователя"
    )

    if caller_id == OWNER_ID:
        help_text += (
            "\n\n🛠 <b>Владелец:</b>\n"
            "└ /post — Опубликовать пост в канал"
        )

    await message.answer(help_text, parse_mode=ParseMode.HTML)

# --- КОМАНДЫ ПОСТИНГА (ТОЛЬКО ДЛЯ ВЛАДЕЛЬЦА) ---
@dp.message(Command("post"))
async def cmd_post(message: types.Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        return await message.answer("❌ У вас нет прав для этой команды.")
    
    await message.answer("📢 Отправьте текст или медиа с текстом для публикации в канал:")
    await state.set_state(PostState.waiting_for_post)

@dp.message(PostState.waiting_for_post)
async def process_post(message: types.Message, state: FSMContext):
    CHANNEL_ID = "@my_channel" # Укажи свой канал
    
    try:
        sent_msg = await message.send_copy(chat_id=CHANNEL_ID)
        async with db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO channel_posts (message_id, channel_id, text) VALUES ($1, $2, $3);",
                sent_msg.message_id, sent_msg.chat.id, message.html_text or message.text
            )
        await message.answer(f"✅ Пост успешно опубликован в канал! ID: {sent_msg.message_id}")
    except Exception as e:
        await message.answer(f"❌ Ошибка при публикации: {e}")
    finally:
        await state.clear()

# --- УПРАВЛЕНИЕ РОЛЯМИ АДМИНИСТРАЦИИ ---
@dp.message(Command(commands=["setdirector", "setadmin", "setintern", "demote"]))
async def set_role_command(message: types.Message):
    caller_id = message.from_user.id
    caller_role = await get_admin_role(caller_id)
    
    if caller_role not in ['owner', 'director']:
        return await message.answer("❌ Недостаточно прав для управления ролями.")

    args = message.text.split()
    if len(args) < 2:
        return await message.answer("⚠️ Использование: /command <user_id>")
    
    try:
        target_id = int(args[1])
    except ValueError:
        return await message.answer("❌ Неверный ID пользователя.")

    command = message.text.split()[0][1:]
    
    if command == "demote":
        async with db_pool.acquire() as conn:
            await conn.execute("DELETE FROM admins WHERE user_id = $1;", target_id)
        return await message.answer(f"✅ Пользователь <code>{target_id}</code> понижен до пользователя.", parse_mode=ParseMode.HTML)

    role_map = {
        "setdirector": "director",
        "setadmin": "admin",
        "setintern": "intern"
    }
    new_role = role_map.get(command)

    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO admins (user_id, role) VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE SET role = $2;
        """, target_id, new_role)
    
    await message.answer(f"✅ Пользователю <code>{target_id}</code> успешно назначена роль: <b>{new_role}</b>", parse_mode=ParseMode.HTML)

# --- СТАТИСТИКА ---
@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    async with db_pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM admin_actions WHERE admin_id = $1;", message.from_user.id)
    await message.answer(f"📊 Ваша статистика: вы взяли в работу обращений: <b>{count}</b>", parse_mode=ParseMode.HTML)

@dp.message(Command(commands=["adminstats", "астат"]))
async def cmd_admin_stats(message: types.Message):
    caller_role = await get_admin_role(message.from_user.id)
    if caller_role not in ['owner', 'director']:
        return await message.answer("❌ Недостаточно прав.")
        
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT admin_username, COUNT(*) as total 
            FROM admin_actions 
            GROUP BY admin_username 
            ORDER BY total DESC;
        """)
    
    text = "📈 <b>Общая статистика работы сотрудников:</b>\n\n"
    for r in rows:
        uname = f"@{r['admin_username']}" if r['admin_username'] else "Без юзернейма"
        text += f"▪️ {uname}: <b>{r['total']}</b> тикетов\n"
        
    await message.answer(text, parse_mode=ParseMode.HTML)

# --- ОБРАБОТКА ТИКЕТОВ И ОБЩЕНИЯ С ПОЛЬЗОВАТЕЛЯМИ ---
@dp.message(F.chat.type == "private")
async def private_msg(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    username_str = f"@{username}" if username else "Отсутствует"

    async with db_pool.acquire() as conn:
        user_row = await conn.fetchrow("SELECT topic_id FROM users WHERE user_id = $1;", user_id)

        if user_row and user_row["topic_id"]:
            topic_id = user_row["topic_id"]
        else:
            forum_topic = await bot.create_forum_topic(
                chat_id=ADMIN_CHAT_ID,
                name=f"{first_name} | {user_id}"
            )
            topic_id = forum_topic.message_thread_id

            await conn.execute("""
                INSERT INTO users (user_id, username, first_name, topic_id) 
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (user_id) DO UPDATE SET topic_id = $4, username = $2, first_name = $3;
            """, user_id, username, first_name, topic_id)

            # Карточка в персональный топик
            await bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                message_thread_id=topic_id,
                text=(
                    f"📋 <b>Информация о новом пользователе:</b>\n"
                    f"├ Имя: {first_name}\n"
                    f"├ Юзернейм: {username_str}\n"
                    f"└ ID: <code>{user_id}</code>\n\n"
                    f"⏳ <i>Статус: ПЗ ожидает назначения сотрудника.</i>"
                ),
                parse_mode=ParseMode.HTML
            )

            # Карточка в неразобранные (ID 765) с кнопкой
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🟢 Взять обращение", callback_data=f"take_pz_{user_id}")]
            ])
            await bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                message_thread_id=UNASSIGNED_TOPIC_ID,
                text=(
                    f"⚠️ <b>Новое обращение (ПЗ без администратора!)</b>\n\n"
                    f"👤 Пользователь: {username_str}\n"
                    f"🆔 ID: <code>{user_id}</code>\n"
                    f"📝 Имя: {first_name}\n\n"
                    f"<i>Ожидает сотрудника. Нажмите кнопку ниже, чтобы взять тикет в работу.</i>"
                ),
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML
            )

    await message.send_copy(chat_id=ADMIN_CHAT_ID, message_thread_id=topic_id)

# --- КНОПКА ВЗЯТИЯ ПЗ ---
@dp.callback_query(F.data.startswith("take_pz_"))
async def take_pz(callback: types.CallbackQuery):
    target_id = int(callback.data.split("_")[2])
    admin_mention = f"@{callback.from_user.username}" if callback.from_user.username else callback.from_user.first_name
    
    async with db_pool.acquire() as conn:
        user_row = await conn.fetchrow("SELECT username, topic_id FROM users WHERE user_id = $1;", target_id)
        
        await conn.execute(
            "INSERT INTO admin_actions (admin_id, admin_username, target_user_id) VALUES ($1, $2, $3);", 
            callback.from_user.id, callback.from_user.username, target_id
        )

    if not user_row or not user_row["topic_id"]:
        return await callback.answer("❌ Ошибка: топик пользователя не найден.", show_alert=True)

    user_topic_id = user_row["topic_id"]
    username_str = f"@{user_row['username']}" if user_row['username'] else f"ID: {target_id}"

    chat_id_str = str(ADMIN_CHAT_ID)
    clean_chat_id = chat_id_str[4:] if chat_id_str.startswith("-100") else chat_id_str.lstrip("-")
    topic_link = f"https://t.me/c/{clean_chat_id}/{user_topic_id}"

    pz_info_text = (
        f"✅ <b>Обращение взято в работу!</b>\n\n"
        f"👤 Пользователь: {username_str} (<code>{target_id}</code>)\n"
        f"🛡 Сотрудник: <b>{admin_mention}</b>\n"
        f"🔗 <a href='{topic_link}'>Перейти в персональный топик ПЗ</a>"
    )

    try:
        await callback.message.edit_text(pz_info_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Не удалось обновить сообщение в неразобранных: {e}")

    try:
        await bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            message_thread_id=user_topic_id,
            text=f"🟢 <b>ПЗ успешно закреплено за администратором {admin_mention}!</b>",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Не удалось отправить уведомление в личный топик: {e}")

    await callback.answer("Вы успешно взяли ПЗ!")

# --- ОТВЕТ АДМИНА ИЗ ТОПИКА ПОЛЬЗОВАТЕЛЮ ---
@dp.message(F.chat.id == ADMIN_CHAT_ID)
async def admin_reply(message: types.Message):
    if not message.message_thread_id or message.message_thread_id == UNASSIGNED_TOPIC_ID:
        return
        
    if message.from_user.is_bot:
        return

    async with db_pool.acquire() as conn:
        user_row = await conn.fetchrow("SELECT user_id FROM users WHERE topic_id = $1;", message.message_thread_id)

    if user_row:
        user_id = user_row["user_id"]
        try:
            await message.send_copy(chat_id=user_id)
        except Exception as e:
            await message.reply(f"❌ Не удалось отправить сообщение пользователю: {e}")

# --- ЗАПУСК БОТА ---
async def main():
    await init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Бот запущен и готов к работе.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())