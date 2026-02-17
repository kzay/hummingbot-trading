#!/usr/bin/env bash
# ============================================
# status.sh - Quick Infrastructure Status Check
# ============================================
# Usage: bash status.sh
# ============================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE_DIR="${PROJECT_DIR}/compose"
ENV_FILE="${PROJECT_DIR}/env/.env"

echo "============================================"
echo " Hummingbot Infrastructure Status"
echo " $(date)"
echo "============================================"
echo ""

cd "$COMPOSE_DIR"

# ---- Container Status ----
echo "---- Container Status ----"
docker compose --env-file "$ENV_FILE" ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"
echo ""

# ---- Resource Usage ----
echo "---- Resource Usage ----"
docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}" $(docker ps --filter "name=hbot-" -q 2>/dev/null) 2>/dev/null || echo "No running containers"
echo ""

# ---- Disk Usage ----
echo "---- Disk Usage ----"
echo "Host disk:"
df -h / | tail -1 | awk '{print "  Used: "$3" / "$2" ("$5" used)"}'
echo ""
echo "Docker disk:"
docker system df 2>/dev/null | head -5
echo ""

# ---- Bot Data Sizes ----
echo "---- Bot Data Sizes ----"
for bot_dir in "${PROJECT_DIR}"/data/bot*; do
    if [ -d "$bot_dir" ]; then
        bot_name=$(basename "$bot_dir")
        size=$(du -sh "$bot_dir" 2>/dev/null | cut -f1)
        echo "  ${bot_name}: ${size}"
    fi
done
echo ""

# ---- Backup Status ----
echo "---- Backup Status ----"
BACKUP_DIR="${PROJECT_DIR}/backups"
if [ -d "$BACKUP_DIR" ]; then
    count=$(ls -1 "${BACKUP_DIR}"/*.tar.gz 2>/dev/null | wc -l)
    latest=$(ls -t "${BACKUP_DIR}"/*.tar.gz 2>/dev/null | head -1)
    total_size=$(du -sh "$BACKUP_DIR" 2>/dev/null | cut -f1)
    echo "  Total backups: ${count}"
    echo "  Total size: ${total_size}"
    if [ -n "$latest" ]; then
        echo "  Latest: $(basename "$latest")"
    fi
else
    echo "  No backups directory"
fi
echo ""

# ---- Health Checks ----
echo "---- Health Checks ----"
for container in $(docker ps --filter "name=hbot-" --format "{{.Names}}" 2>/dev/null); do
    health=$(docker inspect --format='{{.State.Health.Status}}' "$container" 2>/dev/null || echo "no-healthcheck")
    status=$(docker inspect --format='{{.State.Status}}' "$container" 2>/dev/null || echo "unknown")
    echo "  ${container}: ${status} (health: ${health})"
done

echo ""
echo "============================================"
