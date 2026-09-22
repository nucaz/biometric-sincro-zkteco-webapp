from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, DateTime, Date, Time, ForeignKey, UniqueConstraint, Text, Boolean
)
from sqlalchemy.orm import relationship
from .db import Base


def utcnow():
    return datetime.now(timezone.utc)


class Device(Base):
    """A physical biometric terminal. device_id is the stable identity
    (the terminal's own serial number when known, otherwise ip:port) so
    renaming a device or changing its IP never orphans its history."""
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True)
    device_id = Column(String(64), unique=True, nullable=False)
    name = Column(String(120), nullable=False)
    sede = Column(String(120), nullable=True)  # branch / location label for HR filtering
    ip = Column(String(64), nullable=False)
    port = Column(Integer, nullable=False, default=4370)
    comm_password = Column(Integer, nullable=False, default=0)  # ZK "comm key" -- 0 means none set
    terminal_no = Column(Integer, nullable=True)  # ZKTeco's own device-number label, informational only
    model = Column(String(64), nullable=True)
    active = Column(Integer, nullable=False, default=1)  # 1/0, avoid polling retired devices
    deleted = Column(Boolean, nullable=False, default=False)  # hidden from the devices list/sync, but the row (and its history) is never actually dropped -- see device_delete()
    last_synced_at = Column(DateTime, nullable=True)
    last_sync_status = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    logs = relationship("AttendanceLog", back_populates="device")
    employee_links = relationship("EmployeeMap", back_populates="device")


class DeviceLock(Base):
    """Cross-process advisory lock for one physical device -- a ZK terminal
    only accepts one live session at a time, and the web app (waitress)
    and a scheduled `python -m central.sync` run are separate OS
    processes that can't see each other's in-memory state, so this has to
    live in the shared DB instead of a plain threading.Lock. See
    central/device_lock.py for acquire/release; a lock older than its
    staleness window is treated as abandoned (the process that took it
    died or leaked past central.webapp's own hard timeout) and can be
    taken over instead of blocking forever."""
    __tablename__ = "device_locks"

    device_pk = Column(Integer, primary_key=True)
    locked_at = Column(DateTime, nullable=False)
    locked_by = Column(String(150), nullable=True)  # hostname:pid, best-effort, for diagnostics only


class AttendanceLog(Base):
    """One raw punch. device_user_id is the ID as enrolled on that specific
    device -- it is only unique WITHIN a device, never across devices, so
    every query/join must go through (device_id, device_user_id) together."""
    __tablename__ = "attendance_log"
    __table_args__ = (
        UniqueConstraint("device_pk", "device_user_id", "timestamp", name="uq_device_user_ts"),
    )

    id = Column(Integer, primary_key=True)
    device_pk = Column(Integer, ForeignKey("devices.id"), nullable=False)
    device_user_id = Column(String(32), nullable=False)
    user_name = Column(String(120), nullable=True)  # name as reported by the device at sync time
    # Indexed on its own (not just as part of uq_device_user_ts) -- reports
    # now scan by date range across every device/employee at once instead
    # of one device_pk + device_user_id at a time.
    timestamp = Column(DateTime, nullable=False, index=True)
    status = Column(String(32), nullable=True)  # 'Check In' / 'Check Out' / 'Unknown Punch (n)'
    synced_at = Column(DateTime, default=utcnow, nullable=False)

    device = relationship("Device", back_populates="logs")


