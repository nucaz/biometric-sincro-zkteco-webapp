"""
Central database connection.

Defaults to a local SQLite file so the whole system can be tried out with
zero setup. Point DATABASE_URL at Postgres/MySQL for a real multi-sede
deployment, e.g.:
    postgresql+psycopg2://user:pass@host:5432/attendance
    mysql+pymysql://user:pass@host:3306/attendance
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DEFAULT_SQLITE_PATH = os.path.join(os.path.dirname(__file__), "attendance.db")
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{DEFAULT_SQLITE_PATH}")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def init_db():
    from . import models  # noqa: F401  (register models on Base before create_all)
    Base.metadata.create_all(engine)
    _migrate_add_user_lockout_columns()


def _migrate_add_user_lockout_columns():
    """create_all() only creates missing TABLES -- it never adds a column
    to a `users` table that already exists with data on an upgraded
    server, so bring it up to date here. Idempotent: skips any column
    that's already there, safe to call on every startup."""
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("users")}
    with engine.begin() as conn:
        if "failed_login_attempts" not in existing:
            conn.execute(text("ALTER TABLE users ADD COLUMN failed_login_attempts INTEGER NOT NULL DEFAULT 0"))
        if "locked" not in existing:
            conn.execute(text("ALTER TABLE users ADD COLUMN locked BOOLEAN NOT NULL DEFAULT FALSE"))
