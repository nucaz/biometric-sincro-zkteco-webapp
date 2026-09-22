"""
Attendance evaluation engine: given an employee's schedule history and
their raw punches, decide -- day by day -- whether they worked, were late,
were absent, or the day wasn't even a work day for them.

Kept separate from webapp.py because this is business logic that multiple
screens need unchanged (the absences report today, tardiness/lunch reports
later): a route file should call this, not reimplement it.
"""
from collections import namedtuple
from datetime import datetime, time, timedelta

from sqlalchemy.orm import joinedload

from central.models import AttendanceException, AttendanceLog, Employee, EmployeeMap, EmployeeSchedule

# One evaluated day for one employee.
#   status: 'sin_horario' | 'descanso' | 'falta' | 'justificado' | 'tardanza' | 'a_tiempo'
#   overtime_minutes: None when there's nothing to evaluate (no exit_time
#       set on the schedule, or the day wasn't worked), otherwise >= 0.
#   lunch_status: None (no lunch window on this schedule, or day not
#       worked) | 'no_marcado' | 'cumplido' | 'excedido'
#   exception_kind: the AttendanceException.kind covering this day, only
#       set when status == 'justificado'.
DayStatus = namedtuple(
    "DayStatus",
    "date status schedule_name first_punch last_punch minutes_late punches "
    "overtime_minutes lunch_status lunch_minutes expected_entry expected_exit exception_kind",
)

STATUS_LABELS = {
    "sin_horario": "Sin horario asignado",
    "descanso": "Descanso",
    "falta": "Falta",
    "justificado": "Justificado",
    "tardanza": "Tardanza",
    "a_tiempo": "A tiempo",
}

LUNCH_STATUS_LABELS = {
    "no_marcado": "No marcado",
    "cumplido": "Cumplido",
    "excedido": "Excedido",
}

EXCEPTION_LABELS = {
    "vacaciones": "Vacaciones",
    "permiso": "Permiso",
    "descanso_medico": "Descanso médico",
    "otro": "Otro",
}


def _schedules_by_employee(db, employee_ids):
    if not employee_ids:
        return {}
    rows = (
        db.query(EmployeeSchedule)
        .options(joinedload(EmployeeSchedule.schedule))
        .filter(EmployeeSchedule.employee_id.in_(employee_ids))
        .all()
    )
    by_employee = {}
    for r in rows:
        by_employee.setdefault(r.employee_id, []).append(r)
    return by_employee


def _schedule_on(assignments, date_):
    """The assignment covering `date_`, if any. Assignments never overlap
    (employee_schedule_assign() in webapp.py closes the previous one
    before opening a new one), so at most one can match."""
    for a in assignments:
        if a.effective_from <= date_ and (a.effective_to is None or date_ <= a.effective_to):
            return a.schedule
    return None


def _punches_by_employee_day(db, employee_ids, start_date, end_date):
    """{(employee_id, date): [timestamp, ...]} for every punch in range,
    in one query -- joins through EmployeeMap since AttendanceLog only
    knows (device_pk, device_user_id), not the canonical employee."""
    if not employee_ids:
        return {}
    start_dt = datetime.combine(start_date, time.min)
    end_dt = datetime.combine(end_date, time.min) + timedelta(days=1)
    rows = (
        db.query(EmployeeMap.employee_id, AttendanceLog.timestamp)
        .join(
            AttendanceLog,
            (AttendanceLog.device_pk == EmployeeMap.device_pk)
            & (AttendanceLog.device_user_id == EmployeeMap.device_user_id),
        )
        .filter(EmployeeMap.employee_id.in_(employee_ids))
        .filter(AttendanceLog.timestamp >= start_dt, AttendanceLog.timestamp < end_dt)
        .all()
    )
    by_day = {}
    for employee_id, ts in rows:
        by_day.setdefault((employee_id, ts.date()), []).append(ts)
    return by_day


def _exceptions_by_employee(db, employee_ids, start_date, end_date):
    if not employee_ids:
        return {}
    rows = (
        db.query(AttendanceException)
        .filter(AttendanceException.employee_id.in_(employee_ids))
        .filter(AttendanceException.date_from <= end_date, AttendanceException.date_to >= start_date)
        .all()
    )
    by_employee = {}
    for r in rows:
        by_employee.setdefault(r.employee_id, []).append(r)
    return by_employee


