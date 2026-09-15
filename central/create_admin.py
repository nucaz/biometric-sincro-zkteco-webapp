"""
Bootstrap the first admin account for the web dashboard.

Usage:
    python -m central.create_admin <username> <password>
"""
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from central.db import SessionLocal, init_db  # noqa: E402
from central.models import User  # noqa: E402
from central.auth import hash_password  # noqa: E402


def create_admin(username, password, role="super_admin"):
    init_db()
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.username == username).first()
        if existing:
            existing.password_hash = hash_password(password)
            existing.role = role
            existing.active = True
            db.commit()
            print(f"Updated existing user '{username}' (role={role}).")
        else:
            db.add(User(username=username, password_hash=hash_password(password), role=role))
            db.commit()
            print(f"Created user '{username}' (role={role}).")
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python -m central.create_admin <username> <password> [role]")
        sys.exit(1)
    role = sys.argv[3] if len(sys.argv) > 3 else "super_admin"
    create_admin(sys.argv[1], sys.argv[2], role)
