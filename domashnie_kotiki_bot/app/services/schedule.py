from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, time

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ExchangeSuggestion,
    ExchangeSuggestionStatus,
    Role,
    ScheduleEntry,
    ScheduleSource,
    ScheduleStatus,
    User,
)
from app.services.users import get_pair
from app.utils import combine_date_time, now_msk


DAY_START = time(0, 0)
DAY_END = time(23, 59)


@dataclass(frozen=True)
class Interval:
    start: datetime
    end: datetime

    @property
    def minutes(self) -> int:
        return max(0, int((self.end - self.start).total_seconds() // 60))

    @property
    def hours(self) -> float:
        return round(self.minutes / 60, 1)


def day_bounds(day: datetime) -> tuple[datetime, datetime]:
    start = datetime(day.year, day.month, day.day, 0, 0)
    end = start + timedelta(days=1)
    return start, end


def intersect(a: Interval, b: Interval) -> Interval | None:
    start = max(a.start, b.start)
    end = min(a.end, b.end)
    if start < end:
        return Interval(start, end)
    return None


def subtract_busy_from_day(day: datetime, busy: list[Interval]) -> list[Interval]:
    start, end = day_bounds(day)
    free = [Interval(start, end)]
    for b in sorted(busy, key=lambda x: x.start):
        next_free: list[Interval] = []
        for f in free:
            if b.end <= f.start or b.start >= f.end:
                next_free.append(f)
                continue
            if f.start < b.start:
                next_free.append(Interval(f.start, b.start))
            if b.end < f.end:
                next_free.append(Interval(b.end, f.end))
        free = next_free
    return [f for f in free if f.minutes >= 15]


async def add_schedule_entry(
    session: AsyncSession,
    user: User,
    day: datetime,
    status_type: ScheduleStatus,
    title: str,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    comment: str | None = None,
    source_type: ScheduleSource = ScheduleSource.MANUAL,
) -> ScheduleEntry:
    now = now_msk()
    entry = ScheduleEntry(
        user_id=user.id,
        date=datetime(day.year, day.month, day.day),
        start_at=start_at,
        end_at=end_at,
        status_type=status_type,
        title=title,
        comment=comment,
        source_type=source_type,
        created_at=now,
        updated_at=now,
    )
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return entry


async def list_entries_for_day(session: AsyncSession, user: User, day: datetime) -> list[ScheduleEntry]:
    start, end = day_bounds(day)

    # Для MVP берём все записи пользователя и фильтруем в Python.
    # Это проще и безопаснее для записей без start_at/end_at, например "выходной".
    # Для большой базы лучше заменить на SQL-фильтр по диапазонам.
    result = await session.execute(
        select(ScheduleEntry).where(ScheduleEntry.user_id == user.id)
    )
    all_entries = list(result.scalars())

    entries: list[ScheduleEntry] = []
    for e in all_entries:
        if e.start_at and e.end_at:
            # Смена пересекает выбранный день, включая ночные смены через полночь.
            if e.end_at > start and e.start_at < end:
                entries.append(e)
        else:
            # Полный день / выходной / неизвестный статус.
            if e.date.date() == start.date():
                entries.append(e)
    return entries


async def free_intervals_for_day(session: AsyncSession, user: User, day: datetime) -> list[Interval] | None:
    entries = await list_entries_for_day(session, user, day)
    start, end = day_bounds(day)

    if not entries:
        return None

    # Если есть полный выходной и нет рабочих интервалов — весь день свободен.
    has_full_free = any(e.status_type == ScheduleStatus.FREE for e in entries)
    busy: list[Interval] = []

    for e in entries:
        if e.status_type == ScheduleStatus.FREE:
            continue

        if e.status_type in {
            ScheduleStatus.WORK_SHIFT,
            ScheduleStatus.NIGHT_SHIFT,
            ScheduleStatus.BUSY,
            ScheduleStatus.IRREGULAR,
            ScheduleStatus.PARTIAL_FREE_AFTER,
            ScheduleStatus.PARTIAL_FREE_BEFORE,
        }:
            if e.start_at and e.end_at:
                busy.append(Interval(max(e.start_at, start), min(e.end_at, end)))
            elif e.status_type in {ScheduleStatus.BUSY, ScheduleStatus.IRREGULAR}:
                busy.append(Interval(start, end))

    if has_full_free and not busy:
        return [Interval(start, end)]

    return subtract_busy_from_day(day, busy)


async def shared_free_intervals(session: AsyncSession, day: datetime) -> list[Interval] | None:
    kot, kotik = await get_pair(session)
    if not kot or not kotik:
        return None

    kot_free = await free_intervals_for_day(session, kot, day)
    kotik_free = await free_intervals_for_day(session, kotik, day)

    if kot_free is None or kotik_free is None:
        return None

    shared: list[Interval] = []
    for a in kot_free:
        for b in kotik_free:
            i = intersect(a, b)
            if i and i.minutes >= 30:
                shared.append(i)
    return shared


def classify_shared_intervals(intervals: list[Interval] | None) -> str:
    if intervals is None:
        return "unknown"
    if not intervals:
        return "none"
    total_hours = sum(i.hours for i in intervals)
    longest = max(i.hours for i in intervals)
    if total_hours >= 20:
        return "full_day"
    if longest >= 4:
        return "good_window"
    return "small_window"


def format_intervals(intervals: list[Interval]) -> str:
    if not intervals:
        return "нет общего окна"
    parts = [f"{i.start:%H:%M}–{i.end:%H:%M}" for i in intervals]
    return ", ".join(parts)


async def find_exchange_candidates(session: AsyncSession, days_ahead: int = 14) -> list[ExchangeSuggestion]:
    """
    Ищет дни, где Кот работает, а Котик имеет большое свободное окно.
    Сохраняет кандидатов, если для даты ещё не было подсказки.
    """
    kot, kotik = await get_pair(session)
    if not kot or not kotik:
        return []

    today = now_msk()
    candidates: list[ExchangeSuggestion] = []

    for offset in range(1, days_ahead + 1):
        day = datetime(today.year, today.month, today.day) + timedelta(days=offset)

        kot_entries = await list_entries_for_day(session, kot, day)
        kot_work = [
            e for e in kot_entries
            if e.status_type in {ScheduleStatus.WORK_SHIFT, ScheduleStatus.NIGHT_SHIFT}
            and e.start_at and e.end_at
        ]
        if not kot_work:
            continue

        kotik_free = await free_intervals_for_day(session, kotik, day)
        if not kotik_free:
            continue

        longest_kotik = max(kotik_free, key=lambda i: i.minutes)
        if longest_kotik.hours < 4:
            continue

        # Если уже есть хорошее общее окно — обмен не нужен.
        shared = await shared_free_intervals(session, day)
        if shared and max(i.hours for i in shared) >= 4:
            continue

        for shift in kot_work:
            exists = await session.execute(
                select(ExchangeSuggestion).where(
                    ExchangeSuggestion.target_date == datetime(day.year, day.month, day.day),
                    ExchangeSuggestion.kot_shift_start == shift.start_at,
                    ExchangeSuggestion.ignored.is_(False),
                )
            )
            if exists.scalar_one_or_none():
                continue

            suggestion = ExchangeSuggestion(
                target_date=datetime(day.year, day.month, day.day),
                kot_shift_start=shift.start_at,
                kot_shift_end=shift.end_at,
                kotik_free_start=longest_kotik.start,
                kotik_free_end=longest_kotik.end,
                potential_shared_time=f"{longest_kotik.start:%H:%M}–{longest_kotik.end:%H:%M}",
                status=ExchangeSuggestionStatus.FOUND,
                suggested_at=None,
                last_reminded_at=None,
                ignored=False,
                comment="Автоматически найден шанс для совместного времени",
            )
            session.add(suggestion)
            candidates.append(suggestion)

    await session.commit()
    return candidates


async def list_exchange_suggestions(session: AsyncSession, limit: int = 10) -> list[ExchangeSuggestion]:
    result = await session.execute(
        select(ExchangeSuggestion)
        .where(ExchangeSuggestion.ignored.is_(False), ExchangeSuggestion.status != ExchangeSuggestionStatus.CLOSED)
        .order_by(ExchangeSuggestion.target_date)
        .limit(limit)
    )
    return list(result.scalars())
