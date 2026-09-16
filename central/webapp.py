"""
HR-facing web dashboard + admin screens over the central attendance database.

Run with:
    python -m central.webapp
Then open http://localhost:5000

First run needs an admin account:
    python -m central.create_admin <username> <password>
"""
import csv
import io
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime, timedelta

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from flask import (
    Flask, render_template, request, redirect, url_for, session as flask_session,
    Response, flash
)
from zk import const as zk_const
from sqlalchemy import func

from attendance_system import ZKTecoAttendance, check_network_reachable
from central.db import SessionLocal, init_db
from central.models import Device, AttendanceLog, EmployeeMap, Employee, User, TrustedDevice, AuditLog
from central.auth import login_required, admin_required, super_admin_required, verify_password, hash_password, ROLE_LABELS
from central.sync import sync_all, sync_device
from central.backup import export_data, import_data
from central.twofa import (
    generate_secret, qr_data_uri, verify_code, new_trusted_device_token,
    hash_token, trusted_device_expiry, TRUSTED_DEVICE_COOKIE, TRUSTED_DEVICE_DAYS,
)
from central.audit import log_event, resolve_hostname, client_ip, client_user_agent

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")

# Idempotent (create_all only adds missing tables) -- called at import time,
# not just under __main__, so it also runs under a WSGI server like
# gunicorn/waitress that imports `central.webapp:app` directly.
init_db()

PAGE_SIZE = 200


def _connect_to(device):
    """Build a ZKTecoAttendance for `device`, carrying its comm key (the
    ZK "communication password" -- ZKTimeNet's own att_terminal.terminal_connectpwd
    column, confirmed against the local ZKTimeNet.db install) if one is set."""
    return ZKTecoAttendance(device.ip, port=device.port, password=device.comm_password or 0)


@app.before_request
def guard():
    if request.endpoint in ("login", "verify_2fa", "static"):
        return
    if "user_id" not in flask_session:
        return redirect(url_for("login", next=request.path))


@app.after_request
def no_cache(response):
    # This is an internal HR/admin tool with no static-asset pipeline --
    # every page is server-rendered per request, so there's no upside to
    # letting a browser (or a caching proxy) reuse an old copy, and real
    # downsides: it's how a stale copy of devices.html's sync script could
    # end up running even after the server was updated with a fix.
    response.headers["Cache-Control"] = "no-store"
    return response


@app.context_processor
def inject_role():
    role = flask_session.get("role")
    return {
        "current_role": role,
        "current_role_label": ROLE_LABELS.get(role, role),
        "current_username": flask_session.get("username"),
        "can_manage": role in ("admin", "super_admin"),
        "is_super_admin": role == "super_admin",
    }


# -------------------------------------------------------------- audit ----

def _audit(db, action, target=None, detail=None, username=None):
    """Append one audit_log row using the client info cached on this
    session at login time (so a reverse-DNS lookup only happens once per
    session, not on every click) -- falls back to a fresh lookup for
    events that happen outside a session, like a failed login."""
    ip = flask_session.get("client_ip")
    if ip is None:
        ip = client_ip()
        hostname = resolve_hostname(ip)
        user_agent = client_user_agent()
    else:
        hostname = flask_session.get("client_hostname")
        user_agent = flask_session.get("client_user_agent")
    log_event(
        db, action,
        username=username or flask_session.get("username"),
        target=target, detail=detail,
        ip=ip, hostname=hostname, user_agent=user_agent,
    )
    db.commit()


def _audit_context():
    """Snapshot of who's making this request, as plain values -- pass this
    into a background thread instead of calling _audit() there directly,
    since flask.session/request only exist on the request thread that
    started them, not on a worker thread spawned from it."""
    return {
        "username": flask_session.get("username"),
        "ip": flask_session.get("client_ip") or client_ip(),
        "hostname": flask_session.get("client_hostname"),
        "user_agent": flask_session.get("client_user_agent") or client_user_agent(),
    }


# ------------------------------------------------------ sync hard timeout -
# No live progress view anymore -- it went through two designs (Server-Sent
# Events, then polling a background job) and both ended up adding more
# failure modes than they were worth for what's fundamentally a "click a
# button, wait, see the result" action. Back to a plain blocking request:
# the button disables itself while the form submits, the page redirects
# back with a flash message once it's done. What's still very much needed:
# sync_device()'s own retry loop is supposed to bound how long a device can
# take (3 attempts x 20s timeout + delays, under 2 minutes) -- but a flaky
# device (seen for real against one K20) can make a pyzk socket call hang
# PAST its own configured timeout instead of raising, which no amount of
# retry logic inside sync_device() can protect against. run_with_hard_timeout
# is the actual ceiling: past HARD_SYNC_TIMEOUT_SECONDS, give up and report
# an error instead of leaving the request (and the waitress/gunicorn worker
# thread serving it) hanging forever. Python can't forcibly kill the
# underlying thread if it's truly stuck in a blocking call, so a hung one
# leaks in the background (it dies with the process) -- max_workers is
# generous specifically so a few of those can't starve out real work.
_sync_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="sync-job")
HARD_SYNC_TIMEOUT_SECONDS = 150


def run_with_hard_timeout(fn, *args, **kwargs):
    """Call fn(*args, **kwargs) with a firm ceiling. Raises TimeoutError
    (built-in, not concurrent.futures') with a clear Spanish message if it
    doesn't return in time -- callers just need one except TimeoutError."""
    future = _sync_executor.submit(fn, *args, **kwargs)
    try:
        return future.result(timeout=HARD_SYNC_TIMEOUT_SECONDS)
    except FuturesTimeoutError:
        raise TimeoutError(
            f"Sin respuesta del dispositivo tras {HARD_SYNC_TIMEOUT_SECONDS} segundos -- "
            "probablemente un problema de red con ese equipo, no de la aplicación."
        )


# ---------------------------------------------------------------- auth ----

def _finish_login(user, remember_next_url=None):
    flask_session["user_id"] = user.id
    flask_session["role"] = user.role
    flask_session["username"] = user.username
    flask_session.pop("pending_2fa_user_id", None)
    flask_session.pop("pending_2fa_next", None)
    ip = client_ip()
    flask_session["client_ip"] = ip
    # Best-effort PC name via reverse DNS -- see central/audit.py for why a
    # browser can't just report its Windows computer name directly.
    flask_session["client_hostname"] = resolve_hostname(ip)
    flask_session["client_user_agent"] = client_user_agent()


def _device_is_trusted(db, user):
    token = request.cookies.get(TRUSTED_DEVICE_COOKIE)
    if not token:
        return False
    th = hash_token(token)
    return db.query(TrustedDevice).filter(
        TrustedDevice.user_id == user.id,
        TrustedDevice.token_hash == th,
        TrustedDevice.expires_at > datetime.utcnow(),
    ).first() is not None


