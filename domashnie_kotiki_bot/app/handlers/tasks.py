from __future__ import annotations

from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards import (
    assignee_keyboard,
    deadline_keyboard,
    discussion_actions_keyboard,
    discussion_reason_keyboard,
    main_menu,
    points_keyboard,
    task_actions_keyboard,
    task_review_keyboard,
    yes_no_comment_keyboard,
)
from app.models import CommentType, Role, Task, TaskStatus, User
from app.services.messages import task_card
from app.services.tasks import (
    add_comment,
    cancel_task,
    change_task_points,
    count_task,
    create_task,
    get_task,
    list_active_tasks,
    list_discussion_tasks,
    list_done_tasks,
    mark_done_and_add_points,
    revoke_task_points,
    set_task_status,
)
from app.services.users import get_all_users, get_user_by_role, get_user_by_tg
from app.utils import now_msk, parse_date_ru, role_label


router = Router()


class CreateTask(StatesGroup):
    title = State()
    assignee = State()
    points = State()
    manual_points = State()
    deadline = State()
    manual_deadline = State()
    comment_choice = State()
    comment = State()


class DiscussTask(StatesGroup):
    text = State()


async def _other_users(session: AsyncSession, actor_tg_id: int) -> list[User]:
    users = await get_all_users(session)
    return [u for u in users if u.telegram_id != actor_tg_id]


