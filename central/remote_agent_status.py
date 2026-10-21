"""
Página de estado para el agente remoto -- pensada para alguien
físicamente en la sede (o en su red local) que quiere confirmar "¿este
agente está vivo, llega a la central, y ve mis biométricos?", y además
hacer un diagnóstico real o bajar un respaldo SIN necesitar PowerShell
ni VPN hacia la central.

Deliberadamente NO es una copia del panel central (central/webapp.py):
este agente es un puente, no una segunda fuente de verdad -- duplicar
login, roles, auditoría, etc. acá solo generaría confusión sobre cuál
panel es el real. Es una página sin autenticación (misma red local que
ya tiene acceso directo a los biométricos, mismo nivel de confianza)
que:
  - confirma que esta base compartida con la central responde,
  - lista los dispositivos que este agente administra (Device.agent_name
    == AGENT_NAME) con su último estado de sincronización,
  - prueba la conexión de red (TCP, sin protocolo ZK) a cada uno EN VIVO
    cada vez que se carga la página,
  - y, con un botón, puede abrir una sesión real al equipo (probar
    conexión de verdad, ver sus usuarios, o descargar TODAS sus
    marcaciones) -- reutilizando central.remote_agent._run_action(), la
    MISMA función que ya usa el puente cuando un comando llega desde el
    panel central, así que un botón acá y un clic en el panel central no
    pueden chocar sin que el candado compartido (device_lock.py) lo
    note. Sigue siendo de solo lectura hacia el EQUIPO (nada que
    reinicie/apague/vacíe/edite usuarios) -- para eso, el panel central.

Se levanta en un hilo de fondo desde central/remote_agent.py#main(),
aparte del bucle de sincronización/comandos -- ver AGENT_STATUS_PORT.
"""
import csv
import io
from datetime import datetime

from flask import Flask, Response, render_template_string

from attendance_system import check_network_reachable
from central.db import SessionLocal
from central.device_lock import DeviceBusy
from central.models import Device
from central.remote_agent import _run_action

try:
    from zk import const as zk_const
    PRIVILEGE_LABELS = {
        zk_const.USER_DEFAULT: "Usuario",
        zk_const.USER_ADMIN: "Administrador",
        zk_const.USER_ENROLLER: "Enrolador",
        zk_const.USER_MANAGER: "Supervisor",
    }
except Exception:
    PRIVILEGE_LABELS = {}

app = Flask(__name__)


def _get_owned_device(session, device_pk):
    """Solo deja operar dispositivos que de verdad pertenecen a ESTE
    agente -- aunque la base sea compartida con la central, esta página
    no debería poder tocar (ni mostrar por error) un equipo de otra
    sede."""
    agent_name = app.config["AGENT_NAME"]
    device = session.get(Device, device_pk)
    if not device or device.deleted or device.agent_name != agent_name:
        return None
    return device

