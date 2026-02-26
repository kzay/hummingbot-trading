# Project Backlog — EPP v2.4 Trading Desk

> **How to use this file**
> - Anything added here has been diagnosed and triaged.
> - Tiers: **P0** = blocks live trading / safety gap · **P1** = affects PnL / reliability · **P2** = quality / completeness
> - Status: `open` · `in-progress` · `done` · `deferred` · `wontfix`
> - When you start an item, move it to `in-progress` and note the date.
> - When done, move to `done` with a commit reference.

---

## P0 — Blocks Live Trading / Safety

### [P0-1] Signal service → controller wiring is missing `open`
**What**: `signal_service` publishes `StrategySignalEvent` and `MlSignalEvent` to `SIGNAL_STREAM` / `ML_SIGNAL_STREAM` on Redis. `epp_v2_4.apply_execution_intent()` and `_external_target_base_pct_override` exist on the controller side. **Nothing connects them.** Signals are generated and dropped.
**Decision needed**: Should the controller poll Redis in its own tick (lightweight inline reader), or should `hb_bridge.py` route signal events into `apply_execution_intent()` on the controller? The bridge approach keeps the controller clean. **Recommended: bridge route.**
**Files**: `hbot/services/signal_service/main.py`, `hbot/controllers/epp_v2_4.py:1015`, `hbot/controllers/paper_engine_v2/hb_bridge.py`
**Effort**: ~2-3h

---

### [P0-2] HARD_STOP does not emit a kill-switch Redis intent `open`
**What**: When the controller hits a HARD_STOP (max loss, drawdown breach, cancel budget overflow), `ops_guard.force_hard_stop()` stops order placement but **does not publish an execution intent** to the kill-switch service. Open exchange orders are not canceled — only new orders stop.
**Decision needed**: Emit `kill_switch` intent from inside `_resolve_guard_state()` on first HARD_STOP transition, or wire it through `hb_bridge.py` on state change? Bridge is cleaner.
**Files**: `hbot/controllers/epp_v2_4.py:658`, `hbot/controllers/ops_guard.py`, `hbot/controllers/paper_engine_v2/hb_bridge.py`
**Effort**: ~1h

---

### [P0-3] Exchange reconciliation runs blind (no API keys configured) `open`
**What**: `reconciliation_service` sets `exchange_source_enabled: false` when `RECON_EXCHANGE_SOURCE_ENABLED` is not set. `exchange_snapshot_service` returns `missing_credentials` when `BITGET_API_KEY` is absent. Live reconciliation therefore never compares against real exchange state.
**Action**: Set `BITGET_API_KEY` / `BITGET_SECRET` / `BITGET_PASSPHRASE` in `.env` (see `.env.example`), set `RECON_EXCHANGE_SOURCE_ENABLED=true` in compose for reconciliation service.
**Files**: `hbot/services/exchange_snapshot_service/main.py:47`, `hbot/services/reconciliation_service/main.py:232`, `hbot/compose/docker-compose.yml`
**Effort**: ~30min (config only, once API keys are set)

---

### [P0-4] Go-live hardening checklist: 0 of 14 items validated `open`
**What**: `hbot/docs/ops/go_live_hardening_checklist.md` is complete and well-written, but every checkbox is empty. Before live trading, all 14 items must be signed off.
**Action**: Work through checklist on testnet. Items 3 (kill switch), 4 (orphan scan), 9 (synthetic breach), 11 (paper-live parity) are highest risk.
**File**: `hbot/docs/ops/go_live_hardening_checklist.md`
**Effort**: ~half day on testnet

---

## P1 — Affects PnL / Reliability

### [P1-1] Funding rate fetched but never enters the cost model `open`
**What**: `_refresh_funding_rate()` stores `self._funding_rate` but this value is never subtracted from the spread floor or edge gate. For a short position in a positive-funding-rate environment, the strategy silently underestimates holding cost.
**Action**: Add `funding_rate_cost_bps` to the spread floor calculation in `_compute_spread_and_edge()`. For a short position with positive funding: `extra_cost = funding_rate * leverage * funding_periods_per_day`. Include in `min_edge_threshold`.
**Files**: `hbot/controllers/epp_v2_4.py:_compute_spread_and_edge`, `hbot/controllers/epp_v2_4.py:_refresh_funding_rate`
**Effort**: ~1h

---

