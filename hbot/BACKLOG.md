# hbot — AI-Executable Backlog

> **For AI agents**: Each item is a complete spec. Read the item you are working on
> fully before touching any code. All design decisions are pre-answered.
> After every change: `python -m py_compile hbot/controllers/epp_v2_4.py` and
> `PYTHONPATH=hbot python -m pytest hbot/tests/ -x -q --ignore=hbot/tests/integration`.

**Tiers**: P0 = blocks live / safety gap · P1 = affects PnL / reliability · P2 = quality
**Status**: `open` · `in-progress (YYYY-MM-DD)` · `done (commit)`

---

## BUILD_SPEC — Multi-Bot Desk Audit Follow-Up (2026-02-27) `in-progress (2026-02-27)`

These items are derived from the `MODE=BUILD_SPEC` audit and are tracked here so implementation can proceed in a deterministic order with explicit acceptance criteria.

### [SPEC-A1] Reconciliation exchange-source preflight gate `done (2026-02-27)`
- Extend `scripts/ops/preflight_startup.py` with a reconciliation readiness check:
  - Require non-empty `BITGET_API_KEY`, `BITGET_SECRET`, `BITGET_PASSPHRASE`
  - Require `RECON_EXCHANGE_SOURCE_ENABLED=true`
  - Validate `reports/reconciliation/latest.json.exchange_source_enabled == true`
  - Validate `reports/exchange_snapshots/latest.json.account_probe.status == "ok"`
- Emit machine-readable evidence to `reports/ops/preflight_recon_latest.json`
- Acceptance: non-compliant env/report state fails preflight with actionable reason.

### [SPEC-A2] Go-live checklist evidence collector `done (2026-02-27)`
- Add `scripts/ops/checklist_evidence_collector.py` to parse `docs/ops/go_live_hardening_checklist.md`
  and produce a structured evidence bundle with item-level status/evidence paths.
- Write outputs:
  - `reports/ops/go_live_checklist_evidence_<timestamp>.json`
  - `reports/ops/go_live_checklist_evidence_latest.json`
- Acceptance: each checklist section has explicit PASS/FAIL/UNKNOWN status and evidence references.

### [SPEC-A3] Telegram alerting validator + evidence artifact `done (2026-02-27)`
- Add `scripts/ops/validate_telegram_alerting.py`:
  - Validate token/chat_id format
  - Probe Telegram `sendMessage` API
  - Return explicit diagnosis (`403_forbidden`, `invalid_chat_id`, `network_error`, `ok`)
- Write `reports/ops/telegram_validation_latest.json`
- Acceptance: failure mode is unambiguous, suitable for promotion gate decisions.

### [SPEC-A4] Promotion gate integration for SPEC-A1/A2/A3 `done (2026-02-27)`
- Extend `scripts/release/run_promotion_gates.py` with new checks:
  - `recon_exchange_live_gate`
  - `go_live_checklist_evidence_gate`
  - `telegram_alerting_gate`
- Extend `scripts/release/run_strict_promotion_cycle.py` to run required refresh/probe steps before strict evaluation.
- Acceptance: strict cycle blocks on missing/failed artifacts for these gates.

### [SPEC-B1] Multi-day strategy summary hardening (ROAD-1 support) `done (2026-02-27)`
- Finalize/standardize `scripts/analysis/bot1_multi_day_summary.py` output contract:
  - `reports/strategy/multi_day_summary_latest.json`
  - Daily table + Sharpe/win-rate/max-drawdown/regime breakdown
- Acceptance: handles missing days deterministically with warnings, never silent drops.

### [SPEC-C1] Testnet readiness gate (ROAD-5 support) `done (2026-02-27)`
- Add `scripts/release/testnet_readiness_gate.py`:
  - Verify kill-switch non-dry-run test evidence
  - Verify testnet credential scope
  - Verify connector/profile readiness
- Output `reports/ops/testnet_readiness_latest.json`
- Acceptance: explicit PASS/FAIL with remediation hints.

### [SPEC-C2] Testnet daily scorecard automation (ROAD-5 support) `done (2026-02-27)`
- Add `scripts/analysis/testnet_daily_scorecard.py` with metrics:
  - fill count ratio, slippage vs paper, rejection rate, cancel-before-fill rate, drift alarms
- Outputs:
  - `reports/strategy/testnet_daily_scorecard_<YYYYMMDD>.json`
  - `reports/strategy/testnet_daily_scorecard_latest.json`
- Acceptance: supports 20-day aggregation and ROAD-5 pass/fail decision.

### [SPEC-D1] Second strategy lane config package (ROAD-9 support) `done (2026-02-27)`
- Add ETH MM bot config package for `bot3` with isolated paths and policy role.
- Acceptance: bot3 ETH lane can be launched independently with existing risk/telemetry stack.

### [SPEC-D2] Portfolio allocator service scaffold (ROAD-9 support) `done (2026-02-27)`
- Add `services/portfolio_allocator/main.py` with policy-driven allocation proposal flow.
- Integrate with `config/multi_bot_policy_v1.json` (non-breaking extension).
- Acceptance: deterministic allocation proposal artifact for weekly rebalance.

### [SPEC-E1] Tests for new gates and ops scripts `done (2026-02-27)`
- Add tests for:
  - preflight reconciliation gate
  - telegram validation classifier
  - checklist evidence collector parser
- Acceptance: deterministic unit tests, no external network dependency.

---

## BUILD_SPEC — Canonical Data Plane Migration (Timescale) `in-progress (2026-03-02)`

Goal: migrate from CSV-first persistence to a canonical event/database plane suitable for semi-pro reliability, while keeping backward-compatible CSV artifacts during transition.

### [SPEC-TS1] Timescale-capable ops DB baseline `open`
- Switch compose Postgres runtime to Timescale-capable image (PG16 compatible) via env-configurable image override.
- Add explicit `.env.template` knobs for DB image, retention windows, compression thresholds, and migration flags.
- Keep current `postgres-data` volume and `ops-db-writer` service contract unchanged.
- Acceptance:
  - `docker compose config` resolves with Timescale image by default.
  - Existing `ops-db-writer` startup still works when Timescale is unavailable (unless strict flag enabled).

### [SPEC-TS2] Schema bootstrap for Timescale migration `open`
- Extend `services/ops_db_writer/schema_v1.sql` with canonical raw event table:
  - `event_envelope_raw` keyed by `(stream, stream_entry_id)` for idempotent replay.
  - Payload JSONB + key dimensions (`event_id`, `event_type`, `instance_name`, `trading_pair`, `ts_utc`, `ingest_ts_utc`).
- Add supporting indexes for time/window queries across `bot_snapshot_minute`, `fills`, and `event_envelope_raw`.
- Acceptance:
  - Schema apply is idempotent.
  - Re-running writer does not duplicate raw events for same stream entry IDs.

### [SPEC-TS3] Timescale hypertable + policy bootstrap in writer `open`
- Add bootstrap logic in `services/ops_db_writer/main.py`:
  - optional `CREATE EXTENSION IF NOT EXISTS timescaledb`.
  - convert `bot_snapshot_minute`, `fills`, `event_envelope_raw` to hypertables when extension exists.
  - apply configurable retention and compression policies (if enabled).
- Add strict/soft behavior:
  - strict mode fails run when Timescale is required but unavailable.
  - soft mode logs warning and continues as plain Postgres.
- Acceptance:
  - Writer evidence (`reports/ops_db_writer/latest.json`) includes migration metadata.
  - Policies are applied idempotently (`if_not_exists` semantics).

### [SPEC-TS4] Event-store dual-write (JSONL + DB raw events) `open`
- Extend `services/event_store/main.py` with optional DB mirror sink:
  - write normalized envelopes to `event_envelope_raw` before ACK.
  - keep JSONL + integrity artifacts as compatibility path.
  - if DB mirror enabled and write fails, leave stream entries unacked for replay.
- Acceptance:
  - With mirror enabled, ACK occurs only after file + stats + DB success.
  - With mirror disabled, behavior remains identical to current baseline.

### [SPEC-TS5] Backfill and reconciliation utilities `open`
- Add deterministic backfill flow from existing artifacts:
  - `reports/event_store/events_*.jsonl` -> `event_envelope_raw`
  - `data/*/logs/epp_v24/*/fills.csv` + `minute.csv` -> canonical tables (existing writer path).
- Emit parity artifacts:
  - row counts by day/source
  - mismatch list for missing/duplicate rows
- Acceptance:
  - Backfill is idempotent.
  - DB-vs-CSV parity deltas are explicit and machine-readable.

### [SPEC-TS6] DB-first read path with CSV fallback `open`
- Update downstream consumers (`tradenote_sync`, selected analysis/report scripts) to prefer DB reads when enabled:
  - fallback to current CSV path if DB unavailable.
- Add feature flag and evidence in outputs indicating active source (`db` vs `csv`).
- Acceptance:
  - No consumer regression when DB-first disabled.
  - Consumers surface source mode in report metadata.

### [SPEC-TS7] Cutover guardrails and promotion gates `open`
- Add release gate checks for canonical plane:
  - DB ingest freshness
  - DB-vs-CSV parity thresholds
  - duplicate suppression rate
  - event-store replay lag under threshold
- Acceptance:
  - Strict promotion cycle blocks cutover if canonical-plane checks fail.

### [SPEC-TS8] Backup/restore + rollback drills `open`
- Define and automate:
  - Postgres/Timescale backup cadence and verification.
  - restore drill to fresh instance.
  - rollback path from `db_primary` to `csv_compat` flags.
- Evidence outputs in `reports/ops/`.
- Acceptance:
  - Restore recovers canonical tables and latest parity state.
  - Rollback can be performed in < 5 minutes with documented commands.

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

### [P0-2] HARD_STOP must publish a kill-switch execution intent `done (2026-02-26)`

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
- `hbot/env/.env.template` — shows which vars to set.

**Action (config only — no code)**:
1. Ensure `hbot/env/.env` has the required vars (see `hbot/env/.env.template`).
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

### [P1-1] Add funding rate to the spread floor cost model `done (2026-02-26)`

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

### [P1-2] Realized-edge tracker with auto-widen `done (2026-02-26)`

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

### [P1-3] EOD position close at daily rollover `done (2026-02-26)`

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

### [P1-4] OHLCV candles for regime EMA/ATR `done (2026-02-26)`

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

### [P1-6] Add `neutral_high_vol` regime `done (2026-02-26)`

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

### [P1-7] Automated daily paper-state backup `done (2026-02-26)`

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

### [P1-8] Audit `risk_service` for completeness `done (2026-02-26)`

**What exists**: `hbot/services/risk_service/main.py` — 112 lines. Compare to
`portfolio_risk_service/main.py` (335 lines) and `reconciliation_service/main.py` (465 lines).

**Action**: Read `risk_service/main.py` end-to-end. Check:
- Does it have a complete poll loop?
- Does it write `reports/risk_service/latest.json`?
- Does it publish to `hb.audit.v1`?
- Does it use `ShutdownHandler`?
If any are missing, implement. If it's intentionally a thin wrapper, add a comment explaining its role.

---

### [P1-9] Decide on ClickHouse: wire or disable `done (2026-02-26)`

**What exists**: `hbot/services/clickhouse_ingest/main.py` (232 lines) is in compose
but no `clickhouse` server service exists in `docker-compose.yml`. Ingest events are dropped.

**Decision needed from operator**: Is ClickHouse planned? If yes → add to compose.
If no → comment out or remove the ingest service from compose to eliminate the log noise.
For now, recommended action: **comment it out** in compose with a note, and add a
`# To enable: see clickhouse_ingest/README.md` marker.

---

## P2 — Quality / Completeness

---

### [P2-1] Add tests for critical untested modules `done (2026-02-26)`

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

