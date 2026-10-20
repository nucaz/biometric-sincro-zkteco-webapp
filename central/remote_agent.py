"""
Runs on a remote branch server that can reach ITS OWN LAN's biometric
devices directly, but that the central app (central/webapp.py) cannot
reach over the network -- e.g. behind a VPN that only routes this
server's own traffic to headquarters, not arbitrary devices on its LAN.

Both jobs below talk to the SAME shared DATABASE_URL the central app
uses (confirmed reachable over the VPN tunnel) -- this is just another
process coordinating through the one shared database, the same idea as
central/device_lock.py, not a new network protocol to open a firewall
hole for:

1. Sync -- reuses central.sync.sync_all(only_agent=AGENT_NAME) AS-IS to
   pull attendance from every device this agent owns and upsert it
   centrally. See central/sync_loop.py's scheduling helpers, reused here
   (not reimplemented) for the SYNC_DAILY_AT / SYNC_INTERVAL_MINUTES env
   vars.

2. Device-management commands -- polls `device_commands` for pending
   rows targeting a device this agent owns (Device.agent_name ==
   AGENT_NAME), executes the SAME ZKTecoAttendance call
   central/webapp.py's run_device_op() would make in-process for a local
   device, and writes the result back. This is the "puente" (bridge):
   run_device_op() in webapp.py detects Device.agent_name is set and
   enqueues here instead of connecting directly.

   ACTIONS below must stay in sync with webapp.py: every route that
   retrofits a new `action=` for run_device_op() needs the matching
   branch added here too. As of this writing only "test" (Probar
   conexión) is wired up end to end on both sides -- the others
   (restart/poweroff/clear_attendance/device user management) are NOT
   yet retrofitted in webapp.py, so a remote device can't use them until
   that's done; see CLAUDE.md for the status of that follow-up work.

Run with:
    AGENT_NAME=sede-remota-1 DATABASE_URL=postgresql+psycopg2://... python -m central.remote_agent
"""
import json
import os
import sys
import time
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from attendance_system import ZKTecoAttendance  # noqa: E402
from central.db import SessionLocal, init_db  # noqa: E402
from central.models import Device, DeviceCommand  # noqa: E402
from central.sync import sync_all  # noqa: E402
from central.sync_loop import _seconds_until  # noqa: E402

COMMAND_POLL_SECONDS = 5


def _run_action(device, action, params):
    """Mirrors the closures central/webapp.py's run_device_op() callers
    build in-process (device_test's `work()`, etc.) -- same
    ZKTecoAttendance calls, dispatched by name instead of being a literal
    Python closure, since a closure can't cross a process boundary.
    Returning None (not raising) for "reached the device but the ZK
    handshake itself was rejected" matches device_test's local `work()`
    exactly, so webapp.py's existing `if result is None:` branch (comm
    key hint, etc.) behaves identically for a local or a remote device."""
    system = ZKTecoAttendance(device.ip, port=device.port, password=device.comm_password or 0)
    system.connect()
    if not system.conn:
        return None
    try:
        if action == "test":
            return {
                "model": system.device_info.get("model", "").strip(),
                "serial": system.device_info.get("serial_number", "").strip(),
            }
        raise ValueError(f"Acción desconocida para el agente remoto: '{action}'.")
    finally:
        system.disconnect()


def _process_one(session, cmd):
    device = session.get(Device, cmd.device_pk)
    cmd.picked_up_at = datetime.utcnow()
    session.commit()
    try:
        if not device:
            raise RuntimeError(f"device_pk={cmd.device_pk} ya no existe.")
        params = json.loads(cmd.params) if cmd.params else {}
        result = _run_action(device, cmd.action, params)
        cmd.status = "done"
        cmd.result = json.dumps(result)
    except Exception as e:
        cmd.status = "error"
        cmd.error = str(e)
    cmd.completed_at = datetime.utcnow()
    session.commit()
    print(f"[remote_agent] {cmd.action} -> device_pk={cmd.device_pk}: {cmd.status}", flush=True)


def poll_commands(agent_name):
    session = SessionLocal()
    try:
        device_ids = [d.id for d in session.query(Device.id).filter(Device.agent_name == agent_name).all()]
        if not device_ids:
            return
        pending = (
            session.query(DeviceCommand)
            .filter(DeviceCommand.device_pk.in_(device_ids), DeviceCommand.status == "pending")
            .order_by(DeviceCommand.created_at)
            .all()
        )
        for cmd in pending:
            _process_one(session, cmd)
    finally:
        session.close()


def _run_sync(agent_name):
    print(f"[remote_agent] {datetime.now().isoformat(timespec='seconds')} -- sincronizando dispositivos de '{agent_name}'", flush=True)
    results = sync_all(only_agent=agent_name)
    for name, result in results.items():
        print(f"[remote_agent] sync {name}: {result}", flush=True)


def main():
    agent_name = os.environ.get("AGENT_NAME")
    if not agent_name:
        print("Falta la variable de entorno AGENT_NAME.", file=sys.stderr)
        sys.exit(1)
    init_db()

    interval_raw = os.environ.get("SYNC_INTERVAL_MINUTES")
    daily_at = os.environ.get("SYNC_DAILY_AT") or ("" if interval_raw else "23:00")
    next_sync = time.monotonic()  # sync once right away, then on schedule
    interval_seconds = int(interval_raw) * 60 if interval_raw else None

    print(f"[remote_agent] agente '{agent_name}' iniciado -- comandos cada {COMMAND_POLL_SECONDS}s, "
          + (f"sync cada {interval_raw} min" if interval_seconds else f"sync diario a las {daily_at}"), flush=True)

    while True:
        poll_commands(agent_name)
        if time.monotonic() >= next_sync:
            _run_sync(agent_name)
            next_sync = time.monotonic() + (interval_seconds if interval_seconds else _seconds_until(daily_at))
        time.sleep(COMMAND_POLL_SECONDS)


if __name__ == "__main__":
    main()
