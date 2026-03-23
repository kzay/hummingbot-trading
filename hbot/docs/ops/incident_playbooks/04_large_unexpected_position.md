# Incident Playbook 04 — Large Unexpected Position

**Scenario:** `position_base` in `minute.csv` is significantly larger than expected (> 2× `max_base_pct` of equity), or there is a large position on exchange that doesn't match the paper/local state.

---

## Trigger Indicators

- `minute.csv`: `position_base` significantly non-zero when it should be flat (e.g., > 2× max_base_pct)
- Reconciliation alert: `position_drift_pct > 0.05` in `minute.csv`
- `reports/reconciliation/latest.json`: `inventory_drift_pct > critical_threshold`
- `minute.csv` state: `soft_pause` with `risk_reasons: position_drift_high`
- Exchange account shows unexpected open position (live mode only)

---

## Immediate Actions (< 2 minutes)

1. **Quantify the position:**
   ```bash
   # Get latest position from minute.csv
   tail -1 hbot/data/bot1/logs/epp_v24/bot1_a/minute.csv
   # Look at: position_base, avg_entry_price, equity_quote, base_pct
   ```

2. **Is the bot in SOFT_PAUSE or HARD_STOP?** If yes: good — risk controls fired correctly.

3. **Estimate unrealized PnL:**
   ```
   unrealized = (current_mid - avg_entry_price) * position_base
   # Negative = loss, positive = gain
   ```

4. **In live mode: check exchange position immediately:**
   - Log into Bitget → Positions page → confirm what exchange sees vs local `position_base`.
   - If exchange shows > 2× what minute.csv shows: orphan position risk — go to Step 5.

5. **Decide: hold or flatten?**
   - If position is within 2× `max_base_pct`: bot's derisk logic will handle it automatically.
   - If position is > 2× `max_base_pct` or you want immediate flat: proceed to manual flatten.

---

## Diagnosis Steps

**Check how position accumulated:**
```bash
# Look at fills.csv for the last 30 fills
tail -30 hbot/data/bot1/logs/epp_v24/bot1_a/fills.csv
# Count consecutive buys vs sells — large position usually from one-sided fills
```

**Check if derisk logic is active:**
```bash
tail -5 hbot/data/bot1/logs/epp_v24/bot1_a/minute.csv
# risk_reasons should include base_pct_above_max or eod_close_pending if derisk is running
```

**Check reconciliation:**
```bash
cat hbot/reports/reconciliation/latest.json
# position_drift_pct field — 0 = perfect sync, > 0.05 = investigation needed
```

---

## Recovery: Manual Flatten Procedure

### Paper mode — inject derisk intent
```bash
# Trigger EOD close via execution intent (if kill_switch service supports it)
# Or simply wait — max_base_pct guard will derisk automatically in next tick
# Position should degrade naturally as bot places sell-only orders
```

### Live mode — manual flatten via exchange UI
1. Log into Bitget → Futures → Positions.
2. Click "Market Close" on the BTC-USDT position.
3. Confirm position is closed.
4. Check `reports/reconciliation/latest.json` — `position_drift_pct` should drop to ~0.

### Live mode — forced flatten via kill switch
```bash
# HTTP endpoint (does not require Redis)
curl -X POST http://localhost:9900/kill
# This cancels all open orders and optionally closes position (depends on kill switch config)
```

### If bot continues placing orders after flatten:
```bash
# Restart bot with fresh daily state
docker compose --env-file hbot/infra/env/.env -f hbot/infra/compose/docker-compose.yml restart bot1
```

---

## Root Cause Investigation

| Cause | How to identify | Prevention |
|---|---|---|
| One-sided regime fill burst | Many consecutive same-side fills in fills.csv | Check `max_base_pct` and `derisk_spread_pct` settings |
| Derisk logic not firing | `risk_reasons` empty despite large base_pct | Check `max_base_pct` config vs actual base_pct |
| Paper/live position drift | `position_drift_pct > 0.05` | Enable `RECON_EXCHANGE_SOURCE_ENABLED=true` |
| Orphan position from prior session | Exchange shows position, bot shows 0 | Implement orphan order scan (go-live checklist item 4) |
| `startup_position_sync: false` | Bot didn't read exchange position on startup | Ensure `startup_position_sync: true` in config |

---

## Post-Incident Review

- [ ] Position flattened and confirmed (exchange + local state match)
- [ ] Root cause identified
- [ ] `fills.csv` shows the fill pattern that caused the accumulation
- [ ] Config adjusted if needed (max_base_pct, derisk_spread_pct, derisk trigger)
- [ ] Reconciliation service shows `position_drift_pct < 0.01` after recovery
- [ ] Documented in iteration log if config change was made