### [P1-2] No realized-edge tracker — adverse selection not auto-detected `open`
**What**: The strategy computes theoretical `net_edge_pct` but has no running measurement of actual fill edge per regime. When fills consistently happen on the wrong side (adverse selection > cost), the bot does not auto-adapt. Only the drift-spike multiplier reacts to price moves, not fill quality.
**Decision needed**: Track a 30-minute EWMA of `pnl_vs_mid_pct` per fill. If EWMA drops below `-cost_floor_bps` for 30+ min in a given regime, auto-widen spreads by `1.5x` for that regime until EWMA recovers. Needs a new `_fill_edge_ewma` state field.
**Files**: `hbot/controllers/epp_v2_4.py:did_fill_order`, `hbot/controllers/epp_v2_4.py:_compute_spread_and_edge`
**Effort**: ~3h

---

### [P1-3] No EOD position close `open`
**What**: Daily rollover at 00:00 UTC resets loss counters but leaves any open position. A −0.5% unrealized position that rolls over starts the new day with a fresh loss budget but is already in a hole.
**Decision needed**: Two options: (a) `close_at_daily_rollover: true` config flag — on day rollover, if `abs(position_base) > min_close_notional`, emit a tight-spread derisk order to flatten before counters reset. (b) Alternatively, carry the unrealized PnL forward into the new day's starting equity. Option (a) is cleaner for live trading.
**Files**: `hbot/controllers/epp_v2_4.py:_maybe_roll_day`
**Effort**: ~2h

---

### [P1-4] OHLCV candles connector configured but never fetched `open`
**What**: `candles_connector` and `candles_trading_pair` config fields exist with validators, but `ohlcv` has 0 occurrences in controller logic. Regime detection uses internal 10s sampled mid, which is noisier than exchange 1m OHLCV for EMA/ATR computation.
**Decision needed**: Use `market_data_provider.get_candles_df()` with the configured `candles_connector` for EMA and ATR, falling back to the internal price buffer when candles unavailable. The `price_buffer` would remain for sub-minute drift detection only.
**Files**: `hbot/controllers/epp_v2_4.py:_detect_regime`, `hbot/controllers/price_buffer.py`
**Effort**: ~3-4h

---

### [P1-5] `order_book_stale` in `minute.csv` logs timer start, not 30s threshold `open`
**What**: `minute.csv` column `order_book_stale` logs `str(self._book_stale_since_ts > 0)` — fires immediately when the book stops moving, before the 30s trading guard triggers. This makes the ops log misleading: column shows `True` but the bot is still quoting.
**Action**: Change the logged value to `str(market.order_book_stale)` (the actual 30s-gated bool) instead of the raw timer flag. One-line fix.
**Files**: `hbot/controllers/epp_v2_4.py:2320`
**Effort**: ~5 min

---

### [P1-6] `neutral_high_vol` regime missing from PHASE0_SPECS `open`
**What**: Regime detection has `neutral_low_vol` and `high_vol_shock` but no middle ground. Moderate-volatility ranging (most common profitable MM environment) falls into `neutral_low_vol` (spreads potentially too tight) or triggers `high_vol_shock` (spreads too wide, level count drops to 1-2).
**Action**: Add `neutral_high_vol` RegimeSpec between `neutral_low_vol` and `high_vol_shock` with intermediate spreads. Add detection: `high_vol_band_pct * 0.5 <= band_pct < high_vol_band_pct` → `neutral_high_vol`.
**Files**: `hbot/controllers/epp_v2_4.py:PHASE0_SPECS`, `hbot/controllers/epp_v2_4.py:_detect_regime`
**Effort**: ~1h

---

### [P1-7] No automated paper-state daily backup `open`
**What**: `paper_desk_v2.json`, `minute.csv`, and `fills.csv` are single files with no backup schedule. A Docker volume wipe or container recreation loses all paper trading history.
**Action**: Add a small `ops_retention` cron step (or extend `scripts/ops/artifact_retention.py`) that copies the three key paper files to a timestamped archive directory once per day.
**Files**: `hbot/scripts/ops/artifact_retention.py`, `hbot/compose/docker-compose.yml`
**Effort**: ~1h

---

### [P1-8] `hbot-risk-service` is only 112 lines — needs audit `open`
**What**: `services/risk_service/main.py` is 112 lines vs 335-465 for comparable services. Likely a stub or early prototype.
**Action**: Read, verify it has a complete event loop, proper shutdown handling, and publishes meaningful outputs.
**Files**: `hbot/services/risk_service/main.py`
**Effort**: ~30min to audit, variable to fix

