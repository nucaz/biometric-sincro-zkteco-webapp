#!/usr/bin/env bash
# Installs the central attendance service (Flask app + sync job) on a
# Debian/Ubuntu server: system packages, PostgreSQL, a Python venv, the
# app itself under /opt, and two systemd units (web service + a timer
# that runs the sync periodically).
#
# Needs internet access to apt-get and pip (there is no way to install a
# real PostgreSQL *server* package with zero network access -- if this
# box truly has none, see the "Sin internet / sin acceso al repo" section
# in deploy/linux_server/README.md for the SQLite-only fallback instead).
#
# Usage (as root, or with sudo):
#   sudo ./deploy/linux_server/install.sh
#
# Safe to re-run: every step checks whether it already did its job.
set -euo pipefail

APP_DIR="/opt/asistencia"
SERVICE_USER="asistencia"
DB_NAME="asistencia"
DB_USER="asistencia"
DOMAIN_OR_IP="${DOMAIN_OR_IP:-localhost}"

log() { echo -e "\n\033[1;36m==> $*\033[0m"; }

if [ "$(id -u)" -ne 0 ]; then
    echo "Corre esto como root (sudo ./install.sh)." >&2
    exit 1
fi

if ! command -v apt-get >/dev/null 2>&1; then
    echo "Este script asume Debian/Ubuntu (apt-get). En RHEL/CentOS/Fedora," >&2
    echo "instala manualmente los equivalentes con dnf/yum: python3, python3-venv," >&2
    echo "postgresql-server, y sigue el resto de los pasos de este script a mano." >&2
    exit 1
fi

log "Instalando paquetes del sistema (python3, venv, postgresql)..."
apt-get update -y
apt-get install -y python3 python3-venv python3-pip postgresql postgresql-contrib rsync

log "Creando usuario de servicio '$SERVICE_USER' (sin login)..."
id -u "$SERVICE_USER" >/dev/null 2>&1 || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"

log "Copiando la aplicación a $APP_DIR..."
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
mkdir -p "$APP_DIR"
# devices.json excluded on purpose: it's the developer's own local device
# list (real IPs/serials) -- never something to ship to a server.
rsync -a --exclude 'venv' --exclude '__pycache__' --exclude 'dist' --exclude 'dist_installer' \
      --exclude 'build' --exclude 'central/attendance.db' --exclude 'devices.json' \
      "$SOURCE_DIR"/ "$APP_DIR"/
[ -f "$APP_DIR/devices.json" ] || echo "[]" > "$APP_DIR/devices.json"

log "Configurando PostgreSQL (base '$DB_NAME', usuario '$DB_USER')..."
DB_PASSWORD_FILE="$APP_DIR/.db_password"
if [ ! -f "$DB_PASSWORD_FILE" ]; then
    DB_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
    echo "$DB_PASSWORD" > "$DB_PASSWORD_FILE"
    chmod 600 "$DB_PASSWORD_FILE"
else
    DB_PASSWORD="$(cat "$DB_PASSWORD_FILE")"
fi
sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" | grep -q 1 || \
    sudo -u postgres psql -c "CREATE ROLE $DB_USER LOGIN PASSWORD '$DB_PASSWORD';"
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1 || \
    sudo -u postgres psql -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;"

DATABASE_URL="postgresql+psycopg2://$DB_USER:$DB_PASSWORD@localhost:5432/$DB_NAME"

log "Creando entorno virtual e instalando dependencias..."
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip -q
"$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/central/requirements.txt"

log "Escribiendo configuración de entorno..."
if [ -f "$APP_DIR/central.env" ]; then
    # Preserve the existing SECRET_KEY on updates -- regenerating it on
    # every run would silently invalidate every logged-in session (Flask
    # signs the session cookie with it) each time this script re-runs.
    echo "central.env ya existe -- se conserva (evita invalidar sesiones activas)."
else
    cat > "$APP_DIR/central.env" <<EOF
DATABASE_URL=$DATABASE_URL
SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
EOF
    chmod 600 "$APP_DIR/central.env"
fi

chown -R "$SERVICE_USER":"$SERVICE_USER" "$APP_DIR"

log "Inicializando la base de datos..."
sudo -u "$SERVICE_USER" bash -c "cd '$APP_DIR' && set -a && source central.env && set +a && venv/bin/python -m central.seed_devices" || true

if [ -n "${ADMIN_USER:-}" ] && [ -n "${ADMIN_PASSWORD:-}" ]; then
    log "Creando cuenta de super administrador '$ADMIN_USER' (desde variables de entorno)..."
    sudo -u "$SERVICE_USER" bash -c "cd '$APP_DIR' && set -a && source central.env && set +a && venv/bin/python -m central.create_admin '$ADMIN_USER' '$ADMIN_PASSWORD'"
else
    echo ""
    echo "No definiste ADMIN_USER / ADMIN_PASSWORD -- crea la primera cuenta a mano:"
    echo "  sudo -u $SERVICE_USER bash -c \"cd $APP_DIR && source central.env && venv/bin/python -m central.create_admin admin TU_CLAVE\""
fi

log "Instalando servicios systemd..."
cp "$SOURCE_DIR/deploy/linux_server/asistencia-web.service" /etc/systemd/system/
cp "$SOURCE_DIR/deploy/linux_server/asistencia-sync.service" /etc/systemd/system/
cp "$SOURCE_DIR/deploy/linux_server/asistencia-sync.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now asistencia-web.service
systemctl enable --now asistencia-sync.timer

log "Listo."
echo "Panel web: http://$DOMAIN_OR_IP:5000"
echo "Logs del servicio web:  journalctl -u asistencia-web -f"
echo "Logs de sincronización: journalctl -u asistencia-sync -f"
echo "Próxima sincronización: systemctl list-timers asistencia-sync.timer"
echo ""
echo "IMPORTANTE: esto sirve en HTTP plano en el puerto 5000. Si vas a exponerlo"
echo "fuera de la red interna, pon un proxy (nginx/caddy) delante con TLS --"
echo "ver deploy/linux_server/README.md."
