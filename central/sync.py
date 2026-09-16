"""
Pulls attendance from every active device in the central `devices` table
and upserts new punches into `attendance_log`. Safe to re-run on a
schedule (every 15-30 min via Task Scheduler / cron) -- already-seen
punches are skipped by (device, device_user_id, timestamp).
"""
import os
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from attendance_system import ZKTecoAttendance, device_lock  # noqa: E402
from central.db import SessionLocal, init_db  # noqa: E402
from central.models import Device, AttendanceLog, utcnow  # noqa: E402

# Pulling the full attendance log is a much bigger transfer than a quick
# "probar conexion" handshake -- some devices (flaky link, VPN between
# sedes, a large backlog) need more than the 5s default timeout, and an
# occasional "TCP packet invalid" mid-transfer is usually transient and
# resolves itself on a clean retry rather than being a real device fault.
SYNC_TIMEOUT_SECONDS = 20
MAX_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 3


def _noop(msg):
    pass


def _pull_raw_with_retry(device: Device, progress=None):
    """Connects to `device` and downloads its full current attendance log
    (always ALL of it -- the ZK protocol has no "since X" query, there's
    nothing partial to ask for), retrying a couple of times on transient
    protocol errors (e.g. "TCP packet invalid") before giving up. Returns
    the raw DataFrame (or None if the device genuinely has zero records
    right now) -- does NOT touch the central DB."""
    progress = progress or _noop
    lock = device_lock((device.ip, device.port))
    if not lock.acquire(blocking=False):
        raise RuntimeError(
            f"'{device.name}' ya tiene otra operación en curso (otra sincronización, "
            "una prueba de conexión, etc.) -- se omite esta vuelta en vez de sumar "
            "una segunda conexión al mismo equipo."
        )
    try:
        raw = None
        last_error = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            prefix = f"(intento {attempt}/{MAX_ATTEMPTS}) " if attempt > 1 else ""
            progress(f"{prefix}Conectando a '{device.name}' ({device.ip}:{device.port})...")
            system = ZKTecoAttendance(
                device.ip, port=device.port, password=device.comm_password or 0,
                timeout=SYNC_TIMEOUT_SECONDS,
            )
            try:
                system.connect()
                if not system.conn:
                    last_error = system.last_connect_error or "Connection failed"
                    raise RuntimeError(last_error)
                progress(f"Conectado. Descargando marcaciones de '{device.name}'... (puede tardar según cuántas tenga)")
                raw = system.get_raw_attendance(device_name=device.name)
                model = system.device_info.get('model', '').strip()
                if model and model != device.model:
                    device.model = model
                last_error = None
                break
            except Exception as e:
                last_error = str(e)
                progress(f"Error en el intento {attempt}: {last_error}")
            finally:
                system.disconnect()
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_DELAY_SECONDS)

        if last_error is not None:
            raise RuntimeError(last_error)
        return raw
    finally:
        lock.release()


def _insert_new_rows(session, device: Device, raw, progress=None) -> int:
    """Dedup-insert `raw` (a DataFrame from `_pull_raw_with_retry`) into
    `attendance_log` by (device, device_user_id, timestamp), and update
    the device's last-sync bookkeeping. Returns how many rows were
    actually new (records already present are silently skipped)."""
    progress = progress or _noop

    if raw is None or raw.empty:
        progress(f"'{device.name}' no tiene marcaciones nuevas que descargar (0 en el dispositivo o ya estaban todas).")
        device.last_synced_at = utcnow()
        device.last_sync_status = "OK - 0 new records"
        session.commit()
        return 0

    total_pulled = len(raw)
    progress(f"Descargadas {total_pulled} marcación(es) de '{device.name}'. Comparando contra la base central para no duplicar...")

    min_ts, max_ts = raw['timestamp'].min(), raw['timestamp'].max()
    existing = session.query(AttendanceLog.device_user_id, AttendanceLog.timestamp).filter(
        AttendanceLog.device_pk == device.id,
        AttendanceLog.timestamp >= min_ts,
        AttendanceLog.timestamp <= max_ts,
    ).all()
    seen = {(str(uid), ts) for uid, ts in existing}

    new_rows = []
    for _, row in raw.iterrows():
        ts = row['timestamp']
        ts = ts.to_pydatetime() if hasattr(ts, 'to_pydatetime') else ts
        key = (str(row['user_id']), ts)
        if key in seen:
            continue
        seen.add(key)  # guard against duplicate punches within this same pull
        new_rows.append(AttendanceLog(
            device_pk=device.id,
            device_user_id=str(row['user_id']),
            user_name=row['user_name'],
            timestamp=ts,
            status=row['status'],
        ))

    if new_rows:
        progress(f"Guardando {len(new_rows)} registro(s) nuevo(s) en la base central...")
        session.bulk_save_objects(new_rows)
    device.last_synced_at = utcnow()
    device.last_sync_status = f"OK - {len(new_rows)} new records"
    session.commit()
    progress(f"Listo: {len(new_rows)} nuevo(s) de {total_pulled} descargado(s) del dispositivo.")
    return len(new_rows)


