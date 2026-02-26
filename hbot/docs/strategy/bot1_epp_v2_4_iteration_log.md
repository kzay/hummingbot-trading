# bot1 — EPP v2.4 (bitget_perpetual, BTC-USDT) Iteration Log

## Purpose
Single source of truth for:
- **What the strategy is**
- **What we changed** (small deltas)
- **What happened** (results + sanity checks)
- **Next iteration decision**

This file is intended to be updated after each run so we converge on a winning configuration without losing context.

---

## Strategy definition (current)
- **Bot**: `bot1`
- **Controller**: `epp_v2_4` (`variant: a`)
- **Venue / instrument**: `bitget_perpetual` perp
- **Pair**: `BTC-USDT`
- **Mode**: paper (Paper Engine v2, PaperDesk v2)

### Execution loop / signal inputs
- **Clock tick**: 1s (`conf_client.yml: tick_size: 1.0`)
- **Signal sampling**: mid/top-of-book sampled every **10s** (`sample_interval_s: 10`)
- **Regime / indicators**: computed on internal sampled mid series (not exchange OHLCV candles)

### Current config pointers
- **Controller config**: `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`
- **Script config**: `hbot/data/bot1/conf/scripts/v2_epp_v2_4_bot_a.yml`
- **Logs**: `hbot/data/bot1/logs/epp_v24/bot1_a/`

---

## How to measure (commands)

### Segment-by-segment report (auto-detect resets)
```bash
python hbot/scripts/analysis/bot1_performance_report.py --day 2026-02-27 --exchange bitget_perpetual --pair BTC-USDT
```

### Day summary (quick snapshot)
```bash
python hbot/scripts/analysis/bot1_paper_day_summary.py --day 2026-02-27 --exchange bitget_perpetual --pair BTC-USDT
```

---

## Known data-quality caveats
- **Daily counters can reset mid-day** (restart / manual reset to escape `daily_turnover_hard_limit`), which breaks reconciliation between:
  - `daily_state_*.json` (today counters)
  - `fills.csv` (trade-by-trade truth)
- For performance, prefer **`fills.csv` aggregates** and treat `daily_state` as "best effort".

---

## Results

### 2026-02-26 — Full day summary (corrected logic active from 16:30 UTC)

| Metric | Value |
|---|---|
| Bot state at EOD | `running` |
| Equity at EOD | **504.77 USDT** (+0.96% on 499.96 open) |
| Today realized PnL | **+4.82 USDT** |
| Today fees paid | 0.97 USDT |
| Net after fees | **+3.85 USDT (+0.77%)** |
| Position at EOD | −0.000055 BTC (essentially flat) |
| Drawdown | **0%** |
| Fills | 254 (100% maker) |

_Note: first 16.5h were affected by the derisk bug (stuck soft_pause). Clean-run data starts 2026-02-27._

---

## Iterations

### Iteration 2026-02-26a — "Throttle churn" (implemented)
**Goal**: reduce turnover so negative expectancy doesn't scale; force trades only when edge is clearly above costs.

**Change set**: `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`
- **Edge gate**: `min_net_edge_bps: 8 → 15`
- **Spreads**: `0.0020,0.0030 → 0.0025,0.0035`
- **Refresh**: `executor_refresh_time: 90 → 150`

**Outcome**: helped reduce churn but bot accumulated large short from `down→sell_only` regime behavior and was stuck for 12h due to the derisk direction bug.

---

### Iteration 2026-02-26b — "Derisk fix + delta-neutral conversion" (implemented)

**Goal**: fix bot1 stuck in `soft_pause` 12+ hours; eliminate runaway directional exposure.

**Root-cause diagnosis — 3 bugs:**

1. **Derisk direction** (`epp_v2_4.py`): `base_pct_above_max` always enabled SELL-only.
   For a SHORT position the bot needed to BUY. Fix: branch on `base_pct_net` sign.

2. **Derisk spread too wide**: 25–35 bps below mid never fill in a rising market.
   Fix: `derisk_spread_pct: 0.0003` (3 bps) — close-out orders fill in ≤1 executor cycle.

3. **One-sided regimes on delta-neutral perp**: `down→sell_only`, `up→buy_only` accumulated runaway
   directional exposure. Fix: `regime_specs_override` → all regimes `one_sided: off`, `target_base_pct: 0.0`.

**Also**: `max_base_pct: 0.90 → 0.60` — derisk triggers earlier.

**Result:**
| Metric | Before | After |
|---|---|---|
| State | soft_pause (12h) | running |
| Equity | 494.64 | 504.77 USDT |
| Realized PnL today | −5.32 USDT | **+4.82 USDT** |
| Position | −0.00809 BTC | −0.000055 BTC |
| Drawdown | 1.06% | **0%** |

---

## Semipro 9.5/10 Roadmap

### Platform: completed ✓
- Paper engine v2 with full event/fill/PnL pipeline
- Risk services: portfolio risk, reconciliation, kill-switch (**health fixed**)
- Alertmanager stable (**empty SLACK_WEBHOOK_URL crash fixed**)
- Day-2 gate **auto-refreshes integrity** before evaluation (no more stale-delta false failures)
- Promotion gates strict cycle: PASS
- Derisk direction + spread bugs fixed (2026-02-26)
- `max_base_pct` tightened to 0.60 for earlier position limit enforcement

### 2026-02-26 — Final confirmed result

| Metric | Value |
|---|---|
| Equity EOD | **508.07 USDT** (+8.11 USDT, **+1.37% net after fees**) |
| Max drawdown | **0.006%** — effectively zero |
| Fills | 191 today (100% maker), 0.27/min rate |
| Turnover | 12.31× — hit `daily_turnover_hard_limit` at 19:04 UTC |
| Config change | `max_daily_turnover_x_hard: 12 → 30` for full paper observation |

_Note: clean trading was only 16:30–19:04 UTC (~2.5h). Full 24h data starts 2026-02-27._

---

### Next evaluation gate (2026-02-27 — first full clean-config day)

```bash
python hbot/scripts/analysis/bot1_paper_day_summary.py --day 2026-02-27 --exchange bitget_perpetual --pair BTC-USDT
```

**Pass criteria:**
- `realized_pnl_today_quote > 0` after fees
- `drawdown_pct < 2%`
- `position_base` stays within `|base_pct| < 0.60` at all times
- Bot does not hit `hard_stop` before 18:00 UTC (turnover limit now 30×)

**If pass:** run 3 consecutive days, then assess Sharpe (ROAD-1 in backlog).
**If fail:** raise `min_net_edge_bps` 15 → 20 bps, or diagnose adverse selection per regime.

### Queued improvements (priority order)
1. **Realized-edge tracker** — trailing per-regime fill edge; auto-widen spreads when adverse selection > 2 bps for 30+ min
2. **Funding rate in cost model** — verify `_refresh_funding_rate` feeds the spread floor (`funding_cost` currently 0)
3. **EOD position close** — add `close_at_daily_rollover: true` to capture residual unrealized PnL cleanly
4. **Order-book stale threshold** — fix from "any unchanged book" to ">30s unchanged"
5. **OHLCV regime detection** — switch from internal 10s sampled mid to exchange 1m OHLCV candles
6. **Slack alerting** — set `SLACK_WEBHOOK_URL` in `.env`, re-enable `slack_configs` in alertmanager.yml
7. **Live promotion** — 5+ consecutive profitable paper days → promote bot1 to Bitget testnet live
