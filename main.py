import asyncio
import logging
import os
import random
from datetime import datetime, timezone, timedelta
from typing import Callable, Dict, Any, Awaitable

import asyncpg
from aiogram import Bot, Dispatcher, F, types, BaseMiddleware
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, 
    WebAppInfo, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from aiogram.exceptions import TelegramAPIError

# --- НАСТРОЙКИ ЛОГИРОВАНИЯ ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s")
logger = logging.getLogger(__name__)

# --- НАСТРОЙКИ БОТА ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))
UNASSIGNED_TOPIC_ID = int(os.getenv("UNASSIGNED_TOPIC_ID", "765"))
DB_DSN = os.getenv("DATABASE_URL")
OWNER_ID = 8674242517 
CHANNEL_ID = "@eve_ning_glow"

TZ = timezone(timedelta(hours=5))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
db_pool: asyncpg.Pool = None

# Глобальные переменные
photo_id_mode = False 
warned_unauthorized_users = set()
profiled_biz_users = set()

# --- СОСТОЯНИЯ ---
class BotStates(StatesGroup):
    waiting_for_broadcast_audience = State()
    waiting_for_broadcast_n = State()
    waiting_for_broadcast = State()
    waiting_for_anon = State()

class AdminStates(StatesGroup):
    waiting_rest_days = State()
    waiting_rest_reason = State()
    waiting_appeal_text = State()

# --- КОНТЕНТ ---
QUOTES = [
    "Звезды не могут сиять без темноты. Твои трудности делают тебя ярче. ✨",
    "Даже в самой темной ночи есть луч света, и сегодня этот луч — ты.",
    "Сделай глубокий вдох. Ты справляешься намного лучше, чем тебе кажется.",
    "Не забывай отдыхать. Твоя внутренняя батарейка тоже требует подзарядки. 🔋",
    "Вечер — это время, когда можно оставить все тревоги позади и просто быть собой.",
    "Самые красивые закаты бывают после самых тяжелых дней.",
    "Твой внутренний свет способен согреть даже самый холодный вечер. 🕯",
    "Ошибаться — нормально. Завтра будет новый день и новая попытка.",
    "Уют кроется в мелочах: в горячем чае, тихой музыке и спокойных мыслях. ☕️"
]

HUGS = [
    "*Крепко обнимает* Все обязательно будет хорошо, я в тебя верю! ❤️",
    "Посылаю тебе виртуальный плед и кружку горячего какао ☕️ Укутывайся и отдыхай!",
    "Эй, солнышко! Ты огромный молодец. Горжусь тем, как ты справляешься со всем этим. 🫂",
    "Если день был тяжелым, помни, что теперь он закончился. Завтра будет легче. *Теплые обнимашки* 🌙",
    "Лови тысячу лучей поддержки! Ты не один, мы рядом. ☀️",
    "*Гладит по голове* Ты стараешься, и это самое главное. Отдохни сегодня как следует."
]

FAQ_TEXT = (
    "ℹ️ <b>Ответы на частые вопросы (FAQ):</b>\n\n"
    "<b>1. Как стать частью команды?</b>\n— Открываем набор стажёров в канале @eve_ning_glow.\n\n"
    "<b>2. Как долго ждать ответа?</b>\n— Обычно 1-2 часа. Не дублируйте сообщения! 🫂\n\n"
    "<b>3. Для чего этот бот?</b>\n— Задать вопрос, предложить идею или получить поддержку. ☕️\n\n"
    "<i>Остались вопросы? Просто напишите их следующим сообщением!</i> 🌙"
)

RULES_TEXT = (
    "📜 <b>Правила нашего уютного уголка:</b>\n\n"
    "<b>1. Взаимоуважение — прежде всего 🫂</b>\nЛюбые оскорбления строго запрещены.\n\n"
    "<b>2. Терпение — добродетель 🕰</b>\nНе спамьте «Ау», админы ответят!\n\n"
    "<b>3. Никакого шок-контента и 18+ 🔞</b>\n\n"
    "<i>⚠️ За нарушение — вечный бан.</i>"
)

