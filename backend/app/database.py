from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all SQLAlchemy models."""

    pass


settings = get_settings()
engine = create_engine(settings.sqlalchemy_database_url, pool_pre_ping=True, pool_recycle=280, future=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)


def get_db() -> Generator[Session, None, None]:
    """Yield a request-scoped database session for FastAPI dependencies."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Provide a transactional session for CLI scripts and data pipelines."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """Create all application tables if they do not already exist."""
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def check_db() -> bool:
    """Return True when MySQL accepts a simple connectivity query."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
