"""Async engine + session factory + declarative Base (IC§2.1)."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(settings.DATABASE_URL)

async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
