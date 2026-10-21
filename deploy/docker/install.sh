#!/usr/bin/env bash
# Instalador interactivo del despliegue con Docker (Linux/Ubuntu), para
# servidor central (web + sync + Postgres) o agente remoto (puente hacia
# biométricos de una sede que la central no puede alcanzar directo).
#
# Pide SIEMPRE, por pantalla, los datos de conexión y credenciales (nunca
# asume valores por defecto en silencio) -- a propósito, para que cada
# instalación quede con sus propias claves y quede un registro de qué se
# ingresó. Usa "read -p" normal (sin -s) para las contraseñas, igual que
# el install.ps1 de Windows -- por simetría entre ambos scripts y porque
# ya existe el mismo precedente en deploy/windows_server/install.ps1
# (recibe la clave del admin en texto plano por parámetro).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
MARKER_FILE="$SCRIPT_DIR/.deploy_mode"

prompt_with_default() {
    local label="$1" default="$2" value
    read -r -p "$label [$default]: " value || true
    echo "${value:-$default}"
}

prompt_required() {
    local label="$1" value
    while true; do
        read -r -p "$label: " value || true
        if [ -n "$value" ]; then
            echo "$value"
            return
        fi
        echo "Este dato es obligatorio, no puede quedar en blanco." >&2
    done
}

random_secret() {
    openssl rand -base64 32
}

urlencode() {
    # Codifica para armar un DATABASE_URL (RFC 3986) -- sin esto, un
    # "@"/":" sin codificar dentro de un usuario/contraseña tipeado a
    # mano rompe la URL en silencio (visto de verdad en
    # install_agente_remoto.ps1, la versión de Windows, esta sesión).
    local string="$1" length="${#1}" c o
    for (( pos=0; pos<length; pos++ )); do
        c="${string:$pos:1}"
        case "$c" in
            [-_.~a-zA-Z0-9]) o="$c" ;;
            *) printf -v o '%%%02X' "'$c" ;;
        esac
        printf '%s' "$o"
    done
}

read_existing_env_value() {
    # Nunca falla (sale con 0 e imprime "" si no hay nada que encontrar) --
    # a propósito, porque "if [ -f ... ]; then ...; fi" sin "else" devuelve
    # 0 igual cuando la condición es falsa, así que un "||" en el llamador
    # para poner un default NUNCA se activa (bug real encontrado en esta
    # sesión: con el .env recién creado, POSTGRES_USER/POSTGRES_DB/
    # SYNC_DAILY_AT quedaban vacíos en vez de "asistencia"/"23:00"). Los
    # llamadores deben usar "${valor:-default}" sobre el resultado, no "||".
    local path="$1" key="$2" val=""
    if [ -f "$path" ]; then
        val="$(grep -E "^${key}=" "$path" | tail -n1 | cut -d'=' -f2-)" || true
    fi
    echo "$val"
}

echo "=== Instalador Docker - Asistencia biométrica ==="
echo ""

if ! command -v docker >/dev/null 2>&1; then
    echo "docker no está instalado. Instala Docker Engine (https://docs.docker.com/engine/install/) y vuelve a correr este script." >&2
    exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
    echo "'docker compose' no respondió -- ¿el servicio de Docker está corriendo? (sudo systemctl status docker)" >&2
    exit 1
fi

echo "¿Qué vas a instalar en esta máquina?"
echo "  1) Servidor central (panel web + sincronización + base de datos)"
echo "  2) Agente remoto (puente hacia biométricos de una sede, sin panel ni base propia)"
mode_choice=""
while [ "$mode_choice" != "1" ] && [ "$mode_choice" != "2" ]; do
    read -r -p "Elige 1 o 2: " mode_choice || true
done
if [ "$mode_choice" = "1" ]; then
    MODE="central"
else
    MODE="agent"
fi
echo "$MODE" > "$MARKER_FILE"
echo ""

LOG_FILE="$SCRIPT_DIR/instalacion_$(date +%Y%m%d_%H%M%S).txt"
{
    echo "Resumen de instalación -- Asistencia biométrica (Docker)"
    echo "============================================================"
    echo "ADVERTENCIA: este archivo contiene contraseñas en texto plano."
    echo "Guárdalo en un lugar seguro (ej. un gestor de contraseñas) y"
    echo "luego BÓRRALO de esta carpeta -- no lo dejes junto al código."
    echo ""
    echo "Fecha de instalación: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "Modo: $([ "$MODE" = "central" ] && echo "Servidor central" || echo "Agente remoto")"
    echo "Carpeta del repositorio: $REPO_ROOT"
} > "$LOG_FILE"
chmod 600 "$LOG_FILE"