class Employee(Base):
    """Master employee record, independent of any one device. One employee
    can be linked (via EmployeeMap) to a different device_user_id at every
    sede they're enrolled in. `code` is the DNI by convention -- it's what
    a device's own user_id/ID usually already is, so a matching code is
    how employees_unmapped() suggests a link.

    `nombre`/`apellido_paterno`/`apellido_materno` are optional and purely
    additive: when any of them is filled, webapp.py recomputes `full_name`
    from them on save (nombre + apellido_paterno + apellido_materno). When
    they're left blank, `full_name` stays whatever was typed directly --
    this keeps the original one-field quick-add working for an employee
    who doesn't need (or have) a structured name on file."""
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True)
    code = Column(String(32), unique=True, nullable=True)  # DNI, by convention -- see class docstring
    full_name = Column(String(120), nullable=False)
    nombre = Column(String(80), nullable=True)
    apellido_paterno = Column(String(80), nullable=True)
    apellido_materno = Column(String(80), nullable=True)
    fecha_nacimiento = Column(Date, nullable=True)
    celular = Column(String(32), nullable=True)
    correo_personal = Column(String(120), nullable=True)
    correo_corporativo = Column(String(120), nullable=True)
    direccion = Column(String(255), nullable=True)
    area = Column(String(80), nullable=True)
    # Independent of which device/sede the employee actually punches at
    # (that's EmployeeMap -> Device.sede, used by every attendance report's
    # sede filter, and untouched by this field) -- this is the sede they
    # administratively belong to, editable even before they have any
    # device link at all.
    sede = Column(String(120), nullable=True)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    device_links = relationship("EmployeeMap", back_populates="employee")
    schedule_assignments = relationship(
        "EmployeeSchedule", back_populates="employee",
        order_by="EmployeeSchedule.effective_from.desc()",
    )
    exceptions = relationship(
        "AttendanceException", back_populates="employee",
        order_by="AttendanceException.date_from.desc()",
    )


class EmployeeMap(Base):
    """Links a (device, device_user_id) pair -- the identity as enrolled on
    one specific terminal -- to a canonical Employee. Until HR fills this
    in, the dashboard just falls back to the device's own reported
    user_name (often "NN-<id>" for users enrolled without a name)."""
    __tablename__ = "employee_map"
    __table_args__ = (
        UniqueConstraint("device_pk", "device_user_id", name="uq_employee_map_device_user"),
    )

    id = Column(Integer, primary_key=True)
    device_pk = Column(Integer, ForeignKey("devices.id"), nullable=False)
    device_user_id = Column(String(32), nullable=False)
    # Indexed -- attendance reports join AttendanceLog -> EmployeeMap and
    # then filter/group by employee_id across a date range.
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)

    device = relationship("Device", back_populates="employee_links")
    employee = relationship("Employee", back_populates="device_links")