def sync_device(session, device: Device, progress=None) -> int:
    """Pull all punches currently on `device` and insert the ones not
    already in the central DB. Returns how many new rows were inserted.
    `progress(msg)`, if given, is called with a short status line at each
    stage -- used to drive the live progress view in the web panel."""
    progress = progress or _noop
    try:
        raw = _pull_raw_with_retry(device, progress)
    except RuntimeError as e:
        device.last_synced_at = utcnow()
        device.last_sync_status = f"Error: {e}"
        session.commit()
        raise
    return _insert_new_rows(session, device, raw, progress)


def backup_device(session, device: Device, progress=None):
    """Like `sync_device` (one connection to the device, same dedup-insert
    of anything new into the central DB so nothing is lost), but also
    returns the raw DataFrame of EVERY punch currently stored on the
    physical device -- meant to be handed to the user as a downloadable
    file right before "Vaciar dispositivo", as an independent snapshot
    that doesn't depend on trusting the central DB's dedup logic. Returns
    (raw_dataframe_or_None, new_rows_inserted)."""
    progress = progress or _noop
    try:
        raw = _pull_raw_with_retry(device, progress)
    except RuntimeError as e:
        device.last_synced_at = utcnow()
        device.last_sync_status = f"Error: {e}"
        session.commit()
        raise
    new_count = _insert_new_rows(session, device, raw, progress)
    return raw, new_count


def sync_all(progress=None) -> dict:
    progress = progress or _noop
    init_db()
    session = SessionLocal()
    results = {}
    try:
        devices = session.query(Device).filter(Device.active == 1, Device.deleted.is_(False)).all()
        for i, device in enumerate(devices, start=1):
            progress(f"[{i}/{len(devices)}] Sincronizando '{device.name}'...")
            try:
                count = sync_device(session, device, progress=progress)
                results[device.name] = f"{count} new records"
            except Exception as e:
                session.rollback()
                device.last_synced_at = utcnow()
                device.last_sync_status = f"Error: {e}"
                session.commit()
                results[device.name] = f"ERROR: {e}"
                progress(f"'{device.name}' falló: {e}")
    finally:
        session.close()
    return results


if __name__ == "__main__":
    results = sync_all()
    for name, result in results.items():
        print(f"{name}: {result}")

    # Logged separately from the manual "Sincronizar" button in the web
    # panel (central.webapp) so /audit can tell apart what the scheduled
    # task did on its own from what a person clicked -- without this, a
    # device showing a fresh successful sync in the panel could be
    # confused for the result of someone's manual click when it was
    # actually just the timer running in the background.
    from central.audit import log_event  # noqa: E402 (local import: avoids a hard dependency on Flask for this CLI-only path)
    summary = "; ".join(f"{name}: {result}" for name, result in results.items())
    session = SessionLocal()
    try:
        log_event(session, "sync_all", username=None, detail=summary,
                  ip="(tarea programada)", hostname="", user_agent="")
        session.commit()
    finally:
        session.close()
