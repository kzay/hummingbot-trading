# Go-Live Hardening Checklist

## Purpose
Validation checklist for transitioning from testnet/paper to live exchange trading.
Every item must be PASS before deploying with real capital.

## Pre-Deployment Validation

### 1. Fee Resolution
- [ ] `fee_mode: auto` resolves correctly from exchange API
- [ ] Fee rates match exchange dashboard (maker/taker)
- [ ] `require_fee_resolution: true` blocks trading when fees fail
- **Evidence:** `processed_data.fee_source` shows `api:exchange:*`

### 2. Trading Rules
- [ ] Min notional, tick size, lot size match exchange docs
- [ ] `_quantize_price` and `_quantize_amount` produce valid values
- [ ] Orders pass exchange validation (no rejects for size/price)
- **Evidence:** Zero `did_fail_order` events with "invalid" in message

### 3. Kill Switch
- [ ] `services/kill_switch/main.py` deployed and running
- [ ] Dry-run kill switch tested: cancels all orders
- [ ] Live kill switch tested on testnet: orders actually canceled
- **Evidence:** `reports/kill_switch/latest.json` shows `status: executed`

### 4. Orphan Order Scan
- [ ] Startup scan detects and cancels untracked orders
- [ ] Tested: place order via exchange UI, restart bot, verify canceled
- **Evidence:** Log entry "Orphan order canceled: ..."

### 5. Position Reconciliation
- [ ] `_check_position_reconciliation` runs every 5 min
- [ ] Position drift > 5% triggers SOFT_PAUSE
- [ ] `position_drift_pct` visible in `processed_data`
- **Evidence:** `position_drift_pct` stays < 1% during normal operation

### 6. WS Reconnection
- [ ] `ws_reconnect_count` tracked in `processed_data`
- [ ] Order book staleness detected (same TOB > 30s)
- [ ] `connector_status` dict visible in `processed_data`
- **Evidence:** Zero undetected WS drops during 24h soak

### 7. Order Lifecycle
- [ ] Order ack timeout (30s) triggers cancel for stuck orders
- [ ] Cancel-before-place guard prevents duplicate levels
- [ ] `max_active_executors` limit enforced
- [ ] Execution price deviation > 1% logged as WARNING
- **Evidence:** No duplicate orders during regime transitions

### 8. Rate Limits
- [ ] `cancel_budget_per_min: 50` aligns with exchange limit
- [ ] Cancel budget escalation (3 breaches → HARD_STOP) works
- [ ] Exchange rate limit headers show > 50% headroom during soak
- **Evidence:** Zero 429 responses during 48h soak

### 9. Risk Controls
- [ ] `max_daily_loss_pct_hard: 0.03` triggers HARD_STOP
- [ ] `max_drawdown_pct_hard: 0.05` triggers HARD_STOP
- [ ] HARD_STOP publishes kill_switch intent
- [ ] Leverage cap validated (`max_leverage` check in __init__)
- [ ] Margin ratio monitoring active (perps)
- **Evidence:** Synthetic breach test triggers expected controls

### 10. PnL Accounting
- [ ] `realized_pnl_quote` column in fills.csv is populated
- [ ] Daily state persists across restart (`daily_state.json`)
- [ ] Funding rate tracked and visible in `processed_data`
- [ ] `edge_report.py` shows positive or explainable negative edge
- **Evidence:** Daily PnL matches exchange account statement within 5%

## Soak Tests

### 11. Paper→Live Parity
- [ ] Run paper and testnet simultaneously for 1 hour
- [ ] Compare: fill count ratio, spread capture, regime distribution
- [ ] PnL direction should be consistent (both positive or both negative)
- **Evidence:** Side-by-side comparison document

### 12. Restart Recovery
- [ ] Start bot, let it place orders, SIGKILL process
- [ ] Restart and verify orphan orders detected/canceled
- [ ] Daily state restored (loss limits carry over)
- **Evidence:** Log entries showing orphan cleanup + state restoration

### 13. Multi-Day Soak (48h)
- [ ] Run continuously on testnet for 48 hours
- [ ] Daily rollover resets counters correctly
- [ ] No memory growth (check RSS every 6h)
- [ ] No executor leak (active count stays bounded)
- [ ] Funding rate settlement handled (every 8h)
- **Evidence:** `minute.csv` shows 2880 rows, no gaps

### 14. Exchange-Specific
- [ ] Bitget API key has trade + read permissions only (no withdrawal)
- [ ] IP allowlist configured on exchange
- [ ] Account is in correct mode (isolated/cross margin)
- [ ] Position mode (ONEWAY) confirmed on exchange
- **Evidence:** Exchange account settings screenshot

### 15. Framework Patch Audit
- [ ] `enable_framework_paper_compat_fallbacks()` patches disabled in live mode
- [ ] Live connector uses unpatched framework paths (no paper compat shims)
- **Evidence:** Code path audit; live mode does not call `enable_framework_paper_compat_fallbacks()` or patches are gated by `BOT_MODE=paper`

### 16. Connector Health
- [ ] `connector.ready` returns real health state (not hardcoded `True`)
- [ ] WS/API connectivity failures reflected in `ready` status
- **Evidence:** Disconnect test shows `ready=False`; `processed_data.connector_status` reflects actual state

### 17. NTP/Clock Drift
- [ ] Host clock drift < 2s vs exchange server time
- [ ] NTP sync verified on deployment host
- **Evidence:** `ntpdate -q pool.ntp.org` or equivalent; exchange timestamp comparison

### 18. Kill Switch Post-Cancel
- [ ] Kill switch stops bot container after cancel-all
- [ ] `KILL_SWITCH_STOP_BOT=true` and `KILL_SWITCH_BOT_CONTAINER` correctly set
- **Evidence:** Kill switch dry-run then live test; bot container stopped after cancel

### 19. Startup Sync Failure
- [ ] Startup sync failure → HARD_STOP (verified)
- [ ] Position/order sync failure on init blocks trading
- **Evidence:** Synthetic sync failure test triggers HARD_STOP; no orders placed

### 20. Exchange Snapshot Perp Positions
- [ ] Exchange snapshot fetches perp positions
- [ ] `FETCH_PERP_POSITIONS=true` (default); `reports/exchange_snapshots/latest.json` includes `positions`
- **Evidence:** Snapshot JSON contains non-empty `positions` array when perp positions exist

### 21. Rapid Partial Fill Stress Test
- [ ] Rapid partial fill stress test: 50+ fills/order on testnet
- [ ] No executor leak, no memory growth, correct PnL accounting
- **Evidence:** Testnet run with high churn; executor count bounded; fills.csv accurate

### 22. Network Partition Test
- [ ] Network partition test: 30s disconnect mid-trading
- [ ] WS reconnect handled; no orphan orders; safe recovery
- **Evidence:** `iptables` or similar disconnect; log shows reconnect; no duplicate orders

### 23. Redis Outage Test
- [ ] Redis outage test: 5 min stop, verify safe operation
- [ ] Bot degrades gracefully (SOFT_PAUSE or equivalent); no crash
- **Evidence:** `docker stop hbot-redis` for 5 min; bot behavior logged; recovery on Redis restart

### 24. did_fail_order Streak Fix
- [ ] `did_fail_order` streak fix verified: cancel streak not reset on unrelated failures
- [ ] Order rejections do not incorrectly reset cancel-budget or executor state
- **Evidence:** Synthetic `did_fail_order` test; cancel streak preserved per EXEC-E6

## Sign-Off

| Reviewer | Date | Decision |
|----------|------|----------|
| | | GO / NO-GO |

All 24 items must be PASS for GO decision.
