from functools import wraps
from flask import session as flask_session, redirect, url_for, request, abort
from werkzeug.security import generate_password_hash, check_password_hash

from central.db import SessionLocal
from central.models import User

# super_admin: everything, including web-app accounts and backup/restore.
# admin: devices, employees, sync -- day-to-day operation, not accounts/backup.
# viewer: read-only -- dashboard, device status, exports. No writes anywhere.
ROLES = ("super_admin", "admin", "viewer")
ROLE_LABELS = {"super_admin": "Super administrador", "admin": "Administrador", "viewer": "Solo lectura"}


def hash_password(raw):
    return generate_password_hash(raw)


def verify_password(raw, hashed):
    return check_password_hash(hashed, raw)


def current_user():
    if "user_id" not in flask_session:
        return None
    db = SessionLocal()
    try:
        return db.get(User, flask_session["user_id"])
    finally:
        db.close()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in flask_session:
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def role_required(*roles):
    """Restrict a view to one or more roles (e.g. role_required('admin', 'super_admin'))."""
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if "user_id" not in flask_session:
                return redirect(url_for("login", next=request.path))
            if flask_session.get("role") not in roles:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


# Device/employee management: admin and super_admin.
admin_required = role_required("admin", "super_admin")
# Accounts and backup/restore: super_admin only.
super_admin_required = role_required("super_admin")
