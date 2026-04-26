from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Task, User
from app.services.schedule import classify_shared_intervals, format_intervals, shared_free_intervals
from app.services.tasks import list_today_tasks
from app.services.weather import get_weather
from app.utils import fmt_dt, role_label, status_label


def task_card(task: Task) -> str:
    assignee = role_label(task.assignee.role if task.assignee else None)
    return (
        f"📝 <b>{task.title}</b>\n"
        f"👤 Ответственный: {assignee}\n"
        f"⭐ Баллы: {task.points}\n"
        f"⏰ Срок: {fmt_dt(task.deadline_at)}\n"
        f"📌 Статус: {status_label(task.status)}"
    )


async def morning_message(session: AsyncSession, city: str) -> str:
    weather = await get_weather(city)
    tasks = await list_today_tasks(session)
    today = datetime.now().strftime("%d.%m")

    text = (
        "☀️ <b>Доброе утро, домашние котики!</b>\n\n"
        f"Сегодня {today}. Пусть день будет мягким, дела закрываются спокойно, "
        "а у котиков останутся силы на тепло друг к другу 😽\n\n"
        f"{weather['text']}\n"
        f"{weather['phrase']}\n\n"
    )

    if tasks:
        text += "📝 <b>Задачи на сегодня:</b>\n"
        for task in tasks[:8]:
            assignee = role_label(task.assignee.role if task.assignee else None)
            text += f"— {task.title} — {assignee}, {task.points} ⭐\n"
        if len(tasks) > 8:
            text += f"…и ещё {len(tasks) - 8} задач(и)\n"
        text += "\n"
    else:
        text += "📝 На сегодня задач пока нет. Можно добавить маленькое бытовое дело или просто порадоваться тишине 🐾\n\n"

    text += "💞 Не забывайте: вы команда."
    return text


async def evening_shared_message(session: AsyncSession, day: datetime) -> str:
    intervals = await shared_free_intervals(session, day)
    kind = classify_shared_intervals(intervals)

    day_text = day.strftime("%d.%m.%Y")
    if kind == "unknown":
        return (
            f"📅 <b>Проверка на завтра — {day_text}</b>\n\n"
            "🐾 По графику пока не хватает данных. Добавьте расписание, и я найду ваше совместное время 💞"
        )

    if kind == "none":
        return (
            f"🐾 <b>Завтра день плотный — {day_text}</b>\n\n"
            "Совместного окна почти нет, но даже маленькое тёплое сообщение может сделать день мягче 💌"
        )

    windows = format_intervals(intervals or [])
    if kind == "full_day":
        return (
            f"💞 <b>Котики, завтра вы оба дома!</b>\n\n"
            f"📅 {day_text}\n"
            "Это официальный день обнимашек, вкусной еды и отдыха от всех дел 🏡🐾"
        )

    if kind == "good_window":
        return (
            f"💞 <b>Завтра у вас есть хорошее общее время</b>\n\n"
            f"📅 {day_text}\n"
            f"🕐 Общее окно: <b>{windows}</b>\n\n"
            "Можно успеть погулять, посмотреть фильм или просто побыть вместе 😽"
        )

    return (
        f"🐾 <b>Завтра есть маленькое общее окошко</b>\n\n"
        f"📅 {day_text}\n"
        f"🕐 Общее окно: <b>{windows}</b>\n\n"
        "Даже час можно сделать тёплым 💞"
    )
