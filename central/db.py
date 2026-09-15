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
