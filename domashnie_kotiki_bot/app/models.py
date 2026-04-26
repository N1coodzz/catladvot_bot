from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Role(str, enum.Enum):
    KOT = "kot"
    KOTIK = "kotik"


class TaskStatus(str, enum.Enum):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    WAITING_APPROVAL = "waiting_approval"
    COUNTED = "counted"
    DISCUSSION = "discussion"
    REWORK = "rework"
    POINTS_REVIEW = "points_review"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"
    DELETED = "deleted"


class CommentType(str, enum.Enum):
    NORMAL = "normal"
    DISCUSSION = "discussion"
    POINTS = "points"
    REWORK = "rework"
    SYSTEM = "system"


class PointsAction(str, enum.Enum):
    ADD = "add"
    REMOVE = "remove"
    CHANGE = "change"
    MANUAL = "manual"


class ScheduleStatus(str, enum.Enum):
    FREE = "free"
    BUSY = "busy"
    WORK_SHIFT = "work_shift"
    NIGHT_SHIFT = "night_shift"
    PARTIAL_FREE_AFTER = "partial_free_after"
    PARTIAL_FREE_BEFORE = "partial_free_before"
    IRREGULAR = "irregular"
    UNKNOWN = "unknown"


class ScheduleSource(str, enum.Enum):
    MANUAL = "manual"
    REPLACEMENT = "replacement"
    EXCHANGE = "exchange"
    GENERATED = "generated"


class ReplacementType(str, enum.Enum):
    TOOK_EXTRA_SHIFT = "took_extra_shift"
    SHIFT_REMOVED = "shift_removed"
    SWAPPED_SHIFT = "swapped_shift"
    OTHER = "other"


class ExchangeSuggestionStatus(str, enum.Enum):
    FOUND = "found"
    KOT_WILL_CHECK = "kot_will_check"
    SUCCESS = "success"
    NOT_NOW = "not_now"
    IGNORED_DATE = "ignored_date"
    CLOSED = "closed"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    role: Mapped[Role] = mapped_column(Enum(Role), unique=True)
    display_name: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime)

    notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    morning_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    evening_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    weather_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    tasks_created: Mapped[list["Task"]] = relationship(back_populates="creator", foreign_keys="Task.creator_id")
    tasks_assigned: Mapped[list["Task"]] = relationship(back_populates="assignee", foreign_keys="Task.assignee_id")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    creator_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    points: Mapped[int] = mapped_column(Integer)
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), default=TaskStatus.NEW)

    deadline_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    counted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    discussion_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)

    creator: Mapped[User] = relationship(back_populates="tasks_created", foreign_keys=[creator_id])
    assignee: Mapped[User | None] = relationship(back_populates="tasks_assigned", foreign_keys=[assignee_id])
    comments: Mapped[list["TaskComment"]] = relationship(back_populates="task", cascade="all, delete-orphan")


class TaskComment(Base):
    __tablename__ = "task_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"))
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    comment_text: Mapped[str] = mapped_column(Text)
    comment_type: Mapped[CommentType] = mapped_column(Enum(CommentType), default=CommentType.NORMAL)
    created_at: Mapped[datetime] = mapped_column(DateTime)

    task: Mapped[Task] = relationship(back_populates="comments")
    author: Mapped[User] = relationship()


class PointsHistory(Base):
    __tablename__ = "points_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    points: Mapped[int] = mapped_column(Integer)
    action_type: Mapped[PointsAction] = mapped_column(Enum(PointsAction))
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)

    user: Mapped[User] = relationship()
    task: Mapped[Task | None] = relationship()


class ScheduleEntry(Base):
    __tablename__ = "schedule_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    date: Mapped[datetime] = mapped_column(DateTime, index=True)
    start_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    status_type: Mapped[ScheduleStatus] = mapped_column(Enum(ScheduleStatus))
    title: Mapped[str] = mapped_column(String(128))
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[ScheduleSource] = mapped_column(Enum(ScheduleSource), default=ScheduleSource.MANUAL)

    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)

    user: Mapped[User] = relationship()


class ShiftReplacement(Base):
    __tablename__ = "shift_replacements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    original_schedule_id: Mapped[int | None] = mapped_column(ForeignKey("schedule_entries.id"), nullable=True)
    replacement_type: Mapped[ReplacementType] = mapped_column(Enum(ReplacementType))

    old_start_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    old_end_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    new_start_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    new_end_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    old_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    new_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class ExchangeSuggestion(Base):
    __tablename__ = "exchange_suggestions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_date: Mapped[datetime] = mapped_column(DateTime, index=True)
    kot_shift_start: Mapped[datetime]
    kot_shift_end: Mapped[datetime]
    kotik_free_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    kotik_free_end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    potential_shared_time: Mapped[str | None] = mapped_column(String(128), nullable=True)

    status: Mapped[ExchangeSuggestionStatus] = mapped_column(Enum(ExchangeSuggestionStatus), default=ExchangeSuggestionStatus.FOUND)
    suggested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_reminded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ignored: Mapped[bool] = mapped_column(Boolean, default=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)


class Setting(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(128), unique=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
