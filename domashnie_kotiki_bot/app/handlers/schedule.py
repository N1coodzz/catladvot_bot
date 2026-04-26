from __future__ import annotations

from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards import (
    cancel_back_keyboard,
    irregular_count_keyboard,
    main_menu,
    schedule_menu_keyboard,
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
from app.services.users import get_pair, get_user_by_tg
from app.utils import fmt_date, now_msk, parse_date_ru, parse_time_hhmm, role_label, schedule_status_label

router = Router()


class AddSchedule(StatesGroup):
    choose_type = State()
    date = State()
    irregular_count = State()
    start_time = State()
    end_time = State()
    after_period = State()


def _day_iso(day: datetime) -> str:
    return day.strftime("%Y-%m-%d")


def _parse_day_iso(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d")


def _day_start(day: datetime) -> datetime:
    return datetime(day.year, day.month, day.day)


def _periods_text(periods: list[dict]) -> str:
    if not periods:
        return "пока нет периодов"
    parts = []
    for idx, p in enumerate(periods, 1):
        start = datetime.fromisoformat(p["start"])
        end = datetime.fromisoformat(p["end"])
        plus = " (+1 день)" if end.date() > start.date() else ""
        parts.append(f"{idx}) {start:%H:%M}–{end:%H:%M}{plus}")
    return "\n".join(parts)


def _entry_period_text(entry) -> str:
    if entry.start_at and entry.end_at:
        text = f"{entry.start_at:%H:%M}–{entry.end_at:%H:%M}"
        if entry.end_at.date() > entry.start_at.date():
            text += " (+1 день)"
        return text
    return "весь день"


async def _user_day_block(session: AsyncSession, user, day: datetime) -> str:
    entries = await list_entries_for_day(session, user, day)
    text = f"<b>{role_label(user.role)}</b>\n"

    if not entries:
        text += "   ❓ график не заполнен\n"
    else:
        for e in entries:
            source = " · 🔁 замена" if e.source_type == ScheduleSource.REPLACEMENT else ""
            text += f"   {schedule_status_label(e.status_type)} · {_entry_period_text(e)}{source}\n"
            if e.comment:
                text += f"   💬 {e.comment}\n"

    free = await free_intervals_for_day(session, user, day)
    if free is None:
        text += "   🕊 свободно: нужно заполнить график\n"
    elif free:
        text += f"   🕊 свободно: <b>{format_intervals(free)}</b>\n"
    else:
        text += "   🕊 свободно: почти нет\n"
    return text


async def _show_schedule_day(session: AsyncSession, user, day: datetime) -> str:
    text = f"📅 <b>График: {role_label(user.role)} — {fmt_date(day)}</b>\n\n"
    text += await _user_day_block(session, user, day)

    shared = await shared_free_intervals(session, day)
    text += "\n"
    if shared is None:
        text += "💞 Общее время: пока не хватает графика второго котика.\n"
    elif shared:
        text += f"💞 Общее время котиков: <b>{format_intervals(shared)}</b>\n"
    else:
        text += "💞 Общее время котиков: почти нет общего окна.\n"
    return text


async def _show_common_schedule(session: AsyncSession, days: int = 7) -> str:
    kot, kotik = await get_pair(session)
    if not kot or not kotik:
        return "🐾 Для общего графика нужны оба пользователя: Кот и Котик."

    today = _day_start(now_msk())
    text = "👥 <b>Общий график котиков</b>\n\n"
    text += "Здесь видно, кто занят, кто свободен и где есть общее окошко 💞\n\n"

    for offset in range(days):
        day = today + timedelta(days=offset)
        shared = await shared_free_intervals(session, day)
        if shared is None:
            shared_text = "❓ не хватает графика"
        elif shared:
            shared_text = f"💞 {format_intervals(shared)}"
        else:
            shared_text = "— общего окна почти нет"

        text += f"━━━━━━━━━━━━━━\n📅 <b>{day:%d.%m.%Y}</b>\n"
        text += await _user_day_block(session, kot, day)
        text += await _user_day_block(session, kotik, day)
        text += f"<b>Итог:</b> {shared_text}\n\n"

    return text


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


async def _send_saved_result(message: Message, session: AsyncSession, user, day: datetime, title: str) -> None:
    text = await _show_schedule_day(session, user, day)
    await message.answer(
        f"{title}\n\n{text}\n🐾 Если что-то не так — можно сразу отредактировать этот день.",
        reply_markup=schedule_result_keyboard(_day_iso(day)),
    )
    await message.answer("📅 Вернула тебя в раздел графика", reply_markup=schedule_menu_keyboard(user.role))


def _schedule_type_title(role: Role, raw: str) -> str:
    if raw == "night_shift":
        return "🌙 Ночная смена"
    if raw == "irregular":
        return "🌀 Ненормированный день"
    if raw == "replacement":
        return "🔁 Замена"
    if raw == "free":
        return "💤 Выходной"
    return "💼 Рабочая смена" if role == Role.KOT else "💼 Рабочий день"


async def _continue_after_date(message: Message, state: FSMContext, session: AsyncSession, user, day: datetime) -> None:
    data = await state.get_data()
    schedule_type = data.get("schedule_type")

    if schedule_type == "free":
        await _save_quick_day(
            session,
            user,
            day,
            ScheduleStatus.FREE,
            "Выходной",
            comment="Полностью свободный день",
            source_type=ScheduleSource.MANUAL,
        )
        await state.clear()
        await _send_saved_result(message, session, user, day, f"💤 Записал выходной на {fmt_date(day)}")
        return

    if schedule_type == "irregular":
        await state.set_state(AddSchedule.irregular_count)
        await message.answer(
            "🌀 <b>Ненормированный день</b>\n\n"
            "Напиши, сколько периодов занятости будет в этот день, или выбери кнопку.\n"
            "Например: если Котик занята 09:00–11:00, 13:00–15:00 и 18:00–19:00 — это 3 периода.",
            reply_markup=irregular_count_keyboard(),
        )
        return

    # Рабочий день/смена/замена: вводим первый период занятости.
    default_target = 1 if (user.role == Role.KOTIK and schedule_type == "work_day") else None
    await state.update_data(periods=[], target_periods=default_target, current_period=1)
    await state.set_state(AddSchedule.start_time)

    if schedule_type == "replacement":
        await message.answer(
            "🔁 <b>Замена Кота</b> — фиксируем уже случившееся изменение графика.\n\n"
            "Если день стал выходным — напиши <code>выходной</code>.\n"
            "Если появилась смена — введи начало занятости, например <code>08:00</code>.",
            reply_markup=cancel_back_keyboard(),
        )
    else:
        await message.answer(
            f"{_schedule_type_title(user.role, schedule_type)}\n\n"
            "Введи время начала занятости. Пример: <code>09:00</code>",
            reply_markup=cancel_back_keyboard(),
        )


async def _save_periods(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    user = await get_user_by_tg(session, message.chat.id)
    if not user:
        await message.answer("🐾 Сначала нажми /start.")
        await state.clear()
        return

    periods = list(data.get("periods") or [])
    if not periods:
        await message.answer("🐾 Пока нет периодов. Добавь хотя бы одно время занятости.")
        return

    day = datetime.fromisoformat(data["day"])
    schedule_type = data.get("schedule_type")
    source = ScheduleSource.REPLACEMENT if schedule_type == "replacement" else ScheduleSource.MANUAL

    if source == ScheduleSource.REPLACEMENT and user.role != Role.KOT:
        await message.answer("🐾 Замены доступны только Коту.")
        await state.clear()
        return

    for idx, p in enumerate(periods):
        start = datetime.fromisoformat(p["start"])
        end = datetime.fromisoformat(p["end"])
        if schedule_type == "night_shift" or end.date() > start.date():
            status = ScheduleStatus.NIGHT_SHIFT
        else:
            status = ScheduleStatus.WORK_SHIFT if schedule_type != "irregular" else ScheduleStatus.IRREGULAR
        title = _schedule_type_title(user.role, schedule_type)
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
            replace_day=(idx == 0),
        )

    await state.clear()
    title = "🔁 Замена сохранена" if source == ScheduleSource.REPLACEMENT else "📅 График сохранён"
    await _send_saved_result(message, session, user, day, title)


@router.message(F.text.in_({"📅 График", "/schedule"}))
async def schedule_menu(message: Message, session: AsyncSession, state: FSMContext) -> None:
    user = await get_user_by_tg(session, message.from_user.id)
    if not user:
        await message.answer("🐾 Сначала нажми /start.")
        return

    await state.clear()
    hint = (
        "🐱 У Кота здесь смены 2/2, ночи, замены и шансы для обмена."
        if user.role == Role.KOT
        else "🐾 У Котика график проще: рабочий день, выходной или ненормированный день с несколькими периодами занятости."
    )
    await message.answer(
        f"📅 <b>График</b>\n\n{hint}\n\nВыбери, что хочешь сделать:",
        reply_markup=schedule_menu_keyboard(user.role),
    )


@router.message(F.text == "➕ Добавить мой день")
async def add_my_schedule_day(message: Message, session: AsyncSession, state: FSMContext) -> None:
    user = await get_user_by_tg(session, message.from_user.id)
    if not user:
        await message.answer("🐾 Сначала нажми /start.")
        return
    await state.clear()
    await state.set_state(AddSchedule.choose_type)
    await message.answer(
        f"📅 <b>{role_label(user.role)}, какой день добавляем?</b>\n\n"
        "Сначала выбираем тип дня, потом дату и время. Если ошибся — будет кнопка назад/отмена.",
        reply_markup=schedule_type_keyboard(user.role),
    )


@router.message(F.text == "👀 Мой график")
async def my_schedule(message: Message, session: AsyncSession) -> None:
    user = await get_user_by_tg(session, message.from_user.id)
    if not user:
        await message.answer("🐾 Сначала нажми /start.")
        return

    today = _day_start(now_msk())
    text = f"👀 <b>Мой график: {role_label(user.role)}</b>\n\n"
    for offset in range(7):
        day = today + timedelta(days=offset)
        text += f"━━━━━━━━━━━━━━\n📅 <b>{day:%d.%m}</b>\n"
        text += await _user_day_block(session, user, day)
    await message.answer(text, reply_markup=schedule_menu_keyboard(user.role))


@router.message(F.text == "👥 Общий график")
async def common_schedule(message: Message, session: AsyncSession) -> None:
    user = await get_user_by_tg(session, message.from_user.id)
    text = await _show_common_schedule(session, days=7)
    # Telegram ограничивает длину сообщения. Отправляем аккуратными частями, если график получился длинным.
    if len(text) <= 3900:
        await message.answer(text, reply_markup=schedule_menu_keyboard(user.role if user else None))
        return

    chunks = text.split("━━━━━━━━━━━━━━")
    current = chunks[0]
    for chunk in chunks[1:]:
        part = "━━━━━━━━━━━━━━" + chunk
        if len(current) + len(part) > 3800:
            await message.answer(current)
            current = part
        else:
            current += part
    if current:
        await message.answer(current, reply_markup=schedule_menu_keyboard(user.role if user else None))


@router.message(F.text == "🔁 Замены")
async def replacement_menu(message: Message, session: AsyncSession, state: FSMContext) -> None:
    user = await get_user_by_tg(session, message.from_user.id)
    if not user:
        await message.answer("🐾 Сначала нажми /start.")
        return

    if user.role != Role.KOT:
        await message.answer(
            "🐾 У Котика нет замен: её график меняется через обычный 📅 График.\n"
            "Если день сложный — выбирай 🌀 Ненормированный день и добавляй периоды занятости.",
            reply_markup=schedule_menu_keyboard(user.role),
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
        "📅 Введи дату, которую нужно заменить: <code>15.05</code> или <code>15.05.2026</code>",
        reply_markup=cancel_back_keyboard(),
    )


@router.callback_query(AddSchedule.choose_type, F.data.startswith("schedule_type:"))
async def schedule_type(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    raw = callback.data.split(":", 1)[1]
    user = await get_user_by_tg(session, callback.from_user.id)
    if not user:
        await callback.message.answer("🐾 Сначала нажми /start.")
        await callback.answer()
        return

    if raw == "back":
        await state.clear()
        await callback.message.answer("📅 Вернула раздел графика", reply_markup=schedule_menu_keyboard(user.role))
        await callback.answer()
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
        "📅 Введи дату в формате <code>15.05</code> или <code>15.05.2026</code>.",
        reply_markup=cancel_back_keyboard(),
    )
    await callback.answer()


@router.message(AddSchedule.date)
async def schedule_date(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if message.text in {"❌ Отмена", "⬅️ Назад", "🏡 Главное меню"}:
        user = await get_user_by_tg(session, message.from_user.id)
        await state.clear()
        await message.answer("📅 Вернула раздел графика", reply_markup=schedule_menu_keyboard(user.role if user else None))
        return

    day = parse_date_ru(message.text)
    if not day:
        await message.answer("🐾 Не понял дату. Пример: <code>15.05</code>")
        return

    user = await get_user_by_tg(session, message.from_user.id)
    if not user:
        await message.answer("🐾 Сначала нажми /start.")
        return

    day = _day_start(day)
    await state.update_data(day=day.isoformat())
    await _continue_after_date(message, state, session, user, day)


@router.callback_query(AddSchedule.irregular_count, F.data.startswith("irregular_count:"))
async def irregular_count_callback(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    value = callback.data.split(":", 1)[1]
    user = await get_user_by_tg(session, callback.from_user.id)
    if value == "back":
        await state.set_state(AddSchedule.choose_type)
        await callback.message.answer("Выбери тип дня заново:", reply_markup=schedule_type_keyboard(user.role if user else Role.KOTIK))
        await callback.answer()
        return
    if value == "manual":
        await callback.message.answer("✍️ Напиши число периодов занятости. Например: <code>4</code>")
        await callback.answer()
        return
    count = int(value)
    await state.update_data(periods=[], target_periods=count, current_period=1)
    await state.set_state(AddSchedule.start_time)
    await callback.message.answer(
        f"🌀 Записала {count} период(а/ов).\n\n"
        f"Период 1 из {count}: введи начало занятости, например <code>09:00</code>",
        reply_markup=cancel_back_keyboard(),
    )
    await callback.answer()


@router.message(AddSchedule.irregular_count)
async def irregular_count_text(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if message.text in {"❌ Отмена", "⬅️ Назад", "🏡 Главное меню"}:
        user = await get_user_by_tg(session, message.from_user.id)
        await state.clear()
        await message.answer("📅 Вернула раздел графика", reply_markup=schedule_menu_keyboard(user.role if user else None))
        return
    try:
        count = int(message.text.strip())
    except ValueError:
        await message.answer("🐾 Напиши число. Например: <code>4</code>")
        return
    if count < 1 or count > 8:
        await message.answer("🐾 Давай от 1 до 8 периодов, чтобы график оставался понятным.")
        return
    await state.update_data(periods=[], target_periods=count, current_period=1)
    await state.set_state(AddSchedule.start_time)
    await message.answer(
        f"🌀 Окей, будет {count} период(а/ов).\n\n"
        f"Период 1 из {count}: введи начало занятости, например <code>09:00</code>",
        reply_markup=cancel_back_keyboard(),
    )


@router.message(AddSchedule.start_time)
async def schedule_start_time(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    schedule_type = data.get("schedule_type")
    text = message.text.strip().lower()

    if text in {"❌ отмена", "отмена", "⬅️ назад", "назад", "🏡 главное меню"} or message.text in {"❌ Отмена", "⬅️ Назад", "🏡 Главное меню"}:
        user = await get_user_by_tg(session, message.from_user.id)
        await state.clear()
        await message.answer("📅 Вернула раздел графика", reply_markup=schedule_menu_keyboard(user.role if user else None))
        return

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
    target = data.get("target_periods")
    current = data.get("current_period", 1)
    prefix = f"Период {current} из {target}. " if target else ""
    await message.answer(
        f"{prefix}Теперь введи время окончания этого периода.\n\n"
        "Пример: <code>20:00</code>. Если конец меньше начала, я пойму это как переход на следующий день.",
        reply_markup=cancel_back_keyboard(),
    )


@router.message(AddSchedule.end_time)
async def schedule_end_time(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if message.text in {"❌ Отмена", "⬅️ Назад", "🏡 Главное меню"}:
        await state.set_state(AddSchedule.start_time)
        await message.answer("Окей, вернулась к началу периода. Введи начало занятости ещё раз.", reply_markup=cancel_back_keyboard())
        return

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
    target = data.get("target_periods")
    current = int(data.get("current_period", 1))
    await state.update_data(periods=periods)

    if target and current >= int(target):
        await message.answer(
            "✅ Все периоды добавлены. Сохраняю день.\n\n"
            f"<b>Итоговая занятость:</b>\n{_periods_text(periods)}"
        )
        await _save_periods(message, state, session)
        return

    if target:
        await state.update_data(current_period=current + 1)
        await state.set_state(AddSchedule.start_time)
        await message.answer(
            f"✅ Период {current} добавлен.\n\n"
            f"<b>Уже записано:</b>\n{_periods_text(periods)}\n\n"
            f"Период {current + 1} из {target}: введи начало занятости.",
            reply_markup=cancel_back_keyboard(),
        )
        return

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
    user = await get_user_by_tg(session, callback.from_user.id)
    if not user:
        await callback.message.answer("🐾 Сначала нажми /start.")
        await callback.answer()
        return

    if action == "add":
        await state.set_state(AddSchedule.start_time)
        await callback.message.answer("➕ Введи начало следующего периода занятости, например <code>15:00</code>", reply_markup=cancel_back_keyboard())
        await callback.answer()
        return

    if action == "clear":
        await state.update_data(periods=[])
        await state.set_state(AddSchedule.start_time)
        await callback.message.answer("🧹 Очистил периоды. Введи начало занятости заново, например <code>09:00</code>", reply_markup=cancel_back_keyboard())
        await callback.answer()
        return

    if action == "cancel":
        await state.clear()
        await callback.message.answer("🐾 Ок, добавление графика отменено.", reply_markup=schedule_menu_keyboard(user.role))
        await callback.answer()
        return

    if action == "save":
        await _save_periods(callback.message, state, session)
        await callback.answer()
        return

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
        day = _day_start(now) + timedelta(days=offset)
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
            reply_markup=schedule_menu_keyboard(user.role),
        )
        return

    await find_exchange_candidates(session, days_ahead=14)
    suggestions = await list_exchange_suggestions(session, limit=10)

    if not suggestions:
        await message.answer(
            "🔎 Пока не нашёл очевидных шансов для обмена.\n\n"
            "<b>Чем отличается от “Замены”?</b>\n"
            "🔁 <b>Замены</b> — обмен уже случился, и бот фиксирует новый график.\n"
            "🔎 <b>Шансы</b> — бот только замечает день, где Кот работает, а Котик свободна.\n\n"
            "Сейчас всё спокойно: либо у котиков уже есть время, либо нужно чуть дополнить график 🐾",
            reply_markup=schedule_menu_keyboard(user.role),
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
    await message.answer(text, reply_markup=schedule_menu_keyboard(user.role))
