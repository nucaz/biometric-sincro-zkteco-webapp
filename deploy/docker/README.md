# Despliegue con Docker (Windows o Ubuntu)

Tres contenedores, el mismo `docker-compose.yml` en ambos sistemas
operativos -- a diferencia de `deploy/windows_server/` (tarea programada)
y `deploy/linux_server/` (systemd), que son dos caminos nativos distintos
que hay que mantener por separado:

- **`db`**: PostgreSQL 16 oficial, con los datos en un volumen con nombre
  (sobrevive a `docker compose down`, solo se borra con
  `docker compose down -v`).
- **`web`**: el panel (`central.webapp:app` con `gunicorn`), puerto 5000.
- **`sync`**: el mismo código, corriendo `central/sync_loop.py` en vez
  del panel -- reemplaza al timer de systemd / la tarea programada de
  Windows, que no existen dentro de un contenedor. Ver el propio archivo
  para el horario configurable.

## Instalación automática (recomendada)

`deploy/docker/install.ps1` (Windows) / `deploy/docker/install.sh`
(Linux/Ubuntu) hacen todo lo de abajo por vos, siempre preguntando los
datos en pantalla (nunca instalan con valores por defecto en silencio):
elegir si esta máquina es el **servidor central** o un **agente
remoto**, pedir usuario/contraseña de la base de datos (o generarla
automática si dejás el campo vacío), el puerto del panel, la hora de
sincronización y la primera cuenta de super administrador; al final
levantan los contenedores con `docker compose up -d --build` y dejan un
archivo `instalacion_<fecha>.txt` en esta misma carpeta con un resumen
de todo lo que se ingresó (incluidas las contraseñas -- bórralo o
muévalo a un lugar seguro una vez que lo hayas guardado).

```powershell
# Windows -- o doble clic en AsistenciaDocker_Instalar.bat
.\deploy\docker\install.ps1
```

```bash
# Linux/Ubuntu
./deploy/docker/install.sh
```

Para administrar el servicio después de instalado (Windows, doble clic;
Linux, línea de comandos):

```
AsistenciaDocker_Iniciar.bat / _Detener.bat / _Reiniciar.bat / _Estado.bat / _Diagnostico.bat
./deploy/docker/manage.sh {start|stop|restart|status|diagnose}
```

`diagnose`/`_Diagnostico.bat` revisa que Docker responda, el estado de
cada contenedor, las últimas líneas de log de cada uno, que PostgreSQL
acepte conexiones y que el panel responda por HTTP (solo en modo
central) -- pensado para cuando alguien reporta "no funciona" y hay que
saber por dónde empezar sin memorizar comandos de `docker compose`.

**A diferencia de los `.bat` de `deploy\windows_server\`, estos NO se
auto-elevan a Administrador** -- Docker Desktop corre con la sesión del
usuario que inició sesión, y abrir una consola elevada aparte puede
terminar hablando con un Docker Desktop distinto (o con ninguno).

## Instalación manual (para quien prefiera no usar el instalador)

```bash
cp .env.example .env
# edita .env: POSTGRES_PASSWORD y SECRET_KEY como mínimo

docker compose up -d --build
docker compose exec web python -m central.create_admin admin "clave-fuerte-aqui"
```

Abre `http://localhost:5000` (o el `WEB_PORT` que hayas puesto en `.env`).

## Actualizar a una versión nueva del código

```bash
git pull
docker compose up -d --build
```

Los cambios de esquema (tablas/columnas nuevas) se aplican solos al
arrancar `web` o `sync` -- ver `init_db()` en `central/db.py`, mismo
mecanismo que ya usan los despliegues nativos.

## Logs y comandos útiles

```bash
docker compose logs -f web
docker compose logs -f sync
docker compose exec web python -m central.sync          # sincronizar ahora, a mano
docker compose exec db pg_dump -U asistencia asistencia > respaldo.sql   # backup completo
docker compose down                                      # detiene todo, conserva los datos
```

## Lo único que de verdad cambia entre Windows y Ubuntu: llegar a los relojes

El panel y la sincronización necesitan alcanzar los biométricos en tu red
local (ej. `172.16.1.25:4370`) desde DENTRO del contenedor. Por defecto
Docker Compose pone a `web`/`sync` en una red *bridge* propia, con salida
a internet/LAN igual que cualquier conexión saliente del host -- esto
suele funcionar sin tocar nada, tanto con Docker Desktop (Windows) como
con Docker Engine (Ubuntu).

**Verificado en esta sesión**: con la red *bridge* por defecto (sin tocar
nada), un contenedor `web` corriendo con Docker Desktop en Windows se
conectó sin problema al PISO2 real (`172.16.1.25:4370`) y leyó su número
de serie -- así que para el caso normal no hace falta ningún ajuste.

