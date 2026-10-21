"""
Página de estado, SOLO LECTURA, para el agente remoto -- pensada para
alguien físicamente en la sede (o en su red local) que quiere confirmar
"¿este agente está vivo, llega a la central, y ve mis biométricos?" sin
necesitar PowerShell ni VPN hacia la central.

Deliberadamente NO es una copia del panel central (central/webapp.py):
este agente es un puente, no una segunda fuente de verdad -- duplicar
login, roles, auditoría, etc. acá solo generaría confusión sobre cuál
panel es el real. Es una sola página, sin autenticación (de solo
lectura, en la misma red local que ya tiene acceso directo a los
biométricos, mismo nivel de confianza) que:
  - confirma que esta base compartida con la central responde,
  - lista los dispositivos que este agente administra (Device.agent_name
    == AGENT_NAME) con su último estado de sincronización,
  - prueba la conexión de red (TCP, sin protocolo ZK) a cada uno EN VIVO
    cada vez que se carga la página -- simple y suficiente para "¿está
    prendido y en la red ahora mismo?", sin necesitar JavaScript.

Se levanta en un hilo de fondo desde central/remote_agent.py#main(),
aparte del bucle de sincronización/comandos -- ver AGENT_STATUS_PORT.
"""
from datetime import datetime

from flask import Flask, render_template_string

from attendance_system import check_network_reachable
from central.db import SessionLocal
from central.models import Device

app = Flask(__name__)

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
          <th>Última sincronización</th><th>Resultado</th>
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
        </tr>
        {% endfor %}
      </table>
    {% endif %}
  </div>

  <div class="card refresh">
    Esto SOLO muestra estado -- para reiniciar/vaciar/gestionar usuarios de un equipo, hacelo desde el
    panel central. "Red ahora" es un chequeo de red simple (TCP), no abre el protocolo del reloj --
    se repite cada vez que se recarga esta página, no hace falta nada más para refrescarlo.
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
                "name": d.name, "ip": d.ip, "port": d.port,
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
