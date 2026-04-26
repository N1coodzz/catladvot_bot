from __future__ import annotations

from datetime import datetime, timedelta

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionLocal
from app.models import Role, User
from app.services.messages import evening_shared_message, morning_message
from app.services.schedule import find_exchange_candidates, list_exchange_suggestions
from app.services.tasks import all_points_summary
from app.services.users import get_all_users, get_pair
from app.utils import now_msk, role_label


def _parse_hhmm(value: str) -> tuple[int, int]:
    h, m = value.split(":")
    return int(h), int(m)


async def send_to_all(bot: Bot, text: str) -> None:
    async with SessionLocal() as session:
        users = await get_all_users(session)
        for user in users:
            if user.notifications_enabled:
                try:
                    await bot.send_message(user.telegram_id, text)
                except Exception:
                    pass


async def send_morning(bot: Bot) -> None:
    async with SessionLocal() as session:
        text = await morning_message(session, settings.weather_city)
        users = await get_all_users(session)
        for user in users:
            if user.notifications_enabled and user.morning_enabled:
                try:
                    await bot.send_message(user.telegram_id, text)
                except Exception:
                    pass


async def send_evening(bot: Bot) -> None:
    tomorrow = now_msk() + timedelta(days=1)
    async with SessionLocal() as session:
        text = await evening_shared_message(session, tomorrow)
        users = await get_all_users(session)
        for user in users:
            if user.notifications_enabled and user.evening_enabled:
                try:
                    await bot.send_message(user.telegram_id, text)
                except Exception:
                    pass


async def send_weekly_report(bot: Bot) -> None:
    async with SessionLocal() as session:
        users = await get_all_users(session)
        if not users:
            return

        now = now_msk()
        today_start = datetime(now.year, now.month, now.day)
        week_start = today_start - timedelta(days=today_start.weekday())
        points = await all_points_summary(session, users, week_start, None)

        text = "🏆 <b>Итоги недели в домике</b>\n\n"
        for user in users:
            text += f"{role_label(user.role)} — {points[user.id]} ⭐\n"

        text += "\nГлавное — дом стал уютнее благодаря вам обоим 💞"

        for user in users:
            if user.notifications_enabled:
                try:
                    await bot.send_message(user.telegram_id, text)
                except Exception:
                    pass


async def send_exchange_overview(bot: Bot) -> None:
    if not settings.exchange_suggestions_enabled:
        return

    async with SessionLocal() as session:
        await find_exchange_candidates(session, days_ahead=14)
        suggestions = await list_exchange_suggestions(session, limit=5)
        if not suggestions:
            return

        kot, _ = await get_pair(session)
        if not kot:
            return

        text = "🐾 <b>Кот, бот нашёл пару мягких шансов для совместного времени</b>\n\n"
        for s in suggestions[:3]:
            text += (
                f"📅 {s.target_date:%d.%m}\n"
                f"🐱 У тебя смена: {s.kot_shift_start:%H:%M}–{s.kot_shift_end:%H:%M}\n"
                f"🐾 У Котика свободное окно: {s.potential_shared_time}\n"
                "Если поменяться будет легко — можно попробовать 💞\n\n"
            )
        text += "Без давления — просто тёплая подсказка от бота."

        try:
            await bot.send_message(kot.telegram_id, text)
        except Exception:
            pass


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=settings.timezone)

    mh, mm = _parse_hhmm(settings.morning_message_time)
    eh, em = _parse_hhmm(settings.evening_message_time)
    wh, wm = _parse_hhmm(settings.weekly_report_time)

    scheduler.add_job(send_morning, CronTrigger(hour=mh, minute=mm, timezone=settings.timezone), args=[bot])
    scheduler.add_job(send_evening, CronTrigger(hour=eh, minute=em, timezone=settings.timezone), args=[bot])
    scheduler.add_job(send_weekly_report, CronTrigger(day_of_week="sun", hour=wh, minute=wm, timezone=settings.timezone), args=[bot])

    # Мягкий обзор возможных обменов: воскресенье и среда, без ежедневного спама.
    scheduler.add_job(send_exchange_overview, CronTrigger(day_of_week="sun", hour=18, minute=0, timezone=settings.timezone), args=[bot])
    scheduler.add_job(send_exchange_overview, CronTrigger(day_of_week="wed", hour=18, minute=0, timezone=settings.timezone), args=[bot])

    scheduler.start()
    return scheduler