async def _notify_others(
    *,
    message_or_callback: Message | CallbackQuery,
    session: AsyncSession,
    actor_tg_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Синхронизирует изменения: отправляет сообщение второму котику.

    В боте всего два пользователя, поэтому надёжнее уведомлять всех зарегистрированных,
    кроме автора действия. Это покрывает задачи Кота, Котика и “Оба”.
    """
    bot = message_or_callback.bot
    for user in await _other_users(session, actor_tg_id):
        try:
            await bot.send_message(user.telegram_id, text, reply_markup=reply_markup)
        except Exception:
            # Не роняем основное действие, если Telegram временно не доставил сообщение.
            pass


async def _notify_task_created(
    message: Message,
    session: AsyncSession,
    creator: User,
    task: Task,
) -> None:
    # Если задача назначена конкретно на автора — дополнительно никого не дёргаем.
    if task.assignee_id == creator.id:
        return

    text = (
        f"🐾 {role_label(creator.role)} добавил новую бытовую задачу:\n\n"
        f"{task_card(task)}\n\n"
        "Задача синхронизирована в общем домике 🏡"
    )

    # Для конкретного партнёра и для “Оба” хватает уведомить второго пользователя.
    await _notify_others(
        message_or_callback=message,
        session=session,
        actor_tg_id=creator.telegram_id,
        text=text,
        reply_markup=task_actions_keyboard(task.id),
    )


@router.message(F.text == "➕ Создать задачу")
async def start_task_creation(message: Message, state: FSMContext, session: AsyncSession) -> None:
    user = await get_user_by_tg(session, message.from_user.id)
    if not user:
        await message.answer("🐾 Сначала нажми /start и выбери роль.")
        return

    await state.clear()
    await state.set_state(CreateTask.title)
    await message.answer("📝 Напиши задачу, которую нужно выполнить")


@router.message(CreateTask.title)
async def task_title(message: Message, state: FSMContext) -> None:
    title = message.text.strip()
    if len(title) < 2:
        await message.answer("🐾 Задача слишком короткая. Напиши чуть подробнее.")
        return

    await state.update_data(title=title)
    await state.set_state(CreateTask.assignee)
    await message.answer("🐾 Кому назначить задачу?", reply_markup=assignee_keyboard())


@router.callback_query(CreateTask.assignee, F.data.startswith("task_assignee:"))
async def task_assignee(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":", 1)[1]
    await state.update_data(assignee=value)
    await state.set_state(CreateTask.points)
    await callback.message.answer("⭐ Сколько звёздочек дать за задачу?", reply_markup=points_keyboard())
    await callback.answer()


@router.callback_query(CreateTask.points, F.data.startswith("task_points:"))
async def task_points(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":", 1)[1]
    if value == "manual":
        await state.set_state(CreateTask.manual_points)
        await callback.message.answer("✍️ Введи количество звёздочек числом")
        await callback.answer()
        return

    await state.update_data(points=int(value))
    await state.set_state(CreateTask.deadline)
    await callback.message.answer("⏰ Когда нужно выполнить?", reply_markup=deadline_keyboard())
    await callback.answer()


@router.message(CreateTask.manual_points)
async def task_manual_points(message: Message, state: FSMContext) -> None:
    try:
        points = int(message.text.strip())
    except ValueError:
        await message.answer("🐾 Нужно ввести число. Например: 4")
        return

    if points < 0 or points > 100:
        await message.answer("🐾 Давай от 0 до 100 звёздочек, чтобы бытовая магия была честной.")
        return

    await state.update_data(points=points)
    await state.set_state(CreateTask.deadline)
    await message.answer("⏰ Когда нужно выполнить?", reply_markup=deadline_keyboard())


@router.callback_query(CreateTask.deadline, F.data.startswith("task_deadline:"))
async def task_deadline(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":", 1)[1]
    now = now_msk()
    deadline = None

    if value == "today":
        deadline = datetime(now.year, now.month, now.day, 23, 59)
    elif value == "tomorrow":
        t = now + timedelta(days=1)
        deadline = datetime(t.year, t.month, t.day, 23, 59)
    elif value == "week":
        deadline = datetime(now.year, now.month, now.day, 23, 59) + timedelta(days=7)
    elif value == "manual":
        await state.set_state(CreateTask.manual_deadline)
        await callback.message.answer(
            "✍️ Введи дату и время в формате:\n"
            "<code>15.05 20:00</code>\n\n"
            "Можно и просто дату: <code>15.05</code>"
        )
        await callback.answer()
        return

    await state.update_data(deadline_at=deadline)
    await state.set_state(CreateTask.comment_choice)
    await callback.message.answer("💬 Хочешь добавить комментарий к задаче?", reply_markup=yes_no_comment_keyboard())
    await callback.answer()


@router.message(CreateTask.manual_deadline)
async def task_manual_deadline(message: Message, state: FSMContext) -> None:
    deadline = parse_date_ru(message.text)
    if not deadline:
        await message.answer("🐾 Не понял дату. Пример: <code>15.05 20:00</code>")
        return

    if deadline.hour == 0 and deadline.minute == 0:
        deadline = deadline.replace(hour=23, minute=59)

    await state.update_data(deadline_at=deadline)
    await state.set_state(CreateTask.comment_choice)
    await message.answer("💬 Хочешь добавить комментарий к задаче?", reply_markup=yes_no_comment_keyboard())


@router.callback_query(CreateTask.comment_choice, F.data.startswith("task_comment:"))
async def task_comment_choice(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    value = callback.data.split(":", 1)[1]
    if value == "yes":
        await state.set_state(CreateTask.comment)
        await callback.message.answer("💬 Напиши комментарий")
        await callback.answer()
        return

    await finish_create_task(callback.message, state, session, callback.from_user.id, None)
    await callback.answer()


@router.message(CreateTask.comment)
async def task_comment_text(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await finish_create_task(message, state, session, message.from_user.id, message.text.strip())


async def finish_create_task(message: Message, state: FSMContext, session: AsyncSession, telegram_id: int, comment: str | None) -> None:
    creator = await get_user_by_tg(session, telegram_id)
    if not creator:
        await message.answer("🐾 Сначала нажми /start.")
        return

    data = await state.get_data()
    assignee_raw = data["assignee"]
    assignee = None

    if assignee_raw == "kot":
        assignee = await get_user_by_role(session, Role.KOT)
    elif assignee_raw == "kotik":
        assignee = await get_user_by_role(session, Role.KOTIK)
    # assignee_raw == "both" => assignee=None, это задача для обоих.

    task = await create_task(
        session=session,
        creator=creator,
        assignee=assignee,
        title=data["title"],
        points=data["points"],
        deadline_at=data.get("deadline_at"),
        description=comment,
    )
    if comment:
        await add_comment(session, task, creator, comment, CommentType.NORMAL)
        task = await get_task(session, task.id) or task

    await state.clear()
    await message.answer(
        "🏡 <b>Новая задача создана!</b>\n\n"
        f"{task_card(task)}\n\n"
        "Пусть бытовые дела закрываются легко 😽",
        reply_markup=main_menu(),
    )
    await _notify_task_created(message, session, creator, task)


@router.message(F.text.in_({"📋 Мои задачи", "/tasks"}))
async def my_tasks(message: Message, session: AsyncSession) -> None:
    user = await get_user_by_tg(session, message.from_user.id)
    if not user:
        await message.answer("🐾 Сначала нажми /start.")
        return

    tasks = await list_active_tasks(session, assignee_id=user.id)
    if not tasks:
        await message.answer("🐾 У тебя пока нет активных задач. Можно выдохнуть или создать новую ⭐")
        return

    await message.answer("📋 <b>Твои активные задачи:</b>")
    for task in tasks[:10]:
        await message.answer(task_card(task), reply_markup=task_actions_keyboard(task.id))


@router.message(F.text == "🏠 Все задачи")
async def all_tasks(message: Message, session: AsyncSession) -> None:
    tasks = await list_active_tasks(session)
    if not tasks:
        await message.answer("🏡 Активных задач пока нет. В домике спокойно 🐾")
        return

    await message.answer("🏠 <b>Все активные задачи:</b>")
    for task in tasks[:15]:
        await message.answer(task_card(task), reply_markup=task_actions_keyboard(task.id))


@router.message(F.text == "✅ Выполненные")
async def done_tasks(message: Message, session: AsyncSession) -> None:
    tasks = await list_done_tasks(session)
    if not tasks:
        await message.answer("✅ Выполненных задач пока нет, но звёздочки уже где-то рядом ⭐")
        return

    await message.answer("✅ <b>Выполненные задачи:</b>")
    for task in tasks[:15]:
        await message.answer(task_card(task))


@router.message(F.text == "💬 Обсуждения")
async def discussion_tasks(message: Message, session: AsyncSession) -> None:
    tasks = await list_discussion_tasks(session)
    if not tasks:
        await message.answer("💬 Сейчас нет задач на обсуждении. Котики договорились 🐾")
        return

    await message.answer("💬 <b>Задачи на обсуждении:</b>")
    for task in tasks[:15]:
        await message.answer(task_card(task), reply_markup=discussion_actions_keyboard(task.id))


@router.callback_query(F.data.startswith("task_action:"))
async def task_action(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    _, action, task_id_raw = callback.data.split(":")
    task = await get_task(session, int(task_id_raw))
    user = await get_user_by_tg(session, callback.from_user.id)
    if not task or not user:
        await callback.answer("Не нашёл задачу 🐾", show_alert=True)
        return

    if action == "progress":
        task = await set_task_status(session, task, TaskStatus.IN_PROGRESS)
        await callback.message.edit_text(task_card(task), reply_markup=task_actions_keyboard(task.id))
        await _notify_others(
            message_or_callback=callback,
            session=session,
            actor_tg_id=callback.from_user.id,
            text=f"🔄 {role_label(user.role)} взял задачу в работу:\n\n{task_card(task)}",
            reply_markup=task_actions_keyboard(task.id),
        )
        await callback.answer("Задача в работе 🐾")
        return

    if action == "done":
        task = await mark_done_and_add_points(session, task)
        await callback.message.answer(
            "✅ Задача отмечена как выполненная!\n"
            "Звёздочки начислены ⭐\n"
            "Если у второго котика будет нюанс, он сможет мягко обсудить задачу."
        )

        await _notify_others(
            message_or_callback=callback,
            session=session,
            actor_tg_id=callback.from_user.id,
            text=(
                f"🐾 {role_label(user.role)} отметил задачу выполненной:\n\n"
                f"{task_card(task)}\n\n"
                "Всё хорошо?"
            ),
            reply_markup=task_review_keyboard(task.id),
        )
        await callback.answer()
        return

    if action == "discuss":
        await state.update_data(task_id=task.id, discuss_reason="comment")
        await state.set_state(DiscussTask.text)
        await callback.message.answer("💬 Напиши, что хочется уточнить по задаче.\nБез ссор — просто чтобы котики поняли друг друга 🐾")
        await callback.answer()
        return

    if action == "cancel":
        task = await cancel_task(session, task, remove_points=True)
        await callback.message.edit_text(f"{task_card(task)}\n\n🕊 Задача закрыта как неактуальная.")
        await _notify_others(
            message_or_callback=callback,
            session=session,
            actor_tg_id=callback.from_user.id,
            text=f"🕊 {role_label(user.role)} закрыл задачу как неактуальную:\n\n{task_card(task)}",
        )
        await callback.answer("Задача отменена 🐾")


@router.callback_query(F.data.startswith("task_review:"))
async def task_review(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    _, action, task_id_raw = callback.data.split(":")
    task = await get_task(session, int(task_id_raw))
    user = await get_user_by_tg(session, callback.from_user.id)
    if not task or not user:
        await callback.answer("Не нашёл задачу 🐾", show_alert=True)
        return

    if action == "count":
        task = await count_task(session, task)
        await callback.message.edit_text(f"{task_card(task)}\n\n🟢 Задача засчитана. Домик стал уютнее 💞")
        await _notify_others(
            message_or_callback=callback,
            session=session,
            actor_tg_id=callback.from_user.id,
            text=f"🟢 {role_label(user.role)} засчитал задачу:\n\n{task_card(task)}\n\nБаллы синхронизированы ⭐",
        )
        await callback.answer("Засчитано ⭐")
        return

    if action == "rework":
        await revoke_task_points(session, task, "Задача вернулась на доработку / баллы временно сняты")
        task = await set_task_status(session, task, TaskStatus.REWORK)
        await callback.message.edit_text(
            f"{task_card(task)}\n\n🔄 Задача вернулась на доработку. Почти готово, осталось чуть-чуть 🐾"
        )
        await _notify_others(
            message_or_callback=callback,
            session=session,
            actor_tg_id=callback.from_user.id,
            text=(
                f"🔄 {role_label(user.role)} вернул задачу на доработку:\n\n"
                f"{task_card(task)}\n\n"
                "Баллы временно синхронизированы и вернутся после выполнения ⭐"
            ),
            reply_markup=task_actions_keyboard(task.id),
        )
        await callback.answer()
        return

    if action == "discuss":
        await callback.message.answer("🐾 Что хочется уточнить по задаче?", reply_markup=discussion_reason_keyboard(task.id))
        await callback.answer()
        return


@router.callback_query(F.data.startswith("discuss_reason:"))
async def discussion_reason(callback: CallbackQuery, state: FSMContext) -> None:
    _, reason, task_id_raw = callback.data.split(":")
    await state.update_data(task_id=int(task_id_raw), discuss_reason=reason)
    await state.set_state(DiscussTask.text)
    if reason == "points":
        await callback.message.answer("⭐ Напиши новое количество баллов числом. Можно добавить комментарий после числа: <code>2, потому что задача лёгкая</code>")
    else:
        await callback.message.answer("💬 Напиши комментарий к задаче")
    await callback.answer()


@router.message(DiscussTask.text)
async def discussion_text(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    task = await get_task(session, int(data["task_id"]))
    author = await get_user_by_tg(session, message.from_user.id)
    if not task or not author:
        await message.answer("🐾 Не получилось найти задачу.")
        await state.clear()
        return

    reason = data.get("discuss_reason", "comment")
    text = message.text.strip()

    if reason == "rework":
        await revoke_task_points(session, task, "Задача ушла на доработку / баллы временно сняты")
        new_status = TaskStatus.REWORK
        comment_type = CommentType.REWORK
    elif reason == "points":
        parts = text.replace(",", " ").split()
        try:
            new_points = int(parts[0])
        except (ValueError, IndexError):
            await message.answer("🐾 Для изменения баллов начни сообщение с числа. Например: <code>2, задача полегче</code>")
            return
        if new_points < 0 or new_points > 100:
            await message.answer("🐾 Давай от 0 до 100 звёздочек.")
            return
        task = await change_task_points(session, task, new_points, f"Баллы изменены через обсуждение: {text}")
        new_status = TaskStatus.POINTS_REVIEW
        comment_type = CommentType.POINTS
    elif reason == "cancel":
        task = await cancel_task(session, task, remove_points=True)
        new_status = TaskStatus.CANCELLED
        comment_type = CommentType.DISCUSSION
    else:
        new_status = TaskStatus.DISCUSSION
        comment_type = CommentType.DISCUSSION

    await add_comment(session, task, author, text, comment_type)
    if reason != "cancel":
        task = await set_task_status(session, task, new_status)
    else:
        task = await get_task(session, task.id) or task

    await _notify_others(
        message_or_callback=message,
        session=session,
        actor_tg_id=message.from_user.id,
        text=(
            f"💬 {role_label(author.role)} хочет обсудить задачу\n\n"
            f"{task_card(task)}\n\n"
            f"💬 Комментарий: “{text}”\n\n"
            "Можно спокойно договориться — котики же команда 🐾"
        ),
        reply_markup=discussion_actions_keyboard(task.id),
    )

    await state.clear()
    await message.answer(
        "💬 Комментарий добавлен и синхронизирован со вторым котиком 🐾",
        reply_markup=main_menu(),
    )


@router.callback_query(F.data.startswith("discussion_action:"))
async def discussion_action(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    _, action, task_id_raw = callback.data.split(":")
    task = await get_task(session, int(task_id_raw))
    user = await get_user_by_tg(session, callback.from_user.id)
    if not task or not user:
        await callback.answer("Не нашёл задачу 🐾", show_alert=True)
        return

    if action in {"count", "close"}:
        task = await count_task(session, task)
        await callback.message.edit_text(f"{task_card(task)}\n\n🟢 Обсуждение закрыто, задача засчитана 💞")
        await _notify_others(
            message_or_callback=callback,
            session=session,
            actor_tg_id=callback.from_user.id,
            text=f"🟢 {role_label(user.role)} закрыл обсуждение:\n\n{task_card(task)}\n\nКотики договорились 💞",
        )
        await callback.answer()
        return

    if action == "rework":
        await revoke_task_points(session, task, "Задача вернулась на доработку / баллы временно сняты")
        task = await set_task_status(session, task, TaskStatus.REWORK)
        await callback.message.edit_text(f"{task_card(task)}\n\n🔄 Вернули на доработку. Без ссор, просто чуть поправить 🐾")
        await _notify_others(
            message_or_callback=callback,
            session=session,
            actor_tg_id=callback.from_user.id,
            text=(
                f"🔄 {role_label(user.role)} вернул задачу на доработку:\n\n"
                f"{task_card(task)}\n\n"
                "Баллы временно синхронизированы и вернутся после выполнения ⭐"
            ),
            reply_markup=task_actions_keyboard(task.id),
        )
        await callback.answer()
        return

    if action == "points":
        task = await set_task_status(session, task, TaskStatus.POINTS_REVIEW)
        await callback.message.answer("⭐ Напиши новое количество баллов числом. Например: <code>2, потому что задача полегче</code>")
        await state.update_data(task_id=task.id, discuss_reason="points")
        await state.set_state(DiscussTask.text)
        await callback.answer()
        return

    if action == "reply":
        await callback.message.answer("💬 Напиши ответ по задаче")
        await state.update_data(task_id=task.id, discuss_reason="comment")
        await state.set_state(DiscussTask.text)
        await callback.answer()
        return
