# Sistema de Asistencia ZKTeco (multi-sede)

Plataforma para consolidar las marcaciones de varios relojes biométricos
ZKTeco (distintas sedes) en un solo panel central, más la app de escritorio
original para conexión directa y puntual a un equipo.

- **App de escritorio** (`attendance_gui.py`): se conecta directo a UN
  reloj por IP para consultar/exportar marcaciones, administrar usuarios del
  equipo, hacer ping y reiniciarlo. Pensada para uso puntual desde una PC.
- **Panel web central** (`central/`): un servicio Flask que sincroniza
  TODOS los relojes configurados a una sola base de datos, con dashboard de
  RRHH, gestión de empleados, roles de acceso y 2FA. Pensado para correr
  como servicio permanente en un servidor.

Ambas comparten la misma capa de conexión al dispositivo
(`attendance_system.py`, sobre [`pyzk`](https://github.com/fananimi/pyzk)),
así que lo que funciona en una funciona en la otra.

## Cómo funciona la conexión al reloj

Los relojes ZKTeco de esta familia (probado con K20 real, protocolo
genérico a ZK30/ZKG3) se manejan por TCP/UDP directo, **sin ADMS/push** —
o sea, es el software el que se conecta al reloj a pedir datos, el reloj no
avisa nada por sí solo. Para eso necesitas:

- **IP y puerto** del equipo (el puerto por defecto de fábrica es `4370`).
- **Comm Key** (clave de comunicación), si el equipo la tiene configurada
  en su menú — si no, se deja en `0`.
- **Device Number** (número de dispositivo), informativo, tal como aparece
  en el menú de red del propio reloj.

El botón **"Probar conexión"** (tanto en la app de escritorio como en el
panel web) confirma que el equipo responde y captura su **modelo y número
de serie reales** — el panel usa ese serial (cuando existe) como identidad
estable del dispositivo en la base de datos, para que renombrarlo o
cambiarle la IP después nunca desconecte su historial de marcaciones ya
guardado.

### Por qué el ID de usuario del reloj no basta

El ID de un empleado en el Reloj A (ej. "5") no tiene relación con el ID
"5" en el Reloj B — son numeraciones internas independientes de cada
equipo. El panel central resuelve esto con una tabla de vínculos
(`employee_map`) que conecta el par `(dispositivo, id-en-ese-dispositivo)`
con un empleado único del maestro central (por Código/DNI). Si el mismo
empleado está enrolado en varias sedes, cada sede tiene su propio vínculo
apuntando al mismo empleado — así el dashboard muestra su nombre real y su
historial completo sin importar en qué reloj marcó.

## App de escritorio

Conexión directa a un reloj para trabajo puntual:

- Ver, filtrar por fecha y exportar marcaciones (CSV/Excel/PDF), con
  agrupación automática entrada/salida y cálculo de horas.
- Administrar los usuarios enrolados en ESE equipo (alta/edición/baja),
  detección de modelo/serie, Ping y Reiniciar el equipo remotamente.
- Se distribuye como instalador de Windows (`.exe`) — ver
  [`deploy/windows_desktop/`](deploy/windows_desktop/README.md).

## Panel web central

- **Marcaciones**: filtra por sede/dispositivo/fecha/nombre, vista resumen
  por día o marcaciones crudas, exporta a CSV, Excel (con estilo y
  auto-ancho) o PDF (con encabezado y paginación).
- **Dispositivos**: tarjetas por equipo con Editar, Usuarios, Probar
  conexión, Ping, Sincronizar (uno o todos), Reiniciar, Apagar y Eliminar.
- **Usuarios de un dispositivo**: quién está enrolado en ese reloj físico,
  con alta/edición/baja que escribe directo en el equipo (no puede
  registrar la huella de forma remota — eso sigue siendo físico).
- **Empleados**: maestro central con importación desde Excel, alta
  individual, y vinculación con auto-sugerencia cuando el Código/DNI ya
  coincide con un usuario existente en algún reloj.
- **Cuentas y roles** (solo super admin): crea usuarios del panel con el
  rol que corresponda.
- **Backup**: exporta/importa toda la base de datos en un JSON portable
  (sirve igual si es SQLite, PostgreSQL o MySQL).

### Roles de acceso

| Rol | Puede |
|---|---|
| `viewer` (solo lectura) | Ver marcaciones y dispositivos, exportar (CSV/Excel/PDF). Nada de escritura. |
| `admin` | Todo lo de `viewer` + agregar/editar/reiniciar dispositivos, gestionar empleados y usuarios del reloj. |
| `super_admin` | Todo lo de `admin` + cuentas del panel y backup/restore. |

### Doble autenticación (2FA)

Cada usuario del panel puede activar 2FA desde **Cuenta → Seguridad**:
escanea un código QR con cualquier app TOTP (Google Authenticator, Authy,
etc.) y a partir de ahí el login pide, además de la clave, el código de 6
dígitos. Si el usuario siempre entra desde la misma PC/navegador, puede
marcar "Recordar este equipo" — la próxima vez no le vuelve a pedir el
código (se guarda un token propio en una cookie, nunca la clave ni el
secreto TOTP). Un super admin puede resetear el 2FA de otro usuario si
pierde el celular.

## Instalación

### Windows — instalador de la app de escritorio

Para dar la app de escritorio a alguien que solo necesita conectarse a un
reloj puntualmente, sin instalar Python: usa el instalador ya compilado
(`ZKTecoAttendanceSystem_Setup_X.Y.Z.0.exe`, generado con PyInstaller +
Inno Setup). Detalles de cómo generarlo/actualizarlo en
[`deploy/windows_desktop/README.md`](deploy/windows_desktop/README.md).

### Windows Server — panel web central

```powershell
.\deploy\windows_server\install.ps1 -AdminUser admin -AdminPassword "clave-fuerte-aqui"
```

Corre como servicio vía Tareas Programadas de Windows (sin depender de
herramientas de terceros), servido por `waitress`. Usa SQLite por defecto
o `-DatabaseUrl` para apuntar a PostgreSQL/MySQL ya existente. Debe
correrse como Administrador para que registre las tareas. Detalles en
[`deploy/windows_server/README.md`](deploy/windows_server/README.md).

### Linux Server (Debian/Ubuntu) — panel web central

```bash
sudo ./deploy/linux_server/install.sh
```

Instala PostgreSQL, crea el entorno virtual, descarga dependencias y deja
el panel corriendo como servicio `systemd` (con un timer que sincroniza
los dispositivos cada 15 minutos). Detalles en
[`deploy/linux_server/README.md`](deploy/linux_server/README.md).

### Desarrollo local (cualquier SO, SQLite, cero configuración)

```bash
pip install -r central/requirements.txt
python -m central.seed_devices               # importa devices.json
python -m central.create_admin admin TU_CLAVE # primera cuenta de acceso
python -m central.sync                        # primera sincronización manual
python -m central.webapp                      # abre http://localhost:5000
```

Ver más detalle técnico del panel (esquema de datos, automatización del
sync, cómo agregar un dispositivo nuevo) en
[`central/README.md`](central/README.md).

### Guías ilustradas y diagrama de arquitectura

- [`deploy/docs/instalacion_windows_server.pdf`](deploy/docs/instalacion_windows_server.pdf)
- [`deploy/docs/instalacion_linux_server.pdf`](deploy/docs/instalacion_linux_server.pdf)
- [`deploy/docs/architecture.drawio`](deploy/docs/architecture.drawio) --
  ábrelo en [app.diagrams.net](https://app.diagrams.net) para ver/editar el
  diagrama completo (relojes -> sincronización -> base de datos -> panel
  web -> navegador).

## Estructura del repositorio

```
├── attendance_gui.py          # App de escritorio (Tkinter)
├── attendance_system.py       # Capa de conexión al dispositivo (compartida)
├── requirements.txt           # Dependencias de la app de escritorio
├── VERSION                    # Versión del instalador de escritorio
├── central/                   # Panel web (Flask) + sincronización multi-dispositivo
│   ├── webapp.py               # Rutas del dashboard
│   ├── models.py                # Esquema de base de datos
│   ├── sync.py                  # Sincronización periódica
│   └── requirements.txt        # Dependencias del panel (incluye las de arriba)
└── deploy/                    # Empaquetado e instaladores
    ├── windows_desktop/        # Instalador .exe de la app de escritorio
    ├── windows_server/         # Instalación como servicio en Windows Server
    └── linux_server/           # Instalación como servicio en Linux (systemd)
```

## Actualizar la aplicación

Los usuarios finales nunca reciben el código fuente. La única forma de
sacar una versión nueva es editar el código de este repositorio y volver a
correr el script de build correspondiente:

- **App de escritorio**: sube `VERSION` y corre
  `.\deploy\windows_desktop\build.ps1` — genera un instalador nuevo para
  redistribuir.
- **Panel web**: copia el código actualizado al servidor y vuelve a
  correr `install.ps1` / `install.sh` — reinstala dependencias si
  cambiaron y reinicia el servicio.

## Licencia

MIT — ver [LICENSE](LICENSE).

---
Develop Juan Carlos Aguirre Alvarado - Infraestructura TI & Ciberseguridad Apps
