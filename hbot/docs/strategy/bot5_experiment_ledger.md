# Bot5 Experiment Ledger

## Purpose
This ledger is the bot5-specific research trail for controller changes, config experiments, and performance reads.

Use it to:
- keep `bot5` analysis separate from shared `latest` artifacts
- record every bot5 experiment before and after the change
- preserve the evidence bundle used for each decision
- avoid repeating failed bot5 hypotheses

## Bot5 Evidence Bundle
- Runtime config: `hbot/data/bot5/conf/controllers/epp_v2_4_bot5_ift_jota_paper.yml`
- Script config: `hbot/data/bot5/conf/scripts/v2_epp_v2_4_bot5_ift_jota_paper.yml`
- Minute log: `hbot/data/bot5/logs/epp_v24/bot5_a/minute.csv`
- Fills log: `hbot/data/bot5/logs/epp_v24/bot5_a/fills.csv`
- Daily state: `hbot/data/bot5/logs/epp_v24/bot5_a/daily_state_bitget_perpetual_paper.json`
- Paper engine state: `hbot/data/bot5/logs/epp_v24/bot5_a/paper_desk_v2.json`
- Recovery orders: `hbot/data/bot5/logs/recovery/open_orders_latest.json`
- Desk snapshot: `hbot/reports/desk_snapshot/bot5/latest.json`
- Baseline dossier: `hbot/reports/analysis/bot5_performance_dossier_latest.json`
- Baseline dossier markdown: `hbot/reports/analysis/bot5_performance_dossier_latest.md`
- Edge report: `hbot/reports/analysis/bot5_edge_report_latest.json`

## Notes
- `bot5` does produce `minute.csv`; the earlier discovery issue came from filename-based search, not a logging failure.
- Treat shared/global promotion artifacts as context only unless a bot5-specific copy is generated in the same experiment cycle.
- When comparing pre/post bot5 changes, use the same artifact set and observation window.

## Entry Template
```markdown
## BOT5-EXP-YYYYMMDD-XX: Short title
- Date:
- Type: `config` | `code` | `config+code` | `analysis`
- Hypothesis:
- Changes:
  - `path`: summary
- Observation window:
- Metrics checked:
  - total net pnl:
  - expectancy per fill:
  - rolling expectancy ci:
  - maker ratio:
  - inventory drift:
  - drawdown:
- Evidence:
  - `path`
- Result: `keep` | `revert` | `inconclusive`
- Decision / next step:
```

## Baseline
- Controller lane: `epp_v2_4_bot5`
- Pair: `BTC-USDT`
- Mode: `paper`
- Intent: bot5-only tuning with reusable shared modules

## Ledger
## BOT5-EXP-20260307-01: Bot5 isolated baseline and controller split
- Date: `2026-03-07`
- Type: `code+analysis`
- Hypothesis: bot5 needs an isolated controller lane and bot5-only artifacts before any tuning decision can be trusted.
- Changes:
  - `hbot/controllers/epp_v2_4_bot5.py`: added a thin bot5-specific controller/config wrapper over the shared EPP implementation
  - `hbot/controllers/market_making/epp_v2_4_bot5.py`: added market-making shim for bot5 controller resolution
  - `hbot/data/bot5/conf/controllers/epp_v2_4_bot5_ift_jota_paper.yml`: repointed `controller_name` to `epp_v2_4_bot5`
  - `hbot/scripts/analysis/performance_dossier.py`: added custom output stem support so bot5 dossiers can be saved without overwriting shared artifacts
  - `hbot/scripts/analysis/edge_report.py`: added custom output path support for bot5-specific edge reports
- Observation window: historical bot5 paper data currently present in `minute.csv` / `fills.csv` through `2026-03-06T17:11Z`
- Metrics checked:
  - total net pnl: dossier `+3.5624` quote across 3 included days
  - expectancy per fill: dossier `+0.002358` quote, rolling 300-fill CI upper bound `+0.006546`
  - rolling expectancy ci: dossier gate `PASS`, but near-zero lower bound `-0.000072`
  - maker ratio: weighted maker ratio `85.70%`
  - inventory drift: desk snapshot base exposure around `8.57%` of equity with residual position left open
  - drawdown: dossier max drawdown `1.67%`
  - edge decomposition: edge report verdict `NEGATIVE_EDGE`, net edge total `-37.6338` quote, average net edge `-18.55 bps`
- Evidence:
  - `hbot/reports/analysis/bot5_performance_dossier_latest.json`
  - `hbot/reports/analysis/bot5_performance_dossier_latest.md`
  - `hbot/reports/analysis/bot5_edge_report_latest.json`
  - `hbot/reports/desk_snapshot/bot5/latest.json`
- Result: `keep`
- Decision / next step: keep the isolated bot5 lane. The next controlled experiment should target directional inventory bias and permissive low-edge participation, because realized PnL is mildly positive while fill-edge decomposition remains negative.

