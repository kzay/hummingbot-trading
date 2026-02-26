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
python hbot/scripts/analysis/bot1_performance_report.py --day 2026-02-26 --exchange bitget_perpetual --pair BTC-USDT
```

### Day summary (quick snapshot)
```bash
python hbot/scripts/analysis/bot1_paper_day_summary.py --day 2026-02-26 --exchange bitget_perpetual --pair BTC-USDT
```

---

## Known data-quality caveats
- **Daily counters can reset mid-day** (restart / manual reset to escape `daily_turnover_hard_limit`), which breaks reconciliation between:
  - `daily_state_*.json` (today counters)
  - `fills.csv` (trade-by-trade truth)
- For performance, prefer **`fills.csv` aggregates** and treat `daily_state` as “best effort”.

---

## Results (latest baseline)

### 2026-02-26 — segmented performance (from `fills.csv`, derived edge using `mid_ref`)
Detected reset boundaries (from `minute.csv`): **00:20:27Z**, **01:18:36Z**

| segment | window (UTC) | fills | notional (USDT) | fees (bps) | realized pnl (bps) | net pnl after fees (bps) | avg edge vs mid (bps) | notes |
|---|---|---:|---:|---:|---:|---:|---:|---|
| seg_1 | 00:00 → 00:20 | 17 | 488 | 3.57 | -80.77 | -84.33 | +0.86 | early burst loss; fee rate abnormal vs expected 2 bps |
| seg_2 | 00:20 → 01:18 | 92 | 3149 | 2.00 | -3.33 | -5.33 | -0.46 | core regime: “more trade → more loss”; hit `daily_turnover_hard_limit` hard-stops |
| seg_3 | 01:18 → … | 40 | 1441 | 2.00 | -0.31 | -2.31 | -0.10 | closer to flat, still negative after fees |

### Interpretation
- The pattern “**more trading → more loss**” is consistent with **negative net expectancy per notional** (seg_2 net \(\approx\) -5.33 bps after fees).
- `minute.csv`’s `net_edge_pct` is often positive while realized fill edge is negative → the **edge model is optimistic** vs realized fill outcomes.

---

## Iterations

### Iteration 2026-02-26 — “Throttle churn” bundle (implemented)
**Goal**: reduce turnover so negative expectancy doesn’t scale; force trades only when edge is clearly above costs.

**Change set (controller config)**: `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`
- **Edge gate**: `min_net_edge_bps: 8 → 15`
- **Spreads**: `0.0020,0.0030 → 0.0025,0.0035` (both sides)
- **Refresh**: `executor_refresh_time: 90 → 150`

**Iteration start**
- Strategy restart time (container logs): **2026-02-26T01:37:38Z**

**Expected signature if working**
- Fills/min and notional/hour **drop materially**
- Net PnL/notional improves (less churn), even if absolute PnL moves slowly

**Run notes**
- Bot restarted and confirmed running via Prometheus (`hbot_bot_state{bot="bot1",state="running"} = 1`)

**Early checkpoint (very small sample, since 01:37:20Z)**
- `fills.csv` since-start: **10 fills**, **311.77 USDT** notional
- Net after fees: **-7.17 bps** (too small to conclude; keep running to ≥200 fills)
- Avg fill edge vs mid (`mid_ref`): **-0.56 bps**

**To evaluate**
- Minimum sample: **≥200 fills** (may take longer with throttling) or ≥6 hours
- KPI focus: net pnl after fees (bps), avg edge vs mid (bps), turnover_x slope vs PnL

---

## Iteration 2026-02-26 — "Derisk fix + delta-neutral conversion" (implemented)

**Goal**: fix bot1 stuck in `soft_pause` for 12+ hours; flip PnL positive; eliminate runaway directional exposure.

### Root-cause diagnosis
Two bugs identified:

1. **Derisk direction bug** (`epp_v2_4.py` line ~747):
   - `base_pct_above_max` always forced `sell_only` during derisk.
   - But `base_pct_gross = abs(position) / equity` — for a SHORT position this means the bot needed to **BUY**, not sell more.
   - Fix: check `base_pct_net` (signed) to determine direction: `net < 0` → BUY-only; `net >= 0` → SELL-only.

2. **Derisk spread too wide** (25–35 bps below mid):
   - Buy orders placed far below current market never filled in a rising market.
   - Fix: added `derisk_spread_pct: 0.0003` (3 bps) so close-out orders place near mid and fill within 1–2 executor cycles.

3. **One-sided regimes on delta-neutral perp** (config):
   - PHASE0_SPECS `down→sell_only`, `up→buy_only` accumulated runaway directional exposure.
   - Fix: `regime_specs_override` sets all regimes to `one_sided: "off"` with `target_base_pct: "0.0"`.

4. **max_base_pct 0.90 → 0.60**:
   - Position was allowed to grow too large before derisk triggered.
   - Reduced to 0.60 so derisk fires earlier.

### Result (2026-02-26)
| Metric | Before fix | After fix |
|---|---|---|
| State | soft_pause (12h stuck) | running |
| Equity | 494.64 USDT | 499.58 USDT |
| Today realized PnL | −5.32 USDT (−1.06%) | −0.38 USDT (−0.076%) |
| Position | −0.00809 BTC short | −0.00353 BTC |
| base_pct gross | 1.097 (above max) | 0.475 (within limits) |

Derisk filled 10 buy orders at 16:30–16:31 UTC with **all positive `pnl_vs_mid`** (0.25–0.90 bps).

### Files changed
- `hbot/controllers/epp_v2_4.py` — derisk direction + spread logic
- `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml` — `max_base_pct`, `derisk_spread_pct`, `regime_specs_override`

### Next evaluation
- Allow 6–12 hours of fresh running to measure realized PnL under corrected logic.
- KPI focus: is daily PnL positive after fees? (target: ≥ 0 bps net).

---

## Next candidate improvements (queued)
1. **Fix `minute.csv` order-book staleness signal**: currently logs “stale since any unchanged book” rather than “stale >30s”, which confuses ops and diagnosis.
2. If still negative after throttle: **increase min edge further** (15 → 20 bps) or widen L1 spreads again.
3. Improve edge model realism: incorporate adverse selection / drift penalties so `net_edge_pct` aligns with realized edge.

