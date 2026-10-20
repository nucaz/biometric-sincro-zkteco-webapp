#!/usr/bin/env bash
# Interruptor de emergencia para el despliegue con Docker (Linux/Ubuntu):
# inicia, detiene, reinicia, muestra estado o diagnostica. Detecta solo si
# esta máquina es "servidor central" o "agente remoto" leyendo
# deploy/docker/.deploy_mode (lo escribe install.sh).
#
# Uso: ./deploy/docker/manage.sh {start|stop|restart|status|diagnose}
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
MARKER_FILE="$SCRIPT_DIR/.deploy_mode"
ACTION="${1:-status}"

if [ ! -f "$MARKER_FILE" ]; then
    echo "No se encontró deploy/docker/.deploy_mode -- ¿ya corriste install.sh en esta máquina?" >&2
    exit 1
fi
MODE="$(cat "$MARKER_FILE" | tr -d '[:space:]')"

if [ "$MODE" = "central" ]; then
    COMPOSE_FILE="$REPO_ROOT/docker-compose.yml"
    ENV_FILE="$REPO_ROOT/.env"
    WORK_DIR="$REPO_ROOT"
    SERVICES=(db web sync)
elif [ "$MODE" = "agent" ]; then
    COMPOSE_FILE="$SCRIPT_DIR/docker-compose.agent.yml"
    ENV_FILE="$SCRIPT_DIR/.env"
    WORK_DIR="$SCRIPT_DIR"
    SERVICES=(agent)
else
    echo "deploy/docker/.deploy_mode tiene un valor desconocido: '$MODE' (se esperaba 'central' o 'agent'). Vuelve a correr install.sh." >&2
    exit 1
fi

compose() {
    (cd "$WORK_DIR" && docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" "$@")
}

case "$ACTION" in
    start)
        echo "Iniciando ($MODE)..."
        compose up -d
        ;;
    stop)
        echo "Deteniendo ($MODE)..."
        compose stop
        ;;
    restart)
        echo "Reiniciando ($MODE)..."
        compose restart
        ;;
    status)
        ;;
    diagnose)
        ;;
    *)
        echo "Uso: $0 {start|stop|restart|status|diagnose}" >&2
        exit 1
        ;;
esac

if [ "$ACTION" != "diagnose" ]; then
    echo ""
    echo "=== Estado actual ($MODE) ==="
    compose ps
fi

if [ "$ACTION" = "diagnose" ]; then
    echo "=== Diagnóstico del despliegue Docker ($MODE) ==="
    echo ""

    echo "--- Docker ---"
    docker --version
    docker compose version
    DOCKER_UP=1
    if ! docker info >/dev/null 2>&1; then
        DOCKER_UP=0
        echo "Docker no responde -- revisa 'sudo systemctl status docker'."
    else
        echo "Docker responde correctamente."
    fi

    if [ "$DOCKER_UP" -eq 1 ]; then
        echo ""
        echo "--- Contenedores ---"
        compose ps

        for svc in "${SERVICES[@]}"; do
            echo ""
            echo "--- Últimas líneas de log: $svc ---"
            compose logs --tail 15 "$svc"
        done

        if [ "$MODE" = "central" ]; then
            echo ""
            echo "--- Base de datos ---"
            if compose exec -T db pg_isready >/dev/null 2>&1; then
                echo "PostgreSQL responde."
            else
                echo "PostgreSQL NO responde -- revisa el log de 'db' arriba."
            fi

            WEB_PORT="$(grep -E '^WEB_PORT=' "$ENV_FILE" 2>/dev/null | tail -n1 | cut -d'=' -f2- || true)"
            WEB_PORT="${WEB_PORT:-5000}"
            echo ""
            echo "--- Panel web (http://localhost:$WEB_PORT) ---"
            if command -v curl >/dev/null 2>&1; then
                code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://localhost:$WEB_PORT/login" || echo "sin-respuesta")"
                echo "Responde con código HTTP $code."
            else
                echo "curl no está instalado -- no se pudo probar el panel directamente."
            fi
        else
            echo ""
            echo "--- Comandos pendientes para este agente ---"
            echo "Revisa la pestaña Dispositivos del panel central -- un comando que se queda"
            echo "'pendiente' por mucho tiempo suele ser este agente caído o sin red hacia la central."
        fi
    fi

    echo ""
    echo "--- Espacio en disco usado por Docker ---"
    docker system df
fi
