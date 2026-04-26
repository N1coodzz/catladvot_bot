from __future__ import annotations

from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards import points_period_keyboard
from app.services.tasks import all_points_summary, list_points_history
from app.services.users import get_all_users, get_user_by_tg
from app.utils import now_msk, role_label

router = Router()


def _period_bounds(period: str) -> tuple[str, datetime | None, datetime | None]:
    now = now_msk()
    today_start = datetime(now.year, now.month, now.day)
    if period == "today":
        return "за сегодня", today_start, today_start + timedelta(days=1)
    if period == "week":
        week_start = today_start - timedelta(days=today_start.weekday())
        return "за неделю", week_start, None
    if period == "month":
        return "за месяц", datetime(now.year, now.month, 1), None
    return "за всё время", None, None


async def _points_text(session: AsyncSession, period: str) -> str:
    users = await get_all_users(session)
    if not users:
        return "🐾 Пока никто не зарегистрирован."

    title, start, end = _period_bounds(period)
    summary = await all_points_summary(session, users, start, end)
    sorted_users = sorted(users, key=lambda u: summary[u.id], reverse=True)

    text = f"⭐ <b>Звёздочки заботы {title}</b>\n\n"
    for user in sorted_users:
        text += f"{role_label(user.role)} — <b>{summary[user.id]}</b> ⭐\n"

    if len(sorted_users) == 2:
        first, second = sorted_users
        diff = summary[first.id] - summary[second.id]
        if diff > 0:
            text += f"\n🏆 Сейчас чуть впереди {role_label(first.role)} на {diff} ⭐. Но главное — домик становится уютнее благодаря обоим 💞"
        else:
            text += "\n🐾 Пока ничья по звёздочкам. Милый баланс в домике 🏡"

    text += (
        "\n\nПодсказка: ниже можно быстро переключить период или посмотреть историю начислений."
    )
    return text


@router.message(F.text.in_({"⭐ Баллы", "/points"}))
async def points(message: Message, session: AsyncSession) -> None:
    user = await get_user_by_tg(session, message.from_user.id)
    text = await _points_text(session, "today")
    await message.answer(text, reply_markup=points_period_keyboard("today"))


@router.callback_query(F.data.startswith("points:"))
async def points_period(callback: CallbackQuery, session: AsyncSession) -> None:
    period = callback.data.split(":", 1)[1]
    if period not in {"today", "week", "month", "all"}:
        await callback.answer()
        return
    text = await _points_text(session, period)
    await callback.message.answer(text, reply_markup=points_period_keyboard(period))
    await callback.answer()


@router.callback_query(F.data.startswith("points_history:"))
async def points_history(callback: CallbackQuery, session: AsyncSession) -> None:
    period = callback.data.split(":", 1)[1]
    if period not in {"today", "week", "month", "all"}:
        await callback.answer()
        return

    title, start, end = _period_bounds(period)
    rows = await list_points_history(session, start=start, end=end, limit=15)
    if not rows:
        await callback.message.answer(
            f"📜 <b>История звёздочек {title}</b>\n\n"
            "Пока начислений нет. Значит, котики ещё только готовят бытовые подвиги 🐾",
            reply_markup=points_period_keyboard(period),
        )
        await callback.answer()
        return

    text = f"📜 <b>История звёздочек {title}</b>\n\n"
    for row in rows:
        sign = "+" if row.points > 0 else ""
        task_title = row.task.title if row.task else "ручная корректировка"
        text += f"{row.created_at:%d.%m %H:%M} · {role_label(row.user.role)} · {sign}{row.points} ⭐ · {task_title}\n"
    text += "\nПоказываю последние 15 записей, чтобы не перегружать чат 🐾"
    await callback.message.answer(text, reply_markup=points_period_keyboard(period))
    await callback.answer()
