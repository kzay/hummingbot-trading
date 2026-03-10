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

## EXP-20260310-06: Bot7 thesis-only rerun after inactive-order cleanup
- Date: `2026-03-10`
- Type: `runtime_validation`
- Area: `bot7_mean_reversion`
- Hypothesis: after the inactive-order cleanup fix, Bot7 should produce a clean post-restart observation window where thesis-state `probe_*` / `mean_reversion_*` rows can be evaluated without fallback-fill contamination.
- Changes:
  - no code/config changes; reran the thesis-only performance breakdown on the fresh post-cleanup window
- Observation window: `2026-03-10T12:34:33.905104+00:00` through `2026-03-10T23:16:01.196853+00:00` using `hbot/data/bot7/logs/epp_v24/bot7_a/minute.csv`, `hbot/data/bot7/logs/epp_v24/bot7_a/fills.csv`, `hbot/data/bot7/logs/recovery/open_orders_latest.json`, and `hbot/reports/desk_snapshot/bot7/latest.json`.
- Metrics checked:
  - fills: `0` total fills in the clean window, with `0` thesis-state fills and `0` fallback-state fills
  - net pnl: `0` gross realized and `0` net after fees in the clean window because no new fills occurred
  - pnl/fill: not measurable in the clean window due to zero-fill sample
  - maker ratio: not measurable in the clean window due to zero-fill sample
  - soft-pause ratio/state: all `635` minute rows remained `hard_stop`; reasons were `464 regime_inactive`, `138 no_entry`, `13 indicator_warmup`, `1 trade_flow_stale`, `12 probe_short`, and `7 probe_long`
  - drawdown: unchanged / low, but the runtime stayed pinned behind `daily_turnover_hard_limit`; thesis rows reached `quote_side_mode` of `buy_only` or `sell_only` for `19` minutes while `orders_active` still stayed `0`
- Result: `inconclusive`
- Decision / next step: the cleanup fix succeeded, but viability is still unproven because the clean window has no execution sample; reset into a fresh non-hard-stop window before judging Bot7's thesis-state edge.

## EXP-20260310-05: Bot7 reuse paper-order fail-close in inactive off states
- Date: `2026-03-10`
- Type: `code`
- Area: `bot7_mean_reversion`
- Hypothesis: Bot7's executor-level cancellation is insufficient because the shared paper engine can still retain orphaned working orders after restarts or executor races; reusing the existing PaperDesk fail-close cleanup used by alpha no-trade should flush those lingering paper orders when Bot7 is intentionally `off` in `regime_inactive`, `no_entry`, `trade_flow_stale`, or expired warmup states.
- Changes:
  - `hbot/controllers/bots/bot7/adaptive_grid_v1.py`: when Bot7 resolves to `quote_side_mode=off` for fail-closed inactive reasons, it now calls the shared paper-order cleanup path in addition to canceling active quote executors
  - `hbot/tests/controllers/test_epp_v2_4_bot7.py`: extended inactive-state cancellation coverage to assert the paper-order cleanup hook is invoked
- Observation window: immediate post-restart failure analysis plus validation restart on `2026-03-10` using `hbot/reports/desk_snapshot/bot7/latest.json`, `hbot/data/bot7/logs/recovery/open_orders_latest.json`, `hbot/data/bot7/logs/epp_v24/bot7_a/minute.csv`, and deterministic controller unit tests after confirming executor-only cancellation did not clear the aged working buys.
- Metrics checked:
  - fills: Bot7 added one more `regime_inactive` fill before this patch took effect, increasing total fills to `149`; after the validation restart no newer fills appeared and `fill_age_s` advanced while the order leak stayed shut
  - net pnl: total fees remained at `1.881451592` with no additional post-restart fee growth in the immediate validation window, so the orphan-order leak stopped adding fresh drag
  - pnl/fill: unchanged negative expectancy historically; this pass only validates execution cleanup, not thesis profitability
  - maker ratio: still `100%` maker
  - soft-pause ratio/state: validation rows still show fail-closed `quote_side_mode=off`, now with `cancel_per_min=23` during startup cleanup and `orders_active=0`; `open_orders_latest.json` dropped to `orders_count=0` and desk snapshot `open_orders` is now empty
  - drawdown: unchanged / low; turnover hard-stop remains the active runtime clamp
- Result: `keep`
- Decision / next step: keep the paper-order fail-close hook and start the next isolated Bot7 observation window; only judge viability on fresh `probe_*` / `mean_reversion_*` activity now that stale inactive-state orders have been cleared.

## EXP-20260310-04: Bot7 flush inactive-state lingering quotes
- Date: `2026-03-10`
- Type: `code`
- Area: `bot7_mean_reversion`
- Hypothesis: Bot7 still cannot be judged on thesis-state edge while working quote orders survive into `regime_inactive` and `no_entry`; forcing active-quote cancellation whenever the lane is intentionally `off` in those inactive states should stop invalid carry-over fills and create a clean observation window.
- Changes:
  - `hbot/controllers/bots/bot7/adaptive_grid_v1.py`: extended Bot7's active-quote cancellation trigger so `quote_side_mode=off` also flushes lingering quote executors for `regime_inactive` and `no_entry`, in addition to stale-flow and expired warmup paths
  - `hbot/tests/controllers/test_epp_v2_4_bot7.py`: added regression coverage for inactive-state `off` paths that must still enqueue active-quote cancellation even when the prior quote-side mode is already `off`
- Observation window: post-analysis follow-up on `2026-03-10` using `hbot/reports/desk_snapshot/bot7/latest.json`, `hbot/data/bot7/logs/recovery/open_orders_latest.json`, `hbot/data/bot7/logs/epp_v24/bot7_a/minute.csv`, `hbot/data/bot7/logs/epp_v24/bot7_a/fills.csv`, and deterministic controller unit tests after the patch.
- Metrics checked:
  - fills: latest analyzed run had `148` total fills, with `99` under `regime_inactive`, `23` under `no_entry`, `16` under `indicator_warmup`, `9` under `trade_flow_stale`, and only `1` thesis-state `probe_long` fill
  - net pnl: analyzed total net after fees remained negative at about `-1.9078` quote, with the post-fix subwindow still negative at about `-1.6955`
  - pnl/fill: net after fees remained about `-0.0129` quote per fill, confirming inactive-state carry-over orders still dominate expectancy
  - maker ratio: `100%` maker, so the current leak remains passive-order lifecycle rather than taker escalation
  - soft-pause ratio/state: dominant non-thesis reasons remain `regime_inactive` and `no_entry`; this pass only flushes orders when Bot7 is already intentionally non-quoting
  - drawdown: runtime stopped on `daily_turnover_hard_limit`, so the immediate issue is execution churn and invalid evaluation rather than large mark-to-market loss