# --- ИНИЦИАЛИЗАЦИЯ БД ---
async def init_db():
    global db_pool
    try:
        db_pool = await asyncpg.create_pool(dsn=DB_DSN)
        async with db_pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY, username TEXT, first_name TEXT,
                    topic_id INT, warmth INT DEFAULT 0, msg_count INT DEFAULT 0,
                    join_date TIMESTAMP DEFAULT NOW(), care_sub BOOLEAN DEFAULT FALSE,
                    is_blocked BOOLEAN DEFAULT FALSE, is_banned BOOLEAN DEFAULT FALSE
                );

                CREATE TABLE IF NOT EXISTS admins (
                    user_id BIGINT PRIMARY KEY, username TEXT, role TEXT, tag TEXT,
                    warns INT DEFAULT 0, curator_id BIGINT, taken_tickets INT DEFAULT 0,
                    closed_tickets INT DEFAULT 0, rating_sum INT DEFAULT 0, rating_count INT DEFAULT 0,
                    rest_until TIMESTAMP
                );
                
                CREATE TABLE IF NOT EXISTS admin_actions (
                    id SERIAL PRIMARY KEY, admin_id BIGINT, admin_username TEXT,
                    target_user_id BIGINT, action_time TIMESTAMP DEFAULT NOW(),
                    status TEXT DEFAULT 'open', closed_time TIMESTAMP
                );
            """)
            await conn.execute("""
                INSERT INTO admins (user_id, role, tag) VALUES ($1, 'owner', 'Владелец')
                ON CONFLICT (user_id) DO UPDATE SET role = 'owner', tag = 'Владелец';
            """, OWNER_ID)
    except Exception as e:
        logger.critical(f"Ошибка БД: {e}")

async def get_admin_role(user_id: int) -> str:
    if user_id == OWNER_ID: return 'owner'
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT role FROM admins WHERE user_id = $1;", user_id)
            return row["role"] if row else None
    except Exception: return None

# --- СИСТЕМНАЯ СИГНАЛИЗАЦИЯ ---
class SecurityMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if isinstance(event, types.Message):
            if event.chat.id == ADMIN_CHAT_ID and not event.from_user.is_bot:
                user_id = event.from_user.id
                role = await get_admin_role(user_id)
                if not role and user_id not in warned_unauthorized_users:
                    warned_unauthorized_users.add(user_id)
                    admin_mention = f"@{event.from_user.username}" if event.from_user.username else event.from_user.first_name
                    try:
                        await bot.send_message(
                            chat_id=OWNER_ID,
                            text=f"🚨 <b>Система безопасности!</b>\n"
                                 f"В админ-чате написал пользователь без роли!\n\n"
                                 f"👤 Пользователь: {admin_mention}\n"
                                 f"🆔 ID: <code>{user_id}</code>\n\n"
                                 f"<i>Вы можете выдать ему роль (командой /setintern) или удалить из чата.</i>",
                            parse_mode=ParseMode.HTML
                        )
                    except Exception: pass
        return await handler(event, data)


# --- ПАНЕЛЬ ВЛАДЕЛЬЦА (MINI APP) ---
@dp.message(Command("panel"), F.from_user.id == OWNER_ID)
async def cmd_panel(message: types.Message):
    try: await message.delete()
    except Exception: pass
    async with db_pool.acquire() as conn: admins_count = await conn.fetchval("SELECT COUNT(*) FROM admins;") or 0
    try: chat_count = (await bot.get_chat_member_count(ADMIN_CHAT_ID)) - 1
    except Exception: chat_count = 0
    without_role = max(0, chat_count - admins_count)
    
    final_url = f"https://lukinovd24-maker.github.io/bot-panel/?chat_count={chat_count}&admins={admins_count}&without_role={without_role}"
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Открыть панель управления", web_app=WebAppInfo(url=final_url))]], resize_keyboard=True)
    await message.answer("👑 <b>Панель готова!</b> Кнопка внизу экрана.", reply_markup=kb, parse_mode=ParseMode.HTML)

@dp.message(Command("closepanel"), F.from_user.id == OWNER_ID)
async def cmd_close_panel(message: types.Message):
    await message.answer("Панель скрыта.", reply_markup=ReplyKeyboardRemove())

@dp.message(F.web_app_data)
async def process_web_app_data(message: types.Message):
    if message.from_user.id != OWNER_ID: return
    data = message.web_app_data.data
    
    if data == "get_stats": await cmd_stats(message)
    elif data == "get_admins": await cmd_adminlist(message)
    
    elif data == "get_active_tickets":
        async with db_pool.acquire() as conn:
            tickets = await conn.fetch("SELECT target_user_id, admin_id, admin_username FROM admin_actions WHERE status = 'open';")
        if not tickets: return await message.answer("✅ Сейчас нет активных тикетов.")
        text = "🎫 <b>Активные тикеты в работе:</b>\n\n"
        for t in tickets: text += f"Пользователь: <code>{t['target_user_id']}</code>\n└ Взял: @{t['admin_username']} (ID: {t['admin_id']})\n\n"
        await message.answer(text, parse_mode=ParseMode.HTML)
        
    elif data == "get_rests":
        async with db_pool.acquire() as conn:
            rests = await conn.fetch("SELECT user_id, username, role, rest_until FROM admins WHERE rest_until > NOW();")
        if not rests: return await message.answer("🏖 Сейчас никто не в отпуске.")
        text = "🌴 <b>Список сотрудников в отпуске (Рест):</b>\n\n"
        for r in rests:
            date_str = r['rest_until'].strftime('%d.%m.%Y %H:%M')
            text += f"▪️ @{r['username']} ({r['role']}) — до <b>{date_str}</b>\n"
        await message.answer(text, parse_mode=ParseMode.HTML)
        
    elif data.startswith("role|"):
        parts = data.split("|")
        action, target_id = parts[1], int(parts[2])
        async with db_pool.acquire() as conn:
            if action == "demote":
                await conn.execute("DELETE FROM admins WHERE user_id = $1;", target_id)
                await message.answer(f"✅ Пользователь <code>{target_id}</code> снят.", parse_mode=ParseMode.HTML)
            else:
                await conn.execute("INSERT INTO admins (user_id, role) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET role = $2;", target_id, action)
                await message.answer(f"✅ Роль <b>{action}</b> назначена <code>{target_id}</code>.", parse_mode=ParseMode.HTML)

    elif data.startswith("warn|"):
        parts = data.split("|")
        if len(parts) < 3: return
        action, target_id_str = parts[1], parts[2]
        if not target_id_str.isdigit(): return await message.answer("❌ Ошибка: ID должен состоять только из цифр.")
        target_id = int(target_id_str)
        
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT warns FROM admins WHERE user_id = $1;", target_id)
            if not row: return await message.answer(f"❌ Пользователь не админ.")
            
            # ВЫДАТЬ ВЫГОВОР
            if action == "add":
                new_warns = row['warns'] + 1
                if new_warns >= 5:
                    await conn.execute("DELETE FROM admins WHERE user_id = $1;", target_id)
                    await message.answer(f"⚠️ Админ <code>{target_id}</code> снят (5/5 выговоров).", parse_mode=ParseMode.HTML)
                else:
                    await conn.execute("UPDATE admins SET warns = $1 WHERE user_id = $2;", new_warns, target_id)
                    await message.answer(f"⚠️ Выговор выдан. Статус: <b>{new_warns}/5</b>", parse_mode=ParseMode.HTML)
                    appeal_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⚖️ Подать обжалование", callback_data="start_appeal")]])
                    try: await bot.send_message(target_id, f"⚠️ <b>Внимание!</b>\nВам выдан выговор. Выговоров: <b>{new_warns}/5</b>", reply_markup=appeal_kb, parse_mode=ParseMode.HTML)
                    except Exception: pass
            
            # СНЯТЬ ВЫГОВОР
            elif action == "remove":
                if row['warns'] <= 0: return await message.answer(f"У администратора <code>{target_id}</code> и так 0 выговоров.", parse_mode=ParseMode.HTML)
                new_warns = row['warns'] - 1
                await conn.execute("UPDATE admins SET warns = $1 WHERE user_id = $2;", new_warns, target_id)
                await message.answer(f"✅ Выговор снят. Текущий статус: <b>{new_warns}/5</b>", parse_mode=ParseMode.HTML)
                try: await bot.send_message(target_id, f"✅ <b>Хорошие новости!</b>\nВладелец снял с вас один выговор.\nТекущее количество: <b>{new_warns}/5</b>", parse_mode=ParseMode.HTML)
                except Exception: pass

# --- СИСТЕМА ОБЖАЛОВАНИЯ ВЫГОВОРОВ ---
@dp.callback_query(F.data == "start_appeal")
async def start_appeal(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("⚖️ Напишите текст обжалования одним сообщением (объясните ситуацию, прикрепите доказательства):")
    await state.set_state(AdminStates.waiting_appeal_text)
    await callback.answer()

@dp.message(AdminStates.waiting_appeal_text)
async def process_appeal(message: types.Message, state: FSMContext):
    admin_id = message.from_user.id
    username = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Снять выговор (Одобрить)", callback_data=f"appeal_ok_{admin_id}")],
        [InlineKeyboardButton(text="❌ Отклонить обжалование", callback_data=f"appeal_no_{admin_id}")]
    ])
    await bot.send_message(OWNER_ID, f"🚨 <b>НОВОЕ ОБЖАЛОВАНИЕ ВЫГОВОРА!</b>\nОт: {username} (ID: {admin_id})\n\n<b>Текст/Доказательства:</b>\n{message.text}", reply_markup=kb, parse_mode=ParseMode.HTML)
    await message.answer("✅ Ваше обжалование отправлено Владельцу на рассмотрение.")
    await state.clear()

@dp.callback_query(F.data.startswith("appeal_"))
async def process_appeal_verdict(callback: CallbackQuery):
    action, admin_id = callback.data.split("_")[1], int(callback.data.split("_")[2])
    if action == "ok":
        async with db_pool.acquire() as conn: await conn.execute("UPDATE admins SET warns = GREATEST(warns - 1, 0) WHERE user_id = $1;", admin_id)
        await callback.message.edit_text(callback.message.html_text + "\n\n✅ <b>ВЕРДИКТ: Одобрено (выговор снят)</b>", parse_mode=ParseMode.HTML)
        try: await bot.send_message(admin_id, "✅ <b>Ваше обжалование одобрено!</b> Выговор был снят.", parse_mode=ParseMode.HTML)
        except Exception: pass
    else:
        await callback.message.edit_text(callback.message.html_text + "\n\n❌ <b>ВЕРДИКТ: Отклонено</b>", parse_mode=ParseMode.HTML)
        try: await bot.send_message(admin_id, "❌ <b>Ваше обжалование отклонено.</b> Выговор остается в силе.", parse_mode=ParseMode.HTML)
        except Exception: pass

# --- СИСТЕМА ОТПУСКОВ (РЕСТОВ) ---
@dp.message(Command("rest"))
async def cmd_rest(message: types.Message, state: FSMContext):
    if not await get_admin_role(message.from_user.id): return
    await message.answer("🏖 <b>Запрос на рест (отпуск)</b>\nНа сколько дней вы хотите взять рест? (Напишите цифру)", parse_mode=ParseMode.HTML)
    await state.set_state(AdminStates.waiting_rest_days)

@dp.message(AdminStates.waiting_rest_days)
async def process_rest_days(message: types.Message, state: FSMContext):
    if not message.text.isdigit(): return await message.answer("⚠️ Пожалуйста, введите только цифру (количество дней).")
    await state.update_data(rest_days=int(message.text))
    await message.answer("Напишите причину реста (почему вы берете отпуск):")
    await state.set_state(AdminStates.waiting_rest_reason)

@dp.message(AdminStates.waiting_rest_reason)
async def process_rest_reason(message: types.Message, state: FSMContext):
    data = await state.get_data()
    days = data['rest_days']
    reason = message.text
    admin_id = message.from_user.id
    username = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Одобрить рест", callback_data=f"rest_ok_{admin_id}_{days}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"rest_no_{admin_id}")]
    ])
    await bot.send_message(OWNER_ID, f"🏖 <b>ЗАПРОС НА РЕСТ</b>\nОт: {username} (ID: {admin_id})\nСрок: <b>{days} дней</b>\nПричина: {reason}", reply_markup=kb, parse_mode=ParseMode.HTML)
    await message.answer("⏳ Запрос на рест отправлен Владельцу.")
    await state.clear()

@dp.callback_query(F.data.startswith("rest_"))
async def process_rest_verdict(callback: CallbackQuery):
    parts = callback.data.split("_")
    action, admin_id = parts[1], int(parts[2])
    
    if action == "ok":
        days = int(parts[3])
        async with db_pool.acquire() as conn:
            await conn.execute("UPDATE admins SET rest_until = NOW() + $1::interval WHERE user_id = $2;", f"{days} days", admin_id)
            users = await conn.fetch("SELECT target_user_id FROM admin_actions WHERE admin_id = $1 AND status = 'open';", admin_id)
        await callback.message.edit_text(callback.message.html_text + "\n\n✅ <b>ВЕРДИКТ: Одобрено</b>", parse_mode=ParseMode.HTML)
        try: await bot.send_message(admin_id, f"✅ <b>Ваш рест на {days} дней одобрен!</b> Отдыхайте.", parse_mode=ParseMode.HTML)
        except Exception: pass
        for u in users:
            try: await bot.send_message(u['target_user_id'], f"⚠️ <b>Внимание!</b>\nАдминистратор, который рассматривает ваше обращение, ушел в отпуск (рест) на {days} дней. Вы можете подождать его, либо закрыть этот тикет и открыть новый.", parse_mode=ParseMode.HTML)
            except Exception: pass
    else:
        await callback.message.edit_text(callback.message.html_text + "\n\n❌ <b>ВЕРДИКТ: Отклонено</b>", parse_mode=ParseMode.HTML)
        try: await bot.send_message(admin_id, "❌ <b>Ваш запрос на рест отклонен.</b>", parse_mode=ParseMode.HTML)
        except Exception: pass


# --- TELEGRAM BUSINESS ---
@dp.business_message(Command("search"))
@dp.business_message(F.text.lower() == "/search")
async def biz_search_command(message: types.Message):
    if message.from_user.id != OWNER_ID: return
    target_id = message.chat.id
    async with db_pool.acquire() as conn:
        user_data = await conn.fetchrow("SELECT user_id, first_name, username, topic_id, is_blocked, is_banned FROM users WHERE user_id = $1;", target_id)
    if not user_data: return await bot.send_message(OWNER_ID, f"❌ Бизнес-поиск: Пользователь с ID <code>{target_id}</code> не найден в базе.", parse_mode=ParseMode.HTML)
    has_ticket = "Да (топик открыт)" if user_data["topic_id"] else "Нет активных тикетов"
    is_blocked = "🚫 Да" if user_data["is_blocked"] else "🍏 Нет"
    is_banned = "🔴 ЗАБАНЕН" if user_data["is_banned"] else "🟢 Чист"
    username_text = f"@{user_data['username']}" if user_data['username'] else "Скрыт"
    info_text = (
        f"💼 <b>Бизнес-проверка:</b>\n├ Имя: {user_data['first_name']}\n├ Юзернейм: {username_text}\n├ ID: <code>{user_data['user_id']}</code>\n"
        f"├ Бот заблокирован: {is_blocked}\n├ Статус в боте: {is_banned}\n└ Тикет: {has_ticket}"
    )
    await bot.send_message(OWNER_ID, info_text, parse_mode=ParseMode.HTML)

@dp.business_message(F.chat.type == "private")
async def auto_biz_profile(message: types.Message):
    if message.from_user.id == OWNER_ID: return
    target_id = message.from_user.id
    if target_id in profiled_biz_users: return
    profiled_biz_users.add(target_id)
    async with db_pool.acquire() as conn:
        user_data = await conn.fetchrow("SELECT user_id, first_name, username, topic_id, is_blocked, is_banned FROM users WHERE user_id = $1;", target_id)
    if not user_data: return
    has_ticket = "Да (топик открыт)" if user_data["topic_id"] else "Нет активных тикетов"
    is_blocked = "🚫 Да" if user_data["is_blocked"] else "🍏 Нет"
    is_banned = "🔴 ЗАБАНЕН" if user_data["is_banned"] else "🟢 Чист"
    username_text = f"@{user_data['username']}" if user_data['username'] else "Скрыт"
    info_text = (
        f"🔔 <b>Вам в ЛС написал пользователь бота!</b>\n├ Имя: {user_data['first_name']}\n├ Юзернейм: {username_text}\n├ ID: <code>{user_data['user_id']}</code>\n"
        f"├ Бот заблокирован: {is_blocked}\n├ Статус: {is_banned}\n└ Тикет: {has_ticket}\n\n<i>(Это автоматическая проверка новых диалогов)</i>"
    )
    try: await bot.send_message(OWNER_ID, info_text, parse_mode=ParseMode.HTML)
    except Exception: pass


# --- РАДАР И ФОНОВЫЕ ЗАДАЧИ ---
@dp.message(F.new_chat_members, F.chat.id == ADMIN_CHAT_ID)
async def admin_group_new_member(message: types.Message):
    for new_member in message.new_chat_members:
        if new_member.is_bot: continue
        async with db_pool.acquire() as conn:
            user_data = await conn.fetchrow("SELECT topic_id, join_date FROM users WHERE user_id = $1;", new_member.id)
        mention = f"@{new_member.username}" if new_member.username else new_member.first_name
        if user_data:
            days_in_db = (datetime.now() - user_data['join_date']).days
            topic_text = f"<code>{user_data['topic_id']}</code>" if user_data['topic_id'] else "Нет"
            text = f"👋 <b>Новый участник в админ-чате!</b>\n\n👤 Юзер: {mention}\n🆔 ID: <code>{new_member.id}</code>\n🎫 Открытый топик: {topic_text}\n📅 В базе данных: <b>{days_in_db} дней</b>"
        else:
            text = f"👋 <b>Новый участник в админ-чате!</b>\n\n👤 Юзер: {mention}\n🆔 ID: <code>{new_member.id}</code>\n⚠️ В базе данных: <b>Не найден</b>"
        await message.answer(text, parse_mode=ParseMode.HTML)

async def care_scheduler():
    while True:
        now = datetime.now(TZ)
        if now.hour == 21 and now.minute == 0:
            async with db_pool.acquire() as conn:
                users = await conn.fetch("SELECT user_id FROM users WHERE care_sub = TRUE AND is_blocked = FALSE AND is_banned = FALSE;")
            text = "🌙 Вечернее Сияние напоминает: этот день позади. Выпей чаю, включи любимую музыку и отдохни. Ты молодец! ❤️"
            for u in users:
                try:
                    await bot.send_message(u['user_id'], text)
                    await asyncio.sleep(0.1)
                except Exception: pass
            await asyncio.sleep(60)
        await asyncio.sleep(30)


# --- ПОЛЬЗОВАТЕЛЬСКАЯ ЧАСТЬ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    if message.chat.type != "private": return
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (user_id, username, first_name, is_blocked) VALUES ($1, $2, $3, FALSE)
            ON CONFLICT (user_id) DO UPDATE SET username = $2, first_name = $3, is_blocked = FALSE;
        """, message.from_user.id, message.from_user.username, message.from_user.first_name)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Задать вопрос", callback_data="cat_question"), InlineKeyboardButton(text="ℹ️ FAQ", callback_data="cat_faq")],
        [InlineKeyboardButton(text="🎭 Анонимная предложка", callback_data="anon_suggest")],
        [InlineKeyboardButton(text="📜 Правила", callback_data="cat_rules")]
    ])
    await message.answer(
        "Приветствую, путник! Ты попал в прекрасный бот <b>«Вечернее сияние»</b> ✨\n\nВыбери нужный раздел ниже, или просто напиши сообщение.",
        reply_markup=kb, parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data.startswith("cat_"))
