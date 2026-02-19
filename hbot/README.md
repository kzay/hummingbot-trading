# Hummingbot Trading Infrastructure

Production-ready, Docker-based Hummingbot infrastructure for Bitget Spot trading with full monitoring stack.

---

## Table of Contents

1. [Project Structure](#1-project-structure)
2. [Architecture Overview](#2-architecture-overview)
3. [Prerequisites](#3-prerequisites)
4. [Deployment Procedure](#4-deployment-procedure)
5. [Bitget Configuration](#5-bitget-configuration)
6. [Custom Strategy Layer](#6-custom-strategy-layer)
7. [Monitoring & Grafana](#7-monitoring--grafana)
8. [Scaling to Multiple Bots](#8-scaling-to-multiple-bots)
9. [Update Procedure](#9-update-procedure)
10. [Backup & Rollback](#10-backup--rollback)
11. [Security](#11-security)
12. [Operating Model](#12-operating-model)
13. [Troubleshooting](#13-troubleshooting)
16. [Documentation Hub](#16-documentation-hub)

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
│   ├── bot2/                         # Same structure, Bot D no-trade monitor
│   └── bot3/                         # Paper trade smoke test instance
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
│   ├── utils/                        # Shared utilities
│   │   └── health_check.py           # System health checker
│   ├── deploy.sh                     # First-time VPS setup
│   ├── backup.sh                     # Backup bot data
│   ├── update.sh                     # Safe update procedure
│   ├── rollback.sh                   # Restore from backup
│   ├── add-bot.sh                    # Add new bot instance
│   └── status.sh                     # Quick status check
├── docs/                             # Centralized documentation hub
│   ├── architecture/                 # System and data-flow views
│   ├── strategy/                     # EPP and ML strategy specs
│   ├── risk/                         # Risk policy and kill switches
│   ├── infra/                        # Deployment, secrets, profiles
│   ├── ops/                          # Runbooks and incident response
│   ├── validation/                   # Test plans and release gates
│   └── governance/                   # Doc standards and change log
├── env/
│   └── .env.template                 # Environment variable template
├── backups/                          # Backup archives (gitignored)
├── security/                         # Security configs (firewall rules, etc.)
├── .gitignore                        # Git exclusions
└── README.md                         # This file
```

## 16. Documentation Hub

Comprehensive documentation is organized under:

- `docs/README.md` (index)
- `docs/infra/`
- `docs/techspec/`
- `docs/architecture/`
- `docs/financial/`
- `docs/strategy/`
- `docs/risk/`
- `docs/ops/`
- `docs/validation/`
- `docs/governance/`

### What goes where

| Folder | Purpose | Git tracked? |
|--------|---------|-------------|
| `compose/` | Docker Compose orchestration | Yes |
| `data/botX/conf/` | Bot configuration, encrypted API keys | Partial (.gitkeep only) |
| `data/botX/logs/` | Runtime logs | No |
| `data/botX/data/` | SQLite DB, trade history | No |
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
#   4. start with your selected built-in script/config

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

## 6. Custom Strategy Layer

The repository is intentionally clean of custom strategy/controller code.

- No files are mounted from `controllers/` or `scripts/strategies/`.
- Bot runtime should use built-in Hummingbot scripts/configs or newly added project-specific code.
- Keep bot-specific runtime scripts under `data/botX/scripts/` when needed.

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

## 14. EPP v2.4 (Phase 0)

Phase 0 mapping in this repository:
- `bot1` = Bot A (spot inventory engine, active trading)
- `bot2` = Bot D (cash parking/monitoring, no-trade mode)
- Bot B / Bot C exist only as disabled config stubs in `conf/controllers/`

### 14.1 Config Files

Bot A (`bot1`):
- `data/bot1/conf/controllers/epp_v2_4_bot_a.yml`
- `data/bot1/conf/scripts/v2_epp_v2_4_bot_a.yml`

Bot D (`bot2`):
- `data/bot2/conf/controllers/epp_v2_4_bot_d.yml`
- `data/bot2/conf/scripts/v2_epp_v2_4_bot_d.yml`

Disabled stubs (Phase 0 only):
- `data/bot1/conf/controllers/epp_v2_4_bot_b_stub.yml`
- `data/bot1/conf/controllers/epp_v2_4_bot_c_stub.yml`

### 14.2 Run Paper Mode

There are **two independent** paper trading mechanisms. Choose one:

#### Option A: Hummingbot Framework Paper Trade (recommended for standalone scripts)

The framework wraps the real connector with `PaperTradeExchange`, simulating
fills locally.  Orders never reach the exchange.

**Requirements:**
- `conf_client.yml` must list the exchange in `paper_trade_exchanges`:
  ```yaml
  paper_trade:
    paper_trade_exchanges:
      - bitget
    paper_trade_account_balance:
      BTC: 1.0
      USDT: 10000.0
  ```
- Scripts/controllers must use the **`_paper_trade` suffix** as connector name:
  ```python
  markets = {"bitget_paper_trade": {"BTC-USDT"}}   # correct
  # markets = {"bitget": {"BTC-USDT"}}              # WRONG: sends real orders!
  ```
- Bitget spot account must have **some balance** (even 2 USDT dust) so the
  underlying connector initializes (order book, trading rules).  The paper
  wrapper overrides balances with the configured `paper_trade_account_balance`.

> **WARNING:** Using `connector_name: bitget` with `paper_trade_exchanges: [bitget]`
> does **NOT** auto-wrap the connector.  `self.buy("bitget", ...)` sends real
> orders to the exchange.  You must use `bitget_paper_trade` explicitly.
> (Verified against Hummingbot v2.12.0 source: `connector_manager.py` line 68.)

#### Option B: Controller-Level Paper Mode (used by EPP v2.4)

The EPP controller has built-in paper simulation via `paper_mode: true`.
It uses the real connector only for market data (mid-price, order book) and
tracks virtual balances internally (`paper_start_quote`, `paper_start_base`).

**Requirements:**
- `conf_client.yml`: `paper_trade_exchanges: []` (empty -- no framework wrapping)
- Controller YAML: `connector_name: bitget` + `paper_mode: true`
- Bitget spot account must have **some balance** so `connector.ready` returns
  `True` (the `account_balance` check requires `len(_account_balances) > 0`).

#### Starting Paper Mode

1. Start bot containers:

```bash
cd hbot/compose
docker compose --env-file ../env/.env --profile multi up -d bot1 bot2
```

2. Start bot1 strategy:

```bash
docker attach hbot-bot1
start --script v2_with_controllers.py --conf v2_epp_v2_4_bot_a.yml
```

3. Start bot2 monitor (no trades):

```bash
docker attach hbot-bot2
start --script v2_with_controllers.py --conf v2_epp_v2_4_bot_d.yml
```

4. Validate paper run:
   - Bot1 creates simulated orders/fills (check CSV logs + `status`).
   - Bot2 stays no-trade (`variant: d`, `no_trade: true`).
   - CSV logs appear under `data/bot1/logs/epp_v24/...` and `data/bot2/logs/epp_v24/...`.

### 14.3 Run Live Micro Mode

Promotion from paper to live is a **single-field change** in the controller YAML:

1. Ensure encrypted connector credentials are configured (`connect bitget`).
2. In the controller YAML, change `paper_mode: false`.
   (`connector_name` stays `bitget` -- the V2 controller uses the real connector
   for both paper and live; only `paper_mode` controls simulation.)
3. Keep conservative `total_amount_quote` and leave Bot D as `no_trade: true`.
4. Recreate the container:
   ```bash
   docker compose --env-file ../env/.env -f docker-compose.yml up -d --force-recreate bot1
   ```
5. Attach and start the strategy.

### 14.6 After Paper Pass -> Live Switch

Promotion from paper to live for the V2 EPP controller requires **one field change**
per controller YAML (`connector_name` already points to `bitget`):

| Field | Paper (current) | Live |
|-------|----------------|------|
| `paper_mode` | `true` | `false` |
| `connector_name` | `bitget` (unchanged) | `bitget` (unchanged) |

Steps:

1. In `data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: set `paper_mode: false`.
2. Keep Bot D protections unchanged: `variant: d`, `no_trade: true`.
3. Ensure encrypted connector credentials are configured (`connect bitget`).
4. Recreate the container:
   ```bash
   docker compose --env-file ../env/.env -f docker-compose.yml up -d --force-recreate bot1
   ```
5. Start with micro notional (`total_amount_quote`) and observe for 5-7 days.
6. Confirm logs and ops guard remain healthy before increasing capital.

> **Note:** `connector_name` stays `bitget` in both modes because the V2 controller
> framework's `MarketDataProvider` cannot resolve `bitget_paper_trade` as a module.
> Paper simulation is handled entirely by the controller's `paper_mode` flag.
> For standalone scripts (bot3), use `bitget_paper_trade` in the `markets` dict instead.

### 14.4 Go-Live Checklist (15 items)

**Paper-to-live verification:**

1. Controller YAML has `paper_mode: false`.
2. `status` does NOT show "Paper Trading Active".
3. Bitget spot account has sufficient balance for the configured `total_amount_quote`.

**Operational checks:**

4. Connector login succeeds for both bot1 and bot2.
5. `bot1` uses `variant: a` with `enabled: true` and `no_trade: false`.
6. `bot2` uses `variant: d` with `no_trade: true`.
7. Bot B/C configs remain `enabled: false`.
8. Spread floor and turnover cap are set and non-zero.
9. Runtime turnover remains below `3x/day` (target `<2x/day`).
10. Fees/gross profit stays below `35-40%`.
11. Profit factor remains above `1.25` in validation window.
12. Drawdown is below `3-4%` over the validation window.
13. No repeated cancel failures or balance mismatch events.
14. CSV logs are being written for fills/minute/daily on both instances.
15. Ops guard transitions (`running`, `soft_pause`, `hard_stop`) are visible in status/logs.

### 14.5 EPP Split CSV Logs

Per instance logs are written under:
- `data/<bot>/logs/epp_v24/<instance>_<variant>/fills.csv`
- `data/<bot>/logs/epp_v24/<instance>_<variant>/minute.csv`
- `data/<bot>/logs/epp_v24/<instance>_<variant>/daily.csv`

How to read quickly:
- `fills.csv`: execution-level records (price/amount/notional/fee/state)
- `minute.csv`: 1-minute health + edge + turnover snapshot
- `daily.csv`: equity open/now, PnL, turnover, ops events

---

## 15. External Signal/Risk (Redis Streams)

The project now supports a hybrid external orchestration model:

- Hummingbot remains the exchange data and execution gateway.
- External services generate signal and risk decisions.
- Hummingbot keeps final local safety authority (connector readiness, local kill/soft pause behavior).

### 15.1 Enable External Stack

Set in `env/.env`:

```bash
EXT_SIGNAL_RISK_ENABLED=true
BUS_SOFT_PAUSE_ON_OUTAGE=true
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_DB=0
REDIS_CONSUMER_GROUP=hb_group_v1
EVENT_POLL_MS=1000
RISK_MAX_ABS_SIGNAL=0.25
```

Start with external profile:

```bash
cd hbot/compose
docker compose --env-file ../env/.env --profile multi --profile external up -d
```

### 15.2 Stream Flow

- `hb.market_data.v1`: market/controller snapshots from Hummingbot.
- `hb.signal.v1`: normalized signal events from signal service.
- `hb.ml_signal.v1`: ML inference events (model version, confidence, latency).
- `hb.risk_decision.v1`: approve/reject decisions from risk service.
- `hb.execution_intent.v1`: intents consumed by Hummingbot bridge.
- `hb.audit.v1`: audit/ops events from Hummingbot.
- `hb.dead_letter.v1`: invalid or rejected intent events.

### 15.3 Safety Behavior

- If Redis connectivity degrades and outage protection is enabled, Hummingbot can soft-pause external intent application.
- Local Hummingbot controls remain authoritative.
- External intents are idempotent by `event_id` and rejected if expired.

Detailed architecture: `docs/external_signal_risk_architecture.md`

### 15.4 ML Signal Injection (MVP)

ML is injected with the same external pipeline:

`market_data -> ml_signal -> risk_decision -> execution_intent -> Hummingbot`

Enable in `env/.env`:

```bash
ML_ENABLED=true
ML_RUNTIME=sklearn_joblib
ML_MODEL_SOURCE=local
ML_MODEL_URI=/workspace/hbot/models/current/model.joblib
ML_CONFIDENCE_MIN=0.60
ML_MAX_SIGNAL_AGE_MS=3000
ML_INFERENCE_TIMEOUT_MS=200
ML_HORIZON_S=60
ML_FEATURE_SET=v1
```

For custom class runtime:

```bash
ML_RUNTIME=custom_python
ML_CUSTOM_CLASS_PATH=your_module_path:YourModelClass
```

The model directory is mounted to signal-service at `/workspace/hbot/models`.
Keep the first rollout in shadow mode and verify `hb.ml_signal.v1` before increasing intent authority.

---

## Common Issues & Fixes

### "bitget is not ready" -- connector never becomes ready

**Symptom:** The log repeats `bitget is not ready. Please wait...` indefinitely.

**Root cause:** `ExchangePyBase.ready` requires ALL five conditions to be True:

| Condition | What it checks |
|-----------|---------------|
| `symbols_mapping_initialized` | REST API fetched trading pair symbols |
| `order_books_initialized` | WebSocket order book has data |
| `account_balance` | `len(_account_balances) > 0` |
| `trading_rule_initialized` | REST API fetched trading rules |
| `user_stream_initialized` | Private WebSocket received a message |

The most common blocker is **`account_balance: False`** when the Bitget spot
account is empty.  Even in paper mode, the underlying connector must initialize.

**Fix:** Transfer a small amount (2 USDT) to the Bitget spot account.

**Diagnostic:** Add this to any controller/script to see which condition fails:
```python
for name, conn in self.connectors.items():
    print(f"{name} status_dict={conn.status_dict}")
```

### Controller config missing `id` field

**Symptom:** `status` shows controller name as `nan` and controller never ticks.

**Fix:** Add an explicit `id` to the controller YAML:
```yaml
id: epp_v2_4_bot_a          # <-- add this
controller_name: epp_v2_4
controller_type: market_making
```

### Stale `.pyc` bytecache after controller code changes

**Symptom:** Code changes to mounted `epp_v2_4.py` have no effect. Old errors
repeat despite the source file being updated.

**Fix:** Clear the cache and recreate the container:
```bash
docker exec hbot-bot1 rm -rf /home/hummingbot/controllers/__pycache__ \
    /home/hummingbot/controllers/market_making/__pycache__
docker compose --env-file ../env/.env -f docker-compose.yml up -d --force-recreate bot1
```

`docker restart` alone is NOT sufficient -- it preserves the container's
writable layer where `.pyc` files live.

---

## License

Private infrastructure project. Not for redistribution.
