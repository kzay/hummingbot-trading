# Incident Playbook 07 — Disaster Recovery (Full Stack)

**Scenario:** Complete infrastructure failure — VPS down, all containers stopped, data corruption, or need to restore from scratch.

---

## Trigger Indicators

- VPS unreachable (SSH timeout, no response)
- All containers stopped or exited unexpectedly
- Docker volumes corrupted or missing
- Redis/Postgres data directories empty or corrupted
- Bot state files (`minute.csv`, `fills.csv`, `daily_state_*.json`) missing or truncated
- Grafana dashboards blank or datasources unreachable
- Need to restore from backup after hardware failure or migration

---

## Immediate Actions (< 2 minutes)

1. **Verify VPS reachability:**
   ```bash
   ping <vps-ip>
   ssh user@<vps-ip> "echo ok"
   ```

2. **Check Docker and container status:**
   ```bash
   docker ps -a
   docker compose --env-file hbot/infra/env/.env -f hbot/infra/compose/docker-compose.yml ps -a
   ```

3. **Verify critical data paths exist:**
   ```bash
   ls -la hbot/data/bot1/logs/epp_v24/bot1_a/minute.csv
   ls -la hbot/data/bot1/logs/epp_v24/bot1_a/fills.csv
   ls -la hbot/reports/
   ```

4. **If VPS is down:** Contact hosting provider. Document outage start time. Proceed to restore on new VPS when access is restored.

---

## Diagnosis Steps

| Symptom | Likely Cause | Check |
|---|---|---|
| Containers all exited | Host reboot, OOM, or manual stop | `dmesg \| grep -i oom`, `uptime` |
| Volume data missing | Wrong mount path, volume not restored | `docker volume ls`, `ls -la hbot/data/` |
| Redis empty | Redis data dir not persisted or corrupted | `docker exec redis redis-cli dbsize` |
| Postgres unreachable | Postgres data dir corrupted or not restored | `docker logs postgres --tail 50` |
| minute.csv truncated | Bot crashed mid-write, no backup | `wc -l hbot/data/bot1/logs/epp_v24/bot1_a/minute.csv` |
| Grafana no data | Prometheus/Postgres down or datasource misconfigured | Check Grafana datasource config |

---

## Resolution Steps

### 1. Service startup ordering (critical)

Start services in this order to avoid dependency failures:

```bash
cd hbot
# 1. Redis first (signal, risk, kill_switch depend on it)
docker compose --env-file infra/env/.env -f infra/compose/docker-compose.yml up -d redis
sleep 10
docker exec redis redis-cli ping  # Expect PONG

# 2. Postgres second (ops-db-writer, Grafana, reconciliation depend on it)
docker compose --env-file infra/env/.env -f infra/compose/docker-compose.yml up -d postgres
sleep 15
docker exec postgres pg_isready -U postgres

# 3. Core services (signal, risk, kill_switch, event-store, etc.)
docker compose --env-file infra/env/.env -f infra/compose/docker-compose.yml --profile external up -d

# 4. Bots last
docker compose --env-file infra/env/.env -f infra/compose/docker-compose.yml up -d bot1
```

### 2. Docker volumes and bind mounts restore

If using bind mounts (default for `hbot/data/`, `hbot/reports/`):
- Restore from backup into `hbot/data/bot1/`, `hbot/data/bot1/logs/`, etc.
- Verify paths match compose: `hbot/data/bot1/conf`, `hbot/data/bot1/logs`, `hbot/data/bot1/data`

If using Docker volumes (`redis-data`, `postgres-data`, `prometheus-data`, `grafana-data`):
```bash
# Restore volume from backup (example: postgres)
docker run --rm -v postgres-data:/restore -v /path/to/backup:/backup alpine sh -c "cd /restore && tar xvf /backup/postgres_backup.tar"
```

### 3. Redis state recovery vs JSON fallback

- **Redis:** If Redis data is lost, Redis starts empty. Event store and signal services will use JSONL fallback if configured.
- **JSON fallback:** Check `hbot/reports/event_store/*.jsonl` for events written during Redis outage.
- **No Redis restore needed for trading:** Bot and paper engine are Redis-independent. Trading resumes when bot starts.

### 4. Postgres data restore

