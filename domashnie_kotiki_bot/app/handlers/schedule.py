from __future__ import annotations

from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards import (
    main_menu,
    schedule_period_keyboard,
    schedule_result_keyboard,
    schedule_type_keyboard,
)
from app.models import Role, ScheduleSource, ScheduleStatus
from app.services.schedule import (
    add_schedule_entry,
    find_exchange_candidates,
    format_intervals,
    free_intervals_for_day,
    list_entries_for_day,
    list_exchange_suggestions,
    shared_free_intervals,
)
from app.services.users import get_user_by_tg
from app.utils import fmt_date, now_msk, parse_date_ru, parse_time_hhmm, role_label, schedule_status_label

router = Router()


class AddSchedule(StatesGroup):
    choose_type = State()
    date = State()
    start_time = State()
    end_time = State()
    after_period = State()


def _day_iso(day: datetime) -> str:
    return day.strftime("%Y-%m-%d")


def _parse_day_iso(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d")


def _periods_text(periods: list[dict]) -> str:
    if not periods:
        return "пока нет периодов"
    parts = []
    for idx, p in enumerate(periods, 1):
        start = datetime.fromisoformat(p["start"])
        end = datetime.fromisoformat(p["end"])
        parts.append(f"{idx}) {start:%H:%M}–{end:%H:%M}" + (" (+1 день)" if end.date() > start.date() else ""))
    return "\n".join(parts)


async def _show_schedule_day(session: AsyncSession, user, day: datetime) -> str:
    entries = await list_entries_for_day(session, user, day)
    text = f"📅 <b>График: {role_label(user.role)} — {fmt_date(day)}</b>\n\n"

    if not entries:
        text += "🐾 На этот день график пока не заполнен.\n"
    else:
        for idx, entry in enumerate(entries, 1):
            if entry.start_at and entry.end_at:
                period = f"{entry.start_at:%H:%M}–{entry.end_at:%H:%M}"
                if entry.end_at.date() > entry.start_at.date():
                    period += " (+1 день)"
            else:
                period = "весь день"
            source = "🔁 замена" if entry.source_type == ScheduleSource.REPLACEMENT else "✍️ вручную"
            text += (
                f"{idx}. {schedule_status_label(entry.status_type)}\n"
                f"   🕐 {period}\n"
                f"   📌 {entry.title} · {source}\n"
            )
            if entry.comment:
                text += f"   💬 {entry.comment}\n"
            text += "\n"

    free = await free_intervals_for_day(session, user, day)
    if free is None:
        text += "🕊 Свободные окна: нужно добавить график.\n"
    elif free:
        text += f"🕊 Свободные окна: <b>{format_intervals(free)}</b>\n"
    else:
        text += "🕊 Свободные окна: почти нет.\n"

    shared = await shared_free_intervals(session, day)
    if shared is None:
        text += "💞 Общее время: пока не хватает графика второго котика.\n"
    elif shared:
        text += f"💞 Общее время котиков: <b>{format_intervals(shared)}</b>\n"
    else:
        text += "💞 Общее время котиков: почти нет общего окна.\n"

    return text


async def _send_saved_result(message: Message, session: AsyncSession, user, day: datetime, title: str) -> None:
    text = await _show_schedule_day(session, user, day)
    await message.answer(
        f"{title}\n\n{text}\n🐾 Если что-то не так — можно сразу отредактировать этот день.",
        reply_markup=schedule_result_keyboard(_day_iso(day)),
    )
    await message.answer("🏡 Вернула меню под твою роль", reply_markup=main_menu(user.role))


async def _save_quick_day(
    session: AsyncSession,
    user,
    day: datetime,
    status: ScheduleStatus,
    title: str,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    comment: str | None = None,
    source_type: ScheduleSource = ScheduleSource.MANUAL,
) -> None:
    await add_schedule_entry(
        session,
        user,
        day,
        status,
        title,
        start_at=start_at,
        end_at=end_at,
        comment=comment,
        source_type=source_type,
        replace_day=True,
    )


async def _continue_after_date(message: Message, state: FSMContext, session: AsyncSession, user, day: datetime) -> None:
    data = await state.get_data()
    schedule_type = data.get("schedule_type")
    source_type = ScheduleSource.REPLACEMENT if schedule_type == "replacement" else ScheduleSource.MANUAL

    # Быстрые типы: сохраняем сразу и показываем понятный итог.
    if schedule_type == "free":
        await _save_quick_day(session, user, day, ScheduleStatus.FREE, "Выходной", comment="Полностью свободный день", source_type=source_type)
        await state.clear()
        await _send_saved_result(message, session, user, day, f"💤 Записал выходной на {fmt_date(day)}")
        return

    if schedule_type == "free_after_14":
        await _save_quick_day(
            session,
            user,
            day,
            ScheduleStatus.PARTIAL_FREE_AFTER,
            "Свободна после 14:00",
            start_at=day.replace(hour=0, minute=0),
            end_at=day.replace(hour=14, minute=0),
            comment="Занятость до 14:00, дальше свободное время",
        )
        await state.clear()
        await _send_saved_result(message, session, user, day, f"🕑 Записал: {fmt_date(day)} свободна после 14:00")
        return

    if schedule_type == "busy_until_19":
        await _save_quick_day(
            session,
            user,
            day,
            ScheduleStatus.PARTIAL_FREE_AFTER,
            "Занята до 19:00",
            start_at=day.replace(hour=0, minute=0),
            end_at=day.replace(hour=19, minute=0),
            comment="Занятость до 19:00, дальше свободное время",
        )
        await state.clear()
        await _send_saved_result(message, session, user, day, f"🌆 Записал: {fmt_date(day)} занята до 19:00")
        return

    if schedule_type == "irregular":
        await _save_quick_day(
            session,
            user,
            day,
            ScheduleStatus.IRREGULAR,
            "Ненормированный день",
            start_at=day.replace(hour=0, minute=0),
            end_at=day + timedelta(days=1),
            comment="Ненормированный день — лучше уточнить вручную, если появятся точные окна",
        )
        await state.clear()
        await _send_saved_result(message, session, user, day, f"🌀 Записал ненормированный день на {fmt_date(day)}")
        return

    # Все рабочие/сменные типы идут через один удобный ввод периодов.
    await state.update_data(periods=[])
    await state.set_state(AddSchedule.start_time)
    if schedule_type == "replacement":
        await message.answer(
            "🔁 <b>Замена Кота</b> — это изменение уже существующего графика на конкретный день.\n\n"
            "Если день стал выходным — напиши <code>выходной</code>.\n"
            "Если появилась/изменилась смена — введи время начала первого периода, например <code>08:00</code>.\n\n"
            "После первого периода можно добавить ещё один, если день разбит на части."
        )
    else:
        await message.answer(
            "🕐 Введи <b>первое время занятости</b>.\n\n"
            "Пример: <code>09:00</code>\n"
            "Если занятость в несколько частей, после первого периода нажмёшь “➕ Добавить ещё”."
        )


@router.message(F.text.in_({"📅 График", "/schedule"}))
async def schedule_menu(message: Message, session: AsyncSession, state: FSMContext) -> None:
    user = await get_user_by_tg(session, message.from_user.id)
    if not user:
        await message.answer("🐾 Сначала нажми /start.")
        return

    await state.clear()
    await state.set_state(AddSchedule.choose_type)
    hint = (
        "🐱 Для Кота здесь можно указать смену, ночь, выходной или занятость по времени. "
        "Замены доступны отдельной кнопкой 🔁."
        if user.role == Role.KOT
        else "🐾 Для Котика выбирай формат дня. Если день рабочий и занятость кусками — выбирай 💼 Рабочий день, там можно добавить несколько периодов."
    )
    await message.answer(
        f"📅 <b>{role_label(user.role)}, какой день добавляем?</b>\n\n{hint}",
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
            "🐾 У Котика нет вкладки замен: у неё график ненормированный.\n"
            "Чтобы изменить день, используй 📅 График → выбери дату → задай новый формат дня.",
            reply_markup=main_menu(user.role),
        )
        return

    await state.clear()
    await state.update_data(schedule_type="replacement")
    await state.set_state(AddSchedule.date)
    await message.answer(
        "🔁 <b>Замена</b> — это когда у Кота изменился уже известный график:\n"
        "— взял чужую смену;\n"
        "— смену забрали;\n"
        "— поменялся сменами.\n\n"
        "📅 Введи дату, которую нужно заменить: <code>15.05</code> или <code>15.05.2026</code>"
    )


@router.callback_query(AddSchedule.choose_type, F.data.startswith("schedule_type:"))
async def schedule_type(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    raw = callback.data.split(":", 1)[1]
    user = await get_user_by_tg(session, callback.from_user.id)
    if not user:
        await callback.message.answer("🐾 Сначала нажми /start.")
        await callback.answer()
        return

    if raw == "replacement" and user.role != Role.KOT:
        await callback.answer("Замены доступны только Коту 🐾", show_alert=True)
        return

    await state.update_data(schedule_type=raw)
    data = await state.get_data()
    edit_day = data.get("edit_day")
    if edit_day:
        day = _parse_day_iso(edit_day)
        await state.update_data(day=day.isoformat())
        await _continue_after_date(callback.message, state, session, user, day)
        await callback.answer()
        return

    await state.set_state(AddSchedule.date)
    await callback.message.answer(
        "📅 Введи дату в формате <code>15.05</code> или <code>15.05.2026</code>.\n\n"
        "Подсказка: после выбора типа дня бот уже не будет предлагать другие типы — чтобы не путаться."
    )
    await callback.answer()


@router.message(AddSchedule.date)
async def schedule_date(message: Message, state: FSMContext, session: AsyncSession) -> None:
    day = parse_date_ru(message.text)
    if not day:
        await message.answer("🐾 Не понял дату. Пример: <code>15.05</code>")
        return

    user = await get_user_by_tg(session, message.from_user.id)
    if not user:
        await message.answer("🐾 Сначала нажми /start.")
        return

    day = datetime(day.year, day.month, day.day)
    await state.update_data(day=day.isoformat())
    await _continue_after_date(message, state, session, user, day)


@router.message(AddSchedule.start_time)
async def schedule_start_time(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    schedule_type = data.get("schedule_type")
    text = message.text.strip().lower()

    if schedule_type == "replacement" and text in {"выходной", "вых", "free", "отдых"}:
        user = await get_user_by_tg(session, message.from_user.id)
        if not user or user.role != Role.KOT:
            await message.answer("🐾 Замены доступны только Коту.")
            await state.clear()
            return
        day = datetime.fromisoformat(data["day"])
        await _save_quick_day(
            session,
            user,
            day,
            ScheduleStatus.FREE,
            "Замена: выходной",
            comment="Замена: смену забрали / день стал свободным",
            source_type=ScheduleSource.REPLACEMENT,
        )
        await state.clear()
        await _send_saved_result(message, session, user, day, f"🔁 Записал замену: {fmt_date(day)} теперь выходной")
        return

    t = parse_time_hhmm(message.text)
    if not t:
        await message.answer("🐾 Не понял время. Введи в формате <code>08:00</code>.")
        return

    await state.update_data(start_time=message.text.strip())
    await state.set_state(AddSchedule.end_time)
    await message.answer(
        "⏰ Теперь введи время окончания этого периода.\n\n"
        "Пример: <code>20:00</code>\n"
        "Если конец меньше начала, я пойму это как переход на следующий день. Например 20:00–08:00."
    )


@router.message(AddSchedule.end_time)
async def schedule_end_time(message: Message, state: FSMContext, session: AsyncSession) -> None:
    end_t = parse_time_hhmm(message.text)
    if not end_t:
        await message.answer("🐾 Не понял время. Пример: <code>20:00</code>")
        return

    data = await state.get_data()
    start_t = parse_time_hhmm(data["start_time"])
    day = datetime.fromisoformat(data["day"])
    start = day.replace(hour=start_t.hour, minute=start_t.minute)
    end = day.replace(hour=end_t.hour, minute=end_t.minute)
    if end <= start:
        end += timedelta(days=1)

    periods = list(data.get("periods") or [])
    periods.append({"start": start.isoformat(), "end": end.isoformat()})
    await state.update_data(periods=periods)
    await state.set_state(AddSchedule.after_period)

    await message.answer(
        "✅ Период добавлен.\n\n"
        f"<b>Текущие периоды занятости:</b>\n{_periods_text(periods)}\n\n"
        "Можно добавить ещё один период или сохранить день.",
        reply_markup=schedule_period_keyboard(),
    )


@router.callback_query(AddSchedule.after_period, F.data.startswith("schedule_period:"))
async def schedule_period_action(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    action = callback.data.split(":", 1)[1]
    data = await state.get_data()
    user = await get_user_by_tg(session, callback.from_user.id)
    if not user:
        await callback.message.answer("🐾 Сначала нажми /start.")
        await callback.answer()
        return

    if action == "add":
        await state.set_state(AddSchedule.start_time)
        await callback.message.answer("➕ Введи начало следующего периода занятости, например <code>15:00</code>")
        await callback.answer()
        return

    if action == "clear":
        await state.update_data(periods=[])
        await state.set_state(AddSchedule.start_time)
        await callback.message.answer("🧹 Очистил периоды. Введи начало занятости заново, например <code>09:00</code>")
        await callback.answer()
        return

    if action == "cancel":
        await state.clear()
        await callback.message.answer("🐾 Ок, добавление графика отменено.", reply_markup=main_menu(user.role))
        await callback.answer()
        return

    if action != "save":
        await callback.answer()
        return

    periods = list(data.get("periods") or [])
    if not periods:
        await callback.message.answer("🐾 Пока нет периодов. Добавь хотя бы одно время занятости.")
        await callback.answer()
        return

    day = datetime.fromisoformat(data["day"])
    schedule_type = data.get("schedule_type")
    source = ScheduleSource.REPLACEMENT if schedule_type == "replacement" else ScheduleSource.MANUAL
    if source == ScheduleSource.REPLACEMENT and user.role != Role.KOT:
        await callback.message.answer("🐾 Замены доступны только Коту.")
        await state.clear()
        await callback.answer()
        return

    for idx, p in enumerate(periods):
        start = datetime.fromisoformat(p["start"])
        end = datetime.fromisoformat(p["end"])
        status = ScheduleStatus.NIGHT_SHIFT if end.date() > start.date() or schedule_type == "night_shift" else ScheduleStatus.WORK_SHIFT
        title = "Замена" if schedule_type == "replacement" else ("Ночная смена" if status == ScheduleStatus.NIGHT_SHIFT else "Рабочий день")
        await add_schedule_entry(
            session,
            user,
            day,
            status,
            title,
            start_at=start,
            end_at=end,
            comment="Период занятости" if len(periods) > 1 else None,
            source_type=source,
            replace_day=(idx == 0),  # при сохранении день перезаписывается целиком, дальше добавляются периоды
        )

    await state.clear()
    title = "🔁 Замена сохранена" if source == ScheduleSource.REPLACEMENT else "📅 График сохранён"
    await _send_saved_result(callback.message, session, user, day, title)
    await callback.answer()


@router.callback_query(F.data.startswith("schedule_view:"))
async def schedule_view_day(callback: CallbackQuery, session: AsyncSession) -> None:
    user = await get_user_by_tg(session, callback.from_user.id)
    if not user:
        await callback.message.answer("🐾 Сначала нажми /start.")
        await callback.answer()
        return
    day = _parse_day_iso(callback.data.split(":", 1)[1])
    text = await _show_schedule_day(session, user, day)
    await callback.message.answer(text, reply_markup=schedule_result_keyboard(_day_iso(day)))
    await callback.answer()


@router.callback_query(F.data.startswith("schedule_edit:"))
async def schedule_edit_day(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    user = await get_user_by_tg(session, callback.from_user.id)
    if not user:
        await callback.message.answer("🐾 Сначала нажми /start.")
        await callback.answer()
        return
    day_iso = callback.data.split(":", 1)[1]
    await state.clear()
    await state.update_data(edit_day=day_iso)
    await state.set_state(AddSchedule.choose_type)
    await callback.message.answer(
        f"✏️ Редактируем график на <b>{fmt_date(_parse_day_iso(day_iso))}</b>.\n\n"
        "Выбери новый формат дня. Старый график на эту дату будет заменён.",
        reply_markup=schedule_type_keyboard(user.role),
    )
    await callback.answer()


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


@router.message(F.text.in_({"🔎 Шансы для обмена", "🔁 Возможные обмены"}))
async def exchange_candidates(message: Message, session: AsyncSession) -> None:
    user = await get_user_by_tg(session, message.from_user.id)
    if not user:
        await message.answer("🐾 Сначала нажми /start.")
        return

    if user.role != Role.KOT:
        await message.answer(
            "🐾 Шансы для обмена нужны Коту, потому что у него сменный график 2/2.\n"
            "У Котика график меняется через 📅 График, без отдельной вкладки замен.",
            reply_markup=main_menu(user.role),
        )
        return

    await find_exchange_candidates(session, days_ahead=14)
    suggestions = await list_exchange_suggestions(session, limit=10)

    if not suggestions:
        await message.answer(
            "🔎 Пока не нашёл очевидных шансов для обмена.\n\n"
            "<b>Чем отличается от “Замены”?</b>\n"
            "🔁 Замены — ты уже поменял график, и бот фиксирует факт.\n"
            "🔎 Шансы для обмена — бот просто ищет даты, где ты работаешь, а Котик свободна, и мягко предлагает подумать.\n\n"
            "Сейчас всё спокойно: либо у котиков уже есть время, либо нужно чуть дополнить график 🐾"
        )
        return

    text = (
        "🔎 <b>Шансы для обмена смены</b>\n\n"
        "Подсказка:\n"
        "🔁 <b>Замены</b> — когда обмен уже случился, и нужно обновить график.\n"
        "🔎 <b>Шансы</b> — когда бот заметил потенциальный день для обмена, но без давления.\n\n"
    )
    for s in suggestions:
        text += (
            f"📅 {s.target_date:%d.%m.%Y}\n"
            f"🐱 Кот работает: {s.kot_shift_start:%H:%M}–{s.kot_shift_end:%H:%M}\n"
            f"🐾 Котик свободна: {s.potential_shared_time}\n"
            "Можно подумать об обмене, если это легко и без напряга 💞\n\n"
        )
    await message.answer(text)