MAX_LOGIN_ATTEMPTS = 3


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        db = SessionLocal()
        try:
            attempted_username = request.form.get("username", "").strip()
            user = db.query(User).filter(User.username == attempted_username).first()

            if user and user.locked:
                _audit(db, "login_blocked", username=user.username, detail="cuenta bloqueada por intentos fallidos")
                flash("Esta cuenta está bloqueada por demasiados intentos fallidos. Pide a un super administrador que la desbloquee en Cuentas.")
                return render_template("login.html")

            if user and user.active and verify_password(request.form.get("password", ""), user.password_hash):
                if user.failed_login_attempts:
                    user.failed_login_attempts = 0
                    db.commit()
                next_url = request.args.get("next") or url_for("dashboard")
                if user.totp_enabled and not _device_is_trusted(db, user):
                    flask_session["pending_2fa_user_id"] = user.id
                    flask_session["pending_2fa_next"] = next_url
                    return redirect(url_for("verify_2fa"))
                _finish_login(user)
                _audit(db, "login", detail="sin 2FA (no activado o equipo recordado)")
                return redirect(next_url)

            if user and user.active:
                # Only a real, active account can be locked -- an unknown
                # username or an already-disabled account doesn't count
                # attempts, there's nothing there to protect by locking it.
                user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
                if user.failed_login_attempts >= MAX_LOGIN_ATTEMPTS:
                    user.locked = True
                    db.commit()
                    _audit(db, "account_locked", username=user.username, detail=f"{MAX_LOGIN_ATTEMPTS} intentos fallidos seguidos")
                    flash(f"Cuenta bloqueada tras {MAX_LOGIN_ATTEMPTS} intentos fallidos. Pide a un super administrador que la desbloquee en Cuentas.")
                else:
                    remaining = MAX_LOGIN_ATTEMPTS - user.failed_login_attempts
                    db.commit()
                    _audit(db, "login_failed", username=user.username, detail=f"contraseña incorrecta ({remaining} intento(s) restante(s))")
                    flash(f"Usuario o contraseña incorrectos. Te queda(n) {remaining} intento(s) antes de que se bloquee la cuenta.")
            else:
                _audit(db, "login_failed", username=attempted_username or None,
                       detail="usuario inactivo" if (user and not user.active) else "usuario no encontrado")
                flash("Usuario o contraseña incorrectos.")
        finally:
            db.close()
    return render_template("login.html")


@app.route("/2fa/verify", methods=["GET", "POST"])
def verify_2fa():
    pending_id = flask_session.get("pending_2fa_user_id")
    if not pending_id:
        return redirect(url_for("login"))
    db = SessionLocal()
    try:
        user = db.get(User, pending_id)
        if not user or not user.active or not user.totp_enabled:
            flask_session.pop("pending_2fa_user_id", None)
            return redirect(url_for("login"))

        if request.method == "POST":
            code = request.form.get("code", "")
            if verify_code(user.totp_secret, code):
                next_url = flask_session.get("pending_2fa_next") or url_for("dashboard")
                _finish_login(user)
                remembered = bool(request.form.get("remember_device"))
                _audit(db, "login", detail="con 2FA" + (" + equipo recordado" if remembered else ""))
                resp = redirect(next_url)
                if remembered:
                    raw_token, token_hash = new_trusted_device_token()
                    db.add(TrustedDevice(
                        user_id=user.id, token_hash=token_hash,
                        label=request.headers.get("User-Agent", "")[:200],
                        expires_at=trusted_device_expiry(),
                    ))
                    db.commit()
                    resp.set_cookie(
                        TRUSTED_DEVICE_COOKIE, raw_token,
                        max_age=TRUSTED_DEVICE_DAYS * 24 * 3600,
                        httponly=True, samesite="Lax",
                    )
                return resp
            _audit(db, "login_2fa_failed", username=user.username)
            flash("Código incorrecto. Verifica la hora de tu teléfono y vuelve a intentar.")
        return render_template("verify_2fa.html", username=user.username)
    finally:
        db.close()


@app.route("/logout")
def logout():
    if "user_id" in flask_session:
        db = SessionLocal()
        try:
            _audit(db, "logout")
        finally:
            db.close()
    flask_session.clear()
    return redirect(url_for("login"))


# ----------------------------------------------------------- dashboard ----

def _display_name(db, device_pk, device_user_id, fallback_name):
    mapped = db.query(EmployeeMap).filter(
        EmployeeMap.device_pk == device_pk,
        EmployeeMap.device_user_id == device_user_id,
    ).first()
    if mapped:
        return mapped.employee.full_name
    return fallback_name or f"ID {device_user_id}"


def _group_by_day(rows, db):
    """Collapse raw punches into one line per (device, employee, day):
    check_in = earliest punch that day, check_out = latest (when there's
    more than one). K20-class devices often don't reliably tag punches as
    in/out, so min/max-of-the-day is the robust rule rather than trusting
    each row's own status."""
    buckets = {}
    for r in rows:
        key = (r.device_pk, r.device_user_id, r.timestamp.date())
        bucket = buckets.setdefault(key, {
            "device_name": r.device.name,
            "sede": r.device.sede or "-",
            "employee": _display_name(db, r.device_pk, r.device_user_id, r.user_name),
            "device_user_id": r.device_user_id,
            "date": r.timestamp.date(),
            "timestamps": [],
        })
        bucket["timestamps"].append(r.timestamp)

    grouped = []
    for bucket in buckets.values():
        ts = sorted(bucket.pop("timestamps"))
        bucket["check_in"] = ts[0]
        bucket["check_out"] = ts[-1] if len(ts) > 1 else None
        bucket["punches"] = len(ts)
        grouped.append(bucket)
    grouped.sort(key=lambda g: (g["date"], g["employee"]), reverse=True)
    return grouped


def _apply_filters(query, args):
    start = args.get("start")
    end = args.get("end")
    device_id = args.get("device")
    sede = args.get("sede")
    q = (args.get("q") or "").strip()

    if start:
        query = query.filter(AttendanceLog.timestamp >= datetime.strptime(start, "%Y-%m-%d"))
    if end:
        end_dt = datetime.strptime(end, "%Y-%m-%d") + timedelta(days=1)
        query = query.filter(AttendanceLog.timestamp < end_dt)
    if device_id:
        query = query.filter(Device.device_id == device_id)
    if sede:
        query = query.filter(Device.sede == sede)
    if q:
        like = f"%{q}%"
        query = query.filter(
            (AttendanceLog.user_name.ilike(like)) | (AttendanceLog.device_user_id.ilike(like))
        )
    return query


@app.route("/")
@login_required
def dashboard():
    db = SessionLocal()
    try:
        # Default to the last 7 days when no range is given, so the first
        # load of the dashboard doesn't have to group the entire history
        # (tens of thousands of rows) on every request.
        args = request.args.to_dict()
        if not args.get("start") and not args.get("end"):
            today = datetime.now().date()
            args["start"] = (today - timedelta(days=7)).strftime("%Y-%m-%d")
            args["end"] = today.strftime("%Y-%m-%d")

        base = db.query(AttendanceLog).join(Device, AttendanceLog.device_pk == Device.id)
        filtered = _apply_filters(base, args)
        view = args.get("view", "grouped")
        page = max(1, int(args.get("page", 1)))

        if view == "grouped":
            all_rows = filtered.order_by(AttendanceLog.timestamp).all()
            grouped = _group_by_day(all_rows, db)
            total = len(grouped)
            records = grouped[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]
        else:
            total = filtered.count()
            rows = (filtered.order_by(AttendanceLog.timestamp.desc())
                    .offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE).all())
            records = [{
                "device_name": r.device.name,
                "sede": r.device.sede or "-",
                "employee": _display_name(db, r.device_pk, r.device_user_id, r.user_name),
                "device_user_id": r.device_user_id,
                "timestamp": r.timestamp,
                "status": r.status,
            } for r in rows]

        devices = db.query(Device).order_by(Device.name).all()
        sedes = sorted({d.sede for d in devices if d.sede})

        return render_template(
            "dashboard.html",
            records=records, devices=devices, sedes=sedes, view=view,
            total=total, page=page, page_size=PAGE_SIZE, args=args,
        )
    finally:
        db.close()


