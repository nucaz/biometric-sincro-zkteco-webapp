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
- La `SECRET_KEY` ya no se regenera en cada actualización del servidor
  (antes cerraba la sesión de todos los usuarios activos).

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