Si un dispositivo deja de verse SOLO desde dentro del contenedor (pero sí
responde si corres `python -m central.sync` fuera de Docker, en el mismo
servidor), la causa casi siempre es una red corporativa restrictiva que
filtra tráfico que no sale directo de la IP del host. La solución en ese
caso, **solo en Linux** (no existe en Docker Desktop/Windows):

```yaml
# en docker-compose.yml, servicio `sync` (y `web` si hace falta):
network_mode: host
```

Esto saca al contenedor de la red *bridge* y lo pone a usar la red del
host directamente -- mismo comportamiento de red que el despliegue nativo
de `deploy/linux_server/`. No se ha necesitado todavía en las pruebas de
esta sesión (hechas contra un reloj real alcanzable desde el host), así
que queda documentado por si hace falta, no aplicado por defecto.

## Migrar los datos reales desde SQLite (Windows de producción)

Esto es un paso aparte, todavía no construido -- ver `CLAUDE.md` /
`CHANGELOG.md` para el estado de ese trabajo. Hasta entonces, Docker y la
instalación nativa de Windows pueden convivir: no hay nada que te obligue
a migrar los datos existentes antes de probar Docker con una base nueva.

## Integración con la app de planillas/tareo

Ya existe: `/api/v1/...` (autenticación por token, no por sesión de
navegador) corre dentro del mismo contenedor `web`, sin servicio aparte.
Crea un token desde el panel en **API** (solo super admin) -- ver
`central/api.py` para las rutas disponibles.

## Agente remoto (sedes detrás de otra VPN)

**Requisito previo, antes de tocar la PC remota**: el servidor CENTRAL
tiene que estar corriendo de verdad con este `docker-compose.yml` (no
la instalación nativa de Windows con SQLite) -- el agente remoto se
conecta por VPN al puerto 5432 de un PostgreSQL que solo existe en el
despliegue Docker. Si el servidor central todavía usa SQLite (la
instalación de `deploy\windows_server\`), un `Test-NetConnection` desde
la sede remota va a mostrar `PingSucceeded: True` (la VPN funciona) pero
`TcpTestSucceeded: False` (no hay nada escuchando en 5432 todavía) --
visto de verdad en esta sesión, no es un problema de VPN ni de firewall,
es que falta este paso.

Una vez que la central corre con Docker:

1. El servicio `db` publica `POSTGRES_PORT` (5432 por defecto) en el
   host -- lo hace `docker-compose.yml` solo, sin nada que tocar.
2. En el servidor central (Windows), hay que abrir ese puerto en el
   Firewall de Windows para que acepte conexiones entrantes desde la IP
   de la VPN (Docker Desktop no abre esto solo para conexiones que
   lleguen de OTRA máquina, a diferencia de `localhost`):
   ```powershell
   New-NetFirewallRule -DisplayName "Asistencia - PostgreSQL (agentes remotos)" `
       -Direction Inbound -Protocol TCP -LocalPort 5432 -Action Allow
   ```
3. Recién ahí, desde la PC remota, `Test-NetConnection -ComputerName
   <IP-VPN-de-la-central> -Port 5432` debería dar `TcpTestSucceeded:
   True`.

Para una sede cuyos biométricos este servidor no puede alcanzar
directo, pero cuyo propio servidor SÍ llega a la base central por VPN
(puerto 5432 de Postgres): clona este mismo repositorio ahí y corre el
instalador en modo "Agente remoto" (opción 2 al preguntar):

```powershell
# Windows -- o doble clic en AsistenciaDocker_Instalar.bat
.\deploy\docker\install.ps1
```

```bash
./deploy/docker/install.sh   # Linux/Ubuntu
```

Te va a pedir el nombre de este agente y los datos de conexión a la
base central (host, puerto, usuario, contraseña, nombre de base) --
arma el `DATABASE_URL` y levanta `deploy/docker/docker-compose.agent.yml`
(un solo servicio, sin Postgres propio) por vos. Si preferís armarlo a
mano, el archivo queda documentado ahí mismo.

Luego, en **Dispositivos** (en el panel central), edita cada equipo de
esa sede y pon `sede-remota-1` en "Agente remoto" -- debe coincidir
EXACTO con `AGENT_NAME`. Desde ahí, ese dispositivo se sincroniza solo
desde el agente (no desde la central, que nunca podría alcanzarlo), y
"Probar conexión" se ejecuta a través del agente en vez de conectar
directo -- **el resto de las acciones de dispositivo (Reiniciar,
Apagar, Vaciar, gestión de Usuarios) todavía NO soportan el puente
remoto** -- ver CLAUDE.md para el estado exacto de ese trabajo pendiente.

**Probado en esta sesión** contra el PISO2 real: un proceso "central"
encoló el comando, un segundo proceso actuando como agente remoto lo
tomó, se conectó de verdad al reloj, y el resultado (modelo/serie)
volvió a la central correctamente -- incluyendo que una acción NO
retrofitteada todavía (ej. Reiniciar) sobre un dispositivo remoto falla
al instante con un mensaje claro, en vez de intentar una conexión
directa que nunca iba a funcionar.
