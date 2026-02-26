# hbot — AI-Executable Backlog

> **For AI agents**: Each item is a complete spec. Read the item you are working on
> fully before touching any code. All design decisions are pre-answered.
> After every change: `python -m py_compile hbot/controllers/epp_v2_4.py` and
> `PYTHONPATH=hbot python -m pytest hbot/tests/ -x -q --ignore=hbot/tests/integration`.

**Tiers**: P0 = blocks live / safety gap · P1 = affects PnL / reliability · P2 = quality
**Status**: `open` · `in-progress (YYYY-MM-DD)` · `done (commit)`

---

## P0 — Blocks Live Trading / Safety

---

### [P0-1] Wire signal service output into the controller `done (2026-02-26)`

**Why it matters**: `signal_service` publishes inventory and ML signals to Redis but nothing
consumes them. The entire signal pipeline is a no-op.

**What exists now**:
- `hbot/services/signal_service/main.py:107` — publishes `StrategySignalEvent` with
  `signal_name="inventory_rebalance"`, `signal_value=float(imbalance)` to stream
  `hb.signal.v1` (constant: `SIGNAL_STREAM` in `services/contracts/stream_names.py`).
- `hbot/controllers/epp_v2_4.py:1015` — `apply_execution_intent(intent: Dict)` already
  handles `action="set_target_base_pct"` and sets `self._external_target_base_pct_override`.
- `hbot/controllers/paper_engine_v2/hb_bridge.py` — bridge already imports Redis and calls
  per-controller methods each tick. It already has a Redis client available via `_redis_*` fields.

**Design decision (pre-answered)**: Route through `hb_bridge.py`. Do NOT add Redis to the
controller. The bridge polls `SIGNAL_STREAM` once per tick (non-blocking), maps signal
events to `apply_execution_intent()` calls.

**Implementation steps**:
1. In `hb_bridge.py`, find the method called once per tick (likely `_run_tick` or similar).
   Add a private method `_consume_signals(self) -> None`.
2. In `_consume_signals`: call `self._redis_client.xread({SIGNAL_STREAM: self._last_signal_id},
   count=20, block=0)` (non-blocking). For each entry:
   - If `signal_name == "inventory_rebalance"`: call
     `ctrl.apply_execution_intent({"action": "set_target_base_pct",
     "target_base_pct": signal_value})` on the matching controller.
   - Update `self._last_signal_id` to the last processed entry id.
3. Call `self._consume_signals()` from the tick method, wrapped in `try/except Exception`
   (Redis down must not crash the tick).
4. Add `self._last_signal_id: str = "0-0"` to `__init__`.
5. Import `SIGNAL_STREAM` from `services.contracts.stream_names`.

**Acceptance criteria**:
- `signal_service` running + `signal_value != 0` → `minute.csv` `target_net_base_pct`
  column changes within 2 ticks.
- Redis unavailable → bridge logs a warning, tick continues normally.
- No new imports added to `epp_v2_4.py`.

**Do not**:
- Do not block the tick with `block_ms > 0`.
- Do not add a Redis client to `epp_v2_4.py`.
- Do not process ML signals yet — only `signal_name == "inventory_rebalance"` for now.

---

### [P0-2] HARD_STOP must publish a kill-switch execution intent `open`

**Why it matters**: When the controller hits max-loss / drawdown / cancel-budget breach,
`force_hard_stop()` stops new orders but **open exchange orders remain live**.
On live trading this could accumulate large adverse position.

**What exists now**:
- `hbot/controllers/ops_guard.py` — `force_hard_stop(reason: str) -> GuardState` sets
  `self._state = GuardState.HARD_STOP`. Returns the new state.
- `hbot/controllers/epp_v2_4.py:658` — `_resolve_guard_state()` calls
  `self._ops_guard.force_hard_stop(...)` in several places. After the call it just
  returns the state — no side effect.
- `hbot/controllers/paper_engine_v2/hb_bridge.py` — already has a Redis publisher
  (`self._redis_publish(stream, payload)` or similar). Already knows the controller state.
- `hbot/services/kill_switch/main.py` — listens on `hb.execution_intent.v1` for
  `action="kill_switch"` and cancels all exchange orders.
- Event schema: `ExecutionIntentEvent` in `hbot/services/contracts/event_schemas.py`.

**Design decision (pre-answered)**: Detect first HARD_STOP transition in `hb_bridge.py`
by comparing previous vs current `GuardState`. On first transition to `HARD_STOP`, publish
`ExecutionIntentEvent(action="kill_switch", ...)` to `hb.execution_intent.v1`.
Do not modify `ops_guard.py` or the controller.

**Implementation steps**:
1. In `hb_bridge.py.__init__`, add `self._prev_guard_state: Optional[GuardState] = None`.
2. In the tick method, after reading `controller.processed_data["state"]` (or equivalent),
   detect state change: `if new_state == "hard_stop" and prev != "hard_stop"`.
3. On first HARD_STOP: build and publish `ExecutionIntentEvent`:
   ```python
   intent = ExecutionIntentEvent(
       producer="hb_bridge",
       instance_name=controller.config.instance_name,
       action="kill_switch",
       metadata={"reason": "hard_stop_transition", "details": "controller entered HARD_STOP"},
   )
   self._redis_publish(EXECUTION_INTENT_STREAM, intent.model_dump())
   ```
4. Import `ExecutionIntentEvent` from `services.contracts.event_schemas` and
   `EXECUTION_INTENT_STREAM` from `services.contracts.stream_names`.
5. Update `self._prev_guard_state` each tick.

**Acceptance criteria**:
- Synthetic HARD_STOP (trigger `max_daily_loss_pct_hard` in paper with a large loss) →
  `reports/kill_switch/latest.json` shows a kill-switch intent was received.
