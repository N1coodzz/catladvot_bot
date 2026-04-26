from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Role, User
from app.utils import now_msk


async def get_user_by_tg(session: AsyncSession, telegram_id: int) -> User | None:
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    return result.scalar_one_or_none()


async def get_user_by_role(session: AsyncSession, role: Role) -> User | None:
    result = await session.execute(select(User).where(User.role == role))
    return result.scalar_one_or_none()


async def get_all_users(session: AsyncSession) -> list[User]:
    result = await session.execute(select(User).order_by(User.role))
    return list(result.scalars())


async def register_user(session: AsyncSession, telegram_id: int, role: Role) -> tuple[User | None, str]:
    existing = await get_user_by_tg(session, telegram_id)
    if existing:
        return existing, "already_registered"

    role_owner = await get_user_by_role(session, role)
    if role_owner:
        return None, "role_taken"

    display_name = "Кот" if role == Role.KOT else "Котик"
    user = User(
        telegram_id=telegram_id,
        role=role,
        display_name=display_name,
        created_at=now_msk(),
        notifications_enabled=True,
        morning_enabled=True,
        evening_enabled=True,
        weather_enabled=True,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user, "registered"


async def get_pair(session: AsyncSession) -> tuple[User | None, User | None]:
    kot = await get_user_by_role(session, Role.KOT)
    kotik = await get_user_by_role(session, Role.KOTIK)
    return kot, kotik


async def get_partner(session: AsyncSession, user: User) -> User | None:
    return await get_user_by_role(session, Role.KOTIK if user.role == Role.KOT else Role.KOT)