async def process_category(callback: CallbackQuery):
    if callback.data == "cat_faq": await callback.message.answer(FAQ_TEXT, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    elif callback.data == "cat_rules": await callback.message.answer(RULES_TEXT, parse_mode=ParseMode.HTML)
    elif callback.data == "cat_question": await callback.message.answer("📝 Напиши свой вопрос следующим сообщением, и мы передадим его админам!")
    await callback.answer()

@dp.message(Command("profile"))
async def cmd_profile(message: types.Message):
    async with db_pool.acquire() as conn:
        u = await conn.fetchrow("SELECT warmth, msg_count, join_date FROM users WHERE user_id = $1;", message.from_user.id)
    if not u: return
    days = (datetime.now() - u['join_date']).days
    await message.answer(
        f"🪪 <b>Твоя карточка сияния:</b>\n\n👤 Имя: {message.from_user.first_name}\n☀️ Уровень тепла: <b>{u['warmth']}</b>\n💬 Оставлено сообщений: {u['msg_count']}\n📅 С нами дней: {days}", 
        parse_mode=ParseMode.HTML
    )

@dp.message(Command("status"))
async def cmd_status(message: types.Message):
    async with db_pool.acquire() as conn:
        u = await conn.fetchrow("SELECT topic_id FROM users WHERE user_id = $1;", message.from_user.id)
        if not u or not u['topic_id']: return await message.answer("У тебя нет открытых обращений. Можешь написать нам!")
        open_tickets = await conn.fetchval("SELECT COUNT(*) FROM admin_actions WHERE status = 'open';")
    await message.answer(f"Твой тикет в работе! 🎫\nВсего открытых обращений у админов сейчас: {open_tickets}")

@dp.message(Command("care"))
async def cmd_care(message: types.Message):
    async with db_pool.acquire() as conn:
        u = await conn.fetchrow("SELECT care_sub FROM users WHERE user_id = $1;", message.from_user.id)
        if not u: return
        new_val = not u['care_sub']
        await conn.execute("UPDATE users SET care_sub = $1 WHERE user_id = $2;", new_val, message.from_user.id)
    status = "✅ Подписка оформлена!" if new_val else "❌ Подписка отменена."
    await message.answer(f"{status} Ежедневные письма заботы в 21:00.")

@dp.message(Command("hug"))
async def cmd_hug(message: types.Message): await message.answer(random.choice(HUGS))
@dp.message(Command("coffee"))
async def cmd_coffee(message: types.Message): await message.answer("Вот твой горячий какао с маршмеллоу ☕️, админ уже спешит к тебе!")
@dp.message(Command("quote"))
async def cmd_quote(message: types.Message): await message.answer(f"<i>«{random.choice(QUOTES)}»</i>", parse_mode=ParseMode.HTML)


# --- АНОНИМКА ---
@dp.callback_query(F.data == "anon_suggest")
async def start_anon(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("🤫 Напиши свою идею или историю. Она будет отправлена админам абсолютно анонимно!")
    await state.set_state(BotStates.waiting_for_anon)
    await callback.answer()

@dp.message(BotStates.waiting_for_anon)
async def process_anon(message: types.Message, state: FSMContext):
    sent_msg = await message.send_copy(chat_id=ADMIN_CHAT_ID, message_thread_id=UNASSIGNED_TOPIC_ID)
    await bot.send_message(ADMIN_CHAT_ID, "👆 <b>АНОНИМНАЯ ПРЕДЛОЖКА</b>", reply_to_message_id=sent_msg.message_id, message_thread_id=UNASSIGNED_TOPIC_ID, parse_mode=ParseMode.HTML)
    await message.answer("✅ Отправлено анонимно! Спасибо за твою идею.")
    await state.clear()


# --- АДМИН КОМАНДЫ, ДОСЬЕ, ИНФО ---
@dp.message(Command("help"))
@dp.message(F.text.lower().in_({".help", "/хелп", ".хелп"}))
async def cmd_help(message: types.Message):
    try: await message.delete()
    except Exception: pass
    role = await get_admin_role(message.from_user.id)
    if not role: return await message.answer("❌ У вас нет доступа.")
    help_text = (
        "📌 <b>Список доступных команд:</b>\n\n"
        "👑 <b>Управление:</b>\n├ /stats — Статистика бота\n├ /adminstats — Статистика тикетов\n├ /adminlist — Список состава\n├ /check — Проверить пользователя\n├ /use — Memory-based досье с карточкой\n├ /id — ID пользователя\n├ /photoid — ID фото\n├ /panel — Панель управления Владельца (Mini App)\n└ /broadcast — Сделать рассылку\n\n"
        "🛡 <b>Роли и Дисциплина:</b>\n├ /setdirector, /setadmin, /setintern, /demote [ID]\n├ /setcurator [ID_админа] [ID_куратора]\n├ /rest - Запрос отпуска\n\n"
        "🎫 <b>Тикеты:</b>\n├ /close — Закрыть тикет\n└ /ban — Заблокировать юзера (внутри топика)"
    )
    await message.answer(help_text, parse_mode=ParseMode.HTML)

@dp.message(Command("photoid"), F.from_user.id == OWNER_ID)
async def cmd_toggle_photoid(message: types.Message):
    try: await message.delete()
    except Exception: pass
    global photo_id_mode
    photo_id_mode = not photo_id_mode
    state_text = "ВКЛЮЧЕН 🟢" if photo_id_mode else "ВЫКЛЮЧЕН 🔴"
    await message.answer(f"📸 Режим получения ID фото: <b>{state_text}</b>", parse_mode=ParseMode.HTML)

@dp.message(F.photo, F.from_user.id == OWNER_ID)
async def get_photo_id(message: types.Message):
    if not photo_id_mode: return
    photo_id = message.photo[-1].file_id
    await message.answer(f"📸 <b>ID вашей картинки:</b>\n\n<code>{photo_id}</code>", parse_mode=ParseMode.HTML)

@dp.message(Command("id"))
@dp.message(F.text.lower().in_({".ид", "/id"}))
async def cmd_id(message: types.Message):
    try: await message.delete()
    except Exception: pass
    target = message.reply_to_message.from_user if message.reply_to_message else message.from_user
    await message.answer(f"🆔 <b>Информация:</b>\n├ Имя: {target.first_name}\n├ Юзернейм: @{target.username}\n└ ID: <code>{target.id}</code>", parse_mode=ParseMode.HTML)

@dp.message(Command("check"))
@dp.message(F.text.lower().in_({".чек", "/check"}))
async def cmd_check(message: types.Message):
    try: await message.delete()
    except Exception: pass
    if not await get_admin_role(message.from_user.id): return await message.answer("❌ У вас нет прав.")
    args = message.text.split()
    target_id, target_username = None, None
    if message.reply_to_message: target_id = message.reply_to_message.from_user.id
    elif len(args) > 1:
        arg = args[1]
        if arg.isdigit(): target_id = int(arg)
        elif arg.startswith("@"): target_username = arg[1:]
        else: target_username = arg
    else:
        return await message.answer("⚠️ Используйте: <code>.чек 123456</code> или <code>.чек @user</code>", parse_mode=ParseMode.HTML)

    async with db_pool.acquire() as conn:
        if target_id: user_data = await conn.fetchrow("SELECT user_id, first_name, username, topic_id, is_blocked, is_banned FROM users WHERE user_id = $1;", target_id)
        elif target_username: user_data = await conn.fetchrow("SELECT user_id, first_name, username, topic_id, is_blocked, is_banned FROM users WHERE username ILIKE $1;", target_username)
    if not user_data: return await message.answer(f"❌ Пользователь не найден в базе.", parse_mode=ParseMode.HTML)
    has_ticket = "Да" if user_data["topic_id"] else "Нет"
    is_blocked = "🚫 Да" if user_data["is_blocked"] else "🍏 Нет"
    is_banned = "🔴 Да" if user_data["is_banned"] else "🟢 Нет"
    username_text = f"@{user_data['username']}" if user_data['username'] else "Скрыт"
    await message.answer(
        f"🔍 <b>Проверка пользователя:</b>\n├ Имя: {user_data['first_name']}\n├ Юзернейм: {username_text}\n├ ID: <code>{user_data['user_id']}</code>\n"
        f"├ Заблокировал бота: {is_blocked}\n├ Бан от админов: {is_banned}\n└ Тикет: {has_ticket}", parse_mode=ParseMode.HTML
    )

@dp.message(Command("check_use"))
@dp.message(Command("use"))
async def cmd_check_use(message: types.Message):
    try: await message.delete()
    except Exception: pass
    if not await get_admin_role(message.from_user.id): return
    args = message.text.split()
    if len(args) < 2 and not message.reply_to_message: return await message.answer("⚠️ Используй: <code>/use ID</code> или <code>/use @username</code> (или ответом)", parse_mode=ParseMode.HTML)
    target_id, target_username = None, None
    if message.reply_to_message: target_id = message.reply_to_message.from_user.id
    else:
        arg = args[1]
        if arg.isdigit(): target_id = int(arg)
        else: target_username = arg.replace("@", "")

    async with db_pool.acquire() as conn:
        if target_id: u = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1;", target_id)
        else: u = await conn.fetchrow("SELECT * FROM users WHERE username ILIKE $1;", target_username)
    if not u: return await message.answer("❌ Человек не найден в базе данных.")
    admin_role = await get_admin_role(u['user_id'])
    role_text = admin_role.capitalize() if admin_role else "Пользователь"
    ban_text = "🔴 ЗАБЛОКИРОВАН" if u['is_banned'] else "🟢 Чист"
    await message.answer(f"🗃 <b>MEMORY-BASED SYSTEM</b>\n\n👤 <b>Имя:</b> {u['first_name']}\n🆔 <b>ID:</b> <code>{u['user_id']}</code>\n⚠️ <b>Статус:</b> {ban_text}\n💬 <b>Сообщений:</b> {u['msg_count']}\n🎭 <b>Роль:</b> {role_text}", parse_mode=ParseMode.HTML)

@dp.message(Command(commands=["setdirector", "setadmin", "setintern", "demote"]))
async def set_role_command(message: types.Message):
    if await get_admin_role(message.from_user.id) not in ['owner', 'director']: return await message.answer("❌ Недостаточно прав.")
    args = message.text.split()
    if len(args) < 2: return await message.answer("⚠️ Использование: /command <user_id>")
    target_id = int(args[1])
    command = args[0][1:].split('@')[0]
    async with db_pool.acquire() as conn:
        if command == "demote":
            await conn.execute("DELETE FROM admins WHERE user_id = $1;", target_id)
            return await message.answer(f"✅ Пользователь <code>{target_id}</code> уволен.", parse_mode=ParseMode.HTML)
        role_map = {"setdirector": "director", "setadmin": "admin", "setintern": "intern"}
        new_role = role_map.get(command)
        await conn.execute("INSERT INTO admins (user_id, role) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET role = $2;", target_id, new_role)
    await message.answer(f"✅ Роль <b>{new_role}</b> назначена <code>{target_id}</code>.", parse_mode=ParseMode.HTML)

@dp.message(Command("setcurator"))
async def cmd_set_curator(message: types.Message):
    if await get_admin_role(message.from_user.id) not in ['owner', 'director']: return
    args = message.text.split()
    if len(args) < 3: return
    async with db_pool.acquire() as conn: await conn.execute("UPDATE admins SET curator_id = $1 WHERE user_id = $2;", int(args[2]), int(args[1]))
    await message.answer(f"✅ Куратор назначен.")

@dp.message(Command("ban"), F.chat.id == ADMIN_CHAT_ID)
async def cmd_ban(message: types.Message):
    try: await message.delete()
    except Exception: pass
    topic_id = message.message_thread_id
    if not topic_id or topic_id == UNASSIGNED_TOPIC_ID: return
    admin_id = message.from_user.id
    admin_role = await get_admin_role(admin_id)
    if not admin_role: return
    async with db_pool.acquire() as conn:
        user_row = await conn.fetchrow("SELECT user_id FROM users WHERE topic_id = $1;", topic_id)
        if not user_row: return
        target_user_id = user_row["user_id"]
        if admin_role == 'intern':
            admin_data = await conn.fetchrow("SELECT curator_id FROM admins WHERE user_id = $1;", admin_id)
            curator_id = admin_data['curator_id'] if admin_data else None
            if not curator_id: return await message.answer("⚠️ За вами не закреплен куратор! Вы не можете запрашивать блокировку.")
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Одобрить бан", callback_data=f"approve_ban_{target_user_id}_{topic_id}")],
                [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_ban_{target_user_id}_{topic_id}")]
            ])
            try:
                chat_id_str = str(ADMIN_CHAT_ID).replace("-100", "")
                topic_link = f"https://t.me/c/{chat_id_str}/{topic_id}"
                await bot.send_message(curator_id, f"🚨 <b>Запрос на блокировку от стажёра!</b>\nСтажёр @{message.from_user.username} хочет забанить <code>{target_user_id}</code>.\n🔗 <a href='{topic_link}'>Топик</a>", reply_markup=kb, parse_mode=ParseMode.HTML)
                await message.answer("⏳ Запрос отправлен куратору.")
            except Exception: pass
            return
        await conn.execute("UPDATE users SET is_banned = TRUE, topic_id = NULL WHERE user_id = $1;", target_user_id)
        await conn.execute("UPDATE admin_actions SET status = 'closed', closed_time = NOW() WHERE target_user_id = $1 AND status = 'open';", target_user_id)
    await message.answer("🔨 <b>Пользователь заблокирован!</b> Топик можно закрывать.", parse_mode=ParseMode.HTML)
    try: await bot.send_message(target_user_id, "🚫 <b>Вы были заблокированы администрацией бота.</b>", parse_mode=ParseMode.HTML)
    except Exception: pass
    try: await bot.close_forum_topic(chat_id=ADMIN_CHAT_ID, message_thread_id=topic_id)
    except Exception: pass

@dp.callback_query(F.data.startswith("approve_ban_") | F.data.startswith("reject_ban_"))
async def process_ban_approval(callback: CallbackQuery):
    action, _, target_user_id, topic_id = callback.data.split("_")
    target_user_id, topic_id = int(target_user_id), int(topic_id)
    if action == "approve":
        async with db_pool.acquire() as conn:
            await conn.execute("UPDATE users SET is_banned = TRUE, topic_id = NULL WHERE user_id = $1;", target_user_id)
            await conn.execute("UPDATE admin_actions SET status = 'closed', closed_time = NOW() WHERE target_user_id = $1 AND status = 'open';", target_user_id)
        await callback.message.edit_text("✅ <b>Бан одобрен.</b>", parse_mode=ParseMode.HTML)
        try: await bot.close_forum_topic(chat_id=ADMIN_CHAT_ID, message_thread_id=topic_id)
        except Exception: pass
    else:
        await callback.message.edit_text("❌ <b>Бан отклонен.</b>", parse_mode=ParseMode.HTML)


# --- СТАТИСТИКА И РАССЫЛКИ ---
@dp.message(Command("adminlist"))
async def cmd_adminlist(message: types.Message):
    try: await message.delete()
    except Exception: pass
    if not await get_admin_role(message.from_user.id): return
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id, role, tag, warns FROM admins ORDER BY role;")
    text = "📋 <b>Состав:</b>\n\n"
    for r in rows: text += f"▪️ ID {r['user_id']} — <b>{r['role']}</b> | ⚠️ {r['warns']}/5\n"
    await message.answer(text, parse_mode=ParseMode.HTML)

@dp.message(Command("adminstats"))
async def cmd_admin_stats(message: types.Message):
    try: await message.delete()
    except Exception: pass
    if await get_admin_role(message.from_user.id) not in ['owner', 'director']: return
    async with db_pool.acquire() as conn:
        query = """
            SELECT a.admin_id, MAX(a.admin_username) as admin_username,
                   COUNT(*) AS total_taken,
                   COUNT(*) FILTER (WHERE a.action_time >= CURRENT_DATE) AS taken_today,
                   COUNT(*) FILTER (WHERE a.action_time >= date_trunc('week', CURRENT_DATE)) AS taken_week,
                   COUNT(*) FILTER (WHERE a.status = 'closed') AS total_closed,
                   MAX(ad.rating_sum) as r_sum, MAX(ad.rating_count) as r_count
            FROM admin_actions a JOIN admins ad ON a.admin_id = ad.user_id
            GROUP BY a.admin_id ORDER BY total_taken DESC;
        """
        rows = await conn.fetch(query)
    if not rows: return await message.answer("📈 Статистика пуста.")
    text = "📈 <b>Статистика сотрудников:</b>\n\n"
    for r in rows:
        r_sum = r['r_sum'] or 0
        r_count = r['r_count'] or 0
        rating = f"{(r_sum / r_count):.1f}⭐️" if r_count > 0 else "Нет"
        username_text = f"@{r['admin_username']}" if r['admin_username'] else f"ID: {r['admin_id']}"
        text += (f"👤 <b>{username_text}</b>\n ├ Взято: <b>{r['total_taken']}</b> (Сегодня: {r['taken_today']} | Неделя: {r['taken_week']})\n"
                 f" ├ Закрыто: {r['total_closed']}\n └ Рейтинг: {rating}\n\n")
    await message.answer(text, parse_mode=ParseMode.HTML)

@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    try: await message.delete()
    except Exception: pass
    if not await get_admin_role(message.from_user.id): return
    async with db_pool.acquire() as conn:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users;") or 0
        banned_users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_blocked = TRUE;") or 0
        active_users = total_users - banned_users
        owner_count = await conn.fetchval("SELECT COUNT(*) FROM admins WHERE role = 'owner';") or 0
        directors_count = await conn.fetchval("SELECT COUNT(*) FROM admins WHERE role = 'director';") or 0
        admins_count = await conn.fetchval("SELECT COUNT(*) FROM admins WHERE role = 'admin';") or 0
        interns_count = await conn.fetchval("SELECT COUNT(*) FROM admins WHERE role = 'intern';") or 0
        user_msgs = await conn.fetchval("SELECT SUM(msg_count) FROM users;") or 0
    stats_text = (
        "📊 <b>Полная статистика:</b>\n\n👥 <b>Пользователи:</b>\n├ Всего пользователей: <b>{total_users}</b>\n"
        f"├ 🍏 Активных: <b>{active_users}</b>\n└ 🚫 В блоке: <b>{banned_users}</b>\n\n🎭 <b>Команда:</b>\n"
        f"├ 👑 Владелец: {owner_count} | 💼 Директоров: {directors_count}\n└ 🛡 Админов: {admins_count} | 🔰 Стажёров: {interns_count}\n\n"
        f"✉️ <b>Всего сообщений в бот:</b> {user_msgs}"
    )
    await message.answer(stats_text, parse_mode=ParseMode.HTML)

@dp.message(Command("broadcast"))
async def cmd_broadcast(message: types.Message, state: FSMContext):
    if await get_admin_role(message.from_user.id) not in ['owner', 'director']: return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Всем пользователям", callback_data="bc_all")],
        [InlineKeyboardButton(text="🔥 Топ 50 (самые активные)", callback_data="bc_active")],
        [InlineKeyboardButton(text="🔢 Каждому N-ому", callback_data="bc_nth")]
    ])
    await message.answer("📢 <b>Настройка рассылки</b>\nВыберите аудиторию:", reply_markup=kb, parse_mode=ParseMode.HTML)
    await state.set_state(BotStates.waiting_for_broadcast_audience)