- Second HARD_STOP tick does NOT re-publish (only fires on first transition).
- Works in paper mode (kill-switch service may be in DRY_RUN but intent is still published).

**Do not**:
- Do not fire on every HARD_STOP tick — only on the first transition.
- Do not modify `epp_v2_4.py` or `ops_guard.py`.

---

### [P0-3] Enable real exchange reconciliation once API keys are set `open`

**Why it matters**: `reconciliation_service` runs with `exchange_source_enabled: false`
when env vars are absent. Inventory drift vs real exchange is never detected.

**What exists now**:
- `hbot/services/reconciliation_service/main.py:232` — reads
  `RECON_EXCHANGE_SOURCE_ENABLED` env var. When false, skips exchange balance fetch.
- `hbot/services/exchange_snapshot_service/main.py:47` — tries ccxt, returns
  `{"status": "missing_credentials"}` when `BITGET_API_KEY` is blank.
- `hbot/.env.example` — shows which vars to set.

**Action (config only — no code)**:
1. Copy `hbot/.env.example` → `hbot/.env`.
2. Fill in `BITGET_API_KEY`, `BITGET_SECRET`, `BITGET_PASSPHRASE`.
3. Set `RECON_EXCHANGE_SOURCE_ENABLED=true`.
4. `docker-compose up -d --no-deps reconciliation-service exchange-snapshot-service`.
5. Check `hbot/reports/reconciliation/latest.json` — `exchange_source_enabled` should be `true`.

**Acceptance criteria**:
- `reconciliation/latest.json` shows `exchange_source_enabled: true`.
- `exchange_snapshots/latest.json` shows `status: ok` with real balance data.

**Do not**: Commit `.env` to git.

---

### [P0-4] Complete go-live hardening checklist `open`

**Why it matters**: All 14 items are unchecked. At least 4 are safety-critical before
any live capital is deployed.

**File**: `hbot/docs/ops/go_live_hardening_checklist.md`

**Prioritized order**:
1. Item 3 — Kill switch: dry-run then testnet live test
2. Item 9 — Synthetic breach: trigger `max_daily_loss_pct_hard` and verify HARD_STOP fires
3. Item 4 — Orphan order scan: place order via exchange UI, kill bot, restart, verify canceled
4. Item 11 — Paper/live parity: run both 1h side-by-side on testnet
5. Items 1,2,5,6,7,8,10,12,13,14 — work through in order

**For each item**: check the box in the MD file, add the evidence path, commit.

---

## P1 — Affects PnL / Reliability

---

### [P1-1] Add funding rate to the spread floor cost model `open`

**What exists now**:
- `hbot/controllers/epp_v2_4.py:1487` — `_refresh_funding_rate()` fetches funding rate
  and stores in `self._funding_rate: Decimal`. Called every `funding_rate_refresh_s` (300s).
- `hbot/controllers/epp_v2_4.py:_compute_spread_and_edge` — builds `SpreadEdgeState`
  with `net_edge`, `min_edge_threshold`. Currently does NOT include `self._funding_rate`.
- Funding impact: for a SHORT position with positive funding, the bot PAYS funding every 8h.
  Cost per trade = `funding_rate * leverage / (8 * 3600 / avg_hold_time_s)` approximately.
  Simplified: add half the 8h funding rate to cost floor when the bot is net short.

**Design decision (pre-answered)**: Add `funding_rate_cost_bps` computed once in
`_compute_spread_and_edge` from `self._funding_rate`, then add it to `min_cost_bps`
before computing `min_edge_threshold`. Sign: positive funding + net short = extra cost;
positive funding + net long = slight rebate (cap at 0 for conservative estimate).

**Implementation steps**:
1. In `_compute_spread_and_edge`, after computing `smooth_drift`, add:
   ```python
   # Funding cost contribution (sign-aware, only for perp)
   funding_cost_bps = _ZERO
   if self._is_perp and self._funding_rate != _ZERO:
       sign = Decimal("-1") if base_pct < _ZERO else _ONE  # short pays, long receives
       funding_cost_bps = max(_ZERO, sign * self._funding_rate * _10K)
   ```
2. Add `funding_cost_bps` to the `min_cost_bps` sum (wherever fees + slippage + drift are summed).
3. Add `"funding_rate_bps": str(self._funding_rate * _10K)` to the `_log_minute` output dict.
4. No config changes needed.

**Acceptance criteria**:
- `minute.csv` has a `funding_rate_bps` column with non-zero values for perp connector.
- When `self._funding_rate = Decimal("0.0001")` (1 bp) and bot is short, `min_edge_threshold`
  increases by 1 bp compared to `funding_rate = 0`.

---

### [P1-2] Realized-edge tracker with auto-widen `open`

**What exists now**:
- `hbot/controllers/epp_v2_4.py:786` — `did_fill_order(event)` processes each fill.
  Currently updates position, fees, and logs to fills.csv. Does NOT track fill edge EWMA.
- `hbot/controllers/epp_v2_4.py:_compute_spread_and_edge` — computes regime-based spreads.
  No feedback from actual fill quality.

**Design decision (pre-answered)**: In `did_fill_order`, compute `fill_edge_bps =
(fill_price - mid_ref) * side_sign / mid_ref * 10000`. Maintain
`self._fill_edge_ewma: Optional[Decimal]` with alpha=0.05 (slow: 20-fill window).
In `_compute_spread_and_edge`, if `_fill_edge_ewma < -cost_floor_bps` for
`_adverse_fill_count >= 20` consecutive fills, multiply spread_min and spread_max
by `self.config.adverse_fill_spread_multiplier` (new config field, default 1.3).
Reset adverse count when EWMA recovers above `-cost_floor_bps * 0.5`.

