from __future__ import annotations

from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards import main_menu, schedule_type_keyboard
from app.models import Role, ScheduleSource, ScheduleStatus
from app.services.schedule import (
    add_schedule_entry,
    find_exchange_candidates,
    format_intervals,
    list_exchange_suggestions,
    shared_free_intervals,
)
from app.services.users import get_user_by_tg
from app.utils import combine_date_time, fmt_date, now_msk, parse_date_ru, parse_time_hhmm, role_label

router = Router()


class AddSchedule(StatesGroup):
    choose_type = State()
    date = State()
    start_time = State()
    end_time = State()
    comment = State()


@router.message(F.text.in_({"📅 График", "/schedule"}))
async def schedule_menu(message: Message, session: AsyncSession, state: FSMContext) -> None:
    user = await get_user_by_tg(session, message.from_user.id)
    if not user:
        await message.answer("🐾 Сначала нажми /start.")
        return

    await state.clear()
    await state.set_state(AddSchedule.choose_type)
    await message.answer(
        f"📅 {role_label(user.role)}, какой день добавляем?",
        reply_markup=schedule_type_keyboard(user.role),
    )


@router.message(F.text == "🔁 Замены")
async def replacement_menu(message: Message, session: AsyncSession, state: FSMContext) -> None:
    user = await get_user_by_tg(session, message.from_user.id)
    if not user:
        await message.answer("🐾 Сначала нажми /start.")
        return

    if user.role != Role.KOT:
        await message.answer(
            "🐾 Замены нужны только для графика Кота.\n"
            "У Котика график ненормированный, его лучше менять через 📅 График и обычные дни."
        )
        return

    await state.clear()
    await state.update_data(schedule_type="replacement")
    await state.set_state(AddSchedule.date)
    await message.answer(
        "🔁 Добавляем замену Кота.\n\n"
        "📅 Введи дату, которую нужно изменить: <code>15.05</code> или <code>15.05.2026</code>"
    )


@router.callback_query(AddSchedule.choose_type, F.data.startswith("schedule_type:"))
async def schedule_type(callback: CallbackQuery, state: FSMContext) -> None:
    raw = callback.data.split(":", 1)[1]
    await state.update_data(schedule_type=raw)
    await state.set_state(AddSchedule.date)
    await callback.message.answer("📅 Введи дату в формате <code>15.05</code> или <code>15.05.2026</code>")
    await callback.answer()


