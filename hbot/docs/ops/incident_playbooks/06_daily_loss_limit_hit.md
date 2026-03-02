# Incident Playbook 06 — Daily Loss Limit Hit (HARD_STOP)

**Scenario:** `max_daily_loss_pct_hard: 0.03` (3%) was reached. Controller entered `HARD_STOP`. All orders were cancelled (via kill switch if wired). Bot will NOT resume until UTC midnight rollover.

---

## Trigger Indicators

- `minute.csv` state: `hard_stop`
- `minute.csv` `risk_reasons`: `daily_loss_hard`
- `minute.csv` `daily_loss_pct`: >= 0.03
- `reports/kill_switch/latest.json`: recent execution with reason `hard_stop_transition`
- Telegram alert (if Telegram token is valid)
- Grafana: "Bot State" panel red, "Daily Loss %" at 3% line

---

## Immediate Actions (< 2 minutes)

1. **Confirm HARD_STOP is from daily loss (not another cause):**
   ```bash
   tail -3 hbot/data/bot1/logs/epp_v24/bot1_a/minute.csv
   # Confirm: state=hard_stop, risk_reasons contains daily_loss_hard, daily_loss_pct >= 0.03
   ```

2. **Confirm position is flat:**
   ```bash
   tail -1 hbot/data/bot1/logs/epp_v24/bot1_a/minute.csv | grep position_base
   # In paper: position_base should be closing toward 0 (derisk in progress, then hard stop)
   # In live: log into exchange and confirm no open positions
   ```

3. **Confirm kill switch executed (live mode only):**
   ```bash
   cat hbot/reports/kill_switch/latest.json
   # result.status should be "executed", not "dry_run" or "error"
   ```

4. **Do NOT restart the bot.** The limit exists for a reason. Accept the stop.

---

## Do NOT Do

- **Do NOT restart the bot before midnight UTC.** The daily_loss counter resets at midnight. Restarting early means the counter resets early, which defeats the purpose of the daily limit.
- **Do NOT raise `max_daily_loss_pct_hard` reactively** — analyze the fills first.
- **Do NOT disable the kill switch** to get orders back live.

---

## Diagnosis: What Caused the Loss?

**Step 1: Quantify the loss:**
```bash
# Get daily loss from minute.csv
tail -1 hbot/data/bot1/logs/epp_v24/bot1_a/minute.csv
# daily_loss_pct × equity_quote = loss in USDT
# Example: daily_loss_pct=0.031, equity=500 → loss ≈ 15.5 USDT
```

**Step 2: Inspect fills for the loss period:**
```bash
# Get today's fills
python hbot/scripts/analysis/bot1_paper_day_summary.py --day YYYY-MM-DD
# Look at: fills, pos_edge_frac, avg_edge_vs_mid_pct, fee rate
```

**Step 3: Run TCA report:**
```bash
python hbot/scripts/analysis/bot1_tca_report.py --day YYYY-MM-DD --save
# Look at: adverse_selection_rate, worst_regimes_by_adverse_rate, avg_implementation_shortfall_bps
```

**Step 4: Identify likely cause:**

| Cause | Indicator | Fix |
|---|---|---|
| Adverse fill burst | `adverse_selection_rate > 0.7`, `fill_edge_ewma_bps` deep negative | Widen `min_net_edge_bps` by 5 bps |
| High vol shock | `regime=high_vol_shock` for many rows | Review `high_vol_band_pct` threshold |
| Large directional position | `position_base` large when market moved against | Check `max_base_pct` and derisk timing |
| Fee rate higher than expected | `fees_usdt` >> expected at configured rate | Verify `fee_mode=auto` and API credentials |
| Turnover too high | `turnover_today_x` > `turnover_cap_x` | Reduce `max_active_executors` |

---

## Recovery Steps

### Wait for midnight UTC rollover:
The bot automatically resets daily counters at midnight UTC and resumes trading. No action required. 

Verify at midnight:
```bash
# After midnight UTC, check minute.csv
tail -3 hbot/data/bot1/logs/epp_v24/bot1_a/minute.csv
# state should transition back to running
# daily_loss_pct should reset to near 0
```

### If the bot does NOT automatically resume at midnight:
```bash
# Manual restart
docker compose --env-file hbot/env/.env -f hbot/compose/docker-compose.yml restart bot1
```

### Config adjustment (do this BEFORE resuming if cause is identified):
1. Open `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`.
2. Apply the appropriate fix from the diagnosis table above.
3. Restart bot to pick up config changes.
4. Monitor the next day's trading closely.

---

## Frequency Tracking

If this is the second daily loss limit in a week:
1. **Pause trading** until root cause is resolved.
2. Run multi-day TCA: `python hbot/scripts/analysis/bot1_tca_report.py --start YYYY-MM-DD --end YYYY-MM-DD`
3. Review regime breakdown — is the bot losing in one specific regime?
4. Consider raising `min_net_edge_bps` (conservative) or reducing position size.
5. Document findings in `docs/strategy/bot1_epp_v2_4_iteration_log.md`.

If this is the **third** daily loss limit in a week: **stop trading and escalate**. The strategy is not working in current market conditions.

---

## Post-Incident Review

- [ ] Daily loss amount documented (USDT and bps of equity)
- [ ] Root cause identified (adverse selection / vol shock / position / fee error)
- [ ] TCA report saved to `reports/strategy/tca_latest.json`
- [ ] Config adjusted and tested before resuming
- [ ] Entry added in `docs/strategy/bot1_epp_v2_4_iteration_log.md`
- [ ] ROAD-1 gate status updated (days with daily_loss_hard don't count toward 20-day gate)