def _export_table(db, args):
    """Shared by CSV/Excel/PDF export: same filters, same two views
    (grouped/raw) as the dashboard, as plain headers + row lists."""
    base = db.query(AttendanceLog).join(Device, AttendanceLog.device_pk == Device.id)
    filtered = _apply_filters(base, args).order_by(AttendanceLog.timestamp)
    rows = filtered.all()

    if args.get("view", "grouped") == "grouped":
        headers = ["Sede", "Dispositivo", "Empleado", "ID", "Fecha", "Entrada", "Salida", "Marcaciones"]
        table = [[
            g["sede"], g["device_name"], g["employee"], g["device_user_id"],
            g["date"].strftime("%Y-%m-%d"), g["check_in"].strftime("%H:%M:%S"),
            g["check_out"].strftime("%H:%M:%S") if g["check_out"] else "", g["punches"],
        ] for g in _group_by_day(rows, db)]
    else:
        headers = ["Sede", "Dispositivo", "Empleado", "ID", "Fecha", "Hora", "Estado"]
        table = [[
            r.device.sede or "", r.device.name,
            _display_name(db, r.device_pk, r.device_user_id, r.user_name),
            r.device_user_id, r.timestamp.strftime("%Y-%m-%d"),
            r.timestamp.strftime("%H:%M:%S"), r.status,
        ] for r in rows]
    return headers, table


def _export_subtitle(args):
    parts = []
    if args.get("start") or args.get("end"):
        parts.append(f"{args.get('start', '...')} a {args.get('end', '...')}")
    if args.get("sede"):
        parts.append(f"Sede: {args['sede']}")
    if args.get("q"):
        parts.append(f"Búsqueda: \"{args['q']}\"")
    parts.append("Resumen por día" if args.get("view", "grouped") == "grouped" else "Marcaciones crudas")
    return " · ".join(parts)


@app.route("/export.csv")
@login_required
def export_csv():
    db = SessionLocal()
    try:
        headers, table = _export_table(db, request.args)
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(headers)
        writer.writerows(table)
        return Response(
            buf.getvalue(), mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=attendance_export.csv"},
        )
    finally:
        db.close()


@app.route("/export.xlsx")
@login_required
def export_xlsx():
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    db = SessionLocal()
    try:
        headers, table = _export_table(db, request.args)

        wb = Workbook()
        ws = wb.active
        ws.title = "Marcaciones"

        ws.merge_cells("A1:{}1".format(get_column_letter(len(headers))))
        ws["A1"] = "Asistencia - Panel RRHH"
        ws["A1"].font = Font(size=14, bold=True, color="1F2937")

        ws.merge_cells("A2:{}2".format(get_column_letter(len(headers))))
        ws["A2"] = _export_subtitle(request.args)
        ws["A2"].font = Font(size=10, italic=True, color="6B7280")

        ws.merge_cells("A3:{}3".format(get_column_letter(len(headers))))
        ws["A3"] = f"Generado {datetime.now().strftime('%Y-%m-%d %H:%M')} · {len(table)} registro(s) · Develop Juan Carlos Aguirre Alvarado"
        ws["A3"].font = Font(size=8, color="9CA3AF")

        header_row = 5
        header_fill = PatternFill(start_color="1F2937", end_color="1F2937", fill_type="solid")
        for col, title in enumerate(headers, start=1):
            cell = ws.cell(row=header_row, column=col, value=title)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center")

        stripe_fill = PatternFill(start_color="F3F4F6", end_color="F3F4F6", fill_type="solid")
        for r, row in enumerate(table, start=header_row + 1):
            for c, value in enumerate(row, start=1):
                cell = ws.cell(row=r, column=c, value=value)
                if (r - header_row) % 2 == 0:
                    cell.fill = stripe_fill

        for col in range(1, len(headers) + 1):
            letter = get_column_letter(col)
            max_len = max([len(str(headers[col - 1]))] + [len(str(row[col - 1])) for row in table]) if table else len(str(headers[col - 1]))
            ws.column_dimensions[letter].width = min(max(max_len + 2, 10), 40)

        ws.freeze_panes = f"A{header_row + 1}"
        if table:
            ws.auto_filter.ref = f"A{header_row}:{get_column_letter(len(headers))}{header_row + len(table)}"

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        filename = f"attendance_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        return Response(
            buf.read(),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    finally:
        db.close()


class _ReportPDF:
    """Thin wrapper so we don't repeat the header/footer/striping dance
    between the two PDF exports (dashboard + device users, if that ever
    grows one)."""

    def __init__(self, title, subtitle):
        from fpdf import FPDF

        class PDF(FPDF):
            def footer(self):
                self.set_y(-15)
                self.set_font("Arial", size=8)
                self.set_text_color(150, 150, 150)
                self.cell(0, 10, f"Página {self.page_no()}/{{nb}} · Develop Juan Carlos Aguirre Alvarado - Infraestructura TI & Ciberseguridad Apps", align="C")

        self.pdf = PDF()
        self.pdf.alias_nb_pages()
        self.pdf.add_page()
        self.pdf.set_font("Arial", "B", 16)
        self.pdf.set_text_color(31, 41, 55)
        self.pdf.cell(0, 10, title, ln=True)
        self.pdf.set_font("Arial", size=10)
        self.pdf.set_text_color(107, 114, 128)
        self.pdf.cell(0, 6, subtitle, ln=True)
        self.pdf.set_text_color(0, 0, 0)
        self.pdf.ln(4)

    def table(self, headers, rows, col_widths):
        pdf = self.pdf
        pdf.set_font("Arial", "B", 9)
        pdf.set_fill_color(31, 41, 55)
        pdf.set_text_color(255, 255, 255)
        for w, h in zip(col_widths, headers):
            pdf.cell(w, 8, str(h), border=0, fill=True, align="C")
        pdf.ln()
        pdf.set_font("Arial", size=8)
        pdf.set_text_color(20, 20, 20)
        for i, row in enumerate(rows):
            pdf.set_fill_color(243, 244, 246) if i % 2 else pdf.set_fill_color(255, 255, 255)
            for w, value in zip(col_widths, row):
                text = str(value)
                if pdf.get_string_width(text) > w - 2:
                    while pdf.get_string_width(text + "...") > w - 2 and len(text) > 1:
                        text = text[:-1]
                    text += "..."
                pdf.cell(w, 6, text, border="B", fill=True)
            pdf.ln()

    def output(self):
        return bytes(self.pdf.output())


@app.route("/export.pdf")
@login_required
def export_pdf():
    db = SessionLocal()
    try:
        headers, table = _export_table(db, request.args)
        report = _ReportPDF("Reporte de Asistencia", _export_subtitle(request.args))
        if request.args.get("view", "grouped") == "grouped":
            col_widths = [28, 25, 45, 20, 22, 20, 20, 22]
        else:
            col_widths = [28, 25, 55, 22, 25, 22, 25]
        report.table(headers, table, col_widths)

        filename = f"attendance_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        return Response(
            report.output(), mimetype="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    finally:
        db.close()


# ------------------------------------------------------------- devices ----

