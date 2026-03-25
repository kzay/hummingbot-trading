# Incident Playbook 12 — Metrics Exporter Failure

**Scenario:** The `kzay-capital-metrics-exporter` service has stopped responding, is failing to scrape, or is returning stale/empty metrics. Prometheus alerts fire indicating scrape failures.

---

## Trigger Indicators

- Prometheus alert `MetricsExporterScrapeFailed` fires (absent or zero `scrape_duration_seconds`)
- Prometheus targets page shows metrics-exporter as `DOWN`
- Grafana dashboards dependent on custom metrics show "No data" or flat lines
- `docker logs kzay-capital-metrics-exporter` shows errors or no recent output

---

## Immediate Actions (< 2 minutes)

1. **Check exporter status:**
   ```bash
   docker ps --filter name=kzay-capital-metrics-exporter --format "{{.Status}}"
   docker logs kzay-capital-metrics-exporter --tail 30 2>&1
   ```

2. **Check if metrics endpoint responds:**
   ```bash
   curl -s http://localhost:9101/metrics | head -20
   # Should return Prometheus-formatted metrics
   ```

3. **Check trading impact:** The metrics exporter is purely observational. Bot trading, paper engine, and all critical services are unaffected.

---

## Impact Assessment

| Component | Impact when metrics-exporter is down |
|---|---|
| Bot trading | **None** — exporter is read-only observability |
| Prometheus scraping | Custom metrics stop updating; built-in metrics (cAdvisor, node) still work |
| Grafana custom panels | Panels using exporter metrics show stale or "No data" |
| Alerting | Alerts dependent on exporter metrics stop evaluating |
| Redis / Postgres | **Unaffected** |

---

## Recovery Steps

### 1. Restart the metrics exporter
```bash
docker compose --env-file hbot/infra/env/.env -f hbot/infra/compose/docker-compose.yml \
  restart metrics-exporter
sleep 10
```

### 2. Verify the metrics endpoint is serving
```bash
curl -s http://localhost:9101/metrics | grep -c "^hbot_"
# Should return a positive count of custom metrics
```

### 3. Verify Prometheus is scraping successfully
```bash
curl -s http://localhost:9090/api/v1/targets | grep -A5 "metrics_exporter"
# health should show "up"
```

### 4. Check Grafana dashboards
Verify that dashboards using exporter metrics (bot PnL, fill rates, position sizes) are rendering current data.

---

## Common Failure Causes

1. **Postgres connection failure**: If exporter queries Postgres and Postgres is down, the exporter may crash or hang. Fix Postgres first (see Playbook 11).
2. **Redis connection failure**: If exporter reads from Redis streams and Redis is unreachable.
3. **OOM kill**: Check `docker inspect kzay-capital-metrics-exporter --format '{{.State.OOMKilled}}'`
4. **Query timeout**: Slow SQL queries against Postgres can cause the exporter to miss scrape deadlines (default 10s).
5. **Port conflict**: Another process binding to port 9101.

---

## Diagnostic Commands

```bash
# Check container resource usage
docker stats kzay-capital-metrics-exporter --no-stream

# Check restart count
docker inspect kzay-capital-metrics-exporter --format '{{.RestartCount}}'

# Check if port is bound
docker port kzay-capital-metrics-exporter

# Full container logs (last 100 lines)
docker logs kzay-capital-metrics-exporter --tail 100 2>&1
```

---

## Post-Incident Review

- [ ] Root cause identified (OOM? Postgres down? query timeout? config error?)
- [ ] Total metrics gap duration recorded
- [ ] Confirm all Grafana panels recovered
- [ ] If query timeout: optimize slow SQL queries or add query timeouts
- [ ] If OOM: increase memory limit in docker-compose.yml
- [ ] Consider adding a dedicated health endpoint for the exporter
