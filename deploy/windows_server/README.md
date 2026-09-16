# Despliegue en Windows Server

Instala el panel central bajo `C:\Asistencia`, servido por `waitress`
(WSGI puro Python, corre nativo en Windows a diferencia de `gunicorn`) y
registrado como dos Tareas Programadas de Windows -- sin depender de
herramientas de terceros (NSSM, etc.) que no pude probar en esta sesión.

Probado en esta misma sesión, en esta PC Windows, de punta a punta
(venv, dependencias, base de datos, cuenta de super admin, y el panel
sirviendo peticiones reales vía `waitress`) -- lo único que no pude
probar en vivo es el registro final de las Tareas Programadas, porque
esta sesión no corre con privilegios de Administrador. Esa parte del
script solo necesita permisos, no lógica nueva; si algo falla ahí,
dímelo y lo reviso.

## Requisitos previos

- **Sistema operativo**: Windows Server 2016 o más nuevo (también corre
  igual en Windows 10/11 para pruebas). El script usa `ScheduledTasks`,
  que viene incluido de fábrica en todos ellos.
- **Python 3.10 o superior** instalado en el servidor, con la casilla
  **"Add python.exe to PATH"** marcada durante la instalación --
  descárgalo de [python.org/downloads/windows](https://www.python.org/downloads/windows/).
  El script llama a `python` desde PATH; si no lo encuentra, lo dice y se
  detiene ahí mismo.
- **PowerShell en modo Administrador** ("Ejecutar como administrador") --
  sin esto, el script prepara todo (app, dependencias, base de datos,
  cuenta) pero se detiene antes de dejar el servicio corriendo de verdad
  (ver más abajo).
- **Acceso de red desde el servidor a cada reloj biométrico**, normalmente
  puerto `4370/TCP` -- si hay firewall entre el servidor y las sedes, ese
  puerto tiene que estar abierto en ambos sentidos de la conexión que
  inicia el servidor.
- **Salida a internet** durante la instalación, para que `pip` descargue
  las dependencias de [`central/requirements.txt`](../../central/requirements.txt)
  (Flask, SQLAlchemy, pyzk, etc.). Si el servidor no tiene internet, arma
  antes un *wheelhouse* offline (`pip download -r central\requirements.txt -d wheelhouse`
  desde una máquina que sí lo tenga) y copia esa carpeta al servidor --
  avísame si necesitas que adapte el script para instalar desde ahí.
- **Puerto 5000 libre** en el servidor (el panel escucha ahí por
  defecto) y, si vas a entrar desde otras PCs de la red, una regla de
  entrada abierta en el Firewall de Windows Defender para ese puerto.
- **(Opcional) PostgreSQL o MySQL ya instalado y accesible**, solo si NO
  vas a usar SQLite (ver sección "Base de datos" más abajo). Este script
  no instala el motor de base de datos en Windows.

## Instalación paso a paso

1. **Copia este repositorio al servidor** (clónalo con `git clone
   https://github.com/nucaz/biometric-sincro-zkteco-webapp.git`, o baja
   el ZIP desde GitHub y descomprímelo) -- puede quedar en cualquier
   carpeta temporal, el instalador copia lo necesario a `C:\Asistencia`
   por su cuenta.
2. Abre **PowerShell como Administrador** y entra a la carpeta donde
   quedó el repositorio.
3. Corre el instalador (ver "Uso" abajo). La primera vez, dale también
   `-AdminUser`/`-AdminPassword` para que te deje la cuenta de acceso ya
   creada.
4. Cuando termine, abre `http://localhost:5000` en ese mismo servidor
   (o `http://<IP-del-servidor>:5000` desde otra PC de la red) e inicia
   sesión con la cuenta que creaste.
5. Desde el panel, ve a **Dispositivos → Agregar dispositivo** y carga
   cada reloj (nombre, sede, IP, puerto, y comm key si el equipo la
   tiene configurada) -- o usa "Probar conexión" para confirmar que cada
   uno responde antes de esperar a la sincronización automática.

## Uso (PowerShell como Administrador)

```powershell
.\deploy\windows_server\install.ps1 -AdminUser admin -AdminPassword "clave-fuerte-aqui"
```

Sin `-AdminUser`/`-AdminPassword`, el script te deja el comando exacto
para crear la cuenta después.

## Nombres de las tareas programadas

`install.ps1` registra siempre estas dos, con estos nombres exactos
(los verás así en el Programador de Tareas de Windows):

| Tarea | Qué hace | Se reinicia sola si falla |
|---|---|---|
| `AsistenciaWeb` | Corre el panel web (`waitress`, puerto 5000) permanentemente | Sí -- hasta 999 veces, cada 1 minuto |
| `AsistenciaSync` | Sincroniza los relojes cada 15 minutos | No aplica (corre y termina cada vez) |

## Interruptor de emergencia: iniciar / detener / reiniciar

En `deploy\windows_server\` (dentro de `C:\Asistencia` después de instalar)
hay cuatro `.bat` de doble clic -- piden permisos de administrador solos
cuando hace falta, y siempre imprimen el nombre de la tarea y su estado:

| Archivo | Acción |
|---|---|
| `AsistenciaWeb_Estado.bat` | Muestra el estado de ambas tareas (no pide administrador) |
| `AsistenciaWeb_Iniciar.bat` | Inicia `AsistenciaWeb` si estaba detenida |
| `AsistenciaWeb_Detener.bat` | Detiene `AsistenciaWeb` (para mantenimiento) -- `AsistenciaSync` sigue su horario normal |
| `AsistenciaWeb_Reiniciar.bat` | Detiene y vuelve a iniciar `AsistenciaWeb` -- úsalo después de una actualización o si el panel no responde |

Por detrás, los cuatro llaman a
[`service.ps1`](service.ps1) (`-Action Start|Stop|Restart|Status`), así
que también se puede usar directo desde PowerShell como Administrador:

```powershell
.\deploy\windows_server\service.ps1 -Action Restart
```

Nota: `AsistenciaWeb` ya está configurada para reiniciarse sola (hasta
999 veces, cada 1 minuto) si el proceso se cae solo -- estos botones son
para cuando quieres forzarlo tú (después de actualizar, por ejemplo) o
para pararlo a propósito durante mantenimiento.

Si lo corres SIN privilegios de administrador, prepara todo igual (app,
dependencias, base de datos, cuenta) pero se detiene antes de registrar
las tareas programadas y te lo dice explícitamente -- vuelve a correrlo
elevado para terminar.

## Base de datos

Por defecto usa SQLite (`C:\Asistencia\central\attendance.db`) -- no
necesita instalar nada más, sirve bien para el volumen de este proyecto
(unas pocas sedes). Si prefieres PostgreSQL/MySQL, este script **no
instala el motor** en Windows (a diferencia del script de Linux) -- apunta
`-DatabaseUrl` a una instancia que ya tengas corriendo:

```powershell
.\deploy\windows_server\install.ps1 -DatabaseUrl "postgresql+psycopg2://usuario:clave@servidor:5432/asistencia" -AdminUser admin -AdminPassword "clave-fuerte"
```

## Actualizar

Vuelve a correr el mismo script (como Administrador) después de copiar
el código nuevo -- reinstala dependencias si cambiaron y dejas las
tareas programadas tal cual (`-Force` las reemplaza sin duplicar).
Después:

```powershell
Stop-ScheduledTask -TaskName AsistenciaWeb
Start-ScheduledTask -TaskName AsistenciaWeb
```

## Comandos útiles

```powershell
Get-ScheduledTask -TaskName Asistencia*        # estado de ambas tareas
Get-ScheduledTaskInfo -TaskName AsistenciaWeb  # última corrida, próxima corrida
Stop-ScheduledTask -TaskName AsistenciaWeb
Start-ScheduledTask -TaskName AsistenciaWeb
C:\Asistencia\venv\Scripts\python.exe -m central.sync   # sincronizar a mano
```

## Producción real -- qué falta

- **HTTPS**: igual que en Linux, esto sirve HTTP plano en el puerto
  5000. Si sale fuera de la red interna, ponle un proxy (IIS con
  URL Rewrite, o nginx para Windows) con certificado TLS delante.
- **Backups**: usa `/backup` en el propio panel para un respaldo lógico
  rápido; si usas PostgreSQL, súmale un respaldo del motor aparte.
- **Firewall**: abre el puerto 5000 solo a la red que de verdad lo
  necesita (Firewall de Windows Defender, regla de entrada).
