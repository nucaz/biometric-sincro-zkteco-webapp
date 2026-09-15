"""
Full JSON export/import of the central database. Portable across SQLite,
PostgreSQL and MySQL (it doesn't depend on any engine-specific dump tool),
and human-readable enough to sanity-check before restoring.

WARNING: the exported file contains password hashes for every web-app
account (needed to restore login access) -- treat it as a secret, same as
you would a database credential.
"""
from datetime import datetime, timezone
from central.models import Device, AttendanceLog, Employee, EmployeeMap, User, TrustedDevice

FORMAT_VERSION = 1


def _iso(dt):
    return dt.isoformat() if dt else None


def _parse_dt(s):
    return datetime.fromisoformat(s) if s else None


def export_data(session):
    return {
        "format_version": FORMAT_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "devices": [{
            "id": d.id, "device_id": d.device_id, "name": d.name, "sede": d.sede,
            "ip": d.ip, "port": d.port, "comm_password": d.comm_password,
            "terminal_no": d.terminal_no, "model": d.model, "active": d.active,
            "last_synced_at": _iso(d.last_synced_at), "last_sync_status": d.last_sync_status,
            "created_at": _iso(d.created_at),
        } for d in session.query(Device).all()],
        "employees": [{
            "id": e.id, "code": e.code, "full_name": e.full_name,
            "active": e.active, "created_at": _iso(e.created_at),
        } for e in session.query(Employee).all()],
        "employee_map": [{
            "id": m.id, "device_pk": m.device_pk, "device_user_id": m.device_user_id,
            "employee_id": m.employee_id,
        } for m in session.query(EmployeeMap).all()],
        "attendance_log": [{
            "id": a.id, "device_pk": a.device_pk, "device_user_id": a.device_user_id,
            "user_name": a.user_name, "timestamp": _iso(a.timestamp), "status": a.status,
            "synced_at": _iso(a.synced_at),
        } for a in session.query(AttendanceLog).all()],
        "users": [{
            "id": u.id, "username": u.username, "password_hash": u.password_hash,
            "role": u.role, "active": u.active, "totp_secret": u.totp_secret,
            "totp_enabled": u.totp_enabled, "created_at": _iso(u.created_at),
        } for u in session.query(User).all()],
        "trusted_devices": [{
            "id": t.id, "user_id": t.user_id, "token_hash": t.token_hash,
            "label": t.label, "created_at": _iso(t.created_at), "expires_at": _iso(t.expires_at),
        } for t in session.query(TrustedDevice).all()],
    }


def import_data(session, data):
    """Wipes every table this backup covers and reloads it from `data`.
    Runs inside the caller's transaction -- caller commits or rolls back."""
    if "format_version" not in data:
        raise ValueError("Archivo de backup inválido: falta 'format_version'.")

    # Delete children before parents to respect foreign keys.
    session.query(AttendanceLog).delete()
    session.query(EmployeeMap).delete()
    session.query(TrustedDevice).delete()
    session.query(User).delete()
    session.query(Employee).delete()
    session.query(Device).delete()
    session.flush()

    for d in data.get("devices", []):
        session.add(Device(
            id=d["id"], device_id=d["device_id"], name=d["name"], sede=d.get("sede"),
            ip=d["ip"], port=d["port"], comm_password=d.get("comm_password", 0),
            terminal_no=d.get("terminal_no"), model=d.get("model"), active=d.get("active", 1),
            last_synced_at=_parse_dt(d.get("last_synced_at")), last_sync_status=d.get("last_sync_status"),
            created_at=_parse_dt(d.get("created_at")) or datetime.now(timezone.utc),
        ))
    for e in data.get("employees", []):
        session.add(Employee(
            id=e["id"], code=e.get("code"), full_name=e["full_name"],
            active=e.get("active", True), created_at=_parse_dt(e.get("created_at")) or datetime.now(timezone.utc),
        ))
    session.flush()
    for m in data.get("employee_map", []):
        session.add(EmployeeMap(id=m["id"], device_pk=m["device_pk"], device_user_id=m["device_user_id"], employee_id=m["employee_id"]))
    for a in data.get("attendance_log", []):
        session.add(AttendanceLog(
            id=a["id"], device_pk=a["device_pk"], device_user_id=a["device_user_id"],
            user_name=a.get("user_name"), timestamp=_parse_dt(a["timestamp"]), status=a.get("status"),
            synced_at=_parse_dt(a.get("synced_at")) or datetime.now(timezone.utc),
        ))
    for u in data.get("users", []):
        session.add(User(
            id=u["id"], username=u["username"], password_hash=u["password_hash"],
            role=u.get("role", "viewer"), active=u.get("active", True),
            totp_secret=u.get("totp_secret"), totp_enabled=u.get("totp_enabled", False),
            created_at=_parse_dt(u.get("created_at")) or datetime.now(timezone.utc),
        ))
    session.flush()
    for t in data.get("trusted_devices", []):
        session.add(TrustedDevice(
            id=t["id"], user_id=t["user_id"], token_hash=t["token_hash"], label=t.get("label"),
            created_at=_parse_dt(t.get("created_at")) or datetime.now(timezone.utc),
            expires_at=_parse_dt(t["expires_at"]),
        ))
    session.flush()

    counts = {k: len(data.get(k, [])) for k in ("devices", "employees", "employee_map", "attendance_log", "users", "trusted_devices")}
    return counts
