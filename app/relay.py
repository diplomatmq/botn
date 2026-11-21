import logging

from aiogram import Bot
from aiogram.enums import ContentType, MessageEntityType
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import LinkPreviewOptions, Message, MessageEntity, MessageId, User

from app.db import Storage

log = logging.getLogger("bot")

TEXT_LIMIT = 4096
CAPTION_LIMIT = 1024
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)

CAPTIONABLE_TYPES = {
    ContentType.PHOTO,
    ContentType.VIDEO,
    ContentType.ANIMATION,
    ContentType.DOCUMENT,
    ContentType.AUDIO,
}

RELAYABLE_TYPES = CAPTIONABLE_TYPES | {
    ContentType.TEXT,
    ContentType.VOICE,
    ContentType.VIDEO_NOTE,
    ContentType.STICKER,
    ContentType.LIVE_PHOTO,
    ContentType.CONTACT,
    ContentType.LOCATION,
    ContentType.VENUE,
    ContentType.POLL,
    ContentType.DICE,
    ContentType.GAME,
}


def utf16_len(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def has_custom_emoji(entities: list[MessageEntity] | None) -> bool:
    return any(entity.type == MessageEntityType.CUSTOM_EMOJI for entity in entities or [])


def without_custom_emoji(entities: list[MessageEntity] | None) -> list[MessageEntity]:
    return [entity for entity in entities or [] if entity.type != MessageEntityType.CUSTOM_EMOJI]


def shift_entities(
    entities: list[MessageEntity] | None, offset: int
) -> list[MessageEntity] | None:
    if not entities:
        return None
    return [entity.model_copy(update={"offset": entity.offset + offset}) for entity in entities]


def is_custom_emoji_error(error: TelegramBadRequest) -> bool:
    return "CUSTOM_EMOJI" in (error.message or "").upper()


def build_header(sender: User) -> str:
    name = " ".join(part for part in (sender.first_name, sender.last_name) if part).strip()
    name = name or "Без имени"
    username = f" (@{sender.username})" if sender.username else ""
    return f"👤 {name}{username} · ID {sender.id}:"


class Relay:
    def __init__(self, bot: Bot, db: Storage):
        self._bot = bot
        self._db = db

    async def to_owner(self, message: Message, header: str, owner_id: int, user_id: int) -> None:
        header_line = f"{header}\n"
        offset = utf16_len(header_line)

        if message.text:
            combined = header_line + message.text
            if utf16_len(combined) <= TEXT_LIMIT:
                sent = await self._send_text(
                    owner_id, combined, shift_entities(message.entities, offset)
                )
            else:
                await self._send_header(owner_id, header, user_id)
                sent = await self._copy(owner_id, message)
        elif message.content_type in CAPTIONABLE_TYPES:
            caption = message.caption
            combined = header_line + caption if caption else header
            if utf16_len(combined) <= CAPTION_LIMIT:
                sent = await self._copy(
                    owner_id,
                    message,
                    caption=combined,
                    caption_entities=shift_entities(message.caption_entities, offset)
                    if caption
                    else None,
                )
            else:
                await self._send_header(owner_id, header, user_id)
                sent = await self._copy(owner_id, message)
        else:
            await self._send_header(owner_id, header, user_id)
            sent = await self._copy(owner_id, message)

        await self._db.link(owner_id, sent.message_id, user_id)

    async def to_user(self, message: Message, user_id: int) -> MessageId | Message:
        try:
            return await self._copy(user_id, message)
        except TelegramBadRequest as error:
            if not message.text or not is_custom_emoji_error(error):
                raise
            return await self._send_text(
                user_id, message.text, without_custom_emoji(message.entities) or None
            )

    async def report_failure(self, owner_id: int, header: str, error: TelegramBadRequest) -> None:
        try:
            await self._send_text(
                owner_id, f"Не получилось передать сообщение.\n{header} {error.message}"
            )
        except TelegramAPIError as nested:
            log.warning("failed to report relay error to %s: %s", owner_id, nested)

    async def _send_header(self, owner_id: int, header: str, user_id: int) -> None:
        sent = await self._send_text(owner_id, header)
        await self._db.link(owner_id, sent.message_id, user_id)

    async def _send_text(
        self, chat_id: int, text: str, entities: list[MessageEntity] | None = None
    ) -> Message:
        try:
            return await self._bot.send_message(
                chat_id, text, entities=entities, link_preview_options=NO_PREVIEW
            )
        except TelegramBadRequest as error:
            if not has_custom_emoji(entities) or not is_custom_emoji_error(error):
                raise
            return await self._bot.send_message(
                chat_id,
                text,
                entities=without_custom_emoji(entities) or None,
                link_preview_options=NO_PREVIEW,
            )

    async def _copy(
        self,
        chat_id: int,
        message: Message,
        caption: str | None = None,
        caption_entities: list[MessageEntity] | None = None,
    ) -> MessageId:
        source = {"from_chat_id": message.chat.id, "message_id": message.message_id}
        try:
            return await self._bot.copy_message(
                chat_id=chat_id,
                caption=caption,
                caption_entities=caption_entities,
                **source,
            )
        except TelegramBadRequest as error:
            if caption is None or not has_custom_emoji(caption_entities) or not is_custom_emoji_error(error):
                raise
            return await self._bot.copy_message(
                chat_id=chat_id,
                caption=caption,
                caption_entities=without_custom_emoji(caption_entities) or None,
                **source,
            )
