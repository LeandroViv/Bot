"""Database layer with SQLAlchemy async engine and models."""

from __future__ import annotations

import datetime as dt
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from sqlalchemy import BigInteger, DateTime, String, Text, func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from bot.config import settings


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class User(Base):
    """Telegram user model."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    language_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    is_bot: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, username={self.username})>"


class Chat(Base):
    """Telegram chat model (private, group, channel)."""

    __tablename__ = "chats"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # private, group, supergroup, channel
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<Chat(id={self.id}, type={self.type})>"


class MessageLog(Base):
    """Log of messages for analytics/debugging."""

    __tablename__ = "message_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    message_type: Mapped[str] = mapped_column(String(50), nullable=False)  # text, photo, document, etc.
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    def __repr__(self) -> str:
        return f"<MessageLog(id={self.id}, user_id={self.user_id}, chat_id={self.chat_id})>"


class BotState(Base):
    """Key-value store for bot state persistence."""

    __tablename__ = "bot_state"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<BotState(key={self.key})>"


# Engine and session factory
_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def get_engine() -> AsyncEngine:
    """Get or create the async engine."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            settings.database_url,
            echo=settings.log_level == "DEBUG",
            pool_pre_ping=True,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get or create the session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Get a database session."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Initialize database tables."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Close database connections."""
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
        _engine = None
        _session_factory = None


# Repository functions
async def get_or_create_user(
    session: AsyncSession,
    user_id: int,
    username: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    language_code: Optional[str] = None,
    is_bot: bool = False,
) -> User:
    """Get existing user or create new one."""
    user = await session.get(User, user_id)
    if user is None:
        user = User(
            id=user_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            language_code=language_code,
            is_bot=is_bot,
        )
        session.add(user)
    else:
        # Update fields if changed
        if username is not None:
            user.username = username
        if first_name is not None:
            user.first_name = first_name
        if last_name is not None:
            user.last_name = last_name
        if language_code is not None:
            user.language_code = language_code
    return user


async def get_or_create_chat(
    session: AsyncSession,
    chat_id: int,
    chat_type: str,
    title: Optional[str] = None,
    username: Optional[str] = None,
) -> Chat:
    """Get existing chat or create new one."""
    chat = await session.get(Chat, chat_id)
    if chat is None:
        chat = Chat(
            id=chat_id,
            type=chat_type,
            title=title,
            username=username,
        )
        session.add(chat)
    else:
        if title is not None:
            chat.title = title
        if username is not None:
            chat.username = username
    return chat


async def log_message(
    session: AsyncSession,
    message_id: int,
    user_id: int,
    chat_id: int,
    text: Optional[str],
    message_type: str,
) -> MessageLog:
    """Log a message."""
    log = MessageLog(
        message_id=message_id,
        user_id=user_id,
        chat_id=chat_id,
        text=text,
        message_type=message_type,
    )
    session.add(log)
    return log


async def get_bot_state(session: AsyncSession, key: str) -> Optional[str]:
    """Get a value from bot state."""
    state = await session.get(BotState, key)
    return state.value if state else None


async def set_bot_state(session: AsyncSession, key: str, value: str) -> BotState:
    """Set a value in bot state."""
    state = await session.get(BotState, key)
    if state is None:
        state = BotState(key=key, value=value)
        session.add(state)
    else:
        state.value = value
    return state