@dp.callback_query(F.data.startswith("bc_"), BotStates.waiting_for_broadcast_audience)
async def process_bc_audience(callback: CallbackQuery, state: FSMContext):
    audience = callback.data.split("_")[1]
    await state.update_data(audience=audience)
    if audience == "nth":
        await callback.message.edit_text("🔢 Введите число N (например, 5):")
        await state.set_state(BotStates.waiting_for_broadcast_n)
    else:
        await callback.message.edit_text("📢 Отправьте пост для рассылки (любой текст, медиа, Premium-эмодзи):")
        await state.set_state(BotStates.waiting_for_broadcast)

@dp.message(BotStates.waiting_for_broadcast_n)
async def process_bc_n(message: types.Message, state: FSMContext):
    if not message.text.isdigit() or int(message.text) < 2: return await message.answer("⚠️ Пожалуйста, введите число (больше 1).")
    await state.update_data(nth=int(message.text))
    await message.answer("📢 Отправьте пост для рассылки:")
    await state.set_state(BotStates.waiting_for_broadcast)

@dp.message(BotStates.waiting_for_broadcast)
async def process_broadcast_preview(message: types.Message, state: FSMContext):
    await state.update_data(bc_msg_id=message.message_id, bc_chat_id=message.chat.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 /send (Начать)", callback_data="bc_confirm_send")],
        [InlineKeyboardButton(text="❌ /cancel (Отменить)", callback_data="bc_confirm_cancel")]
    ])
    await message.send_copy(chat_id=message.chat.id)
    await message.answer("👆 <b>Так будет выглядеть пост.</b> Запускаем?", reply_markup=kb, parse_mode=ParseMode.HTML)