**Implementation steps**:
1. Add to `EppV24Config`:
   ```python
   adverse_fill_spread_multiplier: Decimal = Field(default=Decimal("1.3"),
       description="Spread multiplier when realized fill edge EWMA is persistently negative")
   adverse_fill_count_threshold: int = Field(default=20, ge=5, le=200)
   ```
2. Add to `__init__`: `self._fill_edge_ewma: Optional[Decimal] = None`,
   `self._adverse_fill_count: int = 0`.
3. In `did_fill_order`: compute fill_edge_bps, update EWMA with alpha=0.05, update counter.
4. In `_compute_spread_and_edge`: if adverse, multiply the computed `spread_pct` before
   applying to `buy` and `sell` spreads.
5. Add `"fill_edge_ewma_bps"` and `"adverse_fill_active"` to the `_log_minute` output.

**Acceptance criteria**:
- `minute.csv` shows `fill_edge_ewma_bps` column.
- In paper mode, after 20 consecutive adverse fills, `spread_multiplier` > 1.0 in
  `processed_data`.

---

### [P1-3] EOD position close at daily rollover `open`

**What exists now**:
- `hbot/controllers/epp_v2_4.py:2103` — `_maybe_roll_day(now_ts)` detects day boundary,
  resets daily counters. Currently does NOT place any closing order.
- `self._position_base: Decimal` — signed net position. If non-zero at rollover, it carries
  into the new day with fresh loss budget but existing unrealized PnL.

**Design decision (pre-answered)**: Add `close_position_at_rollover: bool = True` config.
When True and `abs(self._position_base) * mid > min_close_notional_quote` at rollover,
set a `_pending_eod_close: bool = True` flag. On next tick, force `derisk_only` by injecting
`base_pct_above_max` (or equivalent) into risk_reasons regardless of actual base_pct.
Clear the flag once `abs(position_base) < min_base_amount`.

**Implementation steps**:
1. Add to `EppV24Config`:
   ```python
   close_position_at_rollover: bool = Field(default=True)
   min_close_notional_quote: Decimal = Field(default=Decimal("5.0"))
   ```
2. Add `self._pending_eod_close: bool = False` to `__init__`.
3. In `_maybe_roll_day`, after resetting counters: if `close_position_at_rollover` and
   `abs(self._position_base) * mid > min_close_notional_quote`, set `_pending_eod_close = True`.
4. In `_evaluate_all_risk`, if `_pending_eod_close`: append `"eod_close_pending"` to reasons.
5. In `_emit_tick_output`, handle `rr == {"eod_close_pending"}` as a new derisk branch
   (same logic as `base_pct_above_max` but uses `base_pct_net` to pick side).
6. Clear `_pending_eod_close` when `abs(self._position_base) < self._min_base_amount(mid)`.

**Acceptance criteria**:
- At midnight UTC, if position is non-zero, `minute.csv` shows `eod_close_pending` in
  `risk_reasons` until position is flat.
- Does not fire if `abs(position_base) * mid < min_close_notional_quote`.

---

### [P1-4] OHLCV candles for regime EMA/ATR `open`

**What exists now**:
- `hbot/controllers/epp_v2_4.py:86` — `candles_connector` config field with validator.
  Currently unused in any method.
- `hbot/controllers/price_buffer.py` — provides `ema()`, `band_pct()`, `adverse_drift_30s()`.
  Uses internal 10s sampled mid prices.
- `hbot/controllers/epp_v2_4.py:_detect_regime` — calls `self._price_buffer.ema(50)` and
  `self._price_buffer.band_pct(14)`.

**Design decision (pre-answered)**: When `candles_connector` is set, fetch 1m OHLCV via
`self.market_data_provider.get_candles_df(connector, pair, "1m", ema_period + 5)`.
Use OHLCV close prices for EMA and (high-low)/close for ATR. Fall back to `price_buffer`
when candles unavailable (connector not ready or returns empty). Keep `price_buffer` for
sub-minute drift detection always.

**Implementation steps**:
1. Add helper `_get_ohlcv_ema_and_atr(self) -> Tuple[Optional[Decimal], Optional[Decimal]]`
   that fetches candles when `self.config.candles_connector` is non-empty, returns
   `(ema, band_pct)` or `(None, None)` on any failure.
2. In `_detect_regime`, try `_get_ohlcv_ema_and_atr()` first. On `(None, None)` fall
   back to `self._price_buffer.ema(...)` and `self._price_buffer.band_pct(...)`.
3. Add `"regime_source": "ohlcv"/"price_buffer"` to processed_data for monitoring.

**Acceptance criteria**:
- `minute.csv` shows `regime_source` column.
- When `candles_connector` is blank (default), `regime_source == "price_buffer"`.
- No crash when candles return empty dataframe.

---

### [P1-5] Fix `order_book_stale` minute.csv logging `done (9fef542)`

The logged value was `_book_stale_since_ts > 0` (fires immediately) instead of the
30-second-gated `market.order_book_stale`. Fixed in commit `9fef542`.

---

### [P1-6] Add `neutral_high_vol` regime `open`

**What exists now**:
- `hbot/controllers/epp_v2_4.py:275` — `PHASE0_SPECS` dict with 4 regimes:
  `neutral_low_vol`, `up`, `down`, `high_vol_shock`.
- `hbot/controllers/epp_v2_4.py:1024` — `_detect_regime`: if `band_pct >= high_vol_band_pct`
  → `high_vol_shock`; else `neutral_low_vol`/`up`/`down`.

**Design decision (pre-answered)**: Add `neutral_high_vol` between `neutral_low_vol` and
`high_vol_shock`. Detection: `band_pct >= high_vol_band_pct * 0.5 AND band_pct < high_vol_band_pct`
AND regime is not `up` or `down` (price near EMA). Spreads: mid-point between the two.

