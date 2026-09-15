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

## Uso (PowerShell como Administrador)

```powershell
.\deploy\windows_server\install.ps1 -AdminUser admin -AdminPassword "clave-fuerte-aqui"
```

Sin `-AdminUser`/`-AdminPassword`, el script te deja el comando exacto
para crear la cuenta después.

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
