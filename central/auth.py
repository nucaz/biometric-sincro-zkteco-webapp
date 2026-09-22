from functools import wraps
from flask import session as flask_session, redirect, url_for, request, abort, flash
from werkzeug.security import generate_password_hash, check_password_hash

from central.db import SessionLocal
from central.models import User, RoleModule

# super_admin: everything, including web-app accounts and backup/restore.
# admin: devices, employees, sync -- day-to-day operation, not accounts/backup.
# viewer: read-only -- dashboard, device status, exports. No writes anywhere.
ROLES = ("super_admin", "admin", "viewer")
ROLE_LABELS = {"super_admin": "Super administrador", "admin": "Administrador", "viewer": "Solo lectura"}

# Modules a super_admin can show/hide per role from /permissions -- only
# the sections viewer/admin can reach at all; Cuentas/Backup/Auditoría/
# Permisos stay hard-wired to super_admin_required and are never on this
# list, a deliberate boundary (account management and full data export/
# import are privilege-escalation-adjacent, not something to soften with
# a checkbox).
MODULES = {
    "reports_overview": "Panel",
    "dashboard": "Marcaciones",
    "export": "Exportar marcaciones",
    "devices": "Dispositivos",
    "device_users": "Usuarios del dispositivo",
    "employees": "Empleados",
    "employees_unmapped": "Sin vincular",
    "schedules": "Horarios",
    "attendance_exceptions": "Vacaciones y permisos",
    "reports_absences": "Reporte de faltas",
    "reports_hours": "Tardanzas y horas extra",
}
CONFIGURABLE_ROLES = ("viewer", "admin")

# What each role could reach before this permission screen existed --
# module_enabled() falls back to this whenever there's no explicit
# RoleModule override, so installing/upgrading never changes anyone's
# access on its own. Only a super_admin flipping a checkbox in
# /permissions departs from this.
DEFAULT_MODULE_ACCESS = {
    "reports_overview": {"viewer": True, "admin": True},
    "dashboard": {"viewer": True, "admin": True},
    "export": {"viewer": True, "admin": True},
    "devices": {"viewer": True, "admin": True},
    "device_users": {"viewer": False, "admin": True},
    "employees": {"viewer": False, "admin": True},
    "employees_unmapped": {"viewer": False, "admin": True},
    "schedules": {"viewer": False, "admin": True},
    "attendance_exceptions": {"viewer": False, "admin": True},
    "reports_absences": {"viewer": True, "admin": True},
    "reports_hours": {"viewer": True, "admin": True},
}


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


def module_enabled(role, module):
    """Whether `role` can open `module` right now. super_admin always can
    -- the permission matrix only ever narrows viewer/admin, never itself.
    An explicit RoleModule row wins; otherwise falls back to
    DEFAULT_MODULE_ACCESS (i.e. this app's behavior before /permissions
    existed)."""
    if role not in CONFIGURABLE_ROLES:
        return True
    db = SessionLocal()
    try:
        override = db.query(RoleModule).filter(
            RoleModule.role == role, RoleModule.module == module
        ).first()
        if override is not None:
            return override.enabled
        return DEFAULT_MODULE_ACCESS.get(module, {}).get(role, False)
    finally:
        db.close()


def module_required(module):
    """Gate a module's *view* route behind /permissions, on top of
    login_required. Only ever narrows what a role could already reach --
    it never grants a write route access it doesn't already have
    (create/edit/delete routes keep their own admin_required/
    super_admin_required untouched), so turning a module on for 'viewer'
    only ever exposes whatever that page already shows a non-manager
    (guarded by the `can_manage` flag inside the template itself)."""
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if "user_id" not in flask_session:
                return redirect(url_for("login", next=request.path))
            if not module_enabled(flask_session.get("role"), module):
                flash("No tienes acceso a este módulo. Pide a un super administrador que te lo habilite en Permisos.")
                return redirect(url_for("account_security"))
            return view(*args, **kwargs)
        return wrapped
    return decorator
