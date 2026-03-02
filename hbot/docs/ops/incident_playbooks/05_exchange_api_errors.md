# Incident Playbook 05 — Exchange API Errors (429 / 5xx)

**Scenario:** Bot is receiving 429 (rate limit exceeded) or 5xx (exchange server errors) from Bitget API. Orders are failing, order book updates are delayed, or bot enters `soft_pause`.

---

## Trigger Indicators

- `docker logs hbot-bot1`: `429 Too Many Requests` or `5xx` errors
- `minute.csv`: `ws_reconnect_count` increasing rapidly
- `minute.csv`: `order_book_stale: True` for > 30 seconds
- `minute.csv`: `cancel_per_min` exceeding `cancel_budget_per_min: 50`
- `minute.csv` state: `soft_pause` with `risk_reasons: cancel_budget_breach` or `order_ack_timeout`
- Fills stop completely during exchange maintenance window

---

## Immediate Actions (< 2 minutes)

1. **Check bot logs for error type:**
   ```bash
   docker logs hbot-bot1 --tail 50 2>&1 | grep -iE "429|503|502|504|rate.limit|too many"
   ```

2. **Check current rate limit headroom:**
   ```bash
   tail -3 hbot/data/bot1/logs/epp_v24/bot1_a/minute.csv
   # cancel_per_min should be < 50
   # If cancel_budget_breach in risk_reasons: bot will HARD_STOP after 3 breaches
   ```

3. **Check exchange status:**
   - Visit https://status.bitget.com (or https://www.bitgetstatus.com)
   - Check Telegram/X for Bitget maintenance announcements

4. **For 429 — reduce order activity:**
   - Bot will self-throttle via `cancel_budget_per_min`. No immediate action required.
   - If `HARD_STOP` from cancel_budget_breach: wait for midnight rollover or restart.

5. **For 5xx or WS disconnect — wait and monitor:**
   - Hummingbot auto-reconnects WebSocket.
   - `ws_reconnect_count` in minute.csv will increment.
   - If exchange is down: bot enters `soft_pause` due to `order_book_stale` after 30s.

---

## Diagnosis Steps

**429 Rate Limit Analysis:**
```bash
# Check cancel rate over time
grep "cancel_per_min" hbot/data/bot1/logs/epp_v24/bot1_a/minute.csv | tail -20
# If consistently near 50: reduce max_active_executors or increase executor_refresh_time

# Check order placement rate  
grep -c "" hbot/data/bot1/logs/epp_v24/bot1_a/fills.csv  # total fills
# High fills/hour relative to equity = high cancel rate
```

**WebSocket Disconnect (5xx / connectivity):**
```bash
# Check reconnect count over time
tail -20 hbot/data/bot1/logs/epp_v24/bot1_a/minute.csv | grep -o "ws_reconnect_count,[0-9]*"
# Reconnect count > 5 in a session suggests unstable connection

# Check order_book_stale
tail -5 hbot/data/bot1/logs/epp_v24/bot1_a/minute.csv | grep order_book_stale
# True = stale book → bot pauses automatically (correct behavior)
```

**Check for IP ban or API key suspension:**
```bash
docker logs hbot-bot1 2>&1 | grep -iE "ban|forbidden|unauthorized|invalid.*key"
# If present: API key may be suspended — rotate per secrets_and_key_rotation.md
```

---

## Recovery Steps

### 429 Rate Limit (temporary):
The bot self-throttles. No action unless HARD_STOP occurs.

If HARD_STOP from cancel_budget_breach:
1. Wait for UTC midnight rollover (counters reset automatically).
2. Or restart bot if situation is urgent: `docker compose ... restart bot1`
3. After recovery, reduce order churn: lower `max_active_executors` to 20, increase `executor_refresh_time` to 200.

### Exchange 5xx / WS Disconnection:
1. Hummingbot auto-reconnects. Wait 2-5 minutes.
2. Verify reconnect: `docker logs hbot-bot1 --tail 10 2>&1 | grep -i "connected\|reconnect"`
3. If reconnect fails after 5 minutes: `docker compose ... restart bot1`

### Exchange Maintenance Window:
1. Bot will auto-pause (order_book_stale after 30s). No action needed.
2. After maintenance ends: bot auto-resumes on next tick when book becomes fresh.
3. Verify: `minute.csv` `order_book_stale` goes back to `False`.

### API Key Issues:
1. Rotate key per `docs/ops/secrets_and_key_rotation.md`.
2. Verify new key has trade + read permissions but NOT withdrawal.
3. Recreate bot: `docker compose --env-file hbot/env/.env ... up -d --no-deps bot1`

---

## Prevention

| Action | Config/Code |
|---|---|
| Reduce cancel rate | Lower `max_active_executors` (default 30 → try 15) |
| Reduce order frequency | Increase `executor_refresh_time` (150 → 200) |
| Add circuit breaker for 429 | Built into Hummingbot rate limiter — no code change needed |
| Increase cancel budget | Raise `cancel_budget_per_min` (50 → 80) if exchange allows |

---

## Post-Incident Review

- [ ] Duration of disruption recorded
- [ ] Number of fills missed during disruption estimated
- [ ] Rate limit headroom confirmed adequate after config changes
- [ ] Exchange status page checked — was this exchange-wide or account-specific?
- [ ] Update cancel budget / executor settings if needed
