import asyncio
import logging
import os

from aiogram import Bot, Dispatcher

from app.config import load_config
from app.db import Storage
from app.handlers import create_owner_router, create_user_router
from app.relay import Relay

log = logging.getLogger("bot")


async def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = load_config()

    db = Storage(config.db_path)
    await db.connect()

    bot = Bot(token=config.bot_token)
    relay = Relay(bot, db)

    dispatcher = Dispatcher()
    dispatcher.include_router(create_owner_router(config, db, relay))
    dispatcher.include_router(create_user_router(config, db, relay))
    dispatcher.shutdown.register(db.close)

    log.info("bot started, owners: %s", ", ".join(map(str, config.owner_ids)))

    try:
        await dispatcher.start_polling(bot, allowed_updates=["message"])
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
