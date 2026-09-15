# Despliegue en servidor Linux (Debian/Ubuntu)

Instala el panel central (`central/webapp.py`) como servicio permanente
con `systemd`, PostgreSQL como base de datos, y la sincronización
(`central/sync.py`) corriendo sola cada 15 minutos vía un timer de
`systemd` (no cron, mismo resultado, mejor integrado con logs).

**No probado en un servidor real todavía** -- esta sesión corre en tu PC
Windows, así que no hay una máquina Linux a mano para ejecutarlo en vivo.
Está escrito con cuidado y revisado (sintaxis validada con `bash -n`),
pero la primera corrida en tu servidor real es la prueba de verdad.
Avísame el resultado y ajusto lo que haga falta.

## Uso

```bash
# 1. Copia todo el proyecto al servidor (scp, rsync, git clone -- lo que tengas)
# 2. Desde la raíz del proyecto ya copiada:
sudo ADMIN_USER=admin ADMIN_PASSWORD='clave-fuerte-aqui' ./deploy/linux_server/install.sh
```

Si omites `ADMIN_USER`/`ADMIN_PASSWORD`, el script te deja el comando
exacto para crear la cuenta después a mano.

Es seguro volver a correrlo (cada paso revisa si ya se hizo). Por ejemplo,
para llevar una actualización de código: copia los archivos nuevos sobre
el proyecto, y vuelve a correr `install.sh` -- reinstala dependencias si
cambiaron y reinicia el servicio via `systemctl`.

## Sin internet / sin acceso a un repositorio

Este instalador necesita `apt-get` y `pip` con internet la primera vez
(para el propio motor de PostgreSQL, que no tiene sentido "vendorizar" --
es un paquete del sistema operativo, no una librería Python). Si el
servidor de verdad no tiene salida a internet:

1. **Opción simple: usa SQLite en vez de PostgreSQL.** No es un servicio
   de sistema, es solo un archivo -- no necesita instalar nada. Omite el
   bloque de PostgreSQL del script (o simplemente no definas
   `DATABASE_URL` en `central.env`; `central/db.py` ya usa SQLite por
   defecto). Para lo que maneja este proyecto (unas pocas sedes, no
   millones de registros por día) SQLite aguanta perfectamente.
2. **Opción completa: arma un "wheelhouse" offline.** En una máquina CON
   internet (puede ser esta misma PC Windows con WSL, o cualquier Linux):
   ```bash
   pip download -r central/requirements.txt -d vendor_wheels/
   ```
   Copia la carpeta `vendor_wheels/` al servidor sin internet junto con
   el proyecto, y en el servidor instala con:
   ```bash
   pip install --no-index --find-links=vendor_wheels/ -r central/requirements.txt
   ```
   El propio PostgreSQL como programa seguiría necesitando su `.deb`
   descargado aparte (`apt-get download postgresql postgresql-contrib` en
   la máquina con internet, y `dpkg -i` en el servidor) -- o usa la
   Opción 1 (SQLite) y te ahorras todo esto.

## Actualizar la app en el servidor

```bash
# Copia el código nuevo (git pull, scp, lo que uses) y luego:
sudo ./deploy/linux_server/install.sh   # reinstala dependencias si cambiaron
sudo systemctl restart asistencia-web
```

La base de datos no se toca al actualizar código -- solo cambian los
archivos Python y se reinicia el proceso.

## Producción real -- qué falta

- **HTTPS**: `gunicorn` sirve HTTP plano en el puerto 5000. Si esto se
  expone fuera de la red interna, pon `nginx` o `caddy` delante como
  proxy con certificado TLS (Let's Encrypt es gratis con `certbot`).
- **Backups**: usa el backup JSON del propio panel (`/backup`) para un
  respaldo lógico rápido, y además `pg_dump` regular de PostgreSQL para
  un respaldo completo del motor.
- **Firewall**: si el puerto 5000 no necesita ser público, restringe con
  `ufw` a la red interna.

## Comandos útiles

```bash
journalctl -u asistencia-web -f       # logs del panel web en vivo
journalctl -u asistencia-sync -f      # logs de la última sincronización
systemctl list-timers asistencia-sync.timer   # cuándo corre la próxima
sudo systemctl restart asistencia-web
sudo -u asistencia bash -c "cd /opt/asistencia && source central.env && venv/bin/python -m central.sync"  # sync manual
```
