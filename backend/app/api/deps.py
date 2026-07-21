"""FastAPI dependencies: database session and authenticated current user."""

from collections.abc import AsyncGenerator

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import raise_api_error
from app.auth.jwt import verify_token
from app.db.base import async_session_factory
from app.db.models import User


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session


async def get_current_user(request: Request, session: AsyncSession = Depends(get_session)) -> User:
    token = request.cookies.get("session_token")
    claims = verify_token(token) if token else None
    if claims is None:
        raise_api_error(401, "UNAUTHENTICATED", "Yêu cầu đăng nhập")

    try:
        user_id = int(claims["sub"])
    except (KeyError, TypeError, ValueError):
        raise_api_error(401, "UNAUTHENTICATED", "Yêu cầu đăng nhập")

    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise_api_error(401, "UNAUTHENTICATED", "Yêu cầu đăng nhập")
    request.state.user = user
    return user
