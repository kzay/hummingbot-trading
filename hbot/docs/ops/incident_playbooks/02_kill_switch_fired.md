# Incident Playbook 02 — Kill Switch Fired

**Scenario:** `kzay-capital-kill-switch` executed a cancel-all on the exchange. `reports/kill_switch/latest.json` shows `trigger: execution_intent` or `trigger: api` with `result.status: executed`.

---

## Trigger Indicators

- Telegram alert: kill switch fired
- `reports/kill_switch/latest.json`: `result.status = executed` with recent timestamp
- bot1 logs: `HARD_STOP transition detected — kill_switch intent published`
- Exchange order book: all open orders cancelled
- `minute.csv`: state transitions to `hard_stop`

---

## Immediate Actions (< 2 minutes)

1. **Confirm kill switch executed successfully:**
   ```bash
   cat hbot/reports/kill_switch/latest.json
   # Check: result.status, result.cancelled (list of cancelled order IDs), result.error
   ```

2. **Check position is flat:**
   ```bash
   # In paper mode: check paper_desk_v2.json
   cat hbot/data/bot1/logs/epp_v24/bot1_a/paper_desk_v2.json | python -m json.tool | grep -A5 "position"
   # In live mode: log into exchange and verify positions
   ```

3. **Do NOT restart bot immediately.** Understand why the kill switch fired first.

4. **Check what triggered it:**
   ```bash
   docker logs kzay-capital-bot1 --tail 50 2>&1 | grep -E "HARD_STOP|kill_switch|guard"
   tail -5 hbot/data/bot1/logs/epp_v24/bot1_a/minute.csv
   ```

---

## Diagnosis Steps

| kill_switch.json field | Meaning |
|---|---|
| `trigger: execution_intent` | Fired by hb_bridge detecting HARD_STOP in controller |
| `trigger: api` | Fired directly via HTTP POST to kill_switch service |
| `result.status: executed` | Orders were successfully cancelled |
| `result.status: error: missing_credentials` | Kill switch has no real API key — orders NOT cancelled (paper mode) |
| `result.status: dry_run` | `KILL_SWITCH_DRY_RUN=true` — no real cancellation happened |

**Determine root cause in controller:**
```bash
# Look for what caused HARD_STOP in minute.csv risk_reasons
tail -20 hbot/data/bot1/logs/epp_v24/bot1_a/minute.csv | cut -d',' -f<risk_reasons_column>
# Typical causes: daily_loss_hard, drawdown_hard, cancel_budget_breach, external_kill_switch
```

**In live mode — verify all orders cancelled:**
- Log into Bitget and confirm no open orders remain.
- If orders were NOT cancelled (kill switch failed): manually cancel via exchange UI immediately.

---

## Recovery Steps

### Step 1: Assess and document the incident
1. Record timestamp, trigger reason, and position at time of trigger.
2. Compute PnL impact: compare `equity_quote` before and after in `minute.csv`.

### Step 2: Verify flat position
- Paper: `paper_desk_v2.json` `quantity` should be 0 for all instruments.
- Live: exchange position page shows 0 open positions.

### Step 3: Resume trading (only after root cause is understood)
1. If stop was correct (real risk limit breach): wait for UTC midnight rollover.
2. If false positive: fix the underlying issue, restart bot:
   ```bash
   docker compose --env-file hbot/infra/env/.env -f hbot/infra/compose/docker-compose.yml restart bot1
   ```
3. If kill switch had `KILL_SWITCH_DRY_RUN=true` in live mode: **this is a critical gap** — set `KILL_SWITCH_DRY_RUN=false` and add real API credentials before resuming.

### Step 4: Validate kill switch credentials (live mode only)
```bash
# Confirm kill switch has active API key
docker exec kzay-capital-kill-switch env | grep KILL_SWITCH
# KILL_SWITCH_API_KEY and KILL_SWITCH_SECRET must be non-empty
# KILL_SWITCH_DRY_RUN must be false
```

---

## Post-Incident Review

- [ ] Root cause of HARD_STOP confirmed
- [ ] All positions confirmed flat on exchange
- [ ] Kill switch executed correctly (not dry-run, not missing credentials)
- [ ] Incident logged in `docs/ops/incident_log.md` with timestamp + evidence
- [ ] Go-live checklist item 3 (Kill Switch) evidence updated if this was a planned test
- [ ] If recurring false positive: adjust risk thresholds and document
