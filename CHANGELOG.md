# Changelog

Todos los cambios notables de este proyecto se documentan aquí. El formato
sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.0.0/) y el
versionado es [SemVer](https://semver.org/lang/es/) (`MAYOR.MENOR.PARCHE`).

La versión vigente es la que está en el archivo [`VERSION`](VERSION) — es la
que numera el instalador de escritorio y la que se etiqueta (`git tag`) en
cada release. Ver [`deploy/README.md`](deploy/README.md#cómo-sacar-una-versión-nueva)
para el procedimiento completo de release.

## [Unreleased]

### Agregado
- **Puente remoto completo: todas las acciones de dispositivo ya
  funcionan contra un biométrico de agente remoto** (`central/
  remote_agent.py`, `central/webapp.py`): hasta ahora solo "Probar
  conexión" pasaba por el puente -- Reiniciar, Apagar, Vaciar
  dispositivo, Ping, Descargar respaldo, y la gestión completa de
  Usuarios del dispositivo (listar, crear, editar, eliminar) ya
  funcionan igual para un dispositivo local o de sede remota, sin que
  el usuario note la diferencia. "Descargar respaldo" fue el más
  delicado: antes no pasaba por el mecanismo del puente en absoluto, y
  ahora viaja como una lista de filas por JSON desde el agente,
  reconstruida en un DataFrame del lado central para armar el mismo CSV
  de siempre. Probado de punta a punta contra el PISO2 real (acciones
  de solo lectura: ping, probar conexión, listar usuarios, un respaldo
  completo de 36,494 marcaciones) -- las acciones de escritura
  (reiniciar/apagar/vaciar/crear-editar-eliminar usuario) siguen el
  mismo patrón exacto ya probado, pero no se ejecutaron contra el
  equipo real por estar en uso productivo.
- **Página de estado del agente remoto** (`central/
  remote_agent_status.py`): una página web liviana y de solo lectura
  que corre en la propia PC del agente (puerto 5050 por defecto,
  configurable al instalar), para confirmar desde esa sede -- sin
  PowerShell ni VPN hacia la central -- que el agente está vivo, que
  llega a la base central, y qué tan accesibles están sus biométricos
  en este momento. Deliberadamente NO es una copia del panel central
  (eso duplicaría login/roles/auditoría y generaría confusión sobre
  cuál es la fuente de verdad) -- es una sola página sin autenticación,
  pensada para la misma confianza que ya tiene esa red local con los
  biométricos. `install_agente_remoto.ps1` la levanta sola (vía
  `waitress`, mismo servidor que ya usa el panel central) y abre el
  puerto en el Firewall de Windows si corre elevado.
- **Migración a PostgreSQL nativa, sin Docker**
  (`deploy/windows_server/migrar_a_postgresql.ps1`): para cuando el
  servidor central tampoco tiene virtualización disponible (ej. es una
  VM de Hyper-V sin virtualización anidada habilitada). Usa PostgreSQL
  para Windows instalado como cualquier programa (sin BIOS, sin
  hipervisor), crea el usuario/base de la app con `psql`, migra los
  datos reales con el mismo `central/migrate_sqlite_to_postgres.py`, y
  reinstala el panel con el `install.ps1` nativo de siempre (apuntado a
  `-DatabaseUrl`) -- el panel sigue siendo exactamente el mismo
  mecanismo de Tareas Programadas que ya corre en producción, nada
  cambia ahí salvo la base de datos detrás. Probado de punta a punta
  contra una instalación real de PostgreSQL 17 (no Docker): encontró y
  corrigió un bug real -- el mensaje de error de PostgreSQL para "el rol
  ya existe" viene LOCALIZADO según el idioma de Windows (en español:
  "el rol «x» ya existe", no "already exists"), así que la primera
  versión (que buscaba ese texto en inglés) nunca detectaba
  correctamente un segundo intento sobre un usuario/base ya creados.
  Corregido consultando `pg_roles`/`pg_database` ANTES de crear, en vez
  de crear y adivinar el error después.
- **Agente remoto nativo, sin Docker** (`deploy/windows_server/
  install_agente_remoto.ps1`, `agente_remoto_servicio.ps1`, `.bat`
  `AsistenciaAgenteRemoto_*`): para una sede cuya PC remota no tiene
  virtualización habilitada en BIOS (Docker Desktop no arranca ahí).
  Mismo mecanismo que ya usa el panel central nativo (Python + venv +
  Tarea Programada de Windows, sin Docker para nada) aplicado al agente
  remoto (`central/remote_agent.py`, que no tiene ninguna dependencia de
  Docker). Pide siempre el nombre del agente y los datos de conexión a
  la base central; el script de gestión agrega un `Diagnose` que prueba
  la conexión real a la central (`Test-NetConnection`) y muestra el
  `DATABASE_URL` guardado con la contraseña enmascarada.
- **Migración real de datos SQLite -> PostgreSQL**
  (`central/migrate_sqlite_to_postgres.py`,
  `deploy/docker/migrar_servidor_central.ps1`): hasta ahora Docker solo
  arrancaba con una base vacía -- esto trae los datos REALES (empleados,
  marcaciones, usuarios del panel, horarios, vacaciones/permisos, todo)
  desde el SQLite nativo. El script de Python copia tabla por tabla en
  el orden correcto de llaves foráneas, conserva los IDs originales,
  reajusta las secuencias de PostgreSQL para que el próximo insert de la
  app no choque con un ID ya usado, y se niega a correr si el destino ya
  tiene datos (salvo `--force`). Tolera un SQLite de origen más viejo
  que todavía no tenga alguna tabla/columna agregada después (ej.
  `api_tokens`, `devices.agent_name`) -- la trata como "nada que migrar
  ahí todavía", no como error.
  `migrar_servidor_central.ps1` es el que de verdad se corre en el
  servidor central: pide confirmación explícita, detiene las tareas
  programadas nativas (para que nada siga escribiendo durante la
  migración), hace un respaldo con fecha del SQLite real ANTES de tocar
  nada, pide los datos de conexión de PostgreSQL (siempre, igual que
  `install.ps1`), migra, y solo si la migración salió bien levanta el
  panel completo -- si falla, no toca el panel nuevo y deja clarísimo
  cómo volver al sistema nativo (las tareas programadas no se eliminan,
  solo se detienen). También intenta abrir el puerto de PostgreSQL en el
  Firewall de Windows automáticamente. Probado de punta a punta en esta
  sesión contra la base de datos local real (6 empleados, 39,685
  marcaciones, 2 cuentas de usuario, horarios, vacaciones): las 14
  tablas migraron con conteos exactos, la secuencia de Postgres quedó
  bien (un insert de prueba después de migrar tomó el siguiente ID sin
  chocar), y la aplicación arrancó normal contra la base ya migrada.

### Corregido
- **`install_agente_remoto.ps1` e `install.ps1` no detectaban el "alias
  de ejecución de aplicaciones" falso de `python` en Windows** -- el
  `python.exe` que Windows pone en PATH por defecto
  (`%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe`) resuelve igual que
  un Python real para `Get-Command`, pero al ejecutarlo solo abre la
  Microsoft Store y no hace nada. El chequeo de "¿existe el comando
  python?" pasaba igual, `python -m venv venv` no creaba nada, y el
  resto del instalador seguía adelante sin darse cuenta -- en el caso
  real del usuario, terminó registrando e iniciando la Tarea Programada
  del agente remoto apuntando a un `venv\Scripts\python.exe` que nunca
  se creó, y mostrando "=== Listo ===" como si hubiera funcionado.
  Corregido: ahora se confirma que `python --version` de verdad
  responde con un número de versión (no solo que el comando "existe"),
  y además se verifica explícitamente que `venv\Scripts\python.exe`
  quedó creado antes de registrar la Tarea Programada -- si cualquiera
  de los dos falla, el script para con un mensaje claro en vez de
  reportar éxito falso. Verificado reproduciendo el alias falso con un
  script de prueba que imita su comportamiento exacto (mismo mensaje,
  mismo código de salida) y confirmando que la detección nueva lo
  atrapa, mientras que una instalación de Python real sigue pasando sin
  problema.
- **`migrar_a_postgresql.ps1` no detectaba un `robocopy` que fallara en
  silencio** -- el código de salida de `robocopy` nunca se revisaba (sus
  códigos son por bits: 0-7 éxito/informativo, 8+ error real, no el
  0/distinto-de-0 habitual). En el servidor real del usuario, que tiene
  el repo clonado dentro de `C:\WINDOWS\System32\` (una carpeta con
  permisos/protecciones especiales de Windows), la copia de
  `central/requirements.txt` hacia `C:\Asistencia` no se completaba bien
  y el script seguía adelante igual, fallando recién más abajo en `pip
  install` con un "No such file or directory" que no explicaba la causa
  real. Corregido: ahora revisa el código de salida de `robocopy` Y
  confirma con `Test-Path` que `requirements.txt` quedó copiado antes de
  seguir -- si no, para con un mensaje claro sugiriendo mover el repo
  fuera de una carpeta protegida de Windows.
- **`migrar_a_postgresql.ps1` fallaba al re-correrlo sobre un usuario de
  PostgreSQL que ya existía de un intento anterior** -- el script dejaba
  la contraseña real en PostgreSQL sin tocar ("ya existe, se deja
  igual"), pero seguía usando la contraseña recién tipeada/generada en
  ESA corrida para armar la conexión -- nunca coincidían. El error que
  esto producía era particularmente confuso: no "contraseña incorrecta"
  sino un `UnicodeDecodeError` de psycopg2 (el mensaje de autenticación
  fallida de PostgreSQL viene en español, en una codificación que
  psycopg2 no esperaba). Reportado por el usuario en su segundo intento
  real. Corregido: si el usuario ya existe, ahora el script actualiza su
  contraseña (`ALTER USER ... WITH PASSWORD`) a la que se acaba de
  ingresar, en vez de dejarla desincronizada. Mismo cambio corrigió de
  paso que `pip install -r central\requirements.txt` fallaba con "No
  such file or directory" por depender de una ruta relativa al
  directorio de trabajo del proceso (no siempre bien propagado en una
  sesión elevada) -- ahora usa una ruta absoluta. Verificado reproduciendo
  el escenario exacto (usuario ya creado, contraseña distinta en la
  segunda corrida): confirmó la actualización de contraseña y una
  conexión real exitosa, sin el error de Unicode.
- **`migrar_a_postgresql.ps1` no actualizaba `C:\Asistencia` con el
  código más reciente antes de migrar** -- si la carpeta de instalación
  tenía código de antes de que existiera `central/
  migrate_sqlite_to_postgres.py`, la migración fallaba con "No module
  named central.migrate_sqlite_to_postgres" en vez de migrar. Reportado
  por el usuario corriéndolo de verdad contra su servidor. Corregido:
  ahora el script actualiza `$InstallDir` con `robocopy` (mismos
  excludes que ya usa `install.ps1`, nunca toca el `.db` real ni
  `devices.json`) y reinstala `requirements.txt` ANTES de intentar
  migrar, no solo al final.
- **El `db` (PostgreSQL) de `docker-compose.yml` nunca publicaba el
  puerto 5432 hacia afuera del host** -- solo era visible entre los
  contenedores del propio `docker compose` (`web`/`sync`), nunca desde
  otra máquina. Esto rompía por completo la idea de "agente remoto"
  (una sede detrás de otra VPN conectándose a la base central): la VPN
  en sí funcionaba perfecto (`ping` llegaba), pero el puerto nunca
  respondía porque Docker no lo estaba exponiendo. Encontrado en vivo
  con el usuario probando una PC remota real contra el servidor central
  (`Test-NetConnection ... -Port 5432` con `PingSucceeded: True` /
  `TcpTestSucceeded: False`). Ahora el puerto (`POSTGRES_PORT`,
  configurable, 5432 por defecto) se publica -- `install.ps1`/
  `install.sh` lo preguntan y además intentan abrir ese puerto en el
  Firewall de Windows automáticamente cuando corren en una consola de
  Administrador (si no, dejan el comando exacto para hacerlo a mano).
  Verificado de punta a punta: contenedor `db` publicando
  `0.0.0.0:5432->5432/tcp` y una conexión real desde fuera del
  contenedor confirmando `TcpTestSucceeded: True`.

### Agregado
- **Instalador interactivo y scripts de gestión para el despliegue con
  Docker** (`deploy/docker/install.ps1` / `install.sh`,
  `deploy/docker/manage.ps1` / `manage.sh`, `deploy/docker/
  docker-compose.agent.yml`, `.bat` de doble clic en `deploy/docker/`):
  un solo instalador para Windows y Linux que SIEMPRE pregunta por
  pantalla (nunca instala con valores por defecto en silencio) si la
  máquina es **servidor central** o **agente remoto**, los datos de
  conexión a la base de datos (o genera una contraseña automática si se
  deja vacío), el puerto del panel, la hora de sincronización y la
  primera cuenta de super administrador; al final deja un archivo
  `instalacion_<fecha>.txt` con el resumen de todo lo ingresado
  (incluidas las contraseñas, con advertencia de que hay que guardarlo
  en un lugar seguro y borrarlo de ahí). `manage.ps1`/`manage.sh`
  agregan `start/stop/restart/status` y un `diagnose` nuevo (estado de
  Docker, de cada contenedor, últimas líneas de log, si PostgreSQL
  responde y si el panel responde por HTTP) -- pensado para no tener que
  memorizar comandos de `docker compose` cuando algo "no funciona". A
  diferencia de los `.bat` de `deploy\windows_server\`, los de Docker NO
  se auto-elevan a Administrador (Docker Desktop corre con la sesión del
  usuario, no con SYSTEM). Probado de punta a punta en esta sesión,
  en modo central y en modo agente, incluidos dos bugs reales que solo
  aparecieron al correrlo de verdad (no se habrían visto solo leyendo el
  código): `-d` de `docker compose up -d` lo absorbía PowerShell como
  abreviación del parámetro común `-Debug` al pasarlo suelto a una
  función propia, dejando el panel "pegado" en primer plano mostrando
  logs en vez de desprenderse -- se corrigió pasando los argumentos como
  un array con nombre; y en `install.sh`, un `if [ -f "$archivo" ]; then
  ...; fi` sin `else` siempre devuelve éxito (0) aunque la condición sea
  falsa, así que un `|| valor_por_defecto` después nunca se activaba y
  `POSTGRES_USER`/`POSTGRES_DB`/`SYNC_DAILY_AT` quedaban vacíos en el
  `.env` en una instalación nueva (la app no se notaba porque
  `docker-compose.yml` ya trae sus propios valores por defecto) --
  se corrigió usando `${variable:-default}` en vez de depender del
  código de salida de la función.
- **API con autenticación por token** (`/api/v1/...`, `central/api.py`):
  para integrar con una app de planillas/tareo externa, sin usar la
  sesión de navegador de las pantallas humanas. Lectura de empleados,
  horarios, marcaciones, faltas y tardanzas; escritura (crear/editar)
  de empleados y horarios, y asignación de horario a un empleado. Los
  tokens se crean y revocan desde **API** en el menú (solo super admin,
  `/api-tokens`) con permiso de solo lectura o lectura+escritura; el
  valor del token se muestra una sola vez, al crearlo. Cada acción por
  API queda en el log de auditoría como `API:<nombre del token>`, aparte
  de las acciones humanas. Probado de punta a punta (todas las rutas,
  token inválido, token revocado, token de solo lectura intentando
  escribir, actualización parcial que no borra campos no mencionados)
  con el cliente de pruebas de Flask, y también contra PostgreSQL real
  en Docker.
- **Puente para administrar biométricos en sedes remotas**
  (`central/remote_agent.py`, campo "Agente remoto" en Dispositivos):
  para un equipo que este servidor no puede alcanzar directo (ej. detrás
  de otra VPN) pero cuyo propio servidor de sede SÍ llega a la base
  central. Se instala el mismo código ahí como un agente que sincroniza
  sus propios dispositivos y ejecuta acciones de administración que la
  central encola -- por ahora solo "Probar conexión" quedó conectada en
  ambos lados; el resto (Reiniciar, Apagar, Vaciar, gestión de Usuarios
  del dispositivo) todavía no, y lo avisa con un mensaje claro en vez de
  intentar una conexión directa que nunca iba a funcionar. Probado de
  punta a punta contra un reloj real: un proceso central encoló el
  comando, un agente remoto simulado lo ejecutó de verdad contra el
  equipo, y el resultado volvió correctamente.
- **Despliegue con Docker** (`Dockerfile`, `docker-compose.yml`,
  `central/sync_loop.py`, ver `deploy/docker/README.md`): tres
  contenedores (panel web, sincronización, PostgreSQL) que corren igual
  en Windows y en Ubuntu -- un solo camino de despliegue en vez de
  mantener el instalador de Windows y el de Linux por separado. Probado
  de punta a punta contra un PostgreSQL real: arranque de los tres
  contenedores, creación automática de las tablas, inicio de sesión y
  todas las pantallas, y conexión real desde dentro del contenedor a un
  reloj biométrico de la red local sin configuración adicional.
- **Buscador de DNI en "Sin vincular"**: el desplegable plano de
  empleados (difícil de revisar por DNI en una lista larga) se
  reemplazó por un campo de búsqueda con autocompletado -- se escribe
  el DNI, el navegador sugiere coincidencias, y el botón "Vincular" se
  queda deshabilitado hasta que la coincidencia sea exacta (aparece un
  "✓ Nombre" en verde confirmándolo) o se escriba un nombre nuevo. Ya no
  se puede vincular "a ciegas" con una fila parcialmente escrita.
- **Ficha de empleado enriquecida**: nuevos campos opcionales -- Nombres,
  Apellido paterno, Apellido materno, Fecha de nacimiento, Celular,
  Correo personal, Correo corporativo, Dirección, Área y Sede
  (administrativa, independiente del dispositivo donde marca). Si se
  llenan Nombres/Apellidos, el "Nombre completo" se arma solo al
  guardar (Nombres + Apellido paterno + Apellido materno); si se dejan
  vacíos, el alta rápida de un solo campo de nombre sigue funcionando
  igual que antes -- nada de esto es obligatorio ni rompe empleados ya
  cargados. La ficha ahora también muestra en qué dispositivo(s) y con
  qué ID está vinculado el empleado ("Vinculado en"), y "Empleados"
  suma columnas de Área y Sede.
- **Plantilla de Excel descargable** en Empleados y en Horarios
  ("Descargar plantilla" / "Asignar desde Excel"): un archivo en
  blanco con los encabezados correctos y una fila de ejemplo, listo
  para llenar y volver a subir -- ya no hace falta armar el archivo
  a mano leyendo la lista de columnas soportadas. La importación de
  empleados ahora reconoce Nombres/Apellidos/Fecha de nacimiento/
  Celular/Correos/Dirección/Área/Sede además de las columnas que ya
  soportaba, y al actualizar un empleado existente por código nunca
  borra un campo que la fila importada simplemente no traía.
- **Menú lateral izquierdo** en reemplazo de la barra superior: colapsable
  (botón "Colapsar" al fondo del menú, y un botón flotante para volver a
  mostrarlo) y de ancho ajustable arrastrando su borde derecho -- ambos
  se recuerdan entre páginas (en el navegador de quien lo usa, no es un
  ajuste compartido). Agrupa las pantallas de administración
  (Cuentas/Backup/Auditoría/Permisos) bajo un rótulo aparte, resalta la
  pantalla activa, y cada ítem tiene su propio ícono. Sin librerías ni
  fuentes de íconos externas -- los íconos son SVG in-line
  (`central/icons.py`), igual de autocontenido que el resto del panel
  (pensado para un servidor sin salida a internet).
- **Vacaciones, permisos y descansos médicos** (`/exceptions`, módulo
  "Vacaciones y permisos"): registro simple por empleado y rango de
  fechas. Un día dentro de un registro deja de contar como "Falta" en el
  reporte de faltas y aparece como "Justificado" -- también accesible
  desde la ficha de cada empleado. Sin flujo de aprobación propio: quien
  ya puede gestionar empleados puede registrar uno, mismo nivel de
  confianza que el resto del maestro de empleados.
- **Asignar horarios desde Excel** (`/schedules/import`): columnas
  código, horario y vigencia opcional -- mismo patrón que la importación
  de empleados ya existente (reporta fila por fila qué se asignó y qué
  falló, sin detener el archivo completo por un error puntual).
- **Panel** (`/reports/overview`, módulo "Panel"): tarjetas con presentes,
  tardanzas, faltas, justificados y empleados sin horario asignado de
  HOY, más una tabla de quién acumula 2 o más faltas en los últimos 30
  días. Pantalla aparte de "Marcaciones" (que sigue siendo la página de
  inicio tras iniciar sesión) para no sumarle este cálculo a la pantalla
  más visitada del panel.
- **Horarios y reporte de faltas**: maestro de horarios configurable
  (`/schedules`, módulo "Horarios") -- cada uno con su propia hora de
  ingreso, hora de salida, tolerancia de tardanza en minutos, ventana de
  refrigerio (opcional) y sus propios días laborables marcados uno por
  uno (no un preset L-V/L-S fijo, porque el día de descanso varía
  libremente según área/tienda/especialidad). Desde la ficha de cada
  empleado se le asigna un horario con fecha de vigencia -- si cambia de
  horario, se guarda el historial completo en vez de perder el anterior.
  Nuevo reporte **Faltas** (`/reports/absences`, módulo "Reporte de
  faltas"): por rango de fechas y sede, muestra a quién le falta marcar
  (usando "Desde" = "Hasta" = hoy) o quién acumula más de N faltas en un
  período, con export a Excel. Un día sin marcación solo cuenta como
  falta si el horario asignado lo marca como laborable ese día -- días de
  descanso no entran en el conteo. A los empleados activos sin ningún
  horario asignado se les avisa aparte en el reporte (su asistencia no se
  pudo evaluar) en vez de contarlos silenciosamente como falta o como
  presente.
- **Reporte de Tardanzas y horas extra** (`/reports/hours`, módulo
  "Tardanzas y horas extra"): por cada empleado y día, compara la primera
  marcación contra la hora de ingreso (tardanza, en minutos) y la última
  marcación contra la hora de salida del horario asignado (minutos
  extra), y evalúa si el refrigerio se marcó y si se excedió del tiempo
  esperado (con la misma tolerancia del horario). Solo lista días con
  algo que revisar -- un día sin novedad no aparece, igual que "Faltas"
  solo lista días con falta. Con export a Excel. Un horario creado antes
  de que existiera "Hora de salida" no calcula horas extra hasta que se
  vuelva a guardar desde `/schedules` (se avisa en pantalla).
- Pantalla **Permisos** (solo super admin): elige, por módulo, si "Solo
  lectura" y "Administrador" pueden abrir Marcaciones, Exportar
  marcaciones, Dispositivos, Usuarios del dispositivo, Empleados y Sin
  vincular -- por defecto queda igual que antes de esta función (nada
  cambia hasta que alguien lo toque). "Exportar marcaciones" es aparte
  de "Marcaciones" (se puede dejar ver la pantalla sin poder exportar).
  Nunca le da a "Solo lectura" permisos de escritura (eso lo sigue
  controlando cada pantalla), ni a "Administrador" las pantallas de
  Super administrador (Cuentas, Backup, Auditoría, Permisos), que
  siguen fijas.
- Cualquier usuario puede cambiar su propia contraseña desde
  Seguridad, pidiendo la actual -- antes solo un super admin podía
  resetearla (sin pedir la anterior, para el caso de olvido).
- Botón "Eliminar" para cuentas del panel web (solo super admin, no
  puedes eliminar la tuya propia) -- antes solo se podían desactivar.
- "Usuarios de un dispositivo": campo para ver/cambiar/resetear la
  contraseña (PIN) local de cada usuario del reloj -- la que se usa en
  el menú físico del equipo y para el respaldo por USB, independiente
  de la "comm key" del dispositivo y de la clave del panel web. Ya
  existía la forma de marcar a alguien como "Administrador del equipo"
  (Privilegio) y de eliminarlo, pero no de gestionar su PIN.
- La vista "Resumen por día" (y sus exports CSV/Excel/PDF) solo mostraba
  Entrada/Salida (primera y última marcación) -- si alguien marcaba
  también al salir/entrar de almuerzo, esas marcaciones de en medio
  quedaban contadas en "Marcaciones" con el aviso "revisar" pero nunca
  se veían ni se exportaban, sin más remedio que ir a "Marcaciones
  crudas" y filtrar a mano. Ahora hay una columna "Todas las
  marcaciones" con la hora exacta de cada toque del día, en pantalla y
  en los tres exports (el PDF de esta vista pasó a horizontal para que
  entre sin truncar).
- Botón "Resetear contraseña" en Cuentas (solo super admin): fija una
  contraseña nueva para cualquier usuario del panel sin necesitar la
  anterior.
- Desactivar un empleado en el maestro central (con "Propagar a los
  relojes" marcado) ahora también elimina su huella/tarjeta de cada
  reloj donde está vinculado -- revoca su acceso físico real, no solo
  el registro en la base central. Su historial de marcaciones nunca se
  toca (ni el borrado en el reloj ni la desactivación en la base lo
  afectan).
- Log de auditoría (`/audit`, solo super admin): conexiones (login, 2FA,
  ping/probar conexión) y cambios (dispositivos, empleados, cuentas,
  backup, sincronización), con IP y nombre de PC (mejor esfuerzo, por DNS
  inverso) y hora local del servidor.
- Botón "Vaciar dispositivo": borra las marcaciones guardadas en el reloj
  físico para que empiece de cero, sin tocar el historial ya sincronizado
  en la base central. Pide escribir el nombre del equipo para confirmar.
- Botón "Descargar respaldo": trae un CSV con TODAS las marcaciones que
  hay ahora mismo en el equipo (no solo lo que ya está en la base
  central) y de paso las guarda en la base central. Pensado para usar
  justo antes de "Vaciar dispositivo", como respaldo independiente.
- "Eliminar" un dispositivo ya no borra su historial bajo ninguna
  circunstancia -- solo lo oculta de la lista y de la sincronización, con
  un botón "Restaurar" en "Ver eliminados" para traerlo de vuelta.
- Bloqueo de cuenta tras 3 intentos fallidos de inicio de sesión seguidos
  -- solo un super administrador puede desbloquearla, desde Cuentas.
- Interruptores de emergencia (`.bat`) para iniciar/detener/reiniciar el
  servicio en Windows Server, con el nombre exacto de cada tarea.
- Guías de instalación ilustradas en PDF (Windows/Linux) y diagrama de
  arquitectura para draw.io.
- Flujo de release versionado por tags de Git + GitHub Actions.

### Corregido
- El campo de búsqueda de "Sin vincular" no tenía límite ni validaba
  que fuera numérico -- se podía pegar/teclear una cadena larga de
  dígitos (o de cualquier tipo de texto) sin ningún aviso claro de que
  eso nunca iba a calzar con un DNI real. Ahora el campo se limita a
  exactamente 8 dígitos (cualquier caracter que no sea número se
  descarta al vuelo) y busca de forma exacta contra el DNI (código) del
  maestro de Empleados -- ya no admite buscar por nombre libre, y
  muestra "Faltan N dígito(s)" mientras se completa o "Ningún empleado
  tiene ese DNI en el maestro" si no hay coincidencia.
- Un usuario del reloj enrolado sin nombre (por huella/tarjeta, sin usar el
  teclado del equipo) reportaba un nombre tipo "NN-77672037" -- eso lo
  pone el propio reloj biométrico, no la aplicación, pero mostrarlo tal
  cual en Marcaciones/Faltas/Tardanzas y sus exportes leía como un
  nombre roto. Ahora se muestra como "ID 77672037" en esas pantallas
  (igual que un nombre realmente vacío) hasta que se vincule a un
  empleado real desde "Sin vincular" -- esa pantalla sigue mostrando el
  "NN-xxxxx" tal cual a propósito, porque ahí el objetivo es ver
  exactamente lo que reporta el reloj.
- El buscador de Marcaciones ("Buscar: nombre o ID") solo comparaba
  contra los campos crudos del reloj -- un empleado ya vinculado en
  Empleados cuyo reloj todavía reportaba "NN-xxxxx" no aparecía al
  buscar su nombre real, aunque el nombre real sí se mostrara en
  pantalla. Ahora el filtro también compara contra el nombre del
  empleado vinculado.
- Lentitud del panel al ver/exportar Marcaciones: el nombre de cada
  empleado se resolvía con una consulta a la base por cada marcación
  cruda en vez de una sola consulta por lote -- con semanas de historial
  (varias marcaciones por persona por día) esto era el verdadero cuello
  de botella, no el motor de base de datos. También se agregaron índices
  en `attendance_log.timestamp` y `employee_map.employee_id` (los
  reportes ahora recorren rangos de fechas completos, no solo un
  dispositivo+usuario a la vez) y se activó el modo WAL de SQLite para
  que una sincronización en curso ya no bloquee la lectura del dashboard.
  Con esto, SQLite bien indexado alcanza sin problema para el volumen
  actual -- migrar a Postgres/MySQL (ya soportado hoy vía `DATABASE_URL`,
  ver `central/db.py`) queda para si el volumen de marcaciones o la
  cantidad de sedes/escrituras concurrentes crece mucho más adelante.
- Editar un usuario del reloj desde el panel (aunque fuera solo para
  corregir el nombre) borraba en silencio su PIN local, porque
  `create_or_update_user` siempre mandaba `password=''` al dispositivo
  -- el protocolo ZK no tiene actualización parcial, cada `set_user`
  reescribe el registro completo. Ahora, si no se especifica una
  contraseña nueva, se reenvía la que ya tenía en vez de borrarla.
- Sincronización que fallaba con "TCP packet invalid" en dispositivos con
  transferencias grandes o de red inestable: ahora reintenta hasta 3
  veces con timeout ampliado, y una falla al desconectar ya no tapa el
  error real ni aborta la sincronización completa.
- Un dispositivo realmente colgado a nivel de socket (más allá de su
  propio timeout configurado -- visto de verdad contra un K20 real) podía
  dejar una sincronización corriendo en el servidor sin límite. Ahora hay
  un tope duro de 150s: siempre termina en éxito o error dentro de ese
  tiempo, nunca se queda corriendo para siempre.
- La `SECRET_KEY` ya no se regenera en cada actualización del servidor
  (antes cerraba la sesión de todos los usuarios activos).
- La sincronización automática pasó de cada 15 minutos a una vez por
  noche (23:00 por defecto, configurable con `-SyncTime` en
  `install.ps1`) -- los botones "Sincronizar" del panel siguen
  funcionando al instante cuando se necesite durante el día.
- **Bug crítico de actualización en Windows Server**: `install.ps1` nunca
  detenía el proceso que ya estaba corriendo antes de "iniciarlo" de
  nuevo -- y `Start-ScheduledTask` sobre una tarea ya activa no hace nada
  en Windows. Resultado: cada actualización cambiaba los archivos en
  disco, pero el servicio seguía sirviendo el código viejo hasta que
  alguien lo reiniciara por separado a mano. Corregido para que
  `install.ps1` (y el botón "Reiniciar") siempre detengan el proceso
  -- incluso forzándolo si quedó colgado en una llamada de red -- antes
  de volver a levantarlo.
- La pantalla "Usuarios" de un dispositivo (`/devices/<id>/users`) podía
  terminar en un Internal Server Error en crudo si el equipo no
  respondía (ej. timeout de red) -- ahora usa el mismo tope duro de 150s
  que "Sincronizar" y muestra un mensaje claro en vez de la pantalla de
  error de Flask.
- "Probar conexión", "Reiniciar", "Apagar", "Vaciar dispositivo" y las
  pantallas de alta/edición/baja de usuarios de un reloj se conectaban
  al equipo sin ningún límite de tiempo -- si el equipo no respondía
  (ej. timeout de red), la petición podía quedarse colgada indefinidamente,
  igual que el viejo problema de "Sincronizar". Ahora todas comparten el
  mismo tope duro de 150s.
- Un dispositivo con problemas de red podía recibir varias conexiones
  simultáneas (un clic manual mientras la sincronización automática
  también lo estaba consultando, por ejemplo) -- como el equipo solo
  acepta una sesión a la vez, esto hacía que ambas fallaran o se
  colgaran. Ahora cada dispositivo tiene su propio candado: si ya hay
  una operación en curso contra él, un segundo intento se avisa al
  instante ("ya tiene otra operación en curso") en vez de sumarse a la
  contienda.
- **Causa raíz encontrada para "Connection failed" en el panel cuando la
  app de escritorio sí conectaba al mismo equipo**: antes de hablar el
  protocolo ZK, pyzk hace un `ping` real del sistema operativo al
  dispositivo y aborta si no hay respuesta -- aunque el puerto TCP 4370
  sí esté abierto y disponible. En una red con ICMP filtrado entre el
  servidor y la subred de un dispositivo (común en redes segmentadas
  por firewall) esto produce un falso "no se pudo conectar" incluso con
  el equipo perfectamente accesible por TCP. Ahora se omite ese ping
  interno (`ommit_ping=True`) ya que la propia app ya verifica el
  puerto TCP por su cuenta. De paso, el motivo real de una conexión
  fallida (antes descartado y solo impreso en la consola del servidor)
  ahora se guarda y se muestra en el mensaje de error / auditoría.
- El candado por dispositivo (arriba) solo protegía dentro de un mismo
  proceso -- una sincronización manual desde el panel y la tarea
  programada (`python -m central.sync`, un proceso aparte de Windows
  Task Scheduler) seguían pudiendo chocar contra el mismo equipo al
  mismo tiempo, cada una sin saber de la otra. Ahora el candado vive en
  la base de datos compartida (tabla `device_locks`), así que cubre
  también ese caso: si la tarea programada ya está sincronizando un
  equipo, un clic manual sobre el mismo equipo se avisa al instante en
  vez de sumarse a la contienda -- verificado simulando ambos procesos
  a la vez contra un dispositivo real.

## [1.0.0] - 2026-09-15

Primera versión consolidada de la plataforma multi-dispositivo.

### Agregado
- Panel web central (`central/`): sincroniza varios relojes ZKTeco a una
  sola base de datos, con dashboard de RRHH.
- Roles de acceso: `super_admin`, `admin`, `viewer` con permisos
  diferenciados por módulo.
- Autenticación de doble factor (TOTP + QR) con opción de "recordar este
  equipo" por cookie.
- Maestro de empleados con importación desde Excel y vinculación con
  auto-sugerencia por Código/DNI.
- Exportación de marcaciones a CSV, Excel (con estilo) y PDF (con
  paginación).
- Backup/restore completo de la base de datos en JSON portable.
- Gestión de dispositivos desde el panel: agregar/editar, probar
  conexión, ping, sincronizar, reiniciar, apagar y eliminar.
- App de escritorio: pruebas de ping y reinicio remoto del equipo,
  corrección de agrupación de marcaciones (registros de solo salida ya
  no se perdían) y de columnas de fecha vacías en export CSV/PDF.
- Empaquetado para despliegue:
  - Instalador de Windows para la app de escritorio (PyInstaller + Inno
    Setup).
  - Servicio en Windows Server vía Tareas Programadas (`waitress`).
  - Servicio en Linux (Debian/Ubuntu) vía `systemd` + PostgreSQL
    (`deploy/linux_server/install.sh`).

### Seguridad
- Los instaladores/scripts de despliegue nunca incluyen `devices.json`
  real (IPs/números de serie de producción) — siempre se genera un
  archivo vacío (`[]`) en el paquete distribuido.
