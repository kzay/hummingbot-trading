# Incident Playbook 11 — Postgres Down

**Scenario:** The `kzay-capital-postgres` container has stopped, crashed, or become unreachable. Services depending on Postgres (ops-db-writer, metrics-exporter, any analytics queries) are affected.

---

## Trigger Indicators

- Prometheus alert `PostgresDown` fires (absence of cAdvisor metrics for `postgres` container)
- `docker ps` shows `kzay-capital-postgres` in `Restarting`, `Exited`, or absent state
- `ops-db-writer` logs: connection errors or write failures
- `metrics-exporter` logs: SQL query failures
- Grafana panels backed by Postgres showing "No data" or query timeouts

---

## Immediate Actions (< 2 minutes)

1. **Confirm Postgres is down:**
   ```bash
   docker ps --filter name=kzay-capital-postgres --format "{{.Status}}"
   docker logs kzay-capital-postgres --tail 30 2>&1
   ```

2. **Check trading impact:** Postgres is NOT on the trading hot path. Bot controllers, paper engine, and Redis streams operate independently.

3. **Restart Postgres:**
   ```bash
   docker compose --env-file hbot/infra/env/.env -f hbot/infra/compose/docker-compose.yml restart postgres
   ```

4. **Verify Postgres recovered:**
   ```bash
   docker exec kzay-capital-postgres pg_isready -U $POSTGRES_USER
   # Expected: accepting connections
   ```

---

## Impact Assessment

| Component | Impact when Postgres is down |
|---|---|
| Bot trading | **None** — trading, paper engine, and signal pipeline are Postgres-independent |
| ops-db-writer | Writes stall — events queue in Redis until Postgres recovers |
| metrics-exporter | SQL-backed metrics stop updating; Prometheus scrapes return stale data |
| Grafana historical dashboards | Panels querying Postgres show "No data" or errors |
| Redis streams | **Unaffected** — Redis is independent |
| Daily/weekly reports | Reports that read from Postgres will fail until recovery |

---

## Recovery Steps

### 1. Restart Postgres and verify health
```bash
docker compose --env-file hbot/infra/env/.env -f hbot/infra/compose/docker-compose.yml restart postgres
sleep 15
docker exec kzay-capital-postgres pg_isready -U $POSTGRES_USER
docker ps --filter name=kzay-capital-postgres  # should show (healthy)
```

### 2. Check for data directory corruption
```bash
docker logs kzay-capital-postgres --tail 50 2>&1 | grep -i "corrupt\|error\|fatal\|panic"
```
If corruption is detected, restore from the latest backup before proceeding.

### 3. Restart dependent services
```bash
docker compose --env-file hbot/infra/env/.env -f hbot/infra/compose/docker-compose.yml \
  restart ops-db-writer metrics-exporter
```

### 4. Verify ops-db-writer is draining queued events
```bash
docker logs kzay-capital-ops-db-writer --tail 20 2>&1
# Should see successful write batches resuming
```

### 5. Verify metrics-exporter is serving data
```bash
curl -s http://localhost:9101/metrics | head -20
# Should see non-empty Prometheus metrics output
```

---

## Root Cause Investigation

Common causes of Postgres outages:
- **OOM kill**: Check `docker inspect kzay-capital-postgres --format '{{.State.OOMKilled}}'`
- **Disk full**: Check `docker exec kzay-capital-postgres df -h /var/lib/postgresql/data`
- **WAL accumulation**: Check `docker exec kzay-capital-postgres du -sh /var/lib/postgresql/data/pg_wal/`
- **Shared memory**: Insufficient `shared_buffers` or `work_mem` causing crashes

---

## Post-Incident Review

- [ ] Postgres restart reason identified (OOM? disk? config error?)
- [ ] Total downtime recorded
- [ ] ops-db-writer backlog fully drained after recovery
- [ ] Grafana dashboards confirmed operational
- [ ] If OOM: increase `deploy.resources.limits.memory` in docker-compose.yml
- [ ] If disk: add WAL archiving or increase volume size
