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
  detrás de "el panel está lento" (no el motor SQLite en sí). Esto sigue
  siendo relevante para el Windows de producción actual (todavía SQLite),
  pero YA NO es el criterio para decidir si migrar a Postgres — eso se
  decidió aparte el 2026-10-15 (multiplataforma + Docker + integración
  con la app de planillas), independiente de cómo esté el rendimiento.
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
- **API de integración** (`central/api.py`, Blueprint Flask montado en
  `app` desde `webapp.py`): auth por `ApiToken` (hash SHA-256 del
  token, NO el hash salteado/lento de las contraseñas -- el propio
  token ya tiene 256 bits de entropía, lo que importa acá es poder
  buscarlo con una consulta indexada en vez de comparar contra cada
  token vivo uno por uno), nunca sesión de navegador. `guard()` (el
  `@app.before_request` que protege TODO lo demás) tiene que exceptuar
  `request.blueprint == "api"` explícitamente, o cualquier llamada sin
  cookie de sesión redirigiría a `/login` en vez de devolver JSON 401 --
  si se agrega otro blueprint en el futuro que tampoco deba pasar por
  la sesión, va en esa misma excepción. Las rutas de escritura
  REUTILIZAN (import diferido DENTRO de cada función, nunca al tope del
  archivo -- `webapp.py` importa este módulo para registrar el
  blueprint, así que un import al tope sería circular)
  `_employee_profile_fields_from_form()` / `_schedule_fields_from_form()`
  / `_assign_schedule()` de `webapp.py`, pasando el JSON de la petición
  por `_as_api_form()` (convierte a lo que esas funciones ya esperan:
  `dict.get(key, default)` con strings, igual que `request.form`) --
  así una regla fijada ahí (ej. "no borrar un campo que la fila no
  trajo") aplica también acá, nunca una segunda copia que alguien se
  olvide de actualizar junto con la primera.
- **Puente de administración remota** (`Device.agent_name`,
  `DeviceCommand`, `central/remote_agent.py`): reutiliza la idea de
  `device_lock.py` (coordinación cruzada de procesos por la base de
  datos compartida, no un protocolo de red nuevo) para un problema
  distinto -- encolar un comando en vez de un candado.
  `run_device_op(device_pk, device_name, fn, action=None, params=None)`
  en `webapp.py` revisa `Device.agent_name`: si está vacío, exactamente
  el camino de siempre (`fn` corre en este proceso, cero cambio de
  comportamiento); si no, IGNORA `fn` por completo (una clausura de
  Python con una conexión pyzk viva no puede cruzar a otro proceso) y
  en su lugar encola una fila en `device_commands` con `action` +
  `params`, sondeando hasta que el agente remoto la marque `done`/
  `error`, con el mismo tope `HARD_SYNC_TIMEOUT_SECONDS`. Un caller que
  todavía no pasa `action=` para un dispositivo remoto falla AL
  INSTANTE con un mensaje claro -- a propósito, para no quedarse
  colgado 150s en un intento de conexión directa que nunca iba a
  funcionar. `central/remote_agent.py#_run_action()` tiene que
  mantenerse sincronizado a mano con cada `action=` nuevo que se agregue
  en `webapp.py` -- no hay nada que lo obligue automáticamente, son dos
  archivos separados a propósito (uno corre en la central, el otro en
  la sede remota). El mismo archivo también sincroniza marcaciones
  reutilizando `central.sync.sync_all(only_agent=AGENT_NAME)` sin
  cambios -- `sync_all()` ahora filtra `Device.agent_name IS NULL`
  (local, el comportamiento de toda la vida) vs. `== only_agent`, así
  que la central nunca intenta (ni falla contra) un dispositivo que un
  agente remoto ya es dueño.
- **Instalador y scripts de gestión de Docker** (`deploy/docker/
  install.ps1`/`install.sh`, `manage.ps1`/`manage.sh`,
  `docker-compose.agent.yml`): un instalador interactivo que SIEMPRE
  pregunta (nunca asume valores por defecto en silencio, a pedido
  explícito del usuario) si la máquina es servidor central o agente
  remoto, y arma el `.env` correspondiente (`$RepoRoot\.env` para
  central, `deploy\docker\.env` para agente -- Docker Compose busca el
  `.env` junto al primer `-f` que se le pase, así que el archivo tiene
  que vivir en esa carpeta exacta, no en cualquier lado). El modo
  elegido queda en `deploy/docker/.deploy_mode` (texto plano
  "central"/"agent"), que `manage.ps1`/`manage.sh` leen para saber qué
  `docker-compose*.yml` usar sin volver a preguntar. Dos bugs reales
  encontrados AL PROBARLO (no se habrían visto leyendo el código):
  - **PowerShell se traga flags cortas de una sola letra pasadas sueltas
    a una función propia** si calzan por prefijo único con un parámetro
    común (`-Debug`, `-Verbose`, etc.): `Invoke-Compose up -d` hacía que
    "-d" se interpretara como `-Debug` DE LA FUNCIÓN, nunca llegaba a
    `docker`, así que corría `docker compose up` sin el `-d` real y se
    quedaba pegado en primer plano mostrando logs para siempre en vez de
    desprenderse. Pasa solo al invocar una función/cmdlet de PowerShell,
    nunca al llamar un ejecutable nativo directo (`docker ...` a secas
    no tiene este problema). Arreglado pasando los argumentos como UN
    array por un parámetro con nombre (`Invoke-Compose -ComposeArgs
    @("up", "-d")`) en vez de sueltos -- cualquier wrapper de PowerShell
    nuevo sobre un comando con flags de una letra en este repo debe
    seguir ese patrón.
  - **`if [ -f "$archivo" ]; then ...; fi` en bash, sin `else`, sale con
    código 0 (éxito) aunque la condición sea falsa** -- no hereda el
    código de salida del `test`. Un `$(func ... || echo default)` que
    depende de que `func` "falle" cuando el archivo no existe NUNCA se
    activa: `install.sh` dejaba `POSTGRES_USER`/`POSTGRES_DB`/
    `SYNC_DAILY_AT` vacíos en el primer `.env` (no se notaba porque
    `docker-compose.yml` ya trae sus propios valores por defecto vía
    `${VAR:-asistencia}`). Arreglado haciendo que la función siempre
    imprima algo (vacío si no hay nada) y aplicando el default en el
    llamador con `"${valor:-default}"`, nunca confiando en el código de
    salida de una función que envuelve un `if` sin `else`.
  - Ambos `install.ps1`/`manage.ps1` llevan BOM UTF-8 al guardarlos (a
    propósito, con `[System.IO.File]::WriteAllBytes` -- el `Write`/`Edit`
    normal no lo agrega): sin BOM, PowerShell 5.1 (el que trae Windows
    Server, no una versión más nueva) adivina mal la codificación de un
    `.ps1` con tildes/ñ y corrompe caracteres acentuados al punto de
    romper el parseo del script entero (visto en esta sesión: un "Ó"
    convertido en un caracter que cerraba un string PowerShell antes de
    tiempo). Cualquier `.ps1` nuevo en este repo con texto en español
    necesita este mismo paso después de escribirlo.
  - Los `.bat` de `deploy/docker/` (a diferencia de los de
    `deploy\windows_server\`) NO se auto-elevan a Administrador --
    Docker Desktop corre con la sesión del usuario interactivo, y una
    consola elevada aparte puede terminar hablando con un Docker Desktop
    distinto o con ninguno.
  - Probado de punta a punta en esta sesión, instalación real con
    contenedores (modo central: build, espera de Postgres, creación de
    super admin, panel respondiendo 200; modo agente: build, contenedor
    arriba, falla limpia y clara al no encontrar un Postgres central de
    verdad en esta prueba) y los 5 comandos de gestión
    (start/stop/restart/status/diagnose) en PowerShell y en bash,
    limpiando los contenedores/volúmenes de prueba al terminar.
  - **Bug real encontrado el 2026-10-19, probando contra el servidor
    central real por primera vez**: el servicio `db` de
    `docker-compose.yml` nunca publicaba el puerto 5432 hacia afuera del
    host -- solo era visible ENTRE los contenedores del mismo
    `docker compose` (`web`/`sync` le hablan a `db` por el nombre del
    servicio en la red interna de Docker, nunca por el puerto publicado),
    así que un agente remoto en otra sede, por más que la VPN
    funcionara perfecto, nunca iba a poder llegar -- `Test-NetConnection`
    mostraba `PingSucceeded: True` / `TcpTestSucceeded: False`, la firma
    típica de "la ruta de red está bien, no hay nada escuchando ahí".
    Corregido agregando `ports: - "${POSTGRES_PORT:-5432}:5432"` al
    servicio `db`. `install.ps1`/`install.sh` ahora preguntan también el
    puerto (`POSTGRES_PORT`, 5432 por defecto) y, en modo central,
    intentan abrir ese puerto en el Firewall de Windows con
    `New-NetFirewallRule` SI la consola está elevada (si no, imprimen el
    comando exacto para correrlo a mano) -- la rama elevada no se pudo
    probar en esta sesión (sin forma de conseguir una consola UAC
    elevada en este entorno), solo la rama sin elevar; `install.sh`
    (Linux) solo imprime la guía (`ufw`/`firewalld`), no la automatiza,
    porque varía demasiado entre distros para hacerlo con confianza.
    **Esto NO es un problema de VPN ni del `ommit_ping=True`** -- antes
    de este fix, NINGÚN agente remoto iba a poder conectarse nunca,
    sin importar qué tan bien estuviera la VPN.
  - **Requisito de orden que no estaba explícito antes**: un agente
    remoto necesita que el servidor CENTRAL ya esté corriendo con este
    `docker-compose.yml` (PostgreSQL de verdad, escuchando en red) --
    si la central sigue con la instalación nativa de Windows (SQLite,
    sin ningún servicio de base de datos en red), cualquier intento de
    conexión desde una sede remota va a fallar de la misma manera
    (`TcpTestSucceeded: False`) aunque la VPN esté perfecta, porque
    simplemente no hay nada escuchando en el puerto 5432 todavía. Antes
    de configurar una PC remota, confirmar que la central ya migró.
- **Migración de datos SQLite -> PostgreSQL**
  (`central/migrate_sqlite_to_postgres.py`,
  `deploy/docker/migrar_servidor_central.ps1`): resuelve el pendiente
  que quedaba de "Docker arranca con una base vacía" -- copia cada tabla
  en el orden de `Base.metadata.sorted_tables` (ya viene ordenado por
  dependencia de llaves foráneas, no hay que mantener el orden a mano),
  conservando los IDs originales (no re-numera nada, así que
  `AttendanceLog.device_pk`, `EmployeeMap.employee_id`, etc. siguen
  apuntando a lo mismo) y reajustando la secuencia de Postgres de cada
  tabla con `pg_get_serial_sequence()` + `setval()` después de insertar
  -- sin esto, el primer `INSERT` real de la app después de migrar
  intentaría reusar un ID que el script ya usó a mano y fallaría por
  llave duplicada. Tolera que el SQLite de origen sea de una versión
  anterior del esquema (le falte alguna tabla o columna agregada
  después, ej. `api_tokens` o `devices.agent_name`): lo detecta con
  `inspect()` sobre el origen y lo trata como "nada que migrar ahí
  todavía" en vez de romperse -- las columnas agregadas después son
  siempre nullable/con default por el mismo principio que ya sigue
  `central/db.py` para sus propias migraciones, así que quedan en su
  valor por defecto sin problema. Se niega a correr sobre un destino que
  ya tenga filas salvo `--force` (protección contra correrlo dos veces
  y duplicar todo). NUNCA escribe en el SQLite de origen, solo lee.
  `migrar_servidor_central.ps1` es el orquestador real: pide
  confirmación explícita, detiene las tareas programadas nativas,
  respalda el SQLite con fecha ANTES de tocar nada, levanta SOLO el
  contenedor `db` (vacío), corre la migración usando el Python del venv
  nativo existente (`C:\Asistencia\venv\Scripts\python.exe`, que ya
  tiene `psycopg2-binary` porque está en `central/requirements.txt`
  desde que se agregó soporte a Postgres), y SOLO si la migración
  termina sin errores levanta `web`/`sync` -- si falla, dice
  explícitamente cómo reactivar las tareas nativas en vez de dejar al
  usuario con el panel nuevo a medio armar y el viejo apagado. A
  propósito, este script NO crea una cuenta de administrador nueva (a
  diferencia de `install.ps1` en modo central) -- los admins reales ya
  vienen en la tabla `users` migrada, crear uno nuevo ahí sería
  redundante y confuso.
  - Probado de punta a punta en esta sesión contra la base de datos
    local real de este dev (6 empleados, 39,685 marcaciones, 2 cuentas
    de usuario, 4 horarios, excepciones de asistencia): las 14 tablas
    migraron con conteos exactos origen=destino, un `INSERT` de prueba
    después de migrar tomó el siguiente ID sin chocar (confirma que el
    `setval()` quedó bien), y `central.webapp:app` arrancó normal
    (`GET /login` -> 200) contra la base ya migrada.
  - El script `migrar_servidor_central.ps1` en sí (el orquestador
    completo, con detención de tareas programadas reales) no se pudo
    probar 100% tal cual se invoca, porque este entorno no puede
    conseguir una consola de Windows elevada (UAC) -- se probó
    copiándolo fuera de `deploy/docker/` con el chequeo de elevación y
    los `Stop-ScheduledTask` reemplazados por no-ops (sin tareas
    programadas reales en esta PC de desarrollo), contra una carpeta que
    simula la instalación nativa. Todo lo demás (respaldo, preguntas,
    `docker compose up -d --build db` solo, invocación de la migración,
    `docker compose up -d --build` completo, intento de regla de
    Firewall) corrió real y se verificó. **Falta probarlo tal cual,
    como Administrador, contra una instalación nativa real** antes de
    correrlo en producción -- recomendar al usuario un ensayo en una
    copia/servidor de prueba antes del corte real, no ir directo a
    producción con esto.
- **Agente remoto SIN Docker** (`deploy/windows_server/
  install_agente_remoto.ps1`, `agente_remoto_servicio.ps1`,
  `.bat` `AsistenciaAgenteRemoto_*`): Docker Desktop en Windows necesita
  virtualización habilitada en BIOS (Hyper-V/WSL2) -- en una PC de sede
  remota donde eso no está disponible (hardware viejo, política de IT,
  BIOS bloqueada), Docker Desktop directamente no arranca. `central/
  remote_agent.py` NO tiene ninguna dependencia de Docker -- es un
  script de Python puro que solo necesita `AGENT_NAME` y `DATABASE_URL`
  como variables de entorno, así que corre perfecto como una Tarea
  Programada más, exactamente con el mismo patrón que ya usa
  `deploy\windows_server\install.ps1` para `AsistenciaWeb`/
  `AsistenciaSync` (venv + `Register-ScheduledTask -User SYSTEM`).
  `install_agente_remoto.ps1` es la versión "solo agente" de ese mismo
  patrón: pide SIEMPRE el nombre del agente y los datos de conexión a la
  base central (nunca valores por defecto en silencio, mismo principio
  que el resto de los instaladores de esta sesión), arma el
  `DATABASE_URL`, lo guarda como variable de entorno a nivel de máquina
  (igual que `install.ps1` ya hace con `SECRET_KEY`/`DATABASE_URL`), y
  registra la tarea `AsistenciaAgenteRemoto`. Instala en
  `C:\AsistenciaAgente` por defecto -- deliberadamente distinto de
  `C:\Asistencia` (el panel central) para que nunca choquen si alguna
  vez conviven en la misma máquina. `agente_remoto_servicio.ps1` agrega
  un `Diagnose` que no existía en `service.ps1`: extrae host/puerto del
  `DATABASE_URL` guardado (con regex, enmascarando la contraseña al
  mostrarlo) y corre `Test-NetConnection` contra la central -- mismo
  diagnóstico `PingSucceeded`/`TcpTestSucceeded` que ya se usó para
  encontrar el bug del puerto 5432 no publicado, pero empaquetado para
  que el usuario no tenga que escribirlo a mano cada vez.
  - Probado en esta sesión: el instalador completo (sin elevar, hasta el
    punto donde pide Administrador) contra una carpeta de prueba --
    copia la app, arma el venv, instala dependencias, escribe el
    resumen con credenciales, y confirma que `central.remote_agent`
    importa limpio en ese venv (prueba real de que psycopg2-binary y el
    resto de `requirements.txt` quedaron bien instalados). También
    `agente_remoto_servicio.ps1 -Action Status/Diagnose` (sin tarea
    registrada aún, sin elevar) y el bloqueo correcto de `-Action Start`
    sin permisos de administrador. La lógica de enmascarado y extracción
    de host/puerto del `DATABASE_URL` se probó aparte con un valor de
    ejemplo. **Lo que NO se pudo probar en este entorno** (sin forma de
    conseguir una consola elevada): el registro real de la Tarea
    Programada y el ciclo completo Start/Stop/Restart sobre una tarea
    real -- mismo tipo de limitación ya documentada para
    `migrar_servidor_central.ps1`.
  - **Bug real #5, encontrado por el usuario desplegando el agente de
    verdad en la sede remota** (2026-10-21, VPN y PostgreSQL ya
    confirmados accesibles con `Test-NetConnection` --
    `TcpTestSucceeded: True`): el chequeo original (`Assert-CommandExists
    "python" ...`, con `Get-Command python -ErrorAction SilentlyContinue`)
    pasaba igual contra el "alias de ejecución de aplicaciones" que
    Windows pone en PATH por defecto
    (`%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe`) -- ese archivo
    EXISTE de verdad (por eso `Get-Command` lo encuentra), pero al
    ejecutarlo solo abre la Microsoft Store y sale, sin hacer nada. El
    script pasó el chequeo, `python -m venv venv` no creó nada, y como
    nada de lo que seguía revisaba códigos de salida, el instalador
    siguió hasta el final: configuró las variables de entorno, registró
    la Tarea Programada apuntando a un `venv\Scripts\python.exe`
    inexistente, la "inició", y mostró `=== Listo ===` -- un falso
    éxito completo, el agente nunca llegó a correr. Corregido con
    `Assert-RealPython` (nueva función, reemplaza `Assert-CommandExists`
    para python específicamente, en ESTE script Y en
    `deploy\windows_server\install.ps1` -- mismo patrón original, misma
    vulnerabilidad, corregido ahí también aunque no fue lo que bloqueó
    al usuario esta vez): corre `python --version` de verdad y exige que
    la salida empiece con `Python ` seguido de un número, no solo que el
    comando "exista". Segunda capa de protección agregada en ambos
    scripts: verificación explícita de `Test-Path
    ...\venv\Scripts\python.exe` ANTES de registrar la Tarea
    Programada -- si por cualquier motivo el venv no quedó usable (no
    solo Python roto -- antivirus, disco lleno, etc.), el script para
    con un mensaje claro en vez de declarar éxito falso otra vez.
    Verificado con un script de prueba que imita el comportamiento
    exacto del alias falso (mismo mensaje de Microsoft Store, mismo
    código de salida) -- confirmó que la detección nueva lo atrapa, y
    que una instalación de Python real (la de esta PC de dev) sigue
    pasando sin problema. **El usuario todavía tiene que**: instalar
    Python 3.10+ real en esa PC remota (python.org, marcando "Add
    python.exe to PATH"; si sigue sin andar después de instalarlo,
    puede que el alias de WindowsApps siga adelante en PATH --
    desactivarlo en Configuración > Aplicaciones > Alias de ejecución de
    aplicaciones) y volver a correr `install_agente_remoto.ps1` -- no
    hace falta limpiar la Tarea Programada rota a mano, `Register-
    ScheduledTask -Force` la reemplaza sola.
- **Migración a PostgreSQL SIN Docker en la central**
  (`deploy/windows_server/migrar_a_postgresql.ps1`): resultó que el
  servidor central TAMPOCO puede correr Docker -- es una VM de Hyper-V
  sin virtualización anidada habilitada (confirmado por el usuario), el
  mismo problema que la sede remota pero un nivel más arriba. Esta
  versión reemplaza el contenedor `db` de `migrar_servidor_central.ps1`
  por PostgreSQL para Windows instalado nativamente (sin virtualización,
  sin BIOS, un instalador normal de Windows) y reutiliza
  `deploy\windows_server\install.ps1` (CON `-DatabaseUrl`, un parámetro
  que YA existía antes de esta sesión, sin tocarlo) en vez de `docker
  compose up -d --build` para dejar el panel corriendo -- el panel
  nativo sigue siendo Tareas Programadas de toda la vida, cero cambio de
  mecanismo, solo cambia qué base de datos hay detrás.
  `migrate_sqlite_to_postgres.py` (el motor de migración en sí) no
  necesitó NINGÚN cambio -- es agnóstico de cómo esté hospedado el
  Postgres destino (Docker o nativo), solo le importa el `DATABASE_URL`.
  - **Bug real encontrado probando contra un PostgreSQL de verdad** (no
    Docker, que corre en inglés/C por defecto): el mensaje de error de
    PostgreSQL para "el rol ya existe" viene LOCALIZADO según el idioma
    de Windows -- en este Windows en español, psql devuelve "el rol
    «asistencia» ya existe", nunca la cadena en inglés "already exists"
    que la primera versión del script buscaba con `-match`. Esto nunca
    se habría visto contra el Postgres de Docker (que corre en
    inglés/C por defecto) -- otra confirmación de que `docker compose`
    no es un sustituto de probar contra el motor/SO real de destino.
    Arreglado reemplazando "crear y adivinar el error" por "consultar
    `pg_roles`/`pg_database` ANTES de crear" (`Test-PgRoleExists`/
    `Test-PgDatabaseExists`) -- nunca parsear el texto de un error de
    una herramienta que puede estar localizada, hay que consultar el
    estado real o usar el código SQLSTATE, no el mensaje.
  - Probado de punta a punta en esta sesión instalando PostgreSQL 17
    real vía `winget` (silencioso, puerto 5555 de prueba, se desinstaló
    al terminar): descubrimiento de `psql.exe`, creación de usuario y
    base reales, migración completa (14 tablas, incluida la corrida
    contra la base local real que para este punto ya tenía 41,405
    marcaciones -- sigue creciendo porque algo la sincroniza en segundo
    plano en esta PC de dev), reinstalación del panel vía `install.ps1
    -DatabaseUrl` (degradó con gracia por falta de elevación, mismo
    comportamiento esperado que sin este cambio), e idempotencia
    confirmada aparte contra el Postgres real ya con los datos puestos
    (`Test-PgRoleExists`/`Test-PgDatabaseExists` devolvieron `True` la
    segunda vez, `False` para un rol que no existía). **Lo que NO se
    pudo probar** (misma limitación de siempre, sin consola elevada de
    verdad en este entorno): el registro real de las Tareas Programadas
    dentro de la llamada a `install.ps1`.
  - **Bug real #2, encontrado por el usuario corriéndolo de verdad
    contra su servidor** (2026-10-20, después de los puntos anteriores):
    el script NO actualizaba `$InstallDir` (`C:\Asistencia`) con el
    código del repo antes de migrar -- si esa carpeta tenía código de
    antes de que existiera `central/migrate_sqlite_to_postgres.py` (el
    caso normal: alguien clona el repo, hace `git pull`, pero
    `C:\Asistencia` solo se actualiza cuando corre `install.ps1`, nunca
    automáticamente), `python -m central.migrate_sqlite_to_postgres`
    fallaba con `No module named central.migrate_sqlite_to_postgres`
    ANTES de tocar ningún dato -- el script detectó el fallo y dejó todo
    intacto (panel detenido, respaldo a salvo, mensaje claro de cómo
    volver), tal como está diseñado para una migración fallida. No se
    perdió nada, pero sí había que corregir la causa. Arreglado
    agregando el mismo `robocopy ... /MIR /XD venv ... /XF *.db
    devices.json` que ya usa `install.ps1`, ahora ANTES del intento de
    migración (no solo al final), más un `pip install -r
    requirements.txt` también antes de migrar por si la lista de
    dependencias cambió. Verificado reproduciendo el error exacto
    (carpeta de prueba con un `central/` viejo, sin el script de
    migración) y confirmando que el `robocopy` lo trae y que el módulo
    importa después -- sin volver a instalar PostgreSQL para esto, ya
    que es un problema de archivos, no de conexión a la base.
  - **Bug real #3, mismo usuario, mismo servidor, siguiente intento**:
    había vuelto a correr el script contra un PostgreSQL que YA tenía el
    usuario/base de la vez anterior. El script detectaba bien que el
    usuario ya existía ("se deja igual") pero NO actualizaba su
    contraseña en PostgreSQL -- mientras tanto, como el usuario dejó el
    campo de contraseña vacío (Enter) otra vez, `New-RandomSecret`
    generó una contraseña NUEVA y DISTINTA, que el script igual usó para
    armar el `DATABASE_URL`. Nunca iban a coincidir. El síntoma no fue
    un claro "contraseña incorrecta": psycopg2 reventó con
    `UnicodeDecodeError: 'utf-8' codec can't decode byte 0xf3...` --
    PostgreSQL le mandó el mensaje de autenticación fallida en español
    (con una "ó", byte `0xF3` en Windows-1252/Latin-1) y psycopg2 asumió
    UTF-8 al decodificarlo, mismo tipo de problema de idioma/codificación
    que el bug de `ALTER`/`CREATE` ya documentado arriba, pero esta vez
    del lado de libpq, no de un `-match` de PowerShell. Arreglado:
    cuando el usuario YA existe, el script ahora corre `ALTER USER ...
    WITH PASSWORD` con la contraseña que se acaba de ingresar/generar en
    ESTA corrida, en vez de dejarla sin tocar -- así `$PgPassword`
    (lo que arma el `DATABASE_URL`) SIEMPRE coincide con lo que de
    verdad quedó en PostgreSQL, sea la primera vez o la enésima. De
    paso se endureció el `pip install` (ruta absoluta al
    `requirements.txt` en vez de una relativa al directorio de trabajo
    del proceso -- esa parte SÍ fallaba en la sesión elevada real del
    usuario con "No such file or directory", aunque no en las pruebas
    de esta sesión con una consola no elevada; más seguro no depender
    de la propagación del cwd a un proceso hijo en absoluto) y se agregó
    verificación de `$LASTEXITCODE` ahí, que antes fallaba en silencio y
    seguía adelante. Verificado reproduciendo el escenario EXACTO:
    PostgreSQL 17 real, primera corrida crea el usuario con una
    contraseña, segunda corrida con una contraseña DISTINTA -- confirmó
    el mensaje de "actualizando su contraseña", conexión real exitosa
    (llegó hasta `Creando el esquema en el destino`, sin el
    `UnicodeDecodeError`), y recién ahí el bloqueo esperado y correcto
    de "el destino ya tiene datos" (por no pasar `--force`, ya que el
    destino tenía los datos de la corrida anterior) -- la señal de que
    la conexión en sí quedó perfecta, el único motivo de parada fue la
    protección contra duplicar datos, que es el comportamiento correcto.
  - **Bug real #4, mismo usuario, tercer intento**: con los dos bugs
    anteriores ya corregidos, el `pip install` volvió a fallar con "No
    such file or directory" -- esta vez con la ruta ABSOLUTA ya
    corregida del bug anterior (`C:\Asistencia\central\requirements.txt`),
    así que el problema nunca fue la ruta relativa. La pista real: el
    usuario tiene el repo clonado dentro de `C:\WINDOWS\System32\
    biometric-sincro-zkteco-webapp` -- una ubicación con permisos y
    protecciones especiales de Windows (posible interferencia de
    antivirus/Windows Defender con una copia masiva ahí, o algo más
    específico del propio System32) que lo más probable es que haya
    hecho fallar el `robocopy` para ese archivo puntual EN SILENCIO --
    el script nunca revisaba el código de salida de `robocopy` (sus
    códigos son por bits: 0-7 éxito, 8+ error real, no el patrón
    0/distinto-de-0 de la mayoría de los programas), así que seguía
    adelante como si la copia hubiera salido bien. Corregido agregando
    el chequeo de `$LASTEXITCODE -ge 8` de `robocopy` MÁS un `Test-Path`
    explícito sobre `requirements.txt` después de copiar -- si falla
    cualquiera de los dos, el mensaje de error ahora sugiere
    explícitamente mover el repo fuera de una carpeta protegida de
    Windows como `C:\WINDOWS\System32`. Verificado que el código de
    salida de un `robocopy` exitoso normal es 3 (dentro del rango
    0-7), así que el chequeo nuevo no rompe el caso normal -- no se
    pudo reproducir la falla real DENTRO de System32 en esta sesión
    (clonar algo ahí a propósito solo para probarlo es más riesgo del
    que vale la pena para este diagnóstico). **Recomendación pendiente
    de que el usuario confirme**: mover el repo fuera de
    `C:\WINDOWS\System32` a una carpeta normal (ej. `C:\Proyectos\...`)
    -- probablemente resuelve esto de raíz, más allá del parche
    defensivo.

## Estado actual / pendientes

- Rama `main`. Todo hasta `e13f332` (2026-09-22: horarios, faltas,
  tardanzas/horas extra, vacaciones/permisos, panel de KPIs, menú
  lateral, limpieza de "NN-", ficha de empleado enriquecida + plantillas
  Excel, buscador de DNI en Sin vincular) está commiteado y pusheado a
  `origin/main`. Detalle línea por línea en `CHANGELOG.md`; decisiones
  de diseño en "Arquitectura y decisiones clave" arriba.
- **2026-09-23**: el PISO2 "se caía" intermitentemente -- causa raíz real
  (no la que se sospechaba en la sesión del `ommit_ping=True`): el equipo
  **cambia de IP sola** (DHCP sin reserva), de `172.16.1.241` a `.140` y
  luego a `.25` en el mismo día. No es un bug de la app ni de red/ping --
  cada vez que "deja de responder", lo primero es escanear el puerto 4370
  en la subred (`central/attendance.db` guarda el último
  `last_sync_status` y `audit_log` el historial de intentos) en vez de
  asumir que la IP guardada en `Dispositivos` sigue siendo la correcta.
  Pendiente de pedirle a redes una IP fija o reserva DHCP para que no se
  repita.
- **2026-10-15: Docker** (`Dockerfile`, `docker-compose.yml`,
  `central/sync_loop.py`, `deploy/docker/README.md`) -- tres servicios
  (`db` Postgres 16, `web` gunicorn, `sync` reemplaza al timer de
  systemd / tarea de Windows, que no existen dentro de un contenedor).
  Pensado como el despliegue nuevo "de verdad multiplataforma" (decisión
  del usuario: reemplaza a los instaladores nativos a futuro, no convive
  indefinidamente con ellos). **Probado de punta a punta en esta misma
  sesión** con Docker Desktop (Windows) contra un Postgres real: build,
  arranque de los 3 contenedores, `init_db()` crea las 12 tablas solo,
  login + todas las pantallas clave responden 200, y -- la parte que
  genuinamente no se podía asumir sin probarla -- el contenedor `web`
  SÍ alcanza un reloj físico real de la LAN (PISO2, `172.16.1.25:4370`)
  con la red *bridge* por defecto, sin ningún ajuste. Confirma además
  que todo el esquema construido en sesiones anteriores (Schedule,
  EmployeeSchedule, AttendanceException, campos nuevos de Employee) es
  100% compatible con Postgres tal cual está, sin cambios de código.
  **Todavía NO commiteado** (archivos nuevos, sin pedir commit todavía).
- **2026-10-15: API + puente remoto** (misma sesión que Docker, después):
  `/api/v1/...` (`central/api.py`, token en vez de sesión de navegador,
  gestión de tokens en `/api-tokens`) con lectura de empleados/horarios/
  marcaciones/faltas/tardanzas y escritura de empleados/horarios, para
  la app de planillas/tareo externa. Y el puente de administración
  remota (`central/remote_agent.py`, `Device.agent_name`,
  `DeviceCommand`) para sedes cuyo biométrico este servidor no alcanza
  directo pero cuyo propio servidor sí llega a Postgres por VPN --
  **solo "Probar conexión" quedó retrofitteada en `run_device_op()`**;
  Reiniciar/Apagar/Vaciar/gestión de Usuarios del dispositivo siguen
  sin soportar el puente (fallan rápido con mensaje claro en vez de
  intentar conectar directo, no se quedan colgadas). Ambos probados de
  punta a punta: la API completa con el cliente de pruebas de Flask +
  contra Postgres real en Docker; el puente remoto simulando dos
  procesos (uno "central", uno "agente") contra el PISO2 real, incluido
  el caso de una acción no retrofitteada fallando al instante. Todo
  **sin commitear** al cierre de esta conversación si no se pidió.
  - Bug real encontrado y corregido ANTES de la primera prueba (nunca
    llegó a ejecutarse así): al insertar `ApiToken` en `models.py`
    justo después de `TrustedDevice`, el `old_string` del primer
    `Edit` cortó antes de la línea `user = relationship(...)` de
    `TrustedDevice` sin notarlo, y esa línea quedó pegada dentro de
    `ApiToken` en vez de en su clase -- SQLAlchemy lo delató de
    inmediato (`Mapper 'TrustedDevice' has no property 'user'`) al
    primer uso. Lección: después de insertar una clase nueva ENTRE dos
    clases existentes en `models.py`, releer el bloque completo
    (no solo lo que se acaba de escribir) antes de asumir que quedó
    bien — un modelo grande como este tiene relaciones que se definen
    varias líneas después del último `Column`, fáciles de no ver en
    una lectura parcial.
  - **Retrofit que falta** (mecánico, mismo patrón que "Probar
    conexión", solo falta tiempo): Reiniciar, Apagar, Vaciar,
    crear/editar/eliminar Usuarios del dispositivo -- cada uno necesita
    (a) agregar la rama `action="..."` a su `run_device_op(...)` y (b)
    agregar el branch correspondiente en `_run_action()` de
    `central/remote_agent.py`. `device_sync`/`backup_device` NO pasan
    por `run_device_op()` (usan `central.sync` directo), así que para
    dispositivos remotos ya funcionan solos vía `sync_all(only_agent=...)`
    -- no hay nada que retrofittear ahí.
  - Migración de datos SQLite (producción Windows real) -> Postgres +
    reemplazar las migraciones `_migrate_add_*` a mano por Alembic:
    pedido por el usuario, **todavía no empezado**.
- **2026-10-15: instalador y scripts de gestión de Docker** (misma
  sesión, después de API + puente remoto): `deploy/docker/install.ps1`/
  `install.sh` (elige central o agente, pide SIEMPRE los datos de
  conexión/credenciales, deja `instalacion_<fecha>.txt` con el resumen)
  y `manage.ps1`/`manage.sh` (`start/stop/restart/status/diagnose`) +
  `.bat` de doble clic. Ver el bullet correspondiente en "Arquitectura y
  decisiones clave" arriba para los dos bugs reales que aparecieron al
  probarlo (PowerShell tragándose `-d` como `-Debug`, y un `if` de bash
  sin `else` que nunca activaba el valor por defecto) -- ambos
  corregidos y vueltos a probar de punta a punta. **Todavía NO
  commiteado** (sin pedir commit todavía).
- **2026-10-19: bug real de puerto/firewall encontrado probando contra
  el servidor central de verdad** (usuario probando una PC remota real
  por VPN, no un ensayo local): el servicio `db` de `docker-compose.yml`
  nunca publicaba el puerto 5432 hacia afuera del host, así que ningún
  agente remoto iba a poder conectarse nunca, sin importar qué tan bien
  estuviera la VPN -- confirmado con el usuario que **la central sigue
  con la instalación nativa de Windows (SQLite)**, todavía no migró a
  Docker, así que esto es la primera vez que se iba a probar la
  conexión real. Corregido (`docker-compose.yml` publica
  `POSTGRES_PORT`, 5432 por defecto; `install.ps1`/`install.sh` lo
  preguntan y `install.ps1` intenta abrir el Firewall de Windows solo
  si corre elevado). Ver el bullet correspondiente en "Arquitectura y
  decisiones clave" arriba para el detalle completo, incluida la
  limitación de que la rama elevada del Firewall no se pudo probar en
  esta sesión. **Todo esto sin commitear** (sin pedir commit todavía).
- **2026-10-20: migración real SQLite -> PostgreSQL construida**
  (`central/migrate_sqlite_to_postgres.py`,
  `deploy/docker/migrar_servidor_central.ps1`) -- el pendiente de la
  entrada anterior ("la migración real... todavía no empezado") ya no
  aplica, se construyó y se probó de punta a punta contra la base local
  real de este dev (6 empleados, 39,685 marcaciones -- ver el bullet
  correspondiente en "Arquitectura y decisiones clave" arriba para el
  detalle completo). **Lo que SÍ sigue pendiente**: correrlo de verdad
  contra el servidor central de producción -- el orquestador completo
  (`migrar_servidor_central.ps1`, con `Stop-ScheduledTask` real sobre
  las tareas nativas) no se pudo probar tal cual se invoca en este
  entorno (sin forma de conseguir una consola elevada de Windows acá),
  así que antes de correrlo en el servidor real, recomendado hacer un
  primer ensayo en una copia de prueba. Commiteado y pusheado a
  `origin/main` en 4 commits (`e18093d`..`0a27c57`): Docker, API +
  puente remoto, instalador/gestión de Docker, y esta migración.
- **2026-10-20: agente remoto sin Docker** (`deploy/windows_server/
  install_agente_remoto.ps1`, `agente_remoto_servicio.ps1`, `.bat`
  `AsistenciaAgenteRemoto_*`) -- el usuario reportó que la PC de la sede
  remota donde pensaba desplegar no tiene virtualización habilitada en
  BIOS, así que Docker Desktop no es una opción ahí. Ver el bullet
  correspondiente en "Arquitectura y decisiones clave" arriba para el
  detalle completo (mismo patrón que el panel central nativo, sin
  Docker para nada). **Pendiente**: probarlo con una consola realmente
  elevada (Tarea Programada real, ciclo Start/Stop/Restart) -- en este
  entorno no se pudo. **Sin commitear** (sin pedir commit todavía).
- **2026-10-20: resultó que la central TAMPOCO tiene virtualización** --
  es una VM de Hyper-V sin virtualización anidada (confirmado por el
  usuario al preguntarle directamente, después de que la sede remota ya
  había dado el mismo problema). Se construyó
  `deploy/windows_server/migrar_a_postgresql.ps1` -- la versión SIN
  Docker de `migrar_servidor_central.ps1` (PostgreSQL para Windows
  nativo + el `install.ps1` nativo de siempre con `-DatabaseUrl`). Ver
  el bullet correspondiente en "Arquitectura y decisiones clave" arriba
  para el bug real que encontró (mensajes de error de PostgreSQL
  localizados al español) y el detalle de las pruebas (PostgreSQL 17
  real instalado y desinstalado vía `winget` en esta sesión). **Con
  esto, la ruta recomendada para TODO este despliegue -- central y sede
  remota -- pasó a ser 100% nativa, sin Docker en ningún lado**; los
  scripts de Docker (`deploy/docker/`) quedan como alternativa para
  quien sí tenga virtualización disponible, no como el camino principal
  que se pensaba al empezar esta sesión. **Pendiente**: lo mismo que la
  entrada anterior -- probarlo con una consola elevada de verdad contra
  una instalación nativa real. Commiteado y pusheado a `origin/main`
  (`3e103e7`, `83244f7`). Dejó una carpeta vacía `C:\Program
  Files\PostgreSQL\17` en esta PC de dev (residuo del desinstalador de
  PostgreSQL, un bloqueo de seguridad de la herramienta impidió
  borrarla) -- inofensiva, el usuario la puede borrar cuando quiera.
- **2026-10-21: usuario corriendo `migrar_a_postgresql.ps1` de verdad
  contra su servidor, CUATRO rondas de bugs reales encontrados y
  corregidos, uno por intento** -- ver el detalle completo de los
  cuatro en "Arquitectura y decisiones clave" arriba:
  - Bug #2 (`C:\Asistencia` con código viejo, faltaba el script de
    migración) -- commiteado en `a2fd09f`.
  - Bug #3 (contraseña de PostgreSQL desincronizada en una segunda
    corrida, `UnicodeDecodeError` confuso) -- commiteado en `00654b0`.
  - Bug #4 (`robocopy` fallando en silencio porque el repo del usuario
    está clonado dentro de `C:\WINDOWS\System32\`, un directorio
    protegido de Windows -- el script nunca revisaba su código de
    salida) -- corregido con chequeo de `$LASTEXITCODE` + `Test-Path`,
    **todavía SIN commitear**.
  **Todavía sin confirmar**: que el usuario haya movido el repo fuera
  de `C:\WINDOWS\System32` (recomendado, probablemente la causa raíz
  real del bug #4) y que haya corrido el script de punta a punta con
  éxito -- cada intento hasta ahora se detuvo ANTES de tocar datos (el
  respaldo del SQLite real sigue a salvo en `C:\Asistencia\backups\`,
  el panel nativo sigue ahí sin tocar, nada se perdió en ningún
  intento). Si sigue fallando después de mover el repo, revisar también
  si hay antivirus/Windows Defender interfiriendo con la copia.
- **2026-10-21: central migrada a PostgreSQL con éxito, confirmado por
  el usuario** ("ya realice el despliegue y migración a postgresql, y
  probé el acceso a la aplicación") -- el bug #4 de arriba quedó
  resuelto en la práctica (no está confirmado si fue mover el repo, el
  fix del código, o ambos, pero el resultado final funcionó). Pasando al
  despliegue del agente remoto en la sede "megaplaza": VPN y PostgreSQL
  de la central confirmados accesibles desde la PC remota
  (`Test-NetConnection` con `TcpTestSucceeded: True`, la central ya
  tiene el puerto abierto). Encontrado y corregido el **bug real #5**
  (alias de ejecución de `python` de Windows, ver el detalle completo en
  "Arquitectura y decisiones clave" arriba) -- el primer intento de
  `install_agente_remoto.ps1` ahí registró una Tarea Programada rota sin
  que el usuario se enterara (mostró "Listo" con el agente en realidad
  caído). **Pendiente de confirmar**: que el usuario haya instalado
  Python real en esa PC remota y vuelto a correr el instalador con el
  fix -- recién ahí el agente de "sede-megaplaza" queda operativo de
  verdad. **Sin commitear** (sin pedir commit todavía).
- **Biométrico nuevo evaluado**: manual revisado (ZKTeco Green Label
  G3, reconocimiento facial/vascular) -- usa el mismo protocolo que ya
  soporta la app: puerto TCP 4370 por defecto, Clave de Comunicación,
  ID de dispositivo 1-254, exactamente el modelo que `pyzk`/
  `attendance_system.py` ya hablan (ADMS -- el protocolo de push a un
  servidor cloud -- está disponible en el equipo pero NO es lo que esta
  app usaría). Compatible en teoría; recomendado probar UN equipo real
  contra `pyzk` antes de comprar varios, por la misma razón que el K20
  ya dio sorpresas de firmware en esta misma base de código.
- **Manual de usuario para RRHH**, Artifact publicado:
  https://claude.ai/artifact/52rSs6ftJj4fMS1SV5sNz7 — cubre cada
  pantalla con capturas del laboratorio local, las columnas de los dos
  imports de Excel, y un aviso de que es laboratorio, no producción.
  Para actualizarlo: `Artifact(action:"read", url:"<esa URL>")` primero
  (las variables de publicación no persisten entre conversaciones).

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
