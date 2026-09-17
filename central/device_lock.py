"""
Cross-process advisory lock for a physical device, backed by the shared
DB (see models.DeviceLock) instead of an in-memory threading.Lock -- the
web app (waitress, one long-lived process) and a scheduled
`python -m central.sync` run (a fresh process every time Task Scheduler
fires) can't see each other's memory, but they both already talk to the
same database, so that's where they have to coordinate. A ZK terminal
only accepts one live session at a time; without this, a scheduled sync
and a manual click in the panel landing on the same device around the
same moment just make both of them fail or hang instead of one waiting
its turn.
"""
import os
import socket
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError

from .db import SessionLocal
from .models import DeviceLock

# A bit past central.webapp's own HARD_SYNC_TIMEOUT_SECONDS (150s): a
# lock still held past this point almost certainly belongs to a process
# that crashed or leaked (pyzk not respecting its own socket timeout,
# same known issue as everywhere else in this codebase) rather than one
# still doing legitimate work, so it's safe to take over instead of
# blocking every future attempt on that device forever.
STALE_AFTER_SECONDS = 180


class DeviceBusy(RuntimeError):
    pass


def _owner_label():
    return f"{socket.gethostname()}:{os.getpid()}"


def acquire(device_pk, device_name, owner=None):
    """Claim the lock for `device_pk`. Raises DeviceBusy immediately
    (never blocks/waits) if someone else already holds a fresh one."""
    owner = owner or _owner_label()
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        existing = db.get(DeviceLock, device_pk)
        if existing is not None:
            age = (now - existing.locked_at).total_seconds()
            if age < STALE_AFTER_SECONDS:
                raise DeviceBusy(
                    f"'{device_name}' ya tiene otra operación en curso "
                    f"({existing.locked_by or 'otro proceso'}, hace {int(age)}s). "
                    "Espera a que termine antes de intentar de nuevo -- el equipo "
                    "solo acepta una conexión a la vez."
                )
            existing.locked_at = now
            existing.locked_by = owner
        else:
            db.add(DeviceLock(device_pk=device_pk, locked_at=now, locked_by=owner))
        try:
            db.commit()
        except IntegrityError:
            # Lost a race against another process taking the same
            # (just-created or just-gone-stale) lock at the same instant --
            # whoever's commit landed first legitimately owns it now.
            db.rollback()
            raise DeviceBusy(
                f"'{device_name}' ya tiene otra operación en curso. "
                "Espera a que termine antes de intentar de nuevo."
            )
    finally:
        db.close()


def release(device_pk):
    db = SessionLocal()
    try:
        existing = db.get(DeviceLock, device_pk)
        if existing is not None:
            db.delete(existing)
            db.commit()
    finally:
        db.close()
