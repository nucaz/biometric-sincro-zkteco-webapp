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


def _enable_sqlite_wal():
    """Default SQLite journal mode locks the whole file for the duration of
    a write -- with waitress (web app) and the scheduled `python -m
    central.sync` process both hitting this same file, a sync running
    every 15 min can make the dashboard visibly stall. WAL lets readers
    keep working while a write is in progress; it's a one-time on-disk
    flag (persists across restarts) and has no downside for a single-file
    local deployment like this one."""
    if not DATABASE_URL.startswith("sqlite"):
        return
    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA journal_mode=WAL")


def init_db():
    from . import models  # noqa: F401  (register models on Base before create_all)
    _enable_sqlite_wal()
    Base.metadata.create_all(engine)
    _migrate_add_user_lockout_columns()
    _migrate_add_device_deleted_column()
    _migrate_add_attendance_log_indexes()
    _migrate_add_schedule_exit_time()
    _migrate_add_employee_profile_columns()
    _migrate_add_device_agent_name()


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


def _migrate_add_device_deleted_column():
    """Same as _migrate_add_user_lockout_columns, for devices.deleted --
    needed so "Eliminar" on an already-running server can switch from
    dropping a device's history to preserving it (see device_delete())
    without losing anything already on disk."""
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    if "devices" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("devices")}
    if "deleted" not in existing:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE devices ADD COLUMN deleted BOOLEAN NOT NULL DEFAULT FALSE"))


def _migrate_add_attendance_log_indexes():
    """attendance_log.timestamp and employee_map.employee_id are declared
    with index=True in models.py, which only takes effect via create_all()
    on a table that doesn't exist yet -- an already-running install with
    these tables already created needs the index added explicitly. Guarded
    by name so this is a no-op once it's run once (or on a fresh install,
    where create_all already made it)."""
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    if "attendance_log" in inspector.get_table_names():
        existing = {ix["name"] for ix in inspector.get_indexes("attendance_log")}
        if "ix_attendance_log_timestamp" not in existing:
            with engine.begin() as conn:
                conn.execute(text("CREATE INDEX ix_attendance_log_timestamp ON attendance_log (timestamp)"))
    if "employee_map" in inspector.get_table_names():
        existing = {ix["name"] for ix in inspector.get_indexes("employee_map")}
        if "ix_employee_map_employee_id" not in existing:
            with engine.begin() as conn:
                conn.execute(text("CREATE INDEX ix_employee_map_employee_id ON employee_map (employee_id)"))


def _migrate_add_schedule_exit_time():
    """A schedule created before exit_time existed has no way to know its
    own exit hour -- add the column (nullable; the form requires it going
    forward, but an old row stays NULL until someone re-saves it in
    /schedules) instead of losing whatever schedules were already
    created."""
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    if "schedules" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("schedules")}
    if "exit_time" not in existing:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE schedules ADD COLUMN exit_time TIME"))


def _migrate_add_employee_profile_columns():
    """Extended HR profile fields on employees -- all nullable/additive,
    see the Employee class docstring in models.py for why nombre/
    apellido_paterno/apellido_materno don't replace full_name."""
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    if "employees" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("employees")}
    new_columns = {
        "nombre": "VARCHAR(80)",
        "apellido_paterno": "VARCHAR(80)",
        "apellido_materno": "VARCHAR(80)",
        "fecha_nacimiento": "DATE",
        "celular": "VARCHAR(32)",
        "correo_personal": "VARCHAR(120)",
        "correo_corporativo": "VARCHAR(120)",
        "direccion": "VARCHAR(255)",
        "area": "VARCHAR(80)",
        "sede": "VARCHAR(120)",
    }
    with engine.begin() as conn:
        for name, ddl_type in new_columns.items():
            if name not in existing:
                conn.execute(text(f"ALTER TABLE employees ADD COLUMN {name} {ddl_type}"))


def _migrate_add_device_agent_name():
    """See Device.agent_name's docstring in models.py -- nullable/
    additive, every device that existed before this stays NULL (direct
    connection, unchanged behavior)."""
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    if "devices" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("devices")}
    if "agent_name" not in existing:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE devices ADD COLUMN agent_name VARCHAR(64)"))
