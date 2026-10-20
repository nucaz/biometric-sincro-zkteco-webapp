"""
JSON API (token auth, never the cookie session every human screen uses)
for machine-to-machine integration -- the first and only consumer
planned right now is a separate "planillas y tareo" web app being built
in parallel, which needs both to READ (marcaciones/faltas/tardanzas/
empleados) and WRITE (horarios/empleados) here. See CLAUDE.md.

Deliberately a separate Blueprint/module instead of more routes bolted
onto the already-large central/webapp.py. Imports FROM central.webapp
(the shared form-parsing helpers: _employee_profile_fields_from_form,
_schedule_fields_from_form, _assign_schedule, _parse_date_field,
WEEKDAY_FORM_FIELDS) are deliberately deferred to inside each route
function, not at module load time -- webapp.py imports this module to
register the blueprint, so a top-level import here would be circular.
Reusing those functions (instead of re-implementing the same field
rules here) is the whole point: a quirk fixed there -- e.g. the
"don't blank out a field the row didn't mention" rule, or how
full_name gets recomputed from nombre/apellidos -- is fixed here too,
automatically, not a second copy to remember to update.
"""
import hashlib
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify, g

from central.db import SessionLocal
from central.models import (
    ApiToken, AttendanceLog, Device, Employee, EmployeeMap, EmployeeSchedule, Schedule,
)
from central import attendance_rules
from central.audit import log_event

api = Blueprint("api", __name__, url_prefix="/api/v1")

MAX_RANGE_DAYS = 186
DEFAULT_RANGE_DAYS = 7
MAX_LIMIT = 5000
DEFAULT_LIMIT = 1000


def generate_token():
    """Returns (raw_token, token_hash) for a brand-new token. The raw
    value must be shown to the caller immediately and never stored --
    only the hash persists (see ApiToken's docstring in models.py)."""
    raw = secrets.token_urlsafe(32)
    return raw, hashlib.sha256(raw.encode()).hexdigest()