## BOT5-EXP-20260307-02: Tighten bot5 edge floor and remove trend one-sided quoting
- Date: `2026-03-07`
- Type: `config`
- Hypothesis: bot5's realized PnL is being flattered by directional drift while raw edge decomposition stays negative because the lane re-enters on too little edge and still permits one-sided trend accumulation. Tightening the effective edge floor and restoring two-sided quoting should improve trade selection and reduce inventory-biased participation.
- Changes:
  - `hbot/data/bot5/conf/controllers/epp_v2_4_bot5_ift_jota_paper.yml`: `min_net_edge_bps` `0.25 -> 1.50`
  - `hbot/data/bot5/conf/controllers/epp_v2_4_bot5_ift_jota_paper.yml`: `edge_resume_bps` `0.25 -> 2.00`
  - `hbot/data/bot5/conf/controllers/epp_v2_4_bot5_ift_jota_paper.yml`: `adaptive_edge_relax_max_bps` `10 -> 2`
  - `hbot/data/bot5/conf/controllers/epp_v2_4_bot5_ift_jota_paper.yml`: `adaptive_min_edge_bps_floor` `0.10 -> 1.00`
  - `hbot/data/bot5/conf/controllers/epp_v2_4_bot5_ift_jota_paper.yml`: `regime_specs_override.up.one_sided` `buy_only -> off`
  - `hbot/data/bot5/conf/controllers/epp_v2_4_bot5_ift_jota_paper.yml`: `regime_specs_override.down.one_sided` `sell_only -> off`
- Observation window: bot5 container restart plus early post-change runtime from `2026-03-07T00:24Z` to `2026-03-07T00:26Z`
- Metrics checked:
  - total net pnl: no new post-change fills yet, so PnL comparison is still baseline-only
  - expectancy per fill: no new post-change fill sample yet
  - rolling expectancy ci: no new post-change fill sample yet
  - maker ratio: no new post-change fill sample yet
  - inventory drift: restart carried a residual short around `-19.1%` net-base, confirming inventory cleanup is still a separate issue from quote-side mode
  - drawdown: fresh day drawdown remained low, roughly `0.00% -> 0.01%` in the first minutes
  - runtime quote posture: minute rows moved from pre-change thresholds around `0.96 bps` to post-change `edge_pause_threshold_pct = 1.0 bps` and `edge_resume_threshold_pct = 1.5 bps`
  - live order posture: post-change minute rows showed `orders_active = 4`, and the first refreshed desk snapshot showed both buy and sell resting orders instead of trend-one-sided placement
- Evidence:
  - `hbot/data/bot5/logs/epp_v24/bot5_a/minute.csv`
  - `hbot/reports/desk_snapshot/bot5/latest.json`
  - `hbot/reports/analysis/bot5_performance_dossier_latest.json`
  - `hbot/reports/analysis/bot5_edge_report_latest.json`
- Result: `inconclusive`
- Decision / next step: keep the experiment live for now. Early runtime confirms the new thresholds loaded and the lane is quoting two-sided again, but there are not enough fresh fills yet to claim an expectancy improvement.

## BOT5-EXP-20260307-03: Dedicated bot5 IFT/JOTA controller with flow-gated directionality
- Date: `2026-03-07`
- Type: `config+code`
- Hypothesis: bot5 needs a real strategy layer of its own, not just a renamed shared controller. A dedicated bot5 controller can keep shared EPP safety plumbing intact while restoring IFT/JOTA behavior as flow-aware directional bias: stay two-sided when conviction is weak, bias inventory when conviction is moderate, and switch to one-sided scalping only when imbalance and trend alignment are both strong.
- Changes:
  - `hbot/controllers/epp_v2_4_bot5.py`: replaced the thin wrapper with a bot5-specific controller/config that computes flow conviction from order-book imbalance plus EMA displacement, biases the perp net target when conviction is strong enough, switches to `buy_only` / `sell_only` only when directional conviction is high and safety vetoes are clear, tightens edge when conviction is weak, and compresses active quote levels for defensive or directional scalping posture
  - `hbot/data/bot5/conf/controllers/epp_v2_4_bot5_ift_jota_paper.yml`: added bot5-only flow thresholds and directional inventory/floor knobs while keeping static regime `one_sided` defaults off so the controller decides direction intentionally instead of by config drift
  - `hbot/tests/controllers/test_epp_v2_4_bot5.py`: added bot5-focused tests for directional target bias, quote-side switching, and the selective-quote safety veto
