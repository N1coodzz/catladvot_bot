from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models import CommentType, PointsAction, PointsHistory, Task, TaskComment, TaskStatus, User
from app.utils import now_msk


_TASK_LOAD_OPTIONS = (selectinload(Task.creator), selectinload(Task.assignee))


async def create_task(
    session: AsyncSession,
    creator: User,
    assignee: User | None,
    title: str,
    points: int,
    deadline_at: datetime | None,
    description: str | None = None,
) -> Task:
    """
    assignee=None означает “👥 Оба”.
    В этом режиме задача показывается обоим пользователям, а баллы за выполнение получают оба.
    """
    now = now_msk()
    task = Task(
        title=title,
        description=description,
        creator_id=creator.id,
        assignee_id=assignee.id if assignee else None,
        points=points,
        deadline_at=deadline_at,
        status=TaskStatus.NEW,
        created_at=now,
        updated_at=now,
        is_deleted=False,
    )
    session.add(task)
    await session.commit()
    return await get_task(session, task.id)  # type: ignore[return-value]


async def get_task(session: AsyncSession, task_id: int) -> Task | None:
    result = await session.execute(
        select(Task)
        .options(*_TASK_LOAD_OPTIONS)
        .where(Task.id == task_id, Task.is_deleted.is_(False))
    )
    return result.scalar_one_or_none()


async def list_active_tasks(session: AsyncSession, assignee_id: int | None = None) -> list[Task]:
    q = (
        select(Task)
        .options(*_TASK_LOAD_OPTIONS)
        .where(
            Task.is_deleted.is_(False),
            Task.status.notin_([TaskStatus.COUNTED, TaskStatus.CANCELLED, TaskStatus.DELETED]),
        )
        .order_by(Task.deadline_at.is_(None), Task.deadline_at, Task.created_at.desc())
    )
    if assignee_id is not None:
        # assignee_id=None — задача для ОБОИХ, поэтому она должна быть в “Моих задачах” у каждого.
        q = q.where(or_(Task.assignee_id == assignee_id, Task.assignee_id.is_(None)))
    result = await session.execute(q)
    return list(result.scalars())


async def list_done_tasks(session: AsyncSession) -> list[Task]:
    result = await session.execute(
        select(Task)
        .options(*_TASK_LOAD_OPTIONS)
        .where(Task.is_deleted.is_(False), Task.status.in_([TaskStatus.DONE, TaskStatus.COUNTED]))
        .order_by(Task.completed_at.desc().nullslast())
    )
    return list(result.scalars())


async def list_discussion_tasks(session: AsyncSession) -> list[Task]:
    result = await session.execute(
        select(Task)
        .options(*_TASK_LOAD_OPTIONS)
        .where(
            Task.is_deleted.is_(False),
            Task.status.in_([TaskStatus.DISCUSSION, TaskStatus.REWORK, TaskStatus.POINTS_REVIEW]),
        )
        .order_by(Task.updated_at.desc())
    )
    return list(result.scalars())


async def list_today_tasks(session: AsyncSession, user_id: int | None = None) -> list[Task]:
    now = now_msk()
    start = datetime(now.year, now.month, now.day)
    end = start + timedelta(days=1)
    q = (
        select(Task)
        .options(*_TASK_LOAD_OPTIONS)
        .where(
            Task.is_deleted.is_(False),
            Task.status.notin_([TaskStatus.COUNTED, TaskStatus.CANCELLED, TaskStatus.DELETED]),
            Task.deadline_at >= start,
            Task.deadline_at < end,
        )
        .order_by(Task.deadline_at)
    )
    if user_id:
        q = q.where(or_(Task.assignee_id == user_id, Task.assignee_id.is_(None)))
    result = await session.execute(q)
    return list(result.scalars())


async def set_task_status(session: AsyncSession, task: Task, status: TaskStatus) -> Task:
    task.status = status
    task.updated_at = now_msk()
    await session.commit()
    return await get_task(session, task.id)  # type: ignore[return-value]


async def _point_recipient_ids(session: AsyncSession, task: Task) -> list[int]:
    """Кому начислять баллы за задачу."""
    if task.assignee_id is not None:
        return [task.assignee_id]

    # assignee_id=None значит “Оба”: баллы получает Кот и Котик.
    result = await session.execute(select(User.id).order_by(User.role))
    return [int(row[0]) for row in result.all()]


