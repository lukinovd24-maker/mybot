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
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
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

# Временная зона (UTC+5)
TZ = timezone(timedelta(hours=5))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
db_pool: asyncpg.Pool = None
last_tech_message_id = None
photo_id_mode = False 
warned_unauthorized_users = set()

# --- СОСТОЯНИЯ ---
class BotStates(StatesGroup):
    waiting_for_broadcast_audience = State()
    waiting_for_broadcast_n = State()
    waiting_for_broadcast = State()
    waiting_for_anon = State()
    waiting_for_secret = State()

# --- КОНТЕНТ (ТЕКСТЫ И ФИШКИ) ---
QUOTES = [
    "Звезды не могут сиять без темноты. Твои трудности делают тебя ярче. ✨",
    "Даже в самой темной ночи есть луч света, и сегодня этот луч — ты.",
    "Сделай глубокий вдох. Ты справляешься намного лучше, чем тебе кажется.",
    "Не забывай отдыхать. Твоя внутренняя батарейка тоже требует подзарядки. 🔋",
    "Вечер — это время, когда можно оставить все тревоги позади и просто быть собой.",
    "Самые красивые закаты бывают после самых тяжелых дней.",
    "Твой внутренний свет способен согреть даже самый холодный вечер. 🕯",
    "Ошибаться — нормально. Завтра будет новый день и новая попытка.",
    "Маленькие шаги — это тоже прогресс. Не торопи себя.",
    "Уют кроется в мелочах: в горячем чае, тихой музыке и спокойных мыслях. ☕️",
    "Ты заслуживаешь всей той любви и заботы, которую так щедро даришь другим.",
    "Пусть этот вечер принесет тебе только спокойствие и теплые мысли. 🌙"
]

HUGS = [
    "*Крепко обнимает* Все обязательно будет хорошо, я в тебя верю! ❤️",
    "Посылаю тебе виртуальный плед и кружку горячего какао ☕️ Укутывайся и отдыхай!",
    "Эй, солнышко! Ты огромный молодец. Горжусь тем, как ты справляешься со всем этим. 🫂",
    "Если день был тяжелым, помни, что теперь он закончился. Завтра будет легче. *Теплые обнимашки* 🌙",
    "Иногда лучшая продуктивность — это просто позволить себе полежать. Ты в безопасности, расслабься. ✨",
    "Лови тысячу лучей поддержки! Ты не один, мы рядом. ☀️",
    "*Гладит по голове* Ты стараешься, и это самое главное. Отдохни сегодня как следует.",
    "Давай вместе сделаем вдох... и выдох. Всё наладится, вот увидишь! 🫂",
    "Я хоть и бот, но отправляю тебе самые искренние и теплые объятия! ❤️",
    "Ты чудесный человек, и всё обязательно сложится самым лучшим образом. Не грусти! 🌸"
]

FILMS = [
    "Ходячий замок (2004) 🏰 — Идеальная сказка от Хаяо Миядзаки для уютного вечера.",
    "Шепот сердца (1995) 🎻 — Вдохновляющее аниме о поиске себя, творчестве и любви.",
    "Твое имя (2016) 🌠 — Невероятно красивая история о связи сквозь время и расстояние.",
    "Маленькие женщины (2019) 📖 — Теплый, осенний и очень душевный фильм о семье и мечтах.",
    "Паддингтон (2014) 🐻 — Максимально доброе и милое кино, которое гарантированно заставит улыбнуться.",
    "Невероятная жизнь Уолтера Митти (2013) 🏔 — Визуальный шедевр, который вдохновляет мечтать и действовать.",
    "Амели (2001) ☕️ — Чудаковатая, но очень светлая французская классика о маленьких радостях жизни.",
    "Коралина в Стране Кошмаров (2009) 🗝 — Слегка жутковатая, но безумно атмосферная кукольная анимация.",
    "Судзумэ, закрывающая двери (2022) 🚪 — Красиво, трогательно и с глубоким смыслом. Визуал на высоте!",
    "Патэма наоборот (2013) 🌌 — Очень необычное аниме, которое переворачивает мир с ног на голову."
]

MUSIC = [
    "Lofi Girl - 1 A.M Study Session 🎧 — Идеальный расслабляющий фон для учебы или мыслей.",
    "The Neighbourhood - Sweater Weather 🌧 — Настоящая осенне-вечерняя классика.",
    "Сироткин - Выше домов 🌇 — Очень светлая, теплая и атмосферная русскоязычная инди-песня.",
    "Joji - Glimpse of Us 🎹 — Меланхоличная, немного грустная, но невероятно красивая.",
    "in love with a ghost - we've never met but can we have a cup of coffee or something ☕️ — Название говорит само за себя!",
    "Coldplay - Yellow 🌟 — Песня, которая звучит и ощущается как теплые дружеские объятия.",
    "Mac DeMarco - Chamber Of Reflection 🪞 — Легкий гипнотический ретро-вайб для ночных раздумий.",
    "Aurora - Runaway 🌲 — Магический, эльфийский вокал, уносящий далеко в лес от забот.",
    "d4vd - Romantic Homicide 🥀 — Современная эстетика, немного мрачная, но завораживающая.",
    "Lamp - Yume Utsutsu 🏮 — Японский лаунж, безумно уютный и расслабляющий. Как теплый свет фонаря."
]