```bash
# If you have a pg_dump backup
docker exec -i postgres psql -U postgres < /path/to/backup.sql

# Verify
docker exec postgres psql -U postgres -c "\dt"
```

### 5. Bot state verification after restore

```bash
# Verify minute.csv has recent data
tail -5 hbot/data/bot1/logs/epp_v24/bot1_a/minute.csv

# Verify fills.csv integrity (no truncated lines)
tail -3 hbot/data/bot1/logs/epp_v24/bot1_a/fills.csv

# Verify daily_state exists
ls -la hbot/data/bot1/logs/epp_v24/bot1_a/daily_state_*.json

# Verify paper desk state
cat hbot/data/bot1/logs/epp_v24/bot1_a/paper_desk_v2.json | head -20
```

### 6. Grafana dashboard restore

- Dashboards are stored in `grafana-data` volume or provisioned via config.
- If Grafana was reset: re-import dashboards from `hbot/infra/monitoring/grafana/` or backup.
- Verify datasources: Prometheus and Postgres must be reachable.

### 7. When to reset vs restore state

| Situation | Action |
|---|---|
| Clean restart, no data loss | Start services normally — no restore |
| minute.csv/fills.csv corrupted | Restore from backup; if no backup, reset (new session, loss of history) |
| Redis/Postgres data lost | Start fresh; bot will create new state. Restore from backup only if backup exists |
| Config files corrupted | Restore from git: `git checkout HEAD -- hbot/data/bot1/conf/` |

### 8. DNS/firewall verification for remote access

```bash
# Verify SSH
nc -zv <vps-ip> 22

# Verify Docker API if remote (optional)
# Verify Grafana/Alertmanager ports if exposed
nc -zv <vps-ip> 3000  # Grafana
nc -zv <vps-ip> 9093  # Alertmanager
```

---

## Post-Resolution Verification

- [ ] All containers running: `docker ps` shows expected services
- [ ] Redis: `docker exec redis redis-cli ping` returns PONG
- [ ] Postgres: `docker exec postgres pg_isready -U postgres` returns accepting connections
- [ ] Bot1 minute.csv updating: `tail -1 hbot/data/bot1/logs/epp_v24/bot1_a/minute.csv` has recent timestamp
- [ ] fills.csv and minute.csv row counts consistent with pre-incident
- [ ] Grafana panels showing data
- [ ] Reconciliation check passed: `python hbot/scripts/reconciliation/run_reconciliation.py` (if available)

---

## RPO / RTO Estimates

| Data Store | RPO (max data loss) | RTO (time to restore) | Notes |
|---|---|---|---|
| Redis streams | ~0 (AOF appendfsync everysec) | < 2 min (auto-start, AOF replay) | If AOF corrupted: start fresh, no trading impact |
| Postgres (ops DB) | Last pg_dump interval (default: none) | 5-15 min (restore from dump) | Historical fills/PnL only; bot operation unaffected |
| Bot state (minute.csv, fills.csv) | ~0 (flushed every tick, ~1-5s) | < 1 min (files on bind mount) | If corrupted: bot starts fresh session |
| Paper desk state (paper_desk_v2.json) | ~0 (persisted on fill/tick) | < 1 min (file on bind mount) | If missing: paper engine reinitializes with zero positions |
| Prometheus TSDB | ~15s (scrape interval) | < 2 min (auto-start, WAL replay) | 30d retention; if volume lost, metrics history lost |
| Grafana dashboards | N/A (provisioned from git) | < 1 min (auto-provisioned) | Custom changes in `grafana-data` volume need backup |
| Event store JSONL | ~1s (buffered flush + critical sync) | < 1 min (file on bind mount) | Append-only; truncation loses tail events only |

**Target SLA:** RTO < 15 min for full stack restart from clean shutdown. RTO < 30 min for restore from backup after data loss.

---

## Prevention / Long-term

- Schedule daily backups of `hbot/data/`, `hbot/reports/`, and Docker volumes (`redis-data`, `postgres-data`)
- Document backup/restore procedure and test quarterly
- Use logrotate for `hbot/data/bot1/logs/*.log` to avoid disk fill
- Consider off-VPS backup (S3, rsync to secondary host)
- Run artifact retention to avoid unbounded growth: `python hbot/scripts/release/run_artifact_retention.py --apply` (or use `artifact-retention` service in `infra/compose/docker-compose.yml`)