@dp.callback_query(F.data.in_(["bc_confirm_send", "bc_confirm_cancel"]))
async def execute_broadcast(callback: CallbackQuery, state: FSMContext):
    if callback.data == "bc_confirm_cancel":
        await callback.message.edit_text("🚫 Рассылка отменена.")
        return await state.clear()
    data = await state.get_data()
    bc_msg_id, bc_chat_id = data.get("bc_msg_id"), data.get("bc_chat_id")
    audience, nth = data.get("audience"), data.get("nth", 1)
    await callback.message.edit_text("⏳ <b>Рассылка запущена...</b>", parse_mode=ParseMode.HTML)
    
    async with db_pool.acquire() as conn:
        if audience in ["all", "nth"]: users = await conn.fetch("SELECT user_id FROM users WHERE is_blocked = FALSE AND is_banned = FALSE;")
        elif audience == "active": users = await conn.fetch("SELECT user_id FROM users WHERE is_blocked = FALSE AND is_banned = FALSE ORDER BY msg_count DESC LIMIT 50;")
            
    if audience == "nth": users = users[::nth]
    success, blocked = 0, 0
    for u in users:
        try:
            await bot.copy_message(chat_id=u["user_id"], from_chat_id=bc_chat_id, message_id=bc_msg_id)
            success += 1
            await asyncio.sleep(0.05)
        except Exception:
            blocked += 1
            async with db_pool.acquire() as conn: await conn.execute("UPDATE users SET is_blocked = TRUE WHERE user_id = $1;", u["user_id"])
    await callback.message.answer(f"✅ <b>Рассылка завершена!</b>\nУспешно: {success}\nЗаблокировали бота: {blocked}", parse_mode=ParseMode.HTML)
    await state.clear()


