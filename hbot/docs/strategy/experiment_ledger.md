# EPP v2.4 Experiment Ledger

## Purpose
This file is the permanent research ledger for `bot1` strategy tuning and experiment cycles.

Use it to:
- track every material strategy/config/code experiment
- record why a change was made
- record what evidence was observed
- prevent repeating failed ideas
- keep a clean chain from hypothesis -> change -> result -> decision

Primary scope:
- `hbot/controllers/epp_v2_4.py`
- `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`
- strategy-facing paper execution changes that affect fill quality or runtime behavior

Primary evidence sources:
- `hbot/data/bot1/logs/epp_v24/bot1_a/minute.csv`
- `hbot/data/bot1/logs/epp_v24/bot1_a/fills.csv`
- `hbot/reports/desk_snapshot/bot1/latest.json`
- `hbot/reports/analysis/performance_dossier_latest.json`
- `hbot/reports/strategy/multi_day_summary_latest.json`
- `hbot/reports/strategy/strategy_loop_20260305.md`

## Entry Template
Copy this block for every new experiment or tuning cycle.

```markdown
## EXP-YYYYMMDD-XX: Short title
- Date:
- Type: `config` | `code` | `config+code`
- Area: `regime` | `edge_gate` | `governor` | `inventory` | `paper_execution` | `risk` | `other`
- Hypothesis:
- Changes:
  - `path`: change summary
- Observation window:
- Metrics checked:
  - fills:
  - net pnl:
  - pnl/fill:
  - maker ratio:
  - soft-pause ratio/state:
  - drawdown:
- Result: `keep` | `revert` | `inconclusive`
- Decision / next step:
```