PAGE = """
<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agente remoto - {{ agent_name }}</title>
<style>
  body { font-family: "Segoe UI", Arial, sans-serif; background: #1f2937; color: #111827; margin: 0; padding: 24px; }
  .card { background: #fff; border-radius: 8px; padding: 20px 24px; max-width: 900px; margin: 0 auto 16px; box-shadow: 0 4px 12px rgba(0,0,0,.3); }
  h1 { font-size: 20px; margin: 0 0 4px; }
  .sub { color: #6b7280; font-size: 13px; margin-bottom: 16px; }
  .ok { color: #15803d; font-weight: 600; }
  .fail { color: #b91c1c; font-weight: 600; }
  table { width: 100%; border-collapse: collapse; margin-top: 8px; }
  th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid #e5e7eb; font-size: 14px; }
  th { color: #6b7280; font-weight: 600; font-size: 12px; text-transform: uppercase; }
  .pill { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 12px; font-weight: 600; }
  .pill-ok { background: #dcfce7; color: #15803d; }
  .pill-fail { background: #fee2e2; color: #b91c1c; }
  .refresh { font-size: 13px; color: #6b7280; }
  a.refresh-link { color: #2563eb; }
  .actions form { display: inline-block; margin: 2px 4px 2px 0; }
  .actions button { font-size: 12px; padding: 4px 8px; border-radius: 6px; border: 1px solid #d1d5db; background: #f3f4f6; cursor: pointer; }
  .actions button:hover { background: #e5e7eb; }
</style>
</head>
<body>
  <div class="card">
    <h1>Agente remoto: {{ agent_name }}</h1>
    <div class="sub">Consultado el {{ now }} -- <a class="refresh-link" href="">volver a revisar ahora</a></div>
    <div>Conexión a la base de datos central:
      {% if db_ok %}<span class="ok">OK</span>{% else %}<span class="fail">FALLÓ -- {{ db_error }}</span>{% endif %}
    </div>
  </div>

  <div class="card">
    <h1>Biométricos de esta sede ({{ devices|length }})</h1>
    {% if not db_ok %}
      <p>No se puede listar -- no hay conexión a la base central (ver arriba).</p>
    {% elif not devices %}
      <p>Ningún dispositivo tiene <code>Agente remoto = {{ agent_name }}</code> todavía en el panel central.
         Configuralo en <strong>Dispositivos</strong> → editar cada equipo de esta sede.</p>
    {% else %}
      <table>
        <tr>
          <th>Nombre</th><th>IP:Puerto</th><th>Red ahora</th>
          <th>Última sincronización</th><th>Resultado</th><th>Acciones</th>
        </tr>
        {% for d in devices %}
        <tr>
          <td>{{ d.name }}</td>
          <td>{{ d.ip }}:{{ d.port }}</td>
          <td>
            {% if d.reachable %}<span class="pill pill-ok">responde</span>
            {% else %}<span class="pill pill-fail">{{ d.reach_detail }}</span>{% endif %}
          </td>
          <td>{{ d.last_synced_at or "nunca" }}</td>
          <td>{{ d.last_sync_status or "-" }}</td>
          <td class="actions">
            <form method="post" action="/device/{{ d.id }}/test">
              <button type="submit">Probar conexión real</button>
            </form>
            <form method="post" action="/device/{{ d.id }}/users">
              <button type="submit">Ver usuarios</button>
            </form>
            <form method="post" action="/device/{{ d.id }}/backup">
              <button type="submit">Descargar marcaciones</button>
            </form>
          </td>
        </tr>
        {% endfor %}
      </table>
    {% endif %}
  </div>

  <div class="card refresh">
    "Red ahora" es solo un chequeo de red (TCP, sin abrir el protocolo del reloj) -- se repite cada vez
    que se recarga la página. Los tres botones de Acciones sí abren una sesión real al equipo (puede
    tardar unos segundos) y comparten el mismo candado que usa el panel central, así que no van a
    chocar con una sincronización en curso. Para reiniciar/apagar/vaciar/editar usuarios de un equipo,
    hacelo desde el panel central -- acá es intencionalmente de solo lectura hacia el dispositivo.
  </div>
</body>
</html>
"""

RESULT_PAGE = """
<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }} - {{ agent_name }}</title>
<style>
  body { font-family: "Segoe UI", Arial, sans-serif; background: #1f2937; color: #111827; margin: 0; padding: 24px; }
  .card { background: #fff; border-radius: 8px; padding: 20px 24px; max-width: 900px; margin: 0 auto 16px; box-shadow: 0 4px 12px rgba(0,0,0,.3); }
  h1 { font-size: 20px; margin: 0 0 4px; }
  .ok { color: #15803d; font-weight: 600; }
  .fail { color: #b91c1c; font-weight: 600; }
  table { width: 100%; border-collapse: collapse; margin-top: 8px; }
  th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid #e5e7eb; font-size: 14px; }
  th { color: #6b7280; font-weight: 600; font-size: 12px; text-transform: uppercase; }
  a.back { color: #2563eb; font-size: 13px; }
</style>
</head>
<body>
  <div class="card">
    <h1>{{ title }}</h1>
    <p class="{{ 'ok' if ok else 'fail' }}">{{ msg }}</p>
    {% if users %}
    <table>
      <tr><th>ID</th><th>Nombre</th><th>Privilegio</th><th>Tarjeta</th></tr>
      {% for u in users %}
      <tr><td>{{ u.user_id }}</td><td>{{ u.name }}</td><td>{{ u.privilege_label }}</td><td>{{ u.card or '-' }}</td></tr>
      {% endfor %}
    </table>
    {% endif %}
    <p><a class="back" href="/">&larr; volver</a></p>
  </div>
</body>
</html>
"""


@app.route("/")
def status():
    agent_name = app.config["AGENT_NAME"]
    db_ok, db_error = True, None
    devices = []
    session = SessionLocal()
    try:
        rows = session.query(Device).filter(
            Device.agent_name == agent_name, Device.deleted.is_(False),
        ).order_by(Device.name).all()
        for d in rows:
            reachable, detail = check_network_reachable(d.ip, d.port, timeout=2)
            devices.append({
                "id": d.id, "name": d.name, "ip": d.ip, "port": d.port,
                "reachable": reachable, "reach_detail": detail,
                "last_synced_at": d.last_synced_at.strftime("%Y-%m-%d %H:%M") if d.last_synced_at else None,
                "last_sync_status": d.last_sync_status,
            })
    except Exception as e:
        db_ok, db_error = False, str(e)
    finally:
        session.close()

    return render_template_string(
        PAGE, agent_name=agent_name, now=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        db_ok=db_ok, db_error=db_error, devices=devices,
    )


