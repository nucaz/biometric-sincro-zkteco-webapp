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
- Log de auditoría (`/audit`, solo super admin): conexiones (login, 2FA,
  ping/probar conexión) y cambios (dispositivos, empleados, cuentas,
  backup), con IP y nombre de PC (mejor esfuerzo, por DNS inverso).
- Progreso en vivo al sincronizar (una sola vez o todos los dispositivos):
  ventana con el avance real (conectando, descargando, guardando) y el
  total de registros nuevos al terminar, en vez de un botón "colgado".
- Botón "Vaciar dispositivo": borra las marcaciones guardadas en el reloj
  físico para que empiece de cero, sin tocar el historial ya sincronizado
  en la base central. Pide escribir el nombre del equipo para confirmar.
- Bloqueo de cuenta tras 3 intentos fallidos de inicio de sesión seguidos
  -- solo un super administrador puede desbloquearla, desde Cuentas.
- Interruptores de emergencia (`.bat`) para iniciar/detener/reiniciar el
  servicio en Windows Server, con el nombre exacto de cada tarea.
- Guías de instalación ilustradas en PDF (Windows/Linux) y diagrama de
  arquitectura para draw.io.
- Flujo de release versionado por tags de Git + GitHub Actions.

### Corregido
- Sincronización que fallaba con "TCP packet invalid" en dispositivos con
  transferencias grandes o de red inestable: ahora reintenta hasta 3
  veces con timeout ampliado, y una falla al desconectar ya no tapa el
  error real ni aborta la sincronización completa.
- La ventana de progreso de sincronización se quedaba trancada sin forma
  de cerrarla ni mostrar ningún avance (se basaba en una conexión larga
  tipo Server-Sent Events, y algo entre el servidor y el navegador podía
  retener el primer mensaje indefinidamente). Reemplazada por un diseño
  mucho más simple y robusto: la sincronización corre como un trabajo en
  segundo plano con un identificador, y el navegador consulta su estado
  cada segundo con peticiones cortas normales -- "Cerrar" ya no depende
  de ninguna conexión, siempre funciona al instante. También se
  aumentaron los hilos del servidor (waitress/gunicorn) para que una
  sincronización lenta no deje el resto de la aplicación sin responder.
- La `SECRET_KEY` ya no se regenera en cada actualización del servidor
  (antes cerraba la sesión de todos los usuarios activos).
- Una sincronización podía quedar corriendo en el servidor sin límite si
  el dispositivo se colgaba a nivel de socket más allá de su propio
  timeout configurado (visto de verdad contra un K20 real) -- ahora hay
  un tope duro de 150s por trabajo: siempre termina en "listo" o "error",
  nunca se queda en "corriendo" para siempre.
- El log de auditoría mostraba la hora en UTC en vez de la hora local del
  servidor (5 horas de diferencia con Perú) -- ahora usa la hora local,
  igual que el resto de la aplicación.
- La sincronización automática pasó de cada 15 minutos a una vez por
  noche (23:00 por defecto, configurable con `-SyncTime` en
  `install.ps1`) -- los botones "Sincronizar" del panel siguen
  funcionando al instante cuando se necesite durante el día.
- "Eliminar" un dispositivo borraba también todo su historial de
  marcaciones si se forzaba -- ahora nunca lo hace: solo lo oculta de la
  lista y de la sincronización, con un botón "Restaurar" para traerlo de
  vuelta.
- **Bug crítico de actualización en Windows Server**: `install.ps1` nunca
  detenía el proceso que ya estaba corriendo antes de "iniciarlo" de
  nuevo -- y `Start-ScheduledTask` sobre una tarea ya activa no hace nada
  en Windows. Resultado: cada actualización cambiaba los archivos en
  disco, pero el servicio seguía sirviendo el código viejo hasta que
  alguien lo reiniciara por separado a mano. Corregido para que
  `install.ps1` (y el botón "Reiniciar") siempre detengan el proceso
  -- incluso forzándolo si quedó colgado en una llamada de red -- antes
  de volver a levantarlo.

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
