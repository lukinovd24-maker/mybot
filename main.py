import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from aiohttp import web
import database as db

# Новый токен установлен сюда
TOKEN = os.getenv("BOT_TOKEN", "8641353697:AAGaWup_XK0YobyxpDTydxhEx5vsm_hBevc")
GROUP_CHAT_ID = -1004404098187
OWNER_ID = 8674242517
PROJECT_NAME = "Вечернее сияние"

dp = Dispatcher()
bot = Bot(token=TOKEN)

@dp.message(CommandStart(), F.chat.type == "private")
async def start_cmd(message: Message):
    db.add_user(message.from_user.id)
    await message.answer(
        f"Привет! Добро пожаловать в проект «{PROJECT_NAME}» ✨\n\n"
        "Напишите сюда ваше сообщение, и администрация ответит вам в ближайшее время."
    )

@dp.message(Command("stats"))
async def stats_cmd(message: Message):
    if not db.is_admin(message.from_user.id, OWNER_ID):
        return
    
    total_users, blocked_users = db.get_user_counts()
    stats_data = db.get_stats()
    
    user_msgs = stats_data.get("user_messages", 0)
    admin_replies = stats_data.get("admin_replies", 0)
    total_messages = user_msgs + admin_replies
    
    text = (
        f"📊 **Статистика бота**\n"
        f"👥 Общее кол-во пользователей: **{total_users}**\n"
        f"🚫 Заблокированных: **{blocked_users}**\n\n"
        f"💬 Общее количество сообщений (от админов + от пользователей): **{total_messages}**\n"
        f"📥 Написано сообщений пользователями: **{user_msgs}**\n"
        f"📤 Ответов от админов: **{admin_replies}**"
    )
    await message.answer(text, parse_mode="Markdown")

@dp.message(Command("broadcast"))
async def broadcast_cmd(message: Message):
    if not db.is_admin(message.from_user.id, OWNER_ID):
        return
    
    text_to_send = message.text.replace("/broadcast", "").strip()
    if not text_to_send:
        return await message.answer("Использование: `/broadcast Ваш текст`", parse_mode="Markdown")
    
    users = db.get_all_users()
    count = 0
    blocked_count = 0
    
    for u_id in users:
        try:
            await bot.send_message(u_id, text_to_send)
            count += 1
            await asyncio.sleep(0.05)
        except Exception:
            db.set_user_blocked(u_id, True)
            blocked_count += 1
            
    await message.answer(f"📢 **Рассылка завершена!**\n\n✅ Доставлено: **{count}**\n🚫 Заблокировали бота: **{blocked_count}**", parse_mode="Markdown")

@dp.message(Command("addadmin"))
async def add_admin_cmd(message: Message):
    if not db.is_admin(message.from_user.id, OWNER_ID):
        return await message.answer("У вас нет прав для этой команды.")
    
    args = message.text.split(maxsplit=2)
    if len(args) < 2:
        return await message.answer("Использование: `/addadmin <user_id> [@username]`", parse_mode="Markdown")
    
    try:
        new_admin_id = int(args[1])
        username = args[2] if len(args) > 2 else "Без юзернейма"
        db.add_admin(new_admin_id, username)
        await message.answer(f"✅ Пользователь {new_admin_id} ({username}) добавлен в список админов!")
    except ValueError:
        await message.answer("ID пользователя должен быть числом!")

@dp.message(F.chat.type == "private")
async def user_message_handler(message: Message):
    db.add_user(message.from_user.id)
    db.increment_stat("user_messages")
    
    user_id = message.from_user.id
    user_name = message.from_user.full_name
    thread_id = db.get_thread_id(user_id)

    if not thread_id:
        try:
            topic = await bot.create_forum_topic(
                chat_id=GROUP_CHAT_ID,
                name=f"{user_name} | ID: {user_id}"
            )
            thread_id = topic.message_thread_id
            db.save_topic(user_id, thread_id)
        except Exception as e:
            logging.error(f"Ошибка создания топика: {e}")
            return await message.answer("Не удалось связаться с администрацией. Попробуйте позже.")

    try:
        await bot.copy_message(
            chat_id=GROUP_CHAT_ID,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
            message_thread_id=thread_id
        )
        await message.answer("Ваше сообщение отправлено администрации!")
    except Exception as e:
        try:
            topic = await bot.create_forum_topic(
                chat_id=GROUP_CHAT_ID,
                name=f"{user_name} | ID: {user_id}"
            )
            thread_id = topic.message_thread_id
            db.save_topic(user_id, thread_id)
            await bot.copy_message(
                chat_id=GROUP_CHAT_ID,
                from_chat_id=message.chat.id,
                message_id=message.message_id,
                message_thread_id=thread_id
            )
            await message.answer("Ваше сообщение отправлено администрации!")
        except Exception as ex:
            logging.error(f"Ошибка отправки: {ex}")
            await message.answer("Не удалось доставить сообщение.")

@dp.message(F.chat.id == GROUP_CHAT_ID)
async def admin_reply_handler(message: Message):
    if not message.message_thread_id:
        return

    thread_id = message.message_thread_id
    user_id = db.get_user_by_thread(thread_id)

    if user_id:
        try:
            await bot.copy_message(
                chat_id=user_id,
                from_chat_id=GROUP_CHAT_ID,
                message_id=message.message_id
            )
            db.increment_stat("admin_replies")
            db.set_user_blocked(user_id, False)
        except Exception:
            db.set_user_blocked(user_id, True)
            await message.answer("❌ Не удалось отправить ответ. Пользователь заблокировал бота.")

async def handle_ping(request):
    return web.Response(text="Bot is running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    app.router.add_get("/health", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def main():
    db.init_db()
    logging.basicConfig(level=logging.INFO)
    asyncio.create_task(start_web_server())
    await asyncio.sleep(1)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