@app.route("/device/<int:device_pk>/test", methods=["POST"])
def device_test(device_pk):
    """Abre una sesión real (no solo TCP) y pide modelo/serie -- la misma
    acción "test" que usa el botón 'Probar conexión' del panel central,
    pero corrida directo desde acá (sin pasar por el puente), útil
    cuando lo que se quiere descartar es justamente si el puente es el
    problema."""
    agent_name = app.config["AGENT_NAME"]
    session = SessionLocal()
    try:
        device = _get_owned_device(session, device_pk)
        if not device:
            return "Dispositivo no encontrado para este agente.", 404
        name = device.name
        try:
            result = _run_action(session, device, "test", {})
            if result is None:
                ok, msg = False, (
                    "El equipo respondió en la red pero rechazó la conexión -- "
                    "revisá la Clave de comunicación configurada para este dispositivo en el panel central."
                )
            else:
                ok = True
                msg = f"Conexión real OK. Modelo: {result['model'] or '?'} -- N° de serie: {result['serial'] or '?'}."
        except DeviceBusy as e:
            ok, msg = False, str(e)
        except Exception as e:
            ok, msg = False, f"Error: {e}"
    finally:
        session.close()
    return render_template_string(
        RESULT_PAGE, title=f"Probar conexión real -- {name}", agent_name=agent_name, ok=ok, msg=msg, users=None,
    )


@app.route("/device/<int:device_pk>/users", methods=["POST"])
def device_users(device_pk):
    """Lista los usuarios enrolados EN EL EQUIPO ahora mismo (huellas/
    tarjetas), igual que 'Usuarios' en el panel central -- de solo
    lectura, no permite crear/editar/borrar desde acá."""
    agent_name = app.config["AGENT_NAME"]
    session = SessionLocal()
    try:
        device = _get_owned_device(session, device_pk)
        if not device:
            return "Dispositivo no encontrado para este agente.", 404
        name = device.name
        users = None
        try:
            raw_users = _run_action(session, device, "list_users", {})
            for u in raw_users:
                u["privilege_label"] = PRIVILEGE_LABELS.get(u["privilege"], str(u["privilege"]))
            users = raw_users
            ok, msg = True, f"{len(users)} usuario(s) en el equipo."
        except DeviceBusy as e:
            ok, msg = False, str(e)
        except Exception as e:
            ok, msg = False, f"Error: {e}"
    finally:
        session.close()
    return render_template_string(
        RESULT_PAGE, title=f"Usuarios del equipo -- {name}", agent_name=agent_name, ok=ok, msg=msg, users=users,
    )


@app.route("/device/<int:device_pk>/backup", methods=["POST"])
def device_backup(device_pk):
    """Descarga un CSV con TODAS las marcaciones que hay ahora mismo EN
    EL EQUIPO, igual que 'Descargar respaldo' en el panel central --
    y de paso guarda en la base central las que todavía no tenía (mismo
    dedup de siempre), útil cuando la sincronización disparada desde el
    panel central viene lenta o falla, porque esta corre directo en la
    red local del equipo, sin pasar por el puente."""
    agent_name = app.config["AGENT_NAME"]
    session = SessionLocal()
    try:
        device = _get_owned_device(session, device_pk)
        if not device:
            return "Dispositivo no encontrado para este agente.", 404
        name = device.name
        try:
            result = _run_action(session, device, "backup", {})
            rows = result.get("rows") or []
        except DeviceBusy as e:
            return render_template_string(
                RESULT_PAGE, title=f"Descargar marcaciones -- {name}", agent_name=agent_name,
                ok=False, msg=str(e), users=None,
            )
        except Exception as e:
            return render_template_string(
                RESULT_PAGE, title=f"Descargar marcaciones -- {name}", agent_name=agent_name,
                ok=False, msg=f"Error: {e}", users=None,
            )
    finally:
        session.close()

    if not rows:
        return render_template_string(
            RESULT_PAGE, title=f"Descargar marcaciones -- {name}", agent_name=agent_name,
            ok=True, msg=f"'{name}' no tiene marcaciones guardadas en el equipo ahora mismo -- no hay nada que respaldar.",
            users=None,
        )

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["user_id", "user_name", "timestamp", "status"])
    for r in rows:
        writer.writerow([r.get("user_id"), r.get("user_name"), r.get("timestamp"), r.get("status")])
    filename = f"respaldo_{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        buf.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