### [P2-2] Validate Grafana alert rules with synthetic breach `done (2026-02-26)`

**What exists**: `hbot/monitoring/prometheus/alert_rules.yml` — defines rules.
No validation script exists.

**Action**: Create `hbot/scripts/ops/synthetic_alert_test.py` that:
1. Temporarily writes a metric value above threshold to a test Prometheus pushgateway.
2. Waits 30s for alert to fire.
3. Checks `http://localhost:9093/api/v1/alerts` for the expected alert.
4. Cleans up.

---

### [P2-3] Configure Telegram alerting `done (2026-02-26)`

Replaced Slack with Telegram (native Alertmanager receiver — no webhook proxy needed).

**To activate** (config-only, 5 min):
1. Message `@BotFather` on Telegram → `/newbot` → copy the token.
2. Add bot to a group or DM it, visit `https://api.telegram.org/bot<TOKEN>/getUpdates` for `chat_id`.
3. Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`.
4. Uncomment `telegram_configs` in `monitoring/alertmanager/alertmanager.yml`.
5. `docker compose restart alertmanager`.

---

### [P2-4] Document signal → controller data flow `done (2026-02-26)`

**File**: `hbot/docs/architecture/data_flow_signal_risk_execution.md` — check if it exists
and covers the full loop from `signal_service` → Redis → `hb_bridge` → `apply_execution_intent`
→ `_external_target_base_pct_override`. Add or update after P0-1 is implemented.

---

## Path to 9.5 / 10 — Beyond the Backlog

> These are not bug fixes. They are the items that turn a well-engineered paper bot
> into a validated, deployable semipro trading desk. Work through them in order —
> each stage gates the next. Do not skip ahead.

### Scoring map

| Stage | Score | Gate | Status |
|---|---|---|---|
| Bugs fixed, infrastructure stable | 6.5 | — | **Done 2026-02-27** |
| Backlog P0 + P1 + ROAD infra complete | 7.5 | Bot running cleanly | **Done 2026-02-27** |
| 20-day paper run validated | 8.0 | Sharpe ≥ 1.5, PnL positive | **Waiting: 20 days paper data** |
| Walk-forward backtest passes | 8.5 | OOS edge on 6m history | Code ready — run after 8.0 gate |
| Order book signals + Kelly sizing | 8.8 | Edge stable after sizing change | **Code done 2026-02-27** (disabled by default) |
| 4-week testnet live | 9.0 | No safety incidents, execution ≈ paper | **Waiting: testnet API keys + 28 days** |
| TCA + incident playbooks + secrets hygiene | 9.3 | All checklist items signed off | **Code done 2026-02-27** |
| AI: regime classifier replaces EMA/ATR | 9.4 | Walk-forward Sharpe improves ≥ 0.3 | **Code done 2026-02-27** — needs ≥10k rows |
| AI: adverse selection classifier wired | 9.5 | Adverse fill rate drops ≥ 15% OOS | **Code done 2026-02-27** — needs ≥5k fills |
| Second uncorrelated strategy | 9.5+ | Portfolio Sharpe > single-strategy Sharpe | Open |

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

### [ROAD-2] Walk-forward backtest on 6-month historical data `done (2026-02-27)`

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

### [ROAD-3] Order book imbalance signal `done (2026-02-27)`

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

### [ROAD-4] Kelly-adjusted position sizing `done (2026-02-27)`

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

### [ROAD-6] Transaction cost analysis (TCA) report `done (2026-02-27)`

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

### [ROAD-7] Incident response playbooks `done (2026-02-27)`

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

### [ROAD-8] API key hygiene and secrets rotation `done (2026-02-27)` — docs created, human action required for key creation

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

### [ROAD-10] AI regime classifier — replace EMA/ATR with learned model `done (2026-02-27)` — infrastructure only, model training requires ≥10k minute.csv rows

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

### [ROAD-11] AI adverse selection classifier — reduce bad fills `done (2026-02-27)` — infrastructure only, model training requires ≥5k fills

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

## Infrastructure Fixes (Surfaced 2026-02-27)

---

### [INFRA-1] Watchdog STATE_FILE persists across container recreates `done (2026-02-27)`

**Problem**: `STATE_FILE = Path("/tmp/watchdog_state.json")` is wiped on every `docker compose up`
(container recreate). Circuit breaker resets to zero — bot can be restarted 5 more times even
after a known-bad config is never fixed.

**Fix**: Changed to `Path(HB_DATA_ROOT) / "watchdog_state.json"` so the file survives recreates.
Also added `WATCHDOG_STATE_FILE` env var override.

---

### [INFRA-2] Always pass `--env-file` when running `docker compose up` `done (2026-02-27)`

**Problem**: Running `docker compose up` without `--env-file hbot/env/.env` bakes empty strings
into container env vars (e.g. `CONFIG_PASSWORD=`). The Hummingbot quickstart interprets empty
`CONFIG_PASSWORD` as "not set" → falls through to interactive login prompt → bot hangs forever.
The watchdog then burns all 5 circuit-breaker restarts with no progress.

**Fix applied**: Created `hbot/scripts/ops/compose_up.sh` wrapper that always injects `--env-file`.
Added `preflight_startup.py` and `--check-bot-preflight` to promotion gates. Strict cycle runs
preflight with `--require-bot-container` when in CI.

---

### [INFRA-3] Compose lint: writable `reports/` overlay required for services that write `done (2026-02-27)`

**Problem**: `risk-service` volume was `..:/workspace/hbot:ro` with no writable overlay for
`reports/`. Service crashed with `OSError: [Errno 30] Read-only file system` on every startup.

**Fix applied**: Added `../reports:/workspace/hbot/reports` overlay to `risk-service` in
`docker-compose.yml` (same pattern as `coordination-service`). Also created missing
`hbot/reports/risk_service/` directory.

**Follow-up**: Add a compose lint check to promotion gates — any service that calls
`_write_latest()` or creates files in `reports/` must have a writable overlay.

---

### [INFRA-4] Telegram BOT_TOKEN 403 — alerting currently silent `open`

**Problem**: All Telegram alerts from watchdog and alertmanager are failing with
`HTTP Error 403: Forbidden`. The `TELEGRAM_BOT_TOKEN` in `env/.env` is revoked.
The 5 failed restarts this morning sent **zero alerts**.

**Code done (2026-02-27)**: `check_alerting_health.py` now probes Telegram API first.
Promotion gates will fail if Telegram is configured but returns 403.

**Fix required** (human action):
1. `@BotFather` → `/mybots` → select bot → `Revoke current token` → copy new token.
2. Update `TELEGRAM_BOT_TOKEN` in `hbot/env/.env`.
3. Restart affected services: `docker compose --env-file hbot/env/.env ... restart bot-watchdog alertmanager`.
4. Add `check_alerting_health.py` assertion to promotion gates — must pass before any live capital.

---

### [INFRA-5] Unify observability data plane (single source for Telegram + Grafana + gates) `done (2026-02-28)`

**Problem**: Current desk views read from different paths:
- Telegram command bot reads `minute.csv`, `fills.csv`, `open_orders_latest.json`, and `reports/*.json` directly.
- Grafana reads Prometheus/Loki via exporters/services that also parse files.

This split creates drift risk: one surface can look healthy while another is stale or missing rows.
When bot/controller bugs occur (tick loop stalls, writer failure, schema drift), `minute.csv` and
derived metrics can silently diverge across consumers.

**Design decision**: Introduce a canonical observability read model:
1. `event_store` (streams) remains write-ahead history.
2. Add a `desk_snapshot_service` that materializes a single `latest` snapshot contract per bot
   (state, fills freshness, orders, risk, gates, health) from streams/files with explicit freshness metadata.
3. Make Telegram and Grafana read this same snapshot contract (Grafana via exporter metrics generated from it).
4. Add contract tests + freshness SLO checks so any missing `minute`/fills/orders data fails promotion gates.

**Implementation steps**:
1. Define schema: `reports/desk_snapshot/<bot>/latest.json` with `source_ts`, `age_s`, `completeness`, `schema_version`.
2. Implement `services/desk_snapshot_service/main.py` (idempotent merge, partial-source diagnostics).
3. Update `services/telegram_bot/main.py` to use desk snapshot first, fallback to direct files only on missing snapshot.
4. Update `services/bot_metrics_exporter.py` to emit metrics from desk snapshot fields (single mapping layer).
5. Add gate script `scripts/release/validate_data_plane_consistency.py`:
   - file vs snapshot parity checks
   - snapshot freshness thresholds
   - required-field completeness score.
6. Add dashboard panel and alert: `data_plane_consistency_status`.

**Acceptance criteria**:
- Telegram `/status` and Grafana key stats are sourced from the same snapshot values.
- If bot minute pipeline stalls for >2 minutes, consistency gate fails with explicit diagnosis.
- If any required snapshot field is missing, exporter emits a red status metric and promotion gate blocks.
- End-to-end replay test confirms deterministic snapshot reconstruction from event stream for a day.

---

## Tech Debt — Surfaced by Architecture Audit (2026-02-27)

---

### [DEBT-1] Split `epp_v2_4.py` god class into modules `done (2026-02-27)`

**Priority**: P1 — affects maintainability and testability.

**Problem**: `epp_v2_4.py` is 2,473 lines with regime detection, spread computation,
risk evaluation, execution emission, position accounting, and logging all in one class.
Hard to test, hard to change, high cognitive load.

**What already exists**:
- `controllers/regime_detector.py` (45 lines) — stub with helpers, not used by the controller.
- `controllers/spread_engine.py` (81 lines) — stub with helpers, not used by the controller.
- `controllers/risk_policy.py` (91 lines) — used by the controller for limit evaluation.

**Design decision**: Extract these methods from `EppV24Controller` into standalone classes
that the controller composes:

| Method group | Target module | Est. lines |
|---|---|---|
| `_detect_regime`, `_get_ohlcv_ema_and_atr` | `regime_detector.py` | ~150 |
| `_compute_spread_and_edge`, `_compute_levels_and_sizing` | `spread_engine.py` | ~250 |
| `_evaluate_all_risk`, `_evaluate_market_conditions` | `risk_evaluator.py` (new) | ~200 |
| `_emit_tick_output`, `_log_minute` | `tick_emitter.py` (new) | ~300 |

**Constraints**:
- Each extracted class receives only what it needs via method args (no access to `self`).
- Controller becomes orchestrator (~500 lines): `__init__`, `on_tick`, `did_fill_order`,
  `_preflight`, `_resolve_guard_state`, `apply_execution_intent`.
- No change in behavior — extraction only.

**Acceptance criteria**:
- `python -m py_compile hbot/controllers/epp_v2_4.py` passes.
- All existing tests pass unchanged.
- `epp_v2_4.py` drops below 800 lines.

---

### [DEBT-2] Add `epp_v2_4` core unit tests `done (2026-02-27)`

**Priority**: P1 — only `test_epp_v2_4_state.py` (179 lines) exists, covering state
transitions only. Zero tests for spread computation, regime detection, risk evaluation,
or fill handling.

**What to test** (priority order):

1. `_detect_regime`: synthetic price buffer → expected regime for each of 5 regimes +
   regime hold and transition.
2. `_compute_spread_and_edge`: regime + costs → expected spread floor, net edge, fill factor.
   Test funding rate contribution, drift spike multiplier, adverse fill multiplier.
3. `_evaluate_all_risk`: over-limit scenarios (daily loss, drawdown, turnover) → expected
   risk_reasons and hard_stop flag.
4. `did_fill_order`: fill edge EWMA update, adverse fill counter, EOD close flag.
5. `_apply_runtime_spreads_and_sizing`: Kelly sizing path when enabled.

**Pattern**: Mock `MarketMakingControllerBase` and `ConnectorRuntimeAdapter`. Instantiate
`EppV24Controller` with `EppV24Config` and synthetic data. Easier after DEBT-1 extraction.

**Acceptance criteria**:
- ≥20 test cases covering all 5 areas above.
- `PYTHONPATH=hbot python -m pytest hbot/tests/controllers/test_epp_v2_4_core.py -x -q` passes.

---

### [DEBT-3] Split `hb_bridge.py` mixed responsibilities `done (2026-02-27)`

**Priority**: P2 — the file is 1,040 lines mixing signal consumer, kill-switch publisher,
adverse model loader, desk driver, HB event translation, and framework shims.

**Design decision**: Split into focused modules under `controllers/paper_engine_v2/`:

| Module | Responsibility | Est. lines |
|---|---|---|
| `hb_bridge.py` | Core bridge: desk driving, order delegation, balance patching | ~500 |
| `signal_consumer.py` (new) | `_consume_signals`, `_check_hard_stop_transitions` | ~200 |
| `adverse_inference.py` (new) | `_load_adverse_model`, `_build_adverse_features`, `_run_adverse_inference` | ~200 |
| `hb_event_fire.py` (new) | `_fire_fill_event`, `_fire_cancel_event`, `_fire_reject_event` | ~200 |

`drive_desk_tick()` stays in `hb_bridge.py` and calls into the split modules.

**Acceptance criteria**:
- All 14 `test_hb_bridge_signal_routing.py` tests pass.
- No import changes needed in `v2_with_controllers.py`.

---

### [DEBT-4] Document config hierarchy `done (2026-02-27)`

**Priority**: P2 — config comes from env vars (100+), JSON files (15), YAML controller
config, and Docker Compose env blocks. No single doc explains precedence.

**Action**: Create `hbot/docs/infra/config_hierarchy.md` documenting:
1. Env var → Docker Compose env → service default
2. JSON policy configs → loaded at service startup
3. YAML controller config → loaded by Hummingbot strategy
4. Precedence: `fee_mode: auto` tries API → project JSON → manual YAML
5. Which vars are required vs optional for each deployment profile

---

### [DEBT-5] Increase service-layer test coverage `done (2026-02-27)`

**Priority**: P2 — 5 test files (230 lines) for 14 services (5,300 lines). Only event
schemas, intent idempotency, and ML subsystem are tested.

**Priority test targets**:
1. `reconciliation_service/main.py` — drift calculation with mocked exchange data.
2. `coordination_service/main.py` — risk decision → intent transformation.
3. `event_store/main.py` — stream → JSONL write and integrity.
4. `bot_watchdog/main.py` — circuit breaker state machine.
5. `kill_switch/main.py` — cancel-all with mocked ccxt.

**Pattern**: Each test mocks Redis with `unittest.mock.patch`. Tests verify `latest.json`
output shape and audit event publishing.

---

### [DEBT-6] Remove or finalize ClickHouse `done (2026-02-27)`

**Priority**: P2 — `services/clickhouse_ingest/main.py` (232 lines) exists in the codebase
but both ClickHouse services are commented out in compose. Code is dead weight.

**Decision needed**: If ClickHouse is planned, uncomment in compose and document setup.
If not, delete `services/clickhouse_ingest/` and the commented-out compose block to
reduce confusion.

**Recommended action**: Delete — Postgres + JSONL event store covers the analytics need.

---

## Code Quality — Surfaced by Quality Audit (2026-02-27)

---

### [QUAL-1] Group 60+ instance vars into state dataclasses `done (2026-02-27)` — types defined, wiring pending

**Priority**: P2 — improves readability and IDE support for `epp_v2_4.py`.

**Problem**: `__init__` declares 60+ instance variables with no structural grouping.
State management is implicit — every method can read/write any of them.

**Design decision**: Group into typed frozen/unfrozen dataclasses:

| Dataclass | Variables | Mutable? |
|---|---|---|
| `PositionState` | `_position_base`, `_avg_entry_price`, `_realized_pnl_today`, `_position_drift_pct` | Yes |
| `DailyCounters` | `_traded_notional_today`, `_fills_count_today`, `_fees_paid_today_quote`, `_cancel_budget_breach_count` | Yes |
| `RegimeState` | `_active_regime`, `_pending_regime`, `_regime_source`, `_regime_hold_counter` | Yes |
| `FillEdgeState` | `_fill_edge_ewma`, `_fill_edge_variance`, `_fill_count_for_kelly`, `_adverse_fill_count` | Yes |
| `FeeState` | `_maker_fee_pct`, `_taker_fee_pct`, `_fee_source`, `_fee_resolved`, `_fee_resolution_error` | Yes |

**Constraints**:
- Each dataclass lives in `controllers/core.py` or a new `controllers/state_types.py`.
- No behavioral change — this is a refactor.
- Controller methods access `self._position.base` instead of `self._position_base`.

**Acceptance criteria**:
- All tests pass unchanged.
- IDE auto-complete works on grouped state fields.

---

### [QUAL-2] Replace long parameter lists with typed dataclass args `done (2026-02-27)` — TickContext defined, wiring pending

**Priority**: P2 — `_emit_tick_output` has 16 params, `_build_tick_output` has 15.

**Problem**: Long parameter lists make call sites fragile and hard to review.
Adding a new field requires changing every caller and the function signature.

**Design decision**: Create a `TickContext` dataclass that bundles all tick-related
inputs. Pass `TickContext` as a single arg. The dataclass documents the full interface
contract at one location.

**Acceptance criteria**:
- `_emit_tick_output` and `_build_tick_output` accept `TickContext` instead of 15+ positional args.
- All callers adapted.
- No behavioral change.

---

### [QUAL-3] Type `processed_data` with a `ProcessedState` TypedDict `done (2026-02-27)`

**Priority**: P2 — `self.processed_data` is `Dict[str, Any]` with 70+ keys.
Typos in key names are not caught by any tool.

**Problem**: Every access is `self.processed_data.get("key_name", default)` with no
compile-time checking. A typo in a key name silently returns the default, which can
cause subtle behavioral drift (e.g., risk check sees zero when it should see a value).

**Design decision**: Define `class ProcessedState(TypedDict, total=False)` in
`controllers/core.py` with all 70+ keys typed. Annotate `self.processed_data: ProcessedState`.
This provides IDE auto-complete and mypy checking without runtime cost.

**Acceptance criteria**:
- `mypy hbot/controllers/epp_v2_4.py --ignore-missing-imports` reports no new errors.
- All existing keys are covered in the TypedDict.

---

### [QUAL-4] Order book staleness check: use monotonic clock `done (2026-02-27)`

**Priority**: P2 — low likelihood of issue in practice but theoretically incorrect.

**Problem**: In `_evaluate_market_conditions`, the order book staleness check compares
`book_ts` (exchange-provided UTC timestamp) against `now_ts` (local wall clock).
If there is any clock skew between the local machine and the exchange, the staleness
detection will be too aggressive or too lenient.

**Design decision**: Compare against the Hummingbot framework's `market_data_provider.time()`
which uses a synchronized clock. If `book_ts` is exchange-provided, compare delta against
`now_ts` from the same source. Add a `max_clock_skew_s: int = 5` tolerance.

**Acceptance criteria**:
- Staleness check uses consistent time source.
- `max_clock_skew_s` config field added.

---

### [QUAL-5] `_cancel_per_min` thread safety `done (2026-02-27)`

**Priority**: P2 — currently runs single-threaded but will matter if ever parallelized.

**Problem**: `_cancel_per_min()` mutates `self._cancel_events_ts` during a list
comprehension read. In the current single-threaded model this is safe, but it would
break silently if the tick ever runs concurrently with `did_cancel_order`.

**Design decision**: Filter into a new list, then assign atomically:

```python
def _cancel_per_min(self, now: float) -> int:
    recent = [ts for ts in self._cancel_events_ts if now - ts <= 60.0]
    self._cancel_events_ts = recent
    return len(recent)
```

**Acceptance criteria**:
- No behavioral change.
- Thread-safe assignment pattern.

---

## Execution Reliability — Surfaced by Execution Audit (2026-02-27)

---

### [EXEC-1] Kill switch should stop the bot container after cancel-all `done (2026-02-27)`

**Priority**: P0 — after cancelling orders, the bot continues running and can place new ones.

**Problem**: `_cancel_all_orders_ccxt` cancels open orders but doesn't stop the bot
container. The bot's next tick can place new orders immediately after the kill switch fires.

**Design decision**: After `_cancel_all_orders_ccxt` completes, issue `docker stop {bot_container}`
via Docker API (same approach as watchdog). Add configurable `stop_bot_on_kill: bool = True`.

**Acceptance criteria**:
- Kill switch fires → open orders cancelled → bot container stopped within 10s.
- Bot does not place new orders between cancel-all and container stop.

---

### [EXEC-2] Wire `ExchangeRateLimiter` into services `done (2026-02-27)`

**Priority**: P1 — token bucket rate limiter exists (`services/common/rate_limiter.py`)
but has zero imports anywhere. Multiple services hit exchange APIs concurrently with only
ccxt's built-in rate limiting as protection.

**Problem**: `ExchangeRateLimiter` with Bitget (10/s) and Binance (20/s) defaults was
built but never wired. `fee_provider.py` makes direct `urlopen` calls with no rate
limiting or retry.

**Implementation**:
1. Wire `ExchangeRateLimiter.wait_if_needed("bitget")` before API calls in:
   - `fee_provider.py` (line 107, `urlopen` call)
   - `exchange_snapshot_service/main.py` (before ccxt calls)
   - `protective_stop.py` (before ccxt calls)
2. Share a single `ExchangeRateLimiter` instance across services via env-based config.

**Acceptance criteria**:
- 4-hour soak test shows zero 429 responses in logs.
- `fee_provider.py` wrapped in `with_retry` with rate limiter.

---

### [EXEC-3] Exchange snapshot service: fetch perp positions `done (2026-02-27)`

**Priority**: P1 — exchange snapshot only fetches spot balances (`defaultType: "spot"`)
making reconciliation vs exchange blind to perpetual futures positions.

**Problem**: For the primary BTC-USDT perp use case, the exchange snapshot shows
`BTC: 0.0` even with an open perp position. The reconciliation service compares local
state against itself when running in `proxy_local` mode.

**Implementation**:
1. In `exchange_snapshot_service/main.py`, add `ccxt.fetch_positions()` for futures pairs.
2. Add `product_type: "USDT-FUTURES"` to ccxt config for Bitget.
3. Output perp positions alongside spot balances in the snapshot JSON.
4. Change default `snapshot_mode` from `proxy_local` to `bitget_ccxt_private` when
   API credentials are available.

**Acceptance criteria**:
- `exchange_snapshots/latest.json` shows perp positions with amounts.
- Reconciliation service can compare controller `position_base` against exchange snapshot.

---

### [EXEC-4] Redis failure counter and operator visibility `done (2026-02-27)`

**Priority**: P1 — Redis operations silently return `None` / `[]`. No counter, no metric.
Kill switch becomes deaf and audit trail drops with no operator notification.

**Problem**: `hb_bridge/redis_client.py` reconnects with exponential backoff but never
surfaces failure counts. An operator wouldn't know Redis has been down for 30 minutes.

**Implementation**:
1. Add `_consecutive_failures: int` to `RedisStreamClient`.
2. Log WARNING on first failure, ERROR after 5 consecutive failures.
3. Expose `redis_failure_count` property for consumption by `processed_data`.
4. Add `redis_down_since_ts` metric for Prometheus/Grafana.

**Acceptance criteria**:
- `redis_failure_count > 0` visible in `minute.csv` or `processed_data`.
- WARNING log fires on first Redis failure.

---

### [EXEC-5] Stuck-executor escalation to OpsGuard `done (2026-02-27)`

**Priority**: P1 — stuck orders (ack timeout) generate `logger.warning` but don't
feed into OpsGuard. If many orders consistently time out (exchange degradation), the
system keeps retrying without escalating.

**Implementation**:
1. Count consecutive ticks with stuck executors in `executors_to_refresh()`.
2. After N consecutive ticks (configurable, default 5), set `operational_failure = True`
   in the `OpsSnapshot`.
3. OpsGuard will naturally escalate: 6 consecutive → HARD_STOP.

**Acceptance criteria**:
- 5 consecutive ticks with stuck executors → SOFT_PAUSE.
- 6+ consecutive → HARD_STOP.

---

### [EXEC-6] Add level-id deduplication guard `done (2026-02-27)`

**Priority**: P2 — `get_levels_to_execute()` can return the same level_id in consecutive
ticks before the executor is tracked, potentially creating duplicate orders.

**Problem**: No idempotency key ties a level_id to a specific order placement attempt.
The `max_active_executors` cap limits blast radius but doesn't prevent level-specific
duplication.

**Implementation**:
1. Track recently-issued level_ids with a TTL (e.g., `executor_refresh_time` seconds).
2. In `get_levels_to_execute()`, skip level_ids that were issued within the TTL.
3. Clear the TTL entry when the executor transitions to `is_trading`.

**Acceptance criteria**:
- No duplicate executors for the same level within one refresh cycle.

---

### [EXEC-7] Add `async_with_retry` variant `done (2026-02-27)`

**Priority**: P2 — `with_retry` is synchronous only (`time.sleep`). Async services
cannot use it.

**Implementation**:
Add `async_with_retry` to `services/common/retry.py` using `asyncio.sleep` instead
of `time.sleep`, with the same backoff + jitter logic.

**Acceptance criteria**:
- Async services can use retry with exponential backoff.
- Same jitter and retryable-pattern logic as sync variant.

---

### [EXEC-8] Recon escalation on repeated drift `done (2026-02-27)`

**Priority**: P2 — if position reconciliation auto-corrects 10+ times in a row
(systematic desync), no alert fires from the controller. Root cause never investigated.

**Implementation**:
1. Count consecutive auto-corrections in `_check_position_reconciliation`.
2. After 3 corrections in 1 hour, enter SOFT_PAUSE with reason
   `"position_drift_repeated"`.
3. Log at ERROR level.

**Acceptance criteria**:
- 3 consecutive drift corrections within 1 hour → SOFT_PAUSE.
- `minute.csv` shows `position_drift_repeated` in `risk_reasons`.

---

### [EXEC-9] Build SimBroker for live-vs-paper calibration `done (2026-02-27)`

**Priority**: P2 — needed before live capital deployment to measure paper fill rate
optimism and adverse selection gap.

**Problem**: Paper's `prob_fill_on_limit: 1.0` overstates fill rate by 2-3x.
No mechanism exists to measure the gap until live trading starts.

**Design**: Stateless per-tick shadow executor in `controllers/sim_broker.py` (~200 lines):
- Receives `processed_data` dict each tick.
- Simulates fills using `QueuePositionFillModel` with calibrated `prob_fill_on_limit: 0.35`.
- Tracks `shadow_position`, `shadow_pnl`, `shadow_fill_rate`.
- Appends to `shadow_minute.csv` alongside `minute.csv`.
- Computes: `live_fill_rate / shadow_fill_rate`, `edge_drift_bps`, `adverse_rate_delta`.

**Acceptance criteria**:
- `shadow_minute.csv` produced alongside `minute.csv`.
- Fill rate ratio metric available in Grafana.

---

### [EXEC-10] Open-order recovery after restart `done (2026-02-27)` — warning log + flag (framework limitation)

**Priority**: P2 — after a restart, the bot recovers position from the exchange but
does not detect or cancel in-flight orders. Orphan orders can fill and create
untracked position changes.

**Implementation**:
1. In `_run_startup_position_sync`, after position sync, call
   `exchange.fetch_open_orders(symbol)`.
2. Cancel any open orders not tracked by the framework.
3. Log cancelled orphan orders.

**Acceptance criteria**:
- Restart with open orders on exchange → orphan orders cancelled.
- Log entry for each cancelled orphan.

---

### [EXEC-11] `cancel_all_stops` no-op in `BitgetStopBackend` `done (2026-02-27)`

**Priority**: P2 — `protective_stop.py`'s `BitgetStopBackend.cancel_all_stops` is a no-op.
Stale protective stop orders may remain on the exchange after cleanup.

**Implementation**: Implement via `ccxt.fetch_open_orders()` + filter by stop order type
+ cancel each.

---

### [EXEC-12] Tune paper fill model defaults `done (2026-02-27)`

**Priority**: P2 — `prob_fill_on_limit: 1.0` means 100% fill probability when price
touches the order level. Real queue fill probability for BTC-USDT perps is 20-40%.

**Action**: Change default in `fill_models.py` from `1.0` to `0.4`. Add config
documentation noting that this directly affects paper PnL optimism.

---

### [EXEC-13] Go-live hardening checklist additions `done (2026-02-27)`

**Priority**: P1 — the existing 14-item checklist needs 10 more items identified
by the execution reliability audit.

**Items to add to `docs/ops/go_live_hardening_checklist.md`**:

15. Framework patch audit: verify `enable_framework_paper_compat_fallbacks()` patches
    disabled in live mode
16. `connector.ready` returns real health state (not hardcoded `True`)
17. NTP/clock drift: verify drift < 2s vs exchange server time
18. Kill switch stops bot container after cancel-all
19. Startup sync failure → HARD_STOP (verified)
20. Exchange snapshot fetches perp positions
21. Rapid partial fill stress test (50+ fills/order on testnet)
22. Network partition test (30s disconnect mid-trading)
23. Redis outage test (5 min stop, verify safe operation)
24. `did_fail_order` streak fix verified

---

## STRATEGY LOOP - INITIAL_AUDIT Follow-Up (2026-02-28) `done (2026-02-28)`

### [P0-STRAT-20260228-1] Enforce event and parity evidence freshness in strict cycle `done (2026-02-28)`

**Why it matters**: Promotion can pass with stale or contradictory evidence, which hides real execution/accounting blind spots before live readiness decisions.

**What exists now**:
- `hbot/reports/promotion_gates/latest.json` can show pass while newer day2 evidence has `go: false`.
- `hbot/reports/event_store/day2_gate_eval_latest.json` can fail delta tolerance after a pass artifact already exists.
- `hbot/reports/parity/latest.json` can pass with core metrics marked `insufficient_data`.

**Design decision (pre-answered)**: Strict cycle must require fresh day2 evidence with `go == true`, and parity must fail when active-bot core deltas are non-informative.

**Implementation steps**:
1. Update `hbot/scripts/release/run_strict_promotion_cycle.py` to fail if day2 gate is stale or `go != true`.
2. Update `hbot/scripts/release/run_promotion_gates.py` parity gate to fail when fill/slippage/reject deltas are all `insufficient_data` for active bot scope.
3. Add or extend tests in `hbot/tests/services/` for stale-artifact and insufficient-data fail paths.

**Acceptance criteria**:
- Strict cycle fails when `day2_gate_eval_latest.json` is stale or `go: false`.
- Strict cycle fails when parity core metrics are all insufficient for active scope.
- Strict cycle passes only with fresh and internally consistent evidence.

**Do not**:
- Do not bypass by raising thresholds or downgrading these checks to warning.

---

### [P0-STRAT-20260228-2] Escalate missing fill-event parity to critical for active bots `done (2026-02-28)`

**Why it matters**: When minute telemetry shows fills but event store has zero fill events, accounting and parity checks are not trustworthy.

**What exists now**:
- `hbot/services/reconciliation_service/main.py` emits `fills_present_without_order_filled_events` as warning.
- `hbot/reports/reconciliation/latest.json` has active-day cases with `fills_today > 0` and `fills_events = 0`.

**Design decision (pre-answered)**: Treat this condition as critical for active bot-day scope and include explicit diagnostics in the finding payload.

**Implementation steps**:
1. In `hbot/services/reconciliation_service/main.py`, elevate severity to critical when active day has `fills_today > 0` and `fills_events == 0`.
2. Include bot/day/event_file and count details in the critical payload.
3. Add regression tests in `hbot/tests/services/` for severity and active-day scoping.

**Acceptance criteria**:
- Reconciliation status becomes critical under active-day fill parity absence.
- Report payload includes actionable file/count diagnostics.
- Inactive-bot and historical-day behavior remains unchanged.

**Do not**:
- Do not apply critical severity to inactive bots or historical windows.

---

### [P1-STRAT-20260228-3] Accelerate derisk unwind by tightening derisk spread `done (2026-02-28)`

**Why it matters**: Soft-pause is dominated by `base_pct_above_max` and `derisk_only`; faster inventory unwind should restore two-sided quoting sooner.

**What exists now**:
- `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml` has `derisk_spread_pct: 0.0002`.
- Intraday evidence shows persistent inventory-pressure reasons and elevated soft-pause.

**Design decision (pre-answered)**: Change only derisk spread this cycle (single config group), with explicit rollback guardrails.

**Implementation steps**:
1. Update `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: `derisk_spread_pct: 0.0001`.
2. Run paper for 3 days with no other spread/sizing/risk parameter changes.
3. Compare soft-pause, inventory-breach frequency, drawdown, and net PnL per fill against the current baseline.

**Acceptance criteria**:
- Soft-pause ratio drops below 30 percent over the sample window.
- `base_pct_above_max` trigger frequency decreases materially.
- Drawdown and net PnL/fill stay within existing guardrails.

**Do not**:
- Do not change spreads, sizing, or governor parameters in the same cycle.

---

### [P0-STRAT-20260228-4] Resolve bot1 inventory drift critical with consistent perp accounting basis `done (2026-02-28)`

**Why it matters**: Reconciliation currently reports `inventory_drift_critical` for bot1, which means inventory safety checks are not trustworthy at the exact point they are needed.

**What exists now**:
- `hbot/reports/reconciliation/latest.json` reports bot1 `inventory_drift_critical` with drift above critical threshold.
- Bot1 runs perp mode where gross base, net base, and directional exposure can diverge if compared with inconsistent formulas.

**Design decision (pre-answered)**: Use one canonical comparison basis for perp inventory drift across controller snapshots, reconciliation, and exchange snapshot service; do not loosen thresholds to hide mismatch.

**Implementation steps**:
1. Trace and document the exact drift formula currently used by reconciliation for perps.
2. Align reconciliation comparator to the same canonical basis used by controller risk outputs (gross vs net chosen explicitly and consistently).
3. Add deterministic unit tests in `hbot/tests/services/` for perp drift scenarios (flat, long, short, hedge) to prevent regression.
4. Re-run reconciliation and validate bot1 status with fresh artifacts.

**Acceptance criteria**:
- Bot1 no longer emits false `inventory_drift_critical` when data is internally consistent.
- True inventory mismatches still trigger warning/critical at existing thresholds.
- No threshold value is increased as part of this fix.

**Do not**:
- Do not mute or downgrade critical drift findings to force green status.

---

### [P0-STRAT-20260228-5] Trigger protective execution intent when reconciliation is critical `done (2026-02-28)`

**Why it matters**: A critical reconciliation state can coexist with active quoting, creating blind risk when accounting or event parity is broken.

**What exists now**:
- Reconciliation writes `reports/reconciliation/latest.json` and webhook alerts, but does not force a trading safety action.
- Controller can continue quoting while reconciliation is critical.

**Design decision (pre-answered)**: Add an explicit fail-safe bridge from reconciliation critical status to execution control intent for affected bot scope.

**Implementation steps**:
1. In reconciliation workflow, publish an execution intent when status is critical for an active bot.
2. In bridge/controller intent handling, map this intent to a deterministic protective action (at least soft pause; hard stop path configurable).
3. Add audit logs and tests to verify one-shot behavior per state transition (avoid intent spam).

**Acceptance criteria**:
- Critical reconciliation for active bot emits execution intent within one cycle.
- Bot transitions to protective state and stops normal quoting until status recovers.
- Transition and recovery are visible in minute/report artifacts.

**Do not**:
- Do not make this fail-safe optional in strict promotion mode.

---

### [P0-STRAT-20260228-6] Eliminate day2 event-store produced vs ingested lag failures `done (2026-02-28)`

**Why it matters**: Day2 gate currently fails on `delta_since_baseline_tolerance`, undermining trust in event completeness and release evidence.

**What exists now**:
- `hbot/reports/event_store/day2_gate_eval_latest.json` can report `go: false` from produced-vs-ingested delta.
- `source_compare` artifacts show non-zero lag on market data stream.

**Design decision (pre-answered)**: Treat produced-ingested lag as a first-class SLO with explicit diagnostics and automatic strict-cycle failure when breached.

**Implementation steps**:
1. Add per-stream lag diagnostics to latest event-store summary artifacts.
2. Implement deterministic catch-up/backfill handling for missed records before strict evaluation.
3. Enforce strict-cycle fail when lag exceeds tolerance, with actionable remediation in output.
4. Add regression tests for lag detection and recovery paths.

**Acceptance criteria**:
- Day2 gate passes with lag within configured tolerance over a full validation window.
- Strict cycle cannot pass while lag is above tolerance.

**Do not**:
- Do not bypass by inflating tolerance without root-cause correction.

---

### [P1-STRAT-20260228-7] Restore spread competitiveness cap observability in minute and reports `done (2026-02-28)`

**Why it matters**: Audit requires cap-hit rate, but current artifacts do not provide a reliable cap-hit metric.

**What exists now**:
- Controller/tick emitter has cap-related runtime values, but downstream minute/report outputs do not yield a stable cap-hit KPI.
- Strategy audit cannot verify whether cap is too tight, too loose, or inactive.

**Design decision (pre-answered)**: Emit explicit cap activation fields in minute logs and aggregate a daily cap-hit ratio in strategy reports.

**Implementation steps**:
1. Ensure minute schema includes `spread_competitiveness_cap_active` and `spread_competitiveness_cap_side_pct` end-to-end.
2. Update strategy summary scripts to compute cap-hit ratio over the audit window.
3. Add tests covering schema presence and aggregation math.

**Acceptance criteria**:
- Minute logs always include cap activation fields.
- `multi_day_summary` (or companion report) exposes cap-hit percentage.

**Do not**:
- Do not rely on proxy inference from spread-to-market ratios.

---

### [P1-STRAT-20260228-8] Add PnL governor diagnostic counters and activation reason telemetry `done (2026-02-28)`

**Why it matters**: Governor appears permanently inactive in current runs, but there is no clear telemetry on which gating condition blocks activation.

**What exists now**:
- `pnl_governor_active` and size multiplier are logged.
- No per-condition diagnostic counters are emitted for activation blockers.

**Design decision (pre-answered)**: Instrument governor early-return branches with explicit reason telemetry before tuning thresholds.

**Implementation steps**:
1. Add reason codes/counters for each governor non-activation branch.
2. Emit these diagnostics in processed data and minute logs.
3. Add report-level aggregation for governor block reasons.
4. Only after diagnostics, propose config tuning in a separate cycle if needed.

**Acceptance criteria**:
- For every tick, activation or non-activation reason is observable.
- Weekly report shows dominant governor block reasons.

**Do not**:
- Do not increase sizing thresholds without diagnostic evidence.

---

### [P1-STRAT-20260228-9] Validate paper execution realism against testnet micro-benchmark `done (2026-02-28)`

**Why it matters**: Sustained high maker ratios in paper can still overstate live performance without controlled testnet comparison.

**What exists now**:
- Paper fill model has realism knobs and defaults.
- No recurring, automated micro-benchmark that compares paper vs testnet execution quality deltas.

**Design decision (pre-answered)**: Add a repeatable low-risk testnet benchmark and compare slippage/fill/reject metrics to paper within strict thresholds.

**Implementation steps**:
1. Define a 24h micro-size testnet benchmark profile for bot1-equivalent settings.
2. Extend scorecard/parity scripts to compute paper-vs-testnet deltas for fill ratio, slippage, reject rate, cancel-before-fill.
3. Gate results with explicit pass/fail thresholds and artifact output.

**Acceptance criteria**:
- Benchmark artifacts are generated automatically.
- Paper-vs-testnet deltas are measurable and trendable across cycles.

**Do not**:
- Do not loosen parity thresholds solely to force pass.

---

### [P0-STRAT-20260228-10] Close kill-switch non-dry-run readiness gap with evidence `done (2026-02-28)`

**Why it matters**: Testnet readiness currently fails due to missing non-dry-run kill-switch evidence, leaving a critical safety control unproven.

**What exists now**:
- `hbot/reports/ops/testnet_readiness_latest.json` reports failure on kill-switch non-dry-run checks.
- `hbot/reports/kill_switch/latest.json` still reflects dry-run style evidence.

**Design decision (pre-answered)**: Produce explicit non-dry-run test evidence in controlled environment and wire it into readiness gate acceptance.

**Implementation steps**:
1. Run controlled non-dry-run kill-switch execution in testnet scope.
2. Capture and persist evidence artifact showing intent reception and cancel behavior.
3. Re-run readiness gate and ensure it passes with fresh evidence.

**Acceptance criteria**:
- Readiness gate no longer fails on kill-switch non-dry-run checks.
- Evidence is fresh, machine-readable, and linked in report outputs.

**Do not**:
- Do not run this on production credentials or live capital.

---

### [P2-STRAT-20260228-11] Make audit window reconstruction robust to minute log rotation `done (2026-02-28)`

**Why it matters**: Minute data splitting between `minute.csv` and rotated legacy files can produce incomplete baselines if consumers read only one file.

**What exists now**:
- Rotation creates `minute.legacy_*.csv` and a fresh `minute.csv`.
- Ad hoc analysis must manually merge files to reconstruct full intraday window.

**Design decision (pre-answered)**: Add deterministic minute-log discovery and merge behavior in analysis scripts.

**Implementation steps**:
1. Update strategy analysis scripts to load both active and rotated minute files for the target day/window.
2. Add duplicate-row handling and timestamp ordering guarantees.
3. Add tests for rotated/non-rotated scenarios.

**Acceptance criteria**:
- Audit and scorecard scripts produce identical metrics whether rotation occurred or not.

**Do not**:
- Do not require manual file merging for standard audit flows.

---

### [P1-STRAT-20260228-12] Ensure bot_fill event payload carries correct realized PnL semantics `done (2026-02-28)`

**Why it matters**: Event-store `bot_fill` payload currently trends toward zero realized PnL values, reducing value of event-driven finance validation.

**What exists now**:
- `fills.csv` includes non-zero realized PnL over the same period.
- `events_*.jsonl` bot_fill payloads often show `realized_pnl_quote: 0.0`.

**Design decision (pre-answered)**: Align event payload semantics with fill accounting output, documenting when realized PnL is expected to be zero vs non-zero.

**Implementation steps**:
1. Trace realized PnL field population path from paper portfolio to telemetry emitter.
2. Fix mapping or timing issues so event payload matches intended semantics.
3. Add unit tests comparing telemetry payload values to fills artifact for sampled scenarios.
4. Document semantics in service interface docs.

**Acceptance criteria**:
- Event payload realized PnL behavior is consistent with documented accounting semantics.
- Reconciliation/parity consumers can rely on event-driven PnL fields.

**Do not**:
- Do not alter accounting math to fit telemetry output.

---

## BUILD_SPEC — Semi-Pro Paper Exchange Service (exchange mirror) `in-progress (2026-03-01)`

**Objective**: Extract paper execution from controller-local state into a dedicated service that behaves like an exchange adapter while consuming the same real market data connector feed used by each bot.

**Assessment verdict**:
- **Internal readiness (paper-only desk)**: Amber (usable with safeguards).
- **Exchange-mirror readiness**: Red until command contracts, durable state, and parity gates are complete.

**Architecture baseline (target)**:
- **Data layer**: `hb.market_data.v1` remains source of truth from bot connector path (Bitget/other real exchange connectors).
- **Strategy layer**: controller emits intents/commands only, no direct paper accounting mutation.
- **Execution simulation layer**: new `paper_exchange_service` owns order lifecycle, matching, fills, balances, and funding simulation.
- **Risk layer**: existing risk services keep veto/kill authority before commands reach paper exchange.
- **Ops layer**: heartbeat + SLO + parity reports become promotion gates.

**Impact analysis**:
- **Controller impact**: medium-high (replace in-process calls with command adapter, shadow run, then cutover).
- **Contracts impact**: high (new stream names and schema contracts must stay backward compatible).
- **Ops impact**: medium (new service and dashboards, but existing Redis/Prom stack can be reused).
- **Risk of regression**: high without replay/parity tests; reduced to medium after phase gates below.

### [P0-PAPER-SVC-20260301-1] Define v1 command/event/heartbeat contracts and service baseline `in-progress (2026-03-01)`

**Why it matters**: Service extraction is unsafe without explicit stream contracts and a standalone process boundary.

**What exists now**:
- `paper_engine_v2` logic is mostly in-process and coupled to controller flow.
- No dedicated paper-exchange command stream contract yet.

**Design decision (pre-answered)**: Establish contract-first extraction (`command -> result -> heartbeat`) before full matching migration.

**Implementation steps**:
1. Add stream constants for paper-exchange command/event/heartbeat.
2. Add schema models in `event_schemas.py` for command/result/heartbeat.
3. Create `services/paper_exchange_service/main.py` baseline process:
   - consume market snapshots from `hb.market_data.v1`,
   - enforce connector allowlist for real exchange feed provenance,
   - emit heartbeat and command result events.
4. Add unit tests for schema and baseline behavior.

**Acceptance criteria**:
- Service runs independently and publishes heartbeat.
- Command schema validation works and unsupported actions are explicitly rejected.
- Unit tests cover contract roundtrip and baseline processing.

**Do not**:
- Do not route live orders here.
- Do not fake market data inside paper exchange.

---

### [P0-PAPER-SVC-20260301-2] Enforce exchange-data provenance and freshness contract `open`

**Why it matters**: Exchange-mirroring claims are invalid if market data can silently come from synthetic or stale sources.

**What exists now**:
- Market snapshots carry connector identity, but provenance fields are not strict enough for hard gating.

**Design decision (pre-answered)**: Add explicit provenance metadata and stale-data hard gate in paper exchange command path.

**Implementation steps**:
1. Extend market snapshot payload metadata with provenance (`origin`, connector, sequence/reference timestamp).
2. In `paper_exchange_service`, reject command processing when required pair feed is stale.
3. Emit structured rejection reasons (`market_data_stale`, `connector_mismatch`, `missing_pair_feed`).
4. Add tests for freshness boundary and connector mismatch behavior.

**Acceptance criteria**:
- Every processed command references fresh market data from allowed connector.
- Rejection reasons are observable in events and dashboards.

**Do not**:
- Do not silently fallback to last-known data beyond stale threshold.

---

### [P0-PAPER-SVC-20260301-3] Add controller adapter (shadow mode first) `open`

**Why it matters**: Direct in-process paper calls prevent service isolation and realistic exchange-like behavior.

**What exists now**:
- Controller still owns paper accounting path directly.

**Design decision (pre-answered)**: Introduce adapter with dual-write shadow mode before cutover.

**Implementation steps**:
1. Add controller-side adapter that emits `paper_exchange_command` events.
2. Keep current `paper_engine_v2` execution as source-of-truth during shadow phase.
3. Record parity diffs (fills, balances, position, realized/unrealized PnL, funding).
4. Add canary toggle per bot (`PAPER_EXCHANGE_MODE=disabled|shadow|active`).

**Acceptance criteria**:
- Shadow mode runs with parity report artifacts per bot/day.
- No behavior change to trading decisions while in shadow mode.

**Do not**:
- Do not switch bot1 directly to active mode before parity thresholds pass.

---

### [P0-PAPER-SVC-20260301-4] Implement deterministic matching and order-state engine `open`

**Why it matters**: Exchange-mirror credibility depends on realistic order lifecycle and deterministic replay.

**What exists now**:
- Fill models exist, but service-level command/order lifecycle contract is incomplete.

**Design decision (pre-answered)**: Build deterministic core first; advanced microstructure realism can layer later.

**Implementation steps**:
1. Implement in-service order states (`accepted`, `working`, `partially_filled`, `filled`, `cancelled`, `rejected`, `expired`).
2. Support `limit`, `market`, `post_only`, `reduce_only`, IOC/FOK policy behavior.
3. Add deterministic fill clock and sequencing by event timestamp + stream id.
4. Add unit tests and replay tests for edge cases (crossed quotes, cancel-race, partial fills).

**Acceptance criteria**:
- Same replay input always yields same fills and states.
- Order lifecycle is auditable end-to-end with reason codes.

**Do not**:
- Do not introduce nondeterministic randomness without seeded control and test hooks.

---

### [P0-PAPER-SVC-20260301-5] Add durable persistence and crash recovery `open`

**Why it matters**: Exchange-like service cannot lose order/fill state on restart.

**What exists now**:
- Core state durability is partial and still tied to controller lifecycle assumptions.

**Design decision (pre-answered)**: Snapshot + append-log recovery with idempotent reprocessing.

**Implementation steps**:
1. Persist order/fill/account state snapshots on interval and on shutdown.
2. Maintain append-only journal for commands and execution events.
3. Implement restart recovery with checksum/version guard.
4. Add restart simulation tests and idempotency tests.

**Acceptance criteria**:
- Service restart restores consistent state and resumes processing.
- No duplicate fills on replay/recovery.

**Do not**:
- Do not rely solely on in-memory maps for authoritative state.

---

### [P1-PAPER-SVC-20260301-6] Align margin, funding, and fee semantics with current desk accounting `open`

**Why it matters**: PnL and risk drift undermines trust in paper-vs-live promotion gates.

**What exists now**:
- Portfolio/funding behavior was improved, but service extraction can reintroduce drift if semantics diverge.

**Design decision (pre-answered)**: Keep accounting semantics contract-driven and parity-tested against current portfolio outputs.

**Implementation steps**:
1. Define explicit fee/funding/margin contract fields in execution events.
2. Port or wrap current paper accounting logic into service-owned module boundary.
3. Add parity fixtures for maker/taker, funding positive/negative, leverage and margin modes.
4. Add regression tests against known vectors from existing `paper_engine_v2` tests.

**Acceptance criteria**:
- Accounting parity meets tolerance thresholds in replay suite.
- Funding sign and margin reserve behavior are consistent and documented.

**Do not**:
- Do not change risk policy thresholds to hide accounting drift.

---

### [P1-PAPER-SVC-20260301-7] Build parity and replay gate for promotion cycle `open`

**Why it matters**: Service cutover needs objective acceptance gates, not subjective observation.

**What exists now**:
- Some soak and readiness scripts exist, but no dedicated paper-engine service parity gate yet.

**Design decision (pre-answered)**: Add replay and shadow-parity reports as mandatory release checks.

**Implementation steps**:
1. Create script to compare legacy vs service outputs over same market/intent stream.
2. Produce machine-readable artifact (`reports/verification/paper_exchange_parity_latest.json`).
3. Integrate pass/fail thresholds into release scripts.
4. Add tests covering artifact schema and gate decision logic.

**Acceptance criteria**:
- Strict promotion cycle fails on parity regression.
- Artifacts show fill, slippage, position, and equity drift metrics.

**Do not**:
- Do not bypass parity gate with blanket exemptions.

---

### [P1-PAPER-SVC-20260301-8] Add observability and SLO for service reliability `open`

**Why it matters**: Exchange mirror service must be diagnosable under degraded feed, lag, and redis incidents.

**What exists now**:
- Existing dashboards and SLO scripts focus on controller-centric flow.

**Design decision (pre-answered)**: Add service-level metrics and alerts before active cutover.

**Implementation steps**:
1. Export metrics: command latency, rejection reason counts, snapshot freshness, replay lag, restart count.
2. Add Grafana panels and alert rules for stale feed and high reject rate.
3. Extend reliability SLO script with paper-exchange heartbeat and freshness checks.
4. Add tests for metric/report builders where feasible.

**Acceptance criteria**:
- New SLO checks pass in soak.
- Alerting catches stale feed and command backlog conditions.

**Do not**:
- Do not treat missing heartbeat as non-critical.

---

### [P1-PAPER-SVC-20260301-9] Compose integration and controlled rollout plan `open`

**Why it matters**: Safe rollout requires explicit deployment modes and rollback path.

**What exists now**:
- No dedicated compose service role for paper exchange yet.

**Design decision (pre-answered)**: Deploy service behind feature flags with shadow-first canary.

**Implementation steps**:
1. Add service block to compose with healthcheck and required env vars.
2. Introduce per-bot mode flags for disabled/shadow/active.
3. Add rollback procedure to runbooks and preflight checks.
4. Run 24h canary (bot3 or bot4), then bot1 after parity pass.

**Acceptance criteria**:
- Rollout can switch between modes without downtime to other services.
- Rollback returns to legacy path within one restart cycle.

**Do not**:
- Do not enable active mode on all bots simultaneously on first rollout.

---

### [P2-PAPER-SVC-20260301-10] NautilusTrader selective reuse and license boundary `open`

**Why it matters**: Reusing proven components can improve robustness, but license and boundary handling must be explicit.

**What exists now**:
- Team has authorization to use open source components.
- No tracked decision log for what is copied, wrapped, or reimplemented.

**Design decision (pre-answered)**: Use selective, contract-compatible reuse only for modules that improve determinism and exchange realism; keep integration boundary and attribution auditable.

**Implementation steps**:
1. Create module-level decision matrix (`adopt`, `adapt`, `reimplement`) with rationale.
2. Add attribution/license documentation and compliance notes in repo docs.
3. Port components behind local interface adapters, avoiding broad framework lock-in.
4. Add regression tests proving behavior parity after each adopted component.

**Acceptance criteria**:
- Every reused component has provenance, boundary, and tests.
- No undocumented direct dependency on external framework internals.

**Do not**:
- Do not bulk-copy large framework sections without contract mapping and tests.

---

### [P0-PAPER-SVC-20260301-11] Preserve Hummingbot executor/runtime compatibility during extraction `open`

**Why it matters**: Current paper mode works because bridge patches strategy and connector behavior expected by Hummingbot executors. Removing this without equivalent adapter will break desk trading flow.

**What exists now**:
- `hb_bridge` patches strategy `buy/sell/cancel` and maps desk events back into HB events.
- Connector reads (`get_balance`, `get_available_balance`, `get_position`, `ready`) are overridden in paper mode.
- Executor fallback paths rely on these behaviors for in-flight order visibility.

**Design decision (pre-answered)**: Keep an explicit compatibility adapter layer until service-native interfaces fully replace monkey patches.

**Implementation steps**:
1. Define a compatibility contract for order lifecycle callbacks expected by Hummingbot executors.
2. Implement adapter that converts `paper_exchange_event` stream into HB `OrderFilled/OrderCanceled/OrderRejected` semantics.
3. Ensure in-flight order tracker parity (order-id mapping, partial fills, cancel/expire states).
4. Add integration tests that run controller + adapter + simulated service events.

**Acceptance criteria**:
- Existing executor flows continue to operate in paper mode with service backend.
- No regression in fills ingestion, minute metrics, and event-store telemetry.

**Do not**:
- Do not remove compatibility patches before adapter parity is proven.

---

### [P0-PAPER-SVC-20260301-12] Expand market data contract beyond mid-price for exchange-like matching `open`

**Why it matters**: A single mid-price snapshot is insufficient to mirror exchange behavior for spread-sensitive market making.

**What exists now**:
- `market_snapshot` contains summary metrics but lacks explicit top-of-book, trade ticks, and mark/funding timing fields needed for realistic matching.

**Design decision (pre-answered)**: Introduce a minimal exchange-mirroring market schema (L1 first, optional L2 depth extension) and use it as the sole matching input.

**Implementation steps**:
1. Add contract fields/events for `best_bid`, `best_ask`, `last_trade`, `mark_price`, `funding_rate`, and source timestamps.
2. Add sequence/clock fields for deterministic ordering (`exchange_ts_ms`, `ingest_ts_ms`, monotonic sequence).
3. Update service matcher to consume these fields instead of synthetic mid-only approximations.
4. Add replay tests validating spread crossing and post-only behavior from L1 data.

**Acceptance criteria**:
- Matching decisions are explainable from recorded exchange-like input events.
- Replay from recorded stream reproduces identical fills.

**Do not**:
- Do not infer book side prices from mid-price only in active mode.

---

### [P0-PAPER-SVC-20260301-13] Guarantee command idempotency and Redis pending-entry recovery `open`

**Why it matters**: Redis Streams are at-least-once; without pending recovery and idempotency, crashes can stall or duplicate order actions.

**What exists now**:
- Baseline consumer reads new entries and ACKs after processing.
- No explicit claim/replay workflow for pending entries after consumer crash/restart.

**Design decision (pre-answered)**: Add command journal + idempotency keys + pending-claim loop as mandatory reliability baseline.

**Implementation steps**:
1. Add `command_event_id` idempotency tracking with persistent dedup storage.
2. Implement pending-entries reclaim flow (`XPENDING/XAUTOCLAIM` equivalent) with inactivity timeout.
3. Make command processing idempotent for submit/cancel/cancel_all/sync.
4. Add crash-restart tests proving no lost commands and no duplicate fills.

**Acceptance criteria**:
- Restart resumes processing pending commands automatically.
- Replayed command stream yields exactly one terminal outcome per command id.

**Do not**:
- Do not depend on best-effort ACK ordering for correctness.

---

### [P0-PAPER-SVC-20260301-14] Add startup sync handshake and hard-fail invariants `open`

**Why it matters**: Desk startup currently relies on in-process assumptions; service extraction needs explicit synchronization boundaries to avoid silent drift.

**What exists now**:
- Baseline supports a `sync_state` command but has no strict startup gate contract.

**Design decision (pre-answered)**: Require startup handshake (`snapshot_loaded -> sync_ok`) before controller is allowed to quote in active mode.

**Implementation steps**:
1. Define startup handshake events and timeout policy.
2. Block order command emission until service confirms sync completion for instance/pair.
3. On sync failure/timeout, force `HARD_STOP` with explicit audit/dead-letter reason.
4. Add tests for boot success, timeout, partial state, and mismatched instance routing.

**Acceptance criteria**:
- Active mode cannot trade before successful sync handshake.
- Startup failures are explicit, auditable, and recoverable via controlled restart.

**Do not**:
- Do not silently continue in active mode after sync timeout.

---

### [P1-PAPER-SVC-20260301-15] Enforce bot isolation and multi-instance namespace safety `open`

**Why it matters**: Prior incidents showed cross-bot state contamination risks; service extraction must guarantee strict per-bot segregation.

**What exists now**:
- Instance/variant separation improved in config, but service-level namespace contract is not yet formalized.

**Design decision (pre-answered)**: Scope all command/state/order keys by `(instance_name, variant, connector_name, trading_pair)` and verify with isolation tests.

**Implementation steps**:
1. Define canonical namespace key format in contracts and persistence.
2. Ensure command routing rejects cross-instance writes.
3. Add multi-bot concurrency tests (`bot1/bot3/bot4`) with mixed symbols and simultaneous commands.
4. Add ops check that detects namespace collisions in reports.

**Acceptance criteria**:
- No state bleed across bots under parallel workload.
- Isolation checks are part of reliability and promotion artifacts.

**Do not**:
- Do not share mutable order/account state across bot namespaces.

---

### [P1-PAPER-SVC-20260301-16] Define active-mode failure policy and rollback semantics `open`

**Why it matters**: If paper exchange service degrades mid-session, behavior must be deterministic and safe for desk operations.

**What exists now**:
- Rollout strategy exists, but runtime failover policy is not yet explicit.

**Design decision (pre-answered)**: Default to safety-first (pause/stop), with optional controlled fallback only when parity-safe.

**Implementation steps**:
1. Define failure matrix for service down, stale feed, command backlog, and recovery loops.
2. Map each failure class to controller action (`soft_pause`, `hard_stop`, or controlled fallback mode).
3. Emit standardized audit reasons for each transition.
4. Add scenario tests and runbook procedures for each failure mode.

**Acceptance criteria**:
- Failure behavior is deterministic and documented.
- Recovery path is validated in soak and incident drills.

**Do not**:
- Do not silently revert to live connector execution path from paper mode.

---

### [P1-PAPER-SVC-20260301-17] Wire paper-exchange checks into service interfaces, preflight, and strict promotion cycle `open`

**Why it matters**: Desk confidence requires paper-exchange behavior to be visible in the same gating framework that controls go/no-go decisions.

**What exists now**:
- Existing docs/gates focus on current HB bridge + in-process paper engine.

**Design decision (pre-answered)**: Treat paper-exchange service readiness as first-class in docs and release automation.

**Implementation steps**:
1. Update `docs/techspec/service_interfaces.md` with paper-exchange responsibilities and stream contracts.
2. Extend preflight checks to validate paper-exchange config, connector allowlist, and stream wiring.
3. Add strict-cycle gate checks for heartbeat freshness, command lag, and parity artifact freshness.
4. Add tests for new gate logic and failure diagnostics.

**Acceptance criteria**:
- Promotion cycle fails when paper-exchange service is unhealthy or parity stale.
- Operators can trace failures from gate output to concrete remediation steps.

**Do not**:
- Do not mark paper-exchange checks as informational only once active mode is enabled.

---

### [P0-PAPER-SVC-20260301-18] Build automated threshold evaluator for strict cycle (single source of truth) `open`

**Why it matters**: Numeric thresholds are only reliable if enforced by one deterministic evaluator used by CI and promotion gates.

**What exists now**:
- Thresholds are documented in backlog, but enforcement logic is not yet centralized.

**Design decision (pre-answered)**: Add one evaluator script that ingests artifacts/metrics and emits explicit GO/NO-GO with failed-threshold reasons.

**Implementation steps**:
1. Implement `scripts/release/check_paper_exchange_thresholds.py` with machine-readable output.
2. Consume parity/SLO/preflight artifacts and evaluate all paper-service threshold clauses.
3. Wire script into `run_promotion_gates.py` and `run_strict_promotion_cycle.py`.
4. Add tests for pass, single-failure, and multi-failure cases.

**Acceptance criteria**:
- Strict cycle fails on any breached paper-exchange threshold.
- Failure output names exact metric, threshold, observed value, and source artifact.

**Do not**:
- Do not duplicate threshold logic across multiple scripts.

---

### [P1-PAPER-SVC-20260301-19] Add load/backpressure validation for desk-scale concurrency `open`

**Why it matters**: Exchange-like behavior is meaningless if service degrades under realistic multi-bot command and market-event rates.

**What exists now**:
- Functional tests exist, but no formal throughput/backpressure qualification for service mode.

**Design decision (pre-answered)**: Define desk-scale load profile and require latency/queue thresholds before active rollout.

**Implementation steps**:
1. Create reproducible load harness (market events + commands + cancels) for bot1/bot3/bot4 profile.
2. Measure command latency, queue depth growth, and event lag under sustained load.
3. Add fail-fast alerts when queue depth or latency exceeds budget.
4. Add release artifact with percentile latencies and backlog behavior.

**Acceptance criteria**:
- Service remains within latency and queue budgets at target desk load.
- No unbounded queue growth in 2h sustained stress run.

**Do not**:
- Do not approve active mode based only on low-load test results.

---

### [P1-PAPER-SVC-20260301-20] Harden command-channel security and operator safety controls `open`

**Why it matters**: A command stream with weak controls can generate unauthorized simulated orders, invalidating test evidence and desk safety.

**What exists now**:
- Command contracts exist, but explicit command-auth/control policy and audit guarantees are not fully specified.

**Design decision (pre-answered)**: Require producer allowlist + signed/traceable command metadata + explicit operator controls.

**Implementation steps**:
1. Define approved command producers and enforce source validation in service.
2. Add required metadata fields (`operator`, `reason`, `change_ticket`, `trace_id`) for privileged commands.
3. Emit audit events for accept/reject with actor attribution.
4. Add tests for unauthorized producer rejection and missing-metadata rejection.

**Acceptance criteria**:
- Unauthorized producer commands are rejected deterministically.
- All privileged commands are traceable to actor/reason in audit stream.

**Do not**:
- Do not allow wildcard/implicit producer trust in active mode.

---

### [P1-PAPER-SVC-20260301-21] Validate backup/restore and disaster recovery for service state `open`

**Why it matters**: Exchange-mirror service must survive host loss or volume corruption without losing desk continuity.

**What exists now**:
- Restart recovery is planned, but full backup/restore drills are not yet a formal gate.

**Design decision (pre-answered)**: Add periodic backup verification and restore drills as a release prerequisite.

**Implementation steps**:
1. Define backup scope (orders, ledger, journal, snapshots, config version markers).
2. Implement restore procedure into clean environment and replay verification.
3. Run recurring DR drill and produce evidence artifact.
4. Add strict-cycle check for backup freshness and last successful restore drill.

**Acceptance criteria**:
- Restore reproduces consistent state and resumes processing with no duplicate side effects.
- DR evidence is fresh and attached to readiness artifacts.

**Do not**:
- Do not treat untested backups as valid recovery guarantees.

---

### Quantitative Go/No-Go Thresholds (mandatory)

**Hard rule**: a backlog item is **GO** only when **all** thresholds below pass in CI/soak evidence for the required window. Any single breach is **NO-GO**.

**Window defaults**:
- Unit/integration checks: current CI run.
- Soak/SLO checks: latest continuous 24h window unless explicitly stated otherwise.
- Artifact freshness for gate decisions: <= 20 minutes.

1. **[P0-PAPER-SVC-20260301-1] Contracts + baseline service**
   - `schema_validation_error_rate = 0.00%` over >= 10,000 replayed events.
   - Heartbeat cadence: `p99_gap_ms <= 5000` and `max_gap_ms <= 15000` over 30m soak.
   - Unsupported command handling: `reject_rate = 100.00%` with `reason=not_implemented_yet`.
   - Contract tests in `tests/services/test_event_schemas.py` and `tests/services/test_paper_exchange_service.py`: `pass_rate = 100.00%`.

2. **[P0-PAPER-SVC-20260301-2] Provenance + freshness enforcement**
   - Commands processed with stale market data: `0`.
   - Processed commands with allowlisted connector provenance: `100.00%`.
   - Processed commands with complete provenance fields (`origin`, connector, exchange timestamp/sequence): `100.00%`.
   - Rejected stale/mismatch command decision latency: `p95 <= 200 ms`.

3. **[P0-PAPER-SVC-20260301-3] Controller adapter shadow mode**
   - Shadow parity artifact generated for each enabled bot each day: `100.00%`.
   - `fill_count_delta_pct <= 1.00%`.
   - `end_equity_delta_pct <= 0.25%`.
   - `control_state_divergence_count (soft_pause/hard_stop/kill_switch) = 0`.

4. **[P0-PAPER-SVC-20260301-4] Deterministic matching**
   - Deterministic replay hash equality on identical input: `20/20 identical runs`.
   - Terminal order-state coverage (`accepted/working/partially_filled/filled/cancelled/rejected/expired`): `100.00%`.
   - Post-only violation count: `0`.
   - Cancel-race misclassification rate: `<= 0.10%`.

5. **[P0-PAPER-SVC-20260301-5] Persistence + recovery**
   - In 50 crash-restart cycles: `lost_commands = 0`, `duplicate_fills = 0`.
   - Recovery to healthy heartbeat after restart: `<= 30 s`.
   - Pending stream entries older than 60s after recovery stabilization: `0`.

6. **[P1-PAPER-SVC-20260301-6] Accounting parity (fees/funding/margin)**
   - Per-fill fee absolute error: `<= max(1e-8 quote, 0.01% of notional)`.
   - Cumulative realized PnL drift vs reference run: `<= 0.10% of equity`.
   - Funding sign mismatches: `0`.
   - Margin reserve drift vs reference run: `<= 0.10% of equity`.

7. **[P1-PAPER-SVC-20260301-7] Promotion parity gate**
   - Evaluation window size: `>= 24h` and `>= 5000 command events`.
   - Fill ratio delta: `<= 2.00 percentage points`.
   - Reject ratio delta: `<= 1.00 percentage point`.
   - Fill-price delta: `p95 <= 3.0 bps`, `p99 <= 6.0 bps`.
   - End-of-window equity delta: `<= 0.30%`.

8. **[P1-PAPER-SVC-20260301-8] Reliability SLO**
   - Heartbeat availability (`age <= 15s`): `>= 99.90%`.
   - Command processing success (excluding intentional policy rejects): `>= 99.50%`.
   - Command latency: `p95 <= 250 ms`, `p99 <= 500 ms`.
   - Critical dead-letter reasons per hour: `0`.

9. **[P1-PAPER-SVC-20260301-9] Rollout + rollback**
   - Canary run duration before next promotion step: `>= 24h`.
   - Canary critical alerts: `0`.
   - Rollback drill: `RTO <= 5 min`, `RPO (lost commands) = 0`.
   - Active-mode rollout concurrency during first stage: `<= 1 bot` until 72h stability pass.

10. **[P2-PAPER-SVC-20260301-10] Nautilus selective reuse**
    - Reused module provenance documentation coverage: `100.00%`.
    - License/compliance check failures: `0`.
    - Behavior parity tests for each adopted/ported module: `pass_rate = 100.00%`.
    - Undocumented direct dependency on external framework internals: `0`.

11. **[P0-PAPER-SVC-20260301-11] Hummingbot runtime compatibility**
    - Adapter integration tests for executor lifecycle paths: `pass_rate = 100.00%`.
    - HB event count deltas by type (fill/cancel/reject) vs legacy path: `<= 1.00%`.
    - In-flight order lookup miss rate: `<= 0.10%`.
    - Runtime adapter exceptions in 24h shadow soak: `0`.

12. **[P0-PAPER-SVC-20260301-12] Exchange-like market data contract**
    - Snapshots with non-null required L1 fields (`best_bid`, `best_ask`, sequence/timestamps): `>= 99.90%`.
    - Out-of-order sequence handling error rate: `<= 0.01%`.
    - Matching decisions with traceable source input fields: `100.00%`.
    - Active-mode commands executed with mid-only fallback: `0`.

13. **[P0-PAPER-SVC-20260301-13] Idempotency + pending recovery**
    - Duplicate command side effects in forced redelivery tests (>=100 scenarios): `0`.
    - Pending reclaim time after consumer restart: `p95 <= 30 s`.
    - Unacked entries older than 120s in steady state: `0`.
    - Duplicate command detection by idempotency key: `100.00%`.

14. **[P0-PAPER-SVC-20260301-14] Startup sync handshake**
    - Quote-before-sync violations: `0`.
    - Sync handshake completion: `p95 <= 20 s`, `max <= 30 s` (healthy startup).
    - Sync timeout to hard-stop/audit publication: `<= 5 s`.
    - Startup sync success over 100 restart trials: `>= 99.00%`.

15. **[P1-PAPER-SVC-20260301-15] Multi-bot isolation**
    - Cross-instance state mutation/access violations: `0`.
    - Namespace key collisions in 72h multi-bot soak: `0`.
    - Command/event routing correctness to target instance in test matrix: `100.00%`.

16. **[P1-PAPER-SVC-20260301-16] Active-mode failure policy**
    - Service-down detection delay: `<= 5 s`.
    - Transition to safety state (`soft_pause` or `hard_stop`) after detection: `<= 10 s`.
    - Silent fallback to live connector execution from paper mode: `0`.
    - Mean recovery time to controlled running state (with healthy dependencies): `<= 10 min`.

17. **[P1-PAPER-SVC-20260301-17] Gates + preflight + strict cycle wiring**
    - Strict promotion cycle includes paper-exchange checks and fails on any threshold breach: `100.00%`.
    - Preflight non-zero exit when service missing or heartbeat stale > 15s: `100.00%`.
    - Parity/SLO artifact freshness at evaluation time: `<= 20 min`.
    - New gate-path tests (success and failure paths): `pass_rate = 100.00%`.

18. **[P0-PAPER-SVC-20260301-18] Automated threshold evaluator**
    - Evaluator output determinism on same artifacts (>=20 reruns): `100.00% identical`.
    - Threshold clause coverage in evaluator vs backlog matrix: `100.00%`.
    - False-pass rate in mutation tests (intentional threshold breaches): `0`.
    - Strict-cycle invocation success with evaluator integrated: `100.00%`.

19. **[P1-PAPER-SVC-20260301-19] Load/backpressure qualification**
    - Sustained command throughput target: `>= 50 cmds/s` for 2h with no critical failures.
    - Command latency under load: `p95 <= 500 ms`, `p99 <= 1000 ms`.
    - Stream backlog growth rate during steady state: `<= 1.0% per 10 min` after warmup.
    - OOM/restart count during stress window: `0`.

20. **[P1-PAPER-SVC-20260301-20] Command-channel security**
    - Unauthorized producer acceptance rate: `0.00%`.
    - Privileged commands with complete attribution metadata: `100.00%`.
    - Security-policy test suite (allowlist + metadata + audit): `pass_rate = 100.00%`.
    - Missing-audit event rate for accepted privileged commands: `0.00%`.

21. **[P1-PAPER-SVC-20260301-21] Backup/restore and DR**
    - Successful restore drills from latest backup (rolling 30 days): `>= 2` successful runs.
    - Data integrity mismatch after restore/replay: `0`.
    - Recovery time objective for full restore to healthy heartbeat: `<= 15 min`.
    - Backup artifact freshness at gate time: `<= 24 h`.

---

## Done

| Item | Description | Commit | Date |
|---|---|---|---|
| EXEC-E1 | Kill switch retry (3 attempts with backoff) on cancel failures | — | 2026-02-27 |
| EXEC-E3 | Time drift check: real exchange server time (Bitget/Binance) replaces no-op | — | 2026-02-27 |
| EXEC-E4 | Live-mode guard: framework paper patches skip when `BOT_MODE=live` | — | 2026-02-27 |
| EXEC-E5 | Startup sync exhaustion → HARD_STOP (was silent proceed) | — | 2026-02-27 |
| EXEC-E6 | `did_fail_order` no longer resets cancel streak on unrelated failures | — | 2026-02-27 |
| EXEC-E8 | Position recon failures → WARNING + consecutive counter escalation | — | 2026-02-27 |
| EXEC-E9 | Reconnect cooldown: `reconnect_cooldown_s` suppresses quoting after WS reconnect | — | 2026-02-27 |
| EXEC-E13 | `with_retry` backoff now includes random jitter (anti-thundering-herd) | — | 2026-02-27 |
| EXEC-E15 | DailyStateStore: atomic file writes via `tempfile` + `os.replace` | — | 2026-02-27 |
| BUG-C1 | Redis connection leak per fill → lazy singleton `_telemetry_redis` in `epp_v2_4.py` | — | 2026-02-27 |
| BUG-C2 | Silent `except Exception: pass` → add `logger.debug` to all swallowed exceptions | — | 2026-02-27 |
| BUG-C3 | Float arithmetic in `adverse_widen_spreads` → pure Decimal computation | — | 2026-02-27 |
| BUG-R1 | EWMA variance order-of-operations: deviation now computed from *pre-update* EWMA | — | 2026-02-27 |
| BUG-R2 | Brittle `__code__` inspection for position dispatch → `try/except TypeError` | — | 2026-02-27 |
| BUG-M2 | Duplicated locked-base scanning → extracted `_compute_total_base_with_locked()` | — | 2026-02-27 |
| BUG-C6 | `hb_bridge.py` Redis per paper fill → reuse `BridgeState.get_redis()` | — | 2026-02-27 |
| INFRA-2 | compose_up.sh wrapper + preflight_startup.py | — | 2026-02-27 |
| INFRA-1 | Watchdog STATE_FILE to persistent /data/ path | — | 2026-02-27 |
| INFRA-3 | risk-service reports volume `:ro` → writable overlay | — | 2026-02-27 |
| DEBT-H2 | hb_bridge module-level state → BridgeState class | — | 2026-02-27 |
| DEBT-M2 | Delete dead controller stubs (paper_engine.py, binance_perpetual_constants, directional_trading/, market_making/) | — | 2026-02-27 |
| DEBT-L1 | Fix service_interfaces.md path references | — | 2026-02-27 |
| DEBT-L2 | Remove duplicate controllers/market_making mount from compose | — | 2026-02-27 |
| DEBT-L3 | Bake python-telegram-bot into control-plane image (no runtime pip install) | — | 2026-02-27 |

| Item | Description | Commit | Date |
|---|---|---|---|
| QUAL-5 | `_cancel_per_min` thread-safe assignment pattern | — | 2026-02-27 |
| QUAL-4 | Order book staleness check: `max_clock_skew_s` tolerance added | — | 2026-02-27 |
| QUAL-3 | `ProcessedState` TypedDict with 66 typed fields | — | 2026-02-27 |
| QUAL-2 | `TickContext` dataclass defined in `state_types.py` | — | 2026-02-27 |
| QUAL-1 | State dataclasses (`PositionState`, `DailyCounters`, `FillEdgeState`, `FeeState`) defined | — | 2026-02-27 |
| DEBT-1 | `epp_v2_4.py` god class split: `RegimeDetector`, `SpreadEngine`, `RiskEvaluator`, `TickEmitter` | — | 2026-02-27 |
| DEBT-2 | 28 core unit tests: regime, spread, risk, fill EWMA, cancel rate | — | 2026-02-27 |
| DEBT-3 | `hb_bridge.py` split into `signal_consumer.py`, `adverse_inference.py`, `hb_event_fire.py` | — | 2026-02-27 |
| DEBT-4 | Config hierarchy doc: `docs/infra/config_hierarchy.md` | — | 2026-02-27 |
| DEBT-5 | 63 service-layer tests: recon, coordination, event store, watchdog, kill switch | — | 2026-02-27 |
| DEBT-6 | ClickHouse removed: ingest service + compose blocks + Grafana datasource | — | 2026-02-27 |
| EXEC-1 | Kill switch stops bot container after cancel-all via Docker API | — | 2026-02-27 |
| EXEC-2 | `ExchangeRateLimiter` wired into fee_provider, exchange_snapshot, protective_stop | — | 2026-02-27 |
| EXEC-3 | Exchange snapshot fetches perp positions via `ccxt.fetch_positions()` | — | 2026-02-27 |
| EXEC-4 | Redis failure counter: `_consecutive_failures`, WARNING/ERROR escalation | — | 2026-02-27 |
| EXEC-5 | Stuck-executor escalation: N ticks → SOFT_PAUSE → HARD_STOP | — | 2026-02-27 |
| EXEC-6 | Level-id deduplication guard with TTL | — | 2026-02-27 |
| EXEC-7 | `async_with_retry` variant with `asyncio.sleep` | — | 2026-02-27 |
| EXEC-8 | Recon drift escalation: 3 corrections in 1h → HARD_STOP | — | 2026-02-27 |
| EXEC-9 | SimBroker: shadow executor for live-vs-paper calibration | — | 2026-02-27 |
| EXEC-10 | Open-order recovery: startup warning log (framework limitation) | — | 2026-02-27 |
| EXEC-11 | `cancel_all_stops` implemented via `fetch_open_orders` + cancel | — | 2026-02-27 |
| EXEC-12 | Paper fill model: `prob_fill_on_limit` default 1.0 → 0.4 | — | 2026-02-27 |
| EXEC-13 | Go-live checklist: items 15-24 added (framework patches, NTP, kill switch, etc.) | — | 2026-02-27 |
| ROAD-8 | API key hygiene docs: 3-key policy, rotation procedure, IP allowlist | — | 2026-02-27 |
| INFRA-1 | Watchdog STATE_FILE to persistent /data/ path | — | 2026-02-27 |
| INFRA-3 | risk-service reports volume `:ro` → writable overlay | — | 2026-02-27 |
| ROAD-2 | Walk-forward backtest engine + multi-day summary script | — | 2026-02-27 |
| ROAD-3 | OB imbalance signal in controller + spread skew | — | 2026-02-27 |
| ROAD-4 | Kelly-adjusted position sizing (disabled by default) | — | 2026-02-27 |
| ROAD-6 | TCA report: shortfall, market impact, adverse selection | — | 2026-02-27 |
| ROAD-7 | 6 incident response playbooks in docs/ops/incident_playbooks/ | — | 2026-02-27 |
| ROAD-10 | Regime classifier infrastructure: feature builder v2, ML scripts, signal wiring | — | 2026-02-27 |
| ROAD-11 | Adverse classifier infrastructure: dataset builder, training script, bridge wiring | — | 2026-02-27 |
| P1-5 | `order_book_stale` log uses 30s-gated value | `9fef542` | 2026-02-26 |
| — | Add `BACKLOG.md` + env template | `9fef542` | 2026-02-26 |
| — | Alertmanager empty SLACK_WEBHOOK_URL crash | `6c5faef` | 2026-02-26 |
| — | Kill-switch healthcheck curl → python | `6c5faef` | 2026-02-26 |
| — | Day-2 gate auto-refresh integrity | `6c5faef` | 2026-02-26 |
| — | Derisk direction bug (short→BUY-only) | `23cc76e` | 2026-02-26 |
| — | Derisk spread too wide (add `derisk_spread_pct`) | `23cc76e` | 2026-02-26 |
| — | One-sided regimes on delta-neutral perp | `23cc76e` | 2026-02-26 |
| — | Reconciliation `inventory_drift_critical` false-positive | `1e99ea1` | 2026-02-26 |
| — | Promotion gates policy scope + perpetual base_pct | `3bf0734` | 2026-02-26 |
| — | Artifact hygiene + .gitignore | `199654d` | 2026-02-26 |