## Current Baseline
- Bot: `bot1`
- Pair: `BTC-USDT`
- Mode: `paper`
- Current active strategy files:
  - `hbot/controllers/epp_v2_4.py`
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`
- Current long-window warning baseline from `performance_dossier_latest.json`:
  - expectancy per fill: negative
  - taker expectancy: materially negative
  - dominant regime: `neutral_low_vol`
  - soft-pause burden: elevated

## Ledger

## EXP-20260307-17: Enforce paper lot-size parity in runtime sizing
- Date: `2026-03-07`
- Type: `code+config`
- Area: `paper_execution`
- Hypothesis: controller/runtime sizing was underestimating per-order notional (projected ~`2` quote) while paper execution rounded orders to exchange lot size (`0.001` BTC, ~`67` quote each side), creating hidden 10x upsize and invalid risk/expectancy telemetry.
- Changes:
  - `hbot/controllers/epp_v2_4.py`: added PaperDesk-spec lot-size constraint resolution and applied it in `_quantize_amount()` / `_quantize_amount_up()`, including fallback when trading rules are temporarily unavailable
  - `hbot/controllers/epp_v2_4.py`: hardened `_min_base_amount()` to include rule-based minima and PaperDesk lot minima, and scaled `_project_total_amount_quote()` minimum by active level count
  - `hbot/controllers/spread_engine.py`: changed runtime notional floor so min-base is enforced per active level, not once globally
  - `hbot/tests/controllers/test_epp_v2_4_core.py`: added sizing-alignment regressions for paper-spec min-lot quantization and per-level projected-total floor
  - `hbot/tests/controllers/test_spread_engine.py`: added regression for per-level min-base total-notional enforcement
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: retained `total_amount_quote=140` to keep intended sizing in the same scale as effective lot-constrained order flow
- Observation window: runtime probes before fix showed `create_executor_enter amount=0.0001` with PaperDesk `rem=0.001`; after fix, executor and placement traces now both show `amount=0.001` and minute snapshot `projected_total_quote` moved from ~`1.998` to `134.5465`
- Metrics checked:
  - fills: expect fewer unexplained PnL jumps from silent lot upsize
  - net pnl: target is more reliable edge accounting before further alpha tuning
  - pnl/fill: expect cleaner relation between configured sizing and realized per-fill outcomes
  - maker ratio: unchanged directly
  - soft-pause ratio/state: expected improvement as risk math and execution sizing align
  - drawdown: expected reduction in hidden sizing shock risk
- Result: `inconclusive`
- Decision / next step: collect a new post-fix sample window, then re-run dossier and compare expectancy/maker-taker mix with sizing now aligned end-to-end.

## EXP-20260307-16: Profitability clamp v2 (maker quality over taker churn)
- Date: `2026-03-07`
- Type: `config`
- Area: `inventory`
- Hypothesis: today sample shows negative expectancy across maker and taker fills with taker-heavy mix, and runtime probes show intended sub-min size quotes being promoted to exchange minimum lot (`0.0001` intent -> `0.001` actual). Aligning intended quote notional with lot constraints, while suppressing forced taker escalation and directional skew, should improve risk fidelity and per-fill expectancy.
- Changes:
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: increased `total_amount_quote` (`10` -> `140`) to align intended per-side order size with BTC-USDT perp minimum lot behavior seen at runtime, and tightened inventory cap (`max_base_pct` `0.20` -> `0.10`)
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: raised `take_profit` (`0.0006` -> `0.0010`) and `time_limit` (`120` -> `240`) to reduce micro-churn exits and seek better maker capture
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: increased derisk force-taker brakes (`derisk_force_taker_after_s` `300` -> `900`, `derisk_force_taker_min_base_mult` `4.0` -> `8.0`, `derisk_force_taker_expectancy_min_quote` `0.00` -> `0.02`, `derisk_force_taker_expectancy_override_base_mult` `12.0` -> `30.0`)
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: set `ob_imbalance_skew_weight` to `0.0` to disable short-horizon directional imbalance skew until expectancy quality recovers
- Observation window: pre-change baseline from fresh dossier rebuild (`2026-03-07`) showing `expectancy_per_fill_quote=-0.0353`, `maker_ratio=34.7%`, and `taker_expectancy_per_fill_quote=-0.0440`
- Metrics checked:
  - fills: monitor for lower forced-taker count and cleaner maker-led fills
  - net pnl: target reduced loss per hour first, then positive intraday drift
  - pnl/fill: target improvement in both maker and taker buckets
  - maker ratio: target move toward >= 45%
  - soft-pause ratio/state: expected stable-to-lower as forced derisk pressure decreases
  - drawdown: expected improvement via smaller inventory excursions
- Result: `inconclusive`
- Decision / next step: restart bot1 with lot-aligned sizing, verify that open-order remaining quantities match intended lot scale, then recompute dossier deltas and decide whether additional alpha-policy changes are needed.

## EXP-20260307-15: Stabilize stale detection and Bitget WS reconnect policy
- Date: `2026-03-07`
- Type: `config`
- Area: `risk`
- Hypothesis: bot1 appears "stale then back" when transient websocket churn temporarily delays minute logging; strict health checks can restart healthy-but-recovering runtime loops and amplify flapping.
- Changes:
  - `hbot/compose/docker-compose.yml`: bot1 healthcheck now mirrors watchdog semantics by allowing minute-csv grace when heartbeat remains fresh; added bot1-specific Bitget WS stability env overrides (`HB_BITGET_WS_HEARTBEAT_S=20`, `HB_BITGET_WS_MESSAGE_TIMEOUT_S=120`, `HB_BITGET_WS_MAX_CONSEC_TIMEOUTS=6`, `HB_BITGET_WS_TIMEOUT_RETRY_SLEEP_S=1.0`)
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: raised `reconnect_cooldown_s` from `3.0` to `8.0` to reduce reconnect-thrash quoting transitions
- Observation window: repeated user report of regular stale/recover cycles, plus runtime evidence of frequent WS reconnect events with low sustained `order_book_stale` incidence
- Metrics checked:
  - fills: preserve normal fill cadence while reducing forced-restart artifacts
  - net pnl: unchanged in immediate patch window
  - pnl/fill: unchanged in immediate patch window
  - maker ratio: expected broadly unchanged
  - soft-pause ratio/state: expected reduction in reconnect-driven guard oscillation
  - drawdown: unchanged in immediate patch window
- Result: `inconclusive`
- Decision / next step: restart bot1 with new settings, then monitor restart/stale incidence and reconnect event density over the next sample window.

## EXP-20260307-14: Relax neutral alpha no-trade threshold
- Date: `2026-03-07`
- Type: `config`
- Area: `edge_gate`
- Hypothesis: neutral runtime remains over-filtered because `alpha_policy_no_trade_threshold=0.55` blocks quoting even when maker score is in the workable 0.30-0.40 zone; lowering threshold should reduce no-trade idle windows and restore fill cadence.
- Changes:
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: lowered `alpha_policy_no_trade_threshold` from `0.55` to `0.30`
- Observation window: post-code-fix live paper runtime where minute rows still showed dominant `alpha_policy_state=no_trade`
- Metrics checked:
  - fills: target increase in neutral-regime maker participation
  - net pnl: monitor for improved spread-capture opportunity without taker-churn spike
  - pnl/fill: ensure expectancy does not degrade while increasing activity
  - maker ratio: expected to remain high
  - soft-pause ratio/state: unchanged directly; objective is alpha-policy activation
  - drawdown: monitor for inventory/carry side effects
- Result: `inconclusive`
- Decision / next step: restart bot1, then re-check `alpha_no_trade` ratio, `orders_active`, and no-trade-tagged fills over the next sample window.

## EXP-20260307-13: Alpha no-trade sweeps lingering paper orders
- Date: `2026-03-07`
- Type: `code`
- Area: `paper_execution`
- Hypothesis: even with active-executor cancels, PaperDesk orders can linger briefly during restart/recovery races and still fill while alpha is `no_trade`, creating policy-leak fills.
- Changes:
  - `hbot/controllers/epp_v2_4.py`: added throttled helper `_cancel_alpha_no_trade_paper_orders()` and wired it into `_resolve_quote_side_mode()` for alpha no-trade ticks
  - `hbot/tests/controllers/test_epp_v2_4_core.py`: added regression `test_alpha_no_trade_paper_cleanup_is_throttled`
- Observation window: post-restart runtime review (`minute.csv`, `fills.csv`, bot logs) plus targeted unit validation
- Metrics checked:
  - fills: target is reducing fills that occur while `alpha_policy_state=no_trade`
  - net pnl: unchanged in immediate patch window
  - pnl/fill: unchanged in immediate patch window
  - maker ratio: expected broadly unchanged
  - soft-pause ratio/state: unchanged directly; this is policy-consistency hardening
  - drawdown: expected improvement from reduced residual quote leakage
- Result: `inconclusive`
- Decision / next step: keep fix, run fresh sample, and compare no-trade/fill mismatch incidence in the next iteration.

## EXP-20260307-12: Fail-closed cancel when alpha enters no-trade
- Date: `2026-03-07`
- Type: `code`
- Area: `risk`
- Hypothesis: alpha policy can flip to `no_trade` while previously placed quote executors stay live until refresh; those stale quotes can still fill under `alpha_no_trade`, leaking policy intent and adding avoidable churn.
- Changes:
  - `hbot/controllers/epp_v2_4.py`: added immediate fail-closed cancellation path for all active quote executors when `alpha_policy_state=no_trade`, with per-state dedupe to avoid repeated cancel spam
  - `hbot/tests/controllers/test_epp_v2_4_core.py`: added regression `test_alpha_policy_no_trade_cancels_quotes_even_when_mode_already_off`
- Observation window: post-restart runtime review (`minute.csv`, `fills.csv`, bot logs) plus targeted unit validation
- Metrics checked:
  - fills: observed fills occurring while `alpha_policy_state=no_trade` before fix
  - net pnl: unchanged in immediate patch window
  - pnl/fill: unchanged in immediate patch window
  - maker ratio: expected unchanged; objective is policy consistency, not side mix
  - soft-pause ratio/state: expected unchanged
  - drawdown: expected reduced tail risk from unwanted residual fills
- Result: `inconclusive`
- Decision / next step: keep fix, monitor for disappearance of new `fills.csv` rows tagged with `alpha_policy_state=no_trade`, and verify no cancel-budget regressions.

## EXP-20260307-11: Neutral alpha no-trade respects edge resume band
- Date: `2026-03-07`
- Type: `code`
- Area: `edge_gate`
- Hypothesis: in `neutral_low_vol`, alpha policy can keep bot1 in `no_trade` even when net edge is already above the edge-resume threshold; this creates long quote starvation windows despite tradable edge conditions.
- Changes:
  - `hbot/controllers/epp_v2_4.py`: tightened the `neutral_low_edge` no-trade branch so it only blocks when maker score is below threshold **and** `net_edge < edge_resume_threshold`
  - `hbot/tests/controllers/test_epp_v2_4_core.py`: added regression `test_alpha_policy_allows_neutral_quote_when_edge_above_resume_threshold`
- Observation window: runtime audit on latest `minute.csv` rows plus targeted controller/unit validation
- Metrics checked:
  - fills: prolonged zero-fill windows linked to repeated `alpha_policy_state=no_trade` in neutral regime
  - net pnl: unchanged in immediate window (logic fix staged before next run sample)
  - pnl/fill: unchanged in immediate window
  - maker ratio: expected to remain maker-dominant while reducing idle/no-trade minutes
  - soft-pause ratio/state: expected no direct change; focus is reducing alpha `no_trade` suppression
  - drawdown: unchanged in immediate window
- Result: `inconclusive`
- Decision / next step: keep fix, restart/observe next sample, and compare `alpha_no_trade_ratio`, `orders_active`, and fill cadence before additional threshold tuning.

## EXP-20260307-08: Enforce one-way netting for paper leg actions
- Date: `2026-03-07`
- Type: `code`
- Area: `paper_execution`
- Hypothesis: `bot1` can still accumulate synthetic long+short hedge legs in paper mode while configured as `ONEWAY`, because explicit `position_action` hints are interpreted as hedge-leg accounting. This inflates gross exposure/risk signals, traps the bot in derisk loops, and degrades fill quality.
- Changes:
  - `hbot/controllers/paper_engine_v2/portfolio.py`: added one-way leg collapse (`_collapse_oneway_legs`) so non-hedge positions are normalized to a single net leg; ignored explicit `OPEN_*`/`CLOSE_*` leg actions in `settle_fill()` when position mode is not hedge; made action-scoped `get_position()` return netted view in one-way mode
  - `hbot/controllers/epp_v2_4.py`: in fill accounting, force `position_action=auto` when controller position mode is one-way so local PnL/position updates net instead of splitting into hedge legs
  - `hbot/tests/controllers/test_paper_engine_v2/test_portfolio.py`: added regressions proving one-way mode nets correctly even when explicit leg actions are provided
- Observation window: code audit against latest `bot1` runtime artifacts (`minute.csv`, `desk_snapshot`, `performance_dossier`) plus full non-integration test suite
- Metrics checked:
  - fills: no new fills yet after restart; pre-fix window showed derisk taker churn while `base_pct_above_max` persisted
  - net pnl: pre-fix day remains negative; this fix addresses accounting/risk integrity before next tuning cycle
  - pnl/fill: pre-fix expectancy remained negative (maker and taker), indicating carry/churn burden
  - maker ratio: unchanged in the observed window
  - soft-pause ratio/state: elevated pre-fix; expected to drop if one-way netting prevents synthetic gross inflation
  - drawdown: unchanged in short post-fix window
- Result: `inconclusive`
- Decision / next step: keep this fix, let bot run to produce fresh minute/fill rows, and re-check (1) `base_pct_above_max` incidence, (2) `derisk_only/derisk_force_taker` dwell time, and (3) rolling expectancy after new fills.

## EXP-20260307-07: Perp rebalance targets signed net exposure
- Date: `2026-03-07`
- Type: `code`
- Area: `inventory`
- Hypothesis: `bot1` derisk was not flattening cleanly because perp rebalances were targeting sell-ladder inventory instead of the signed `target_net_base_pct`; in delta-neutral mode this leaves the controller biased toward holding base even during `derisk_only`.
- Changes:
  - `hbot/controllers/epp_v2_4.py`: added `_perp_target_base_amount()` and changed `check_position_rebalance()` so perp rebalances target signed net exposure derived from `target_net_base_pct` and `equity_quote`, rather than `_runtime_required_base_amount()`
  - `hbot/tests/controllers/test_epp_v2_4_core.py`: added regression coverage proving a delta-neutral perp rebalance targets full flattening instead of retaining ladder inventory
- Observation window: fresh `bot1` runtime after controller reload
- Metrics checked:
  - fills: expect fewer repeated derisk fills while still above max base
  - net pnl: target is lower carry bleed during inventory cleanup
  - pnl/fill: expect stressed derisk fills to improve or disappear
  - maker ratio: may dip slightly if flattening completes faster
  - soft-pause ratio/state: should improve if `base_pct_above_max` clears faster
  - drawdown: should improve if inventory is allowed to truly return toward zero
- Result: `inconclusive`
- Decision / next step: restart `bot1`, watch for reduction in `base_pct_above_max|derisk_only|derisk_force_taker`, and rerun dossier once new fills arrive.

## EXP-20260307-06: Bot1 earlier profit capture and proactive rebalance
- Date: `2026-03-07`
- Type: `config`
- Area: `inventory`
- Hypothesis: `bot1` is not harvesting inventory gains quickly enough because profit targets are wider than the realized intraday edge and rebalancing is mostly deferred until `derisk_only`; earlier take-profit and proactive rebalancing should cut carry bleed and reduce stressed exits.
- Changes:
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: reduced `take_profit` from `0.004` to `0.0012`
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: reduced `time_limit` from `300` to `120`
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: changed `skip_rebalance` from `true` to `false`
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: reduced `position_rebalance_min_base_mult` from `5.0` to `1.5`
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: increased `derisk_force_taker_after_s` from `90` to `180`
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: increased `derisk_force_taker_expectancy_override_base_mult` from `8.0` to `12.0`
- Observation window: pending fresh `bot1` paper runtime after config reload
- Metrics checked:
  - fills: expect fewer fills arriving while `soft_pause` / `derisk_only` dominates
  - net pnl: target is less negative `neutral_low_vol` expectancy
  - pnl/fill: expect smaller carry losses from earlier flattening
  - maker ratio: should remain acceptable even if slightly lower
  - soft-pause ratio/state: should fall if inventory stops overshooting `max_base_pct`
  - drawdown: should improve if inventory excursions are clipped earlier
- Result: `inconclusive`
- Decision / next step: rerun `bot1`, then compare fresh fill mix and `position_rebalance` behavior before deciding whether the next step is another clamp or a controller change.

## EXP-20260307-05: Bot6 Bitget directional CVD lane bootstrap
- Date: `2026-03-07`
- Type: `code+config`
- Area: `other`
- Hypothesis: a dedicated Bitget perpetual lane that scores futures-vs-spot CVD divergence, stacked imbalances, ADX/SMA trend confirmation, and funding alignment will make directional conviction explicit and observable without mixing the logic into the shared `bot1` market-making baseline.
- Changes:
  - `hbot/controllers/epp_v2_4_bot6.py`: added the dedicated bot6 controller lane for CVD-driven directional bias, size scaling, hedge-candidate signaling, and bot6 telemetry fields
  - `hbot/controllers/market_making/epp_v2_4_bot6.py`: added the standard market-making shim for bot6 loading
  - `hbot/services/common/market_data_plane.py`, `hbot/controllers/connector_runtime_adapter.py`: exposed directional trade-flow features for futures/spot CVD divergence, funding bias, and stacked-imbalance scoring
  - `hbot/controllers/paper_engine_v2/*`, `hbot/services/paper_exchange_service/main.py`: extended hedge-aware paper/runtime plumbing so bot6 can operate with explicit long/short leg semantics
  - `hbot/data/bot6/conf/controllers/epp_v2_4_bot6_bitget_cvd_paper.yml`, `hbot/data/bot6/conf/scripts/v2_epp_v2_4_bot6_bitget_cvd_paper.yml`, `hbot/data/bot6/conf/conf_client.yml`: added isolated bot6 paper config scaffolding
  - `hbot/compose/docker-compose.yml`, `hbot/env/.env.template`, `hbot/scripts/ops/preflight_paper_exchange.py`, `hbot/monitoring/promtail/promtail-config.yml`: wired bot6 into compose, env rollout toggles, preflight checks, and log scraping
  - `hbot/tests/controllers/test_epp_v2_4_bot6.py`, `hbot/tests/controllers/test_paper_engine_v2/test_portfolio.py`, `hbot/tests/services/test_market_data_plane.py`, `hbot/tests/services/test_preflight_paper_exchange.py`: added focused validation coverage for bot6 controller behavior, hedge-leg snapshot persistence, directional trade-feature scoring, and bot6 rollout checks
- Observation window: targeted compile plus focused pytest coverage for bot6 controller logic, hedge-leg persistence, trade-feature scoring, and paper-exchange preflight wiring
- Metrics checked:
  - fills: not yet observed in a bot6 paper run
  - net pnl: not yet observed in a bot6 paper run
  - pnl/fill: not yet observed in a bot6 paper run
  - maker ratio: not yet observed in a bot6 paper run
  - soft-pause ratio/state: not yet observed in a bot6 paper run
  - drawdown: not yet observed in a bot6 paper run
- Result: `inconclusive`
- Decision / next step: keep the bot6 bootstrap and run an isolated paper observation window before judging edge; validate signal-score telemetry, hedge transitions, and funding-based exits against live stream data before any promotion discussion.

## EXP-20260307-04: Neutral carry clamp and taker suppression
- Date: `2026-03-07`
- Type: `config`
- Area: `inventory`
- Hypothesis: the current losses are driven by low-quality `neutral_low_vol` participation plus expensive taker/inventory relief, so making neutral quoting much more selective and capping inventory earlier should improve rolling expectancy even at lower fill count.
- Changes:
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: lowered selective-quote reduce/block thresholds and increased selective edge tightening so poor recent fill quality shuts the bot down faster
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: raised `alpha_policy_no_trade_threshold`, raised `alpha_policy_aggressive_threshold`, raised inventory-relief threshold, and widened aggressive cross spread multiplier to reduce low-conviction directional bias and near-touch entries
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: cut `max_base_pct`, raised `derisk_force_taker_min_base_mult`, and blocked force-taker escalation unless taker expectancy is non-negative
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: widened `neutral_low_vol` quoting and reduced `fill_factor` to prioritize spread quality over churn
- Observation window: pending fresh paper runtime after parity/gate cleanup
- Metrics checked:
  - fills: pending
  - net pnl: pending
  - pnl/fill: target is positive rolling expectancy first, even with lower volume
  - maker ratio: should remain high while absolute taker count falls
  - soft-pause ratio/state: expect more `no_trade` / blocked selective windows in weak neutral conditions
  - drawdown: should improve via lower inventory carry and fewer forced exits
- Result: `inconclusive`
- Decision / next step: collect a fresh post-change sample, then verify whether rolling expectancy improves without replacing spread capture with idle time only; if maker expectancy stays negative, move the next iteration into controller policy logic instead of config-only tuning.

## EXP-20260307-03: Hybrid MM alpha-policy redesign
- Date: `2026-03-07`
- Type: `code+config`
- Area: `inventory`
- Hypothesis: a forward-looking alpha policy that can explicitly choose `no_trade`, one-sided maker bias, or bounded aggressive inventory-relief entries will reduce neutral churn and make expectancy diagnosable by policy state instead of only by aggregate PnL.
- Changes:
  - `hbot/controllers/core.py`: added `QuoteGeometry` and attached quote-geometry decomposition to `SpreadEdgeState`
  - `hbot/controllers/spread_engine.py`: split base spread, reservation-price adjustment, inventory urgency, and alpha skew into explicit quote-geometry outputs
  - `hbot/controllers/epp_v2_4.py`: added `alpha_policy_*` config/runtime state, forward-looking alpha-policy evaluation, no-trade handling, aggressive near-touch quote mode, and cancel-on-no-trade behavior
  - `hbot/controllers/tick_emitter.py`: emitted alpha-policy and quote-geometry telemetry into `ProcessedState` and minute logs
  - `hbot/controllers/epp_logging.py`: extended `fills.csv` and `minute.csv` schemas for alpha-policy/regime observability
  - `hbot/scripts/analysis/performance_dossier.py`: added alpha-state ratios plus expectancy buckets by alpha policy and regime
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: pinned alpha-policy thresholds explicitly for `bot1`
  - `hbot/tests/controllers/test_core.py`, `hbot/tests/controllers/test_spread_engine.py`, `hbot/tests/controllers/test_tick_emitter.py`, `hbot/tests/controllers/test_epp_v2_4_core.py`, `hbot/tests/services/test_performance_dossier.py`: added/updated redesign coverage
- Observation window: compile + targeted redesign tests + full non-integration pytest suite + bot1 paper restart smoke validation
- Metrics checked:
  - fills: one post-restart maker fill recorded with new `alpha_policy_state` / `regime` columns in `fills.csv`
  - net pnl: initial smoke-window net remained negative
  - pnl/fill: initial smoke-window expectancy remained negative and sample size is too small for acceptance
  - maker ratio: 100% in the first smoke-window sample
  - soft-pause ratio/state: zero soft-pause burden in the first smoke-window sample; `minute.csv` showed both `maker_bias_buy` and `no_trade` alpha states
  - drawdown: negligible during the smoke window
- Result: `inconclusive`
- Decision / next step: keep the redesign and collect a materially larger paper sample before judging acceptance; use the new alpha-policy and regime expectancy buckets to decide whether `neutral_low_vol` should remain mostly `no_trade` or permit more `maker_bias_*` participation.

## EXP-20260305-01: Clean paper-state reset and duplicate-order prevention
- Date: `2026-03-05`
- Type: `code+config`
- Area: `paper_execution`
- Hypothesis: stale persisted paper/controller state and lingering paper orders were corrupting experiments and causing duplicate same-side quoting.
- Changes:
  - `hbot/controllers/daily_state_store.py`: added `clear()`
  - `hbot/controllers/paper_engine_v2/state_store.py`: added `clear()`
  - `hbot/controllers/paper_engine_v2/config.py`: added `paper_reset_state_on_startup`
  - `hbot/controllers/paper_engine_v2/desk.py`: clear persisted state on startup when enabled
  - `hbot/controllers/epp_v2_4.py`: clear controller daily state on paper reset; block duplicate level creation when `PaperDesk` already has open orders
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: one-shot enable then disable paper reset flag
- Observation window: startup validation + immediate paper runtime verification
- Metrics checked:
  - fills: resumed from clean 1000 USDT baseline
  - net pnl: not primary metric for this cycle
  - pnl/fill: not primary metric for this cycle
  - maker ratio: not primary metric for this cycle
  - soft-pause ratio/state: not primary metric for this cycle
  - drawdown: not primary metric for this cycle
- Result: `keep`
- Decision / next step: treat strategy edge as the main problem only after structural paper-state corruption was removed.

## EXP-20260305-02: Edge hold reduction
- Date: `2026-03-05`
- Type: `config`
- Area: `edge_gate`
- Hypothesis: shorter edge hold time would reduce dead time and increase productive fills.
- Changes:
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: `edge_state_hold_s: 120 -> 60`
- Observation window: short paper loop after config restart
- Metrics checked:
  - fills: increased
  - net pnl: worse
  - pnl/fill: worse
  - maker ratio: not the main improvement driver
  - soft-pause ratio/state: improved uptime but lower quality
  - drawdown: worse tendency
- Result: `revert`
- Decision / next step: faster resumption alone increases churn when edge quality is weak.

## EXP-20260305-03: Faster trend sensitivity
- Date: `2026-03-05`
- Type: `config`
- Area: `regime`
- Hypothesis: more sensitive trend detection would reduce bad neutral entries.
- Changes:
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: `trend_eps_pct: 0.0007 -> 0.0004`
- Observation window: short paper loop
- Metrics checked:
  - fills: stable
  - net pnl: still weak
  - pnl/fill: still negative
  - maker ratio: no decisive improvement
  - soft-pause ratio/state: no decisive improvement
  - drawdown: no decisive improvement
- Result: `inconclusive`
- Decision / next step: trend sensitivity alone did not fix `neutral_low_vol` expectancy; keep investigating quote quality.

## EXP-20260305-04: Wider neutral-low-vol spreads
- Date: `2026-03-05`
- Type: `config`
- Area: `regime`
- Hypothesis: `neutral_low_vol` needed wider pricing to improve per-fill edge and reduce adverse exits.
- Changes:
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: `neutral_low_vol.spread_min: 0.00020 -> 0.00030`
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: `neutral_low_vol.spread_max: 0.00055 -> 0.00075`
- Observation window: short paper loop
- Metrics checked:
  - fills: lower or slower, but still present
  - net pnl: short window improved, longer windows still weak
  - pnl/fill: improved short-term
  - maker ratio: acceptable
  - soft-pause ratio/state: stable
  - drawdown: no structural regression observed
- Result: `keep`
- Decision / next step: widening improved quality more than quantity; continue reducing neutral adverse-selection.

## EXP-20260305-05: Lower edge resume threshold
- Date: `2026-03-05`
- Type: `config`
- Area: `edge_gate`
- Hypothesis: resume threshold was too strict and causing unnecessary idle time after pauses.
- Changes:
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: `edge_resume_bps: 7.0 -> 6.5`
- Observation window: short paper loop
- Metrics checked:
  - fills: modestly improved
  - net pnl: daily read improved
  - pnl/fill: mixed, but better overall than prior cycle
  - maker ratio: acceptable
  - soft-pause ratio/state: better resumption behavior
  - drawdown: controlled
- Result: `keep`
- Decision / next step: keep resume logic looser than before, but avoid letting it override negative realized-edge evidence.

## EXP-20260305-06: Quote size increase
- Date: `2026-03-05`
- Type: `config`
- Area: `risk`
- Hypothesis: larger quote notional would improve capital efficiency.
- Changes:
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: `total_amount_quote: 10 -> 30`
- Observation window: short paper loop
- Metrics checked:
  - fills: no practical increase in realized size
  - net pnl: worse
  - pnl/fill: worse
  - maker ratio: not improved
  - soft-pause ratio/state: no benefit
  - drawdown: worse risk for no edge gain
- Result: `revert`
- Decision / next step: sizing up without edge is not useful; protect quality first.

## EXP-20260305-07: Tighter stop loss
- Date: `2026-03-05`
- Type: `config`
- Area: `risk`
- Hypothesis: tighter stop loss would reduce damage from adverse exits.
- Changes:
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: `stop_loss: 0.002 -> 0.0015`
- Observation window: short paper loop
- Metrics checked:
  - fills: low
  - net pnl: still negative to flat
  - pnl/fill: not improved enough
  - maker ratio: unchanged in principle
  - soft-pause ratio/state: no decisive help
  - drawdown: not a breakout improvement
- Result: `inconclusive`
- Decision / next step: the main issue remained entry quality, not just stop distance.

## EXP-20260306-01: Neutral EMA-side guard
- Date: `2026-03-06`
- Type: `code+config`
- Area: `regime`
- Hypothesis: in `neutral_low_vol`, the bot was still quoting against short-term directional lean before the full regime classifier switched, causing adverse fills.
- Changes:
  - `hbot/controllers/epp_v2_4.py`: added `neutral_trend_guard_pct` and effective quote-side filtering in `neutral_low_vol`
  - `hbot/controllers/epp_v2_4.py`: cancel stale opposite-side executors when guard flips side mode
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: `neutral_trend_guard_pct: 0.0002`
- Observation window: startup + early paper runtime after restart
- Metrics checked:
  - fills: resumed normally
  - net pnl: too early for durable conclusion
  - pnl/fill: too early for durable conclusion
  - maker ratio: no immediate regression
  - soft-pause ratio/state: no structural regression
  - drawdown: stable at restart window
- Result: `keep`
- Decision / next step: keep because it removes an identifiable bad neutral entry pattern.

## EXP-20260306-02: Block governor edge relaxation on negative realized edge
- Date: `2026-03-06`
- Type: `code`
- Area: `governor`
- Hypothesis: the daily PnL governor should not lower the edge standard merely because the bot is behind target when realized fill quality is already below cost.
- Changes:
  - `hbot/controllers/epp_v2_4.py`: block governor edge relaxation when fill-edge EWMA is below maker fee + slippage cost floor
  - `hbot/controllers/epp_v2_4.py`: refactored shared helper for `fill_edge_below_cost_floor`
  - `hbot/tests/controllers/test_epp_v2_4_core.py`: regression tests
- Observation window: validation + restart + early live paper observation
- Metrics checked:
  - fills: runtime healthy
  - net pnl: too early for full verdict
  - pnl/fill: intent is quality protection, not fill count
  - maker ratio: unchanged structurally
  - soft-pause ratio/state: still elevated
  - drawdown: no regression in restart window
- Result: `keep`
- Decision / next step: maintain fail-closed governor behavior; continue reducing idle time caused by sticky edge gating.

## EXP-20260306-03: Block stale-fill adaptive edge relaxation on negative realized edge
- Date: `2026-03-06`
- Type: `code`
- Area: `edge_gate`
- Hypothesis: stale-fill adaptation should not lower the minimum edge threshold when recent realized edge is already below cost, because that encourages low-quality re-entry after a bad patch.
- Changes:
  - `hbot/controllers/epp_v2_4.py`: disable stale-fill `adaptive_edge_relax_max_bps` effect when fill-edge EWMA is below cost floor
  - `hbot/tests/controllers/test_epp_v2_4_core.py`: regression tests for allowed vs blocked stale-fill relaxation
- Observation window: validation + live paper runtime
- Metrics checked:
  - fills: quoting resumed after restart
  - net pnl: too early for durable conclusion
  - pnl/fill: intent is improved selectivity
  - maker ratio: unchanged structurally
  - soft-pause ratio/state: still needs work
  - drawdown: no restart regression
- Result: `keep`
- Decision / next step: next bottleneck is `soft_pause_edge` stickiness and/or external daily target override behavior.

## EXP-20260306-04: Investigate sticky soft-pause and sparse quoting windows
- Date: `2026-03-06`
- Type: `analysis`
- Area: `edge_gate`
- Hypothesis: quoting dead time is now driven less by execution corruption and more by edge-gate stickiness, potentially amplified by persistent `execution_intent_daily_pnl_target_pct` governor activation.
- Changes:
  - no code/config change yet; evidence-gathering cycle only
- Observation window: live paper runtime after the `2026-03-06` structural edge-governor and adaptation fixes
- Metrics checked:
  - fills: orders were created around `14:16:59` / `14:17:16`, then a later fill around `14:18:44`
  - net pnl: day snapshot stayed modestly positive in quote terms during observation
  - pnl/fill: not yet recomputed for a durable post-change window
  - maker ratio: not recomputed for this short window
  - soft-pause ratio/state: controller repeatedly entered `soft_pause` with `soft_pause_edge = True`, and open orders dropped to zero during those windows
  - drawdown: low in the observed short window
- Result: `inconclusive`
- Decision / next step: inspect whether the active external daily target override and edge hysteresis are keeping the threshold too high after fills, causing long no-order windows despite otherwise healthy runtime.

## EXP-20260306-05: Raise adaptive minimum edge floor
- Date: `2026-03-06`
- Type: `config`
- Area: `edge_gate`
- Hypothesis: the controller is still relaxing too far toward near-zero edge after quiet periods, so lifting the adaptive minimum floor should preserve resumption behavior while preventing the lowest-quality re-entry regime.
- Changes:
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: added `adaptive_min_edge_bps_floor: 3.0`
- Observation window: pre-restart evidence from `latest.json`, recent minute rows, and existing performance dossier; post-change runtime still pending
- Metrics checked:
  - fills: current runtime is healthy enough to trade, so the next experiment can focus on trade quality instead of startup corruption
  - net pnl: current day is modestly positive, but 7-day and 15-day artifacts remain negative
  - pnl/fill: rolling expectancy remains negative, indicating overly permissive low-edge participation is still costly
  - maker ratio: structurally acceptable, so the main problem is entry quality not maker share
  - soft-pause ratio/state: historical no-order windows existed, but current snapshot shows running state with dynamic pause/resume thresholds behaving normally
  - drawdown: long-window drawdown remains above gate target, so fail-closed quality tightening is justified
- Result: `inconclusive`
- Decision / next step: restart `bot1`, observe whether the effective edge floor now stays above 3 bps during stale-fill periods, and compare idle time versus realized edge quality.

## EXP-20260306-06: Shorten edge-gate hold time to restore quote cadence
- Date: `2026-03-06`
- Type: `config`
- Area: `edge_gate`
- Hypothesis: `edge_state_hold_s: 120` is keeping the bot idle longer than necessary after transient edge dips; reducing the hold should improve quote re-entry cadence without reopening the negative-edge leak because the cost-floor protections from earlier experiments remain active.
- Changes:
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: reduce `edge_state_hold_s` from `120` to `45`
- Observation window: pre-reload evidence from the latest bot1 desk snapshot; post-change runtime observation pending
- Metrics checked:
  - fills: early post-reload runtime created both sides immediately and produced at least one new fill; latest published snapshot shows `fill_age_s` around 37s
  - net pnl: current day remained modestly positive in quote terms
  - pnl/fill: still not recomputed over a durable post-change window
  - maker ratio: still not recomputed over a durable post-change window
  - soft-pause ratio/state: post-reload snapshot remained `state = running` with `soft_pause_edge = False`
  - orders active: latest published snapshot still showed `orders_active = 0` and `open_orders = []`, so sustained quote coverage is not yet proven
- Result: `inconclusive`
- Decision / next step: treat the shorter hold-time test as mixed but promising on immediate recovery; keep watching for whether quotes persist on-book after fills, and if the zero-order windows remain, inspect the create/cancel loop rather than the edge gate itself.

## EXP-20260306-07: Reduce post-issue idle throttle after fills
- Date: `2026-03-06`
- Type: `code`
- Area: `execution_cadence`
- Hypothesis: the zero-order windows are being extended by `get_levels_to_execute()` keeping each level in `_recently_issued_levels` for the full `executor_refresh_time`, which delays re-entry long after a fill or close even when the bot is still `running`. Using the short runtime cooldown instead should restore quote cadence without reintroducing duplicate-order churn.
- Changes:
  - `hbot/controllers/epp_v2_4.py`: expire `_recently_issued_levels` using `cooldown_time` instead of `executor_refresh_time`
  - `hbot/tests/controllers/test_epp_v2_4_core.py`: add regression tests for reissue after cooldown expiry and continued blocking inside cooldown
- Observation window: code-path analysis plus live paper evidence after `EXP-20260306-06`
- Metrics checked:
  - fills: post-reload runtime remained healthy; no immediate execution regression observed
  - net pnl: current day remained modestly positive in quote terms
  - pnl/fill: not yet recomputed for post-fix runtime
  - maker ratio: not yet recomputed for post-fix runtime
  - soft-pause ratio/state: fresh post-reload snapshot stayed `running` with `soft_pause_edge = False`
  - orders active: immediate post-reload snapshot showed `orders_active = 2`; in a longer window, paper-engine probes repeatedly showed `open=2` with resting orders (`paper_v2_92`, `paper_v2_93`) while the desk snapshot still reported `orders_active = 0`, indicating cadence improved but the exported active-order metric may be lagging or incomplete
- Result: `inconclusive`
- Decision / next step: keep this fix in place; next investigation should separate execution behavior from observability by reconciling `orders_active`/`open_orders` snapshot fields against PaperDesk probe output before making another strategy-level adjustment.

## EXP-20260306-08: Reconcile desk snapshot with PaperDesk open orders
- Date: `2026-03-06`
- Type: `code`
- Area: `observability`
- Hypothesis: the strategy runtime is now behaving better, but paper-mode observability is under-reporting active/open orders because exported state relies on connector open-orders paths that do not include PaperDesk engine orders. Exporting PaperDesk open orders directly should make `orders_active` and desk snapshots reflect actual resting makers.
- Changes:
  - `hbot/controllers/epp_v2_4.py`: count PaperDesk open orders as a floor for `orders_active` in paper mode
  - `hbot/scripts/shared/v2_with_controllers.py`: include PaperDesk bridge engine open orders in `open_orders_latest.json`, with dedupe against connector-reported orders
  - `hbot/tests/controllers/test_epp_v2_4_core.py`: add regression test for PaperDesk open-order counting
  - `hbot/tests/scripts/test_v2_with_controllers_hard_stop_kill_switch.py`: add regression tests for PaperDesk order export and connector/paper dedupe
- Observation window: code-path analysis plus live paper evidence after `EXP-20260306-07`
- Metrics checked:
  - fills: trading loop remains active; prior cadence fix already restored prompt reissue after stops
  - net pnl: current day remains modestly positive in quote terms
  - pnl/fill: not yet recomputed for post-fix runtime
  - maker ratio: not yet recomputed for post-fix runtime
  - soft-pause ratio/state: latest runtime stayed `running` with `soft_pause_edge = False`
  - orders active / open orders: after reload, `open_orders_latest.json`, desk snapshot, and PaperDesk probe all agreed on two resting orders (`paper_v2_96`, `paper_v2_103`), and desk snapshot now reports `orders_active = 2`
- Result: `keep`
- Decision / next step: rely on desk snapshot order fields again for the tuning loop; return focus to strategy expectancy and inventory behavior now that execution cadence and order observability are materially healthier.

## EXP-20260306-09: Remove directional one-sided quoting in trend regimes
- Date: `2026-03-06`
- Type: `config`
- Area: `inventory_bias`
- Hypothesis: the bot is still leaking expectancy through trend-regime directional bias because `up` remains `buy_only` and `down` remains `sell_only` even though the perp strategy target is net-flat. Switching both regimes back to two-sided quoting should reduce inventory drift and improve expectancy by letting skew handle bias instead of forcing directional accumulation.
- Changes:
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: set `regime_specs_override.up.one_sided` from `buy_only` to `off`
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: set `regime_specs_override.down.one_sided` from `sell_only` to `off`
- Observation window: live paper runtime after cadence and observability fixes
- Metrics checked:
  - fills: trading loop and order visibility are now healthy enough to evaluate strategy behavior rather than pipeline faults
  - net pnl: current day slipped back near flat/negative despite healthier order handling
  - pnl/fill: long-window expectancy remains negative
  - maker ratio: structurally acceptable, so the issue appears to be trade selection and inventory path rather than maker share
  - soft-pause ratio/state: no longer the primary blocker in the current loop
  - inventory behavior: latest desk snapshot showed `regime = up` while the config still encoded directional one-sided behavior despite the YAML comment and the strategy intent calling for delta-neutral perp MM
- Result: `inconclusive`
- Decision / next step: early runtime validation is positive. After reload, logs showed the bot starting in `up` regime and immediately placing both `buy_0` and `sell_0`, which confirms the directional one-sided bias has been removed from the trend override path. Keep observing whether this translates into lower inventory drift and better expectancy over a longer window.

## EXP-20260306-10: Reduce post-fill adaptive edge tightening
- Date: `2026-03-06`
- Type: `config`
- Area: `edge_gate`
- Hypothesis: the strategy is re-entering `soft_pause_edge` too quickly after fresh fills because the adaptive edge floor still adds up to 3 bps of post-fill tightening. Reducing `adaptive_edge_tighten_max_bps` should keep the bot quoting through benign post-fill conditions without reopening the stale-fill undertrading problem.
- Changes:
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: add `adaptive_edge_tighten_max_bps: 1.5` (down from controller default `3`)
- Observation window: live paper runtime immediately after EXP-20260306-09
- Metrics checked:
  - post-fill edge state: after the trend-regime reload, runtime entered `neutral_low_vol` with `soft_pause_edge = True` only ~15s after a buy fill
  - adaptive edge floor: snapshot showed `adaptive_effective_min_edge_pct = 0.000492...` while `net_edge_gate_pct = 0.000472...`, creating a fresh soft pause despite healthy market connectivity
  - fill age: `adaptive_fill_age_s` was far below the `adaptive_fill_target_age_s = 900` default, so the fast-fill tightening branch is currently active most of the time right after trades
  - trend-regime validation: EXP-20260306-09 already showed the bot can now create both `buy_0` and `sell_0` in `up`, so the next blocker appears to be post-fill gating rather than one-sided regime bias
- Result: `inconclusive`
- Decision / next step: early signal is favorable. Fresh post-reload snapshot in `neutral_low_vol` showed `adaptive_effective_min_edge_pct = 0.0003`, `edge_pause_threshold_pct = 0.0003`, `net_edge_gate_pct = 0.000339...`, and `soft_pause_edge = False`, whereas the prior run had re-entered `soft_pause_edge` with a materially higher adaptive threshold soon after a fill. Continue monitoring to confirm this is durable and does not simply shift risk into overtrading.

## EXP-20260306-11: Block duplicate PaperDesk level reissue during inflight accept
- Date: `2026-03-06`
- Type: `code`
- Area: `execution_integrity`
- Hypothesis: the current expectancy/inventory read is being distorted because the controller can reissue the same side level while the prior PaperDesk order is still in the engine inflight queue. Treating inflight accept orders as live occupancy should prevent duplicate `buy_0` / `sell_0` stacking before PaperDesk promotion to `open_orders()`.
- Changes:
  - `hbot/controllers/epp_v2_4.py`: extend `_paper_open_order_level_ids()` to include PaperDesk `_inflight` orders with action `accept`
  - `hbot/controllers/epp_v2_4.py`: extend `_paper_open_order_count()` to include the same inflight accept orders for more accurate working-order visibility
  - `hbot/tests/controllers/test_epp_v2_4_core.py`: add regression coverage proving an inflight PaperDesk buy blocks duplicate `buy_0` reissue and is counted for the current controller connector only
- Observation window: live paper runtime immediately after EXP-20260306-10
- Metrics checked:
  - order integrity: logs showed `buy_0` created twice while the first PaperDesk buy still had `engine_open=1 engine_inflight=1`, producing three live orders total (`paper_v2_107`, `paper_v2_108`, `paper_v2_109`)
  - inventory drift: desk snapshot shifted from a small short to a long-biased book while duplicate buys were resting, making strategy-quality conclusions unreliable
  - gating state: `soft_pause_edge` was already improved by EXP-20260306-10, so the newly observed distortion was execution-level duplication rather than edge gating
  - validation: `python -m py_compile hbot/controllers/epp_v2_4.py` and `PYTHONPATH=hbot python -m pytest hbot/tests/ -x -q --ignore=hbot/tests/integration` both passed after the fix
- Result: `keep`
- Decision / next step: post-reload runtime confirms the duplicate path is closed. Startup created only one `buy_0` and one `sell_0`; subsequent probes showed a single live resting buy with no same-level reissue while the prior order was still working. Strategy analysis can resume without duplicate PaperDesk stacking contaminating the read.

## EXP-20260306-12: Clamp PnL governor edge relaxation
- Date: `2026-03-06`
- Type: `config`
- Area: `trade_selection`
- Hypothesis: the PnL governor is staying active for most of the day and relaxing the edge floor too aggressively while actual PnL remains negative, which likely pushes the bot into lower-quality trades. Reducing `pnl_governor_max_edge_bps_cut` should preserve the adaptive catch-up behavior while preventing the governor from cheapening the quote threshold by ~4-5 bps.
- Changes:
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: change `pnl_governor_max_edge_bps_cut` from `5` to `3`
- Observation window: live paper runtime after EXP-20260306-11 execution-integrity fix
- Metrics checked:
  - governor state: fresh snapshot still showed `pnl_governor_active = True` with `pnl_governor_deficit_ratio = 0.804...`
  - edge relaxation magnitude: live runtime was applying `pnl_governor_edge_relax_bps = 4.022...`, close to the configured cap, even though realized daily PnL remained negative
  - trade quality context: long-window dossier expectancy remains negative, so preserving edge quality is more important than chasing the daily target through aggressive relaxation
  - runtime health: soft-pause edge behavior and duplicate-level execution integrity were already improved in EXP-20260306-10 and EXP-20260306-11, making governor aggressiveness the next clean lever
- Result: `inconclusive`
- Decision / next step: early signal is favorable. Fresh post-reload snapshot showed `pnl_governor_edge_relax_bps = 2.433...` versus the prior `4.022...`, while runtime remained `state = running`, `soft_pause_edge = False`, and PaperDesk probes showed normal two-sided startup followed by a single resting order after fill. Keep observing expectancy and fill quality to confirm that reduced governor aggressiveness improves PnL rather than just slowing turnover.

## EXP-20260306-13: Raise base edge floor to improve fill quality
- Date: `2026-03-06`
- Type: `config`
- Area: `trade_selection`
- Hypothesis: the bot is still recording `fill_edge_below_cost_floor` often enough that stale-fill relaxation is being disabled, which means recent fills remain below the cost-quality bar even after the governor clamp. A small increase in the base edge threshold should improve per-fill quality without fully stalling the paper loop.
- Changes:
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: raise `min_net_edge_bps` from `6.0` to `6.5`
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: raise `edge_resume_bps` from `6.5` to `7.0`
- Observation window: runtime after EXP-20260306-12
- Metrics checked:
  - fill quality signal: fresh snapshot showed `pnl_governor_activation_reason = fill_edge_below_cost_floor` with reason counts dominated by that state
  - governor state: `pnl_governor_edge_relax_bps` already dropped materially after EXP-20260306-12, so remaining low-quality pressure is not primarily coming from the governor
  - runtime health: bot remained `running`, `soft_pause_edge = False`, and open orders stayed orderly at two sides, so a modest edge-floor lift is now a cleaner trade-quality experiment than another cadence change
  - inventory drift: inventory was close to flat, so directional imbalance is not currently the main issue
- Result: `inconclusive`
- Decision / next step: early follow-up suggests this change alone is insufficient, because the effective edge floor still relaxed back to the `3 bps` floor under stale-fill conditions. The next step is to clamp stale-fill relaxation directly so the higher base edge standard can actually hold in runtime.

## EXP-20260306-14: Clamp stale-fill adaptive edge relaxation
- Date: `2026-03-06`
- Type: `config`
- Area: `trade_selection`
- Hypothesis: the previous edge-floor increase is being neutralized because `adaptive_edge_relax_max_bps` is still large enough to drag the effective threshold all the way back to the hard floor when fills go stale. Reducing stale-fill relaxation should stop the bot from cheapening quotes just because recent fills are sparse.
- Changes:
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: reduce `adaptive_edge_relax_max_bps` from `8` to `2`
- Observation window: runtime after EXP-20260306-13
- Metrics checked:
  - effective threshold: fresh post-reload snapshot still showed `adaptive_effective_min_edge_pct = 0.0003` and `edge_pause_threshold_pct = 0.0003`, despite the higher configured base edge floor
  - stale-fill state: `adaptive_fill_age_s = 1800` indicated the controller was in a fully stale-fill regime, so the relax path was dominating the edge calculation
  - governor interaction: `pnl_governor_edge_relax_bps` remained about `2.46`, which means the combination of governor relief and stale-fill relaxation can still overwhelm the intended quality floor
  - runtime health: bot stayed orderly with two-sided quotes and no duplicate-level stacking, so the next problem is threshold softness rather than execution integrity
- Result: `inconclusive`
- Decision / next step: reload `bot1` and verify that stale-fill runtime no longer collapses the effective edge floor back to the minimum.

## EXP-20260306-15: Restore recent fill timestamp on restart
- Date: `2026-03-06`
- Type: `code`
- Area: `runtime_state`
- Hypothesis: repeated config reloads are corrupting the adaptive edge logic because `_last_fill_ts` is not restored across restarts. That makes the controller assume `adaptive_fill_age_s = 1800` immediately after startup, which can trigger stale-fill edge relaxation from a fake age baseline and distort follow-on tuning results.
- Changes:
  - `hbot/controllers/epp_v2_4.py`: persist `last_fill_ts` in daily state
  - `hbot/controllers/epp_v2_4.py`: restore `last_fill_ts` from daily state on startup
  - `hbot/controllers/epp_v2_4.py`: hydrate `last_fill_ts` from the newest `ts` in `fills.csv` as a fallback during fill-cache warmup
  - `hbot/tests/controllers/test_epp_v2_4_core.py`: add regression coverage for CSV hydration and daily-state save/load of `last_fill_ts`
- Observation window: code investigation after EXP-20260306-14
- Metrics checked:
  - inconsistency: after reload, fresh snapshots repeatedly showed `adaptive_fill_age_s = 1800` despite `fill_stats.last_ts` remaining recent, proving runtime fill age was being forgotten
  - code path: `_last_fill_ts` was only updated in `did_fill_order()` and was never restored by `_load_daily_state()` or `_hydrate_seen_fill_order_ids_from_csv()`
  - validation: `python -m py_compile hbot/controllers/epp_v2_4.py` passed; targeted controller/state tests passed via `PYTHONPATH=hbot python -m pytest hbot/tests/controllers/test_epp_v2_4_core.py hbot/tests/controllers/test_epp_v2_4_state.py -q`
  - suite note: full non-integration pytest run is currently blocked by an unrelated failure in `hbot/tests/services/test_realtime_ui_api.py::test_desk_snapshot_fallback_extracts_position_and_orders`
- Result: `inconclusive`
- Decision / next step: reload `bot1` and verify that post-restart `adaptive_fill_age_s` tracks the actual recent fill timestamp instead of defaulting to `1800`.

## EXP-20260306-16: Lower daily PnL target to reduce governor pressure
- Date: `2026-03-06`
- Type: `config`
- Area: `trade_selection`
- Hypothesis: now that restart fill age is restored correctly, the remaining entry discount is largely coming from the daily PnL governor itself. Reducing `daily_pnl_target_pct` should lower the deficit ratio and reduce governor edge relaxation without disabling the governor entirely.
- Changes:
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: reduce `daily_pnl_target_pct` from `0.6` to `0.3`
- Observation window: live paper runtime after EXP-20260306-15
- Metrics checked:
  - restart state: fresh runtime now carries real `last_fill_ts` and reports realistic `adaptive_fill_age_s` values instead of the bogus `1800` reload fallback
  - governor pressure: with the restart artifact removed, the bot still shows `pnl_governor_active = True`, `pnl_governor_deficit_ratio ≈ 0.829`, and `pnl_governor_edge_relax_bps ≈ 2.49`
  - runtime health: bot remains `running`, `soft_pause_edge = False`, with two orderly resting makers and no duplicate-level stacking
  - trade-quality concern: realized PnL remains slightly negative, so continued aggressive catch-up pressure is more likely to degrade fill quality than help expectancy
- Result: `inconclusive`
- Decision / next step: follow-up runtime showed the lower target did not materially reduce governor pressure. `pnl_governor_target_pnl_quote` dropped, but `pnl_governor_edge_relax_bps` remained around `2.58` and the governor stayed active. The next clean experiment is to disable the governor for one isolated cycle and see whether entry quality improves without any deficit-driven edge discount.

## EXP-20260306-17: Disable PnL governor for one cycle
- Date: `2026-03-06`
- Type: `config`
- Area: `trade_selection`
- Hypothesis: if the remaining low-quality fills are primarily caused by deficit-driven edge discounts, disabling the PnL governor for one isolated cycle should remove that pressure and reveal whether the underlying base/adaptive edge policy is strong enough on its own.
- Changes:
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: set `pnl_governor_enabled` from `true` to `false`
- Observation window: runtime after EXP-20260306-16
- Metrics checked:
  - governor pressure persisted: `pnl_governor_active = True` and `pnl_governor_edge_relax_bps ≈ 2.58` even after reducing `daily_pnl_target_pct`
  - runtime health remained good: `state = running`, `soft_pause_edge = False`, and the bot maintained clean two-sided quoting
  - restart-state artifact is already fixed, so a governor-off cycle is now a trustworthy isolate rather than a confounded read
- Result: `inconclusive`
- Decision / next step: reload `bot1` and verify that `pnl_governor_active = False` and `pnl_governor_edge_relax_bps = 0` in fresh runtime snapshots, then compare fill cadence and edge quality.

## EXP-20260306-18: Clean restored paper orphans and clamp snapshot ages
- Date: `2026-03-06`
- Type: `code`
- Area: `restart_recovery`
- Hypothesis: the latest governor-off runtime is being undercut by a restart artifact rather than the edge policy itself. Restored PaperDesk orders can survive bot restarts without matching executors, leaving stale makers far from market that block fresh quoting; separately, the desk snapshot service can export negative age values when timestamps are slightly ahead of the snapshot clock. Cleaning orphaned restored paper orders at startup and clamping exported ages should restore trustworthy post-restart behavior and observability.
- Changes:
  - `hbot/controllers/epp_v2_4.py`: add startup cleanup for restored PaperDesk orders when running in paper mode with no active executors owning them
  - `hbot/services/desk_snapshot_service/main.py`: clamp `minute_age_s` and `fill_age_s` to non-negative values in canonical snapshots
  - `hbot/tests/controllers/test_epp_v2_4_state.py`: add regression coverage for paper-mode startup orphan cleanup
  - `hbot/tests/services/test_desk_snapshot_service.py`: add regression coverage for future-timestamp age clamping
- Observation window: governor-off runtime after EXP-20260306-17
- Metrics checked:
  - live runtime: `pnl_governor_active = False`, `pnl_governor_edge_relax_bps = 0`, but fills went quiet for ~20+ minutes while two restored makers aged on-book far beyond `executor_refresh_time`
  - order age evidence: `open_orders_latest.json` showed orders with ages around `1000-1900s`, inconsistent with expected runtime quote refresh behavior
  - quote quality read: those stale makers were materially away from current mid, making the apparent no-fill window a restart/recovery artifact rather than a clean read on the governor-off edge policy
  - observability oddity: top-level desk snapshot `fill_age_s` had previously gone negative in short windows while controller-side `adaptive_fill_age_s` remained sane
- Result: `keep`
- Decision / next step: live restart validation succeeded. After a true container restart, the current open-order snapshot rotated from the stale restored `paper_v2_135` / `paper_v2_136` pair to fresh runtime quotes (`paper_v2_137` / `paper_v2_138`) with young ages, and desk snapshot top-level ages remained non-negative. Return focus to strategy quality: the next tuning loop should target the post-fill `soft_pause` / edge-threshold behavior rather than restart hygiene.

## EXP-20260306-19: Cancel stale PaperDesk orders during runtime refresh
- Date: `2026-03-06`
- Type: `code`
- Area: `paper_execution`
- Hypothesis: refresh-driven repricing is still broken in paper mode because stopping a stale executor does not always remove its underlying PaperDesk order. The surviving order then blocks same-side re-creation via `_paper_open_order_level_ids()`, leaving quotes stranded far from market for many minutes and suppressing fills.
- Changes:
  - `hbot/controllers/epp_v2_4.py`: add runtime stale PaperDesk order cleanup tied to the executor refresh window so aged paper orders are explicitly canceled during repricing
  - `hbot/tests/controllers/test_epp_v2_4_core.py`: add regression test covering stale paper-order cancellation during refresh reconciliation
- Observation window: live paper runtime after EXP-20260306-18
- Metrics checked:
  - fills: runtime stalled at `69` fills while both makers stayed on-book for ~18-25 minutes without repricing
  - net pnl: day stayed slightly positive, but the fill drought made the short-window read low-confidence
  - pnl/fill: not recomputed yet; this fix targets runtime quote renewal rather than pricing edge itself
  - maker ratio: unchanged structurally
  - soft-pause ratio/state: not the active blocker in this window; state remained `running`
  - drawdown: stable
- Result: `keep`
- Decision / next step: live validation succeeded. After a clean restart, the controller created fresh orders (`paper_v2_140` / `paper_v2_141`), and when the refresh cycle fired it cleared the book to `open=0` instead of leaving a stale survivor pinned on one side. The next blocker is again strategy-side: post-fill `soft_pause_edge` reappeared immediately after the next fill, so the next tuning cycle should reduce the post-fill adaptive edge clamp rather than keep chasing paper-order hygiene.

## EXP-20260306-20: Let live raw edge override lagging EWMA gate
- Date: `2026-03-06`
- Type: `code`
- Area: `edge_gate`
- Hypothesis: the controller is still entering `soft_pause_edge` immediately after some fills because the adaptive post-fill threshold rises quickly while the edge gate decision continues to use a lagging EWMA. If the current raw `net_edge` already clears the live threshold, the bot should not pause just because the smoothed series has not caught up yet.
- Changes:
  - `hbot/controllers/epp_v2_4.py`: keep the EWMA for diagnostics/smoothing, but clamp `net_edge_gate` to at least the current raw `net_edge` before hysteresis evaluation
  - `hbot/tests/controllers/test_epp_v2_4_core.py`: add regressions for both false post-fill block and delayed resume caused only by EWMA lag
- Observation window: log/minute analysis after EXP-20260306-19 plus targeted unit validation
- Metrics checked:
  - post-fill gate mismatch: after the `2026-03-06T22:35:27Z` sell, minute rows at `22:36:18Z` and `22:37:26Z` showed `net_edge_pct` already above the instantaneous threshold while `net_edge_gate_pct` lagged below it, flipping state to `soft_pause`
  - persistence: the pause cleared only once EWMA caught up around `22:39:40Z`, indicating the blocker was gate lag rather than missing raw edge
  - governor isolation: `pnl_governor_active = False` and `pnl_governor_edge_relax_bps = 0`, so this window is no longer confounded by deficit-driven edge discounts
  - validation: targeted controller regressions cover both the no-false-pause path and the blocked-to-running resume path
- Result: `inconclusive`
- Decision / next step: run compile + targeted controller tests, then restart `bot1` and watch the next fresh fill window. If `soft_pause_edge` no longer appears while raw `net_edge_pct` remains above threshold, keep this and resume PnL observation instead of further gate tuning.

## EXP-20260306-21: Selective market-making redesign
- Date: `2026-03-06`
- Type: `code+config`
- Area: `trade_selection`
- Hypothesis: the current controller is structurally unprofitable because it keeps quoting in low-quality `neutral_low_vol` conditions, then leaks the rest of the PnL through inventory/carry cleanup. A stronger selective quote-quality layer should reduce activity materially, tighten the economic entry bar when realized fill quality weakens, and fail-close the bot when recent conditions are statistically bad.
- Changes:
  - `hbot/controllers/epp_v2_4.py`: add selective quote-quality scoring from realized fill edge, adverse-fill streak, and recent slippage; wire the result into adaptive min-edge tightening, side suppression, fail-closed soft pause, and reduced-mode level issuance
  - `hbot/controllers/tick_emitter.py`: export selective quote state/score/reason telemetry into processed state and minute logs
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: enable selective quoting and set initial thresholds for reduce vs block behavior
  - `hbot/scripts/analysis/performance_dossier.py`: add selective quote block/reduce ratios to dossier summaries
  - `hbot/tests/controllers/test_epp_v2_4_core.py`: add regressions for selective edge tightening, side suppression, soft-pause activation, and reduced-mode level throttling
  - `hbot/tests/services/test_performance_dossier.py`: add summary assertions for selective quote ratios
- Observation window: implementation + targeted validation before live paper runtime
- Metrics checked:
  - baseline failure mode: `performance_dossier_latest.json` still shows negative maker and taker rolling expectancy while `multi_day_summary_latest.json` shows spread capture is not dominant
  - design intent: selective quote telemetry must expose when the controller is `inactive`, `reduced`, or `blocked` instead of hiding the new behavior behind generic soft-pause rows
  - protection target: selective filters must not block derisk/hard-stop paths while still cutting low-quality quote issuance
- Result: `inconclusive`
- Decision / next step: validate compile/tests, restart the paper stack, and compare the next paper window against the current baseline using the new selective quote metrics plus rolling expectancy, maker/taker expectancy, and inventory stress.

## EXP-20260307-01: Activate selective filters earlier in-session
- Date: `2026-03-07`
- Type: `config`
- Area: `trade_selection`
- Hypothesis: the selective redesign is live, but with `selective_quality_min_fills = 40` it remains `inactive` for too long during low-cadence recovery windows, so the new filter cannot influence today’s trading. Lowering the activation floor should let the quote-quality logic engage within the current session instead of waiting for another large fill sample.
- Changes:
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: reduce `selective_quality_min_fills` from `40` to `12`
- Observation window: first live paper loop after EXP-20260306-21
- Metrics checked:
  - live state: `orders_active = 2`, `soft_pause_edge = False`, and the controller resumed normal quoting
  - selective telemetry: `selective_quote_state = inactive`, `selective_quote_reason = insufficient_history`, `fills_count_today = 6`
  - fresh trading evidence: a new maker sell fill was recorded at `2026-03-07T00:28:29Z`, confirming the bot is active again and not stuck with empty books
- Result: `inconclusive`
- Decision / next step: restart the paper bot so the lower activation floor takes effect, then continue the observation loop until selective state transitions out of `inactive` or the next inactivity/performance blocker becomes clear.

## EXP-20260307-02: Loosen neutral_low_vol spread floor after fill drought
- Date: `2026-03-07`
- Type: `config`
- Area: `neutral_low_vol`
- Hypothesis: the current post-redesign dry spell is not caused by the new selective filter yet, because live telemetry still shows `selective_quote_state = inactive`. The real blocker is that the neutral low-vol cost model is producing a spread floor around `33-41bps`, which is too wide for steady maker interaction in the current paper tape. Lowering the neutral effective edge floor and increasing the neutral fill factor should move resting quotes closer to market without removing the guard rails entirely.
- Changes:
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: lower `min_net_edge_bps` from `6.5` to `5.5`
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: lower `edge_resume_bps` from `7.0` to `6.0`
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: lower `adaptive_min_edge_bps_floor` from `3.0` to `2.5`
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: raise `regime_specs_override.neutral_low_vol.fill_factor` from `0.50` to `0.62`
- Observation window: live paper runtime after EXP-20260307-01
- Metrics checked:
  - runtime health: controller remained `running` with `orders_active = 2`, `soft_pause_edge = False`, and no explicit risk reasons
  - fill drought: no fresh fills after `2026-03-07T00:32:05Z` even though the bot kept two resting orders live
  - quote geometry: minute rows stayed around `spread_pct = 0.0033-0.0041` while `adaptive_effective_min_edge_pct` remained roughly `6.5-7.9bps`, confirming over-wide neutral quotes rather than a hard pause
  - selective status: `selective_quote_state = inactive`, `selective_quote_reason = insufficient_history`, so the new selective filter is not yet the direct cause of inactivity
- Result: `inconclusive`
- Decision / next step: restart the paper bot, verify that neutral low-vol spread compresses materially, and then watch whether fills resume before the selective filter becomes active.

## EXP-20260307-03: Bot7 adaptive absorption grid lane
- Date: `2026-03-07`
- Type: `code+config`
- Area: `bot7_mean_reversion`
- Hypothesis: a dedicated paper-only `bot7` lane with public-trade-aware mean-reversion signals, hedge-aware paper accounting telemetry, and adaptive ATR grid spacing can express the Adaptive Absorption Grid strategy without changing bot1/bot5 behavior.
- Changes:
  - `hbot/controllers/epp_v2_4_bot7.py`: add the dedicated bot7 controller/config with Bollinger/RSI/ADX signal gating, recent-trade CVD/absorption/delta-trap state, adaptive grid spacing, and bot7-specific processed-data telemetry
  - `hbot/controllers/market_making/epp_v2_4_bot7.py`: add the Hummingbot controller shim for `controller_type: market_making`
  - `hbot/controllers/price_buffer.py`: add Bollinger Bands, RSI, and ADX helpers used by bot7
  - `hbot/controllers/epp_v2_4.py`, `hbot/controllers/tick_emitter.py`, `hbot/controllers/types.py`, `hbot/services/bot_metrics_exporter.py`: preserve/export long-short-gross hedge state plus bot7 strategy telemetry
  - `hbot/data/bot7/**`, `hbot/compose/docker-compose.yml`, `hbot/env/.env.template`, `hbot/monitoring/**`: add bot7 paper config, compose wiring, env placeholders, and log scraping surfaces
  - `hbot/tests/controllers/test_price_buffer.py`, `hbot/tests/controllers/test_epp_v2_4_bot7.py`: add targeted indicator and bot7 signal/grid regressions
- Observation window: implementation + targeted unit validation before first bot7 paper runtime
- Metrics checked:
  - targeted tests: `test_price_buffer.py`, `test_epp_v2_4_bot7.py`, `test_tick_emitter.py`, and paper-engine market-data regressions passed under `PYTHONPATH=hbot`
  - telemetry coverage: minute/Prometheus exports now include `position_gross_base`, `position_long_base`, `position_short_base`, per-leg entry prices, bot7 CVD, bot7 grid levels, and hedge target exposure
  - compatibility guard: bot7 is isolated behind its own controller name / data lane / compose service and leaves the existing bot5 controller contract intact
- Result: `inconclusive`
- Decision / next step: launch the bot7 paper lane, verify trade-feed freshness plus hedge-leg visibility in minute metrics, then evaluate fills, net pnl, maker ratio, CVD exits, hedge lifecycle, and drawdown before deciding whether to keep or tune the lane.

## Open Questions
- Is `execution_intent_daily_pnl_target_pct` keeping the governor active too persistently?
- Is edge-gate hysteresis too sticky after fills in `neutral_low_vol`?
- Are post-fill spreads still not widening enough before re-entry?

## Working Rules
- Every material strategy/config experiment must add or update an entry here in the same work session.
- Reverts are experiments too; record them explicitly.
- If a result is based only on startup behavior or a very short window, mark it `inconclusive`.
- Never claim a strategy improvement without naming the observation window and the metrics checked.

## EXP-20260306-16: Remove neutral imbalance bias and freeze live auto-tuning
- Date: `2026-03-06`
- Type: `code+config`
- Area: `trade_selection`
- Hypothesis: current negative expectancy is being amplified by two control-loop issues: imbalance can still create directional perp bias even when neutral configuration disables OB skew, and live auto-calibration is mutating edge thresholds while the strategy is still structurally losing. Tightening those paths should reduce inventory drift, carry drag, and derisk/taker leakage.
- Changes:
  - `hbot/controllers/epp_v2_4.py`: `_compute_alpha_policy()` now suppresses imbalance-only directional bias for neutral perp targets when OB skew weight is disabled, while preserving explicit inventory-relief behavior.
  - `hbot/controllers/epp_v2_4.py`: `_auto_calibration_record_fill()` now records `fill_edge_bps`, and `_derisk_force_expectancy_allows()` prefers taker fill-edge quality over raw per-fill net PnL when deciding whether force-taker derisk may escalate.
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: set `auto_calibration_shadow_mode: true` and add `derisk_force_taker_expectancy_min_fill_edge_bps: -1.5`.
  - `hbot/tests/controllers/test_epp_v2_4_core.py`: add regression coverage for disabled-imbalance neutral alpha behavior and fill-edge-based derisk allowance.
- Observation window: code-path validation plus current dossier/runtime artifact review; no fresh multi-hour paper soak yet after this change
- Metrics checked:
  - fills: prior dossier shows `85` fills with negative expectancy concentrated in `neutral_low_vol`
  - net pnl: prior dossier / multi-day summary remain negative pre-change, so this pass is aimed at reducing known loss drivers rather than claiming a measured uplift yet
  - pnl/fill: targeted against `expectancy_per_fill_quote = -0.0315` and `taker_expectancy_per_fill_quote = -0.0375`
  - maker ratio: prior run remained too taker-heavy at `31.8%`, so changes specifically try to reduce inventory/derisk paths that convert passive intent into taker cleanup
  - carry / inventory behavior: prior multi-day summary showed `carry_component_usdt = -2.7391` dominating spread capture
  - validation: `python -m py_compile hbot/controllers/epp_v2_4.py` passed; targeted controller pytest passed; full non-integration pytest remains blocked by unrelated promotion-gates test expecting a different event-store container name
- Result: `inconclusive`
- Decision / next step: keep these fixes in place and rerun paper/runtime analysis to see whether neutral-regime expectancy, maker ratio, and derisk dwell improve before making another threshold-only tuning pass.

## EXP-20260306-17: Restore bot1/base behavior and isolate bot7 concerns
- Date: `2026-03-06`
- Type: `architecture`
- Area: `strategy_isolation`
- Hypothesis: bot7 work should live in bot7-specific controller/config surfaces unless a change is genuinely shared platform infrastructure. Reverting bot1/base-path tuning changes and keeping bot7 behavior in `epp_v2_4_bot7.py` should preserve separation of concerns and prevent accidental bot1 strategy drift.
- Changes:
  - `hbot/controllers/epp_v2_4.py`: reverted the temporary bot1/base strategy behavior changes in `_compute_alpha_policy()` and `_derisk_force_expectancy_allows()`.
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: restored `auto_calibration_shadow_mode` to its prior bot1 setting and removed the temporary derisk fill-edge threshold knob.
  - `hbot/tests/controllers/test_epp_v2_4_core.py`: removed the bot1/base regression coverage that had been added for the reverted behavior.
- Observation window: immediate code-path isolation pass after the user requested bot7/bot1 separation; no new runtime performance window claimed
- Metrics checked:
  - boundary check: bot1 strategy semantics return to the shared base path, while bot7 continues to own its strategy behavior through `hbot/controllers/epp_v2_4_bot7.py`
  - validation: targeted compile and controller tests pending / rerun in the same task
- Result: `keep`
- Decision / next step: preserve shared changes only for platform/runtime contracts; implement any future bot7-only strategy behavior in the bot7 controller/config unless there is a clear shared-runtime reason not to.
