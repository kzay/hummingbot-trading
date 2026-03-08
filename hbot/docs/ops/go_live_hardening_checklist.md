# Go-Live Hardening Checklist

## Purpose
Validation checklist for transitioning from testnet/paper to live exchange trading.
Every item must be PASS before deploying with real capital.

## Pre-Deployment Validation

### 1. Fee Resolution
- [x] `fee_mode: auto` resolves correctly from exchange API
- [x] Fee rates match exchange dashboard (maker/taker)
- [x] `require_fee_resolution: true` blocks trading when fees fail
- **Evidence:** `reports/accounting/latest.json`

### 2. Trading Rules
- [x] Min notional, tick size, lot size match exchange docs
- [x] `_quantize_price` and `_quantize_amount` produce valid values
- [x] Orders pass exchange validation (no rejects for size/price)
- **Evidence:** `reports/tests/latest.json`

### 3. Kill Switch
- [x] `services/kill_switch/main.py` deployed and running
- [x] Dry-run kill switch tested: cancels all orders
- [x] Live kill switch tested on testnet: orders actually canceled
- **Evidence:** `reports/kill_switch/latest.json`, `reports/ops/kill_switch_non_dry_run_evidence_latest.json`

### 4. Orphan Order Scan
- [x] Startup scan detects and cancels untracked orders
- [x] Tested: place order via exchange UI, restart bot, verify canceled
- **Evidence:** `reports/verification/paper_exchange_golden_path_latest.json`

### 5. Position Reconciliation
- [x] `_check_position_reconciliation` runs every 5 min
- [x] Position drift > 5% triggers SOFT_PAUSE
- [x] `position_drift_pct` visible in `processed_data`
- **Evidence:** `reports/reconciliation/latest.json`

### 6. WS Reconnection
- [x] `ws_reconnect_count` tracked in `processed_data`
- [x] Order book staleness detected (same TOB > 30s)
- [x] `connector_status` dict visible in `processed_data`
- **Evidence:** `reports/ops/reliability_slo_latest.json`

### 7. Order Lifecycle
- [x] Order ack timeout (30s) triggers cancel for stuck orders
- [x] Cancel-before-place guard prevents duplicate levels
- [x] `max_active_executors` limit enforced
- [x] Execution price deviation > 1% logged as WARNING
- **Evidence:** `reports/verification/paper_exchange_golden_path_latest.json`

### 8. Rate Limits
- [x] `cancel_budget_per_min: 50` aligns with exchange limit
- [x] Cancel budget escalation (3 breaches → HARD_STOP) works
- [x] Exchange rate limit headers show > 50% headroom during soak
- **Evidence:** `reports/ops/reliability_slo_latest.json`

### 9. Risk Controls
- [x] `max_daily_loss_pct_hard: 0.03` triggers HARD_STOP
- [x] `max_drawdown_pct_hard: 0.05` triggers HARD_STOP
- [x] HARD_STOP publishes kill_switch intent
- [x] Leverage cap validated (`max_leverage` check in __init__)
- [x] Margin ratio monitoring active (perps)
- **Evidence:** `reports/verification/paper_exchange_golden_path_latest.json`, `reports/kill_switch/latest.json`

### 10. PnL Accounting
- [x] `realized_pnl_quote` column in fills.csv is populated
- [x] Daily state persists across restart (`daily_state.json`)
- [x] Funding rate tracked and visible in `processed_data`
- [x] `edge_report.py` shows positive or explainable negative edge
- **Evidence:** `reports/accounting/latest.json`

## Soak Tests

### 11. Paper→Live Parity
- [x] Run paper and testnet simultaneously for 1 hour
- [x] Compare: fill count ratio, spread capture, regime distribution
- [x] PnL direction should be consistent (both positive or both negative)
- **Evidence:** `reports/parity/latest.json`, `reports/strategy/testnet_daily_scorecard_latest.json`

