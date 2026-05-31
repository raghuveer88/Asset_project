from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all SQLAlchemy models."""

    pass


settings = get_settings()
engine = create_engine(settings.sqlalchemy_database_url, pool_pre_ping=True, pool_recycle=280, future=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)
EXPECTED_CLOUDSQL_INSTANCE = "asset-project-498003:us-central1:asset-ai-mysql"


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
    return bool(db_connection_diagnostics()["db_connected"])


def db_connection_diagnostics() -> dict:
    """Return sanitized DB and Cloud SQL connection diagnostics."""
    error_type = None
    error_message = None
    connected = False
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        connected = True
    except Exception as exc:
        error_type = type(exc).__name__
        error_message = _sanitize_error_message(str(exc))

    return {
        "db_connected": connected,
        "db_error_type": error_type,
        "db_error_message": error_message,
        "database_url_shape": _database_url_shape(),
        "cloudsql_dir_exists": Path("/cloudsql").exists(),
        "cloudsql_entries": _cloudsql_entries(),
        "expected_cloudsql_instance": EXPECTED_CLOUDSQL_INSTANCE,
        "expected_cloudsql_socket_path_exists": Path("/cloudsql", EXPECTED_CLOUDSQL_INSTANCE).exists(),
    }


def _database_url_shape() -> dict:
    """Describe the configured DATABASE_URL without exposing its password."""
    try:
        url = make_url(settings.sqlalchemy_database_url)
    except Exception as exc:
        return {
            "parse_error_type": type(exc).__name__,
            "parse_error_message": _sanitize_error_message(str(exc)),
        }
    query = dict(url.query)
    return {
        "dialect": url.get_backend_name(),
        "driver": url.get_driver_name(),
        "username": url.username,
        "host": url.host,
        "database": url.database,
        "unix_socket_exists": "unix_socket" in query,
        "unix_socket": query.get("unix_socket"),
    }


def _cloudsql_entries() -> list[str]:
    """List /cloudsql entries when Cloud Run exposes the mount."""
    path = Path("/cloudsql")
    if not path.exists():
        return []
    try:
        return sorted(item.name for item in path.iterdir())
    except Exception as exc:
        return [f"unreadable: {type(exc).__name__}: {_sanitize_error_message(str(exc))}"]


def _sanitize_error_message(message: str) -> str:
    """Remove configured DB secrets from error text."""
    password = None
    try:
        password = make_url(settings.sqlalchemy_database_url).password
    except Exception:
        pass
    sanitized = message
    if password:
        sanitized = sanitized.replace(password, "***")
    sanitized = sanitized.replace(settings.mysql_password, "***")
    return sanitized[:2000]
