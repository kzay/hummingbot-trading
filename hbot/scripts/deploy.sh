#!/usr/bin/env bash
# ============================================
# deploy.sh - First-time VPS Deployment Script
# ============================================
# Usage: sudo bash deploy.sh
# Run this ONCE on a fresh Ubuntu 22/24 VPS
# ============================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "============================================"
echo " Hummingbot Infrastructure - VPS Setup"
echo "============================================"

# ---- 1. System Update ----
echo "[1/8] Updating system packages..."
apt-get update -qq
apt-get upgrade -y -qq

# ---- 2. Install prerequisites ----
echo "[2/8] Installing prerequisites..."
apt-get install -y -qq \
    apt-transport-https \
    ca-certificates \
    curl \
    gnupg \
    lsb-release \
    ufw \
    fail2ban \
    unattended-upgrades \
    logrotate \
    htop \
    jq

# ---- 3. Install Docker ----
echo "[3/8] Installing Docker..."
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
    echo "Docker installed: $(docker --version)"
else
    echo "Docker already installed: $(docker --version)"
fi

# ---- 4. Install Docker Compose plugin ----
echo "[4/8] Verifying Docker Compose..."
if docker compose version &> /dev/null; then
    echo "Docker Compose available: $(docker compose version)"
else
    echo "ERROR: Docker Compose plugin not found. Install manually."
    exit 1
fi

# ---- 5. Configure Firewall ----
echo "[5/8] Configuring firewall (UFW)..."
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment "SSH"
# Do NOT expose monitoring ports publicly - use SSH tunnel
ufw --force enable
echo "Firewall configured. Monitoring ports are NOT exposed."
echo "Use SSH tunnel to access Grafana: ssh -L 3000:127.0.0.1:3000 user@vps"

# ---- 6. Configure fail2ban ----
echo "[6/8] Configuring fail2ban..."
cat > /etc/fail2ban/jail.local << 'FAIL2BAN'
[DEFAULT]
bantime = 3600
findtime = 600
maxretry = 5
backend = systemd

[sshd]
enabled = true
port = ssh
filter = sshd
maxretry = 3
FAIL2BAN
systemctl restart fail2ban

# ---- 7. Setup project directory permissions ----
echo "[7/8] Setting up project permissions..."
cd "$PROJECT_DIR"

# Create .env from template if not exists
if [ ! -f "env/.env" ]; then
    cp env/.env.template env/.env
    chmod 600 env/.env
    echo "Created env/.env from template - EDIT WITH YOUR API KEYS"
else
    echo "env/.env already exists - skipping"
fi

# Set secure permissions on data directories
find data/ -type d -exec chmod 750 {} \;
find env/ -type f -exec chmod 600 {} \;

# ---- 8. Pull Docker images ----
echo "[8/8] Pulling Docker images..."
cd compose/
docker compose --env-file ../env/.env pull

echo ""
echo "============================================"
echo " Setup Complete!"
echo "============================================"
echo ""
echo " Next steps:"
echo "  1. Edit env/.env with your API keys"
echo "  2. cd ${PROJECT_DIR}/compose"
echo "  3. docker compose --env-file ../env/.env up -d"
echo ""
echo " To access Grafana (from your local machine):"
echo "  ssh -L 3000:127.0.0.1:3000 user@your-vps-ip"
echo "  Then open http://localhost:3000"
echo ""
echo " To attach to bot1:"
echo "  docker attach hbot-bot1"
echo "  (Ctrl+P, Ctrl+Q to detach)"
echo "============================================"