FAQ_TEXT = (
    "ℹ️ <b>Ответы на частые вопросы (FAQ):</b>\n\n"
    "<b>1. Как стать частью вашей команды (админом)?</b>\n"
    "— Время от времени мы открываем набор стажёров. Вся информация и анкеты публикуются в нашем основном канале @eve_ning_glow. Внимательно следите за новостями! ✨\n\n"
    "<b>2. Как долго ждать ответа от поддержки?</b>\n"
    "— Наши админы — такие же люди, у них есть учеба и личные дела. Обычно мы отвечаем в течение 1-2 часов. Пожалуйста, не переживайте и не дублируйте сообщения, мы обязательно увидим ваш тикет! 🫂\n\n"
    "<b>3. Для чего вообще нужен этот бот?</b>\n"
    "— Здесь вы можете задать вопрос администрации, предложить идею для постов (даже анонимно!), отправить теплое послание тайному другу или просто получить порцию уюта, если вам грустно. ☕️\n\n"
    "<b>4. Делаете ли вы ВП (взаимопиар) и сотрудничество?</b>\n"
    "— Да! Мы открыты к сотрудничеству. Ознакомиться с условиями можно <a href='https://t.me/eve_ning_glow/445'>в этом посте (Условия ВП)</a>. Если ваш канал подходит, пишите сообщение прямо в этого бота!\n\n"
    "<b>5. Где найти правила вашего комьюнити?</b>\n"
    "— Чтобы всем было комфортно, у нас есть правила. Обязательно прочитайте их тут: <a href='https://t.me/eve_ning_glow/444'>Правила Вечернего сияния</a>.\n\n"
    "<i>Остались вопросы? Просто напишите их следующим сообщением, и первый освободившийся админ с радостью вам ответит!</i> 🌙"
)

RULES_TEXT = (
    "📜 <b>Правила нашего уютного уголка:</b>\n\n"
    "Добро пожаловать в «Вечернее сияние»! ✨ Чтобы всем здесь было комфортно и тепло, мы просим соблюдать несколько простых правил:\n\n"
    "<b>1. Взаимоуважение — прежде всего 🫂</b>\n"
    "Относитесь к администраторам и другим участникам (в тайных письмах) с добром. Любые оскорбления, токсичность, буллинг и агрессия строго запрещены.\n\n"
    "<b>2. Терпение — добродетель 🕰</b>\n"
    "Пожалуйста, не спамьте сообщениями вроде «Ау», «Вы тут?», «Ответьте». Как только вы написали, у нас создался тикет. Админы ответят вам, как только освободятся!\n\n"
    "<b>3. Добро в «Анонимке» и «Тайном друге» 💌</b>\n"
    "Эти функции созданы для того, чтобы делиться теплом, поддержкой и крутыми идеями. Использование их для оскорблений или травли приведет к перманентному бану.\n\n"
    "<b>4. Никакого шок-контента и 18+ 🔞</b>\n"
    "Запрещена отправка любых материалов порнографического характера, жестокости или того, что может травмировать других людей.\n\n"
    "<b>5. Реклама и спам 🚫</b>\n"
    "Не присылайте нам спам-рассылки. Если вы хотите предложить Взаимопиар (ВП) или сотрудничество — напишите об этом сразу, вежливо и по делу.\n\n"
    "<i>⚠️ За нарушение этих правил администрация оставляет за собой право ограничить ваш доступ к боту навсегда.</i>\n"
    "Спасибо, что делаете «Вечернее сияние» самым светлым местом в Telegram! 🌙"
)

