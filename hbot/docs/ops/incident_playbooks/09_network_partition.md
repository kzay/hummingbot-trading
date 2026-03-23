# Incident Playbook 09 — Network Partition / External API Failure

**Scenario:** The VPS loses connectivity to exchange APIs, Redis, or other external services. Bots may enter stale-book / soft-pause state.

---

## Trigger Indicators

- `minute.csv`: `order_book_stale: True` for > 30 seconds
- `minute.csv`: `state: soft_pause` with `risk_reasons: order_book_stale` or `ws_reconnect`
- `minute.csv`: `ws_reconnect_count` increasing rapidly
- Bot logs: `Connection refused`, `timeout`, `xread failed`, `Redis stream client disabled`
- Exchange API: 5xx errors, WebSocket disconnect, or no order book updates
- Grafana: "No data" for exchange-dependent panels

---

## Immediate Actions (< 2 minutes)

1. **Check exchange API connectivity:**
   ```bash
   curl -s -o /dev/null -w "%{http_code}" https://api.bitget.com/api/v2/public/time
   # 200 = OK
   nslookup api.bitget.com
   ping -c 3 api.bitget.com 2>/dev/null || true
   ```

2. **Check Redis inter-container connectivity:**
   ```bash
   docker exec bot1 python -c "import redis; r=redis.Redis(host='redis', port=6379); print(r.ping())" 2>/dev/null || echo "Redis unreachable from bot1"
   docker exec redis redis-cli ping
   ```

3. **Check bot state and order book staleness:**
   ```bash
   tail -3 hbot/data/bot1/logs/epp_v24/bot1_a/minute.csv
   # Look at: order_book_stale, state, risk_reasons, ws_reconnect_count
   ```

4. **Check VPS firewall/iptables:**
   ```bash
   iptables -L -n 2>/dev/null | head -30
   # Ensure no rules blocking outbound 443, 6379, or exchange IPs
   ```

---

## Diagnosis Steps

| Symptom | Likely Cause | Check |
|---|---|---|
| order_book_stale=True | Exchange WS disconnected or delayed | `docker logs bot1 --tail 30 \| grep -i "ws\|reconnect\|disconnect"` |
| Redis unreachable from bot1 | Network partition, Redis down, wrong REDIS_HOST | `docker network inspect kzay-capital-trading` |
| Exchange 5xx / timeout | Exchange maintenance, rate limit, or network path issue | https://status.bitget.com |
| Connection refused to redis | Redis container stopped or wrong port | `docker ps --filter name=redis` |
| DNS resolution failure | VPS DNS misconfigured | `cat /etc/resolv.conf`, `nslookup api.bitget.com` |
| Orphaned orders after partition | Bot paused but orders left on exchange | Check exchange UI; reconcile with `fills.csv` |

---

## Resolution Steps

### 1. Exchange API connectivity

- **Exchange maintenance:** Check https://status.bitget.com. Bot auto-pauses on `order_book_stale`; auto-resumes when book is fresh. No action needed.
- **Temporary 5xx:** Wait 2–5 minutes. Hummingbot auto-reconnects WebSocket.
- **Persistent failure:** Restart bot to force reconnect:
  ```bash
  docker compose --env-file hbot/infra/env/.env -f hbot/infra/compose/docker-compose.yml restart bot1
  ```

### 2. Redis inter-container connectivity

```bash
# Restart Redis if down
docker compose --env-file hbot/infra/env/.env -f hbot/infra/compose/docker-compose.yml restart redis
sleep 10
docker exec redis redis-cli ping

# Restart dependent services to reconnect
docker compose --env-file hbot/infra/env/.env -f hbot/infra/compose/docker-compose.yml --profile external restart signal-service risk-service kill-switch event-store-service coordination-service
```

### 3. VPS firewall or iptables

```bash
# If outbound blocked, allow exchange and Redis
# iptables -A OUTPUT -p tcp --dport 443 -j ACCEPT
# iptables -A OUTPUT -p tcp --dport 6379 -j ACCEPT
# (Adjust per your firewall setup)
```

### 4. Order book staleness — manual vs automatic recovery

- **Automatic:** Bot enters `soft_pause` when `order_book_stale` > 30s. When WS reconnects and book is fresh, bot auto-resumes. No manual action.
- **Manual:** If reconnect fails after 5+ minutes:
  ```bash
  docker compose --env-file hbot/infra/env/.env -f hbot/infra/compose/docker-compose.yml restart bot1
  ```

### 5. Verifying WS reconnect behavior

```bash
docker logs bot1 --tail 50 2>&1 | grep -iE "connected|reconnect|websocket|ws"
# Expect: reconnection messages, then "connected" or similar
```

### 6. Checking for orphaned orders after partition

```bash
# Compare exchange open orders with bot state
# Paper: check paper_desk_v2.json
# Live: use exchange UI or API to list open orders
# Reconcile with hbot/data/bot1/logs/epp_v24/bot1_a/fills.csv
```

---

## Post-Resolution Verification

- [ ] `tail -3 hbot/data/bot1/logs/epp_v24/bot1_a/minute.csv` shows `order_book_stale: False`, `state: running`
- [ ] `ws_reconnect_count` stable (not increasing every minute)
- [ ] Redis: `docker exec redis redis-cli ping` returns PONG
- [ ] Exchange API: `curl -s https://api.bitget.com/api/v2/public/time` returns 200
- [ ] No orphaned orders on exchange (live mode)

---

## Prevention / Long-term

- Monitor `order_book_stale` and `ws_reconnect_count` in Grafana
- Subscribe to exchange status/maint announcements (Bitget Telegram, status page)
- Ensure VPS has stable outbound connectivity; consider redundant network path
- Set `HB_BITGET_WS_HEARTBEAT_S`, `HB_BITGET_WS_MESSAGE_TIMEOUT_S` in env for faster stale detection