**Implementation steps**:
1. Add to `PHASE0_SPECS`:
   ```python
   "neutral_high_vol": RegimeSpec(
       spread_min=Decimal("0.0040"), spread_max=Decimal("0.0080"),
       levels_min=1, levels_max=3, refresh_s=100,
       target_base_pct=Decimal("0.0"), quote_size_pct_min=Decimal("0.0005"),
       quote_size_pct_max=Decimal("0.0008"), one_sided="off", fill_factor=Decimal("0.35"),
   ),
   ```
2. In `_detect_regime`, add detection before the existing `high_vol_shock` check:
   ```python
   high_vol_mid_threshold = self.config.high_vol_band_pct * Decimal("0.5")
   if band_pct >= high_vol_mid_threshold and raw_regime == "neutral_low_vol":
       raw_regime = "neutral_high_vol"
   ```

**Acceptance criteria**:
- `minute.csv` shows `neutral_high_vol` regime during moderate volatility periods.
- `regime_counts` in day summary includes `neutral_high_vol`.

---

### [P1-7] Automated daily paper-state backup `open`

**What exists now**:
- `hbot/scripts/ops/artifact_retention.py` — runs artifact cleanup.
- Key paper files: `data/bot1/logs/epp_v24/bot1_a/{minute.csv, fills.csv, paper_desk_v2.json}`.

**Design decision (pre-answered)**: Extend `artifact_retention.py` to also COPY (not move)
the three key bot1 files to `data/bot1/archive/YYYYMMDD/` once per day at rollover time,
keyed by UTC date.

**Implementation steps**:
1. Add function `backup_paper_state(root: Path, date_str: str) -> None` to `artifact_retention.py`.
2. Sources: `data/bot1/logs/epp_v24/bot1_a/minute.csv`,
   `data/bot1/logs/epp_v24/bot1_a/fills.csv`, `data/bot1/logs/epp_v24/bot1_a/paper_desk_v2.json`.
3. Destination: `data/bot1/archive/{date_str}/` — copy, do not move.
4. Call from the docker-compose `daily-ops-reporter` service or add a cron step in compose.
5. Add `data/bot1/archive/` to `.gitignore`.

**Acceptance criteria**:
- After running the script with `--date 2026-02-26`, `data/bot1/archive/20260226/` contains
  the three files.

---

### [P1-8] Audit `risk_service` for completeness `open`

**What exists**: `hbot/services/risk_service/main.py` — 112 lines. Compare to
`portfolio_risk_service/main.py` (335 lines) and `reconciliation_service/main.py` (465 lines).

**Action**: Read `risk_service/main.py` end-to-end. Check:
- Does it have a complete poll loop?
- Does it write `reports/risk_service/latest.json`?
- Does it publish to `hb.audit.v1`?
- Does it use `ShutdownHandler`?
If any are missing, implement. If it's intentionally a thin wrapper, add a comment explaining its role.

---

### [P1-9] Decide on ClickHouse: wire or disable `open`

**What exists**: `hbot/services/clickhouse_ingest/main.py` (232 lines) is in compose
but no `clickhouse` server service exists in `docker-compose.yml`. Ingest events are dropped.

**Decision needed from operator**: Is ClickHouse planned? If yes → add to compose.
If no → comment out or remove the ingest service from compose to eliminate the log noise.
For now, recommended action: **comment it out** in compose with a note, and add a
`# To enable: see clickhouse_ingest/README.md` marker.

---

## P2 — Quality / Completeness

---

### [P2-1] Add tests for critical untested modules `open`

**Priority order for test files to create**:

1. `hbot/tests/controllers/test_price_buffer.py` — test `ema()` convergence, `band_pct()`
   correctness with synthetic prices, `adverse_drift_30s()` edge cases (empty buffer, monotonic).
2. `hbot/tests/controllers/test_hb_bridge_signal_routing.py` — after P0-1 is done,
   test signal → `apply_execution_intent` routing with mocked Redis.
3. `hbot/tests/services/test_exchange_snapshot.py` — test `missing_credentials` graceful
   fallback and successful ccxt mock response parsing.

**Pattern**: Use `conftest.py` fixtures from `hbot/tests/controllers/test_paper_engine_v2/conftest.py`
for paper engine tests. Mock Redis with `unittest.mock.patch`.

---

### [P2-2] Validate Grafana alert rules with synthetic breach `open`

**What exists**: `hbot/monitoring/prometheus/alert_rules.yml` — defines rules.
No validation script exists.

**Action**: Create `hbot/scripts/ops/synthetic_alert_test.py` that:
1. Temporarily writes a metric value above threshold to a test Prometheus pushgateway.
2. Waits 30s for alert to fire.
3. Checks `http://localhost:9093/api/v1/alerts` for the expected alert.
4. Cleans up.

---

### [P2-3] Configure Slack alerting `open`

**Action**: Set `SLACK_WEBHOOK_URL` in `.env`, uncomment `slack_configs` block in
`hbot/monitoring/alertmanager/alertmanager.yml`, restart alertmanager.
**File**: `hbot/monitoring/alertmanager/alertmanager.yml` (the commented block is already there).
**Effort**: 10 min.

---

### [P2-4] Document signal → controller data flow `open`

**File**: `hbot/docs/architecture/data_flow_signal_risk_execution.md` — check if it exists
and covers the full loop from `signal_service` → Redis → `hb_bridge` → `apply_execution_intent`
→ `_external_target_base_pct_override`. Add or update after P0-1 is implemented.

---

## Path to 9.5 / 10 — Beyond the Backlog

> These are not bug fixes. They are the items that turn a well-engineered paper bot
> into a validated, deployable semipro trading desk. Work through them in order —
> each stage gates the next. Do not skip ahead.

### Scoring map

