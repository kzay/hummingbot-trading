#!/usr/bin/env bash
# ============================================
# log-cleanup.sh - Clean Old Log Files
# ============================================
# Usage: bash log-cleanup.sh [days_to_keep]
# Default: keep last 7 days of logs
#
# Recommended cron (weekly):
#   0 3 * * 0 /path/to/hbot/scripts/log-cleanup.sh >> /var/log/hbot-cleanup.log 2>&1
# ============================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DAYS="${1:-7}"

echo "============================================"
echo " Log Cleanup - $(date)"
echo " Removing logs older than ${DAYS} days"
echo "============================================"

# Clean bot logs
for bot_dir in "${PROJECT_DIR}"/data/bot*; do
    if [ -d "${bot_dir}/logs" ]; then
        bot_name=$(basename "$bot_dir")
        count=$(find "${bot_dir}/logs" -name "*.log*" -mtime "+${DAYS}" -type f 2>/dev/null | wc -l)
        if [ "$count" -gt 0 ]; then
            find "${bot_dir}/logs" -name "*.log*" -mtime "+${DAYS}" -type f -delete
            echo "  ${bot_name}: removed ${count} old log files"
        else
            echo "  ${bot_name}: no old logs to remove"
        fi
    fi
done

# Clean Docker logs (requires root)
if [ "$(id -u)" -eq 0 ]; then
    echo ""
    echo "Truncating Docker container logs..."
    for container in $(docker ps --filter "name=hbot-" -q 2>/dev/null); do
        name=$(docker inspect --format='{{.Name}}' "$container" | sed 's/\///')
        log_file=$(docker inspect --format='{{.LogPath}}' "$container")
        if [ -f "$log_file" ]; then
            size_before=$(du -h "$log_file" | cut -f1)
            truncate -s 0 "$log_file"
            echo "  ${name}: truncated (was ${size_before})"
        fi
    done
else
    echo ""
    echo "Run as root to also truncate Docker container logs."
fi

# Report disk usage
echo ""
echo "Current disk usage:"
df -h / | tail -1 | awk '{print "  Used: "$3" / "$2" ("$5")"}'

echo ""
echo "Cleanup complete."