- Result: `inconclusive`
- Decision / next step: keep the inactive-state flush patch, restart Bot7, and only evaluate viability once `open_orders_latest.json` and desk snapshots stop showing working orders during `regime_inactive` / `no_entry` windows.

## EXP-20260310-02: Bot7 fail-closed stale flow and bounded warmup quotes
- Date: `2026-03-10`
- Type: `code+config`
- Area: `bot7_mean_reversion`
- Hypothesis: bot7's current paper evidence is contaminated because fallback quotes during `indicator_warmup` and `trade_flow_stale` generate fills before the intended absorption / probe / mean-reversion states are active; removing stale-flow quotes and limiting warmup quotes to the first bootstrap bars should isolate the true thesis for the next evaluation window.
- Changes:
  - `hbot/controllers/bots/bot7/adaptive_grid_v1.py`: added `bot7_warmup_quote_max_bars`, stopped placing fallback quotes when the reason is `trade_flow_stale`, and limited `indicator_warmup` quotes to the first bootstrap bars while tagging those quotes as excluded from viability measurement metadata
  - `hbot/data/bot7/conf/controllers/epp_v2_4_bot7_adaptive_grid_paper.yml`: pinned `bot7_warmup_quote_max_bars: 3` for the bounded Bot7 audit cycle
  - `hbot/tests/controllers/test_epp_v2_4_bot7.py`: added regression coverage for bootstrap-window warmup quotes, post-bootstrap fail-closed behavior, and no-quote behavior on stale trade flow
- Observation window: pre-change initial Bot7 audit on `2026-03-10` using `hbot/data/bot7/logs/epp_v24/bot7_a/minute.csv`, `hbot/data/bot7/logs/epp_v24/bot7_a/fills.csv`, `hbot/reports/desk_snapshot/bot7/latest.json`, `hbot/data/bot7/logs/recovery/open_orders_latest.json`, and deterministic controller unit tests after the code change.
- Metrics checked:
  - fills: `20` total fills in the audit window, with `14` under `indicator_warmup`, `4` under `trade_flow_stale`, `2` under `regime_inactive`, and `0` under `mean_reversion_*`
  - net pnl: gross realized `-0.040377204` quote and net after fees `-0.142282636` quote across the current Bot7 sample
  - pnl/fill: net after fees about `-0.0071` quote per fill in the current sample, so fallback activity is not yet viable
  - maker ratio: `100%` maker in the current sample, confirming the issue is not taker leakage but low-quality fallback maker flow
  - soft-pause ratio/state: dominant idle reasons remain `regime_inactive` and `no_entry`; this pass targets measurement isolation rather than changing shared runtime pause policy
  - drawdown: current sample remains low drawdown / low inventory, so the next risk is false-positive edge measurement rather than immediate capital damage
- Result: `inconclusive`
- Decision / next step: keep the fail-closed stale-flow change and bounded warmup window, then run one isolated Bot7 paper cycle without signal-threshold retuning; only judge Bot7 on `probe_*` / `mean_reversion_*` fills after bootstrap and reopen tuning only if thesis-state activity appears.

## EXP-20260310-03: Bot7 cancel lingering quotes on stale-flow fail-close
- Date: `2026-03-10`
- Type: `code`
- Area: `bot7_mean_reversion`
- Hypothesis: stopping new stale-flow quotes is not sufficient if previously placed quote executors remain active and keep filling under `trade_flow_stale`; actively canceling quote executors whenever Bot7 is `off` due to stale trade flow or expired warmup should close the remaining fallback-fill leak.
- Changes:
  - `hbot/controllers/bots/bot7/adaptive_grid_v1.py`: when Bot7 resolves to `quote_side_mode=off` because of `trade_flow_stale` or post-bootstrap `indicator_warmup`, it now requests `_cancel_active_quote_executors()` in addition to any side-transition cancellation
  - `hbot/tests/controllers/test_epp_v2_4_bot7.py`: added regression coverage for stale-flow and expired-warmup paths that must enqueue active-quote cancellation
- Observation window: immediate post-restart Bot7 inspection on `2026-03-10` using `hbot/reports/desk_snapshot/bot7/latest.json`, `hbot/data/bot7/logs/recovery/open_orders_latest.json`, `hbot/data/bot7/logs/epp_v24/bot7_a/minute.csv`, and `hbot/data/bot7/logs/epp_v24/bot7_a/fills.csv`.
- Metrics checked:
  - fills: new post-change fills still arrived under `trade_flow_stale`, indicating older working orders survived the earlier fail-closed patch
  - net pnl: stale-flow fills continued adding fee drag in the immediate restart window, so the isolation goal was not yet met
  - pnl/fill: no thesis-state improvement claim; this pass targets removal of invalid fallback activity
  - maker ratio: remaining leak is still maker-only, confirming the problem is lingering quote lifecycle rather than taker escalation
  - soft-pause ratio/state: latest minute rows show `alpha_policy_reason=trade_flow_stale` with `quote_side_mode=off`, so planning already fail-closes while execution cleanup lagged behind
  - drawdown: unchanged / low in the immediate window
- Result: `inconclusive`
- Decision / next step: keep the active-cancel fail-close patch, restart Bot7 again, and only continue the isolated audit once `trade_flow_stale` rows stop carrying forward old working orders and stale-flow fills stop appearing.

## EXP-20260310-01: Active paper funding settlement parity
- Date: `2026-03-10`
- Type: `code`
- Area: `paper_execution`
- Hypothesis: the active paper-exchange service already persists funding-rate metadata on orders, but without a position ledger and periodic settlement it understates perp carrying costs; adding deterministic position-aware funding settlement should improve execution realism without changing strategy decision logic.
- Changes:
  - `hbot/services/paper_exchange_service/main.py`: added a lightweight position ledger, periodic funding settlement events, funding counters in heartbeat metadata, and persisted position/funding state inside the paper-exchange state snapshot.
  - `hbot/tests/services/test_paper_exchange_service.py`: added regression coverage for long-funding debits, short-funding credits, funding cadence handling, and persisted funding state.
- Observation window: deterministic unit validation on `2026-03-10` via `PYTHONPATH=hbot python -m pytest hbot/tests/services/test_paper_exchange_service.py -q`.
- Metrics checked:
  - fills: existing fill-path tests stayed green after wiring funding settlement into immediate and resting-fill accounting state
  - net pnl: funding charge sign is now reflected in service position state as positive debit for long positive funding and negative debit (credit) for short positive funding
  - pnl/fill: unchanged directly; this pass targets carry-cost realism rather than fill-edge changes
  - maker ratio: unchanged
  - soft-pause ratio/state: unchanged
  - drawdown: not claimed from unit evidence; funding path now contributes signed carry cost into the service snapshot for downstream accounting visibility