POST_TEMPLATES = {
    "1": {"photo": "AgACAgEAAxkBAAIHomqBVpn-nDfOlHe6GkV9Eu8Wsnl4AAIcDGsb1MkQROyB6LwuPOFnAQADAgADeQADPQQ", "text": "🛠 <b>Внимание: Технический перерыв</b>\n\nБот временно приостанавливает работу для проведения плановых технических работ."},
    "2": {"photo": "AgACAgEAAxkBAAIHpmqBV4Ym5NrmF3M1dt4EOLjMgPx6AAIbDGsb1MkQRBiVtlXZfeT_AQADAgADeQADPQQ", "text": "🔄 <b>Обновление системы</b>\n\nМы установили свежее обновление! Бот стал еще стабильнее и быстрее."},
    "3": {"photo": "AgACAgEAAxkBAAIHqGqBV6ZrZD72sMa54lXudN7wOmN2AAIaDGsb1MkQRDAwd7n4XwNcAQADAgADeQADPQQ", "text": "⚠️ <b>Технические неполадки</b>\n\nЗафиксированы кратковременные технические неполадки. Специалисты уже занимаются их устранением."},
    "4": {"photo": "AgACAgEAAxkBAAIHqmqBV8mmLrLScIsh5Yp_f2fO_IBoAAIZDGsb1MkQRENjPsVEPDrLAQADAgADeQADPQQ", "text": "🟢 <b>Бот работает в штатном режиме</b>\n\nВсе системы функционируют стабильно. Можете продолжать отправлять обращения!"},
    "5": {"photo": "AgACAgEAAxkBAAIHrGqBV_o0bNZUKlfax3cFbJLW-Oh6AAIYDGsb1MkQRKC2gU96LUkeAQADAgADeQADPQQ", "text": "✅ <b>Технический перерыв завершен</b>\n\nРаботы успешно завершены, бот возобновил полноценную работу в штатном режиме."},
    "6": {"photo": "AgACAgEAAxkBAAIHrmqBWBiT6kR8JGfgRN44yz92bZ9aAAIXDGsb1MkQRAljMvCDBCuVAQADAgADeQADPQQ", "text": "✨ <b>Результаты обновления</b>\n\nОбновление успешно развернуто. Все новые функции и улучшения уже доступны."}
}

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
                    join_date TIMESTAMP DEFAULT NOW(), care_sub BOOLEAN DEFAULT FALSE
                );
                ALTER TABLE users ADD COLUMN IF NOT EXISTS warmth INT DEFAULT 0;
                ALTER TABLE users ADD COLUMN IF NOT EXISTS msg_count INT DEFAULT 0;
                ALTER TABLE users ADD COLUMN IF NOT EXISTS join_date TIMESTAMP DEFAULT NOW();
                ALTER TABLE users ADD COLUMN IF NOT EXISTS care_sub BOOLEAN DEFAULT FALSE;
                ALTER TABLE users ADD COLUMN IF NOT EXISTS is_blocked BOOLEAN DEFAULT FALSE;

                CREATE TABLE IF NOT EXISTS admins (
                    user_id BIGINT PRIMARY KEY, username TEXT, role TEXT, tag TEXT,
                    warns INT DEFAULT 0, curator_id BIGINT, taken_tickets INT DEFAULT 0,
                    closed_tickets INT DEFAULT 0, rating_sum INT DEFAULT 0, rating_count INT DEFAULT 0
                );
                ALTER TABLE admins ADD COLUMN IF NOT EXISTS taken_tickets INT DEFAULT 0;
                ALTER TABLE admins ADD COLUMN IF NOT EXISTS closed_tickets INT DEFAULT 0;
                ALTER TABLE admins ADD COLUMN IF NOT EXISTS rating_sum INT DEFAULT 0;
                ALTER TABLE admins ADD COLUMN IF NOT EXISTS rating_count INT DEFAULT 0;
                
                CREATE TABLE IF NOT EXISTS admin_actions (
                    id SERIAL PRIMARY KEY, admin_id BIGINT, admin_username TEXT,
                    target_user_id BIGINT, action_time TIMESTAMP DEFAULT NOW(),
                    status TEXT DEFAULT 'open', closed_time TIMESTAMP
                );
                ALTER TABLE admin_actions ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'open';
                ALTER TABLE admin_actions ADD COLUMN IF NOT EXISTS closed_time TIMESTAMP;
                ALTER TABLE admin_actions ADD COLUMN IF NOT EXISTS action_time TIMESTAMP DEFAULT NOW();
                ALTER TABLE admin_actions ADD COLUMN IF NOT EXISTS admin_username TEXT;
                
                CREATE TABLE IF NOT EXISTS channel_posts (
                    post_id SERIAL PRIMARY KEY, message_id INT, channel_id BIGINT, text TEXT
                );
            """)
            await conn.execute("""
                INSERT INTO admins (user_id, role, tag) VALUES ($1, 'owner', 'Владелец')
                ON CONFLICT (user_id) DO UPDATE SET role = 'owner', tag = 'Владелец';
            """, OWNER_ID)
    except Exception as e:
        logger.critical(f"Ошибка при инициализации базы данных: {e}")
        raise

async def get_admin_role(user_id: int) -> str:
    if user_id == OWNER_ID: return 'owner'
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT role FROM admins WHERE user_id = $1;", user_id)
            return row["role"] if row else None
    except Exception: return None

# --- СИСТЕМНАЯ СИГНАЛИЗАЦИЯ (ПРОВЕРКА АДМИН-ЧАТА) ---
class SecurityMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[types.Message, Dict[str, Any]], Awaitable[Any]],
        event: types.Message,
        data: Dict[str, Any]
    ) -> Any:
        if isinstance(event, types.Message):
            # Проверяем только сообщения в админ-чате от реальных людей
            if event.chat.id == ADMIN_CHAT_ID and not event.from_user.is_bot:
                user_id = event.from_user.id
                role = await get_admin_role(user_id)
                # Если роли нет и мы еще не предупреждали об этом человеке
                if not role and user_id not in warned_unauthorized_users:
                    warned_unauthorized_users.add(user_id)
                    admin_mention = f"@{event.from_user.username}" if event.from_user.username else event.from_user.first_name
                    try:
                        await bot.send_message(
                            chat_id=OWNER_ID,
                            text=f"🚨 <b>Система безопасности!</b>\n"
                                 f"В админ-чате написал пользователь без роли стажёра/админа!\n\n"
                                 f"👤 Пользователь: {admin_mention}\n"
                                 f"🆔 ID: <code>{user_id}</code>\n\n"
                                 f"<i>Вы можете выдать ему роль (командой /setintern) или удалить из чата.</i>",
                            parse_mode=ParseMode.HTML
                        )
                    except Exception as e:
                        logger.error(f"Ошибка при отправке уведомления владельцу: {e}")
        
        return await handler(event, data)

# --- РАДАР НОВЫХ ЛИЦ В ЧАТЕ ---
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
            text = (f"👋 <b>Новый участник в админ-чате!</b>\n\n"
                    f"👤 Юзер: {mention}\n"
                    f"🆔 ID: <code>{new_member.id}</code>\n"
                    f"🎫 Открытый топик: {topic_text}\n"
                    f"📅 В базе данных: <b>{days_in_db} дней</b>")
        else:
            text = (f"👋 <b>Новый участник в админ-чате!</b>\n\n"
                    f"👤 Юзер: {mention}\n"
                    f"🆔 ID: <code>{new_member.id}</code>\n"
                    f"⚠️ В базе данных: <b>Не найден (ни разу не писал боту)</b>")
            
        await message.answer(text, parse_mode=ParseMode.HTML)


# --- ФОНОВАЯ РАССЫЛКА ЗАБОТЫ ---
async def care_scheduler():
    while True:
        now = datetime.now(TZ)
        if now.hour == 21 and now.minute == 0:
            async with db_pool.acquire() as conn:
                users = await conn.fetch("SELECT user_id FROM users WHERE care_sub = TRUE AND is_blocked = FALSE;")
            text = "🌙 Вечернее Сияние напоминает: этот день позади. Выпей чаю, включи любимую музыку и отдохни. Ты молодец! ❤️"
            for u in users:
                try:
                    await bot.send_message(u['user_id'], text)
                    await asyncio.sleep(0.1)
                except Exception: pass
            await asyncio.sleep(60)
        await asyncio.sleep(30)

# --- МЕНЮ ПОЛЬЗОВАТЕЛЯ И ФИШКИ ---
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
        [InlineKeyboardButton(text="💌 Тайный друг", callback_data="secret_friend"), InlineKeyboardButton(text="📜 Правила", callback_data="cat_rules")]
    ])
    await message.answer(
        "Приветствую, путник! Ты попал в прекрасный бот <b>«Вечернее сияние»</b> ✨\n\n"
        "Выбери нужный раздел ниже, или просто напиши сообщение, и к тебе придет админ. Удачи тебе, солнышко!",
        reply_markup=kb, parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data.startswith("cat_"))
async def process_category(callback: CallbackQuery):
    if callback.data == "cat_faq":
        await callback.message.answer(FAQ_TEXT, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    elif callback.data == "cat_rules":
        await callback.message.answer(RULES_TEXT, parse_mode=ParseMode.HTML)
    elif callback.data == "cat_question":
        await callback.message.answer("📝 Напиши свой вопрос следующим сообщением, и мы передадим его админам!")
    await callback.answer()

@dp.message(Command("rules"))
async def cmd_rules(message: types.Message):
    await message.answer(RULES_TEXT, parse_mode=ParseMode.HTML)

@dp.message(Command("profile"))
async def cmd_profile(message: types.Message):
    async with db_pool.acquire() as conn:
        u = await conn.fetchrow("SELECT warmth, msg_count, join_date FROM users WHERE user_id = $1;", message.from_user.id)
    if not u: return
    days = (datetime.now() - u['join_date']).days
    await message.answer(
        f"🪪 <b>Твоя карточка сияния:</b>\n\n"
        f"👤 Имя: {message.from_user.first_name}\n"
        f"☀️ Уровень тепла: <b>{u['warmth']}</b>\n"
        f"💬 Оставлено сообщений: {u['msg_count']}\n"
        f"📅 С нами дней: {days}", parse_mode=ParseMode.HTML
    )

@dp.message(Command("care"))
async def cmd_care(message: types.Message):
    async with db_pool.acquire() as conn:
        u = await conn.fetchrow("SELECT care_sub FROM users WHERE user_id = $1;", message.from_user.id)
        if not u: return
        new_val = not u['care_sub']
        await conn.execute("UPDATE users SET care_sub = $1 WHERE user_id = $2;", new_val, message.from_user.id)
    status = "✅ Подписка оформлена!" if new_val else "❌ Подписка отменена."
    await message.answer(f"{status} Ежедневные письма заботы в 21:00.")

@dp.message(Command("status"))
async def cmd_status(message: types.Message):
    async with db_pool.acquire() as conn:
        u = await conn.fetchrow("SELECT topic_id FROM users WHERE user_id = $1;", message.from_user.id)
        if not u or not u['topic_id']:
            return await message.answer("У тебя нет открытых обращений. Можешь написать нам!")
        open_tickets = await conn.fetchval("SELECT COUNT(*) FROM admin_actions WHERE status = 'open';")
    await message.answer(f"Твой тикет в работе! 🎫\nВсего открытых обращений у админов сейчас: {open_tickets}")

@dp.message(Command("hug"))
async def cmd_hug(message: types.Message): await message.answer(random.choice(HUGS))

@dp.message(Command("coffee"))
async def cmd_coffee(message: types.Message): await message.answer("Вот твой горячий какао с маршмеллоу ☕️, админ уже спешит к тебе!")

@dp.message(Command("quote"))
async def cmd_quote(message: types.Message): await message.answer(f"<i>«{random.choice(QUOTES)}»</i>", parse_mode=ParseMode.HTML)

@dp.message(Command("music"))
async def cmd_music(message: types.Message): await message.answer(f"🎧 Рекомендация на вечер: <b>{random.choice(MUSIC)}</b>", parse_mode=ParseMode.HTML)

@dp.message(Command("film"))
async def cmd_film(message: types.Message): await message.answer(f"🎬 Фильм на вечер: <b>{random.choice(FILMS)}</b>", parse_mode=ParseMode.HTML)

# --- АНОНИМКА И ТАЙНЫЙ ДРУГ ---
@dp.callback_query(F.data == "anon_suggest")
async def start_anon(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("🤫 Напиши свою идею или историю. Она будет отправлена админам абсолютно анонимно!")
    await state.set_state(BotStates.waiting_for_anon)
    await callback.answer()

@dp.message(BotStates.waiting_for_anon)
async def process_anon(message: types.Message, state: FSMContext):
    await bot.send_message(
        ADMIN_CHAT_ID, 
        f"🎭 <b>АНОНИМНАЯ ПРЕДЛОЖКА:</b>\n\n{message.text}", 
        parse_mode=ParseMode.HTML, 
        message_thread_id=UNASSIGNED_TOPIC_ID
    )
    await message.answer("✅ Отправлено анонимно! Спасибо за твою идею.")
    await state.clear()

@dp.callback_query(F.data == "secret_friend")
async def start_secret(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("💌 Напиши доброе послание. Я отправлю его случайному пользователю бота от Тайного Друга, а ты получишь +1 к теплу!")
    await state.set_state(BotStates.waiting_for_secret)
    await callback.answer()

@dp.message(BotStates.waiting_for_secret)
async def process_secret(message: types.Message, state: FSMContext):
    async with db_pool.acquire() as conn:
        users = await conn.fetch("SELECT user_id FROM users WHERE user_id != $1 AND is_blocked = FALSE LIMIT 100;", message.from_user.id)
        if users:
            target = random.choice(users)['user_id']
            try:
                await bot.send_message(target, f"💌 <b>Вам письмо от Тайного Друга!</b>\n\n<i>{message.text}</i>", parse_mode=ParseMode.HTML)
                await conn.execute("UPDATE users SET warmth = warmth + 1 WHERE user_id = $1;", message.from_user.id)
                await message.answer("✅ Твое письмо отправлено кому-то случайному! Уровень тепла +1 ☀️")
            except Exception:
                await message.answer("❌ Упс, птичка с письмом заблудилась. Попробуй позже.")
    await state.clear()

# --- СИСТЕМА АДМИНИСТРАТОРОВ И ТИКЕТОВ ---

@dp.message(Command("photoid"), F.from_user.id == OWNER_ID)
async def cmd_toggle_photoid(message: types.Message):
    global photo_id_mode
    photo_id_mode = not photo_id_mode
    state_text = "ВКЛЮЧЕН 🟢" if photo_id_mode else "ВЫКЛЮЧЕН 🔴"
    await message.answer(f"📸 Режим получения ID фото: <b>{state_text}</b>\nТеперь бот {'будет' if photo_id_mode else 'не будет'} реагировать на отправленные картинки.", parse_mode=ParseMode.HTML)

@dp.message(F.photo, F.from_user.id == OWNER_ID)
async def get_photo_id(message: types.Message):
    if not photo_id_mode: 
        return
    photo_id = message.photo[-1].file_id
    await message.answer(f"📸 <b>ID вашей картинки:</b>\n\n<code>{photo_id}</code>", parse_mode=ParseMode.HTML)

@dp.message(Command("help"))
@dp.message(F.text.lower().in_({".help", "/хелп", ".хелп"}))
async def cmd_help(message: types.Message):
    role = await get_admin_role(message.from_user.id)
    if not role: return await message.answer("❌ У вас нет доступа к командам администратора.")
    help_text = (
        "📌 <b>Список доступных команд:</b>\n\n"
        "👑 <b>Управление и Статистика:</b>\n"
        "├ /stats — Полная статистика бота\n"
        "├ /adminstats — Статистика закрытых тикетов\n"
        "├ /adminlist — Список состава\n"
        "├ /check — Проверить пользователя (по реплаю/ID/юзернейму)\n"
        "├ /id — Узнать ID пользователя (ответом)\n"
        "├ /broadcast — Сделать рассылку пользователям\n"
        "└ /photoid — Вкл/Выкл получение ID картинок (Только Владелец)\n\n"
        "🛡 <b>Роли и Дисциплина:</b>\n"
        "├ /setdirector [ID] — Назначить директора\n"
        "├ /setadmin [ID] — Назначить администратора\n"
        "├ /setintern [ID] — Назначить стажёра\n"
        "├ /demote [ID] — Уволить (понизить до пользователя)\n"
        "├ /addmins [ID] [тег] — Установить тег\n"
        "├ /setcurator [ID_админа] [ID_куратора] — Привязать куратора\n"
        "├ /warn [ID] — Выдать выговор (5 = автокик)\n"
        "└ /unwarn [ID] — Сбросить выговоры\n\n"
        "🎫 <b>Тикеты (внутри топика пользователя):</b>\n"
        "└ /close — Закрыть тикет (запишет стату и уведомит юзера)\n\n"
        "📢 <b>Шаблоны постов:</b> пост 1, пост 2... пост 6"
    )
    await message.answer(help_text, parse_mode=ParseMode.HTML)

@dp.message(Command("id"))
@dp.message(F.text.lower().in_({".ид", "/id"}))
async def cmd_id(message: types.Message):
    target = message.reply_to_message.from_user if message.reply_to_message else message.from_user
    await message.answer(
        f"🆔 <b>Информация:</b>\n├ Имя: {target.first_name}\n├ Юзернейм: @{target.username}\n└ ID: <code>{target.id}</code>",
        parse_mode=ParseMode.HTML
    )

@dp.message(Command("check"))
@dp.message(F.text.lower().in_({".чек", "/check"}))
async def cmd_check(message: types.Message):
    if not await get_admin_role(message.from_user.id): return await message.answer("❌ У вас нет прав.")
    
    args = message.text.split()
    target_id = None
    target_username = None

    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
    elif len(args) > 1:
        arg = args[1]
        if arg.isdigit():
            target_id = int(arg)
        elif arg.startswith("@"):
            target_username = arg[1:]
        else:
            target_username = arg
    else:
        return await message.answer("⚠️ Используйте команду ответом на сообщение или укажите ID/Юзернейм (Например: <code>.чек 123456</code> или <code>.чек @user</code>)", parse_mode=ParseMode.HTML)

    async with db_pool.acquire() as conn:
        if target_id:
            user_data = await conn.fetchrow("SELECT user_id, first_name, username, topic_id, is_blocked FROM users WHERE user_id = $1;", target_id)
        elif target_username:
            user_data = await conn.fetchrow("SELECT user_id, first_name, username, topic_id, is_blocked FROM users WHERE username ILIKE $1;", target_username)
    
    if not user_data:
        return await message.answer(f"❌ Пользователь не найден в базе.", parse_mode=ParseMode.HTML)
        
    has_ticket = "Да (топик открыт)" if user_data["topic_id"] else "Нет активных тикетов"
    is_blocked = "🚫 Да" if user_data["is_blocked"] else "🍏 Нет (Активен)"
    username_text = f"@{user_data['username']}" if user_data['username'] else "Скрыт"
    
    await message.answer(
        f"🔍 <b>Проверка пользователя:</b>\n"
        f"├ Имя: {user_data['first_name']}\n"
        f"├ Юзернейм: {username_text}\n"
        f"├ ID: <code>{user_data['user_id']}</code>\n"
        f"├ Бот заблокирован: {is_blocked}\n"
        f"└ Тикет: {has_ticket}", 
        parse_mode=ParseMode.HTML
    )

@dp.message(Command("adminlist"))
@dp.message(F.text.lower().in_({".админы", "/adminlist"}))
async def cmd_adminlist(message: types.Message):
    if not await get_admin_role(message.from_user.id): return
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id, username, role, tag, warns FROM admins ORDER BY role;")
    text = "📋 <b>Состав:</b>\n\n"
    for r in rows: text += f"▪️ ID {r['user_id']} — <b>{r['role']}</b> [{r['tag']}] | ⚠️ {r['warns']}/5\n"
    await message.answer(text, parse_mode=ParseMode.HTML)

@dp.message(Command("adminstats"))
@dp.message(F.text.lower().in_({".астат", "/adminstats"}))
async def cmd_admin_stats(message: types.Message):
    if await get_admin_role(message.from_user.id) not in ['owner', 'director']: 
        return await message.answer("❌ Недостаточно прав для просмотра этой статистики.")
    async with db_pool.acquire() as conn:
        query = """
            SELECT a.admin_id, MAX(a.admin_username) as admin_username,
                   COUNT(*) AS total_taken,
                   COUNT(*) FILTER (WHERE a.action_time >= CURRENT_DATE) AS taken_today,
                   COUNT(*) FILTER (WHERE a.action_time >= date_trunc('week', CURRENT_DATE)) AS taken_week,
                   COUNT(*) FILTER (WHERE a.action_time >= date_trunc('month', CURRENT_DATE)) AS taken_month,
                   COUNT(*) FILTER (WHERE a.status = 'closed') AS total_closed,
                   COUNT(*) FILTER (WHERE a.status = 'open') AS total_open,
                   MAX(ad.rating_sum) as r_sum, MAX(ad.rating_count) as r_count
            FROM admin_actions a
            JOIN admins ad ON a.admin_id = ad.user_id
            GROUP BY a.admin_id ORDER BY total_taken DESC;
        """
        rows = await conn.fetch(query)
        
    if not rows: return await message.answer("📈 Статистика пуста.")
    text = "📈 <b>Статистика сотрудников:</b>\n\n"
    for r in rows:
        r_sum = r['r_sum'] or 0
        r_count = r['r_count'] or 0
        rating = f"{(r_sum / r_count):.1f}⭐️" if r_count > 0 else "Нет оценок"
        
        username_text = f"@{r['admin_username']}" if r['admin_username'] else f"ID: {r['admin_id']}"
        
        text += (
            f"👤 <b>{username_text}</b>\n"
            f" ├ Взято всего: <b>{r['total_taken']}</b>\n"
            f" ├ За сегодня: {r['taken_today']} | За неделю: {r['taken_week']} | За месяц: {r['taken_month']}\n"
            f" ├ Закрыто: {r['total_closed']} | ⚠️ В работе: {r['total_open']}\n"
            f" └ Рейтинг: {rating}\n\n"
        )
    await message.answer(text, parse_mode=ParseMode.HTML)

@dp.message(Command("stats"))
@dp.message(F.text.lower().in_({".стат", "/stats"}))
async def cmd_stats(message: types.Message):
    if not await get_admin_role(message.from_user.id): return
    
    async with db_pool.acquire() as conn:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users;") or 0
        banned_users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_blocked = TRUE;") or 0
        active_users = total_users - banned_users
        
        owner_count = await conn.fetchval("SELECT COUNT(*) FROM admins WHERE role = 'owner';") or 0
        directors_count = await conn.fetchval("SELECT COUNT(*) FROM admins WHERE role = 'director';") or 0
        admins_count = await conn.fetchval("SELECT COUNT(*) FROM admins WHERE role = 'admin';") or 0
        interns_count = await conn.fetchval("SELECT COUNT(*) FROM admins WHERE role = 'intern';") or 0
        
        total_staff = owner_count + directors_count + admins_count + interns_count
        regular_users = max(0, total_users - total_staff)
        
        user_msgs = await conn.fetchval("SELECT SUM(msg_count) FROM users;") or 0
        admin_msgs = await conn.fetchval("SELECT COUNT(*) FROM admin_actions;") or 0
        total_msgs = user_msgs + admin_msgs

    stats_text = (
        "📊 <b>Полная статистика бота:</b>\n\n"
        "👥 <b>Пользователи:</b>\n"
        f"├ Всего пользователей: <b>{total_users}</b>\n"
        f"├ 🍏 Активных (чистых): <b>{active_users}</b>\n"
        f"└ 🚫 Забаненных: <b>{banned_users}</b>\n\n"
        "🎭 <b>Разделение по ролям:</b>\n"
        f"├ 👑 Владелец: <b>{owner_count}</b>\n"
        f"├ 💼 Директоров: <b>{directors_count}</b>\n"
        f"├ 🛡 Администраторов: <b>{admins_count}</b>\n"
        f"├ 🔰 Стажёров: <b>{interns_count}</b>\n"
        f"└ 👤 Пользователей: <b>{regular_users}</b>\n\n"
        "✉️ <b>Сообщения и активность:</b>\n"
        f"├ 📩 От пользователей: <b>{user_msgs}</b>\n"
        f"├ 📤 От администраторов: <b>{admin_msgs}</b>\n"
        f"└ 💬 Всего сообщений: <b>{total_msgs}</b>"
    )
    
    await message.answer(stats_text, parse_mode=ParseMode.HTML)

@dp.message(F.text.in_({"пост 1", "пост 2", "пост 3", "пост 4", "пост 5", "пост 6"}), F.from_user.id == OWNER_ID)
async def send_custom_template_post(message: types.Message):
    global last_tech_message_id
    try:
        key = message.text.split()[-1]
        template = POST_TEMPLATES.get(key)
        if key in ("4", "5") and last_tech_message_id:
            try: await bot.delete_message(chat_id=CHANNEL_ID, message_id=last_tech_message_id)
            except Exception: pass
            last_tech_message_id = None
        sent_msg = await bot.send_photo(chat_id=CHANNEL_ID, photo=template["photo"], caption=template["text"], parse_mode=ParseMode.HTML)
        if key in ("1", "3"): last_tech_message_id = sent_msg.message_id
        async with db_pool.acquire() as conn:
            await conn.execute("INSERT INTO channel_posts (message_id, channel_id, text) VALUES ($1, $2, $3);", sent_msg.message_id, sent_msg.chat.id, template["text"])
        await message.answer(f"✅ Пост #{key} успешно опубликован!")
    except Exception: await message.answer("❌ Ошибка публикации.")

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

@dp.message(Command("addmins"))
async def cmd_addmins(message: types.Message):
    if await get_admin_role(message.from_user.id) not in ['owner', 'director']: return
    args = message.text.split(maxsplit=2)
    if len(args) < 3: return
    async with db_pool.acquire() as conn: await conn.execute("UPDATE admins SET tag = $1 WHERE user_id = $2;", args[2], int(args[1]))
    await message.answer(f"✅ Установлен тег: <b>{args[2]}</b>", parse_mode=ParseMode.HTML)

@dp.message(Command("setcurator"))
async def cmd_set_curator(message: types.Message):
    if await get_admin_role(message.from_user.id) not in ['owner', 'director']: return
    args = message.text.split()
    if len(args) < 3: return
    async with db_pool.acquire() as conn: await conn.execute("UPDATE admins SET curator_id = $1 WHERE user_id = $2;", int(args[2]), int(args[1]))
    await message.answer(f"✅ Куратор назначен.")

@dp.message(Command("warn"))
async def cmd_warn(message: types.Message):
    if await get_admin_role(message.from_user.id) not in ['owner', 'director']: return
    args = message.text.split()
    if len(args) < 2: return
    target_id = int(args[1])
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT warns, curator_id FROM admins WHERE user_id = $1;", target_id)
        if not row: return
        new_warns = row['warns'] + 1
        if new_warns >= 5:
            await conn.execute("DELETE FROM admins WHERE user_id = $1;", target_id)
            try:
                await bot.ban_chat_member(chat_id=ADMIN_CHAT_ID, user_id=target_id)
                await bot.unban_chat_member(chat_id=ADMIN_CHAT_ID, user_id=target_id)
            except Exception: pass
            await message.answer(f"⚠️ Админ {target_id} получил 5/5 выговоров и снят.")
        else:
            await conn.execute("UPDATE admins SET warns = $1 WHERE user_id = $2;", new_warns, target_id)
            await message.answer(f"⚠️ Выговор выдан. Статус: <b>{new_warns}/5</b>", parse_mode=ParseMode.HTML)

@dp.message(Command("unwarn"))
async def cmd_unwarn(message: types.Message):
    if await get_admin_role(message.from_user.id) not in ['owner', 'director']: return
    args = message.text.split()
    if len(args) < 2: return
    async with db_pool.acquire() as conn: await conn.execute("UPDATE admins SET warns = 0 WHERE user_id = $1;", int(args[1]))
    await message.answer("✅ Выговоры обнулены.")

@dp.message(Command("broadcast"))
async def cmd_broadcast(message: types.Message, state: FSMContext):
    if await get_admin_role(message.from_user.id) not in ['owner', 'director']: return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Всем пользователям", callback_data="bc_all")],
        [InlineKeyboardButton(text="🔥 Самым активным (Топ 50)", callback_data="bc_active")],
        [InlineKeyboardButton(text="☀️ Самым теплым (Топ 50)", callback_data="bc_warm")],
        [InlineKeyboardButton(text="🔢 Каждому N-ому", callback_data="bc_nth")]
    ])
    await message.answer("📢 <b>Настройка рассылки</b>\nВыберите, кому отправить сообщение:", reply_markup=kb, parse_mode=ParseMode.HTML)
    await state.set_state(BotStates.waiting_for_broadcast_audience)

@dp.callback_query(F.data.startswith("bc_"), BotStates.waiting_for_broadcast_audience)
async def process_bc_audience(callback: CallbackQuery, state: FSMContext):
    audience = callback.data.split("_")[1]
    await state.update_data(audience=audience)
    
    if audience == "nth":
        await callback.message.edit_text("🔢 Введите число N (например, 5 — отправит каждому пятому):")
        await state.set_state(BotStates.waiting_for_broadcast_n)
    else:
        await callback.message.edit_text("📢 Отправьте сообщение (текст, фото, видео) для рассылки:")
        await state.set_state(BotStates.waiting_for_broadcast)

@dp.message(BotStates.waiting_for_broadcast_n)
async def process_bc_n(message: types.Message, state: FSMContext):
    if not message.text.isdigit() or int(message.text) < 2:
        return await message.answer("⚠️ Пожалуйста, введите число (больше 1).")
    await state.update_data(nth=int(message.text))
    await message.answer("📢 Отправьте сообщение для рассылки:")
    await state.set_state(BotStates.waiting_for_broadcast)

@dp.message(BotStates.waiting_for_broadcast)
async def process_broadcast(message: types.Message, state: FSMContext):
    data = await state.get_data()
    audience, nth = data.get("audience"), data.get("nth", 1)
    
    async with db_pool.acquire() as conn: 
        if audience in ["all", "nth"]:
            users = await conn.fetch("SELECT user_id FROM users WHERE is_blocked = FALSE;")
        elif audience == "active":
            users = await conn.fetch("SELECT user_id FROM users WHERE is_blocked = FALSE ORDER BY msg_count DESC LIMIT 50;")
        elif audience == "warm":
            users = await conn.fetch("SELECT user_id FROM users WHERE is_blocked = FALSE ORDER BY warmth DESC LIMIT 50;")
            
    if audience == "nth": users = users[::nth]
    
    success, blocked = 0, 0
    status_msg = await message.answer(f"⏳ <b>Рассылка началась...</b>\nЦелевая аудитория: {len(users)} чел.", parse_mode=ParseMode.HTML)
    
    async with db_pool.acquire() as conn:
        for u in users:
            try:
                await message.send_copy(chat_id=u["user_id"])
                success += 1
                await asyncio.sleep(0.05)
            except Exception as e:
                err_text = str(e).lower()
                if "forbidden" in err_text or "bot was blocked" in err_text or "deactivated" in err_text:
                    blocked += 1
                    await conn.execute("UPDATE users SET is_blocked = TRUE WHERE user_id = $1;", u["user_id"])
                
    await status_msg.edit_text(
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"Успешно доставлено: <b>{success}</b>\n"
        f"Заблокировали бота: <b>{blocked}</b>", 
        parse_mode=ParseMode.HTML
    )
    await state.clear()

# --- ОБРАБОТКА ТИКЕТОВ ---
@dp.message(F.chat.type == "private")
async def private_msg(message: types.Message, state: FSMContext):
    if await state.get_state(): return
    if message.text and message.text.startswith("/"): return
    user_id = message.from_user.id
    try:
        topic_id = None
        async with db_pool.acquire() as conn:
            await conn.execute("UPDATE users SET msg_count = msg_count + 1, is_blocked = FALSE WHERE user_id = $1;", user_id)
            async with conn.transaction():
                user_row = await conn.fetchrow("SELECT topic_id FROM users WHERE user_id = $1 FOR UPDATE;", user_id)
                if user_row and user_row["topic_id"]: topic_id = user_row["topic_id"]

        if not topic_id:
            forum_topic = await bot.create_forum_topic(chat_id=ADMIN_CHAT_ID, name=f"{message.from_user.first_name} | {user_id}")
            topic_id = forum_topic.message_thread_id
            async with db_pool.acquire() as conn: await conn.execute("UPDATE users SET topic_id = $1 WHERE user_id = $2;", topic_id, user_id)
            
            await bot.send_message(ADMIN_CHAT_ID, message_thread_id=topic_id, text=f"📋 <b>Новый пользователь:</b> [<code>{user_id}</code>]", parse_mode=ParseMode.HTML)
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🟢 Взять обращение", callback_data=f"take_pz_{user_id}")]])
            
            await bot.send_message(
                ADMIN_CHAT_ID, 
                message_thread_id=UNASSIGNED_TOPIC_ID, 
                text=f"⚠️ Новое обращение от [<code>{user_id}</code>]", 
                reply_markup=kb, 
                parse_mode=ParseMode.HTML
            )

        await message.send_copy(chat_id=ADMIN_CHAT_ID, message_thread_id=topic_id)
    except Exception as e: logger.error(f"Ошибка private_msg: {e}")

@dp.callback_query(F.data.startswith("take_pz_"))
async def take_pz(callback: types.CallbackQuery):
    try:
        target_id = int(callback.data.split("_")[2])
        admin_id = callback.from_user.id
        admin_mention = f"@{callback.from_user.username}" if callback.from_user.username else callback.from_user.first_name
        
        async with db_pool.acquire() as conn:
            user_row = await conn.fetchrow("SELECT topic_id FROM users WHERE user_id = $1;", target_id)
            
            if not user_row or not user_row["topic_id"]: 
                return await callback.answer("❌ Топик не найден. Возможно, пользователь удалил чат.", show_alert=True)
                
            await conn.execute("""
                INSERT INTO admin_actions (admin_id, admin_username, target_user_id, status, action_time) 
                VALUES ($1, $2, $3, 'open', NOW());
            """, admin_id, callback.from_user.username, target_id)
            await conn.execute("UPDATE admins SET taken_tickets = taken_tickets + 1 WHERE user_id = $1;", admin_id)
        
        user_topic_id = user_row["topic_id"]
        chat_id_str = str(ADMIN_CHAT_ID)
        clean_chat_id = chat_id_str[4:] if chat_id_str.startswith("-100") else chat_id_str.lstrip("-")
        topic_link = f"https://t.me/c/{clean_chat_id}/{user_topic_id}"
        
        await callback.message.edit_text(
            f"✅ <b>Обращение взято!</b> Сотрудник: <b>{admin_mention}</b>\n🔗 <a href='{topic_link}'>Перейти в топик</a>", 
            parse_mode=ParseMode.HTML
        )
        await bot.send_message(
            chat_id=ADMIN_CHAT_ID, 
            message_thread_id=user_topic_id, 
            text=f"🟢 Закреплено за {admin_mention}!\n<i>Для закрытия напишите /close</i>", 
            parse_mode=ParseMode.HTML
        )
        
        await callback.answer("Готово!")
    except Exception as e:
        logger.error(f"Ошибка в take_pz: {e}")
        await callback.answer(f"❌ Ошибка: {e}", show_alert=True)

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
            await conn.execute("UPDATE admins SET closed_tickets = closed_tickets + 1 WHERE user_id = $1;", admin_id)
            await conn.execute("UPDATE admin_actions SET status = 'closed', closed_time = NOW() WHERE target_user_id = $1 AND status = 'open';", user_id)
            await message.answer("✅ <b>Тикет успешно закрыт!</b>", parse_mode=ParseMode.HTML)
            
            rate_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="1 ⭐️", callback_data=f"rate_{admin_id}_1"), InlineKeyboardButton(text="5 ⭐️", callback_data=f"rate_{admin_id}_5")]])
            try: await bot.send_message(user_id, "✅ <b>Ваше обращение закрыто.</b>\nОцените работу поддержки:", reply_markup=rate_kb, parse_mode=ParseMode.HTML)
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
    await callback.message.edit_text(f"Спасибо за оценку ({score}⭐️)! Тебе начислено +2 к уровню тепла ☀️")

@dp.message(F.chat.id == ADMIN_CHAT_ID)
async def admin_reply(message: types.Message):
    if not message.message_thread_id or message.message_thread_id == UNASSIGNED_TOPIC_ID or message.from_user.is_bot: return
    if message.text and message.text.startswith("/close"): return
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