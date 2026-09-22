# Prompt maestro del proyecto (leer primero)

Este archivo es el contexto persistente del proyecto para Claude Code. Se
lee automáticamente al abrir este repo en cualquier computadora. Está
escrito para que una sesión nueva, sin memoria de las anteriores, pueda
seguir trabajando sin que el usuario tenga que re-explicar todo desde
cero.

**Regla para Claude Code**: cada vez que termines un cambio importante
(feature, fix de bug real, decisión de arquitectura), actualiza la
sección "Estado actual / pendientes" de este archivo antes de terminar
la conversación, y añade un resumen al `CHANGELOG.md` como ya se viene
haciendo. No hace falta preguntarle al usuario si debes actualizarlo —
hazlo como parte natural de cerrar el cambio, igual que ya actualizas el
changelog.

## Quién es el usuario

Juan Carlos Aguirre, encargado de esta plataforma de asistencia
biométrica para una empresa con varias sedes en Lima, Perú (huso horario
America/Lima, UTC-5). Una de las sedes se llama "PUEBLO LIBRE". No es
necesariamente programador de formación — las instrucciones que da
suelen describir el síntoma o la necesidad de negocio, no la solución
técnica ("no veo la opción para...", "sería bueno que se pueda..."), así
que hay que investigar la causa raíz antes de proponer un fix, y
explicar los cambios en español llano, sin jerga innecesaria. Cuando
duda de un diagnóstico previo (p.ej. "el problema no es el ping, el
problema es la conexión") hay que tomarlo en serio y re-investigar, no
descartarlo ni tampoco aceptarlo ciegamente — verificar con evidencia
real (logs de auditoría, pruebas contra el equipo real) antes de
responder.

Trabaja normalmente desde `D:\PROYECTOS JCAGUIRRE-SOFTWARE
DEPILZONE\Biometrico\zkteco-attendance-system-main` en Windows. El
servidor de producción es un Windows Server con una carpeta mapeada
como unidad de red (`Z:\Asistencia` en algunas sesiones) que se puede
usar para inspeccionar en modo solo-lectura la base real y los logs,
pero **nunca** para escribir directo en producción salvo permiso
explícito y puntual del usuario.

## Qué es este proyecto

Plataforma de asistencia biométrica con relojes ZKTeco (protocolo
`pyzk`), dos componentes:

- **App de escritorio** (`attendance_system.py` + GUI): standalone,
  pensada para uso local/directo contra un equipo.
- **Panel web central** (`central/`): Flask + SQLAlchemy + Jinja2,
  sincroniza varios relojes a una sola base (SQLite en Windows,
  Postgres opcional en Linux), con dashboard de RRHH, roles, 2FA,
  exportes, auditoría, gestión de cuentas y de dispositivos. Se sirve
  con `waitress` como una tarea programada de Windows en producción.

Repo: `github.com/nucaz/biometric-sincro-zkteco-webapp.git`, rama
`main`. El detalle línea por línea de cada cambio vive en
[`CHANGELOG.md`](CHANGELOG.md) — este archivo es el resumen
"por qué está así" que el changelog no cuenta.

## Arquitectura y decisiones clave

- **`central/webapp.py`**: rutas Flask. Todas las rutas que hablan con
  un dispositivo físico pasan por `run_device_op(device_pk, device_name,
  fn, ...)`, que adquiere el candado de `central/device_lock.py`, corre
  la operación en `_sync_executor` (un `ThreadPoolExecutor`) y aplica un
  tope duro de `HARD_SYNC_TIMEOUT_SECONDS = 150` con `.result(timeout=...)`.
  Nunca se conecta a un dispositivo directo desde el hilo de la
  petición ni sin este wrapper — un equipo colgado a nivel de socket ya
  causó bloqueos indefinidos antes de esto.
- **`central/device_lock.py`**: candado por dispositivo respaldado en la
  base de datos (tabla `device_locks`), no en memoria. Es necesario
  porque el proceso del panel web (persistente, vía waitress) y el
  proceso de sincronización programada (`python -m central.sync`,
  tarea de Windows aparte) son procesos de SO distintos — un
  `threading.Lock` en memoria solo protege dentro de un proceso y no
  evita que ambos choquen contra el mismo reloj a la vez (el reloj solo
  acepta una sesión viva). `STALE_AFTER_SECONDS = 180` libera candados
  huérfanos si un proceso murió sin soltar.
- **`attendance_system.py` / `pyzk`**: `ZK(...)` se crea con
  `ommit_ping=True`. Motivo: `ZK.connect()` hace primero un `ping` real
  de sistema operativo y aborta si no responde, aunque el puerto TCP
  4370 sí esté abierto — en redes con ICMP filtrado entre segmentos
  (común detrás de firewall) esto produce falsos "no se pudo conectar"
  con el equipo perfectamente accesible. `self.last_connect_error` guarda
  el motivo real en vez de descartarlo.
- **`create_or_update_user(...)`**: el parámetro `password` por defecto
  es `None`, no `''`. `ZK.set_user()` reescribe el registro *completo*
  del usuario en el reloj (no hay update parcial en el protocolo) — si
  se manda `password=''` por defecto, cualquier edición (hasta corregir
  solo el nombre) borraba en silencio el PIN local de esa persona. Si
  `password is None`, se reusa el PIN que ya tenía.
- **Permisos por módulo** (`central/auth.py`, tabla `role_modules`,
  pantalla `/permissions`): `MODULES` es la lista fija de secciones que
  un super_admin puede prender/apagar por rol (`viewer`, `admin`).
  `DEFAULT_MODULE_ACCESS` reproduce exactamente el comportamiento que
  existía *antes* de esta pantalla, así que instalar/actualizar nunca
  cambia el acceso de nadie hasta que alguien toque un checkbox.
  `module_required(module)` solo protege la ruta de **vista/entrada**
  de un módulo — las rutas de escritura (crear/editar/eliminar) siguen
  con su `admin_required`/`super_admin_required` de siempre, sin tocar.
  Esto acota el sistema a que **nunca** amplíe capacidad de escritura
  más allá del techo que ya tenía un rol; solo decide qué pantallas
  puede *abrir*. Cuentas, Backup, Auditoría y Permisos están fuera de
  esta lista a propósito — quedan fijas a `super_admin_required` porque
  tocan gestión de cuentas / export-import completo, terreno adyacente
  a escalamiento de privilegios.
  - Cada vez que una vista pase de `@admin_required` a
    `@module_required(...)`, hay que revisar su plantilla: si tenía
    botones de escritura sin guardar (porque antes solo entraba
    admin+), hay que envolverlos en `{% if can_manage %}` — ya pasó con
    `employees.html`, `employees_unmapped.html` y `device_users.html`.
  - Si un enlace hacia esa pantalla estaba anidado dentro de un bloque
    `{% if can_manage %}` en otra plantilla (p.ej. el link "Usuarios"
    en `devices.html`), hay que sacarlo a su propio
    `{% if can_manage or module_enabled('modulo') %}` o viewer nunca
    podrá llegar aunque tenga el módulo habilitado.
- **Soft-delete vs hard-delete**: los dispositivos se eliminan con
  soft-delete (se preservan marcaciones históricas vía FK). Las cuentas
  del panel web y los usuarios de un reloj sí se pueden eliminar duro —
  nada más queda referenciado por su id (el log de auditoría guarda el
  username como texto plano, no FK).
- **Patrón de hilos**: extraer valores planos (ip, puerto, nombre,
  comm_password, device_pk) de los objetos ORM en el hilo de la
  petición *antes* de mandarlos al executor — nunca compartir una
  `Session` de SQLAlchemy ni un objeto atado al contexto de Flask entre
  hilos.
- **Horarios / motor de asistencia** (`Schedule`, `EmployeeSchedule` en
  `central/models.py`, cálculo en `central/attendance_rules.py`):
  - `Schedule` (horario) NO usa un enum tipo L-V/L-S para días
    laborables — tiene 7 columnas booleanas (`work_mon`..`work_sun`)
    porque el usuario confirmó que el día de descanso varía libremente
    por área/tienda/especialidad, no sigue un patrón común. Tampoco hay
    una tolerancia de tardanza global: cada horario tiene su propio
    `tolerance_minutes`, a pedido explícito del usuario ("horarios que
    uno personalice, luego asignarlo como regla").
  - `EmployeeSchedule` es un historial con vigencia
    (`effective_from`/`effective_to`), no un campo fijo en `Employee` —
    un empleado puede cambiar de horario en el tiempo. Las asignaciones
    nunca se solapan: `employee_schedule_assign()` en `webapp.py` cierra
    la asignación abierta (`effective_to = None`) antes de crear la
    nueva, así que "qué horario tenía X en la fecha Y" siempre es una
    sola fila sin ambigüedad.
  - `attendance_rules.compute_attendance()` evalúa día por día: sin
    horario asignado → `sin_horario` (se reporta aparte, nunca se cuenta
    como falta ni como presente); día no laborable según el horario →
    `descanso`; laborable sin ninguna marcación → `falta`; con marcación
    → `a_tiempo`/`tardanza` contra `entry_time + tolerance_minutes`.
    Además calcula, independiente del status anterior: `overtime_minutes`
    (última marcación vs `exit_time`, solo si el horario ya tiene
    `exit_time` definido — ver siguiente punto) y `lunch_status`
    (`no_marcado`/`cumplido`/`excedido`, asumiendo que la 2ª y 3ª
    marcación del día son salida/vuelta de refrigerio cuando hay ≥4 ese
    día — misma heurística de orden que ya usaba `_group_by_day` en
    `webapp.py`, no el campo `status` de cada marcación). El exceso de
    refrigerio se compara contra la duración esperada + la MISMA
    `tolerance_minutes` del horario (reusada, no es un campo aparte).
  - `Schedule.exit_time` es `nullable=True` a nivel de base de datos
    aposta, aunque el formulario siempre lo exige — un horario creado
    ANTES de que este campo existiera (pasó de verdad en la sesión donde
    se agregó: "Pueblo Libre - Contabilidad" quedó con `exit_time=None`)
    se queda así hasta que alguien lo vuelva a guardar desde
    `/schedules`. El motor debe seguir tolerando `exit_time is None`
    (overtime = `None`, "no evaluado") en vez de asumir que siempre está
    poblado.
  - No se soportan horarios que cruzan la medianoche (turno nocturno):
    `schedule_new`/`schedule_edit` en `webapp.py` rechaza
    `exit_time <= entry_time`. Si el usuario pide un turno de este tipo
    en el futuro, el modelo actual (un solo `date` para todo el cálculo)
    no alcanza y hay que revisar el diseño.
  - `AttendanceException` (vacaciones/permiso/descanso médico,
    `/exceptions`): cubre cualquier día de un rango para un empleado.
    `compute_attendance()` solo la consulta en la rama donde ya iba a
    marcar `falta` (sin marcaciones, día laborable) — si hay una
    excepción vigente ese día, el status pasa a ser `justificado` en vez
    de `falta` y no cuenta en ningún reporte de ausentismo. No tiene flujo
    de aprobación: cualquiera con `admin_required` (mismo nivel que
    gestionar empleados) puede crear una.
  - `schedules_import` (Excel horario↔empleado) y
    `employee_schedule_assign` (formulario individual) comparten la misma
    función `_assign_schedule()` en `webapp.py` para cerrar/abrir
    asignaciones — si se cambia la regla de "no solapar", solo hay que
    tocarla ahí.
- **Menú lateral** (`central/templates/base.html`): reemplazó la barra
  superior horizontal. Íconos vienen de `central/icons.py` — un dict de
  SVG in-line hechos casi enteramente de primitivas (`circle`/`rect`/
  `line`/`polyline`/`polygon`/`ellipse`), a propósito, en vez de curvas
  `<path>` escritas a mano: un típo en un atributo `d` falla en silencio
  (ícono en blanco, sin error en ningún lado) y no hay forma automatizada
  de revisar visualmente docenas de curvas. El estado de colapsado/ancho
  se guarda en `localStorage` del navegador (por eso es por-persona, no
  compartido) y se re-aplica con un script en el `<head>` ANTES de que
  pinte el sidebar — cada página acá es una recarga completa del servidor
  (no hay ruteo del lado del cliente), así que sin ese script el menú
  parpadearía a ancho completo en cada clic. Al agregar una pantalla
  nueva al menú, hay que sumarla en tres lugares: la lista de navegación
  de `base.html`, y si tiene más de una ruta (crear/editar/importar), a
  la lista de endpoints de ese ítem para que "resaltado activo" funcione
  en todas sus páginas.
- **Rendimiento SQLite**: WAL activado (`central/db.py`,
  `_enable_sqlite_wal`) para que una sincronización en curso no bloquee
  la lectura del dashboard — waitress y `python -m central.sync` son
  procesos de SO distintos escribiendo el mismo archivo. El nombre de
  empleado en marcaciones se resuelve por lote (`_bulk_display_names` en
  `webapp.py`), nunca por fila — antes había una consulta a
  `employee_map` por cada marcación cruda, el cuello de botella real
  detrás de "el panel está lento" (no el motor SQLite en sí). Antes de
  proponer migrar a Postgres/MySQL (ya soportado hoy vía `DATABASE_URL`
  sin cambiar código), confirmar que el volumen real ya no lo aguanta
  aun con estos índices — no asumirlo solo porque "SQLite sí a veces se
  siente lento".
- **"NN-xxxxx"**: lo asigna el propio reloj ZKTeco a alguien enrolado sin
  nombre (huella/tarjeta sin usar el teclado del equipo) — confirmado
  seguido el dato hasta `attendance_system.py` (`u.name` viene tal cual
  de `self.conn.get_users()`, la librería `pyzk`), la app nunca lo
  genera. `_clean_fallback_name()` en `webapp.py` lo colapsa a
  "ID <id>" en Marcaciones/Faltas/Tardanzas/exportes (mismo fallback que
  un nombre vacío) — `employees_unmapped()` es la ÚNICA pantalla que
  debe seguir mostrando el "NN-xxxxx" crudo, a propósito. Si se agrega
  un nuevo lugar que muestre nombre de empleado con fallback, usar
  `_clean_fallback_name()`, no `r.user_name or f"ID {...}"` a mano.
- **Ficha de empleado enriquecida** (`Employee` en `models.py`):
  `nombre`/`apellido_paterno`/`apellido_materno` son columnas NUEVAS y
  ADITIVAS, nunca reemplazan `full_name` (que sigue siendo la columna
  real que todo el resto del código ya usaba: exportes, ordenar,
  buscar, propagar nombre al reloj). `_employee_profile_fields_from_form()`
  en `webapp.py` recalcula `full_name` a partir de los 3 campos
  estructurados SOLO cuando al menos uno viene lleno; si vienen vacíos,
  `full_name` se queda con lo que se haya escrito directo en ese campo
  -- así el alta rápida de un solo nombre (como ya la usaba
  `employee_map_create` al vincular "Sin vincular") sigue funcionando
  sin tocarla. `Employee.sede` es dato propio del empleado (a mano,
  con sugerencias vía `<datalist>` poblado desde `Device.sede`) --
  deliberadamente NO es lo mismo que la sede que usan los filtros de
  reportes (`Device.sede` vía `EmployeeMap`), que sigue sin tocar.
- **Import de empleados por Excel**: soporta DOS convenciones a la vez
  sin modo explícito -- una columna "nombre" sola (convención vieja,
  nombre completo en un solo campo) y "nombre" + "apellido paterno" +
  "apellido materno" (convención nueva). Funciona porque el cómputo
  siempre es `" ".join([nombre, paterno, materno] no vacíos)`: si solo
  hay "nombre", el resultado es ese valor sin cambios. Al actualizar un
  empleado existente por código, SOLO se sobreescribe un campo si la
  fila trajo un valor no vacío para esa columna -- una columna ausente
  del archivo (ej. reimportar solo para actualizar celular) nunca borra
  lo que ya había. Plantillas descargables (`/employees/import/
  template.xlsx`, `/schedules/import/template.xlsx`) construidas con
  `_template_workbook()` en `webapp.py` -- deliberadamente NO usa
  `_styled_workbook()` (esa es para reportes de solo lectura, no para
  una hoja pensada para editarse y resubirse).
- **Buscador de DNI en `employees_unmapped.html`**: es 100% del lado
  del cliente, sin ruta nueva en `webapp.py`. Pasó por dos versiones:
  la primera (búsqueda libre por "código - nombre") dejaba pegar
  cualquier texto/número sin límite -- el usuario lo probó de verdad y
  pegó una cadena de 15 dígitos que no calzaba con nada, sin ningún
  aviso de por qué. La versión actual es DNI-only: `<datalist>` solo
  con empleados que YA tienen código (`value="{{ e.code }}"`), objeto
  JS `EMPLOYEES_BY_DNI` (clave = código exacto), y
  `onEmployeeSearchInput()` primero sanea el valor
  (`replace(/\D/g,'').slice(0,8)` -- fuera cualquier caracter que no
  sea dígito, tope 8) y RECIÉN DESPUÉS busca coincidencia exacta. Un
  empleado sin DNI en el maestro simplemente no aparece en el
  `<datalist>` -- hay que ponerle código en Empleados antes de poder
  vincularlo desde acá. El botón "Vincular" arranca `disabled` en el
  HTML y sólo se habilita vía JS -- si algún día esta pantalla necesita
  funcionar sin JavaScript, hay que revisar ese `disabled` a mano.
  Verificado con Playwright contra un servidor de prueba aparte (puerto
  5050, base temporal, apagado al terminar) en ambas versiones,
  incluido reproducir EXACTAMENTE el string de 15 dígitos que el
  usuario pegó -- ahora se trunca a los primeros 8 y muestra "Ningún
  empleado tiene ese DNI en el maestro" en vez de quedarse ahí sin
  explicación.

## Estado actual / pendientes

- Rama `main`, árbol de trabajo limpio — la sesión del 2026-09-21/22
  (horarios, faltas, tardanzas/horas extra, vacaciones/permisos, panel
  de KPIs, menú lateral, limpieza de "NN-", ficha de empleado
  enriquecida + plantillas Excel, buscador de DNI en Sin vincular) está
  commiteada y pusheada a `origin/main`. Detalle línea por línea en
  `CHANGELOG.md`; decisiones de diseño de todo lo anterior en
  "Arquitectura y decisiones clave" arriba.
- **Datos de ejemplo en `central/attendance.db` de ESTA computadora
  (laboratorio local, nunca toca producción — `*.db` está en
  `.gitignore`)**: 6 empleados (Greyvis Silva Falcón, Rolando Romero
  Pasache, Fátima Velásquez López, Roberto Jacobo García, Raúl Ochante,
  Clotilde Munarriz Romero) creados combinando marcaciones reales ya
  sincronizadas del dispositivo PISO2 con horarios/vacaciones de
  ejemplo, para poder demostrar el sistema completo y armar el manual
  de RRHH. Si el usuario pregunta por qué ve estos nombres al probar en
  local, es esto — no son altas suyas ni existen en producción.
- **Manual de usuario para RRHH**, Artifact publicado:
  https://claude.ai/artifact/52rSs6ftJj4fMS1SV5sNz7 — cubre cada
  pantalla con capturas del laboratorio local, las columnas de los dos
  imports de Excel, y un aviso de que es laboratorio, no producción.
  Para actualizarlo: `Artifact(action:"read", url:"<esa URL>")` primero
  (las variables de publicación no persisten entre conversaciones).
- **Rendimiento**: se decidió NO migrar a Postgres/MySQL — la sospecha
  inicial del usuario (motor de base de datos) no coincidía con la
  causa raíz real (una consulta N+1 sin índice en la resolución de
  nombres). Ya corregido con WAL + índices + resolución por lote. Si
  después de esto vuelve a reportarse lento con el volumen real,
  recién ahí evaluar el motor — la ruta ya existe vía `DATABASE_URL`
  sin tocar código.
- **Sin confirmar por el usuario**: si el procedimiento de despliegue
  (ver abajo) ya se corrió en producción para los commits anteriores a
  esta sesión (bloque de Cuentas/Permisos, `80947ca`..`3a1ba6a`) — y,
  por separado, si el fix de `ommit_ping=True` + candado cross-proceso
  resolvió del todo la intermitencia real del equipo PISO2 en uso
  diario (se corrigió la causa raíz identificada, pero sin confirmación
  posterior). Preguntar o recordar el procedimiento si reporta que "no
  ve reflejado" algo nuevo.

## Procedimiento estándar de despliegue

Después de cualquier cambio en `central/`, el usuario actualiza el
servidor de producción así:

```powershell
cd C:\ruta-donde-clonaste\biometric-sincro-zkteco-webapp
git pull
.\deploy\windows_server\install.ps1
```

`install.ps1` detiene el proceso corriendo (incluso forzado si quedó
colgado) antes de volver a levantarlo — antes de que esto se corrigiera
(commit `5708a5c`), una actualización cambiaba los archivos en disco
pero el servicio seguía sirviendo el código viejo hasta un reinicio
manual aparte. Si el usuario reporta que "no ve reflejado" un cambio
después de `git pull`, sospechar primero de esto.

Los cambios de esquema (tablas/columnas nuevas) NO necesitan un paso
aparte de migración manual: `init_db()` en `central/db.py` corre
`create_all()` + una serie de funciones `_migrate_add_*` cada vez que
arranca el proceso (import time de `central/webapp.py`), así que
`install.ps1` ya deja la base de producción al día como parte normal
de reiniciar el servicio. Si algún día una migración deja de ser
"agregar columna nullable" (por ejemplo, un cambio que necesite
rellenar datos o tocar una columna existente), hay que avisarle al
usuario ANTES del despliegue en vez de confiar en que corra sola.

## Convenciones de esta sesión de trabajo

- Todo texto de cara al usuario (mensajes de commit incluidos si son
  visibles, UI, este archivo) va en español.
- Antes de dar por buena una función nueva: probarla localmente
  (levantar el server de dev, crear cuentas de prueba con cada rol,
  verificar comportamiento por defecto idéntico al anterior, luego
  probar el cambio, luego revertir/limpiar cuentas de prueba) en vez de
  asumir que el código es correcto solo por compilar.
- `CHANGELOG.md` se actualiza en la misma sesión que el cambio, con
  bullets en español al estilo ya establecido (ver secciones
  "Agregado" / "Corregido" del `[Unreleased]`).
- **Verificación real en navegador para cualquier cosa con JS o CSS
  interactivo** (menú lateral colapsable/redimensionable, el buscador
  de DNI en Sin vincular): un test con el cliente de pruebas de Flask
  solo confirma que el HTML se renderiza, NUNCA que el JavaScript hace
  lo que dice el comentario — los dos bugs reales que se encontraron
  esta sesión (el "resizer" del menú inatrapable por un
  `overflow:hidden`, y el campo de DNI que aceptaba pegar cualquier
  cantidad de dígitos) solo aparecieron al probarlo con un navegador de
  verdad, no en las pruebas de Python. Este entorno no trae un
  navegador headless instalado por defecto: `pip install playwright`
  + `playwright install chromium` (una sola vez descarga el binario,
  se cachea en `~/AppData/Local/ms-playwright` y las siguientes
  instalaciones del paquete son rápidas) — y **desinstalar Playwright
  al terminar** (`pip uninstall playwright pyee greenlet`), nunca
  dejarlo en `requirements.txt` ni en el venv del proyecto: no es una
  dependencia de la app, es una herramienta de verificación de esta
  sesión. Para no interferir con el servidor de desarrollo que el
  usuario pueda tener abierto, levantar un segundo proceso Flask
  aparte en otro puerto (ver el patrón `seed_and_run_test_server.py`
  usado esta sesión: base de datos temporal, datos de prueba propios,
  puerto distinto) en vez de probar contra `central/attendance.db` real.
- **El manual de RRHH y cualquier documento para gente que no es el
  usuario** se arma con la herramienta Artifact (página HTML publicada,
  ver enlace en "Estado actual / pendientes"), no como archivo suelto
  en el repo — así el usuario tiene un link para compartir directo con
  RRHH sin pasar por git.
