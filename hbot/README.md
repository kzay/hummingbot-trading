# Hummingbot Trading Infrastructure

Production-ready, Docker-based Hummingbot infrastructure for Bitget Spot trading with full monitoring stack.

---

## Table of Contents

1. [Project Structure](#1-project-structure)
2. [Architecture Overview](#2-architecture-overview)
3. [Prerequisites](#3-prerequisites)
4. [Deployment Procedure](#4-deployment-procedure)
5. [Bitget Configuration](#5-bitget-configuration)
6. [Custom Strategies](#6-custom-strategies)
7. [Monitoring & Grafana](#7-monitoring--grafana)
8. [Scaling to Multiple Bots](#8-scaling-to-multiple-bots)
9. [Update Procedure](#9-update-procedure)
10. [Backup & Rollback](#10-backup--rollback)
11. [Security](#11-security)
12. [Operating Model](#12-operating-model)
13. [Troubleshooting](#13-troubleshooting)

---

## 1. Project Structure

```
hbot/
├── compose/                          # Docker Compose files
│   └── docker-compose.yml            # Main orchestration file
├── data/                             # Per-bot persistent data
│   ├── bot1/
│   │   ├── conf/                     # Hummingbot config files + API keys (encrypted)
│   │   ├── logs/                     # Bot log output
│   │   ├── data/                     # SQLite databases, trade history
│   │   ├── scripts/                  # Bot-specific scripts
│   │   └── pmm_scripts/             # PMM script overrides
│   └── bot2/                         # Same structure, additional bot
├── monitoring/
│   ├── prometheus/
│   │   ├── prometheus.yml            # Prometheus scrape configuration
│   │   └── alert_rules.yml           # Alerting rules
│   ├── grafana/
│   │   ├── provisioning/
│   │   │   ├── datasources/          # Auto-provisioned datasources
│   │   │   └── dashboards/           # Dashboard provisioning config
│   │   └── dashboards/               # JSON dashboard definitions
│   └── alertmanager/
│       └── alertmanager.yml          # Alert routing config
├── scripts/                          # Operational scripts
│   ├── strategies/                   # Shared strategy Python files
│   │   ├── bitget_spot_mm.py         # Example market-making strategy
│   │   └── config_bitget_spot_mm.yml # Strategy YAML config
│   ├── utils/                        # Shared utilities
│   │   └── health_check.py           # System health checker
│   ├── deploy.sh                     # First-time VPS setup
│   ├── backup.sh                     # Backup bot data
│   ├── update.sh                     # Safe update procedure
│   ├── rollback.sh                   # Restore from backup
│   ├── add-bot.sh                    # Add new bot instance
│   └── status.sh                     # Quick status check
├── env/
│   └── .env.template                 # Environment variable template
├── backups/                          # Backup archives (gitignored)
├── security/                         # Security configs (firewall rules, etc.)
├── .gitignore                        # Git exclusions
└── README.md                         # This file
```

### What goes where

| Folder | Purpose | Git tracked? |
|--------|---------|-------------|
| `compose/` | Docker Compose orchestration | Yes |
| `data/botX/conf/` | Bot configuration, encrypted API keys | Partial (.gitkeep only) |
| `data/botX/logs/` | Runtime logs | No |
| `data/botX/data/` | SQLite DB, trade history | No |
| `scripts/strategies/` | Shared strategy code | Yes |
| `scripts/utils/` | Shared utilities | Yes |
| `monitoring/` | Prometheus, Grafana configs | Yes |
| `env/` | Environment variables (.env) | Template only |
| `backups/` | Compressed backup archives | No |

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                     VPS (Ubuntu)                     │
│                                                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐          │
│  │  bot1    │  │  bot2    │  │  bot3    │  ...      │
│  │ (hbot)   │  │ (hbot)   │  │ (hbot)   │          │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘          │
│       │              │              │                 │
│       └──────────────┼──────────────┘                │
│                      │ trading network               │
│                      │                               │
│  ┌───────────────────┼──────────────────────┐       │
│  │           monitoring network              │       │
│  │                                           │       │
│  │  ┌────────────┐  ┌──────────────┐        │       │
│  │  │ Prometheus │  │   Grafana    │        │       │
│  │  │  :9090     │──│   :3000      │        │       │
│  │  └─────┬──────┘  └──────────────┘        │       │
│  │        │                                  │       │
│  │  ┌─────┴──────┐  ┌──────────────┐        │       │
│  │  │  cAdvisor  │  │node-exporter │        │       │
│  │  │  :8080     │  │  :9100       │        │       │
│  │  └────────────┘  └──────────────┘        │       │
│  └───────────────────────────────────────────┘       │
│                                                      │
│  Firewall: Only port 22 exposed                     │
│  Monitoring: SSH tunnel only                        │
└─────────────────────────────────────────────────────┘
```

---

## 3. Prerequisites

- Ubuntu 22.04 or 24.04 LTS VPS
- Minimum 2 CPU cores, 4 GB RAM, 40 GB SSD
- Root or sudo access
- Bitget account with API keys (Spot trading enabled)
- SSH key-based authentication configured

---

## 4. Deployment Procedure

### 4.1 First-Time VPS Setup

```bash
# Clone the repository to your VPS
git clone <your-repo-url> ~/hbot
cd ~/hbot/hbot

# Run the deployment script (as root)
sudo bash scripts/deploy.sh
```

This script will:
- Update system packages
- Install Docker and Docker Compose
- Configure UFW firewall (only SSH exposed)
- Configure fail2ban for SSH protection
- Create `.env` from template
- Pull all Docker images

### 4.2 Configure Environment

```bash
# Edit the environment file with your real credentials
nano env/.env
```

Required changes:
- Set `BOT1_BITGET_API_KEY`, `BOT1_BITGET_API_SECRET`, `BOT1_BITGET_PASSPHRASE`
- Set `GF_ADMIN_PASSWORD` to a strong password
- Set `BOT1_PASSWORD` to your desired Hummingbot password

### 4.3 First Start

```bash
cd compose/

# Start bot1 + monitoring stack
docker compose --env-file ../env/.env up -d

# Verify everything is running
docker compose --env-file ../env/.env ps

# Check logs
docker compose --env-file ../env/.env logs -f bot1
```

### 4.4 Connect to Hummingbot

```bash
# Attach to bot1 interactive terminal
docker attach hbot-bot1

# Inside hummingbot:
#   1. Set password when prompted
#   2. connect bitget
#   3. Enter API key, secret, passphrase
#   4. start --script bitget_spot_mm.py

# Detach without stopping: Ctrl+P then Ctrl+Q
```

### 4.5 Access Grafana (via SSH tunnel)

From your **local machine**:

```bash
ssh -L 3000:127.0.0.1:3000 user@your-vps-ip
```

Then open `http://localhost:3000` in your browser.  
Login: credentials from `GF_ADMIN_USER` / `GF_ADMIN_PASSWORD` in `.env`.

---

## 5. Bitget Configuration

### 5.1 API Key Setup on Bitget

1. Go to Bitget > API Management
2. Create a new API key with these permissions:
   - **Read** - required
   - **Spot Trade** - required
   - **Withdraw** - DO NOT enable
3. Set IP whitelist to your VPS IP address
4. Note: API Key, Secret Key, and Passphrase

### 5.2 Connector Configuration

Hummingbot uses the `bitget` connector for spot trading. Inside the Hummingbot CLI:

```
>>> connect bitget
```

It will prompt for:
- API Key
- Secret Key
- Passphrase

These are stored **encrypted** in `data/bot1/conf/connectors/bitget.yml` using your bot password.

### 5.3 Secure Credential Injection

**Method 1: Interactive (recommended)**
```bash
docker attach hbot-bot1
>>> connect bitget
# Enter credentials when prompted
# They are encrypted with CONFIG_PASSWORD
```

**Method 2: Environment variable pre-seeding**

The `CONFIG_PASSWORD` environment variable in docker-compose.yml auto-sets the encryption password. API keys themselves must still be entered interactively or via conf files.

### 5.4 Environment Variable Template

The `env/.env.template` file contains all configurable variables. Copy it to `env/.env` and never commit the `.env` file:

```bash
cp env/.env.template env/.env
chmod 600 env/.env
```

### 5.5 Spot vs Perpetual

The current setup targets Spot. To add Perpetual support:
- The connector name changes to `bitget_perpetual`
- Use `connect bitget_perpetual` in the bot
- Strategy configs need `exchange: bitget_perpetual`
- The Docker image and compose structure remain identical

---

## 6. Custom Strategies

### 6.1 Strategy Files

Strategies live in `scripts/strategies/` and are mounted read-only into every bot container at `/home/hummingbot/custom_strategies/`.

```
scripts/
├── strategies/
│   ├── bitget_spot_mm.py              # Market making strategy
│   └── config_bitget_spot_mm.yml      # YAML configuration
└── utils/
    └── health_check.py                # Shared utility
```

### 6.2 Mounting into Containers

In `docker-compose.yml`, each bot has:
```yaml
volumes:
  - ../scripts/strategies:/home/hummingbot/custom_strategies:ro
  - ../scripts/utils:/home/hummingbot/custom_utils:ro
```

The `:ro` flag ensures bots cannot modify shared strategy code.

### 6.3 Running a Strategy

```bash
docker attach hbot-bot1

# Start with script
>>> start --script bitget_spot_mm.py

# Or start with script + config
>>> start --script bitget_spot_mm.py --conf config_bitget_spot_mm.yml
```

### 6.4 Versioning Strategies

- All strategies are in `scripts/strategies/` and tracked by Git
- Use meaningful commit messages: `feat(strategy): add trailing-stop to spot MM`
- Tag stable versions: `git tag v1.0.0-strategy-stable`
- Bot-specific overrides go in `data/botX/scripts/` (not tracked)
- Never edit strategy files on the VPS directly; push from dev and pull

### 6.5 V2 Normal vs Paper Run Matrix

Before running any paper config, verify the connector is listed under
`paper_trade.paper_trade_exchanges` in `data/bot1/conf/conf_client.yml`.

Attach to the bot first:

```bash
docker attach hbot-bot1
```

Then run one of the following pairs:

#### PMM + RSI + LLM

```text
Normal:
>>> start --script v2_with_controllers.py --conf v2_pmm_rsi_llm.yml

Paper:
>>> start --script v2_with_controllers.py --conf v2_pmm_rsi_llm_paper.yml
```

#### PMM Avellaneda V2

```text
Normal:
>>> start --script v2_with_controllers.py --conf v2_pmm_avellaneda_v2.yml

Paper:
>>> start --script v2_with_controllers.py --conf v2_pmm_avellaneda_v2_paper.yml
```

#### Systematic Alpha V1

```text
Normal:
>>> start --script v2_with_controllers.py --conf v2_systematic_alpha.yml

Paper:
>>> start --script v2_with_controllers.py --conf v2_systematic_alpha_paper.yml
```

#### AI Trend Following V1

```text
Normal:
>>> start --script v2_with_controllers.py --conf v2_ai_trend_following_v1.yml

Paper:
>>> start --script v2_with_controllers.py --conf v2_ai_trend_following_v1_paper.yml
```

#### Directional MAX/MIN V1

```text
Normal:
>>> start --script v2_with_controllers.py --conf v2_directional_max_min.yml

Paper:
>>> start --script v2_with_controllers.py --conf v2_directional_max_min_paper.yml
```

---

## 7. Monitoring & Grafana

### 7.1 Stack Components

| Component | Purpose | Port (localhost only) |
|-----------|---------|----------------------|
| Prometheus | Metrics collection & alerting | 9090 |
| Grafana | Dashboards & visualization | 3000 |
| Node Exporter | Host metrics (CPU, RAM, disk, net) | 9100 |
| cAdvisor | Container metrics | 8080 |
| Alertmanager | Alert routing (optional) | 9093 |

### 7.2 Pre-installed Dashboards

The infrastructure dashboard (`monitoring/grafana/dashboards/infrastructure.json`) includes:

- **System Overview**: CPU %, Memory %, Disk %
- **Container Metrics**: Per-container CPU, Memory, Network I/O
- **Container Restarts**: 24h restart counter with thresholds
- **Network**: Host network traffic, system uptime

### 7.3 Recommended Additional Dashboards

Import these from Grafana.com by ID:

| Dashboard | Grafana ID | Purpose |
|-----------|-----------|---------|
| Node Exporter Full | 1860 | Comprehensive host metrics |
| Docker Container Monitoring | 893 | Detailed container metrics |
| Prometheus Stats | 2 | Prometheus self-monitoring |

To import: Grafana > Dashboards > Import > Enter ID > Select Prometheus datasource.

### 7.4 Alert Rules

Configured in `monitoring/prometheus/alert_rules.yml`:

| Alert | Condition | Severity |
|-------|-----------|----------|
| ContainerDown | Container not seen for 60s | Critical |
| ContainerRestartLoop | >3 restarts in 15min | Critical |
| HighCpuUsage | CPU > 90% for 5min | Warning |
| HighMemoryUsage | Memory > 85% for 5min | Warning |
| HighDiskUsage | Disk > 80% for 10min | Warning |
| DiskAlmostFull | Disk > 95% for 5min | Critical |
| ContainerOomKilled | Any OOM kill event | Critical |

### 7.5 Enabling Alertmanager

```bash
# Start with alerts profile
cd compose/
docker compose --env-file ../env/.env --profile alerts up -d

# Configure Slack/webhook in monitoring/alertmanager/alertmanager.yml
```

---

## 8. Scaling to Multiple Bots

### 8.1 Add a New Bot

```bash
# Use the helper script
bash scripts/add-bot.sh bot3
```

This will:
1. Create the directory structure in `data/bot3/`
2. Print the docker-compose service block to add
3. Print the `.env` variables to add

### 8.2 Activate Additional Bots

Bot2+ use the `multi` profile. To start them:

```bash
cd compose/

# Start bot1 + bot2
docker compose --env-file ../env/.env --profile multi up -d

# Start only bot2
docker compose --env-file ../env/.env --profile multi up -d bot2
```

### 8.3 Resource Planning

| Bots | Min CPU | Min RAM | Min Disk |
|------|---------|---------|----------|
| 1 | 2 cores | 4 GB | 40 GB |
| 2-3 | 4 cores | 8 GB | 60 GB |
| 4-6 | 6 cores | 16 GB | 100 GB |

Each bot consumes approximately 256-512 MB RAM and 0.25-0.5 CPU cores during active trading.

---

## 9. Update Procedure

### 9.1 Safe Update Flow

```bash
# 1. Check current versions
docker compose --env-file ../env/.env ps

# 2. Edit env/.env to pin new version
#    HUMMINGBOT_IMAGE=hummingbot/hummingbot:1.29.0

# 3. Run safe update
bash scripts/update.sh
```

The update script automatically:
1. Creates a pre-update backup
2. Records current container state
3. Pulls new images
4. Performs rolling restart (monitoring first, then bots one-by-one)
5. Verifies health after each restart

### 9.2 Staging Bot Pattern

Before updating production bots, test with a staging bot:

```bash
# 1. Create a staging bot
bash scripts/add-bot.sh bot-staging

# 2. Add to docker-compose.yml with the NEW image version
#    image: hummingbot/hummingbot:1.29.0  # instead of ${HUMMINGBOT_IMAGE}

# 3. Start and test
docker compose --env-file ../env/.env --profile multi up -d bot-staging

# 4. Monitor for 24-48 hours

# 5. If stable, update production bots
```

### 9.3 Version Pinning Strategy

**Always pin versions in production:**

```yaml
# env/.env
HUMMINGBOT_IMAGE=hummingbot/hummingbot:1.28.0   # PINNED
```

```yaml
# docker-compose.yml (monitoring)
image: prom/prometheus:v2.51.2     # PINNED
image: grafana/grafana:10.4.2     # PINNED
image: prom/node-exporter:v1.8.1  # PINNED
image: gcr.io/cadvisor/cadvisor:v0.49.1  # PINNED
```

**Never use `:latest` in production.**

### 9.4 Monthly Maintenance Checklist

```
[ ] Check for Hummingbot version updates (GitHub releases)
[ ] Check for Docker image security updates
[ ] Review Grafana dashboards for anomalies over the past month
[ ] Review alert history
[ ] Run backup and verify backup integrity
[ ] Check disk usage and clean old logs
[ ] Review fail2ban logs for suspicious activity
[ ] Update system packages: apt update && apt upgrade
[ ] Test backup restoration procedure (on staging)
[ ] Review and rotate API keys if needed
[ ] Check Bitget API key IP whitelist
[ ] Review trading performance metrics
```

---

## 10. Backup & Rollback

### 10.1 Manual Backup

```bash
# Backup all bots
bash scripts/backup.sh

# Backup specific bot
bash scripts/backup.sh bot1
```

### 10.2 Automated Backups (cron)

```bash
# Add to crontab (daily at 4 AM UTC)
crontab -e

# Add this line:
0 4 * * * /home/user/hbot/hbot/scripts/backup.sh >> /var/log/hbot-backup.log 2>&1
```

### 10.3 What Gets Backed Up

- `data/botX/conf/` - Configuration and encrypted API keys
- `data/botX/data/` - SQLite database, trade history
- `data/botX/scripts/` - Bot-specific scripts
- `data/botX/pmm_scripts/` - PMM scripts
- `env/.env` - Environment variables (separate backup)
- Monitoring configs

**Not backed up:** Log files (too large, not critical).

### 10.4 Rollback

```bash
# Rollback bot1 to latest backup
bash scripts/rollback.sh bot1

# Rollback to specific backup
bash scripts/rollback.sh bot1 bot1_20240115_040000.tar.gz

# List available backups
ls -lh backups/
```

### 10.5 Offsite Backup

For critical deployments, sync backups offsite:

```bash
# rsync to another server (add to cron after backup)
rsync -avz backups/ backup-user@offsite-server:/backups/hbot/

# Or upload to S3-compatible storage
aws s3 sync backups/ s3://your-bucket/hbot-backups/ --exclude "*.tmp"
```

---

## 11. Security

### 11.1 Firewall (UFW)

The deploy script configures UFW to only allow SSH:

```bash
# Verify firewall status
sudo ufw status verbose

# Expected output:
# Default: deny (incoming), allow (outgoing)
# 22/tcp ALLOW IN  Anywhere
```

**Monitoring ports (3000, 9090, 8080, 9100) are bound to 127.0.0.1 and NOT exposed to the internet.**

### 11.2 Accessing Monitoring (SSH Tunnel)

```bash
# From your local machine:
ssh -L 3000:127.0.0.1:3000 -L 9090:127.0.0.1:9090 user@your-vps-ip

# Then access:
#   Grafana:    http://localhost:3000
#   Prometheus: http://localhost:9090
```

### 11.3 Grafana Security

Configured in docker-compose.yml:
- Anonymous access disabled
- Sign-up disabled
- Organization creation disabled
- Strong admin password required

### 11.4 Secrets Management

| Secret | Storage | Protection |
|--------|---------|-----------|
| Bitget API keys | `data/botX/conf/connectors/` | Encrypted by Hummingbot with CONFIG_PASSWORD |
| CONFIG_PASSWORD | `env/.env` | File permissions 600, gitignored |
| Grafana password | `env/.env` | File permissions 600, gitignored |
| SSH keys | `~/.ssh/` | Standard SSH key management |

### 11.5 Additional Hardening

```bash
# Disable root SSH login
sudo sed -i 's/PermitRootLogin yes/PermitRootLogin no/' /etc/ssh/sshd_config

# Disable password authentication (use keys only)
sudo sed -i 's/#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config

# Restart SSH
sudo systemctl restart sshd

# Enable automatic security updates
sudo dpkg-reconfigure -plow unattended-upgrades
```

### 11.6 Bitget API Key Best Practices

- Enable IP whitelist on Bitget (your VPS IP only)
- NEVER enable Withdraw permission
- Use separate API keys per bot (for isolation)
- Rotate API keys quarterly
- Monitor API key usage on Bitget dashboard

---

## 12. Operating Model

### 12.1 Daily Monitoring (5 minutes)

```bash
# Quick status check
bash scripts/status.sh

# Check Grafana dashboards via SSH tunnel
# Look for:
#   - All containers running (green)
#   - No restart events in 24h
#   - CPU < 70%, Memory < 75%
#   - No active alerts
```

### 12.2 Weekly Checks (15 minutes)

```
[ ] Review trading P&L in Hummingbot (attach to bot, run `history`)
[ ] Check disk usage trend in Grafana
[ ] Verify backups are running (ls -lh backups/)
[ ] Review bot logs for errors: docker logs --tail 100 hbot-bot1
[ ] Check fail2ban status: sudo fail2ban-client status sshd
[ ] Verify system time is accurate: timedatectl
```

### 12.3 Key Metrics for Trading Stability

| Metric | Normal Range | Action Threshold |
|--------|-------------|-----------------|
| Bot container uptime | >99.5% | Investigate any restart |
| Order fill rate | Strategy-dependent | Sudden drop = connectivity issue |
| API latency | <500ms | >2s = degraded performance |
| Host CPU | <60% | >80% = consider scaling |
| Host Memory | <70% | >85% = memory leak or under-provisioned |
| Disk usage | <70% | >80% = clean logs, expand disk |
| Network errors | 0 | Any errors = network investigation |

### 12.4 When to Restart

- **Restart bot**: After config changes, strategy updates, or if memory usage grows steadily (memory leak)
- **Restart monitoring**: After prometheus.yml or alert rule changes
- **Restart all**: After Docker or OS updates
- **Do NOT restart**: During high-volatility market events unless the bot is malfunctioning

### 12.5 Detecting Silent Failures

Silent failures are the most dangerous in trading infrastructure. Watch for:

1. **Stale orders**: Orders sitting for longer than `order_refresh_time` indicates the bot stopped cycling
2. **Flat balance**: No balance changes over expected trading period
3. **Missing logs**: Log file not growing = bot thread may be dead
4. **Zero network I/O**: Container shows no network traffic = exchange connection lost
5. **Database not growing**: SQLite file unchanged for hours during active trading

Monitoring approach:
```bash
# Check if bot1 log is growing (should show recent timestamp)
docker logs --tail 5 hbot-bot1

# Check network I/O (should not be zero for active bot)
docker stats --no-stream hbot-bot1

# Check last database modification
ls -la data/bot1/data/
```

---

## 13. Troubleshooting

### Bot won't start

```bash
# Check logs
docker compose --env-file ../env/.env logs bot1

# Common causes:
# - Invalid CONFIG_PASSWORD
# - Corrupted config files -> restore from backup
# - Docker image not pulled -> docker compose pull bot1
```

### Cannot connect to Bitget

```bash
# Inside the bot:
>>> connect bitget

# If connection fails:
# - Verify API key, secret, passphrase are correct
# - Check IP whitelist on Bitget includes VPS IP
# - Test DNS resolution: docker exec hbot-bot1 ping api.bitget.com
# - Check VPS outbound connectivity
```

### Grafana not loading

```bash
# Verify SSH tunnel is active
# Check Grafana container
docker logs hbot-grafana

# Restart Grafana
docker compose --env-file ../env/.env restart grafana
```

### High memory usage

```bash
# Check per-container memory
docker stats --no-stream

# If a bot is leaking memory, restart it
docker compose --env-file ../env/.env restart bot1

# Consider adding swap (emergency measure)
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

### Backup restoration failed

```bash
# Check backup file integrity
tar -tzf backups/bot1_20240115_040000.tar.gz

# If corrupted, try the next most recent backup
ls -lt backups/bot1_*.tar.gz
```

---

## Quick Reference Commands

```bash
# ---- Lifecycle ----
cd hbot/compose

# Start (bot1 + monitoring)
docker compose --env-file ../env/.env up -d

# Start (all bots including bot2)
docker compose --env-file ../env/.env --profile multi up -d

# Stop everything
docker compose --env-file ../env/.env down

# Stop specific bot
docker compose --env-file ../env/.env stop bot1

# ---- Interaction ----
# Attach to bot
docker attach hbot-bot1
# Detach: Ctrl+P, Ctrl+Q

# View logs
docker compose --env-file ../env/.env logs -f bot1
docker compose --env-file ../env/.env logs --tail 100 bot1

# ---- Operations ----
# Status check
bash scripts/status.sh

# Backup
bash scripts/backup.sh

# Update
bash scripts/update.sh

# Rollback
bash scripts/rollback.sh bot1

# Add new bot
bash scripts/add-bot.sh bot3

# ---- Monitoring Access (from local machine) ----
ssh -L 3000:127.0.0.1:3000 -L 9090:127.0.0.1:9090 user@vps-ip
# Grafana:    http://localhost:3000
# Prometheus: http://localhost:9090
```

---

## License

Private infrastructure project. Not for redistribution.
