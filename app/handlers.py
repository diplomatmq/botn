import logging

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from app.config import Config
from app.db import Storage
from app.relay import RELAYABLE_TYPES, Relay, build_header

log = logging.getLogger("bot")

OWNER_HELP = (
    "Здесь появляются сообщения пользователей.\n"
    "Ответьте на любое из них — ваш ответ уйдёт автору.\n"
    "Поддерживаются текст, фото, видео, файлы, стикеры и кастомные эмодзи.\n"
    "/stats — сколько людей уже написало."
)

UNSUPPORTED_REPLY = "Такой тип сообщений я передать не могу."


def create_owner_router(config: Config, db: Storage, relay: Relay) -> Router:
    router = Router(name="owner")
    router.message.filter(F.chat.type == ChatType.PRIVATE, F.from_user.id.in_(config.owner_ids))

    @router.message(CommandStart())
    @router.message(Command("help"))
    async def owner_help(message: Message) -> None:
        await message.reply(OWNER_HELP)

    @router.message(Command("stats"))
    async def owner_stats(message: Message) -> None:
        await message.reply(f"Пользователей в базе: {await db.count_users()}")

    @router.message(F.reply_to_message)
    async def owner_reply(message: Message) -> None:
        user_id = await db.resolve(message.chat.id, message.reply_to_message.message_id)
        if user_id is None:
            await message.reply("Это сообщение не связано с пользователем.")
            return

        try:
            sent = await relay.to_user(message, user_id)
        except TelegramForbiddenError:
            await message.reply("Пользователь заблокировал бота, сообщение не доставлено.")
            return
        except TelegramBadRequest as error:
            await message.reply(f"Не удалось отправить: {error.message}")
            return

        await db.log_message(
            user_id=user_id,
            direction="out",
            chat_id=message.chat.id,
            message_id=sent.message_id,
            content_type=message.content_type.value,
            text=message.text or message.caption,
        )

    @router.message()
    async def owner_hint(message: Message) -> None:
        await message.reply("Ответьте на сообщение пользователя, чтобы отправить ответ.")

    return router


def create_user_router(config: Config, db: Storage, relay: Relay) -> Router:
    router = Router(name="user")
    router.message.filter(F.chat.type == ChatType.PRIVATE)

    @router.message(CommandStart())
    @router.message(Command("help"))
    async def user_start(message: Message) -> None:
        await message.reply(config.user_greeting)

    @router.message()
    async def user_message(message: Message) -> None:
        sender = message.from_user
        if sender is None:
            return

        await db.touch_user(
            user_id=sender.id,
            username=sender.username,
            first_name=sender.first_name,
            last_name=sender.last_name,
        )
        await db.log_message(
            user_id=sender.id,
            direction="in",
            chat_id=message.chat.id,
            message_id=message.message_id,
            content_type=message.content_type.value,
            text=message.text or message.caption,
        )

        if message.content_type not in RELAYABLE_TYPES:
            await message.reply(UNSUPPORTED_REPLY)
            return

        header = build_header(sender)
        for owner_id in config.owner_ids:
            try:
                await relay.to_owner(message, header, owner_id, sender.id)
            except TelegramForbiddenError:
                log.info("owner %s blocked the bot", owner_id)
            except TelegramBadRequest as error:
                log.warning("relay to owner %s failed: %s", owner_id, error)
                await relay.report_failure(owner_id, header, error)

    return router