@app.route("/devices")
@login_required
def devices_status():
    db = SessionLocal()
    try:
        devices = db.query(Device).filter(Device.deleted.is_(False)).order_by(Device.name).all()
        deleted_devices = db.query(Device).filter(Device.deleted.is_(True)).order_by(Device.name).all()
        deleted_log_counts = {
            device_pk: count for device_pk, count in
            db.query(AttendanceLog.device_pk, func.count(AttendanceLog.id))
            .filter(AttendanceLog.device_pk.in_([d.id for d in deleted_devices]))
            .group_by(AttendanceLog.device_pk).all()
        } if deleted_devices else {}
        return render_template(
            "devices.html", devices=devices, deleted_devices=deleted_devices,
            deleted_log_counts=deleted_log_counts,
        )
    finally:
        db.close()


@app.route("/sync", methods=["POST"])
@admin_required
def sync_now():
    """Manual trigger for the same pull that central.sync does on a
    schedule -- blocks until every active device has been polled or the
    hard timeout gives up on one (can take a while with a lot of devices
    or history; the button disables itself client-side while it waits)."""
    ctx = _audit_context()

    def work():
        results = sync_all()
        summary = "; ".join(f"{name}: {result}" for name, result in results.items())
        db = SessionLocal()
        try:
            log_event(db, "sync_all", detail=summary, **ctx)
            db.commit()
        finally:
            db.close()
        return summary

    try:
        flash(f"Sincronización completa. {run_with_hard_timeout(work)}")
    except TimeoutError as e:
        db = SessionLocal()
        try:
            log_event(db, "sync_all", detail=f"ERROR: {e}", **ctx)
            db.commit()
        finally:
            db.close()
        flash(f"Sincronización interrumpida: {e}")
    return redirect(url_for("devices_status"))


@app.route("/devices/<int:device_pk>/sync", methods=["POST"])
@admin_required
def device_sync_one(device_pk):
    """Same as 'Sincronizar todos' but for just this one device -- handy
    right after fixing a device's IP/comm key without waiting for the
    others to be polled too."""
    ctx = _audit_context()
    db = SessionLocal()
    try:
        device_name = (db.get(Device, device_pk) or abort_404()).name
    finally:
        db.close()

    def work():
        db2 = SessionLocal()
        try:
            device = db2.get(Device, device_pk)
            try:
                count = sync_device(db2, device)
                log_event(db2, "device_sync", target=device.name, detail=f"{count} registro(s) nuevo(s)", **ctx)
                db2.commit()
                return count
            except Exception as e:
                db2.rollback()
                log_event(db2, "device_sync", target=device.name, detail=f"ERROR: {e}", **ctx)
                db2.commit()
                raise
        finally:
            db2.close()

    try:
        count = run_with_hard_timeout(work)
        flash(f"'{device_name}' sincronizado: {count} registro(s) nuevo(s).")
    except TimeoutError as e:
        flash(f"'{device_name}': {e}")
    except Exception as e:
        flash(f"Error sincronizando '{device_name}': {e}")
    return redirect(url_for("devices_status"))


@app.route("/devices/new", methods=["GET", "POST"])
@admin_required
def device_new():
    if request.method == "POST":
        db = SessionLocal()
        try:
            ip = request.form["ip"].strip()
            port = int(request.form.get("port") or 4370)
            comm_password = request.form.get("comm_password", "").strip()
            terminal_no = request.form.get("terminal_no", "").strip()
            device = Device(
                device_id=f"{ip}:{port}",  # upgraded to the real serial once "Probar conexión" runs
                name=request.form["name"].strip(),
                sede=request.form.get("sede", "").strip() or None,
                ip=ip, port=port, active=1,
                comm_password=int(comm_password) if comm_password.isdigit() else 0,
                terminal_no=int(terminal_no) if terminal_no.isdigit() else None,
            )
            db.add(device)
            db.commit()
            _audit(db, "device_add", target=device.name, detail=f"{ip}:{port}")
            flash(f"Dispositivo '{device.name}' agregado. Usa 'Probar conexión' para confirmarlo.")
            return redirect(url_for("devices_status"))
        finally:
            db.close()
    return render_template("device_form.html", device=None)


@app.route("/devices/<int:device_pk>/edit", methods=["GET", "POST"])
@admin_required
def device_edit(device_pk):
    db = SessionLocal()
    try:
        device = db.get(Device, device_pk) or abort_404()
        if request.method == "POST":
            comm_password = request.form.get("comm_password", "").strip()
            terminal_no = request.form.get("terminal_no", "").strip()
            device.name = request.form["name"].strip()
            device.sede = request.form.get("sede", "").strip() or None
            device.ip = request.form["ip"].strip()
            device.port = int(request.form.get("port") or 4370)
            device.comm_password = int(comm_password) if comm_password.isdigit() else 0
            device.terminal_no = int(terminal_no) if terminal_no.isdigit() else None
            device.active = 1 if request.form.get("active") else 0
            db.commit()
            _audit(db, "device_edit", target=device.name)
            flash(f"Dispositivo '{device.name}' actualizado.")
            return redirect(url_for("devices_status"))
        history_count = db.query(AttendanceLog).filter(AttendanceLog.device_pk == device.id).count()
        return render_template("device_form.html", device=device, history_count=history_count)
    finally:
        db.close()


@app.route("/devices/<int:device_pk>/delete", methods=["POST"])
@admin_required
def device_delete(device_pk):
    """"Eliminar" never drops attendance_log/employee_map history and never
    drops the devices row itself -- it hides the device from this list and
    from sync (both manual and scheduled), same as unchecking 'Activo',
    plus taking it out of view entirely. See /devices/<id>/restore to
    bring it back."""
    db = SessionLocal()
    try:
        device = db.get(Device, device_pk) or abort_404()
        history_count = db.query(AttendanceLog).filter(AttendanceLog.device_pk == device.id).count()
        device.deleted = True
        device.active = 0
        db.commit()
        _audit(db, "device_delete", target=device.name, detail=f"oculto, {history_count} marcación(es) conservada(s) en el historial")
        flash(f"'{device.name}' eliminado de la lista. Su historial ({history_count} marcación(es)) se conserva intacto en Marcaciones -- usa 'Ver eliminados' más abajo para restaurarlo si hace falta.")
        return redirect(url_for("devices_status"))
    finally:
        db.close()


@app.route("/devices/<int:device_pk>/restore", methods=["POST"])
@admin_required
def device_restore(device_pk):
    db = SessionLocal()
    try:
        device = db.get(Device, device_pk) or abort_404()
        device.deleted = False
        db.commit()
        _audit(db, "device_restore", target=device.name)
        flash(f"'{device.name}' restaurado -- sigue inactivo (no se sincroniza) hasta que lo actives desde Editar.")
        return redirect(url_for("devices_status"))
    finally:
        db.close()


@app.route("/devices/<int:device_pk>/test", methods=["POST"])
@admin_required
def device_test(device_pk):
    db = SessionLocal()
    try:
        device = db.get(Device, device_pk) or abort_404()

        reachable, detail = check_network_reachable(device.ip, device.port)
        if not reachable:
            _audit(db, "device_test", target=device.name, detail=f"ERROR (red): {detail}")
            flash(f"'{device.name}' ({device.ip}:{device.port}) no responde en la red: {detail}")
            return redirect(url_for("devices_status"))

        system = _connect_to(device)
        system.connect()
        if not system.conn:
            hint = " Revisa la llave de comunicación (comm key) configurada en el equipo." if device.comm_password == 0 else " Revisa que la llave de comunicación configurada aquí coincida con la del equipo."
            _audit(db, "device_test", target=device.name, detail="ERROR (protocolo ZK rechazado)")
            flash(f"'{device.name}' responde en la red pero rechazó la conexión del protocolo ZK.{hint}")
            return redirect(url_for("devices_status"))
        try:
            model = system.device_info.get('model', '').strip()
            serial = system.device_info.get('serial_number', '').strip()
            device.model = model or device.model
            if serial and device.device_id != serial:
                clash = db.query(Device).filter(Device.device_id == serial, Device.id != device.id).first()
                if not clash:
                    device.device_id = serial
            db.commit()
            _audit(db, "device_test", target=device.name, detail=f"OK - modelo {model or '?'}, serial {serial or '?'}")
            flash(f"Conexión OK con '{device.name}': modelo {model or '?'}, serial {serial or '?'}.")
        finally:
            system.disconnect()
        return redirect(url_for("devices_status"))
    finally:
        db.close()