# --- ОБРАБОТКА ТИКЕТОВ В ЛС ---
@dp.message(F.chat.type == "private")
async def private_msg(message: types.Message, state: FSMContext):
    if await state.get_state(): return
    if message.text and message.text.startswith("/"): return
    user_id = message.from_user.id
    try:
        topic_id = None
        async with db_pool.acquire() as conn:
            user_row_banned = await conn.fetchrow("SELECT is_banned FROM users WHERE user_id = $1;", user_id)
            if user_row_banned and user_row_banned.get("is_banned"): return
            await conn.execute("UPDATE users SET msg_count = msg_count + 1, is_blocked = FALSE WHERE user_id = $1;", user_id)
            async with conn.transaction():
                user_row = await conn.fetchrow("SELECT topic_id FROM users WHERE user_id = $1 FOR UPDATE;", user_id)
                if user_row and user_row["topic_id"]: topic_id = user_row["topic_id"]

        if not topic_id:
            forum_topic = await bot.create_forum_topic(chat_id=ADMIN_CHAT_ID, name=f"{message.from_user.first_name} | {user_id}")
            topic_id = forum_topic.message_thread_id
            async with db_pool.acquire() as conn: await conn.execute("UPDATE users SET topic_id = $1 WHERE user_id = $2;", topic_id, user_id)
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🟢 Взять обращение", callback_data=f"take_pz_{user_id}")]])
            await bot.send_message(ADMIN_CHAT_ID, message_thread_id=UNASSIGNED_TOPIC_ID, text=f"⚠️ Новое обращение от [<code>{user_id}</code>]", reply_markup=kb, parse_mode=ParseMode.HTML)

        await message.send_copy(chat_id=ADMIN_CHAT_ID, message_thread_id=topic_id)
    except Exception as e: logger.error(f"Ошибка private_msg: {e}")