class User(Base):
    """An account that can log into the HR web dashboard (distinct from
    Employee / device users -- this is who's allowed to operate the tool)."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(16), nullable=False, default="viewer")  # 'super_admin' | 'admin' | 'viewer'
    active = Column(Boolean, nullable=False, default=True)
    totp_secret = Column(String(64), nullable=True)
    totp_enabled = Column(Boolean, nullable=False, default=False)
    failed_login_attempts = Column(Integer, nullable=False, default=0)
    locked = Column(Boolean, nullable=False, default=False)  # true after too many failed attempts in a row; only a super_admin can clear this
    created_at = Column(DateTime, default=utcnow, nullable=False)

    trusted_devices = relationship("TrustedDevice", back_populates="user")


class AuditLog(Base):
    """Who did what, from where. Written on every login (success/failure)
    and every write action (device/employee/user/backup changes) -- never
    edited or deleted through the app itself, only appended to."""
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True)
    # Deliberately the server's LOCAL clock, not UTC (unlike every other
    # timestamp in this file) -- this table exists for a person to read
    # directly, and showing it 5 hours off from the Windows clock right in
    # front of them (Peru is UTC-5) was confusing enough to get reported
    # as a bug on its own.
    timestamp = Column(DateTime, default=datetime.now, nullable=False)
    username = Column(String(64), nullable=True)  # null for a failed login with an unknown/bad username
    action = Column(String(64), nullable=False)  # e.g. 'login', 'login_failed', 'device_add', 'device_sync', ...
    target = Column(String(200), nullable=True)  # what it acted on, e.g. a device or employee name
    detail = Column(Text, nullable=True)  # extra context, e.g. an error message or what changed
    ip_address = Column(String(64), nullable=True)
    hostname = Column(String(200), nullable=True)  # best-effort reverse DNS of ip_address, see central/audit.py
    user_agent = Column(String(255), nullable=True)


class RoleModule(Base):
    """Explicit override of whether one module is open to one role
    ('viewer' or 'admin' only -- super_admin always sees every module, by
    design, so they can never lock themselves out of managing this very
    screen). Absence of a row means "use the built-in default" (see
    auth.DEFAULT_MODULE_ACCESS) -- NOT "enabled": employees/employees_
    unmapped default OFF for viewer, same as before this feature existed,
    so installing it never silently opens something up nobody configured.
    See central/auth.py (module_required) for where this is enforced and
    the /permissions screen that manages it."""
    __tablename__ = "role_modules"
    __table_args__ = (
        UniqueConstraint("role", "module", name="uq_role_module"),
    )

    id = Column(Integer, primary_key=True)
    role = Column(String(16), nullable=False)
    module = Column(String(32), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)


class Schedule(Base):
    """A configurable type of shift ('horario') -- a super_admin/admin
    manages these from /schedules. Each one carries its OWN tardiness
    tolerance and lunch window rather than a single company-wide rule,
    and its own explicit day-of-week flags rather than a fixed L-V/L-S
    preset -- different areas/stores/branches were confirmed to have work
    weeks that don't follow a common pattern (e.g. rest day varies by
    store agreement), so every weekday needs its own on/off flag."""
    __tablename__ = "schedules"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    entry_time = Column(Time, nullable=False)
    tolerance_minutes = Column(Integer, nullable=False, default=0)
    # Nullable at the DB level even though the form always requires it --
    # a schedule created before this field existed has NULL here until
    # someone opens it in /schedules and saves it again, and the
    # attendance engine has to degrade gracefully (no overtime evaluated)
    # instead of crashing on that old row.
    exit_time = Column(Time, nullable=True)
    lunch_start = Column(Time, nullable=True)
    lunch_end = Column(Time, nullable=True)
    work_mon = Column(Boolean, nullable=False, default=True)
    work_tue = Column(Boolean, nullable=False, default=True)
    work_wed = Column(Boolean, nullable=False, default=True)
    work_thu = Column(Boolean, nullable=False, default=True)
    work_fri = Column(Boolean, nullable=False, default=True)
    work_sat = Column(Boolean, nullable=False, default=False)
    work_sun = Column(Boolean, nullable=False, default=False)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    assignments = relationship("EmployeeSchedule", back_populates="schedule")

    # Index 0 = Monday, matching date.weekday() -- see works_on().
    WEEKDAY_FIELDS = (
        "work_mon", "work_tue", "work_wed", "work_thu",
        "work_fri", "work_sat", "work_sun",
    )

    def works_on(self, date_):
        return bool(getattr(self, self.WEEKDAY_FIELDS[date_.weekday()]))


class EmployeeSchedule(Base):
    """One period during which an employee had a given schedule assigned.
    effective_to is null for the currently active assignment -- assigning
    a new schedule closes the previous open-ended row first (see
    central/webapp.py's employee_schedule_assign), so "what schedule did
    employee X have on date Y" is always exactly one row, never an
    overlap to disambiguate."""
    __tablename__ = "employee_schedules"

    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False)
    schedule_id = Column(Integer, ForeignKey("schedules.id"), nullable=False)
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    employee = relationship("Employee", back_populates="schedule_assignments")
    schedule = relationship("Schedule", back_populates="assignments")


class AttendanceException(Base):
    """A justified absence -- vacation, permission, or medical leave.
    Every calendar day inside [date_from, date_to] for this employee is
    excluded from the 'falta' count in attendance_rules.compute_attendance
    and shown as 'justificado' instead. Deliberately has no approval
    workflow of its own -- whoever can already manage employees can add
    one, same trust boundary as the rest of the employee master data."""
    __tablename__ = "attendance_exceptions"

    KINDS = ("vacaciones", "permiso", "descanso_medico", "otro")

    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    date_from = Column(Date, nullable=False)
    date_to = Column(Date, nullable=False)
    kind = Column(String(20), nullable=False)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    employee = relationship("Employee", back_populates="exceptions")


class TrustedDevice(Base):
    """A browser that skipped OTP on its last login because it already
    proved the 6-digit code once. Identified by the hash of a random
    token in a long-lived cookie -- never the raw token itself."""
    __tablename__ = "trusted_devices"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    token_hash = Column(String(255), nullable=False)
    label = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)

    user = relationship("User", back_populates="trusted_devices")
