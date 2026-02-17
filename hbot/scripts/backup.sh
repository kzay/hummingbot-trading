#!/usr/bin/env bash
# ============================================
# backup.sh - Backup Bot Data and Configs
# ============================================
# Usage: bash backup.sh [bot_name]
# Examples:
#   bash backup.sh          # backup all bots
#   bash backup.sh bot1     # backup only bot1
#
# Recommended: add to crontab for daily backups
#   0 4 * * * /path/to/hbot/scripts/backup.sh >> /var/log/hbot-backup.log 2>&1
# ============================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="${PROJECT_DIR}/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
MAX_BACKUPS=30  # keep last N backups

TARGET_BOT="${1:-all}"

echo "============================================"
echo " Hummingbot Backup - $(date)"
echo "============================================"

mkdir -p "$BACKUP_DIR"

backup_bot() {
    local bot_name="$1"
    local bot_dir="${PROJECT_DIR}/data/${bot_name}"

    if [ ! -d "$bot_dir" ]; then
        echo "WARNING: ${bot_dir} does not exist, skipping."
        return
    fi

    local backup_file="${BACKUP_DIR}/${bot_name}_${TIMESTAMP}.tar.gz"

    echo "Backing up ${bot_name}..."

    # Backup conf, data (exclude large log files)
    tar -czf "$backup_file" \
        -C "${PROJECT_DIR}/data" \
        --exclude='*.log' \
        --exclude='*.log.*' \
        "${bot_name}/conf" \
        "${bot_name}/data" \
        "${bot_name}/scripts" \
        "${bot_name}/pmm_scripts" \
        2>/dev/null || true

    local size
    size=$(du -h "$backup_file" | cut -f1)
    echo "Created: ${backup_file} (${size})"
}

# Backup env file separately (encrypted ideally)
backup_env() {
    local env_backup="${BACKUP_DIR}/env_${TIMESTAMP}.tar.gz"
    tar -czf "$env_backup" -C "${PROJECT_DIR}" env/.env 2>/dev/null || true
    chmod 600 "$env_backup"
    echo "Backed up env to: ${env_backup}"
}

# Backup monitoring configs
backup_monitoring() {
    local mon_backup="${BACKUP_DIR}/monitoring_${TIMESTAMP}.tar.gz"
    tar -czf "$mon_backup" \
        -C "${PROJECT_DIR}" \
        monitoring/prometheus/prometheus.yml \
        monitoring/prometheus/alert_rules.yml \
        monitoring/grafana/provisioning \
        monitoring/grafana/dashboards \
        monitoring/alertmanager/alertmanager.yml \
        2>/dev/null || true
    echo "Backed up monitoring to: ${mon_backup}"
}

# Perform backups
if [ "$TARGET_BOT" = "all" ]; then
    for bot_dir in "${PROJECT_DIR}"/data/bot*; do
        if [ -d "$bot_dir" ]; then
            bot_name=$(basename "$bot_dir")
            backup_bot "$bot_name"
        fi
    done
    backup_env
    backup_monitoring
else
    backup_bot "$TARGET_BOT"
fi

# Cleanup old backups
echo ""
echo "Cleaning up old backups (keeping last ${MAX_BACKUPS})..."
ls -tp "${BACKUP_DIR}"/*.tar.gz 2>/dev/null | tail -n +$((MAX_BACKUPS + 1)) | xargs -r rm -f
echo "Backup directory size: $(du -sh "$BACKUP_DIR" | cut -f1)"

echo ""
echo "Backup complete."