| Stage | Score | Gate |
|---|---|---|
| Today (bugs fixed, infrastructure stable) | 6.5 | — |
| Backlog P0 + P1 complete | 7.5 | All P0 items done, bot running cleanly |
| 20-day paper run validated | 8.0 | Sharpe ≥ 1.5 annualized, PnL positive |
| Walk-forward backtest passes | 8.5 | Out-of-sample edge confirmed on 6m history |
| Order book signals + Kelly sizing | 8.8 | Edge stable after sizing change |
| 4-week testnet live | 9.0 | No safety incidents, execution close to paper |
| TCA + incident playbooks + secrets hygiene | 9.3 | All checklist items signed off |
| AI: regime classifier replaces EMA/ATR | 9.4 | Walk-forward Sharpe improves ≥ 0.3 |
| AI: adverse selection classifier wired | 9.5 | Adverse fill rate drops ≥ 15% out-of-sample |
| Second uncorrelated strategy | 9.5+ | Portfolio Sharpe > single-strategy Sharpe |
| TCA + incident playbooks + secrets hygiene | 9.3 | All checklist items signed off |
| Second uncorrelated strategy + portfolio allocation | 9.5 | Portfolio Sharpe > single-strategy Sharpe |

---

### [ROAD-1] 20-day paper run — prove statistical edge `open`

**Gate**: complete after backlog P0+P1 are done and bot has run for 20 consecutive days.

**Why**: one day of positive paper PnL is noise. Statistical significance requires N ≥ 20
daily observations to produce a 90% confidence interval on Sharpe ratio that excludes zero.

**What to measure each day**:
Run `python hbot/scripts/analysis/bot1_paper_day_summary.py --day YYYY-MM-DD` and record
into a tracking table:

| date | realized_pnl_usdt | fees_usdt | net_pnl_usdt | net_pnl_bps | drawdown_pct | fills | turnover_x | dominant_regime |
|---|---|---|---|---|---|---|---|---|

**Pass criteria**:
- Mean daily `net_pnl_bps` > 0 over the 20-day window
- Sharpe ratio (annualised) ≥ 1.5: `sharpe = (mean_daily_pnl / std_daily_pnl) * sqrt(252)`
- Max single-day drawdown < 2%
- No day hits `max_daily_loss_pct_hard` (3%)
- PnL decomposition shows spread capture is the dominant source (not lucky position carry)

**If criteria fail**: raise `min_net_edge_bps` by 5 bps and repeat. Document each attempt
in `hbot/docs/strategy/bot1_epp_v2_4_iteration_log.md`.

**Implementation needed**:
- Create `hbot/scripts/analysis/bot1_multi_day_summary.py --start YYYY-MM-DD --end YYYY-MM-DD`
  that aggregates the daily summary across a date range and computes Sharpe, max drawdown,
  win rate, and regime-breakdown table.
- Output: JSON to `hbot/reports/strategy/multi_day_summary_latest.json` + console print.

---

### [ROAD-2] Walk-forward backtest on 6-month historical data `open`

**Gate**: complete after ROAD-1 passes.

**Why**: paper PnL with live data is not a backtest — you're seeing real prices in
sequence. A walk-forward test fits parameters on months 1–9 and tests on months 10–12,
proving the edge is not curve-fitted to recent conditions.

**What is needed**:
1. **Historical data pipeline**: fetch 6 months of Bitget BTC-USDT perpetual 1-minute
   OHLCV + order book snapshots via `ccxt` or Bitget API. Store as Parquet in
   `hbot/data/historical/bitget_btc_usdt_perp_1m_YYYYMM.parquet`.
2. **Event-driven backtest engine**: a `BacktestRunner` class in
   `hbot/scripts/backtesting/backtest_runner.py` that:
   - Replays OHLCV bars as `MarketSnapshot` events
   - Feeds them into a headless instance of `EppV24Controller` (no hummingbot runtime)
   - Collects `fills`, `minute` rows, and final PnL
   - Applies realistic fees (maker 0.02%, taker 0.06%) and slippage (1 bp per fill)
3. **Walk-forward loop**: split data into 3 windows (fit/validate/test), run backtest on each.
4. **Parameter stability check**: vary `min_net_edge_bps` ±5 bps and `max_base_pct` ±0.10.
   If Sharpe degrades > 30% with ±1 std param change, the strategy is fragile.

**Pass criteria**:
- Out-of-sample Sharpe ≥ 1.0 on each of 3 test windows
- Maximum out-of-sample drawdown < 5%
- Edge does not vanish when fees increase 20% (break-even fee rate > 1.5× current)

**Skill reference**: `hbot/.cursor/skills/backtesting-validation/SKILL.md`

---

### [ROAD-3] Order book imbalance signal `open`

**Gate**: complete after ROAD-2 passes (validate that adding the signal improves Sharpe).

**Why**: EMA/ATR-based regime detection is lagged. Order book imbalance is a leading
signal — it predicts short-term price direction before price moves.

**What to build**:
- Add `imbalance` field computation in `hbot/controllers/epp_v2_4.py:_evaluate_market_conditions`:
  ```python
  bid_depth = sum of top-5 bid quantities (from order book)
  ask_depth = sum of top-5 ask quantities
  imbalance = (bid_depth - ask_depth) / (bid_depth + ask_depth)  # range [-1, +1]
  ```
- Feed `imbalance` into `skew` in `_compute_spread_and_edge`:
  - `imbalance > 0.3` (strong bid): widen ask spread (more sellers incoming, less rush to sell)
  - `imbalance < -0.3` (strong ask): widen bid spread
  - This is additive to the existing inventory skew, capped by `inventory_skew_cap_pct`
- Add `"ob_imbalance"` to `minute.csv` for tracking.

**Validation**: run ROAD-2 backtest with and without imbalance signal. Keep only if
out-of-sample Sharpe improves by ≥ 0.2.

---

### [ROAD-4] Kelly-adjusted position sizing `open`

**Gate**: complete after ROAD-3 (need stable edge estimate to size from).