if [ "$MODE" = "central" ]; then
    ENV_PATH="$REPO_ROOT/.env"

    echo "--- Datos de la base de datos (PostgreSQL) ---"
    _existing_pg_user="$(read_existing_env_value "$ENV_PATH" POSTGRES_USER)"
    PG_USER=$(prompt_with_default "Usuario de la base de datos" "${_existing_pg_user:-asistencia}")
    _existing_pg_db="$(read_existing_env_value "$ENV_PATH" POSTGRES_DB)"
    PG_DB=$(prompt_with_default "Nombre de la base de datos" "${_existing_pg_db:-asistencia}")
    read -r -p "Contraseña de la base de datos (Enter para generar una automática): " PG_PASSWORD || true
    if [ -z "$PG_PASSWORD" ]; then PG_PASSWORD=$(random_secret); fi

    echo ""
    echo "--- Datos del panel web ---"
    _existing_web_port="$(read_existing_env_value "$ENV_PATH" WEB_PORT)"
    WEB_PORT=$(prompt_with_default "Puerto donde se publica el panel" "${_existing_web_port:-5000}")
    read -r -p "SECRET_KEY para firmar sesiones (Enter para generar una automática): " SECRET_KEY || true
    if [ -z "$SECRET_KEY" ]; then SECRET_KEY=$(random_secret); fi

    echo ""
    echo "--- Sincronización automática de los biométricos ---"
    _existing_sync_at="$(read_existing_env_value "$ENV_PATH" SYNC_DAILY_AT)"
    SYNC_DAILY_AT=$(prompt_with_default "Hora diaria de sincronización (HH:mm, fuera de horario laboral)" "${_existing_sync_at:-23:00}")

    echo ""
    echo "--- Agentes remotos (sedes detrás de otra VPN) ---"
    echo "Si alguna sede va a conectar un agente remoto a esta base (ver"
    echo "deploy/docker/README.md), este puerto tiene que estar accesible por"
    echo "VPN. Si no sabés, dejalo con el valor por defecto -- no hace daño."
    _existing_pg_port="$(read_existing_env_value "$ENV_PATH" POSTGRES_PORT)"
    PG_PORT=$(prompt_with_default "Puerto de PostgreSQL expuesto" "${_existing_pg_port:-5432}")

    echo ""
    echo "--- Primera cuenta de super administrador del panel ---"
    ADMIN_USER=$(prompt_with_default "Usuario administrador" "admin")
    ADMIN_PASSWORD=$(prompt_required "Contraseña del administrador (elige una clave fuerte)")

    cat > "$ENV_PATH" <<EOF
POSTGRES_USER=$PG_USER
POSTGRES_PASSWORD=$PG_PASSWORD
POSTGRES_DB=$PG_DB
POSTGRES_PORT=$PG_PORT
SECRET_KEY=$SECRET_KEY
WEB_PORT=$WEB_PORT
SYNC_DAILY_AT=$SYNC_DAILY_AT
SYNC_INTERVAL_MINUTES=
EOF
    chmod 600 "$ENV_PATH"

    {
        echo "Usuario de base de datos: $PG_USER"
        echo "Contraseña de base de datos: $PG_PASSWORD"
        echo "Nombre de base de datos: $PG_DB"
        echo "Puerto del panel: $WEB_PORT"
        echo "Puerto de PostgreSQL expuesto: $PG_PORT"
        echo "SECRET_KEY: $SECRET_KEY"
        echo "Hora de sincronización diaria: $SYNC_DAILY_AT"
        echo "Usuario administrador del panel: $ADMIN_USER"
        echo "Contraseña del administrador del panel: $ADMIN_PASSWORD"
        echo "Panel web: http://localhost:$WEB_PORT"
    } >> "$LOG_FILE"

    echo ""
    echo "Levantando los contenedores (esto construye la imagen, puede tardar unos minutos)..."
    cd "$REPO_ROOT"
    docker compose up -d --build

    echo "Esperando que la base de datos esté lista..."
    ready=0
    for _ in $(seq 1 30); do
        if docker compose exec -T db pg_isready -U "$PG_USER" >/dev/null 2>&1; then
            ready=1
            break
        fi
        sleep 2
    done
    if [ "$ready" -ne 1 ]; then
        echo "La base de datos no respondió a tiempo -- revisa 'docker compose logs db' antes de seguir." >&2
    fi

    echo "Creando la cuenta de super administrador '$ADMIN_USER'..."
    if ! docker compose exec -T web python -m central.create_admin "$ADMIN_USER" "$ADMIN_PASSWORD"; then
        echo "central.create_admin terminó con error -- puede que la cuenta ya existiera de una instalación anterior." >&2
    fi

    echo ""
    echo "Si vas a usar agentes remotos en otras sedes, abrí el puerto $PG_PORT en el"
    echo "firewall de este servidor (el comando exacto depende de tu distro -- no se"
    echo "hace automático acá porque varía mucho entre ufw/firewalld/iptables):"
    echo "  sudo ufw allow $PG_PORT/tcp        # Ubuntu con ufw"
    echo "  sudo firewall-cmd --add-port=$PG_PORT/tcp --permanent && sudo firewall-cmd --reload   # con firewalld"
