"""Database setup utilities for OpenChatShop.

Provides engine creation, table initialization, session management,
and a convenience init_db() function for one-shot setup.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import Engine
from sqlmodel import Session, SQLModel, create_engine

# Ensure all table models are registered on SQLModel.metadata when
# create_tables() is called, even if the caller only imported
# ``database`` directly.
from open_chat_shop.storage.models import (  # noqa: F401
    AuditRecord,
    ConversationLog,
    Order,
    Product,
    RefundRecord,
    User,
)


def get_engine(url: str = "sqlite:///data/commerce.db") -> Engine:
    """Create and return a SQLModel (SQLAlchemy) engine.

    Args:
        url: SQLAlchemy database URL. Defaults to a local SQLite file.

    Returns:
        A new Engine instance connected to the given URL.
    """
    return create_engine(url, echo=False)


def create_tables(engine: Engine) -> None:
    """Create all tables defined by SQLModel subclasses.

    Safe to call multiple times; existing tables are not recreated.
    """
    SQLModel.metadata.create_all(engine)


@contextmanager
def get_session(engine: Engine) -> Generator[Session, None, None]:
    """Yield a SQLModel Session as a context manager.

    The session is committed on clean exit and rolled back on exception.
    """
    session = Session(engine)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db(url: str = "sqlite:///data/commerce.db") -> Engine:
    """Convenience function: create engine and initialise all tables.

    Returns:
        The initialised Engine ready for session creation.
    """
    engine = get_engine(url)
    create_tables(engine)
    return engine
