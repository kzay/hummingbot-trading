# Incident Playbook 03 — Redis Down Mid-Session

**Scenario:** `kzay-capital-redis` container stopped, crashed, or became unreachable. Services depending on Redis (signal_service, risk_service, kill_switch, coordination, event_store) are affected.

---

## Trigger Indicators

- `docker ps` shows `kzay-capital-redis` in `Restarting` or `Exited` state
- Bot logs: `Redis stream client disabled` or `xread failed (Redis may be down)`
- `reports/risk_service/latest.json`: `redis_stream_enabled: false` (if was previously true)
- `reports/event_store/*.jsonl` files being written (fallback JSONL path active)
- Control-plane services showing errors in `docker logs`
- Grafana: Redis-dependent panels showing "No data"

---

## Immediate Actions (< 2 minutes)

1. **Confirm Redis is down:**
   ```bash
   docker ps --filter name=kzay-capital-redis --format "{{.Status}}"
   docker logs kzay-capital-redis --tail 20 2>&1
   ```

2. **Is bot1 still trading?** The controller and paper engine are Redis-independent. Check:
   ```bash
   # minute.csv should still be written if bot is running
   # Look at mtime of minute.csv
   docker exec kzay-capital-bot1 ls -la /home/hummingbot/logs/epp_v24/bot1_a/minute.csv
   ```
   If bot is still trading: **trading continues normally** (Redis is a side-channel, not on critical path).

3. **Restart Redis:**
   ```bash
   docker compose --env-file hbot/infra/env/.env -f hbot/infra/compose/docker-compose.yml restart redis
   ```

4. **Verify Redis recovered:**
   ```bash
   docker exec kzay-capital-redis redis-cli ping
   # Expected: PONG
   ```

---

## Impact Assessment

| Component | Impact when Redis is down |
|---|---|
| bot1 trading | **None** — paper engine and order placement are Redis-independent |
| Signal routing (inventory_rebalance) | Paused — signals not consumed, bot uses last override or defaults |
| Kill switch via Redis intent | Cannot receive intents — **this is a safety gap in live mode** |
| Event store ingestion | Falls back to local JSONL files (no data loss) |
| Risk service | No signal gate processing |
| Coordination service | No multi-bot coordination |
| Telegam/alertmanager | Unaffected (not Redis-dependent) |

---

## Recovery Steps

### 1. Restart Redis and verify health
```bash
docker compose --env-file hbot/infra/env/.env -f hbot/infra/compose/docker-compose.yml restart redis
sleep 10
docker exec kzay-capital-redis redis-cli ping  # should return PONG
docker ps --filter name=kzay-capital-redis     # should show (healthy)
```

### 2. Restart dependent services to reconnect consumer groups
```bash
docker compose --env-file hbot/infra/env/.env -f hbot/infra/compose/docker-compose.yml \
  --profile external restart \
  signal-service risk-service kill-switch event-store-service coordination-service
```

### 3. Verify signal pipeline resumed
```bash
# Check signal_service is publishing
docker logs kzay-capital-signal-service --tail 20 2>&1
# Should see: xadd to hb.signal.v1
```

### 4. Process fallback JSONL files (if event_store missed entries)
```bash
# Fallback fills were written to reports/event_store/events_YYYYMMDD.jsonl
# Event store service will reprocess on restart if consumer groups are reset
ls -la hbot/reports/event_store/
```

### 5. Verify state continuity
After Redis restart, confirm daily state is intact:
```bash
cat hbot/data/bot1/logs/epp_v24/bot1_a/daily_state_*.json | tail -1
# Check: fills count, traded notional, realized_pnl match minute.csv last row
```

---

## Live Mode — Additional Steps

In live mode, Redis downtime means the kill switch CANNOT receive intents via Redis. If a HARD_STOP occurs while Redis is down:
- The hb_bridge will publish the intent — but Redis is unreachable, so it will fail silently.
- **The kill switch HTTP endpoint still works:** `POST http://localhost:9900/kill` (direct HTTP, Redis-independent).
- If concerned about open positions: `curl -X POST http://localhost:9900/kill` immediately.

---

## Post-Incident Review

- [ ] Redis restart reason identified (OOM? disk full? container restart? host reboot?)
- [ ] Total Redis downtime recorded
- [ ] Were any fills missed during downtime? (check event_store JSONL vs fills.csv)
- [ ] Daily state integrity confirmed after recovery
- [ ] If Redis is on same host: consider moving to dedicated VM or add health monitoring
- [ ] Add Redis OOM/disk check to daily ops report
