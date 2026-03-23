#!/usr/bin/env bash
# ============================================
# Compose Up Wrapper — always inject --env-file
# ============================================
# Prevents empty CONFIG_PASSWORD when running without env file,
# which causes Hummingbot to hang at interactive login prompt.
#
# Usage:
#   ./scripts/ops/compose_up.sh [up|down|restart] [service...]
#   ./scripts/ops/compose_up.sh up -d bot1 bot-watchdog
#
# Requires: infra/env/.env exists (copy from infra/env/.env.template)
# ============================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HB_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMPOSE_DIR="$HB_ROOT/infra/compose"
ENV_FILE="$HB_ROOT/infra/env/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "[compose_up] ERROR: env file not found: $ENV_FILE"
  echo "[compose_up] Copy from template: cp $HB_ROOT/infra/env/.env.template $ENV_FILE"
  exit 1
fi

cd "$COMPOSE_DIR"
exec docker compose --env-file "$ENV_FILE" -f docker-compose.yml "$@"