@app.route("/devices/<int:device_pk>/ping", methods=["POST"])
@admin_required
def device_ping(device_pk):
    """Pure network-reachability test (TCP connect) -- no ZK handshake, no
    comm key involved. Faster and simpler than 'Probar conexión' when all
    you want to know is "is it even on the network right now"."""
    db = SessionLocal()
    try:
        device = db.get(Device, device_pk) or abort_404()
        reachable, detail = check_network_reachable(device.ip, device.port)
        _audit(db, "device_ping", target=device.name, detail="OK" if reachable else f"ERROR: {detail}")
        if reachable:
            flash(f"Ping OK: '{device.name}' ({device.ip}:{device.port}) responde en la red.")
        else:
            flash(f"Ping falló: '{device.name}' ({device.ip}:{device.port}) — {detail}")
        return redirect(url_for("devices_status"))
    finally:
        db.close()


@app.route("/devices/<int:device_pk>/restart", methods=["POST"])
@admin_required
def device_restart(device_pk):
    db = SessionLocal()
    try:
        device = db.get(Device, device_pk) or abort_404()
        system = _connect_to(device)
        system.connect()
        if not system.conn:
            flash(f"No se pudo conectar a '{device.name}' para reiniciarlo.")
            return redirect(url_for("devices_status"))
        try:
            system.restart_device()
            _audit(db, "device_restart", target=device.name)
            flash(f"Se envió el reinicio a '{device.name}'. Tardará unos segundos en volver a estar disponible.")
        except Exception as e:
            _audit(db, "device_restart", target=device.name, detail=f"ERROR: {e}")
            flash(f"Error al reiniciar '{device.name}': {e}")
        return redirect(url_for("devices_status"))
    finally:
        db.close()


@app.route("/devices/<int:device_pk>/poweroff", methods=["POST"])
@admin_required
def device_poweroff(device_pk):
    db = SessionLocal()
    try:
        device = db.get(Device, device_pk) or abort_404()
        system = _connect_to(device)
        system.connect()
        if not system.conn:
            flash(f"No se pudo conectar a '{device.name}' para apagarlo.")
            return redirect(url_for("devices_status"))
        try:
            system.poweroff_device()
            _audit(db, "device_poweroff", target=device.name)
            flash(f"Se envió el apagado a '{device.name}'. A diferencia de reiniciar, no volverá a encender solo.")
        except Exception as e:
            _audit(db, "device_poweroff", target=device.name, detail=f"ERROR: {e}")
            flash(f"Error al apagar '{device.name}': {e}")
        return redirect(url_for("devices_status"))
    finally:
        db.close()


@app.route("/devices/<int:device_pk>/clear_attendance", methods=["POST"])
@admin_required
def device_clear_attendance(device_pk):
    """Wipes the punches stored ON THE PHYSICAL TERMINAL so it starts
    accumulating from zero -- does NOT touch attendance_log in the central
    database (that history stays exactly as it is). Requires typing the
    device's name to confirm (see devices.html) since it's irreversible on
    the device side."""
    db = SessionLocal()
    try:
        device = db.get(Device, device_pk) or abort_404()
        if request.form.get("confirm_name", "").strip() != device.name:
            flash(f"El nombre escrito no coincide con '{device.name}' -- no se vació nada.")
            return redirect(url_for("devices_status"))
        system = _connect_to(device)
        system.connect()
        if not system.conn:
            flash(f"No se pudo conectar a '{device.name}' para vaciarlo.")
            return redirect(url_for("devices_status"))
        try:
            system.clear_attendance_log()
            _audit(db, "device_clear_attendance", target=device.name,
                   detail="marcaciones borradas del equipo (el historial central se conserva)")
            flash(f"'{device.name}' vaciado: sus marcaciones se borraron del equipo. El historial ya sincronizado en el panel se conserva intacto.")
        except Exception as e:
            _audit(db, "device_clear_attendance", target=device.name, detail=f"ERROR: {e}")
            flash(f"Error al vaciar '{device.name}': {e}")
        finally:
            system.disconnect()
        return redirect(url_for("devices_status"))
    finally:
        db.close()


def abort_404():
    from flask import abort
    abort(404)


# --------------------------------------------------------- device users ----
# Employees enrolled directly on a physical terminal (fingerprint/card),
# as opposed to the Employee master record kept centrally.

PRIVILEGE_LABELS = {
    zk_const.USER_DEFAULT: "Usuario",
    zk_const.USER_ADMIN: "Administrador",
    zk_const.USER_ENROLLER: "Enrolador",
    zk_const.USER_MANAGER: "Supervisor",
}


@app.route("/devices/<int:device_pk>/users")
@admin_required
def device_users(device_pk):
    db = SessionLocal()
    try:
        device = db.get(Device, device_pk) or abort_404()
        system = _connect_to(device)
        system.connect()
        if not system.conn:
            flash(f"No se pudo conectar a '{device.name}' para listar usuarios.")
            return redirect(url_for("devices_status"))
        try:
            users = system.list_device_users()
        finally:
            system.disconnect()
        for u in users:
            u['privilege_label'] = PRIVILEGE_LABELS.get(u['privilege'], str(u['privilege']))
            mapped = db.query(EmployeeMap).filter(
                EmployeeMap.device_pk == device.id, EmployeeMap.device_user_id == str(u['user_id'])
            ).first()
            u['employee'] = mapped.employee if mapped else None
        return render_template("device_users.html", device=device, users=users)
    finally:
        db.close()


@app.route("/devices/<int:device_pk>/users/new", methods=["GET", "POST"])
@admin_required
def device_user_new(device_pk):
    db = SessionLocal()
    try:
        device = db.get(Device, device_pk) or abort_404()
        employees = db.query(Employee).filter(Employee.active.is_(True)).order_by(Employee.full_name).all()
        if request.method == "POST":
            user_id = request.form["user_id"].strip()
            name = request.form["name"].strip()
            privilege = zk_const.USER_ADMIN if request.form.get("privilege") == "admin" else zk_const.USER_DEFAULT
            card = request.form.get("card", "").strip()
            employee_id = request.form.get("employee_id")

            system = _connect_to(device)
            system.connect()
            if not system.conn:
                flash(f"No se pudo conectar a '{device.name}'. No se creó el usuario.")
                return redirect(url_for("device_users", device_pk=device.id))
            try:
                created = system.create_or_update_user(
                    user_id=user_id, name=name, privilege=privilege,
                    card=int(card) if card.isdigit() else 0,
                )
            except Exception as e:
                flash(f"Error escribiendo en el dispositivo: {e}")
                return redirect(url_for("device_users", device_pk=device.id))
            finally:
                system.disconnect()

            if employee_id:
                existing_map = db.query(EmployeeMap).filter(
                    EmployeeMap.device_pk == device.id, EmployeeMap.device_user_id == user_id
                ).first()
                if existing_map:
                    existing_map.employee_id = int(employee_id)
                else:
                    db.add(EmployeeMap(device_pk=device.id, device_user_id=user_id, employee_id=int(employee_id)))
                db.commit()

            _audit(db, "device_user_add" if created else "device_user_edit",
                   target=f"{device.name}: {user_id}", detail=name)
            flash(f"Usuario '{name}' {'creado' if created else 'actualizado'} en '{device.name}'.")
            return redirect(url_for("device_users", device_pk=device.id))
        return render_template("device_user_form.html", device=device, employees=employees)
    finally:
        db.close()


