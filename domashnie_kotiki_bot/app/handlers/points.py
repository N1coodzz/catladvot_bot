from __future__ import annotations

from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.tasks import all_points_summary
from app.services.users import get_all_users
from app.utils import now_msk, role_label

router = Router()


@router.message(F.text.in_({"⭐ Баллы", "/points"}))
async def points(message: Message, session: AsyncSession) -> None:
    users = await get_all_users(session)
    if not users:
        await message.answer("🐾 Пока никто не зарегистрирован.")
        return

    now = now_msk()
    today_start = datetime(now.year, now.month, now.day)
    week_start = today_start - timedelta(days=today_start.weekday())
    month_start = datetime(now.year, now.month, 1)

    today = await all_points_summary(session, users, today_start, today_start + timedelta(days=1))
    week = await all_points_summary(session, users, week_start, None)
    month = await all_points_summary(session, users, month_start, None)
    all_time = await all_points_summary(session, users, None, None)

    text = "⭐ <b>Звёздочки заботы</b>\n\n"

    text += "<b>Сегодня:</b>\n"
    for user in users:
        text += f"{role_label(user.role)} — {today[user.id]} ⭐\n"

    text += "\n<b>Неделя:</b>\n"
    for user in users:
        text += f"{role_label(user.role)} — {week[user.id]} ⭐\n"

    text += "\n<b>Месяц:</b>\n"
    for user in users:
        text += f"{role_label(user.role)} — {month[user.id]} ⭐\n"

    text += "\n<b>За всё время:</b>\n"
    for user in users:
        text += f"{role_label(user.role)} — {all_time[user.id]} ⭐\n"

    text += "\nДомик становится уютнее с каждым делом 🏡"
    await message.answer(text)
