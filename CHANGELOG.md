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