def _hash_token(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def _error(message, status):
    return jsonify({"error": message}), status


def api_token_required(scope):
    """scope: 'read' or 'write'. A write-scoped token can also hit
    read-scoped routes (write implies read); a read-only token gets 403
    on a write route."""
    def decorator(fn):
        def wrapped(*args, **kwargs):
            auth = request.headers.get("Authorization", "")
            if not auth.startswith("Bearer "):
                return _error("Falta el encabezado 'Authorization: Bearer <token>'.", 401)
            raw = auth[len("Bearer "):].strip()
            if not raw:
                return _error("Token vacío.", 401)
            db = SessionLocal()
            try:
                token = db.query(ApiToken).filter(ApiToken.token_hash == _hash_token(raw)).first()
                if not token or not token.active:
                    return _error("Token inválido o revocado.", 401)
                if scope == "write" and not token.scope_write:
                    return _error("Este token no tiene permiso de escritura.", 403)
                if scope == "read" and not (token.scope_read or token.scope_write):
                    return _error("Este token no tiene permiso de lectura.", 403)
                token.last_used_at = datetime.utcnow()
                db.commit()
                g.api_token_name = token.name
            finally:
                db.close()
            return fn(*args, **kwargs)
        wrapped.__name__ = fn.__name__
        return wrapped
    return decorator


def _api_audit(action, target=None, detail=None):
    # Separate connection from the route's own `db` session (that one
    # may already be mid-transaction or closed by the time this runs) --
    # same reasoning as _audit()/_audit_context() in central/webapp.py.
    db = SessionLocal()
    try:
        log_event(
            db, action, username=f"API:{g.get('api_token_name', '?')}",
            target=target, detail=detail, ip=request.remote_addr or "",
            hostname="", user_agent=request.headers.get("User-Agent", "")[:255],
        )
        db.commit()
    finally:
        db.close()


def _as_api_form(data):
    """Adapts a JSON request body (a plain dict, values of any JSON type)
    into what the existing form-parsing helpers expect: plain
    dict.get(key, default) with string values, same as Flask's
    request.form. A JSON `null` is dropped entirely (treated as "field
    not provided") rather than passed through as Python None, which
    those helpers don't guard against (they call .strip() on whatever
    .get() returns)."""
    out = {}
    for k, v in (data or {}).items():
        if v is None:
            continue
        out[k] = v if isinstance(v, str) else str(v)
    return out


def _date_range_params(args):
    today = datetime.now().date()
    try:
        start = datetime.strptime(args.get("start"), "%Y-%m-%d").date() if args.get("start") else today - timedelta(days=DEFAULT_RANGE_DAYS)
        end = datetime.strptime(args.get("end"), "%Y-%m-%d").date() if args.get("end") else today
    except ValueError:
        return None, None, _error("Fechas inválidas, usa AAAA-MM-DD.", 400)
    if end < start:
        start, end = end, start
    if (end - start).days > MAX_RANGE_DAYS:
        end = start + timedelta(days=MAX_RANGE_DAYS)
    return start, end, None


def _limit_offset(args):
    try:
        limit = min(MAX_LIMIT, max(1, int(args.get("limit", DEFAULT_LIMIT))))
        offset = max(0, int(args.get("offset", 0)))
    except ValueError:
        limit, offset = DEFAULT_LIMIT, 0
    return limit, offset


def _employee_to_dict(e):
    return {
        "id": e.id, "code": e.code, "full_name": e.full_name,
        "nombre": e.nombre, "apellido_paterno": e.apellido_paterno, "apellido_materno": e.apellido_materno,
        "fecha_nacimiento": e.fecha_nacimiento.isoformat() if e.fecha_nacimiento else None,
        "celular": e.celular, "correo_personal": e.correo_personal, "correo_corporativo": e.correo_corporativo,
        "direccion": e.direccion, "area": e.area, "sede": e.sede, "active": e.active,
    }


def _schedule_to_dict(s):
    return {
        "id": s.id, "name": s.name,
        "entry_time": s.entry_time.strftime("%H:%M") if s.entry_time else None,
        "exit_time": s.exit_time.strftime("%H:%M") if s.exit_time else None,
        "tolerance_minutes": s.tolerance_minutes,
        "lunch_start": s.lunch_start.strftime("%H:%M") if s.lunch_start else None,
        "lunch_end": s.lunch_end.strftime("%H:%M") if s.lunch_end else None,
        "work_days": [
            day for day, field in zip(
                ("lun", "mar", "mie", "jue", "vie", "sab", "dom"), Schedule.WEEKDAY_FIELDS
            ) if getattr(s, field)
        ],
        "active": s.active,
    }


# ----------------------------------------------------------- empleados --

@api.route("/employees", methods=["GET"])
@api_token_required("read")
def api_employees_list():
    db = SessionLocal()
    try:
        q = db.query(Employee)
        if request.args.get("active") == "true":
            q = q.filter(Employee.active.is_(True))
        limit, offset = _limit_offset(request.args)
        rows = q.order_by(Employee.id).offset(offset).limit(limit).all()
        return jsonify({"count": len(rows), "results": [_employee_to_dict(e) for e in rows]})
    finally:
        db.close()


@api.route("/employees/<int:employee_id>", methods=["GET"])
@api_token_required("read")
def api_employee_get(employee_id):
    db = SessionLocal()
    try:
        emp = db.get(Employee, employee_id)
        if not emp:
            return _error("Empleado no encontrado.", 404)
        return jsonify(_employee_to_dict(emp))
    finally:
        db.close()


@api.route("/employees", methods=["POST"])
@api_token_required("write")
def api_employee_create():
    from central.webapp import _employee_profile_fields_from_form
    data = request.get_json(silent=True) or {}
    db = SessionLocal()
    try:
        code = (data.get("code") or "").strip() or None
        if code and db.query(Employee).filter(Employee.code == code).first():
            return _error(f"Ya existe un empleado con código '{code}'.", 409)
        fields = _employee_profile_fields_from_form(_as_api_form(data))
        if not fields["full_name"]:
            return _error("Falta 'full_name', o 'nombre'/'apellido_paterno'/'apellido_materno'.", 400)
        emp = Employee(code=code, active=bool(data.get("active", True)), **fields)
        db.add(emp)
        db.commit()
        _api_audit("api_employee_add", target=emp.full_name)
        return jsonify(_employee_to_dict(emp)), 201
    finally:
        db.close()


@api.route("/employees/<int:employee_id>", methods=["PUT", "PATCH"])
@api_token_required("write")
def api_employee_update(employee_id):
    from central.webapp import _employee_profile_fields_from_form
    data = request.get_json(silent=True) or {}
    db = SessionLocal()
    try:
        emp = db.get(Employee, employee_id)
        if not emp:
            return _error("Empleado no encontrado.", 404)
        if "code" in data:
            new_code = (data.get("code") or "").strip() or None
            if new_code and new_code != emp.code and db.query(Employee).filter(Employee.code == new_code).first():
                return _error(f"Ya existe un empleado con código '{new_code}'.", 409)
            emp.code = new_code
        # Same "only overwrite what was actually sent" rule as the Excel
        # import -- a field this request didn't mention must never get
        # silently blanked out.
        fields = _employee_profile_fields_from_form(_as_api_form(data))
        for key, value in fields.items():
            if key == "full_name" and not value:
                continue  # never blank the name out via a partial update
            if value is not None or key in data:
                setattr(emp, key, value)
        if "active" in data:
            emp.active = bool(data["active"])
        db.commit()
        _api_audit("api_employee_edit", target=emp.full_name)
        return jsonify(_employee_to_dict(emp))
    finally:
        db.close()


# ------------------------------------------------------------- horarios --

@api.route("/schedules", methods=["GET"])
@api_token_required("read")
def api_schedules_list():
    db = SessionLocal()
    try:
        q = db.query(Schedule)
        if request.args.get("active") == "true":
            q = q.filter(Schedule.active.is_(True))
        return jsonify({"results": [_schedule_to_dict(s) for s in q.order_by(Schedule.id).all()]})
    finally:
        db.close()


@api.route("/schedules", methods=["POST"])
@api_token_required("write")
def api_schedule_create():
    from central.webapp import _schedule_fields_from_form
    data = request.get_json(silent=True) or {}
    db = SessionLocal()
    try:
        try:
            fields = _schedule_fields_from_form(_as_api_form(data))
        except ValueError as e:
            return _error(str(e), 400)
        schedule = Schedule(active=True, **fields)
        db.add(schedule)
        db.commit()
        _api_audit("api_schedule_add", target=schedule.name)
        return jsonify(_schedule_to_dict(schedule)), 201
    finally:
        db.close()


@api.route("/schedules/<int:schedule_id>", methods=["PUT", "PATCH"])
@api_token_required("write")
def api_schedule_update(schedule_id):
    from central.webapp import _schedule_fields_from_form, WEEKDAY_FORM_FIELDS
    data = request.get_json(silent=True) or {}
    db = SessionLocal()
    try:
        schedule = db.get(Schedule, schedule_id)
        if not schedule:
            return _error("Horario no encontrado.", 404)
        # _schedule_fields_from_form requires every field (it's built for
        # a full form submit, not a partial PATCH) -- seed it with the
        # schedule's current values first so an update can send just the
        # one field that's changing.
        current = {
            "name": schedule.name,
            "entry_time": schedule.entry_time.strftime("%H:%M"),
            "exit_time": schedule.exit_time.strftime("%H:%M") if schedule.exit_time else "",
            "tolerance_minutes": schedule.tolerance_minutes,
            "lunch_start": schedule.lunch_start.strftime("%H:%M") if schedule.lunch_start else "",
            "lunch_end": schedule.lunch_end.strftime("%H:%M") if schedule.lunch_end else "",
        }
        for key, _ in WEEKDAY_FORM_FIELDS:
            current[key] = getattr(schedule, key)
        current.update(_as_api_form(data))
        try:
            fields = _schedule_fields_from_form(current)
        except ValueError as e:
            return _error(str(e), 400)
        for key, value in fields.items():
            setattr(schedule, key, value)
        if "active" in data:
            schedule.active = bool(data["active"])
        db.commit()
        _api_audit("api_schedule_edit", target=schedule.name)
        return jsonify(_schedule_to_dict(schedule))
    finally:
        db.close()


@api.route("/employees/<int:employee_id>/schedule", methods=["POST"])
@api_token_required("write")
def api_employee_schedule_assign(employee_id):
    from central.webapp import _assign_schedule, _parse_date_field
    data = request.get_json(silent=True) or {}
    db = SessionLocal()
    try:
        emp = db.get(Employee, employee_id)
        if not emp:
            return _error("Empleado no encontrado.", 404)
        schedule_id = data.get("schedule_id")
        schedule = db.get(Schedule, schedule_id) if schedule_id else None
        if not schedule:
            return _error("Falta 'schedule_id' o no existe.", 400)
        effective_from = _parse_date_field(data.get("effective_from")) or datetime.now().date()
        ok, msg = _assign_schedule(db, employee_id, schedule.id, effective_from)
        if not ok:
            return _error(msg, 409)
        db.commit()
        _api_audit("api_employee_schedule_assign", target=emp.full_name, detail=f"horario={schedule.name} desde={effective_from}")
        return jsonify({"employee_id": employee_id, "schedule_id": schedule.id, "effective_from": effective_from.isoformat()}), 201
    finally:
        db.close()


# ---------------------------------------------------------- marcaciones --

@api.route("/attendance", methods=["GET"])
@api_token_required("read")
def api_attendance_list():
    start, end, err = _date_range_params(request.args)
    if err:
        return err
    limit, offset = _limit_offset(request.args)
    db = SessionLocal()
    try:
        q = (
            db.query(AttendanceLog, EmployeeMap.employee_id)
            .outerjoin(
                EmployeeMap,
                (EmployeeMap.device_pk == AttendanceLog.device_pk)
                & (EmployeeMap.device_user_id == AttendanceLog.device_user_id),
            )
            .join(Device, Device.id == AttendanceLog.device_pk)
            .filter(
                AttendanceLog.timestamp >= datetime.combine(start, datetime.min.time()),
                AttendanceLog.timestamp < datetime.combine(end, datetime.min.time()) + timedelta(days=1),
            )
        )
        employee_code = request.args.get("employee_code")
        if employee_code:
            q = q.join(Employee, Employee.id == EmployeeMap.employee_id).filter(Employee.code == employee_code)
        sede = request.args.get("sede")
        if sede:
            q = q.filter(Device.sede == sede)
        total = q.count()
        rows = q.order_by(AttendanceLog.timestamp.desc()).offset(offset).limit(limit).all()
        results = [{
            "id": log.id, "employee_id": emp_id, "device_user_id": log.device_user_id,
            "device_name": log.device.name, "sede": log.device.sede,
            "timestamp": log.timestamp.isoformat(), "status": log.status,
        } for log, emp_id in rows]
        return jsonify({"count": total, "results": results})
    finally:
        db.close()


def _employees_for_api(db, sede):
    return attendance_rules.employees_in_scope(db, sede=sede)


@api.route("/absences", methods=["GET"])
@api_token_required("read")
def api_absences_list():
    start, end, err = _date_range_params(request.args)
    if err:
        return err
    sede = request.args.get("sede") or None
    try:
        min_faltas = max(1, int(request.args.get("min_faltas", 1)))
    except ValueError:
        min_faltas = 1
    db = SessionLocal()
    try:
        employees = _employees_for_api(db, sede)
        attendance = attendance_rules.compute_attendance(db, employees, start, end)
        results = []
        for employee, days in attendance.items():
            fault_days = [d for d in days if d.status == "falta"]
            if len(fault_days) >= min_faltas:
                results.append({
                    "employee_id": employee.id, "code": employee.code, "full_name": employee.full_name,
                    "faltas": len(fault_days),
                    "fechas": [d.date.isoformat() for d in fault_days],
                })
        results.sort(key=lambda r: r["faltas"], reverse=True)
        return jsonify({"start": start.isoformat(), "end": end.isoformat(), "results": results})
    finally:
        db.close()


@api.route("/tardiness", methods=["GET"])
@api_token_required("read")
def api_tardiness_list():
    start, end, err = _date_range_params(request.args)
    if err:
        return err
    sede = request.args.get("sede") or None
    db = SessionLocal()
    try:
        employees = _employees_for_api(db, sede)
        attendance = attendance_rules.compute_attendance(db, employees, start, end)
        results = []
        for employee, days in attendance.items():
            for d in days:
                notable = d.status == "tardanza" or (d.overtime_minutes or 0) > 0 or d.lunch_status in ("excedido", "no_marcado")
                if not notable:
                    continue
                results.append({
                    "employee_id": employee.id, "code": employee.code, "full_name": employee.full_name,
                    "date": d.date.isoformat(), "schedule_name": d.schedule_name, "status": d.status,
                    "minutes_late": d.minutes_late, "overtime_minutes": d.overtime_minutes,
                    "lunch_status": d.lunch_status, "lunch_minutes": d.lunch_minutes,
                })
        results.sort(key=lambda r: r["date"])
        return jsonify({"start": start.isoformat(), "end": end.isoformat(), "results": results})
    finally:
        db.close()
