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
   branch added here too.

Run with:
    AGENT_NAME=sede-remota-1 DATABASE_URL=postgresql+psycopg2://... python -m central.remote_agent
"""
import json
import os
import sys
import threading
import time
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from attendance_system import ZKTecoAttendance, check_network_reachable  # noqa: E402
from central import device_lock  # noqa: E402
from central.db import SessionLocal, init_db  # noqa: E402
from central.models import Device, DeviceCommand  # noqa: E402
from central.sync import sync_all, sync_device, backup_device  # noqa: E402
from central.sync_loop import _seconds_until  # noqa: E402

COMMAND_POLL_SECONDS = 5


def _run_action(session, device, action, params):
    """Mirrors the closures central/webapp.py's run_device_op() callers
    build in-process (device_test's `work()`, etc.) -- same
    ZKTecoAttendance calls, dispatched by name instead of being a literal
    Python closure, since a closure can't cross a process boundary.
    Returning None (not raising) for "reached the device but the ZK
    handshake itself was rejected" matches device_test's local `work()`
    exactly, so webapp.py's existing `if result is None:` branch (comm
    key hint, etc.) behaves identically for a local or a remote device.

    `session` is this agent's own open SessionLocal (same shared
    DATABASE_URL as the central app) -- "backup" and "sync" need it, to
    reuse central.sync.backup_device()/sync_device() exactly as
    webapp.py's local path would (same dedup-insert into the shared
    attendance_log).

    Called from two places: _process_one() below (a command queued by
    the central panel) and central/remote_agent_status.py (a button
    pressed directly on this agent's own local status page, skipping the
    central bridge entirely -- same function either way, so a device
    busy with one can't also be hit by the other without the lock below
    noticing."""
    if action == "ping":
        # Pure TCP reachability -- no ZK handshake, mirrors device_ping's
        # local check_network_reachable() call. Doesn't open a pyzk
        # connection at all, so it's handled before the connect() below.
        reachable, detail = check_network_reachable(device.ip, device.port)
        return {"reachable": reachable, "detail": detail}

    if action == "backup":
        # backup_device() manages its OWN connection, retries and device
        # lock (central/sync.py's _pull_raw_with_retry) -- same function
        # webapp.py's local path calls directly, so it's dispatched here
        # before the generic system.connect() below, not through it.
        raw, new_count = backup_device(session, device)
        rows = [] if raw is None else json.loads(raw.to_json(orient="records", date_format="iso"))
        return {"rows": rows, "new_count": new_count}

    if action == "sync":
        # Same idea as "backup" -- sync_device() already manages its own
        # connection + device_lock via _pull_raw_with_retry, so this also
        # goes before the generic block. Mirrors webapp.py's
        # device_sync_one ("Sincronizar este" button) for a local device.
        new_count = sync_device(session, device)
        return {"new_count": new_count}

    # Every action below opens its OWN direct pyzk connection, unlike
    # "backup"/"sync" above -- needs the same device_lock those already
    # get indirectly, or a command queued from the central panel could
    # collide with a scheduled _run_sync() or a click on this agent's own
    # local status page landing on the same device at the same moment
    # (the device only accepts one live session).
    device_lock.acquire(device.id, device.name, owner="remote_agent")
    try:
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
            if action == "restart":
                system.restart_device()
                return None
            if action == "poweroff":
                system.poweroff_device()
                return None
            if action == "clear_attendance":
                system.clear_attendance_log()
                return None
            if action == "list_users":
                return system.list_device_users()
            if action == "get_user":
                user_id = str(params["user_id"])
                return next((u for u in system.list_device_users() if str(u["user_id"]) == user_id), None)
            if action == "create_or_update_user":
                return system.create_or_update_user(
                    user_id=params["user_id"], name=params["name"],
                    privilege=params.get("privilege", 0),
                    card=params.get("card", 0), password=params.get("password"),
                )
            if action == "delete_user":
                system.delete_device_user(params["user_id"])
                return None
            raise ValueError(f"Acción desconocida para el agente remoto: '{action}'.")
        finally:
            system.disconnect()
    finally:
        device_lock.release(device.id)


def _process_one(session, cmd):
    device = session.get(Device, cmd.device_pk)
    cmd.picked_up_at = datetime.utcnow()
    session.commit()
    try:
        if not device:
            raise RuntimeError(f"device_pk={cmd.device_pk} ya no existe.")
        params = json.loads(cmd.params) if cmd.params else {}
        result = _run_action(session, device, cmd.action, params)
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


def _start_status_page(agent_name):
    """Página de estado de solo lectura en un hilo de fondo -- ver
    central/remote_agent_status.py para qué muestra y por qué es una
    página propia en vez de reusar central/webapp.py. AGENT_STATUS_PORT
    (default 5050, deliberadamente distinto del 5000 del panel central
    por si alguna vez conviven en la misma máquina) -- poner en "" o "0"
    la desactiva por completo."""
    port_raw = os.environ.get("AGENT_STATUS_PORT", "5050")
    if not port_raw or port_raw == "0":
        return
    port = int(port_raw)

    def run():
        # Esto corre en una Tarea Programada (SYSTEM, sin consola
        # visible) -- si algo acá adentro revienta, un hilo normal se
        # muere en silencio y nadie se entera (pasó de verdad en esta
        # sesión: la página nunca arrancó y no quedó ningún rastro de
        # por qué). Por eso cualquier excepción se guarda en un archivo
        # junto a la instalación, no solo se imprime a un stdout que
        # nadie lee.
        try:
            import waitress
            from central import remote_agent_status
            remote_agent_status.app.config["AGENT_NAME"] = agent_name
            print(f"[remote_agent] página de estado en http://0.0.0.0:{port}", flush=True)
            waitress.serve(remote_agent_status.app, host="0.0.0.0", port=port, threads=4)
        except Exception:
            import traceback
            error_path = os.path.join(PROJECT_ROOT, "pagina_estado_error.log")
            with open(error_path, "a", encoding="utf-8") as f:
                f.write(f"\n--- {datetime.now().isoformat(timespec='seconds')} ---\n")
                f.write(traceback.format_exc())
            print(f"[remote_agent] la página de estado no pudo arrancar -- ver {error_path}", flush=True)

    threading.Thread(target=run, daemon=True).start()


def main():
    agent_name = os.environ.get("AGENT_NAME")
    if not agent_name:
        print("Falta la variable de entorno AGENT_NAME.", file=sys.stderr)
        sys.exit(1)
    init_db()
    _start_status_page(agent_name)

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