def _exception_on(exceptions, date_):
    for e in exceptions:
        if e.date_from <= date_ <= e.date_to:
            return e.kind
    return None


def compute_attendance(db, employees, start_date, end_date):
    """Evaluate every calendar day in [start_date, end_date] for each
    employee against their schedule history and punches.
    Returns {employee: [DayStatus, ...]}, one entry per employee passed in,
    days in ascending order."""
    employee_ids = [e.id for e in employees]
    schedules_by_employee = _schedules_by_employee(db, employee_ids)
    punches_by_day = _punches_by_employee_day(db, employee_ids, start_date, end_date)
    exceptions_by_employee = _exceptions_by_employee(db, employee_ids, start_date, end_date)

    result = {}
    for employee in employees:
        assignments = schedules_by_employee.get(employee.id, [])
        exceptions = exceptions_by_employee.get(employee.id, [])
        days = []
        d = start_date
        while d <= end_date:
            schedule = _schedule_on(assignments, d)
            punches = sorted(punches_by_day.get((employee.id, d), []))
            minutes_late = 0
            overtime_minutes = None
            lunch_status = None
            lunch_minutes = None
            exception_kind = None

            if schedule is None:
                status = "sin_horario"
            elif not schedule.works_on(d):
                status = "descanso"
            elif not punches:
                exception_kind = _exception_on(exceptions, d)
                status = "justificado" if exception_kind else "falta"
            else:
                first = punches[0]
                limit = datetime.combine(d, schedule.entry_time) + timedelta(minutes=schedule.tolerance_minutes)
                if first > limit:
                    status = "tardanza"
                    minutes_late = int((first - datetime.combine(d, schedule.entry_time)).total_seconds() // 60)
                else:
                    status = "a_tiempo"

                # Overtime: only evaluable once the schedule has an
                # exit_time -- an old schedule saved before that field
                # existed leaves this as None ("not evaluated") rather
                # than a misleading 0.
                if schedule.exit_time:
                    exit_dt = datetime.combine(d, schedule.exit_time)
                    diff_minutes = int((punches[-1] - exit_dt).total_seconds() // 60)
                    overtime_minutes = max(0, diff_minutes)

                # Lunch: only evaluable when the schedule defines a
                # window. K20-class devices can miss punches, so this
                # ASSUMES the 2nd and 3rd punch of the day are lunch
                # out/in when there are at least 4 -- same ordering
                # heuristic _group_by_day already relies on in webapp.py.
                if schedule.lunch_start and schedule.lunch_end:
                    if len(punches) >= 4:
                        lunch_out, lunch_in = punches[1], punches[2]
                        actual_minutes = int((lunch_in - lunch_out).total_seconds() // 60)
                        expected_minutes = int(
                            (datetime.combine(d, schedule.lunch_end) - datetime.combine(d, schedule.lunch_start))
                            .total_seconds() // 60
                        )
                        lunch_minutes = actual_minutes
                        lunch_status = "excedido" if actual_minutes > expected_minutes + schedule.tolerance_minutes else "cumplido"
                    else:
                        lunch_status = "no_marcado"

            days.append(DayStatus(
                date=d,
                status=status,
                schedule_name=schedule.name if schedule else None,
                first_punch=punches[0] if punches else None,
                last_punch=punches[-1] if punches else None,
                minutes_late=minutes_late,
                punches=punches,
                overtime_minutes=overtime_minutes,
                lunch_status=lunch_status,
                lunch_minutes=lunch_minutes,
                expected_entry=schedule.entry_time if schedule else None,
                expected_exit=schedule.exit_time if schedule else None,
                exception_kind=exception_kind,
            ))
            d += timedelta(days=1)
        result[employee] = days
    return result


def employees_in_scope(db, sede=None, active_only=True):
    """Employees to evaluate, optionally narrowed to one sede (via any
    device they're linked to there -- an employee can be enrolled at more
    than one, so this is an EXISTS-style filter, not a strict one-sede
    field)."""
    query = db.query(Employee)
    if active_only:
        query = query.filter(Employee.active.is_(True))
    if sede:
        from central.models import Device
        query = (
            query.join(EmployeeMap, EmployeeMap.employee_id == Employee.id)
            .join(Device, Device.id == EmployeeMap.device_pk)
            .filter(Device.sede == sede)
            .distinct()
        )
    return query.order_by(Employee.full_name).all()
