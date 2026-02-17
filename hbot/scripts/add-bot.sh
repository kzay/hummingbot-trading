#!/usr/bin/env bash
# ============================================
# add-bot.sh - Add a New Bot Instance
# ============================================
# Usage: bash add-bot.sh bot3
# This creates the data directory structure and
# prints the docker-compose service block to add.
# ============================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

BOT_NAME="${1:?Usage: add-bot.sh <bot_name> (e.g., bot3)}"

BOT_DIR="${PROJECT_DIR}/data/${BOT_NAME}"

if [ -d "$BOT_DIR" ]; then
    echo "ERROR: ${BOT_DIR} already exists."
    exit 1
fi

echo "Creating directory structure for ${BOT_NAME}..."
mkdir -p "${BOT_DIR}/conf"
mkdir -p "${BOT_DIR}/logs"
mkdir -p "${BOT_DIR}/data"
mkdir -p "${BOT_DIR}/scripts"
mkdir -p "${BOT_DIR}/pmm_scripts"

# Create .gitkeep files
touch "${BOT_DIR}/conf/.gitkeep"
touch "${BOT_DIR}/logs/.gitkeep"
touch "${BOT_DIR}/data/.gitkeep"
touch "${BOT_DIR}/scripts/.gitkeep"
touch "${BOT_DIR}/pmm_scripts/.gitkeep"

echo "Directory created: ${BOT_DIR}"
echo ""
echo "============================================"
echo "Add the following to docker-compose.yml:"
echo "============================================"
echo ""

BOT_NUM=$(echo "$BOT_NAME" | grep -oP '\d+' || echo "X")

cat << COMPOSE_BLOCK
  # ==========================================
  # ${BOT_NAME^^} - Bitget Spot
  # ==========================================
  ${BOT_NAME}:
    <<: *hbot-base
    container_name: hbot-${BOT_NAME}
    profiles:
      - multi
    volumes:
      - ../data/${BOT_NAME}/conf:/home/hummingbot/conf
      - ../data/${BOT_NAME}/logs:/home/hummingbot/logs
      - ../data/${BOT_NAME}/data:/home/hummingbot/data
      - ../data/${BOT_NAME}/scripts:/home/hummingbot/scripts
      - ../data/${BOT_NAME}/pmm_scripts:/home/hummingbot/pmm_scripts
      - ../scripts/strategies:/home/hummingbot/custom_strategies:ro
      - ../scripts/utils:/home/hummingbot/custom_utils:ro
    environment:
      - TZ=\${TZ:-UTC}
      - CONFIG_PASSWORD=\${BOT${BOT_NUM}_PASSWORD:-admin}
    deploy:
      resources:
        limits:
          memory: 1G
          cpus: "1.0"
        reservations:
          memory: 256M
          cpus: "0.25"
COMPOSE_BLOCK

echo ""
echo "============================================"
echo "Add the following to env/.env:"
echo "============================================"
echo ""
cat << ENV_BLOCK
# ---- Bot ${BOT_NUM} - ${BOT_NAME} ----
BOT${BOT_NUM}_NAME=${BOT_NAME}
BOT${BOT_NUM}_BITGET_API_KEY=your_bitget_api_key_here
BOT${BOT_NUM}_BITGET_API_SECRET=your_bitget_api_secret_here
BOT${BOT_NUM}_BITGET_PASSPHRASE=your_bitget_passphrase_here
BOT${BOT_NUM}_PASSWORD=adminChangeMeBot${BOT_NUM}
ENV_BLOCK

echo ""
echo "After editing, start with:"
echo "  cd ${PROJECT_DIR}/compose"
echo "  docker compose --env-file ../env/.env --profile multi up -d ${BOT_NAME}"
