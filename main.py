import asyncio
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
import database as db

TOKEN = "8641353697:AAH4Lm2D9v99e7-X0FT-poOa1OVm7oT9gvg"
GROUP_CHAT_ID = -1004404098187
OWNER_ID = 8674242517
PROJECT_NAME = "Вечернее сияние"

dp = Dispatcher()
bot = Bot(token=TOKEN)

user_topics = {}
topic_users = {}

@dp.message(CommandStart(), F.chat.type == "private")
async def start_cmd(message: Message):
    db.add_user(message.from_user.id)
    await message.answer(
        f"Привет! Добро пожаловать в проект «{PROJECT_NAME}» ✨\n\n"
        "Напишите сюда ваше сообщение, и администрация ответит вам в ближайшее время."
    )

@dp.message(Command("broadcast"))
async def broadcast_cmd(message: Message):
    if not db.is_admin(message.from_user.id, OWNER_ID):
        return
    
    text_to_send = message.text.replace("/broadcast", "").strip()
    if not text_to_send:
        return await message.answer("Использование: `/broadcast Ваш текст`", parse_mode="Markdown")
    
    users = db.get_all_users()
    count = 0
    for u_id in users:
        try:
            await bot.send_message(u_id, text_to_send)
            count += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass
            
    await message.answer(f"📢 Рассылка завершена. Доставлено: {count}/{len(users)}")

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
    user_id = message.from_user.id
    user_name = message.from_user.full_name

    if user_id not in user_topics:
        try:
            topic = await bot.create_forum_topic(
                chat_id=GROUP_CHAT_ID,
                name=f"{user_name} | ID: {user_id}"
            )
            user_topics[user_id] = topic.message_thread_id
            topic_users[topic.message_thread_id] = user_id
        except Exception as e:
            logging.error(f"Ошибка при создании топика: {e}")
            return await message.answer("Произошла ошибка при отправке сообщения. Убедитесь, что бот является админом группы.")

    thread_id = user_topics[user_id]

    try:
        await bot.copy_message(
            chat_id=GROUP_CHAT_ID,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
            message_thread_id=thread_id
        )
        await message.answer("Ваше сообщение отправлено администрации!")
    except Exception as e:
        await message.answer("Не удалось доставить сообщение.")

@dp.message(F.chat.id == GROUP_CHAT_ID)
async def admin_reply_handler(message: Message):
    if not message.message_thread_id:
        return

    thread_id = message.message_thread_id
    user_id = topic_users.get(thread_id)

    if user_id:
        try:
            await bot.copy_message(
                chat_id=user_id,
                from_chat_id=GROUP_CHAT_ID,
                message_id=message.message_id
            )
        except Exception:
            await message.answer("❌ Не удалось отправить ответ. Возможно, пользователь заблокировал бота.")

async def main():
    db.init_db()
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