@app.route("/devices/<int:device_pk>/users/<user_id>/edit", methods=["GET", "POST"])
@admin_required
def device_user_edit(device_pk, user_id):
    db = SessionLocal()
    try:
        device = db.get(Device, device_pk) or abort_404()
        employees = db.query(Employee).filter(Employee.active.is_(True)).order_by(Employee.full_name).all()
        current_map = db.query(EmployeeMap).filter(
            EmployeeMap.device_pk == device.id, EmployeeMap.device_user_id == user_id
        ).first()

        if request.method == "POST":
            name = request.form["name"].strip()
            privilege = zk_const.USER_ADMIN if request.form.get("privilege") == "admin" else zk_const.USER_DEFAULT
            card = request.form.get("card", "").strip()
            employee_id = request.form.get("employee_id")

            system = _connect_to(device)
            system.connect()
            if not system.conn:
                flash(f"No se pudo conectar a '{device.name}'. No se actualizó el usuario.")
                return redirect(url_for("device_users", device_pk=device.id))
            try:
                # create_or_update_user matches by user_id and reuses the
                # existing internal uid, so this writes an update, not a
                # second duplicate person.
                system.create_or_update_user(
                    user_id=user_id, name=name, privilege=privilege,
                    card=int(card) if card.isdigit() else 0,
                )
            except Exception as e:
                flash(f"Error escribiendo en el dispositivo: {e}")
                return redirect(url_for("device_users", device_pk=device.id))
            finally:
                system.disconnect()

            if employee_id:
                if current_map:
                    current_map.employee_id = int(employee_id)
                else:
                    db.add(EmployeeMap(device_pk=device.id, device_user_id=user_id, employee_id=int(employee_id)))
                db.commit()
            elif current_map:
                db.delete(current_map)
                db.commit()

            _audit(db, "device_user_edit", target=f"{device.name}: {user_id}", detail=name)
            flash(f"Usuario '{name}' actualizado en '{device.name}' y en la base central.")
            return redirect(url_for("device_users", device_pk=device.id))

        # GET: pull the user's current data live from the device to prefill the form.
        system = _connect_to(device)
        system.connect()
        if not system.conn:
            flash(f"No se pudo conectar a '{device.name}' para leer los datos del usuario.")
            return redirect(url_for("device_users", device_pk=device.id))
        try:
            live_user = next((u for u in system.list_device_users() if str(u['user_id']) == str(user_id)), None)
        finally:
            system.disconnect()
        if not live_user:
            flash(f"El usuario {user_id} ya no existe en '{device.name}'.")
            return redirect(url_for("device_users", device_pk=device.id))

        return render_template(
            "device_user_form.html", device=device, employees=employees,
            editing_user=live_user, current_employee_id=current_map.employee_id if current_map else None,
        )
    finally:
        db.close()


@app.route("/devices/<int:device_pk>/users/<user_id>/delete", methods=["POST"])
@admin_required
def device_user_delete(device_pk, user_id):
    db = SessionLocal()
    try:
        device = db.get(Device, device_pk) or abort_404()
        system = _connect_to(device)
        system.connect()
        if not system.conn:
            flash(f"No se pudo conectar a '{device.name}'. No se eliminó el usuario.")
            return redirect(url_for("device_users", device_pk=device.id))
        try:
            system.delete_device_user(user_id)
            _audit(db, "device_user_delete", target=f"{device.name}: {user_id}")
            flash(f"Usuario {user_id} eliminado de '{device.name}' (su historial de marcaciones se conserva).")
        except Exception as e:
            _audit(db, "device_user_delete", target=f"{device.name}: {user_id}", detail=f"ERROR: {e}")
            flash(f"Error eliminando en el dispositivo: {e}")
        finally:
            system.disconnect()
        return redirect(url_for("device_users", device_pk=device.id))
    finally:
        db.close()


# --------------------------------------------------------- employee master --

@app.route("/employees")
@admin_required
def employees_list():
    db = SessionLocal()
    try:
        employees = db.query(Employee).order_by(Employee.full_name).all()
        return render_template("employees.html", employees=employees)
    finally:
        db.close()


@app.route("/employees/new", methods=["GET", "POST"])
@admin_required
def employee_new():
    if request.method == "POST":
        db = SessionLocal()
        try:
            full_name = request.form["full_name"].strip()
            db.add(Employee(
                code=request.form.get("code", "").strip() or None,
                full_name=full_name,
                active=True,
            ))
            db.commit()
            _audit(db, "employee_add", target=full_name)
            flash("Empleado agregado al maestro.")
            return redirect(url_for("employees_list"))
        finally:
            db.close()
    return render_template("employee_form.html", employee=None)


CODE_COLUMN_NAMES = {"codigo", "código", "code", "dni", "id"}
NAME_COLUMN_NAMES = {"nombre", "nombre completo", "full_name", "name", "empleado"}


@app.route("/employees/import", methods=["GET", "POST"])
@admin_required
def employees_import():
    if request.method == "POST":
        file = request.files.get("xlsx_file")
        if not file or not file.filename:
            flash("Selecciona un archivo .xlsx.")
            return redirect(url_for("employees_import"))
        try:
            from openpyxl import load_workbook
            wb = load_workbook(file.stream, read_only=True, data_only=True)
            ws = wb.active
            rows_iter = ws.iter_rows(values_only=True)
            header = [str(h).strip().lower() if h is not None else "" for h in next(rows_iter)]
        except Exception as e:
            flash(f"No se pudo leer el archivo: {e}")
            return redirect(url_for("employees_import"))

        code_col = next((i for i, h in enumerate(header) if h in CODE_COLUMN_NAMES), None)
        name_col = next((i for i, h in enumerate(header) if h in NAME_COLUMN_NAMES), None)
        if name_col is None:
            flash(f"No encontré una columna de nombre. Encabezados vistos: {', '.join(header)}. Usa una columna llamada 'nombre' o 'full_name'.")
            return redirect(url_for("employees_import"))

        db = SessionLocal()
        try:
            created, updated, skipped = 0, 0, 0
            for row in rows_iter:
                if row is None or all(v is None for v in row):
                    continue
                full_name = str(row[name_col]).strip() if name_col < len(row) and row[name_col] is not None else ""
                code = str(row[code_col]).strip() if code_col is not None and code_col < len(row) and row[code_col] is not None else None
                if not full_name:
                    skipped += 1
                    continue
                existing = db.query(Employee).filter(Employee.code == code).first() if code else None
                if existing:
                    existing.full_name = full_name
                    updated += 1
                else:
                    db.add(Employee(code=code, full_name=full_name, active=True))
                    created += 1
            db.commit()
            _audit(db, "employee_import", detail=f"{created} creado(s), {updated} actualizado(s), {skipped} omitida(s)")
            flash(f"Importación completa: {created} creado(s), {updated} actualizado(s), {skipped} fila(s) sin nombre omitida(s).")
            return redirect(url_for("employees_list"))
        finally:
            db.close()
    return render_template("employees_import.html")