- Observation window: local validation plus fresh runtime after bot5 restart from `2026-03-07T01:18Z` to `2026-03-07T01:19Z`
- Metrics checked:
  - compile/test status: `python -m py_compile` passed for `epp_v2_4.py`, `epp_v2_4_bot5.py`, and the bot5 test file; full non-integration pytest passed with bot5 tests collected as skips in the current stripped environment (`sssss`)
  - runtime startup: bot5 restarted cleanly and loaded the refreshed `epp_v2_4_bot5_ift_jota_paper` controller/config
  - quote posture: fresh minute rows showed `quote_side_mode=off` and `quote_side_reason=regime`, meaning the new controller correctly fell back to two-sided MM when conviction was weak instead of forcing directional posture
  - inventory target: fresh minute rows kept `target_net_base_pct=0.0`, showing the controller did not inject directional inventory bias under weak-conviction conditions
  - participation level: fresh minute rows reduced `projected_total_quote` to about `1.60` quote and active orders to `0 -> 2`, consistent with the new defensive one-level-per-side fallback
  - edge floor: fresh minute rows held `adaptive_effective_min_edge_pct=0.00016` (1.6 bps), matching the new low-conviction extra edge floor
- Evidence:
  - `hbot/controllers/epp_v2_4_bot5.py`
  - `hbot/data/bot5/conf/controllers/epp_v2_4_bot5_ift_jota_paper.yml`
  - `hbot/tests/controllers/test_epp_v2_4_bot5.py`
  - `hbot/data/bot5/logs/epp_v24/bot5_a/minute.csv`
  - `hbot/data/bot5/logs/logs_hummingbot.log`
- Result: `keep`
- Decision / next step: keep the dedicated controller. The implementation is now structurally distinct from shared EPP while preserving shared safety. The next observation window should focus on whether strong imbalance/trend alignment actually produces bot5-only `target_net_base_pct` bias and `buy_only` / `sell_only` quote-side transitions in live paper runtime, and whether those transitions improve expectancy rather than just reducing participation.

## BOT5-EXP-20260307-04: Post-controller observation and refreshed bot5-only reports
- Date: `2026-03-07`
- Type: `analysis`
- Hypothesis: after the dedicated bot5 controller runs for a longer paper window, the lane should either begin expressing its new IFT/JOTA directional state in runtime telemetry or reveal the next real blocker preventing that behavior.
- Changes:
  - `hbot/reports/analysis/bot5_performance_dossier_latest.json`: regenerated from the latest bot5-only evidence bundle with the corrected absolute output path
  - `hbot/reports/analysis/bot5_performance_dossier_latest.md`: regenerated markdown summary from the same evidence bundle
  - `hbot/reports/analysis/bot5_edge_report_latest.json`: regenerated bot5-only edge report from the latest bot5 data root
- Observation window: fresh runtime and fills through `2026-03-07T06:13Z`, using `minute.csv`, `fills.csv`, refreshed dossier, and refreshed edge report
- Metrics checked:
  - total net pnl: dossier still reports `+3.1945` quote over the 7-day lookback, but the current day contribution is negative at `-0.3679` net quote
  - expectancy per fill: dossier `+0.00207` quote overall and rolling 300-fill upper bound `+0.00614`, so the broad historical fill sample still reads positive
  - edge decomposition: edge report remains `NEGATIVE_EDGE` with `net_edge_total_quote=-38.559361` and `avg_edge_bps=-18.05`, so raw edge accounting still disagrees with the headline dossier PnL
  - maker ratio: weighted maker ratio `85.99%`; current trading day maker ratio stayed `100%`
  - inventory drift: bot5 finished the observed window long `0.001136 BTC` with `base_pct` around `38.6%` of equity and `target_net_base_pct=0.0`
  - drawdown: current-day drawdown stayed bounded at about `0.35%`, well under hard-stop limits
  - pause behavior: `soft_pause_state_ratio=45.14%`, and the live minute rows repeatedly show `risk_reasons=adverse_fill_soft_pause`
  - directional activation: no `bot5_` quote-side reasons were recorded in `minute.csv`, and no `buy_only` / `sell_only` rows appeared during the observed sample
- Evidence:
  - `hbot/data/bot5/logs/epp_v24/bot5_a/minute.csv`
  - `hbot/data/bot5/logs/epp_v24/bot5_a/fills.csv`
  - `hbot/reports/analysis/bot5_performance_dossier_latest.json`
  - `hbot/reports/analysis/bot5_performance_dossier_latest.md`
  - `hbot/reports/analysis/bot5_edge_report_latest.json`
  - `hbot/reports/desk_snapshot/bot5/latest.json`
- Result: `inconclusive`
- Decision / next step: the dedicated controller is live, but the observed bottleneck is not missing strategy code anymore. The lane is still spending too much time in `adverse_fill_soft_pause`, and the directional layer never actually activated in this sample. The next required improvement should focus on why bot5 is failing into adverse-fill pause while holding inventory, and on making directional activation observable under valid flow conditions before changing broader spread/size logic again.
