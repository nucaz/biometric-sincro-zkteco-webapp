# Central Attendance Service

Consolida las marcaciones de varios relojes ZKTeco (distintas sedes, mismo
tipo de conexión que ya usa `attendance_gui.py`) en una sola base de datos,
con un panel web para que RRHH lo revise, gestione dispositivos y dé de
alta empleados sin tocar la app de escritorio ni el menú del reloj.

Probado con un K20 real (30k+ marcaciones). El protocolo (pyzk) es
genérico a toda la familia ZKTeco clásica (TCP/UDP, sin ADMS) — debería
funcionar igual con el ZK30 y el ZKG3 en cuanto tengas su IP; solo usa
"Probar conexión" desde el panel para confirmar modelo/serie de cada uno.

## Piezas

- `models.py` — esquema: `devices`, `attendance_log`, `employees`,
  `employee_map`, `users` (cuentas del panel).
- `sync.py` — recorre los dispositivos activos, jala sus marcaciones y
  las inserta (sin duplicar) en `attendance_log`. Pensado para correr
  periódicamente (Task Scheduler / cron), no como servicio permanente.
- `seed_devices.py` — importa `devices.json` (el que ya usa la app de
  escritorio) a la tabla `devices`. Se puede re-correr sin duplicar.
- `create_admin.py` — crea/actualiza una cuenta de acceso al panel.
- `backup.py` — export/import completo de la base en JSON (portable entre
  SQLite/PostgreSQL/MySQL), usado por la pantalla Backup del panel.
- `webapp.py` — dashboard Flask:
  - **Marcaciones**: filtra por sede/dispositivo/fecha/nombre, dos vistas
    (resumen por día o marcaciones crudas), exporta a CSV, Excel (con
    estilo, filtros y auto-ancho) o PDF (con encabezado, franjas y pie de
    página con paginación).
  - **Dispositivos**: tarjetas por equipo (no una tabla apretada) con
    Editar, Usuarios, Probar conexión, Ping, Reiniciar y Apagar — más un
    botón "Sincronizar ahora" para no depender de la tarea programada.
  - **Usuarios de un dispositivo** (`/devices/<id>/users`): lista en vivo
    quién está enrolado en ESE reloj físico, con alta/edición/baja directa
    (busca por ID/DNI, apellido o código) — escribe en el equipo real vía
    el SDK (`attendance_system.py` -> `create_or_update_user` /
    `delete_device_user`). Editar un empleado en el maestro central
    también puede empujar el nombre nuevo a todos los relojes donde esté
    vinculado.
  - **Empleados**: maestro central, y pantalla "Sin vincular" para
    asignarle nombre real a los `NN-xxxxx`.
  - **Cuentas** y **Backup**: solo para super administradores.

### Roles

| Rol | Puede |
|---|---|
| `viewer` (solo lectura) | Ver marcaciones y dispositivos, exportar (CSV/Excel/PDF). Nada de escritura. |
| `admin` | Todo lo de `viewer` + agregar/editar/reiniciar dispositivos, gestionar empleados y usuarios del reloj. |
| `super_admin` | Todo lo de `admin` + cuentas del panel (`/users`) y backup/restore (`/backup`). |

## Por qué el `user_id` del reloj no basta

El ID de un empleado en el reloj A (ej. "5") **no tiene relación** con el
ID "5" en el reloj B — son numeraciones internas independientes. Por eso
todo en este esquema se referencia por `(device_id, device_user_id)`
junto, nunca por `device_user_id` solo. La tabla `employee_map` conecta
esa pareja con un `Employee` del maestro central; si el mismo empleado
está en varias sedes, cada sede tiene su propia fila en `employee_map`
apuntando al mismo `Employee`.

## Dar de alta un empleado en el reloj físico — qué hace y qué no

Desde `/devices/<id>/users/new` el panel escribe directo en el equipo
(ID + nombre + privilegio + tarjeta opcional). **No puede registrar la
huella remotamente** — eso sigue siendo físico: la persona debe acercarse
al reloj después de creada para que el propio equipo capture su huella.
Al crear, si el `user_id` ya existe en ese reloj se ACTUALIZA (nunca
duplica); internamente se resuelve por el `uid` real del dispositivo,
no adivinado. Eliminar un usuario del dispositivo borra su huella/tarjeta
del equipo pero **conserva su historial de marcaciones** en la base
central (el borrado nunca toca `attendance_log`).

## Puesta en marcha (prueba local con SQLite, cero configuración)

```bash
pip install -r central/requirements.txt
python -m central.seed_devices               # importa devices.json
python -m central.create_admin admin TU_CLAVE # primera cuenta de acceso
python -m central.sync                        # primera sincronización manual
python -m central.webapp                      # abre http://localhost:5000
```

## Pasar a PostgreSQL/MySQL para producción

Con la VPN entre sedes que ya tienen, este mismo `sync.py` corriendo
desde un servidor central puede alcanzar todos los relojes directo —
no hace falta un agente por sede. Solo:

```bash
set DATABASE_URL=postgresql+psycopg2://usuario:clave@servidor:5432/asistencia
python -m central.seed_devices
python -m central.create_admin admin TU_CLAVE
python -m central.sync
python -m central.webapp
```

(en Linux: `export DATABASE_URL=...`)

## Automatizar la sincronización periódica

Windows Task Scheduler, acción:
`<ruta al venv>\Scripts\python.exe -m central.sync`
directorio de inicio: la carpeta del proyecto. Cada 15-30 min es un
buen punto de partida; se puede correr más seguido sin riesgo, cada
corrida solo inserta lo nuevo.

## Agregar el ZK30 / ZKG3

1. En el panel: **Dispositivos → + Agregar dispositivo** (nombre, sede,
   IP, puerto) — o con el botón "Add" de la app de escritorio y luego
   `python -m central.seed_devices`.
2. **Probar conexión** — confirma que responde y captura su modelo y
   número de serie reales (así se identifica de forma estable aunque
   cambie de IP después).
3. La siguiente corrida de `central.sync` ya lo incluye automáticamente.

## Pendiente para producción real

- `webapp.py` usa el servidor de desarrollo de Flask (`debug=True`).
  Para producción, servirlo con `waitress` o `gunicorn` detrás de IIS/nginx.
- No hay HTTPS propio: si esto se expone fuera de la red interna,
  ponerlo detrás de un proxy con TLS.
- `sync.py` y las pantallas de "Usuarios del dispositivo" no pueden
  correr al mismo tiempo contra el mismo reloj (el equipo solo acepta
  una sesión a la vez) — si programas el sync muy seguido, evita usar
  esas pantallas de alta/baja justo en ese momento.
