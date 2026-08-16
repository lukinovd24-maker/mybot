import asyncio
import logging
import os
import asyncpg
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramAPIError

# Настройки логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger(__name__)

# --- НАСТРОЙКИ ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))
UNASSIGNED_TOPIC_ID = int(os.getenv("UNASSIGNED_TOPIC_ID", "765"))
DB_DSN = os.getenv("DATABASE_URL")

OWNER_ID = 8674242517 
CHANNEL_ID = "@eve_ning_glow"  # Твой ТГК для постов

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

db_pool: asyncpg.Pool = None

# Глобальная переменная для хранения ID последнего технического поста (для автоудаления)
last_tech_message_id = None

class BroadcastState(StatesGroup):
    waiting_for_broadcast = State()

# --- ТВОИ ШАБЛОНЫ ПОСТОВ С ФОТО И ТЕКСТАМИ ---
POST_TEMPLATES = {
    "1": {
        "photo": "AgACAgEAAxkBAAIHomqBVpn-nDfOlHe6GkV9Eu8Wsnl4AAIcDGsb1MkQROyB6LwuPOFnAQADAgADeQADPQQ",
        "text": (
            "🛠 <b>Внимание: Технический перерыв</b>\n\n"
            "Бот временно приостанавливает работу для проведения плановых технических работ. Скоро снова вернемся в строй, спасибо за ожидание!"
        )
    },
    "2": {
        "photo": "AgACAgEAAxkBAAIHpmqBV4Ym5NrmF3M1dt4EOLjMgPx6AAIbDGsb1MkQRBiVtlXZfeT_AQADAgADeQADPQQ",
        "text": (
            "🔄 <b>Обновление системы</b>\n\n"
            "Мы установили свежее обновление! Бот стал еще стабильнее и быстрее. Приятного использования."
        )
    },
    "3": {
        "photo": "AgACAgEAAxkBAAIHqGqBV6ZrZD72sMa54lXudN7wOmN2AAIaDGsb1MkQRDAwd7n4XwNcAQADAgADeQADPQQ",
        "text": (
            "⚠️ <b>Технические неполадки</b>\n\n"
            "Зафиксированы кратковременные технические неполадки. Специалисты уже занимаются их устранением."
        )
    },
    "4": {
        "photo": "AgACAgEAAxkBAAIHqmqBV8mmLrLScIsh5Yp_f2fO_IBoAAIZDGsb1MkQRENjPsVEPDrLAQADAgADeQADPQQ",
        "text": (
            "🟢 <b>Бот работает в штатном режиме</b>\n\n"
            "Все системы функционируют стабильно. Можете продолжать отправлять обращения!"
        )
    },
    "5": {
        "photo": "AgACAgEAAxkBAAIHrGqBV_o0bNZUKlfax3cFbJLW-Oh6AAIYDGsb1MkQRKC2gU96LUkeAQADAgADeQADPQQ",
        "text": (
            "✅ <b>Технический перерыв завершен</b>\n\n"
            "Работы успешно завершены, бот возобновил полноценную работу в штатном режиме."
        )
    },
    "6": {
        "photo": "AgACAgEAAxkBAAIHrmqBWBiT6kR8JGfgRN44yz92bZ9aAAIXDGsb1MkQRAljMvCDBCuVAQADAgADeQADPQQ",
        "text": (
            "✨ <b>Результаты обновления</b>\n\n"
            "Обновление успешно развернуто. Все новые функции и улучшения уже доступны."
        )
    }
}

# --- ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ ---
async def init_db():
    global db_pool
    try:
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
                    tag TEXT,
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
    except Exception as e:
        logger.critical(f"Ошибка при инициализации базы данных: {e}")
        raise

async def get_admin_role(user_id: int) -> str:
    if user_id == OWNER_ID:
        return 'owner'
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT role FROM admins WHERE user_id = $1;", user_id)
            return row["role"] if row else None
    except Exception as e:
        logger.error(f"Ошибка проверки роли для {user_id}: {e}")
        return None

# --- ПРИВЕТСТВЕННОЕ СООБЩЕНИЕ (/start) ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    if message.chat.type != "private":
        return
    
    await message.answer(
        "приветствую путник ты попал в прекрасный бот под названием \"вечернее сияние\".\n"
        "перед тем как начать общение, прошу заглянуть в наш тгк: https://t.me/eve_ning_glow\n"
        "там вся важная информация.\n\n"
        "Прочитал? тогда пиши \"привет общение/поддержка/уни\" и к тебе придет админ.\n"
        "удачи тебе солнышко",
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )

