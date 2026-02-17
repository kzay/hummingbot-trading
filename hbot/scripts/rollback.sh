#!/usr/bin/env bash
# ============================================
# rollback.sh - Restore Bot from Backup
# ============================================
# Usage: bash rollback.sh <bot_name> [backup_file]
# Examples:
#   bash rollback.sh bot1                          # restore from latest backup
#   bash rollback.sh bot1 bot1_20240115_040000.tar.gz  # restore specific backup
# ============================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="${PROJECT_DIR}/backups"
COMPOSE_DIR="${PROJECT_DIR}/compose"
ENV_FILE="${PROJECT_DIR}/env/.env"

BOT_NAME="${1:?Usage: rollback.sh <bot_name> [backup_file]}"
BACKUP_FILE="${2:-}"

echo "============================================"
echo " Hummingbot Rollback - ${BOT_NAME}"
echo "============================================"

# Find backup file
if [ -z "$BACKUP_FILE" ]; then
    BACKUP_FILE=$(ls -t "${BACKUP_DIR}/${BOT_NAME}_"*.tar.gz 2>/dev/null | head -n1)
    if [ -z "$BACKUP_FILE" ]; then
        echo "ERROR: No backup found for ${BOT_NAME}"
        echo "Available backups:"
        ls -lh "${BACKUP_DIR}/"*.tar.gz 2>/dev/null || echo "  (none)"
        exit 1
    fi
    echo "Using latest backup: $(basename "$BACKUP_FILE")"
else
    BACKUP_FILE="${BACKUP_DIR}/${BACKUP_FILE}"
    if [ ! -f "$BACKUP_FILE" ]; then
        echo "ERROR: Backup file not found: ${BACKUP_FILE}"
        exit 1
    fi
fi

# Confirmation
echo ""
echo "This will:"
echo "  1. Stop ${BOT_NAME}"
echo "  2. Replace data/${BOT_NAME}/ with backup contents"
echo "  3. Restart ${BOT_NAME}"
echo ""
read -p "Continue? (y/N) " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
fi

# ---- Step 1: Stop the bot ----
echo "[1/4] Stopping ${BOT_NAME}..."
cd "$COMPOSE_DIR"
docker compose --env-file "$ENV_FILE" stop "$BOT_NAME" 2>/dev/null || true

# ---- Step 2: Backup current state (just in case) ----
echo "[2/4] Saving current state before rollback..."
EMERGENCY_BACKUP="${BACKUP_DIR}/${BOT_NAME}_pre_rollback_$(date +%Y%m%d_%H%M%S).tar.gz"
tar -czf "$EMERGENCY_BACKUP" \
    -C "${PROJECT_DIR}/data" \
    "${BOT_NAME}/" 2>/dev/null || true
echo "  Emergency backup: $(basename "$EMERGENCY_BACKUP")"

# ---- Step 3: Restore from backup ----
echo "[3/4] Restoring from backup..."
# Remove current data (keep directory structure)
rm -rf "${PROJECT_DIR}/data/${BOT_NAME}/conf/"*
rm -rf "${PROJECT_DIR}/data/${BOT_NAME}/data/"*
rm -rf "${PROJECT_DIR}/data/${BOT_NAME}/scripts/"*
rm -rf "${PROJECT_DIR}/data/${BOT_NAME}/pmm_scripts/"*

# Extract backup
tar -xzf "$BACKUP_FILE" -C "${PROJECT_DIR}/data/"
echo "  Restored from: $(basename "$BACKUP_FILE")"

# ---- Step 4: Restart ----
echo "[4/4] Restarting ${BOT_NAME}..."
docker compose --env-file "$ENV_FILE" up -d "$BOT_NAME"

sleep 10
STATUS=$(docker compose --env-file "$ENV_FILE" ps --format json "$BOT_NAME" 2>/dev/null | jq -r '.[0].State // .State // "unknown"' 2>/dev/null || echo "unknown")

echo ""
echo "============================================"
echo " Rollback complete."
echo " ${BOT_NAME} status: ${STATUS}"
echo "============================================"
