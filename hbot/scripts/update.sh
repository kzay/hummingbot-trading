#!/usr/bin/env bash
# ============================================
# update.sh - Safe Update Procedure
# ============================================
# Usage: bash update.sh [service_name]
# Examples:
#   bash update.sh          # update all services
#   bash update.sh bot1     # update only bot1
#   bash update.sh grafana  # update only grafana
#
# This script:
#   1. Creates a backup before updating
#   2. Pulls new images
#   3. Restarts services one by one
#   4. Verifies health after restart
# ============================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE_DIR="${PROJECT_DIR}/compose"
ENV_FILE="${PROJECT_DIR}/env/.env"

TARGET="${1:-all}"
HEALTH_WAIT=30  # seconds to wait for health check

echo "============================================"
echo " Hummingbot Safe Update - $(date)"
echo "============================================"

# Pre-flight checks
if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: env/.env not found. Run deploy.sh first."
    exit 1
fi

cd "$COMPOSE_DIR"

# ---- Step 1: Backup ----
echo ""
echo "[1/5] Creating pre-update backup..."
bash "${SCRIPT_DIR}/backup.sh"

# ---- Step 2: Record current state ----
echo ""
echo "[2/5] Recording current state..."
docker compose --env-file "$ENV_FILE" ps > "/tmp/hbot_pre_update_state.txt" 2>&1
echo "Current state saved to /tmp/hbot_pre_update_state.txt"

# ---- Step 3: Pull new images ----
echo ""
echo "[3/5] Pulling latest pinned images..."
if [ "$TARGET" = "all" ]; then
    docker compose --env-file "$ENV_FILE" pull
else
    docker compose --env-file "$ENV_FILE" pull "$TARGET"
fi

# ---- Step 4: Rolling restart ----
echo ""
echo "[4/5] Performing rolling restart..."

restart_service() {
    local svc="$1"
    echo "  Restarting ${svc}..."
    docker compose --env-file "$ENV_FILE" up -d --no-deps "$svc"
    echo "  Waiting ${HEALTH_WAIT}s for ${svc} to stabilize..."
    sleep "$HEALTH_WAIT"

    # Check if running
    local status
    status=$(docker compose --env-file "$ENV_FILE" ps --format json "$svc" 2>/dev/null | jq -r '.[0].State // .State // "unknown"' 2>/dev/null || echo "unknown")

    if [ "$status" = "running" ]; then
        echo "  ${svc}: OK (running)"
    else
        echo "  WARNING: ${svc} status is '${status}' - check logs!"
        echo "  Run: docker compose --env-file ../env/.env logs --tail 50 ${svc}"
    fi
}

if [ "$TARGET" = "all" ]; then
    # Update monitoring first, then bots
    for svc in prometheus grafana node-exporter cadvisor; do
        restart_service "$svc"
    done
    # Then bots (one by one for safety)
    for svc in $(docker compose --env-file "$ENV_FILE" ps --services 2>/dev/null | grep "^bot"); do
        restart_service "$svc"
    done
else
    restart_service "$TARGET"
fi

# ---- Step 5: Post-update verification ----
echo ""
echo "[5/5] Post-update verification..."
docker compose --env-file "$ENV_FILE" ps
echo ""

# Check for any unhealthy containers
UNHEALTHY=$(docker ps --filter "name=hbot-" --filter "health=unhealthy" --format "{{.Names}}" 2>/dev/null || true)
if [ -n "$UNHEALTHY" ]; then
    echo "WARNING: Unhealthy containers detected:"
    echo "$UNHEALTHY"
    echo ""
    echo "To rollback, restore from backup and run:"
    echo "  docker compose --env-file ../env/.env up -d"
else
    echo "All containers healthy."
fi

echo ""
echo "============================================"
echo " Update complete."
echo " Review Grafana dashboards for anomalies."
echo "============================================"
