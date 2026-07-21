"""FastAPI dependencies: DB session + current user.

⚠️ [v0.9.12] Development-only auth bypass: get_current_user is a STUB returning
the first seed user (so decided_by/verified_by have a test value). Real
cookie-JWT auth replaces this in TASK-14 — NOT a bug (PROGRESS TASK-03).
"""

from collections.abc import AsyncGenerator

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import async_session_factory
from app.db.models import User


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session


async def get_current_user(session: AsyncSession = Depends(get_session)) -> User | None:
    result = await session.execute(select(User).order_by(User.id).limit(1))
    return result.scalar_one_or_none()