### 12. Restart Recovery
- [x] Start bot, let it place orders, SIGKILL process
- [x] Restart and verify orphan orders detected/canceled
- [x] Daily state restored (loss limits carry over)
- **Evidence:** `reports/verification/paper_exchange_golden_path_latest.json`

### 13. Multi-Day Soak (48h)
- [x] Run continuously on testnet for 48 hours
- [x] Daily rollover resets counters correctly
- [x] No memory growth (check RSS every 6h)
- [x] No executor leak (active count stays bounded)
- [x] Funding rate settlement handled (every 8h)
- **Evidence:** `reports/strategy/multi_day_summary_latest.json`

### 14. Exchange-Specific
- [x] Bitget API key has trade + read permissions only (no withdrawal)
- [x] IP allowlist configured on exchange
- [x] Account is in correct mode (isolated/cross margin)
- [x] Position mode (ONEWAY) confirmed on exchange
- **Evidence:** `reports/exchange_snapshots/latest.json`, `docs/ops/secrets_and_key_rotation.md`

### 15. Framework Patch Audit
- [x] `enable_framework_paper_compat_fallbacks()` patches disabled in live mode
- [x] Live connector uses unpatched framework paths (no paper compat shims)
- **Evidence:** `reports/verification/paper_exchange_hb_compatibility_latest.json`, `docs/validation/hb_executor_runtime_compatibility_contract.md`

### 16. Connector Health
- [x] `connector.ready` returns real health state (not hardcoded `True`)
- [x] WS/API connectivity failures reflected in `ready` status
- **Evidence:** `reports/ops/reliability_slo_latest.json`

### 17. NTP/Clock Drift
- [x] Host clock drift < 2s vs exchange server time
- [x] NTP sync verified on deployment host
- **Evidence:** `docs/ops/option4_operator_checklist.md`

### 18. Kill Switch Post-Cancel
- [x] Kill switch stops bot container after cancel-all
- [x] `KILL_SWITCH_STOP_BOT=true` and `KILL_SWITCH_BOT_CONTAINER` correctly set
- **Evidence:** `reports/kill_switch/latest.json`, `reports/ops/kill_switch_non_dry_run_evidence_latest.json`

### 19. Startup Sync Failure
- [x] Startup sync failure → HARD_STOP (verified)
- [x] Position/order sync failure on init blocks trading
- **Evidence:** `reports/verification/paper_exchange_golden_path_latest.json`

### 20. Exchange Snapshot Perp Positions
- [x] Exchange snapshot fetches perp positions
- [x] `FETCH_PERP_POSITIONS=true` (default); `reports/exchange_snapshots/latest.json` includes `positions`
- **Evidence:** `reports/exchange_snapshots/latest.json`

### 21. Rapid Partial Fill Stress Test
- [x] Rapid partial fill stress test: 50+ fills/order on testnet
- [x] No executor leak, no memory growth, correct PnL accounting
- **Evidence:** `reports/verification/paper_exchange_load_latest.json`

### 22. Network Partition Test
- [x] Network partition test: 30s disconnect mid-trading
- [x] WS reconnect handled; no orphan orders; safe recovery
- **Evidence:** `docs/ops/incident_playbooks/05_exchange_api_errors.md`

### 23. Redis Outage Test
- [x] Redis outage test: 5 min stop, verify safe operation
- [x] Bot degrades gracefully (SOFT_PAUSE or equivalent); no crash
- **Evidence:** `reports/ops/reliability_slo_latest.json`, `tests/controllers/test_hb_bridge_signal_routing.py`

### 24. did_fail_order Streak Fix
- [x] `did_fail_order` streak fix verified: cancel streak not reset on unrelated failures
- [x] Order rejections do not incorrectly reset cancel-budget or executor state
- **Evidence:** `tests/controllers/test_epp_v2_4_state.py`, `reports/tests/latest.json`

## Sign-Off

| Reviewer | Date | Decision |
|----------|------|----------|
| | | GO / NO-GO |

All 24 items must be PASS for GO decision.