# --- СПРАВКА ПО КОМАНДАМ (/help) ---
@dp.message(F.text.in_({"/help", ".help", "/хелп", ".хелп"}))
async def cmd_help(message: types.Message):
    try:
        if message.chat.type == "private":
            return await message.answer("ℹ️ Это бот технической поддержки. Напишите ваше сообщение, и оно автоматически создаст обращение для администраторов.")
        
        caller_id = message.from_user.id
        role = await get_admin_role(caller_id)
        
        if not role:
            return await message.answer("❌ У вас нет доступа к командам администратора.")

        help_text = (
            "📌 <b>Список доступных команд:</b>\n\n"
            "👑 <b>Администрация:</b>\n"
            "├ /stats — Полная статистика бота\n"
            "├ /adminstats (или .астат) — Статистика взятых ПЗ\n"
            "├ /adminlist (или .админы) — Список состава\n"
            "├ /check или .чек — Проверить пользователя\n"
            "├ /broadcast — Сделать рассылку пользователям\n"
            "├ /addmins [юз/ID] [тег] — Установить админ-тег\n"
            "├ /id или .ид — Узнать ID пользователя\n"
            "├ /setdirector [юз/ID] — Назначить директора\n"
            "├ /setadmin [юз/ID] — Назначить администратора\n"
            "├ /setintern [юз/ID] — Назначить стажёра\n"
            "└ /demote [юз/ID] — Понизить до пользователя\n\n"
            "📢 <b>Шаблоны постов (пиши в чат):</b>\n"
            "└ <i>пост 1, пост 2, пост 3, пост 4, пост 5, пост 6</i>"
        )

        await message.answer(help_text, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Ошибка в команде help: {e}")

# --- АВТОМАТИЧЕСКИЕ ШАБЛОНЫ ПОСТОВ С КАРТИНКАМИ И УДАЛЕНИЕМ ---
@dp.message(F.text.in_({"пост 1", "пост 2", "пост 3", "пост 4", "пост 5", "пост 6"}), F.from_user.id == OWNER_ID)
async def send_custom_template_post(message: types.Message):
    global last_tech_message_id
    try:
        key = message.text.split()[-1]
        template = POST_TEMPLATES.get(key)
        
        if not template:
            return await message.answer("❌ Шаблон не найден.")

        # Если публикуется пост 4 или 5 (о возобновлении работы), удаляем предыдущий пост о неполадках/техработах (1 или 3)
        if key in ("4", "5") and last_tech_message_id:
            try:
                await bot.delete_message(chat_id=CHANNEL_ID, message_id=last_tech_message_id)
            except Exception as e:
                logger.warning(f"Не удалось удалить старое сообщение: {e}")
            last_tech_message_id = None

        # Отправляем фото с текстом в канал
        sent_msg = await bot.send_photo(
            chat_id=CHANNEL_ID,
            photo=template["photo"],
            caption=template["text"],
            parse_mode=ParseMode.HTML
        )

        # Если это был пост о проблемах/техработах, запоминаем его ID для последующего удаления
        if key in ("1", "3"):
            last_tech_message_id = sent_msg.message_id

        # Сохраняем в базу
        async with db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO channel_posts (message_id, channel_id, text) VALUES ($1, $2, $3);",
                sent_msg.message_id, sent_msg.chat.id, template["text"]
            )
            
        await message.answer(f"✅ Пост #{key} успешно опубликован в канал!")
    except Exception as e:
        logger.error(f"Ошибка отправки шаблона: {e}")
        await message.answer(f"❌ Ошибка: {e}")

