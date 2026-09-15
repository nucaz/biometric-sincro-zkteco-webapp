"""
One-time / repeatable import of devices.json (used by the desktop app)
into the central `devices` table. Safe to re-run: matches existing rows
by device_id (falling back to ip:port for legacy entries) and updates
them instead of duplicating.

Usage:
    python -m central.seed_devices
"""
import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from central.db import SessionLocal, init_db  # noqa: E402
from central.models import Device  # noqa: E402

DEVICES_JSON = os.path.join(PROJECT_ROOT, "devices.json")


def seed(sede_by_name=None):
    """sede_by_name: optional {device_name: "Local X"} to tag branch/location
    for devices that devices.json doesn't know about."""
    sede_by_name = sede_by_name or {}
    init_db()
    if not os.path.exists(DEVICES_JSON):
        print(f"No devices.json found at {DEVICES_JSON}")
        return
    with open(DEVICES_JSON, "r") as f:
        devices = json.load(f)

    session = SessionLocal()
    try:
        for d in devices:
            ip, port = d["ip"], d.get("port", 4370)
            device_id = d.get("device_id") or f"{ip}:{port}"
            existing = session.query(Device).filter(Device.device_id == device_id).first()
            if existing:
                existing.name = d["name"]
                existing.ip = ip
                existing.port = port
                existing.model = d.get("model") or existing.model
                if d["name"] in sede_by_name:
                    existing.sede = sede_by_name[d["name"]]
                print(f"Updated: {d['name']} ({device_id})")
            else:
                session.add(Device(
                    device_id=device_id,
                    name=d["name"],
                    ip=ip,
                    port=port,
                    model=d.get("model"),
                    sede=sede_by_name.get(d["name"]),
                ))
                print(f"Added: {d['name']} ({device_id})")
        session.commit()
    finally:
        session.close()


if __name__ == "__main__":
    seed()