**Why**: `total_amount_quote: 50` is arbitrary. Kelly sizing allocates more capital
when estimated edge is high and less when uncertain, improving risk-adjusted returns.

**What to build**:
- Add `use_kelly_sizing: bool = False` and `kelly_fraction: Decimal = Decimal("0.25")`
  to `EppV24Config` (fractional Kelly — full Kelly is too aggressive).
- In `_apply_runtime_spreads_and_sizing`, when `use_kelly_sizing` is True:
  ```
  kelly_size = (fill_edge_ewma_bps / variance_bps) * kelly_fraction * equity_quote
  total_amount_quote = clip(kelly_size, min_order_quote, max_order_quote)
  ```
  where `variance_bps` is the rolling std of `fill_edge_ewma_bps` over 50 fills.
- Fall back to `config.total_amount_quote` when EWMA has < 20 observations.

---

### [ROAD-5] 4-week testnet live trading `open`

**Gate**: complete after ROAD-4 and after go-live checklist (P0-4) is fully signed off.

**Why**: paper engine simulates fills perfectly — real markets have partial fills,
cancel-before-fill races, API rate limit spikes, and funding settlements at exact
timestamps. You cannot discover these issues in paper mode.

**Prerequisites**:
- All P0 backlog items done
- `KILL_SWITCH_DRY_RUN=false` tested on testnet (kill-switch actually cancels orders)
- Bitget testnet account funded with test USDT
- Separate API key for testnet (never use mainnet keys on testnet)
- Change `connector_name: bitget_paper_trade` → `bitget_perpetual` in bot1 config only
  after completing this checklist

**What to monitor daily**:
- Fill count ratio: testnet fills / paper fills (should be 0.5–2×, not 0 or 10×)
- Execution slippage: actual fill price vs expected price from paper (`pnl_vs_mid_pct`)
- Order rejection rate: `did_fail_order` events / total orders placed
- Cancel-before-fill rate: orders cancelled before fill vs total placed
- Any `position_drift_pct` > 1% (reconciliation alarm)

**Pass criteria for live promotion**:
- 20 testnet trading days, no HARD_STOP incidents
- Execution slippage < 2 bps vs paper equivalent
- Order rejection rate < 0.5%
- Sharpe on testnet ≥ 0.8× paper Sharpe (some degradation is expected and acceptable)

---

### [ROAD-6] Transaction cost analysis (TCA) report `open`

**Gate**: implement during ROAD-5 testnet run (need live data to validate).

**Why**: TCA breaks down *why* fills are good or bad — essential for tuning and for
proving the strategy to any external stakeholder.

**What to build** (`hbot/scripts/analysis/bot1_tca_report.py`):
- Input: `fills.csv` + `minute.csv` for a given date range
- Output: for each fill, compute:
  - `implementation_shortfall`: fill_price vs mid_at_order_placement
  - `market_impact`: did price move against you in the 60s after fill?
  - `adverse_selection_rate`: fraction of fills where `pnl_vs_mid_pct < 0`
- Aggregate by: regime, time-of-day, order side, spread level
- Print table: which regime has highest adverse selection? Which time of day?

This report directly tells you where to widen spreads or reduce activity.

---

### [ROAD-7] Incident response playbooks `open`

**Gate**: write before first live dollar of capital is deployed.

**Why**: without a playbook, the first real incident becomes a learning experience
that costs money. With a playbook, it's a drill.

**Create `hbot/docs/ops/incident_playbooks/`** with one file per scenario:

| File | Scenario |
|---|---|
| `01_bot_stopped_trading.md` | Bot in SOFT_PAUSE or HARD_STOP unexpectedly |
| `02_kill_switch_fired.md` | Kill-switch triggered — recovery procedure |
| `03_redis_down.md` | Redis went down mid-session — state recovery |
| `04_large_unexpected_position.md` | Position > 2× max_base_pct — manual flatten |
| `05_exchange_api_errors.md` | 429 rate limit or 5xx from exchange |
| `06_daily_loss_limit_hit.md` | HARD_STOP from `max_daily_loss_pct_hard` |

Each playbook: trigger indicators, immediate actions (< 2 min), diagnosis steps, recovery steps, post-incident review checklist.

---

### [ROAD-8] API key hygiene and secrets rotation `open`

**Gate**: before first live capital.

**Current gap**: single `BITGET_API_KEY` used for everything. No rotation procedure.

**What to implement**:
1. Three separate API keys (read-only data, trade-only bot, kill-switch emergency)
2. Kill-switch key has trade+cancel permissions, NO read permissions (reduces surface)
3. Document rotation procedure in `hbot/docs/ops/secrets_and_key_rotation.md` (update the existing file):
   - Rotate every 90 days
   - Steps: create new key → update `.env` → restart services → revoke old key → verify
4. Set up IP allowlist on exchange for all three keys

---

### [ROAD-9] Second uncorrelated strategy `open`

**Gate**: after ROAD-5 testnet live proves bot1 edge. Do not add complexity before edge is confirmed.

**Why**: a single strategy is a single point of failure. Two uncorrelated strategies
improve portfolio Sharpe: `sharpe_portfolio = sqrt(sharpe1² + sharpe2²) / sqrt(2)` when
correlation ≈ 0.

**Options (ranked by implementation effort)**:
1. **ETH-USDT market-making on bot3** (lowest effort — reuse all infrastructure, new pair)
   - Verify correlation of ETH/BTC returns < 0.7 to get real diversification benefit
2. **Trend-following overlay on bot1** (medium effort — same pair, different logic)
   - When `regime == "up"` or `"down"` for > 30 min, take a small directional position
     in addition to market-making
3. **Funding rate arbitrage on bot2** (higher effort — requires cross-exchange)
   - Go long on low-funding exchange, short on high-funding exchange

