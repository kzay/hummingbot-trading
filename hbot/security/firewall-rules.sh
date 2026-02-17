#!/usr/bin/env bash
# ============================================
# firewall-rules.sh - UFW Firewall Configuration
# ============================================
# Usage: sudo bash firewall-rules.sh
# ============================================
set -euo pipefail

echo "Configuring UFW firewall rules..."

# Reset to defaults
ufw --force reset

# Default policies
ufw default deny incoming
ufw default allow outgoing

# SSH (required)
ufw allow 22/tcp comment "SSH"

# Optional: If you need direct access to monitoring (NOT recommended for production)
# Uncomment and replace YOUR_IP with your static IP
# ufw allow from YOUR_IP to any port 3000 proto tcp comment "Grafana from trusted IP"
# ufw allow from YOUR_IP to any port 9090 proto tcp comment "Prometheus from trusted IP"

# Optional: If running a VPN
# ufw allow 51820/udp comment "WireGuard VPN"

# Enable firewall
ufw --force enable

# Show status
ufw status verbose

echo ""
echo "Firewall configured."
echo "Monitoring ports are NOT exposed. Use SSH tunneling."
echo "  ssh -L 3000:127.0.0.1:3000 user@vps-ip"