@dp.callback_query(F.data.startswith("take_pz_"))
async def take_pz(callback: types.CallbackQuery):
    try:
        target_id = int(callback.data.split("_")[2])
        admin_id = callback.from_user.id
        async with db_pool.acquire() as conn:
            user_row = await conn.fetchrow("SELECT topic_id FROM users WHERE user_id = $1;", target_id)
            if not user_row or not user_row["topic_id"]: return await callback.answer("❌ Топик не найден.", show_alert=True)
            await conn.execute("INSERT INTO admin_actions (admin_id, admin_username, target_user_id, status, action_time) VALUES ($1, $2, $3, 'open', NOW());", admin_id, callback.from_user.username, target_id)
            await conn.execute("UPDATE admins SET taken_tickets = taken_tickets + 1 WHERE user_id = $1;", admin_id)
        
        user_topic_id = user_row["topic_id"]
        await callback.message.edit_text(f"✅ <b>Обращение взято!</b>", parse_mode=ParseMode.HTML)
        await bot.send_message(chat_id=ADMIN_CHAT_ID, message_thread_id=user_topic_id, text=f"🟢 Закреплено за вами!\n<i>/close - закрыть, /ban - бан</i>", parse_mode=ParseMode.HTML)
        await callback.answer("Готово!")
    except Exception as e: pass