---

### [P1-9] ClickHouse ingest deployed but ClickHouse server not in compose `open`
**What**: `services/clickhouse_ingest/main.py` (232 lines) is in compose but there is no `clickhouse` service in `docker-compose.yml`. Events published to the ingest service are silently dropped.
**Action**: Either add a `clickhouse` service to compose (adds ~500MB RAM), or disable the ingest service until ClickHouse is intentionally set up, or replace with a simpler Postgres-only path.
**Decision needed**: Is ClickHouse needed now, or is Postgres sufficient?
**Files**: `hbot/compose/docker-compose.yml`, `hbot/services/clickhouse_ingest/main.py`
**Effort**: ~1h to wire or disable cleanly

---

## P2 — Quality / Completeness

### [P2-1] Critical source modules have no tests `open`

| Module | Risk | Recommended test |
|---|---|---|
| `price_buffer.py` | High — regime detection, ATR, EMA | Unit: EMA convergence, ATR correctness, drift detection edge cases |
| `hb_bridge.py` | High — fills routing, paper state sync | Unit: intent routing, fill event dispatch |
| `feature_builder.py` | Medium — ML pipeline input | Unit: feature vector shape, NaN handling |
| `inference_engine.py` | Medium — ML inference path | Unit: timeout, confidence gate |
| `exchange_snapshot_service` | Medium — ccxt credential handling | Unit: missing-creds graceful fallback |
| `bot_metrics_exporter.py` | Medium — Prometheus scrape | Integration: metric labels present |
| `fill_reconciler.py` | Medium — PnL accounting | Unit: FIFO PnL correctness |

**Files**: `hbot/tests/` (new files needed)
**Effort**: ~4-6h total

---

### [P2-2] Grafana alert rules never had a synthetic breach test `open`
**What**: `monitoring/prometheus/alert_rules.yml` defines rules (`KillSwitchTriggered`, `BotHardStop`, etc.) but these have never been validated with a real Prometheus scrape + trigger.
**Action**: Write a `scripts/ops/synthetic_alert_test.py` that temporarily sets a metric value above threshold and verifies the alert fires.
**Files**: `hbot/monitoring/prometheus/alert_rules.yml`, new test script
**Effort**: ~2h

---

### [P2-3] Slack alerting not configured `open`
**What**: `alertmanager.yml` has `slack_configs` commented out pending `SLACK_WEBHOOK_URL`. Critical alerts (HARD_STOP, kill-switch trigger) currently only go to the internal webhook sink.
**Action**: Set `SLACK_WEBHOOK_URL` in `.env` and uncomment `slack_configs` block in `hbot/monitoring/alertmanager/alertmanager.yml`.
**Files**: `hbot/monitoring/alertmanager/alertmanager.yml`, `.env`
**Effort**: 10 min (config only)

---

### [P2-4] Signal → controller architecture not documented `open`
**What**: There is no document describing the intended data flow from `signal_service` through `hb_bridge` to `epp_v2_4`. When P0-1 is implemented, this should be documented.
**Action**: Add a section to `hbot/docs/architecture/data_flow_signal_risk_execution.md` (file exists, check if it covers the full loop).
**Files**: `hbot/docs/architecture/data_flow_signal_risk_execution.md`
**Effort**: ~30min

---

## Done

| Item | Commit | Date |
|---|---|---|
| Derisk direction bug (short → BUY-only) | `23cc76e` | 2026-02-26 |
| Derisk spread too wide (add `derisk_spread_pct`) | `23cc76e` | 2026-02-26 |
| One-sided regimes on delta-neutral perp | `23cc76e` | 2026-02-26 |
| `max_base_pct` 0.90 → 0.60 | `23cc76e` | 2026-02-26 |
| Reconciliation: `inventory_drift_critical` false-positive during unwind | `1e99ea1` | 2026-02-26 |
| Alertmanager crash: empty `SLACK_WEBHOOK_URL` | `6c5faef` | 2026-02-26 |
| Kill-switch healthcheck: curl → python urllib | `6c5faef` | 2026-02-26 |
| Day-2 gate: auto-refresh integrity before evaluation | `6c5faef` | 2026-02-26 |
| Promotion gates: policy scope mismatch (bot4) | `3bf0734` | 2026-02-26 |
| Perpetual `base_pct > 1` false reconciliation critical | `3bf0734` | 2026-02-26 |
| Artifact hygiene + `.gitignore` tightening | `199654d` | 2026-02-26 |
