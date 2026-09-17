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
- `audit.py` + tabla `audit_log` — registro de conexiones (login, 2FA,
  ping/probar conexión) y cambios (dispositivos, empleados, cuentas,
  backup), con IP y, cuando la red lo permite, el nombre de la PC por DNS
  inverso. Ver la pantalla **Auditoría** (solo super admin). Nunca se
  edita ni se borra desde la aplicación, y sobrevive a un restore de
  backup (no está entre las tablas que `backup.py` toca).
- `webapp.py` — dashboard Flask:
  - **Marcaciones**: filtra por sede/dispositivo/fecha/nombre, dos vistas
    (resumen por día o marcaciones crudas), exporta a CSV, Excel (con
    estilo, filtros y auto-ancho) o PDF (con encabezado, franjas y pie de
    página con paginación).
  - **Dispositivos**: tarjetas por equipo (no una tabla apretada) con
    Editar, Usuarios, Probar conexión, Ping, Reiniciar, Apagar, **Descargar
    respaldo**, **Vaciar dispositivo** y **Eliminar** (nunca borra el
    historial -- solo oculta el dispositivo, con un botón "Restaurar" en
    "Ver eliminados"). Los botones "Sincronizar todos"/"Sincronizar este"
    se deshabilitan mientras trabajan y muestran el resultado al terminar
    (cuántos registros nuevos, o el error) -- una versión anterior con una
    ventana de progreso en vivo resultó demasiado frágil en la práctica y
    se volvió a este diseño más simple, con el mismo tope duro de 150s por
    si el dispositivo se cuelga. Ese mismo tope protege "Usuarios",
    "Sincronizar" y "Descargar respaldo" -- ninguno se queda esperando
    para siempre ni tumba la página con un error 500 si el equipo no
    responde.
  - **Usuarios de un dispositivo** (`/devices/<id>/users`): lista en vivo
    quién está enrolado en ESE reloj físico, con alta/edición/baja directa
    (busca por ID/DNI, apellido o código) — escribe en el equipo real vía
    el SDK (`attendance_system.py` -> `create_or_update_user` /
    `delete_device_user`). Incluye el privilegio ("Usuario" o
    "Administrador del equipo" -- este último es quien puede operar el
    menú físico y hacer respaldo por USB en ese reloj) y su PIN local
    para ese mismo menú/respaldo, independiente de la "comm key" del
    dispositivo (usada por esta app para conectarse remotamente) y de la
    clave de este panel web. Editar un empleado en el maestro central
    también puede empujar el nombre nuevo a todos los relojes donde esté
    vinculado, y desactivarlo puede eliminar su enrolamiento de esos
    mismos relojes (ver más abajo).
  - **Empleados**: maestro central, y pantalla "Sin vincular" para
    asignarle nombre real a los `NN-xxxxx`. Al editar uno con "Propagar
    a los relojes" marcado: si cambia el nombre, lo actualiza en cada
    reloj donde está vinculado; si se desactiva, elimina su huella/
    tarjeta de esos mismos relojes (revoca el acceso físico real) --
    en ambos casos su historial de marcaciones en la base central
    nunca se toca.
  - **Cuentas** (solo super admin): alta, Eliminar (no puedes borrar la
    tuya propia), Desactivar/Activar, Resetear contraseña (fija una
    nueva sin necesitar la anterior), Resetear 2FA y Desbloquear (tras
    3 intentos fallidos de inicio de sesión -- el bloqueo es por cuenta,
    nunca por IP/equipo, así que otra cuenta desde la misma máquina
    sigue funcionando normal).
  - **Backup**: solo para super administradores.

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

## Cómo se identifica el equipo (PC) de quien inicia sesión

Un navegador no puede reportar el nombre Windows de su propia PC -- ninguna
API web lo expone, por diseño de privacidad. Lo que sí se captura en cada
login: la IP del cliente (siempre) y, mejor esfuerzo, su nombre por DNS
inverso sobre esa IP. En una red con Active Directory/DNS interno con
registro automático (lo normal en un dominio Windows), esto resuelve al
nombre real de la PC; en una red plana sin esos registros, simplemente
queda vacío y solo se ve la IP. Se resuelve una sola vez por sesión (al
hacer login) y se reusa para el resto de esa sesión, no en cada clic.

## Por qué "TCP packet invalid" podía tumbar una sincronización entera

Encontrado sincronizando un K20 real (PISO2) que fallaba de forma
intermitente: cuando la descarga masiva de marcaciones se corrompía a
mitad de camino (paquete de red perdido, timeout corto), el propio
`disconnect()` de limpieza *también* fallaba al intentar leer la
confirmación del comando -- y esa segunda falla, sin capturar, tapaba el
error real y abortaba todo el intento sin reintentarlo. Corregido en
`attendance_system.py` (`disconnect()` ya no puede tumbar al que lo llama)
y en `sync.py` (reintenta hasta 3 veces con un timeout de 20s para la
descarga masiva, en vez de los 5s por defecto de una conexión rápida).
Confirmado con una sincronización real contra PISO2: 102 marcaciones
nuevas, sin error, tras timeouts previos en el mismo dispositivo.

## Sincronización: siempre trae el historial completo del reloj, nunca solo "lo nuevo"

El protocolo ZK (pyzk) no tiene un comando "dame solo las marcaciones desde
tal fecha" -- `get_attendance()` siempre devuelve TODO lo que el reloj
tiene guardado en ese momento. Lo "incremental" pasa del lado de la base
central: cada corrida compara lo descargado contra lo que ya existe
(por dispositivo + id + fecha/hora exacta) e inserta solo lo que falta.
En la práctica esto ya equivale a una "sincronización completa" cada vez
que se corre -- no hace falta un botón aparte para eso.

## Respaldar un dispositivo antes de vaciarlo

Botón **Descargar respaldo** en cada tarjeta. Se conecta una sola vez al
equipo, descarga TODAS las marcaciones que tiene guardadas ahora mismo
(no solo las que faltan por sincronizar) y hace dos cosas con ellas: las
guarda en la base central igual que "Sincronizar" (dedup por
`device_user_id` + `timestamp`, nunca duplica), y además te entrega un
CSV descargable con ese mismo contenido como respaldo independiente. La
idea es no depender solo de confiar en el dedup de la base central justo
antes de un "Vaciar dispositivo" -- el archivo queda como evidencia de lo
que había en el reloj en ese momento exacto.

## Vaciar un dispositivo (empezar de cero)

Botón **Vaciar dispositivo** en cada tarjeta (pide escribir el nombre
exacto del equipo para confirmar, es irreversible del lado del reloj).
Borra las marcaciones guardadas EN EL EQUIPO -- el historial que ya está
en `attendance_log` **no se toca**. Útil para no acumular años de datos en
la memoria del reloj sin perder nada de lo ya sincronizado. Los usuarios
enrolados (huellas/tarjetas) no se ven afectados, solo el registro de
marcaciones.

## Pendiente para producción real

- `webapp.py` usa el servidor de desarrollo de Flask (`debug=True`).
  Para producción, servirlo con `waitress` o `gunicorn` detrás de IIS/nginx.
- No hay HTTPS propio: si esto se expone fuera de la red interna,
  ponerlo detrás de un proxy con TLS.
- `sync.py` y las pantallas de "Usuarios del dispositivo" no pueden
  correr al mismo tiempo contra el mismo reloj (el equipo solo acepta
  una sesión a la vez) — si programas el sync muy seguido, evita usar
  esas pantallas de alta/baja justo en ese momento.
