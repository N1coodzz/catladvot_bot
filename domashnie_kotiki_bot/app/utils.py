from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.config import settings
from app.models import Role, TaskStatus, ScheduleStatus


def now_msk() -> datetime:
    return datetime.now(settings.tz).replace(tzinfo=None)


def today_msk() -> datetime:
    n = now_msk()
    return datetime(n.year, n.month, n.day)


def parse_date_ru(text: str) -> datetime | None:
    """
    Поддерживает форматы:
    - 15.05
    - 15.05.2026
    - 15.05 20:00
    - 15.05.2026 20:00
    """
    text = text.strip()
    for fmt in ("%d.%m.%Y %H:%M", "%d.%m %H:%M", "%d.%m.%Y", "%d.%m"):
        try:
            dt = datetime.strptime(text, fmt)
            if fmt in ("%d.%m %H:%M", "%d.%m"):
                current = now_msk()
                dt = dt.replace(year=current.year)
            return dt
        except ValueError:
            continue
    return None


def parse_time_hhmm(text: str) -> time | None:
    try:
        return datetime.strptime(text.strip(), "%H:%M").time()
    except ValueError:
        return None


def combine_date_time(day: datetime, t: time) -> datetime:
    return datetime(day.year, day.month, day.day, t.hour, t.minute)


def fmt_dt(dt: datetime | None) -> str:
    if not dt:
        return "без срока"
    return dt.strftime("%d.%m.%Y %H:%M")


def fmt_date(dt: datetime) -> str:
    return dt.strftime("%d.%m.%Y")


def fmt_time(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def role_label(role: Role | str | None) -> str:
    raw = role.value if isinstance(role, Role) else role
    if raw == Role.KOT.value:
        return "🐱 Кот"
    if raw == Role.KOTIK.value:
        return "🐾 Котик"
    return "👥 Оба"


def status_label(status: TaskStatus | str) -> str:
    raw = status.value if isinstance(status, TaskStatus) else status
    labels = {
        "new": "🆕 Новая",
        "in_progress": "🔄 В работе",
        "done": "✅ Выполнена",
        "counted": "🟢 Засчитана",
        "discussion": "💬 На обсуждении",
        "rework": "🔄 На доработке",
        "points_review": "⭐ Баллы на согласовании",
        "overdue": "⏰ Просрочена",
        "cancelled": "❌ Отменена",
        "deleted": "🗑 Удалена",
    }
    return labels.get(raw, raw)


def schedule_status_label(status: ScheduleStatus | str) -> str:
    raw = status.value if isinstance(status, ScheduleStatus) else status
    labels = {
        "free": "💤 свободен/свободна",
        "busy": "💼 занят/занята",
        "work_shift": "💼 смена",
        "night_shift": "🌙 ночная смена",
        "partial_free_after": "🕑 свободен/свободна после времени",
        "partial_free_before": "🌅 свободен/свободна до времени",
        "irregular": "🌀 ненормированный день",
        "unknown": "❓ неизвестно",
    }
    return labels.get(raw, raw)
