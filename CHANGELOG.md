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