async def _task_points_net(session: AsyncSession, task_id: int, user_id: int) -> int:
    result = await session.execute(
        select(func.coalesce(func.sum(PointsHistory.points), 0)).where(
            PointsHistory.task_id == task_id,
            PointsHistory.user_id == user_id,
        )
    )
    return int(result.scalar_one())


async def mark_done_and_add_points(session: AsyncSession, task: Task) -> Task:
    """
    Баллы начисляются сразу.
    Если задача для ОБОИХ, баллы начисляются обоим.
    Повторное нажатие “Выполнено” не дублирует баллы, если они уже начислены.
    """
    now = now_msk()
    task.status = TaskStatus.DONE
    task.completed_at = now
    task.updated_at = now
    task.discussion_until = now + timedelta(hours=settings.task_discussion_hours)

    for user_id in await _point_recipient_ids(session, task):
        if await _task_points_net(session, task.id, user_id) <= 0:
            session.add(
                PointsHistory(
                    user_id=user_id,
                    task_id=task.id,
                    points=task.points,
                    action_type=PointsAction.ADD,
                    comment="Задача отмечена выполненной",
                    created_at=now,
                )
            )
    await session.commit()
    return await get_task(session, task.id)  # type: ignore[return-value]


async def revoke_task_points(session: AsyncSession, task: Task, reason: str) -> None:
    """Снимает текущие начисленные баллы по задаче у всех ответственных, если они есть."""
    now = now_msk()
    for user_id in await _point_recipient_ids(session, task):
        net = await _task_points_net(session, task.id, user_id)
        if net > 0:
            session.add(
                PointsHistory(
                    user_id=user_id,
                    task_id=task.id,
                    points=-net,
                    action_type=PointsAction.REMOVE,
                    comment=reason,
                    created_at=now,
                )
            )
    await session.commit()


async def change_task_points(session: AsyncSession, task: Task, new_points: int, reason: str) -> Task:
    """
    Меняет стоимость задачи и синхронизирует уже начисленные баллы.
    Если задача уже выполнена/засчитана и по ней есть баллы — добавляется дельта.
    """
    old_points = task.points
    task.points = new_points
    task.updated_at = now_msk()

    delta = new_points - old_points
    if delta != 0:
        for user_id in await _point_recipient_ids(session, task):
            net = await _task_points_net(session, task.id, user_id)
            if net > 0:
                session.add(
                    PointsHistory(
                        user_id=user_id,
                        task_id=task.id,
                        points=delta,
                        action_type=PointsAction.CHANGE,
                        comment=reason,
                        created_at=now_msk(),
                    )
                )
    await session.commit()
    return await get_task(session, task.id)  # type: ignore[return-value]


async def count_task(session: AsyncSession, task: Task) -> Task:
    task.status = TaskStatus.COUNTED
    task.counted_at = now_msk()
    task.updated_at = now_msk()
    await session.commit()
    return await get_task(session, task.id)  # type: ignore[return-value]


async def cancel_task(session: AsyncSession, task: Task, remove_points: bool = True) -> Task:
    now = now_msk()
    task.status = TaskStatus.CANCELLED
    task.updated_at = now
    await session.commit()
    if remove_points:
        await revoke_task_points(session, task, "Задача отменена / баллы сняты")
    return await get_task(session, task.id)  # type: ignore[return-value]


async def add_comment(
    session: AsyncSession,
    task: Task,
    author: User,
    text: str,
    comment_type: CommentType = CommentType.NORMAL,
) -> TaskComment:
    comment = TaskComment(
        task_id=task.id,
        author_id=author.id,
        comment_text=text,
        comment_type=comment_type,
        created_at=now_msk(),
    )
    session.add(comment)
    task.updated_at = now_msk()
    await session.commit()
    await session.refresh(comment)
    return comment


async def points_summary(session: AsyncSession, user: User, start: datetime | None = None, end: datetime | None = None) -> int:
    q = select(func.coalesce(func.sum(PointsHistory.points), 0)).where(PointsHistory.user_id == user.id)
    if start:
        q = q.where(PointsHistory.created_at >= start)
    if end:
        q = q.where(PointsHistory.created_at < end)
    result = await session.execute(q)
    return int(result.scalar_one())


async def all_points_summary(session: AsyncSession, users: list[User], start: datetime | None = None, end: datetime | None = None) -> dict[int, int]:
    result: dict[int, int] = {}
    for user in users:
        result[user.id] = await points_summary(session, user, start, end)
    return result
