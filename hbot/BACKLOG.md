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

### [P0-1] Wire signal service output into the controller `open`

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
