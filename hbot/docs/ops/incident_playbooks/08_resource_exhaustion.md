# Incident Playbook 08 — Resource Exhaustion (OOM / Disk Full)

**Scenario:** A container or the host is running out of memory (OOM) or disk space, causing bot crashes, slow performance, or data loss.

---

## Trigger Indicators

- Container repeatedly restarting (Restarting/Exited in `docker ps`)
- `dmesg` shows `Out of memory: Killed process` or `oom-killer`
- `df -h` shows filesystem at >90% or 100%
- Bot logs: `MemoryError`, `Killed`, or abrupt process exit
- Prometheus/Grafana panels showing "No data" or scrape failures
- Slow container startup or unresponsive services

---

## Immediate Actions (< 2 minutes)

1. **Check disk usage:**
   ```bash
   df -h
   du -sh hbot/data/bot1/logs/ hbot/reports/ hbot/data/bot1/logs/epp_v24/
   ```

2. **Check for OOM kills:**
   ```bash
   dmesg | grep -i "out of memory\|oom-killer\|killed process" | tail -20
   docker inspect bot1 --format '{{.State.OOMKilled}}'
   docker inspect redis --format '{{.State.OOMKilled}}'
   docker inspect postgres --format '{{.State.OOMKilled}}'
   ```

3. **Identify largest consumers:**
   ```bash
   du -sh hbot/data/bot1/logs/* hbot/reports/* 2>/dev/null | sort -rh | head -15
   ```

4. **If disk is full:** Free space immediately (see Resolution Steps).

---

## Diagnosis Steps

| Symptom | Likely Cause | Check |
|---|---|---|
| OOMKilled=true on bot1 | Bot memory limit (1G) exceeded | `docker inspect bot1 --format '{{.State.OOMKilled}}'`, `docker stats --no-stream` |
| OOMKilled on redis/postgres | DB memory limit exceeded | Check `deploy.resources.limits.memory` in docker-compose |
| Disk 100% on / | Logs, reports, or Docker overlay | `du -sh /var/lib/docker`, `du -sh hbot/data/bot1/logs/` |
| Large minute.csv or fills.csv | Normal growth; check retention | `wc -l hbot/data/bot1/logs/epp_v24/bot1_a/minute.csv` |
| Prometheus/Grafana disk full | TSDB retention too long | `du -sh` on prometheus-data, grafana-data volumes |
| Docker overlay full | Unused images, containers, build cache | `docker system df` |

---

## Resolution Steps

### 1. Immediate space recovery

```bash
# Rotate/truncate oversized log files (preserve last 10MB if needed)
# Check log sizes first
ls -lh hbot/data/bot1/logs/*.log hbot/data/bot1/logs/errors.log 2>/dev/null

# Truncate if safe (only if causing disk full)
# > hbot/data/bot1/logs/errors.log  # CAUTION: loses content

# Run artifact retention (cleans per hbot/config/artifact_retention_policy.json)
cd hbot && python scripts/release/run_artifact_retention.py --apply 2>/dev/null || true

# Docker prune (removes unused images, containers, build cache)
docker system prune -f
docker volume prune -f  # CAUTION: removes unused volumes only
```

### 2. Log rotation

```bash
# If logrotate is configured (hbot/infra/compose/logrotate.d/hbot)
cat hbot/infra/compose/logrotate.d/hbot
# Manual rotate: logrotate -f /etc/logrotate.d/hbot  # if installed on host
```

### 3. Memory limit adjustment in docker-compose.yml

Edit `hbot/infra/compose/docker-compose.yml`:

```yaml
# Under bot1 deploy.resources.limits
deploy:
  resources:
    limits:
      memory: 1536M   # Increase from 1G if OOM frequent
      cpus: "1.0"
```

Then:
```bash
docker compose --env-file hbot/infra/env/.env -f hbot/infra/compose/docker-compose.yml up -d bot1
```

### 4. Prometheus/Grafana storage cleanup

```bash
# Prometheus: reduce retention in config or compact TSDB
# Edit hbot/infra/monitoring/prometheus/prometheus.yml: --storage.tsdb.retention.time

# Grafana: clear old dashboards, reduce datasource query range
# Or prune grafana-data volume if rebuilt
docker exec prometheus ls -la /prometheus  # Check size
```

### 5. Restart affected containers after freeing resources

```bash
docker compose --env-file hbot/infra/env/.env -f hbot/infra/compose/docker-compose.yml restart bot1
# Or restart the OOM-killed service
```

---

## Post-Resolution Verification

- [ ] `df -h` shows >15% free on root and data partitions
- [ ] `docker ps` shows all expected containers running (no Restarting)
- [ ] `docker inspect bot1 --format '{{.State.OOMKilled}}'` returns false
- [ ] `tail -5 hbot/data/bot1/logs/epp_v24/bot1_a/minute.csv` shows recent rows
- [ ] Prometheus and Grafana scraping successfully

---

## Prevention / Long-term

- Run artifact retention on a schedule (cron or daily-ops-reporter): `hbot/config/artifact_retention_policy.json`
- Set log rotation for `hbot/data/bot1/logs/*.log` (e.g. `hbot/infra/compose/logrotate.d/hbot`)
- Monitor disk via Prometheus `HighDiskUsage` / `DiskAlmostFull` alerts in `hbot/infra/monitoring/prometheus/alert_rules.yml`
- Consider increasing VPS disk if growth is steady; optimize retention first
- When to increase VPS resources vs optimize: increase if limits are reasonable and workload is expected; optimize (retention, prune, limits) if growth is from logs/artifacts or misconfiguration
