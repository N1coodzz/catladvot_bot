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
    В этом режиме задача показывается обоим пользователям, а при подтверждении баллы получают оба.
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
        .where(Task.is_deleted.is_(False), Task.status.in_([TaskStatus.WAITING_APPROVAL, TaskStatus.DONE, TaskStatus.COUNTED]))
        .order_by(Task.completed_at.desc().nullslast(), Task.updated_at.desc())
    )
    return list(result.scalars())


async def list_discussion_tasks(session: AsyncSession) -> list[Task]:
    result = await session.execute(
        select(Task)
        .options(*_TASK_LOAD_OPTIONS)
        .where(
            Task.is_deleted.is_(False),
            Task.status.in_([TaskStatus.WAITING_APPROVAL, TaskStatus.DISCUSSION, TaskStatus.REWORK, TaskStatus.POINTS_REVIEW]),
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


async def mark_done_pending_approval(session: AsyncSession, task: Task) -> Task:
    """
    Исполнитель отметил задачу выполненной.
    ВАЖНО: баллы ещё не начисляются. Задача ждёт подтверждения второго котика.
    """
    now = now_msk()
    task.status = TaskStatus.WAITING_APPROVAL
    task.completed_at = now
    task.updated_at = now
    task.discussion_until = now + timedelta(hours=settings.task_discussion_hours)
    await session.commit()
    return await get_task(session, task.id)  # type: ignore[return-value]


async def approve_task_and_sync_points(session: AsyncSession, task: Task, comment: str = "Задача подтверждена") -> Task:
    """
    Единая точка подтверждения задачи.
    Только эта функция ставит “Засчитана” и доводит баллы до правильного значения.

    Защита от дублей:
    - если по задаче уже есть 10 ⭐ у ответственного, повторное подтверждение не добавит ещё 10;
    - если баллы менялись, функция добавит/снимет только разницу.
    """
    now = now_msk()
    recipients = await _point_recipient_ids(session, task)
    for user_id in recipients:
        current_net = await _task_points_net(session, task.id, user_id)
        delta = task.points - current_net
        if delta != 0:
            session.add(
                PointsHistory(
                    user_id=user_id,
                    task_id=task.id,
                    points=delta,
                    action_type=PointsAction.ADD if delta > 0 else PointsAction.REMOVE,
                    comment=comment,
                    created_at=now,
                )
            )

    task.status = TaskStatus.COUNTED
    task.counted_at = now
    task.updated_at = now
    await session.commit()
    return await get_task(session, task.id)  # type: ignore[return-value]


# Совместимость со старым названием: теперь это НЕ просто смена статуса, а полное подтверждение с баллами.
async def count_task(session: AsyncSession, task: Task) -> Task:
    return await approve_task_and_sync_points(session, task, "Задача засчитана")


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
    Меняет стоимость задачи и синхронизирует уже подтверждённые баллы.
    Если задача ещё ждёт подтверждения — меняется только стоимость задачи.
    """
    old_points = task.points
    task.points = new_points
    task.updated_at = now_msk()

    if task.status == TaskStatus.COUNTED:
        delta = new_points - old_points
        if delta != 0:
            for user_id in await _point_recipient_ids(session, task):
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


async def list_points_history(
    session: AsyncSession,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 15,
) -> list[PointsHistory]:
    q = select(PointsHistory).options(selectinload(PointsHistory.user), selectinload(PointsHistory.task))
    if start:
        q = q.where(PointsHistory.created_at >= start)
    if end:
        q = q.where(PointsHistory.created_at < end)
    q = q.order_by(PointsHistory.created_at.desc()).limit(limit)
    result = await session.execute(q)
    return list(result.scalars())