@dp.message(Command("close"), F.chat.id == ADMIN_CHAT_ID)
async def cmd_close_ticket(message: types.Message):
    topic_id = message.message_thread_id
    if not topic_id or topic_id == UNASSIGNED_TOPIC_ID: return
    async with db_pool.acquire() as conn:
        user_row = await conn.fetchrow("SELECT user_id FROM users WHERE topic_id = $1;", topic_id)
        if user_row:
            user_id = user_row["user_id"]
            admin_id = message.from_user.id
            await conn.execute("UPDATE users SET topic_id = NULL WHERE user_id = $1;", user_id)
            await conn.execute("UPDATE admin_actions SET status = 'closed', closed_time = NOW() WHERE target_user_id = $1 AND status = 'open';", user_id)
            await message.answer("✅ <b>Тикет закрыт!</b>", parse_mode=ParseMode.HTML)
            rate_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="1 ⭐️", callback_data=f"rate_{admin_id}_1"), InlineKeyboardButton(text="5 ⭐️", callback_data=f"rate_{admin_id}_5")]])
            try: await bot.send_message(user_id, "✅ <b>Обращение закрыто.</b>\nОцените работу:", reply_markup=rate_kb, parse_mode=ParseMode.HTML)
            except Exception: pass
            try: await bot.close_forum_topic(chat_id=ADMIN_CHAT_ID, message_thread_id=topic_id)
            except Exception: pass

@dp.callback_query(F.data.startswith("rate_"))
async def process_rating(callback: CallbackQuery):
    _, admin_id, score = callback.data.split("_")
    admin_id, score = int(admin_id), int(score)
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE admins SET rating_sum = rating_sum + $1, rating_count = rating_count + 1 WHERE user_id = $2;", score, admin_id)
        await conn.execute("UPDATE users SET warmth = warmth + 2 WHERE user_id = $1;", callback.from_user.id)
    await callback.message.edit_text(f"Спасибо за оценку ({score}⭐️)! +2 к теплу ☀️")

@dp.message(F.chat.id == ADMIN_CHAT_ID)
async def admin_reply(message: types.Message):
    if not message.message_thread_id or message.message_thread_id == UNASSIGNED_TOPIC_ID or message.from_user.is_bot: return
    if message.text and message.text.startswith("/"): return 
    async with db_pool.acquire() as conn:
        user_row = await conn.fetchrow("SELECT user_id FROM users WHERE topic_id = $1;", message.message_thread_id)
    if user_row: await message.send_copy(chat_id=user_row["user_id"])


# --- ЗАПУСК ---
async def main():
    try:
        await init_db()
        await bot.delete_webhook(drop_pending_updates=True)
        dp.message.middleware(SecurityMiddleware())
        asyncio.create_task(care_scheduler())
        logger.info("Бот успешно запущен!")
        await dp.start_polling(bot)
    finally:
        if db_pool:
            await db_pool.close()

if __name__ == "__main__":
    asyncio.run(main())