@app.route("/employees/<int:employee_id>/edit", methods=["GET", "POST"])
@admin_required
def employee_edit(employee_id):
    db = SessionLocal()
    try:
        employee = db.get(Employee, employee_id) or abort_404()
        if request.method == "POST":
            new_name = request.form["full_name"].strip()
            name_changed = new_name != employee.full_name
            push_to_devices = bool(request.form.get("push_to_devices"))

            employee.code = request.form.get("code", "").strip() or None
            employee.full_name = new_name
            employee.active = bool(request.form.get("active"))
            db.commit()

            if name_changed and push_to_devices:
                results = []
                for link in db.query(EmployeeMap).filter(EmployeeMap.employee_id == employee.id).all():
                    device = db.get(Device, link.device_pk)
                    system = _connect_to(device)
                    system.connect()
                    if not system.conn:
                        results.append(f"{device.name}: no se pudo conectar")
                        continue
                    try:
                        system.create_or_update_user(user_id=link.device_user_id, name=new_name)
                        results.append(f"{device.name}: actualizado")
                    except Exception as e:
                        results.append(f"{device.name}: error ({e})")
                    finally:
                        system.disconnect()
                _audit(db, "employee_edit", target=new_name, detail="propagado a relojes: " + "; ".join(results))
                flash("Empleado actualizado. Relojes: " + (", ".join(results) if results else "no tenía dispositivos vinculados") + ".")
            else:
                _audit(db, "employee_edit", target=new_name)
                flash("Empleado actualizado (solo en la base central).")
            return redirect(url_for("employees_list"))
        return render_template("employee_form.html", employee=employee)
    finally:
        db.close()


@app.route("/employees/unmapped")
@admin_required
def employees_unmapped():
    """(device, device_user_id) pairs seen in attendance_log that have no
    EmployeeMap yet -- the quickest way to clear out "NN-xxxxx" names."""
    db = SessionLocal()
    try:
        seen = db.query(
            AttendanceLog.device_pk, AttendanceLog.device_user_id, AttendanceLog.user_name
        ).distinct().all()
        mapped = {(m.device_pk, m.device_user_id) for m in db.query(EmployeeMap).all()}
        devices = {d.id: d for d in db.query(Device).all()}
        employees = db.query(Employee).filter(Employee.active.is_(True)).order_by(Employee.full_name).all()
        # The device_user_id is often literally the employee's DNI/código --
        # if a matching Employee.code already exists, suggest it instead of
        # defaulting every row to "create a new employee".
        by_code = {e.code: e for e in employees if e.code}
        unmapped = [{
            "device_pk": pk, "device_name": devices[pk].name if pk in devices else "?",
            "device_user_id": uid, "reported_name": name,
            "suggested": by_code.get(uid),
        } for pk, uid, name in seen if (pk, uid) not in mapped]
        return render_template("employees_unmapped.html", rows=unmapped, employees=employees)
    finally:
        db.close()


@app.route("/employees/map", methods=["POST"])
@admin_required
def employee_map_create():
    db = SessionLocal()
    try:
        device_pk = int(request.form["device_pk"])
        device_user_id = request.form["device_user_id"]
        employee_id = request.form.get("employee_id")
        new_name = request.form.get("new_employee_name", "").strip()

        if not employee_id and new_name:
            employee = Employee(full_name=new_name, active=True)
            db.add(employee)
            db.flush()
            employee_id = employee.id

        if not employee_id:
            flash("Selecciona un empleado existente o escribe un nombre nuevo.")
            return redirect(url_for("employees_unmapped"))

        existing = db.query(EmployeeMap).filter(
            EmployeeMap.device_pk == device_pk, EmployeeMap.device_user_id == device_user_id
        ).first()
        if existing:
            existing.employee_id = int(employee_id)
        else:
            db.add(EmployeeMap(device_pk=device_pk, device_user_id=device_user_id, employee_id=int(employee_id)))
        db.commit()
        _audit(db, "employee_link", target=f"device {device_pk}: {device_user_id}", detail=f"employee_id={employee_id}")
        flash("Vinculado correctamente.")
        return redirect(url_for("employees_unmapped"))
    finally:
        db.close()


# ------------------------------------------------------- dashboard users ---
# Accounts that can log into this web app (distinct from Employee/device users)

@app.route("/users")
@super_admin_required
def users_list():
    db = SessionLocal()
    try:
        users = db.query(User).order_by(User.username).all()
        return render_template("users.html", users=users)
    finally:
        db.close()


@app.route("/users/new", methods=["GET", "POST"])
@super_admin_required
def user_new():
    if request.method == "POST":
        db = SessionLocal()
        try:
            username = request.form["username"].strip()
            if db.query(User).filter(User.username == username).first():
                flash("Ese usuario ya existe.")
                return redirect(url_for("user_new"))
            role = request.form.get("role", "viewer")
            db.add(User(
                username=username,
                password_hash=hash_password(request.form["password"]),
                role=role,
                active=True,
            ))
            db.commit()
            _audit(db, "account_add", target=username, detail=f"rol: {role}")
            flash(f"Cuenta '{username}' creada.")
            return redirect(url_for("users_list"))
        finally:
            db.close()
    return render_template("user_form.html")


@app.route("/users/<int:user_pk>/toggle", methods=["POST"])
@super_admin_required
def user_toggle(user_pk):
    db = SessionLocal()
    try:
        user = db.get(User, user_pk) or abort_404()
        if user.id == flask_session.get("user_id"):
            flash("No puedes desactivar tu propia cuenta.")
        else:
            user.active = not user.active
            db.commit()
            _audit(db, "account_toggle", target=user.username, detail="activo" if user.active else "desactivado")
        return redirect(url_for("users_list"))
    finally:
        db.close()


@app.route("/users/<int:user_pk>/reset_2fa", methods=["POST"])
@super_admin_required
def user_reset_2fa(user_pk):
    """Safety valve for a lost-phone lockout: turns 2FA off for that
    account and forgets every trusted device it had, so they can log in
    with just their password and set it up again if they want."""
    db = SessionLocal()
    try:
        user = db.get(User, user_pk) or abort_404()
        user.totp_enabled = False
        user.totp_secret = None
        db.query(TrustedDevice).filter(TrustedDevice.user_id == user.id).delete()
        db.commit()
        _audit(db, "account_reset_2fa", target=user.username)
        flash(f"2FA desactivado para '{user.username}'. Puede iniciar sesión solo con su contraseña.")
        return redirect(url_for("users_list"))
    finally:
        db.close()


@app.route("/users/<int:user_pk>/unlock", methods=["POST"])
@super_admin_required
def user_unlock(user_pk):
    """Clears a lockout from MAX_LOGIN_ATTEMPTS failed passwords in a row
    -- the only way back in for that account short of a super_admin doing
    this, by design (see login())."""
    db = SessionLocal()
    try:
        user = db.get(User, user_pk) or abort_404()
        user.locked = False
        user.failed_login_attempts = 0
        db.commit()
        _audit(db, "account_unlock", target=user.username)
        flash(f"Cuenta '{user.username}' desbloqueada.")
        return redirect(url_for("users_list"))
    finally:
        db.close()


# --------------------------------------------------------------- 2FA self --