- Result: `keep`
- Decision / next step: keep the funding settlement path and use the next active paper soak to verify the new funding events and snapshot fields show up correctly in downstream operator artifacts before treating funding drag as a promotion-gate input.

## EXP-20260308-06: Unblock bot5 neutral quoting and de-risk weak-flow bias
- Date: `2026-03-08`
- Type: `code+config`
- Area: `inventory`
- Hypothesis: bot5 is currently spending long stretches in `running` with `orders_active=0` because its dedicated controller misinterprets neutral quote-side mode `off` as "place nothing", while its weak-flow bias thresholds still push inventory targets hard enough to invite taker cleanup instead of maker-led quoting.
- Changes:
  - `hbot/controllers/bots/bot5/ift_jota_v1.py`: stopped zeroing both sides when quote-side mode is `off`; in the shared runtime, `off` means neutral two-sided quoting, not fail-closed no-trade
  - `hbot/data/bot5/conf/controllers/epp_v2_4_bot5_ift_jota_paper.yml`: aligned `total_amount_quote` / `max_total_notional_quote` with BTC paper minimum-lot reality, capped per-order notional, lengthened `time_limit`, raised weak-flow bias thresholds, reduced directional target size, and widened the low-conviction edge add-on
  - `hbot/tests/controllers/test_epp_v2_4_bot5.py`: updated regression coverage so neutral `off` mode keeps one buy and one sell quote alive under low conviction instead of collapsing projected notional to zero
- Observation window: fresh post-shared-blocker desk snapshots showed `bot5` no longer cap-paused but still `orders_active=0` with `quote_side_mode=off`, `alpha_policy_reason=biased_sell`, and residual long inventory.
- Metrics checked:
  - fills: target is restoring maker-led quote opportunities instead of only residual cleanup flow
  - net pnl: preserve bot5's positive multi-day expectancy while reducing intraday drag from idle windows and cleanup exits
  - pnl/fill: target improvement by cutting weak-conviction directional inventory pressure
  - maker ratio: keep >= current strong baseline while reducing reliance on taker exits
  - soft-pause ratio/state: target lower state burden by removing false zero-quote runtime in neutral mode
  - drawdown: keep within existing paper bounds while making sizing/caps honest
- Result: `inconclusive`
- Decision / next step: restart bot5, inspect `orders_active`, maker/taker mix, and slippage tails in the next paper window before deciding whether to narrow spreads further or relax/tighten directional flow thresholds again.