else
    ENV_PATH="$SCRIPT_DIR/.env"

    echo "--- Identidad de este agente ---"
    echo "Este nombre debe coincidir EXACTO con el 'Agente remoto' que se"
    echo "configure en Dispositivos, en el panel central, para cada equipo"
    echo "de esta sede."
    AGENT_NAME=$(prompt_required "Nombre de este agente (ej. sede-pueblo-libre)")

    echo ""
    echo "--- Conexión a la base de datos del servidor central ---"
    CENTRAL_HOST=$(prompt_required "IP o DNS del servidor central")
    CENTRAL_PORT=$(prompt_with_default "Puerto de PostgreSQL en el servidor central" "5432")
    CENTRAL_DB=$(prompt_with_default "Nombre de la base de datos central" "asistencia")
    CENTRAL_USER=$(prompt_with_default "Usuario de la base de datos central" "asistencia")
    CENTRAL_PASSWORD=$(prompt_required "Contraseña de la base de datos central (la misma que tiene el servidor central)")

    echo ""
    echo "--- Sincronización automática de los biométricos de esta sede ---"
    _existing_sync_at="$(read_existing_env_value "$ENV_PATH" SYNC_DAILY_AT)"
    SYNC_DAILY_AT=$(prompt_with_default "Hora diaria de sincronización (HH:mm)" "${_existing_sync_at:-23:00}")

    DATABASE_URL="postgresql+psycopg2://$(urlencode "$CENTRAL_USER"):$(urlencode "$CENTRAL_PASSWORD")@${CENTRAL_HOST}:${CENTRAL_PORT}/${CENTRAL_DB}"
    cat > "$ENV_PATH" <<EOF
AGENT_NAME=$AGENT_NAME
DATABASE_URL=$DATABASE_URL
SYNC_DAILY_AT=$SYNC_DAILY_AT
SYNC_INTERVAL_MINUTES=
EOF
    chmod 600 "$ENV_PATH"

    {
        echo "Nombre del agente (AGENT_NAME): $AGENT_NAME"
        echo "Servidor central (IP/DNS): $CENTRAL_HOST"
        echo "Puerto PostgreSQL central: $CENTRAL_PORT"
        echo "Base de datos central: $CENTRAL_DB"
        echo "Usuario base de datos central: $CENTRAL_USER"
        echo "Contraseña base de datos central: $CENTRAL_PASSWORD"
        echo "Hora de sincronización diaria: $SYNC_DAILY_AT"
    } >> "$LOG_FILE"

    echo ""
    echo "Levantando el contenedor del agente (esto construye la imagen, puede tardar unos minutos)..."
    docker compose -f "$SCRIPT_DIR/docker-compose.agent.yml" --env-file "$ENV_PATH" up -d --build

    echo ""
    echo "Recuerda: en el panel central, edita cada dispositivo de esta sede"
    echo "y pon '$AGENT_NAME' en el campo 'Agente remoto'."
fi

echo ""
echo "=== Listo ==="
if [ "$MODE" = "central" ]; then
    echo "Panel: http://localhost:$WEB_PORT (o http://<IP-del-servidor>:$WEB_PORT desde otra máquina)"
fi
echo "Resumen con todas las credenciales ingresadas: $LOG_FILE"
echo "Para iniciar/detener/reiniciar/diagnosticar más adelante, usa:  ./deploy/docker/manage.sh <start|stop|restart|status|diagnose>"
