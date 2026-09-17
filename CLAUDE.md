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

## Estado actual / pendientes

- Último commit en `main`: `3a1ba6a` — "Add device-users and export as
  their own permission modules" (2026-09-17). La pantalla `/permissions`
  ahora tiene 6 módulos: Marcaciones, Exportar marcaciones,
  Dispositivos, Usuarios del dispositivo, Empleados, Sin vincular.
- Funcionalidades ya construidas y en el changelog: sincronización con
  candado cross-proceso + timeout duro, backup/descarga completa de un
  dispositivo antes de vaciarlo, reseteo de contraseña por super admin,
  desactivación de empleado → borra su huella/tarjeta del reloj,
  eliminación de cuentas del panel, gestión del PIN local de usuarios
  del reloj (con fix del bug que lo borraba en silencio), cambio de
  contraseña propia (self-service), sistema de permisos por
  módulo/rol, columna "Todas las marcaciones" en el resumen por día.
- **Sin confirmar por el usuario**: si ya se hizo `git pull` +
  `.\deploy\windows_server\install.ps1` en el servidor de producción
  para los últimos commits (el bloque de Cuentas/Permisos,
  `80947ca`..`3a1ba6a`). Preguntar o recordar el procedimiento si el
  usuario reporta que no ve una función nueva reflejada.
- **Sin confirmar por el usuario**: si el fix de `ommit_ping=True` +
  candado cross-proceso resolvió del todo la intermitencia del equipo
  PISO2 (IP `172.16.1.241` en las pruebas de esta sesión, puede variar
  por entorno) en producción real — se corrigió la causa raíz
  identificada, pero no hay confirmación posterior de que ya no dé
  error en el uso diario.
- No hay tareas a medio hacer ni ramas sin mergear — el árbol de
  trabajo está limpio en `main` y todo lo descrito arriba está
  commiteado y pusheado.

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