## EXP-20260308-07: Bot1 neutral expectancy clamp without size increase
- Date: `2026-03-08`
- Type: `config`
- Area: `regime`
- Hypothesis: bot1's dominant loss path is neutral participation and cleanup churn rather than outright inactivity, so widening neutral quotes and making no-trade / inventory-relief / force-taker transitions more selective should improve expectancy before any size increase is considered.
- Changes:
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: increased `take_profit` and `time_limit`, raised `position_rebalance_min_base_mult`, raised `alpha_policy_no_trade_threshold`, raised `alpha_policy_inventory_relief_threshold`, and tightened force-taker escalation thresholds
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`: widened `neutral_low_vol` spread band, slowed neutral refresh cadence, and reduced neutral fill factor so bot1 only participates when edge quality is materially better
- Observation window: pre-change dossier showed `expectancy_per_fill_quote=-0.0294`, `maker_ratio_weighted=35.1%`, `taker_expectancy_per_fill_quote=-0.0346`, `alpha_no_trade_ratio=53.7%`, and dominant negative regime expectancy in `neutral_low_vol`.
- Metrics checked:
  - fills: target lower neutral churn and fewer cleanup-style fills while `alpha_policy_state=no_trade`
  - net pnl: target reduced negative drift before any size increase
  - pnl/fill: target move both maker and taker buckets toward breakeven
  - maker ratio: target restore weighted maker ratio above `45%`
  - soft-pause ratio/state: no direct reliance on soft-pause reduction for this pass
  - drawdown: keep current low drawdown profile intact
- Result: `inconclusive`
- Decision / next step: restart bot1 and inspect the next paper window for `alpha_no_trade_ratio`, `maker_ratio`, and neutral fill expectancy before deciding whether the remaining issue is still neutral quote quality or residual cleanup timing.

## EXP-20260308-08: Bot6 degrade stale-feature hard block into warmup fallback
- Date: `2026-03-08`
- Type: `code+config`
- Area: `regime`
- Hypothesis: bot6 is non-operational because it hard-fails on sparse directional trade features and also inherits the same neutral `quote_side_mode=off` zero-quote bug that blocked bot5, so treating stale directional inputs as warmup/idle instead of a hard block and aligning its lot-constrained sizing should let it trade while preserving directional bias when the signal actually appears.
- Changes:
  - `hbot/controllers/bots/bot6/cvd_divergence_v1.py`: removed hard fail-close on stale trade features, passed a longer trade-feature freshness window, inferred directional trend from score dominance when candle trend bootstrap is unavailable, and stopped zeroing neutral `off` quote-side mode
  - `hbot/data/bot6/conf/controllers/epp_v2_4_bot6_bitget_cvd_paper.yml`: aligned total/max notional with BTC minimum-lot behavior, capped per-order notional, shortened signal windows, reduced ADX and score thresholds, added explicit trade-feature staleness tolerance, and reduced base level count to one per side
  - `hbot/tests/controllers/test_epp_v2_4_bot6.py`: updated regression coverage for neutral `off` quoting, warmup risk handling, and score-based direction fallback without candle data
- Observation window: fresh desk snapshots showed `bot6_trade_features_stale`, `orders_active=0`, `projected_total_quote=0`, and zeroed SMA/CVD fields despite healthy shared runtime plumbing.
- Metrics checked:
  - fills: target first non-zero quote activity and eventual fills before any profitability claim
  - net pnl: no near-term PnL target until quotes/signals exist
  - pnl/fill: not meaningful until bot6 resumes trading
  - maker ratio: target non-zero maker participation once quotes appear
  - soft-pause ratio/state: target removal of `bot6_trade_features_stale` as the dominant runtime blocker
  - drawdown: keep current flat/no-position drawdown unchanged during bring-up
- Result: `inconclusive`
- Decision / next step: restart bot6 and inspect the next minute window for `orders_active`, non-zero `bot6_*` score telemetry, and whether the runtime now sits in `running` rather than `soft_pause`.

## EXP-20260309-13: Bot7 restart verification after telemetry fix
- Date: `2026-03-09`
- Type: `runtime_validation`
- Area: `bot7_post_restart_verification`
- Hypothesis: after restarting bot7 on the updated code, the live minute and desk-snapshot artifacts should finally export bot7-native reasons (`indicator_warmup`, `regime_inactive`, `no_entry`, `probe_*`) and `quote_side_reason` should reflect the bot7 lane rather than the shared `regime` fallback. If execution persistence is still broken, that should remain visible separately in `open_orders` and PaperDesk evidence.
- Changes:
  - runtime only: restarted the `bot7` container after the `EXP-20260309-12` code/config changes
- Observation window: immediate post-restart check on `2026-03-09` using `hbot/reports/desk_snapshot/bot7/latest.json`, `hbot/data/bot7/logs/epp_v24/bot7_a/minute.csv`, `hbot/data/bot7/logs/recovery/open_orders_latest.json`, and `hbot/data/bot7/logs/epp_v24/bot7_a/paper_desk_v2.json`.
- Metrics checked:
  - telemetry consistency: latest minute/snapshot now agree on `alpha_policy_reason = indicator_warmup`, `bot7_gate_reason = indicator_warmup`, `bot7_signal_reason = indicator_warmup`, and `quote_side_reason = bot7_indicator_warmup`
  - warmup quoting: latest minute rows show `projected_total_quote` around `132` with `orders_active = 2` during startup warmup
  - execution persistence: `open_orders_latest.json` still reports `orders_count = 0`, desk snapshot `open_orders` remains empty, and `paper_desk_v2.json` still shows `order_counter = 0`
  - regime state after warmup restart window: current regime returned to `neutral_low_vol`, so the telemetry fix can now be trusted for the next neutral-vs-trend activation comparison
- Result: `inconclusive`
- Decision / next step: keep the telemetry/runtime fixes from `EXP-20260309-12`; do not retune bot7 entry logic further until the paper-execution persistence gap is understood, because the lane now shows startup quote intent correctly but still does not retain tracked open orders.

## EXP-20260309-12: Bot7 tick-consistent telemetry and neutral fallback follow-up
- Date: `2026-03-09`
- Type: `code+config`
- Area: `bot7_telemetry_and_regime_gate`
- Hypothesis: bot7's exported minute/snapshot state is currently inconsistent with its in-memory strategy state because the lane recomputes `_bot7_state` twice per tick and appends bot7-specific telemetry after the base runtime already logs the minute row. Fixing that inconsistency, while only nudging the neutral-regime ADX fallback gate upward, should make operator evidence trustworthy and slightly increase safe neutral-regime activation without enabling trend-chasing in `up`/`down` regimes.
- Changes:
  - `hbot/controllers/epp_v2_4.py`: added a generic pre-log processed-data hook so strategy lanes can inject telemetry before the base runtime writes the minute row.
  - `hbot/controllers/bots/bot7/adaptive_grid_v1.py`: stopped recomputing `_bot7_state` inside `_compute_levels_and_sizing`, invoked bot7's own `_resolve_quote_side_mode` during sizing so `quote_side_reason` is set from bot7 state, and moved bot7 telemetry injection into the pre-log hook path.
  - `hbot/data/bot7/conf/controllers/epp_v2_4_bot7_adaptive_grid_paper.yml`: raised `bot7_adx_neutral_fallback_below` from `28` to `30` so only neutral-regime activation is modestly relaxed.
  - `hbot/tests/controllers/test_epp_v2_4_bot7.py`: added regression coverage for `probe_short`, `mean_reversion_short`, same-tick funding-scale reuse, quote-side reason propagation, and bot7 processed-data emission.
- Observation window: pre-change audit of `2026-03-09` using `hbot/data/bot7/logs/epp_v24/bot7_a/minute.csv`, `hbot/reports/desk_snapshot/bot7/latest.json`, `hbot/data/bot7/logs/recovery/open_orders_latest.json`, `hbot/data/bot7/logs/epp_v24/bot7_a/paper_desk_v2.json`, and `hbot/data/bot7/logs/logs_v2_epp_v2_4_bot7_adaptive_grid_paper.log`.
- Metrics checked:
  - reason mix: `1336` minute rows with `893 regime_inactive`, `323 no_entry`, `107 indicator_warmup`, `7 probe_short`, and `6 probe_long`
  - regime mix: `514 neutral_low_vol`, `389 down`, `348 up`, `85 high_vol_shock`
  - regime-inactive breakdown: `225 neutral_low_vol`, `325 down`, `270 up`, `74 high_vol_shock`, showing the dominant idle state is still mostly trend-regime lockout rather than neutral windows
  - execution persistence: `open_orders_latest.json` had `orders_count = 0`, `paper_desk_v2.json` had `order_counter = 0`, and repeated `PAPER_ENGINE_PROBE` log lines still showed `open=0 inflight=0`
  - telemetry consistency: latest desk snapshot showed `alpha_policy_reason = regime_inactive` while `bot7_gate_reason = inactive`, `bot7_signal_reason = inactive`, and `quote_side_reason = regime`, confirming the pre-fix export mismatch
- Result: `inconclusive`
- Decision / next step: keep the telemetry fix and the neutral-only ADX fallback nudge in code, restart bot7, then verify that minute/snapshot artifacts now show bot7-native reasons and re-check whether `neutral_low_vol` `regime_inactive` rows convert into safe `probe_*` activity with persistent `open_orders` before touching probe/band thresholds again.

## EXP-20260308-10: Bot7 probe path and tighter passive spacing
- Date: `2026-03-08`
- Type: `code+config`
- Area: `bot7_mean_reversion`
- Hypothesis: bot7 is now operationally healthy, but its alpha stack is still too selective for paper execution because neutral-regime activation is too strict, full entry requires perfect tape confirmation, and passive quote spacing is too wide for the queue-aware fill model. Adding a reduced-risk one-sided probe path plus narrower quote spacing should convert some `regime_inactive` / `no_entry` rows into measurable maker participation without turning the strategy into a generic always-on market maker.
- Changes:
  - `hbot/controllers/bots/bot7/adaptive_grid_v1.py`: added softer neutral-regime ADX fallback, separated band-touch tolerance from quote spacing, added depth-imbalance reversal support, and introduced reduced-risk `probe_long` / `probe_short` one-sided entries that cap grid legs and size below full mean-reversion entries.
  - `hbot/data/bot7/conf/controllers/epp_v2_4_bot7_adaptive_grid_paper.yml`: relaxed full-signal RSI / ADX thresholds slightly, added explicit probe thresholds, lowered the grid-spacing floor, and enabled probe sizing controls in paper config.
  - `hbot/tests/controllers/test_epp_v2_4_bot7.py`: extended the bot7 unit surface with probe-entry and probe-grid regression coverage.
- Observation window: pre-change audit of `2026-03-08` paper runtime using `hbot/data/bot7/logs/epp_v24/bot7_a/minute.csv` and `hbot/reports/desk_snapshot/bot7/latest.json`.
- Metrics checked:
  - state mix: `559` minute rows with `347 regime_inactive`, `129 no_entry`, `83 indicator_warmup`
  - activity mix: `bot7_signal_side=off` on all sampled minute rows, with only `35` rows showing `orders_active > 0` and those concentrated in startup warmup
  - fills / pnl: `7` fills, `0` realized pnl, and flat end-state inventory/equity in the latest desk snapshot
  - fill mechanics: queue-aware paper fill model remained enabled, so passive spacing had to be tightened rather than assuming guaranteed touch fills
- Result: `inconclusive`
- Decision / next step: restart bot7, then evaluate whether probe entries produce non-startup `orders_active`, non-zero maker participation, and better fill frequency; only after that compare `probe_*` versus `mean_reversion_*` reason mix and decide whether to keep, tighten, or revert the new probe path.

## EXP-20260308-11: Bot7 startup warmup diagnostics and ATR fallback
- Date: `2026-03-08`
- Type: `code+config`
- Area: `bot7_startup_warmup`
- Hypothesis: bot7 restart warmup is overstated because `ATR` is treated as a hard prerequisite even though it only controls spacing, and because the current startup periods still require too many completed minute bars before the first eligible strategy evaluation. Making `ATR` non-blocking, exposing warmup diagnostics, and shortening startup lookbacks should let bot7 leave `indicator_warmup` faster after restart without removing the core Bollinger/RSI/ADX guardrails.
- Changes:
  - `hbot/controllers/bots/bot7/adaptive_grid_v1.py`: added bot7-local warmup diagnostics (`indicator_ready`, `indicator_missing`, `price_buffer_bars`), made `ATR` optional for readiness, and used grid-floor spacing when `ATR` is still warming up.
  - `hbot/data/bot7/conf/controllers/epp_v2_4_bot7_adaptive_grid_paper.yml`: reduced startup lookbacks further (`bot7_bb_period: 10`, `bot7_adx_period: 5`) and pinned `atr_period: 7` for faster spacing readiness.
  - `hbot/tests/controllers/test_epp_v2_4_bot7.py`: added regression coverage proving bot7 can still produce a valid signal when `ATR` is missing but the core indicators are ready.
- Observation window: live restart soak on `2026-03-08` using `hbot/data/bot7/logs/epp_v24/bot7_a/minute.csv` plus `docker logs bot7`.
- Metrics checked:
  - warmup dwell: post-restart rows stayed in `indicator_warmup` from `13:56:50` through `14:05:00`, then cleared to `regime_inactive` by `14:06:01` instead of remaining indefinitely in bootstrap
  - startup quoting: warmup rows held `orders_active=2` with `projected_total_quote` around `134`
  - first directional evidence: live minute telemetry showed at least one `probe_short` row at `13:51:01` with `orders_active=1` and `projected_total_quote=67.11225`
  - execution evidence: order placements continued to appear in logs, but paper-engine probes still reported `open=0 inflight=0`, so fill persistence remains an execution-quality follow-up rather than a warmup issue
- Result: `keep`
- Decision / next step: keep the warmup fix, then focus the next bot7 pass on converting post-warmup `regime_inactive` into more frequent `probe_*` / `mean_reversion_*` opportunities and on understanding why paper-engine probes still show no persistent open orders after `place_order_done`.

## EXP-20260308-09: Bot7 warmup quotes instead of indicator hard-stop
- Date: `2026-03-08`
- Type: `code+config`
- Area: `regime`
- Hypothesis: bot7 is not trading because indicator bootstrap and trade-tape freshness are treated as a hard block, so giving it a small two-sided warmup quote mode plus faster bootstrap windows should let the passive grid lane come alive before the full mean-reversion signal is ready.
- Changes:
  - `hbot/controllers/bots/bot7/adaptive_grid_v1.py`: removed hard fail-close semantics from warmup/stale gate states and added a two-sided warmup quote path that uses the configured grid floor while indicators or trade flow are still bootstrapping
  - `hbot/data/bot7/conf/controllers/epp_v2_4_bot7_adaptive_grid_paper.yml`: aligned total/max notional with BTC minimum-lot reality, capped per-order notional, shortened bootstrap windows (`BB`, `RSI`, `ADX`, trade window, delta-trap window), relaxed trade-flow staleness tolerance, and enabled one warmup quote level per side
  - `hbot/tests/controllers/test_epp_v2_4_bot7.py`: added regression coverage for warmup two-sided quotes and updated risk handling expectations so stale trade flow no longer acts as a bot-local hard stop
- Observation window: fresh desk snapshots showed `bot7_indicator_warmup`, `orders_active=0`, `projected_total_quote=0`, and no open orders despite healthy shared runtime fields.
- Metrics checked:
  - fills: target first live quotes and eventual passive fills before any alpha tuning claim
  - net pnl: not yet a target until the bot exits pure warmup idleness
  - pnl/fill: not yet meaningful until fills resume
  - maker ratio: target non-zero maker participation after warmup quotes appear
  - soft-pause ratio/state: target removal of `bot7_indicator_warmup` as the dominant runtime blocker
  - drawdown: keep zero-position drawdown flat during bring-up
- Result: `inconclusive`
- Decision / next step: restart bot7 and inspect whether the next minute window shows `running` with `orders_active > 0`; only after that should the actual absorption / delta-trap thresholds be tuned.

## EXP-20260308-05: Make shared edge gate strategy-opt-in
- Date: `2026-03-08`
- Type: `code+config`
- Area: `risk`
- Hypothesis: dedicated non-MM strategy lanes should keep shared runtime safety checks, but they should not inherit the shared net-edge soft-pause gate when edge is not part of the strategy-local validity test.
- Changes:
  - `hbot/controllers/epp_v2_4.py`: added `shared_edge_gate_enabled` and bypassed/reset shared edge-gate hysteresis when a strategy opts out
  - `hbot/controllers/risk_evaluator.py`: added `reset_edge_gate()` so opt-out strategies clear stale edge-block state cleanly
  - `hbot/controllers/bots/bot1/baseline_v1.py`: made bot1's dedicated baseline lane explicitly keep shared edge gating enabled
  - `hbot/controllers/bots/bot5/ift_jota_v1.py`, `hbot/controllers/bots/bot6/cvd_divergence_v1.py`, `hbot/controllers/bots/bot7/adaptive_grid_v1.py`: defaulted dedicated non-edge strategies to `shared_edge_gate_enabled=False`
  - `hbot/data/bot5/conf/controllers/epp_v2_4_bot5_ift_jota_paper.yml`, `hbot/data/bot6/conf/controllers/epp_v2_4_bot6_bitget_cvd_paper.yml`, `hbot/data/bot7/conf/controllers/epp_v2_4_bot7_adaptive_grid_paper.yml`: made the edge-gate opt-out explicit in live config surface
  - `hbot/tests/controllers/test_epp_v2_4_core.py`, `hbot/tests/controllers/test_epp_v2_4_bot1.py`, `hbot/tests/controllers/test_epp_v2_4_bot5.py`, `hbot/tests/controllers/test_epp_v2_4_bot6.py`, `hbot/tests/controllers/test_epp_v2_4_bot7.py`: added regression coverage for the new gate taxonomy
- Observation window: code-path audit after dedicated-bot split plus targeted unit validation.
- Metrics checked:
  - fills: no direct fill-model change; expected only to remove unintended shared edge pauses on dedicated strategy bots
  - net pnl: expected indirect improvement only if bot5/bot6/bot7 were previously being idled by foreign edge gating
  - pnl/fill: unchanged directly
  - maker ratio: unchanged directly for bot1; dedicated bots may see higher activity only when their own gates remain open
  - soft-pause ratio/state: expected lower `soft_pause_edge` incidence on bot5/bot6/bot7 while keeping bot1/shared MM behavior intact
  - drawdown: no direct hard-risk threshold change
- Result: `keep`
- Decision / next step: keep shared runtime safety gates universal, but treat edge gating as a strategy capability; validate in the next paper observation window that bot7 is no longer blocked solely by shared `net_edge`.

## EXP-20260308-04: Extend identity preflight to control/audit streams
- Date: `2026-03-08`
- Type: `code`
- Area: `paper_execution`
- Hypothesis: producer identity preflight should be uniform across bot-control and governance events so malformed `execution_intent`, `strategy_signal`, or `audit` payloads cannot silently enter the event plane.
- Changes:
  - `hbot/services/contracts/event_identity.py`: added required identity rules for `execution_intent`, `strategy_signal`, and `audit`
  - `hbot/services/hb_bridge/redis_client.py`: added centralized producer preflight in `xadd()` using `validate_event_identity`
  - `hbot/controllers/paper_engine_v2/signal_consumer.py`: added preflight before publishing HARD_STOP-derived `execution_intent`
  - `hbot/controllers/paper_engine_v2/hb_bridge.py`: added preflight before publishing sync hard-stop `audit` event
  - `hbot/tests/services/test_event_identity.py`, `hbot/tests/services/test_hb_event_publisher.py`, `hbot/tests/services/test_event_store.py`: added/updated regression coverage
- Observation window: unit and service contract tests after implementation.
- Metrics checked:
  - fills: no direct fill-path logic changes
  - net pnl: no direct strategy pricing change
  - pnl/fill: no direct strategy pricing change
  - maker ratio: no direct quote-policy change
  - soft-pause ratio/state: no direct threshold change; expected safer control-plane behavior under malformed events
  - drawdown: no direct risk-limit change
- Result: `keep`
- Decision / next step: keep centralized preflight as the default producer path and continue adding identity rules as new bot-scoped event types are introduced.

## EXP-20260308-03: Remove blocking paper-event read from tick path
- Date: `2026-03-08`
- Type: `code`
- Area: `paper_execution`
- Hypothesis: paper bots are marked stale because `on_tick()` calls `drive_desk_tick()`, which calls `_consume_paper_exchange_events()`, and that function uses `xread(..., block=0)`. In Redis, `BLOCK 0` means wait forever, so tick cadence can be gated by event-stream traffic instead of the 1s clock.
- Changes:
  - `hbot/controllers/paper_engine_v2/hb_bridge.py`: changed paper-exchange event read from `block=0` (indefinite block) to `block=1` (near non-blocking) and documented the Redis semantics in code comments
  - `hbot/tests/controllers/test_hb_bridge_signal_routing.py`: updated assertions to validate `xread(..., block=1)` in consume-path tests
- Observation window: live container log review (`bot1`, `bot6`, `bot4`) plus code-path audit of `v2_with_controllers.on_tick()` -> `drive_desk_tick()` -> `_consume_paper_exchange_events()` and targeted controller tests.
- Metrics checked:
  - fills: no direct strategy logic change; expected unchanged fill model
  - net pnl: no direct pricing/alpha change
  - pnl/fill: no direct pricing/alpha change
  - maker ratio: no direct quoting-logic change
  - soft-pause ratio/state: expected indirect improvement only if stale-induced cadence pauses disappear
  - drawdown: no direct risk-threshold change
  - stream freshness: expected improvement (market snapshots no longer blocked by paper-event stream idle periods)
- Result: `keep`
- Decision / next step: restart paper bots/services and validate `stream_age_ms` stays under stale threshold in `realtime_ui_api`; if needed, tune stale threshold only after post-fix cadence data is collected.

## EXP-20260308-02: Isolate paper-exchange event ingestion by instance
- Date: `2026-03-08`
- Type: `code`
- Area: `paper_execution`
- Hypothesis: multiple bots sharing the same connector/trading pair were consuming the same paper-exchange event stream without instance filtering, causing bot1 to ingest foreign `pe-*` fills and corrupt strategy accounting/performance attribution.
- Changes:
  - `hbot/controllers/paper_engine_v2/hb_bridge.py`: in `_consume_paper_exchange_events()`, added local-instance gating for non-sync events so only events matching the local controller `instance_name` are processed
  - `hbot/tests/controllers/test_hb_bridge_signal_routing.py`: added regression `test_submit_processed_filled_for_other_instance_is_ignored`
- Observation window: identical `pe-*` order IDs were present simultaneously in `fills.csv` across `bot1`, `bot2`, `bot5`, `bot6`, and `bot7`, confirming cross-instance fill leakage.
- Metrics checked:
  - fills: expected drop in foreign-fill contamination for bot1
  - net pnl: expected to become less noisy/more attributable to bot1 orders
  - pnl/fill: expected to reflect only local strategy execution
  - maker ratio: expected to stabilize after contaminated history ages out
  - soft-pause ratio/state: expected to better align with local fills only
  - drawdown: expected to reflect local inventory path only
- Result: `inconclusive`
- Decision / next step: run fresh post-fix observation window and recompute dossier deltas on uncontaminated fill history.

## EXP-20260308-01: Maker/taker attribution hardening for paper bridge fills
- Date: `2026-03-08`
- Type: `code`
- Area: `paper_execution`
- Hypothesis: paper-bridge fills can arrive without `trade_fee.is_maker`, causing fallback price-vs-mid heuristics to misclassify fills (especially bridge `pe-*` sells), which corrupts maker ratio, taker expectancy, and governor/risk telemetry.
- Changes:
  - `hbot/controllers/epp_v2_4.py`: in `did_fill_order()`, added maker-flag resolution precedence: `trade_fee.is_maker` -> `event.is_maker` -> fee-rate proximity inference (`maker_fee_pct` vs `taker_fee_pct`) -> legacy price-vs-mid heuristic
  - `hbot/controllers/paper_engine_v2/hb_event_fire.py`: attached `is_maker` directly on emitted HB fill events so controller classification can consume explicit bridge truth
  - `hbot/tests/controllers/test_epp_v2_4_core.py`: added regressions for (a) event-level maker flag fallback and (b) fee-rate inference when explicit flags are missing
- Observation window: audit of recent `fills.csv` showed heavy `pe-*` flow with maker-like fee rates but `is_maker=False`, driving distorted maker/taker breakdown in dossier metrics.
- Metrics checked:
  - fills: no change in raw fill count expected from this patch
  - net pnl: unchanged directly (classification fix, not execution-price fix)
  - pnl/fill: unchanged directly
  - maker ratio: expected to improve in post-fix window as maker-like fills are no longer bucketed as taker
  - soft-pause ratio/state: unchanged directly
  - drawdown: unchanged directly
- Result: `inconclusive`
- Decision / next step: collect post-restart sample and verify that new bridge fills carry correct `is_maker` classification before comparing expectancy deltas.

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

## EXP-20260306-18: Give bot7 its own strategy gate profile
- Date: `2026-03-06`
- Type: `code+config`
- Area: `bot_specific_gating`
- Hypothesis: bot7 should use its own mean-reversion / tape-freshness gate semantics rather than inheriting shared alpha-policy naming and behavior from the base runtime. Making bot7 explicitly disable shared alpha/selective soft-pause layers and expose bot7-specific gate reasons should improve separation of concerns and reduce operator confusion.
- Changes:
  - `hbot/controllers/bots/bot7/adaptive_grid_v1.py`: disable inherited alpha/selective/adverse/slippage gate defaults in the bot7 config subclass.
  - `hbot/controllers/bots/bot7/adaptive_grid_v1.py`: add bot7-specific gate metrics, publish `bot7_strategy_gate` instead of shared alpha-policy semantics, and append fail-closed reasons such as `bot7_trade_flow_stale` / `bot7_indicator_warmup`.
  - `hbot/data/bot7/conf/controllers/epp_v2_4_bot7_adaptive_grid_paper.yml`: explicitly keep shared bot1-style alpha/selective soft-pause layers disabled for bot7.
  - `hbot/tests/controllers/test_epp_v2_4_bot7.py`: add regression coverage for bot7 gate defaults, bot7 strategy-gate reporting, and bot7-specific stale-trade risk reasons.
- Observation window: code-path isolation pass only; no new paper runtime window yet
- Metrics checked:
  - boundary check: bot7 now reports bot7-specific gate state/reasons from its own strategy module
  - inheritance check: shared runtime still owns platform/risk plumbing, but bot7 no longer relies on shared alpha-policy gate semantics
  - validation: targeted compile + bot7/bot1 controller tests in same task
- Result: `keep`
- Decision / next step: if additional bots need their own gate families, follow the same pattern: explicit bot-local config defaults plus bot-local gate-state reporting layered over shared runtime safety checks.

## EXP-20260306-19: Standardize bot-local gate profiles across dedicated strategy bots
- Date: `2026-03-06`
- Type: `architecture`
- Area: `all_bot_gate_separation`
- Hypothesis: every dedicated strategy bot should own its own strategy gate semantics, while shared-controller bots should keep the shared base runtime gate behavior. Standardizing this split across bot5/bot6/bot7 reduces cross-bot leakage and makes operator diagnostics strategy-specific.
- Changes:
  - `hbot/controllers/bots/bot5/ift_jota_v1.py`: disable inherited shared trade-quality gate defaults, expose `bot5_strategy_gate`, append bot5-specific fail-closed reasons, and keep directional quote-mode decisions inside the bot5 controller.
  - `hbot/controllers/bots/bot6/cvd_divergence_v1.py`: disable inherited shared trade-quality gate defaults, expose `bot6_strategy_gate`, append bot6-specific stale-feature fail-closed reasons, and keep directional quote-mode decisions inside the bot6 controller.
  - `hbot/controllers/bots/bot7/adaptive_grid_v1.py`: keep bot7-local gate profile introduced in the prior step.
  - `hbot/data/bot5/conf/controllers/epp_v2_4_bot5_ift_jota_paper.yml`, `hbot/data/bot6/conf/controllers/epp_v2_4_bot6_bitget_cvd_paper.yml`, `hbot/data/bot7/conf/controllers/epp_v2_4_bot7_adaptive_grid_paper.yml`: explicitly disable shared bot1-style alpha/selective soft-pause layers.
  - `hbot/tests/controllers/test_epp_v2_4_bot5.py`, `hbot/tests/controllers/test_epp_v2_4_bot6.py`, `hbot/tests/controllers/test_epp_v2_4_bot7.py`: add regression coverage for bot-local gate defaults and bot-specific fail-closed reasons.
- Observation window: code-path isolation pass only; no new multi-hour runtime observation yet
- Metrics checked:
  - boundary check: dedicated strategy bots now emit bot-local gate names/reasons instead of shared alpha-policy semantics
  - scope check: shared-controller bots remain on shared runtime gates and were not moved onto bot-local strategy layers
  - validation: `python -m py_compile` passed for bot5/bot6/bot7 controllers; targeted pytest across bot5/bot6/bot7 plus core controller tests passed
- Result: `keep`
- Decision / next step: preserve this split going forward: new strategy bots get explicit bot-local gate profiles in their dedicated controller module; only truly shared safety/runtime gates stay in the shared base controller.

## EXP-20260306-20: Split bot1 into a dedicated lane and normalize dedicated-bot telemetry
- Date: `2026-03-06`
- Type: `architecture+telemetry`
- Area: `bot1_split_and_telemetry`
- Hypothesis: bot1 should stop pointing directly at the shared `epp_v2_4` controller alias, and dedicated strategy bots should emit a consistent gate/signal telemetry family so operator tooling does not depend on bot-specific ad hoc names.
- Changes:
  - `hbot/controllers/bots/bot1/baseline_v1.py`: add dedicated bot1 baseline controller/config wrapper with bot1-local gate telemetry derived from the existing shared alpha policy behavior.
  - `hbot/controllers/epp_v2_4_bot1.py` and `hbot/controllers/market_making/epp_v2_4_bot1.py`: add bot1 compatibility aliases/shims.
  - `hbot/data/bot1/conf/controllers/*.yml`: switch bot1-owned controller configs from `epp_v2_4` to `epp_v2_4_bot1`.
  - `hbot/controllers/bots/bot5/ift_jota_v1.py`, `hbot/controllers/bots/bot6/cvd_divergence_v1.py`, `hbot/controllers/bots/bot7/adaptive_grid_v1.py`: standardize dedicated-bot telemetry on `botX_gate_state`, `botX_gate_reason`, `botX_signal_side`, `botX_signal_reason`, and `botX_signal_score` while keeping existing bot-specific aliases where useful.
  - `hbot/controllers/tick_emitter.py`, `hbot/controllers/epp_logging.py`, `hbot/services/bot_metrics_exporter.py`: extend minute-log/export surfaces for the standardized dedicated-bot signal-score family.
  - `hbot/tests/controllers/test_epp_v2_4_bot1.py` plus existing bot5/bot6/bot7/exporter tests: add targeted validation for bot1 split and standardized telemetry.
- Observation window: code-path isolation and telemetry-schema validation only; no new runtime paper soak claimed
- Metrics checked:
  - boundary check: bot1 now resolves through a dedicated bot1 controller/module rather than the shared `epp_v2_4` controller name
  - telemetry check: dedicated bots now share a consistent gate/signal naming family in processed state and minute/export surfaces
  - validation: targeted `py_compile` passed; targeted pytest for bot1/bot5/bot6/bot7/core controller coverage and bot metrics exporter passed
- Result: `keep`
- Decision / next step: future dedicated strategy bots should start from this pattern immediately: bot-local controller module, bot-local gate telemetry, and compatibility alias only as a thin wrapper.

## EXP-20260308-01: Extract neutral runtime kernel behind shared MM adapter
- Date: `2026-03-08`
- Type: `architecture+runtime`
- Area: `neutral_runtime_kernel`
- Hypothesis: extracting neutral runtime contracts for compatibility surface, data context, risk decisions, and execution plans behind the existing shared market-making behavior should reduce hidden coupling without breaking external streams, artifacts, or bot7 behavior.
- Changes:
  - `hbot/controllers/runtime/contracts.py`, `hbot/controllers/runtime/core.py`, `hbot/controllers/runtime/data_context.py`, `hbot/controllers/runtime/risk_context.py`, `hbot/controllers/runtime/execution_context.py`: add neutral runtime kernel contracts and compatibility-surface helpers.
  - `hbot/controllers/runtime/market_making_core.py`: add explicit market-making family adapter for quote-ladder execution behavior.
  - `hbot/controllers/shared_mm_v24.py`: route runtime compatibility state, execution planning, and executor-family behavior through the new kernel/adapter split while preserving v1 telemetry and artifact identity.
  - `hbot/controllers/bots/bot7/adaptive_grid_v1.py`: move bot7 onto the new runtime execution-plan hook while keeping legacy compatibility wrappers and processed-data fields.
  - `hbot/tests/controllers/test_runtime_core.py`, `hbot/tests/controllers/test_epp_v2_4_bot7.py`: add coverage for compatibility-surface rules and bot7 execution-plan parity.
- Observation window: code-path parity and boundary validation only; no new paper run claimed
- Metrics checked:
  - compatibility surface: legacy `epp_*` controllers keep `epp_v24` artifact namespace, `epp` daily-state prefix, and `hb.epp_v2_4` telemetry producer prefix
  - boundary checks: strategy-isolation and market-making shim contract tests passed with `PYTHONPATH=hbot`
  - code validity: targeted `py_compile` passed for runtime and bot7 modules
- Result: `keep`
- Decision / next step: keep external v1 streams and `controller_id` stable while continuing migration; add broader parity and service/regression coverage before moving bot5/bot6 or changing downstream consumers.

## EXP-20260309-01: Restore bot7 active-mode order visibility and service-side shared fill matching
- Date: `2026-03-09`
- Type: `code+config`
- Area: `paper_execution`
- Hypothesis: bot7’s missing open-order evidence is not a strategy issue but an execution-read-model gap: active-mode service orders are being accepted, yet `_collect_open_orders_snapshot` ignores `_paper_exchange_runtime_orders`, while the paper exchange service also fails to match shared `instance_name=""` market snapshots against bot-scoped resting orders.
- Changes:
  - `hbot/controllers/paper_engine_v2/hb_bridge.py`: canonicalize controller-route resolution for `_paper_trade` connector aliases, reuse canonical bridge lookup in patched buy/sell/cancel delegation, and hydrate runtime open orders from the service state snapshot after `sync_state` confirmation.
  - `hbot/scripts/shared/v2_with_controllers.py`: include active-mode `_paper_exchange_runtime_orders` in `open_orders_latest.json` generation and expose `active_runtime_open` in `PAPER_ENGINE_PROBE` logs.
  - `hbot/services/paper_exchange_service/main.py`: canonicalize `*_paper_trade` connector names on service ingest/command handling and treat `snapshot.instance_name=""` as a wildcard when matching resting orders for fills.
  - `hbot/data/bot7/conf/controllers/epp_v2_4_bot7_adaptive_grid_paper.yml`: switch `position_mode` from `HEDGE` to `ONEWAY` so bot7 active-mode orders align with the one-way directional execution path used by the other dedicated bots.
  - `hbot/tests/controllers/test_hb_bridge_event_isolation.py`, `hbot/tests/controllers/test_hb_event_fire.py`, `hbot/tests/services/test_paper_exchange_service.py`, `hbot/tests/scripts/test_v2_with_controllers_open_orders.py`: add regression coverage for bridge connector canonicalization, sync-time runtime hydration, SELL-side fill dispatch, service connector normalization, shared-snapshot fills, and active-mode open-order visibility.
- Observation window: artifact/cursor/service regression pass only; no fresh multi-minute bot7 soak claimed in this task.
- Metrics checked:
  - fills: shared market snapshots now remain eligible to fill bot-scoped resting active-mode orders
  - open order visibility: active runtime orders are emitted into `open_orders_latest.json` and visible to downstream desk snapshots
  - routing correctness: `_paper_trade` connector aliases resolve to the registered bridge/controller path instead of falling through to `original_buy`
  - validation: `python -m py_compile` passed for `hb_bridge.py`, `main.py`, `v2_with_controllers.py`, and `epp_v2_4.py`; targeted pytest plus full non-integration pytest passed
- Result: `keep`
- Decision / next step: restart bot7 and verify that `open_orders_latest.json` and the desk snapshot now surface the same active-mode orders already present in `paper_exchange_state_snapshot_latest.json`; if stale pre-restart service orders remain, confirm the reconciliation path cleans them up on the next sync cycle.
