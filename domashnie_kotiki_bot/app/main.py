from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.config import settings
from app.db import init_db
from app.handlers import points, schedule, settings as settings_handler, start, tasks
from app.middlewares import DbSessionMiddleware
from app.scheduler import setup_scheduler


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    await init_db()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    dp.update.middleware(DbSessionMiddleware())

    dp.include_router(start.router)
    dp.include_router(tasks.router)
    dp.include_router(points.router)
    dp.include_router(schedule.router)
    dp.include_router(settings_handler.router)

    setup_scheduler(bot)

    logging.info("Домашние котики запущены 🐾")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