**Portfolio allocation rule**: allocate capital to each strategy proportional to its
inverse variance: `alloc_i = (1/var_i) / sum(1/var_j)`. Rebalance weekly.
Wire allocation through `hbot/config/multi_bot_policy_v1.json`.

---

### [ROAD-10] AI regime classifier — replace EMA/ATR with learned model `open`

**Gate**: complete after ROAD-2 (walk-forward backtest) produces a labeled training dataset.

**Why**: EMA crossover + ATR threshold is lagged and uses only 2 features. A gradient
boosting classifier trained on 20+ microstructure features can predict regime transitions
1–3 ticks before the price confirms them, giving the bot time to re-price quotes ahead
of the move. This is the highest-ROI AI application for a market-maker.

**What the ML pipeline already provides** (no new infrastructure needed):
- `hbot/services/signal_service/feature_builder.py` — builds feature vectors from
  `MarketSnapshotEvent`. The feature set already covers: mid returns, volume velocity,
  bid-ask spread, order book imbalance, EMA distance, ATR, time-of-day encoding.
- `hbot/services/signal_service/model_loader.py` — loads sklearn joblib, ONNX, or HTTP.
- `hbot/services/signal_service/inference_engine.py` — runs inference, returns
  `(predicted_return, confidence, latency_ms)`.
- `hbot/services/signal_service/main.py` — already publishes `MlSignalEvent` to Redis.
- `hbot/controllers/epp_v2_4.py:1015` — `apply_execution_intent` handles
  `action="set_target_base_pct"` (already wired after P0-1).

**Training data source**:
- `hbot/data/bot1/logs/epp_v24/bot1_a/minute.csv` — each row has `regime` label + all
  features needed (mid, band_pct, drift, imbalance).
- Augment with the historical OHLCV dataset from ROAD-2 for volume.
- Minimum: 10,000 labelled rows (≈ 7 days of 1-minute bars).

**Implementation steps**:

1. **Build training dataset** (`hbot/scripts/ml/build_regime_dataset.py`):
   - Read `minute.csv`, extract feature columns + `regime` label.
   - Encode `regime` as integer: `neutral_low_vol=0, neutral_high_vol=1, up=2, down=3, high_vol_shock=4`.
   - Add lag features: returns at t-1, t-2, t-5 (autocorrelation matters).
   - Output: `hbot/data/ml/regime_train_YYYYMMDD.parquet`.

2. **Train and validate** (`hbot/scripts/ml/train_regime_classifier.py`):
   ```python
   from lightgbm import LGBMClassifier  # or XGBClassifier
   model = LGBMClassifier(n_estimators=200, max_depth=6, learning_rate=0.05)
   # Walk-forward cross-validation: fit on months 1-4, validate on month 5
   # Repeat 3 times with different windows
   # Keep model only if OOS accuracy > 55% AND OOS Sharpe improvement > 0.3
   ```
   Save with `joblib.dump(model, "hbot/data/ml/regime_classifier_v1.joblib")`.

3. **Update `feature_builder.py`**: add lag features (t-1, t-2, t-5 returns) and
   time-of-day sine/cosine encoding (`sin(2π * hour/24), cos(2π * hour/24)`).

4. **Update `inference_engine.py`**: current signature returns `(predicted_return, confidence, ms)`.
   Add a `predict_regime(model, features) -> (regime_str, confidence, ms)` function alongside
   the existing one.

5. **Update `signal_service/main.py`**: when `ML_ENABLED=true` and model is a regime
   classifier (detect via `model.estimator_type == "classifier"`), publish `StrategySignalEvent`
   with `signal_name="regime_override"` and `signal_value=predicted_regime_int`.

6. **Update `hb_bridge.py` signal consumer** (P0-1): handle `signal_name="regime_override"` →
   call `ctrl.apply_execution_intent({"action": "set_regime_override", "regime": regime_str})`.

7. **Add `apply_execution_intent` action in `epp_v2_4.py`**:
   ```python
   if action == "set_regime_override":
       regime = str(metadata.get("regime", "")).strip()
       if regime in self._resolved_specs:
           self._external_regime_override = regime
           self._external_regime_override_expiry = now + 30.0  # expires after 30s
   ```
   In `_detect_regime`: return override if set and not expired, else run normal detection.

8. **Add config**: `ml_regime_enabled: bool = False` in `EppV24Config`. Bridge only routes
   regime overrides when this is True.

9. **Set env vars** in compose for signal-service:
   `ML_ENABLED=true`, `ML_RUNTIME=sklearn_joblib`,
   `ML_MODEL_URI=file:///workspace/hbot/data/ml/regime_classifier_v1.joblib`.

**Acceptance criteria**:
- Walk-forward OOS accuracy ≥ 55% (random baseline = 40% for 4 classes weighted by frequency).
- Walk-forward OOS Sharpe improves ≥ 0.3 vs baseline regime detection (run ROAD-2 with both).
- `minute.csv` shows `regime_source: ml` when classifier is active.
- Falls back to EMA/ATR within 1 tick if Redis or model is unavailable.
- No extra latency > 5ms per tick (inference engine already has `ml_inference_timeout_ms`).

**Do not**:
- Do not deploy without walk-forward validation (OOS Sharpe improvement < 0.3 = worse than nothing).
- Do not retrain on live fill data — training set is historical OHLCV only.
- Do not use deep learning (LSTM, Transformer) on the first version — LightGBM generalizes
  better with small datasets and is fully interpretable.

**Skill reference**: `hbot/.cursor/skills/ml-for-trading-optional/SKILL.md`

---

### [ROAD-11] AI adverse selection classifier — reduce bad fills `open`

**Gate**: complete after ROAD-10 is deployed and validated (regime classifier must be
stable before adding another ML layer).