@router.message(AddSchedule.date)
async def schedule_date(message: Message, state: FSMContext, session: AsyncSession) -> None:
    day = parse_date_ru(message.text)
    if not day:
        await message.answer("🐾 Не понял дату. Пример: <code>15.05</code>")
        return

    data = await state.get_data()
    schedule_type = data["schedule_type"]
    user = await get_user_by_tg(session, message.from_user.id)
    if not user:
        await message.answer("🐾 Сначала нажми /start.")
        return

    day = datetime(day.year, day.month, day.day)
    await state.update_data(day=day.isoformat())

    # Быстрые типы без ввода времени.
    if schedule_type == "free":
        await add_schedule_entry(
            session,
            user,
            day,
            ScheduleStatus.FREE,
            "Выходной",
            comment="Полностью свободный день",
        )
        await state.clear()
        await message.answer(f"💤 Записал выходной на {fmt_date(day)}. Котик отдыхает 🐾", reply_markup=main_menu())
        return

    if schedule_type == "free_after_14":
        start = day.replace(hour=0, minute=0)
        end = day.replace(hour=14, minute=0)
        await add_schedule_entry(
            session,
            user,
            day,
            ScheduleStatus.PARTIAL_FREE_AFTER,
            "Свободна после 14:00",
            start_at=start,
            end_at=end,
            comment="Занятость до 14:00, дальше свободное время",
        )
        await state.clear()
        await message.answer(f"🕑 Записал: {fmt_date(day)} свободна после 14:00 🐾", reply_markup=main_menu())
        return

    if schedule_type == "busy_until_19":
        start = day.replace(hour=0, minute=0)
        end = day.replace(hour=19, minute=0)
        await add_schedule_entry(
            session,
            user,
            day,
            ScheduleStatus.PARTIAL_FREE_AFTER,
            "Занята до 19:00",
            start_at=start,
            end_at=end,
            comment="Занятость до 19:00, дальше свободное время",
        )
        await state.clear()
        await message.answer(f"🌆 Записал: {fmt_date(day)} занята до 19:00 🐾", reply_markup=main_menu())
        return

    if schedule_type == "irregular":
        await add_schedule_entry(
            session,
            user,
            day,
            ScheduleStatus.IRREGULAR,
            "Ненормированный день",
            start_at=day.replace(hour=0, minute=0),
            end_at=day + timedelta(days=1),
            comment="Ненормированный день — лучше уточнить вручную",
        )
        await state.clear()
        await message.answer(f"🌀 Записал ненормированный день на {fmt_date(day)}. Пока считаю его занятым 🐾", reply_markup=main_menu())
        return

    # Предзаполненные смены.
    if schedule_type == "day_shift":
        start = day.replace(hour=8, minute=0)
        end = day.replace(hour=20, minute=0)
        await add_schedule_entry(session, user, day, ScheduleStatus.WORK_SHIFT, "Дневная смена", start, end)
        await state.clear()
        await message.answer(f"💼 Записал дневную смену {fmt_date(day)} 08:00–20:00 🐾", reply_markup=main_menu())
        return

    if schedule_type == "night_shift":
        start = day.replace(hour=20, minute=0)
        end = day + timedelta(days=1)
        end = end.replace(hour=8, minute=0)
        await add_schedule_entry(session, user, day, ScheduleStatus.NIGHT_SHIFT, "Ночная смена", start, end)
        await state.clear()
        await message.answer(f"🌙 Записал ночную смену {fmt_date(day)} 20:00–08:00 🐾", reply_markup=main_menu())
        return

    # custom_shift / work_day / replacement
    await state.set_state(AddSchedule.start_time)
    if schedule_type == "replacement":
        await message.answer(
            "🔁 Что стало с этим днём?\n\n"
            "Если смену забрали и день стал выходным — напиши: <code>выходной</code>.\n"
            "Если появилась/изменилась смена — напиши время начала, например: <code>08:00</code>"
        )
    else:
        await message.answer("⏰ Во сколько начинается занятость? Формат: <code>08:00</code>")


