# Incident Playbook 01 — Bot Stopped Trading

**Scenario:** bot1 is running but placing no orders. State shows `SOFT_PAUSE` or `HARD_STOP` unexpectedly, or `minute.csv` shows zero `orders_active` and no fills for > 5 minutes.

---

## Trigger Indicators

- Grafana panel "Bot State" shows `soft_pause` or `hard_stop` (was `running`)
- `minute.csv`: `state != running` for > 3 consecutive rows
- Watchdog Telegram alert: `bot1 frozen — auto-restarting`
- Zero fills in `fills.csv` for > 30 minutes during market hours
- `reports/kill_switch/latest.json` shows a recent execution

---

## Immediate Actions (< 2 minutes)

1. **Check state and reason:**
   ```bash
   docker logs kzay-capital-bot1 --tail 30 2>&1 | grep -E "HARD_STOP|SOFT_PAUSE|guard|risk"
   ```
2. **Check minute.csv last row:**
   ```bash
   tail -1 hbot/data/bot1/logs/epp_v24/bot1_a/minute.csv
   # Look at: state, risk_reasons, daily_loss_pct, drawdown_pct
   ```
3. **Check if daily loss limit was hit:**
   ```bash
   # In minute.csv: daily_loss_pct >= 0.03 → HARD_STOP expected behavior
   # drawdown_pct >= 0.05 → HARD_STOP expected behavior
   ```
4. **If SOFT_PAUSE (edge gate):** Wait up to `edge_state_hold_s` (120s). Bot resumes automatically when edge recovers. No action required.

---

## Diagnosis Steps

| Symptom | Likely Cause | Check |
|---|---|---|
| `risk_reasons` contains `daily_loss_hard` | Max daily loss hit | Check fills.csv realized PnL |
| `risk_reasons` contains `drawdown_hard` | Max drawdown hit | Check equity_quote trend in minute.csv |
| `risk_reasons` contains `cancel_budget_breach` | > 3 cancel rate breaches | Check cancel_per_min in minute.csv |
| `risk_reasons` contains `edge_gate` | Net edge below threshold | Check net_edge_pct vs edge_pause_threshold_pct |
| `risk_reasons` contains `fee_unresolved` | Fee resolution failed | Check fee_source column — should be api:exchange:* |
| `risk_reasons` contains `margin_low` | Margin ratio below threshold | Check margin_ratio column |
| state=`hard_stop` with no clear reason | Possible crash | Check docker logs for exception |

**For `edge_gate` SOFT_PAUSE:**
```bash
# Verify edge conditions in minute.csv
# net_edge_pct should be < edge_pause_threshold_pct
# Bot will auto-resume when edge recovers
```

**For `hard_stop`:**
```bash
# Inspect last 50 log lines
docker logs kzay-capital-bot1 --tail 50 2>&1
# Check if kill_switch intent was published
cat hbot/reports/kill_switch/latest.json
```

---

## Recovery Steps

### SOFT_PAUSE (edge gate): No action needed
Bot auto-resumes. If pause lasts > 30 minutes, consider reducing `min_net_edge_bps` in config.

### HARD_STOP — Daily Loss Limit:
1. Verify loss is real: compare `daily_loss_pct` in minute.csv with `paper_desk_v2.json` equity.
2. Accept the stop — it worked as designed.
3. Wait for UTC midnight rollover (bot resets daily counters and resumes).
4. Investigate fill quality in `fills.csv` for adverse selection patterns.

### HARD_STOP — Cancel Budget Breach:
1. Bot enters HARD_STOP after 3 breaches of `cancel_budget_per_min: 50`.
2. Restart bot: `docker compose --env-file hbot/env/.env -f hbot/compose/docker-compose.yml restart bot1`
3. If recurring: reduce `max_active_executors` or increase `executor_refresh_time` in config.

### HARD_STOP — Fee Unresolved:
1. Check exchange API key connectivity.
2. Restart bot with valid API key.
3. If API key is expired: rotate per `docs/ops/secrets_and_key_rotation.md`.

### HARD_STOP — Unknown / Unexpected:
1. Capture full logs: `docker logs kzay-capital-bot1 > /tmp/bot1_incident.log 2>&1`
2. Check for exceptions: `grep -i "error\|exception\|traceback" /tmp/bot1_incident.log | tail -20`
3. If crash without recovery: `docker compose --env-file hbot/env/.env ... restart bot1`

---

## Post-Incident Review

- [ ] Root cause identified and documented
- [ ] Was the stop correct (real risk event) or false positive?
- [ ] If false positive: update config thresholds and document in `docs/strategy/bot1_epp_v2_4_iteration_log.md`
- [ ] Are fills.csv and daily_state.json intact? Run reconciliation check.
- [ ] Update this playbook if a new failure mode was encountered