**Why**: the largest single cost in the current strategy is adverse selection — fills
that happen right before the market moves against the position. `fills.csv` shows
`pos_edge_frac ≈ 0.43` meaning 57% of fills are adverse. Reducing this to 45% would
improve daily PnL by approximately 30%.

**Core idea**: train a binary classifier that predicts, at the moment a quote is placed,
whether a fill on that quote is likely to be adverse (`pnl_vs_mid_pct < -cost_floor`).
If `P(adverse) > threshold`, either (a) widen spread temporarily, or (b) skip quoting
for one executor cycle.

**Training data source**:
- `hbot/data/bot1/logs/epp_v24/bot1_a/fills.csv` — each fill has `pnl_vs_mid_pct`.
  Label: `adverse = 1 if pnl_vs_mid_pct < -0.0002 else 0` (< −2 bps = adverse).
- Join with `minute.csv` on nearest timestamp to get market state features at fill time.
- Minimum: 5,000 fills (≈ 20 days of current fill rate).

**Features at order placement time** (all available from `minute.csv`):
- `ob_imbalance` (from ROAD-3): primary signal — strong ask imbalance → BUY fills likely adverse
- `adverse_drift_ewma_bps`: recent drift trend
- `spread_multiplier`: current spread width
- `regime`: one-hot encoded
- `fills_in_last_60s`: fill burst rate
- `time_of_day_sin/cos`: session pattern
- `base_pct_net`: signed inventory (long positions → ask fills risky, short → bid fills risky)
- `fill_edge_ewma_bps` (from P1-2): recent fill quality trend

**Implementation steps**:

1. **Build training dataset** (`hbot/scripts/ml/build_adverse_fill_dataset.py`):
   - Read `fills.csv` and `minute.csv`, merge on nearest timestamp.
   - Label each fill: `adverse = 1 if pnl_vs_mid_pct < -0.0002`.
   - For class balance: adverse fills are ~57%, so no resampling needed initially.
   - Output: `hbot/data/ml/adverse_fill_train_YYYYMMDD.parquet`.

2. **Train and validate** (`hbot/scripts/ml/train_adverse_classifier.py`):
   ```python
   from lightgbm import LGBMClassifier
   model = LGBMClassifier(n_estimators=100, max_depth=4, class_weight="balanced")
   # Walk-forward: fit on fills 1-3000, validate on fills 3001-4000, test on 4001-5000
   # Metric: precision@recall=0.7 (we want to be right when we flag adverse)
   ```
   Save: `hbot/data/ml/adverse_classifier_v1.joblib`.

3. **Add inference to `hb_bridge.py`** (not `signal_service` — this needs sub-tick latency):
   - Load model once at startup: `self._adverse_model = joblib.load(model_path) if path else None`.
   - In the tick, before calling `_apply_runtime_spreads_and_sizing()`, compute features
     from `processed_data` and call `model.predict_proba(features)[0][1]` → `p_adverse`.
   - If `p_adverse > self.config.adverse_threshold` (default 0.70):
     - Multiply active spreads by `1 + p_adverse * 0.5` (widen proportionally).
     - Log `"adverse_prediction": p_adverse` to processed_data.
   - If `p_adverse > 0.85`: skip quoting for this tick entirely (set spreads to []).

4. **Add config fields** to `EppV24Config`:
   ```python
   adverse_classifier_enabled: bool = Field(default=False)
   adverse_classifier_model_path: str = Field(default="")
   adverse_threshold_widen: Decimal = Field(default=Decimal("0.70"))
   adverse_threshold_skip: Decimal = Field(default=Decimal("0.85"))
   ```

5. **Add to `minute.csv` logging**: `"adverse_p": str(p_adverse)`, `"adverse_active": str(p_adverse > threshold)`.

**Acceptance criteria**:
- OOS precision ≥ 0.60 at recall = 0.70 on held-out fills.
- Adverse fill rate drops ≥ 15% in paper simulation vs baseline (run 5 days with and without).
- No increase in missed-fill rate > 10% (model should not over-suppress quoting).
- Inference latency < 2ms per tick (LightGBM on 10 features is ~0.1ms).

**Do not**:
- Do not use `pnl_vs_mid_pct` from the SAME fill as a feature (data leakage).
- Do not deploy if OOS precision < 0.55 — random baseline is 0.57 (adverse fill rate).
  A model worse than coin-flip on adverse detection actively hurts performance.
- Do not skip quoting for > 3 consecutive ticks — add a `max_consecutive_skip: int = 3` guard
  to prevent the model from silencing the bot during high-opportunity periods.

**Skill reference**: `hbot/.cursor/skills/ml-for-trading-optional/SKILL.md`

---

## Done

| Item | Description | Commit | Date |
|---|---|---|---|
| P1-5 | `order_book_stale` log uses 30s-gated value | `9fef542` | 2026-02-26 |
| — | Add `BACKLOG.md` + `.env.example` | `9fef542` | 2026-02-26 |
| — | Alertmanager empty SLACK_WEBHOOK_URL crash | `6c5faef` | 2026-02-26 |
| — | Kill-switch healthcheck curl → python | `6c5faef` | 2026-02-26 |
| — | Day-2 gate auto-refresh integrity | `6c5faef` | 2026-02-26 |
| — | Derisk direction bug (short→BUY-only) | `23cc76e` | 2026-02-26 |
| — | Derisk spread too wide (add `derisk_spread_pct`) | `23cc76e` | 2026-02-26 |
| — | One-sided regimes on delta-neutral perp | `23cc76e` | 2026-02-26 |
| — | Reconciliation `inventory_drift_critical` false-positive | `1e99ea1` | 2026-02-26 |
| — | Promotion gates policy scope + perpetual base_pct | `3bf0734` | 2026-02-26 |
| — | Artifact hygiene + .gitignore | `199654d` | 2026-02-26 |
