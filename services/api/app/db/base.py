"""Engine/session construction and the declarative base for all ORM models."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def build_engine(database_url: str, connect_timeout_seconds: float = 2.0) -> Engine:
    """Create an engine.

    ``connect_timeout`` is enforced at the libpq level so a dropped/unreachable host fails
    fast inside its worker thread instead of blocking for the OS-level TCP timeout.
    """
    return create_engine(
        database_url,
        pool_pre_ping=True,
        future=True,
        connect_args={"connect_timeout": max(1, int(round(connect_timeout_seconds)))},
    )


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Transactional scope: commit on success, rollback on error, always close."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