@app.route("/account/security", methods=["GET"])
@login_required
def account_security():
    db = SessionLocal()
    try:
        user = db.get(User, flask_session["user_id"])
        trusted = db.query(TrustedDevice).filter(TrustedDevice.user_id == user.id).order_by(TrustedDevice.created_at.desc()).all()
        recent_logins = (
            db.query(AuditLog)
            .filter(AuditLog.username == user.username, AuditLog.action.in_(["login", "login_failed", "login_2fa_failed"]))
            .order_by(AuditLog.timestamp.desc()).limit(10).all()
        )
        return render_template(
            "account_security.html", user=user, trusted=trusted, recent_logins=recent_logins,
            session_ip=flask_session.get("client_ip"), session_hostname=flask_session.get("client_hostname"),
        )
    finally:
        db.close()


@app.route("/account/security/2fa/setup", methods=["GET", "POST"])
@login_required
def setup_2fa():
    db = SessionLocal()
    try:
        user = db.get(User, flask_session["user_id"])
        if user.totp_enabled:
            flash("El 2FA ya está activado en tu cuenta.")
            return redirect(url_for("account_security"))

        if request.method == "POST":
            pending_secret = flask_session.get("pending_totp_secret")
            if not pending_secret or not verify_code(pending_secret, request.form.get("code", "")):
                flash("Código incorrecto. Escanea el QR de nuevo si tu app no coincide.")
                return redirect(url_for("setup_2fa"))
            user.totp_secret = pending_secret
            user.totp_enabled = True
            db.commit()
            flask_session.pop("pending_totp_secret", None)
            _audit(db, "2fa_setup", target=user.username)
            flash("2FA activado. La próxima vez que inicies sesión (desde un equipo nuevo) te pedirá el código.")
            return redirect(url_for("account_security"))

        secret = flask_session.get("pending_totp_secret") or generate_secret()
        flask_session["pending_totp_secret"] = secret
        qr = qr_data_uri(secret, user.username)
        return render_template("setup_2fa.html", qr=qr, secret=secret)
    finally:
        db.close()


@app.route("/account/security/2fa/disable", methods=["POST"])
@login_required
def disable_2fa():
    db = SessionLocal()
    try:
        user = db.get(User, flask_session["user_id"])
        if not verify_password(request.form.get("password", ""), user.password_hash):
            flash("Contraseña incorrecta -- no se desactivó el 2FA.")
            return redirect(url_for("account_security"))
        user.totp_enabled = False
        user.totp_secret = None
        db.query(TrustedDevice).filter(TrustedDevice.user_id == user.id).delete()
        db.commit()
        _audit(db, "2fa_disable", target=user.username)
        flash("2FA desactivado en tu cuenta.")
        return redirect(url_for("account_security"))
    finally:
        db.close()


@app.route("/account/security/trusted/<int:trusted_id>/revoke", methods=["POST"])
@login_required
def revoke_trusted_device(trusted_id):
    db = SessionLocal()
    try:
        row = db.get(TrustedDevice, trusted_id)
        if not row or row.user_id != flask_session["user_id"]:
            abort_404()
        db.delete(row)
        db.commit()
        flash("Dispositivo olvidado -- la próxima vez pedirá el código de nuevo ahí.")
        return redirect(url_for("account_security"))
    finally:
        db.close()


# ------------------------------------------------------- backup/restore ---

@app.route("/backup")
@super_admin_required
def backup_page():
    db = SessionLocal()
    try:
        counts = {
            "devices": db.query(Device).count(),
            "employees": db.query(Employee).count(),
            "employee_map": db.query(EmployeeMap).count(),
            "attendance_log": db.query(AttendanceLog).count(),
            "users": db.query(User).count(),
        }
        return render_template("backup.html", counts=counts)
    finally:
        db.close()


@app.route("/backup/export")
@super_admin_required
def backup_export():
    db = SessionLocal()
    try:
        data = export_data(db)
        filename = f"asistencia_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        _audit(db, "backup_export", target=filename)
        return Response(
            json.dumps(data, ensure_ascii=False, indent=2),
            mimetype="application/json",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    finally:
        db.close()


@app.route("/backup/import", methods=["POST"])
@super_admin_required
def backup_import():
    if not request.form.get("confirm"):
        flash("Debes marcar la casilla de confirmación para restaurar un backup.")
        return redirect(url_for("backup_page"))
    file = request.files.get("backup_file")
    if not file or not file.filename:
        flash("Selecciona un archivo de backup (.json).")
        return redirect(url_for("backup_page"))
    try:
        data = json.load(file.stream)
    except Exception as e:
        flash(f"El archivo no es un JSON válido: {e}")
        return redirect(url_for("backup_page"))

    db = SessionLocal()
    try:
        counts = import_data(db, data)
        db.commit()
        _audit(db, "backup_import", target=file.filename, detail=", ".join(f"{k}: {v}" for k, v in counts.items()))
        flash(
            "Backup restaurado. "
            + ", ".join(f"{k}: {v}" for k, v in counts.items())
            + ". Tu sesión puede haber quedado inválida si tu cuenta no estaba en el backup — vuelve a iniciar sesión si es necesario."
        )
        return redirect(url_for("backup_page"))
    except Exception as e:
        db.rollback()
        flash(f"Error restaurando el backup (no se aplicó ningún cambio): {e}")
        return redirect(url_for("backup_page"))
    finally:
        db.close()


# ------------------------------------------------------------ audit log ---

@app.route("/audit")
@super_admin_required
def audit_log():
    db = SessionLocal()
    try:
        query = db.query(AuditLog)
        action_filter = request.args.get("action", "").strip()
        username_filter = request.args.get("username", "").strip()
        date_from = request.args.get("from", "").strip()
        date_to = request.args.get("to", "").strip()

        if action_filter:
            query = query.filter(AuditLog.action == action_filter)
        if username_filter:
            query = query.filter(AuditLog.username == username_filter)
        if date_from:
            query = query.filter(AuditLog.timestamp >= datetime.strptime(date_from, "%Y-%m-%d"))
        if date_to:
            query = query.filter(AuditLog.timestamp < datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1))

        page = max(1, request.args.get("page", 1, type=int))
        total = query.count()
        rows = (
            query.order_by(AuditLog.timestamp.desc())
            .offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE).all()
        )
        actions = [a for (a,) in db.query(AuditLog.action).distinct().order_by(AuditLog.action).all()]
        usernames = [u for (u,) in db.query(AuditLog.username).distinct().filter(AuditLog.username.isnot(None)).order_by(AuditLog.username).all()]
        return render_template(
            "audit.html", rows=rows, total=total, page=page, page_size=PAGE_SIZE,
            actions=actions, usernames=usernames,
            filters={"action": action_filter, "username": username_filter, "from": date_from, "to": date_to},
        )
    finally:
        db.close()


@app.route("/audit/export.csv")
@super_admin_required
def audit_export_csv():
    db = SessionLocal()
    try:
        rows = db.query(AuditLog).order_by(AuditLog.timestamp.desc()).all()
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["Fecha/Hora (UTC)", "Usuario", "Acción", "Objetivo", "Detalle", "IP", "Equipo (PC)", "Navegador"])
        for r in rows:
            writer.writerow([
                r.timestamp.strftime("%Y-%m-%d %H:%M:%S"), r.username or "", r.action,
                r.target or "", r.detail or "", r.ip_address or "", r.hostname or "", r.user_agent or "",
            ])
        filename = f"auditoria_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        return Response(
            buf.getvalue(), mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    finally:
        db.close()


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