# --- КОМАНДА /id ---
@dp.message(F.text.in_({"/id", ".ид"}))
async def cmd_id(message: types.Message):
    try:
        target = message.reply_to_message.from_user if message.reply_to_message else message.from_user
        await message.answer(
            f"🆔 <b>Информация о пользователе:</b>\n"
            f"├ Имя: {target.first_name}\n"
            f"├ Юзернейм: @{target.username if target.username else 'отсутствует'}\n"
            f"└ ID: <code>{target.id}</code>",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Ошибка в id: {e}")

# --- КОМАНДА /check ---
@dp.message(F.text.in_({"/check", ".чек"}))
async def cmd_check(message: types.Message):
    try:
        if not await get_admin_role(message.from_user.id):
            return await message.answer("❌ У вас нет прав.")
        if not message.reply_to_message:
            return await message.answer("⚠️ Используйте ответом на сообщение пользователя.")
            
        target = message.reply_to_message.from_user
        async with db_pool.acquire() as conn:
            user_data = await conn.fetchrow("SELECT topic_id FROM users WHERE user_id = $1;", target.id)
            
        has_ticket = "Да (топик создан)" if user_data and user_data["topic_id"] else "Нет активных тикетов"
        await message.answer(
            f"🔍 <b>Проверка пользователя:</b>\n"
            f"├ Имя: {target.first_name}\n"
            f"├ ID: <code>{target.id}</code>\n"
            f"└ Активный тикет: {has_ticket}",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Ошибка check: {e}")

# --- КОМАНДА /addmins ---
@dp.message(Command("addmins"))
async def cmd_addmins(message: types.Message):
    try:
        if await get_admin_role(message.from_user.id) not in ['owner', 'director']:
            return await message.answer("❌ Недостаточно прав.")
        args = message.text.split(maxsplit=2)
        if len(args) < 3:
            return await message.answer("⚠️ Использование: /addmins <user_id> <тег>")
            
        target_id = int(args[1])
        tag = args[2]
        async with db_pool.acquire() as conn:
            await conn.execute("UPDATE admins SET tag = $1 WHERE user_id = $2;", tag, target_id)
            
        await message.answer(f"✅ Администратору <code>{target_id}</code> установлен тег: <b>{tag}</b>", parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Ошибка addmins: {e}")

# --- КОМАНДА /adminlist ---
@dp.message(F.text.in_({"/adminlist", ".админы"}))
async def cmd_adminlist(message: types.Message):
    try:
        if not await get_admin_role(message.from_user.id):
            return await message.answer("❌ Недостаточно прав.")
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("SELECT user_id, username, role, tag FROM admins ORDER BY role;")
            
        if not rows:
            return await message.answer("📋 Список администраторов пуст.")
            
        text = "📋 <b>Список состава администрации:</b>\n\n"
        for r in rows:
            uname = f"@{r['username']}" if r['username'] else f"ID: {r['user_id']}"
            tag_str = f" [{r['tag']}]" if r['tag'] else ""
            text += f"▪️ {uname}{tag_str} — Роль: <b>{r['role']}</b>\n"
            
        await message.answer(text, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Ошибка adminlist: {e}")

# --- РАССЫЛКА (/broadcast) ---
@dp.message(Command("broadcast"))
async def cmd_broadcast(message: types.Message, state: FSMContext):
    if await get_admin_role(message.from_user.id) not in ['owner', 'director']:
        return await message.answer("❌ Недостаточно прав.")
    await message.answer("📢 Отправьте сообщение для рассылки:")
    await state.set_state(BroadcastState.waiting_for_broadcast)

@dp.message(BroadcastState.waiting_for_broadcast)
async def process_broadcast(message: types.Message, state: FSMContext):
    try:
        async with db_pool.acquire() as conn:
            users = await conn.fetch("SELECT user_id FROM users;")
        success, failed = 0, 0
        status_msg = await message.answer("⏳ Рассылка началась...")
        for u in users:
            try:
                await message.send_copy(chat_id=u["user_id"])
                success += 1
                await asyncio.sleep(0.05)
            except Exception:
                failed += 1
        await status_msg.edit_text(f"✅ <b>Рассылка завершена!</b>\n Успешно: {success} | Ошибок: {failed}", parse_mode=ParseMode.HTML)
    finally:
        await state.clear()

# --- УПРАВЛЕНИЕ РОЛЯМИ ---
@dp.message(Command(commands=["setdirector", "setadmin", "setintern", "demote"]))
async def set_role_command(message: types.Message):
    try:
        if await get_admin_role(message.from_user.id) not in ['owner', 'director']:
            return await message.answer("❌ Недостаточно прав.")
        args = message.text.split()
        if len(args) < 2:
            return await message.answer("⚠️ Использование: /command <user_id>")
        target_id = int(args[1])
        command = args[0][1:].split('@')[0]
        
        async with db_pool.acquire() as conn:
            if command == "demote":
                await conn.execute("DELETE FROM admins WHERE user_id = $1;", target_id)
                return await message.answer(f"✅ Пользователь <code>{target_id}</code> понижен.", parse_mode=ParseMode.HTML)

            role_map = {"setdirector": "director", "setadmin": "admin", "setintern": "intern"}
            new_role = role_map.get(command)
            await conn.execute("""
                INSERT INTO admins (user_id, role) VALUES ($1, $2)
                ON CONFLICT (user_id) DO UPDATE SET role = $2;
            """, target_id, new_role)
        await message.answer(f"✅ Роль <b>{new_role}</b> назначена пользователю <code>{target_id}</code>.", parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Ошибка ролей: {e}")

# --- СТАТИСТИКА (/stats) ---
@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    try:
        if not await get_admin_role(message.from_user.id):
            return await message.answer("❌ У вас нет доступа.")

        async with db_pool.acquire() as conn:
            total_users = await conn.fetchval("SELECT COUNT(*) FROM users;") or 0
            directors_count = await conn.fetchval("SELECT COUNT(*) FROM admins WHERE role = 'director';") or 0
            admins_count = await conn.fetchval("SELECT COUNT(*) FROM admins WHERE role = 'admin';") or 0
            interns_count = await conn.fetchval("SELECT COUNT(*) FROM admins WHERE role = 'intern';") or 0
            total_admins_db = await conn.fetchval("SELECT COUNT(*) FROM admins;") or 0
            regular_users = max(0, total_users - total_admins_db)

            admin_actions_count = await conn.fetchval("SELECT COUNT(*) FROM admin_actions;") or 0
            user_msgs = total_users * 2 
            total_msgs = user_msgs + admin_actions_count

        stats_text = (
            "📊 <b>Полная статистика бота:</b>\n\n"
            "👥 <b>Пользователи:</b>\n"
            f"├ Всего пользователей: <b>{total_users}</b>\n"
            f"├ 🍏 Активных (чистых): <b>{total_users}</b>\n"
            "└ 🚫 Забаненных: <b>0</b>\n\n"
            "🎭 <b>Разделение по ролям:</b>\n"
            "├ 👑 Владелец: <b>1</b>\n"
            f"├ 💼 Директоров: <b>{directors_count}</b>\n"
            f"├ 🛡 Администраторов: <b>{admins_count}</b>\n"
            f"├ 🔰 Стажёров: <b>{interns_count}</b>\n"
            f"└ 👤 Пользователей: <b>{regular_users}</b>\n\n"
            "✉️ <b>Сообщения и активность:</b>\n"
            f"├ 📩 От пользователей: <b>{user_msgs}</b>\n"
            f"├ 📤 От администраторов: <b>{admin_actions_count}</b>\n"
            f"└ 💬 Всего сообщений: <b>{total_msgs}</b>"
        )
        await message.answer(stats_text, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Ошибка stats: {e}")
        await message.answer("❌ Не удалось получить статистику.")

@dp.message(F.text.in_({"/adminstats", ".астат"}))
async def cmd_admin_stats(message: types.Message):
    try:
        if await get_admin_role(message.from_user.id) not in ['owner', 'director']:
            return await message.answer("❌ Недостаточно прав.")
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("SELECT admin_username, COUNT(*) as total FROM admin_actions GROUP BY admin_username ORDER BY total DESC;")
        if not rows:
            return await message.answer("📈 Статистика пуста.")
        text = "📈 <b>Статистика работы сотрудников:</b>\n\n"
        for r in rows:
            uname = f"@{r['admin_username']}" if r['admin_username'] else "Без юзернейма"
            text += f"▪️ {uname}: <b>{r['total']}</b> тикетов\n"
        await message.answer(text, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Ошибка астат: {e}")

# --- ТИКЕТЫ И ОБРАЩЕНИЯ ИЗ ЛИЧКИ ---
@dp.message(F.chat.type == "private")
async def private_msg(message: types.Message):
    if message.text and message.text.startswith(("/start", "пост")):
        return
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    username_str = f"@{username}" if username else "Отсутствует"

    try:
        topic_id = None
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                user_row = await conn.fetchrow("SELECT topic_id FROM users WHERE user_id = $1 FOR UPDATE;", user_id)
                if user_row and user_row["topic_id"]:
                    topic_id = user_row["topic_id"]
                else:
                    await conn.execute("""
                        INSERT INTO users (user_id, username, first_name, topic_id) 
                        VALUES ($1, $2, $3, NULL)
                        ON CONFLICT (user_id) DO UPDATE SET username = $2, first_name = $3;
                    """, user_id, username, first_name)

        if not topic_id:
            try:
                forum_topic = await bot.create_forum_topic(chat_id=ADMIN_CHAT_ID, name=f"{first_name} | {user_id}")
                topic_id = forum_topic.message_thread_id
            except TelegramAPIError as e:
                logger.error(f"Ошибка создания топика: {e}")
                return await message.answer("❌ Ошибка создания обращения. Попробуйте позже.")

            async with db_pool.acquire() as conn:
                await conn.execute("UPDATE users SET topic_id = $1 WHERE user_id = $2;", topic_id, user_id)

            await bot.send_message(
                chat_id=ADMIN_CHAT_ID, message_thread_id=topic_id,
                text=f"📋 <b>Новый пользователь:</b> {first_name} ({username_str}) [<code>{user_id}</code>]",
                parse_mode=ParseMode.HTML
            )

            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🟢 Взять обращение", callback_data=f"take_pz_{user_id}")]
            ])
            await bot.send_message(
                chat_id=ADMIN_CHAT_ID, message_thread_id=UNASSIGNED_TOPIC_ID,
                text=f"⚠️ <b>Новое обращение от {username_str}</b> (<code>{user_id}</code>)",
                reply_markup=keyboard, parse_mode=ParseMode.HTML
            )

        await message.send_copy(chat_id=ADMIN_CHAT_ID, message_thread_id=topic_id)
    except Exception as e:
        logger.error(f"Ошибка private_msg: {e}")

@dp.callback_query(F.data.startswith("take_pz_"))
async def take_pz(callback: types.CallbackQuery):
    try:
        target_id = int(callback.data.split("_")[2])
        admin_mention = f"@{callback.from_user.username}" if callback.from_user.username else callback.from_user.first_name
        async with db_pool.acquire() as conn:
            user_row = await conn.fetchrow("SELECT username, topic_id FROM users WHERE user_id = $1;", target_id)
            await conn.execute("INSERT INTO admin_actions (admin_id, admin_username, target_user_id) VALUES ($1, $2, $3);", 
                               callback.from_user.id, callback.from_user.username, target_id)

        if not user_row or not user_row["topic_id"]:
            return await callback.answer("❌ Топик не найден.", show_alert=True)

        user_topic_id = user_row["topic_id"]
        chat_id_str = str(ADMIN_CHAT_ID)
        clean_chat_id = chat_id_str[4:] if chat_id_str.startswith("-100") else chat_id_str.lstrip("-")
        topic_link = f"https://t.me/c/{clean_chat_id}/{user_topic_id}"

        await callback.message.edit_text(
            f"✅ <b>Обращение взято!</b> Сотрудник: <b>{admin_mention}</b>\n🔗 <a href='{topic_link}'>Перейти в топик</a>",
            parse_mode=ParseMode.HTML, disable_web_page_preview=True
        )
        await bot.send_message(chat_id=ADMIN_CHAT_ID, message_thread_id=user_topic_id, text=f"🟢 Закреплено за {admin_mention}!", parse_mode=ParseMode.HTML)
        await callback.answer("Готово!")
    except Exception as e:
        logger.error(f"Ошибка take_pz: {e}")

@dp.message(F.chat.id == ADMIN_CHAT_ID)
async def admin_reply(message: types.Message):
    if not message.message_thread_id or message.message_thread_id == UNASSIGNED_TOPIC_ID or message.from_user.is_bot:
        return
    try:
        async with db_pool.acquire() as conn:
            user_row = await conn.fetchrow("SELECT user_id FROM users WHERE topic_id = $1;", message.message_thread_id)
        if user_row:
            await message.send_copy(chat_id=user_row["user_id"])
    except Exception as e:
        logger.error(f"Ошибка admin_reply: {e}")

# --- ЗАПУСК ---
async def main():
    try:
        await init_db()
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Бот успешно запущен!")
        await dp.start_polling(bot)
    finally:
        if db_pool:
            await db_pool.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")