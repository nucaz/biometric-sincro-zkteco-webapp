"""
Pulls attendance from every active device in the central `devices` table
and upserts new punches into `attendance_log`. Safe to re-run on a
schedule (every 15-30 min via Task Scheduler / cron) -- already-seen
punches are skipped by (device, device_user_id, timestamp).
"""
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from attendance_system import ZKTecoAttendance  # noqa: E402
from central.db import SessionLocal, init_db  # noqa: E402
from central.models import Device, AttendanceLog, utcnow  # noqa: E402


def sync_device(session, device: Device) -> int:
    """Pull all punches currently on `device` and insert the ones we don't
    already have. Returns how many new rows were inserted."""
    system = ZKTecoAttendance(device.ip, port=device.port, password=device.comm_password or 0)
    system.connect()
    if not system.conn:
        device.last_synced_at = utcnow()
        device.last_sync_status = "Connection failed"
        session.commit()
        return 0

    try:
        raw = system.get_raw_attendance(device_name=device.name)
        model = system.device_info.get('model', '').strip()
        if model and model != device.model:
            device.model = model
    finally:
        system.disconnect()

    if raw is None or raw.empty:
        device.last_synced_at = utcnow()
        device.last_sync_status = "OK - 0 new records"
        session.commit()
        return 0

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
        session.bulk_save_objects(new_rows)
    device.last_synced_at = utcnow()
    device.last_sync_status = f"OK - {len(new_rows)} new records"
    session.commit()
    return len(new_rows)


def sync_all() -> dict:
    init_db()
    session = SessionLocal()
    results = {}
    try:
        devices = session.query(Device).filter(Device.active == 1).all()
        for device in devices:
            try:
                count = sync_device(session, device)
                results[device.name] = f"{count} new records"
            except Exception as e:
                session.rollback()
                device.last_synced_at = utcnow()
                device.last_sync_status = f"Error: {e}"
                session.commit()
                results[device.name] = f"ERROR: {e}"
    finally:
        session.close()
    return results


if __name__ == "__main__":
    for name, result in sync_all().items():
        print(f"{name}: {result}")