@router.message(AddSchedule.start_time)
async def schedule_start_time(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    schedule_type = data.get("schedule_type")
    text = message.text.strip().lower()

    # Для замены можно быстро сделать день выходным. Это перезаписывает старый график на дату.
    if schedule_type == "replacement" and text in {"выходной", "вых", "free", "отдых"}:
        user = await get_user_by_tg(session, message.from_user.id)
        if not user:
            await message.answer("🐾 Сначала нажми /start.")
            return
        if user.role != Role.KOT:
            await message.answer("🐾 Замены доступны только Коту.")
            await state.clear()
            return

        day = datetime.fromisoformat(data["day"])
        await add_schedule_entry(
            session,
            user,
            day,
            ScheduleStatus.FREE,
            "Замена: выходной",
            comment="Замена: смену забрали / день стал свободным",
            source_type=ScheduleSource.REPLACEMENT,
            replace_day=True,
        )
        await state.clear()
        await message.answer(
            f"🔁 Записал замену: {fmt_date(day)} теперь выходной. Старый график на этот день перезаписан 🐾",
            reply_markup=main_menu(),
        )
        return

    t = parse_time_hhmm(message.text)
    if not t:
        if schedule_type == "replacement":
            await message.answer("🐾 Напиши <code>выходной</code> или время начала смены, например: <code>08:00</code>")
        else:
            await message.answer("🐾 Не понял время. Пример: <code>08:00</code>")
        return
    await state.update_data(start_time=message.text.strip())
    await state.set_state(AddSchedule.end_time)
    await message.answer("⏰ Во сколько заканчивается? Формат: <code>20:00</code>")


@router.message(AddSchedule.end_time)
async def schedule_end_time(message: Message, state: FSMContext, session: AsyncSession) -> None:
    end_t = parse_time_hhmm(message.text)
    if not end_t:
        await message.answer("🐾 Не понял время. Пример: <code>20:00</code>")
        return

    data = await state.get_data()
    start_t = parse_time_hhmm(data["start_time"])
    day = datetime.fromisoformat(data["day"])
    user = await get_user_by_tg(session, message.from_user.id)
    if not user:
        await message.answer("🐾 Сначала нажми /start.")
        return

    start = combine_date_time(day, start_t)
    end = combine_date_time(day, end_t)
    if end <= start:
        end += timedelta(days=1)

    schedule_type = data["schedule_type"]
    if schedule_type == "replacement" and user.role != Role.KOT:
        await message.answer("🐾 Замены доступны только Коту. Для Котика используй обычный 📅 График.")
        await state.clear()
        return

    source = ScheduleSource.REPLACEMENT if schedule_type == "replacement" else ScheduleSource.MANUAL
    status = ScheduleStatus.NIGHT_SHIFT if end.date() > start.date() else ScheduleStatus.WORK_SHIFT

    title = "Замена" if schedule_type == "replacement" else "Смена по времени"
    await add_schedule_entry(
        session,
        user,
        day,
        status,
        title,
        start_at=start,
        end_at=end,
        source_type=source,
        replace_day=(schedule_type == "replacement"),
    )

    await state.clear()
    tail = "Старый график на этот день перезаписан 🔁" if schedule_type == "replacement" else "Учту это при поиске совместного времени 💞"
    await message.answer(
        f"📅 Записал график:\n\n"
        f"{role_label(user.role)}\n"
        f"📅 {fmt_date(day)}\n"
        f"⏰ {start:%H:%M}–{end:%H:%M}\n\n"
        f"{tail}",
        reply_markup=main_menu(),
    )


@router.message(F.text == "💞 Совместное время")
async def shared_time(message: Message, session: AsyncSession) -> None:
    now = now_msk()
    text = "💞 <b>Совместное время на ближайшие 7 дней</b>\n\n"

    found_any = False
    for offset in range(0, 7):
        day = datetime(now.year, now.month, now.day) + timedelta(days=offset)
        intervals = await shared_free_intervals(session, day)
        if intervals is None:
            text += f"📅 {day:%d.%m}: график не полностью заполнен\n"
            continue
        if intervals:
            found_any = True
            text += f"📅 {day:%d.%m}: {format_intervals(intervals)} 💞\n"
        else:
            text += f"📅 {day:%d.%m}: общего окна почти нет\n"

    if not found_any:
        text += "\n🐾 Пока не нашёл хороших окон, но график можно дополнить."
    else:
        text += "\nДаже маленькое окно можно сделать тёплым 🐾"

    await message.answer(text)


@router.message(F.text == "🔁 Возможные обмены")
async def exchange_candidates(message: Message, session: AsyncSession) -> None:
    await find_exchange_candidates(session, days_ahead=14)
    suggestions = await list_exchange_suggestions(session, limit=10)

    if not suggestions:
        await message.answer(
            "🔁 Пока не нашёл очевидных дней для обмена.\n\n"
            "Это хорошо: либо у котиков уже есть время, либо нужно чуть дополнить график 🐾"
        )
        return

    text = "🔁 <b>Возможные дни для обмена</b>\n\n"
    for s in suggestions:
        text += (
            f"📅 {s.target_date:%d.%m.%Y}\n"
            f"🐱 Кот работает: {s.kot_shift_start:%H:%M}–{s.kot_shift_end:%H:%M}\n"
            f"🐾 Котик свободна: {s.potential_shared_time}\n"
            "Можно подумать об обмене, если это легко и без напряга 💞\n\n"
        )
    await message.answer(text)
