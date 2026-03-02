# Go-Live Promotion Gates Evaluation

```text
You are a release manager and risk officer evaluating whether this paper trading desk
is ready to be promoted to live trading on Bitget BTC-USDT perpetuals.

## Current state
- Bot1 is running in paper mode (BOT_MODE=paper, connector=bitget_perpetual_paper)
- Paper Engine v2 (custom SimBroker) is the execution layer
- Promotion means: switch to BOT_MODE=live, connector=bitget_perpetual, real funds

## Non-negotiable promotion gates

### Gate 1: Code quality
- [ ] `python -m py_compile hbot/controllers/epp_v2_4.py` passes
- [ ] `PYTHONPATH=hbot python -m pytest hbot/tests/ -x -q --ignore=hbot/tests/integration` passes
- [ ] Promotion gate script passes: `PYTHONPATH=hbot python hbot/scripts/release/run_strict_promotion_cycle.py`
- [ ] No open P0 items in hbot/BACKLOG.md
- [ ] No "TODO(live)" or "TODO(prod)" markers in critical paths

### Gate 2: Risk controls verified
- [ ] Kill switch tested: manual trigger → all orders cancelled within 30s
- [ ] Daily loss limit tested: drawdown_pct > max_daily_loss_pct → hard stop fires
- [ ] Max position verified: bot cannot exceed max_base_pct × total_amount_quote
- [ ] Orphan order detection tested: stale order past max_order_age is cancelled
- [ ] Config hot-reload failure: ValidationError → last good config kept, no freeze

### Gate 3: Paper trading validation
- [ ] Paper running continuously for ≥ 7 days without manual intervention
- [ ] Bot freeze rate: < 1 per 72h
- [ ] Soft-pause ratio < 20% over rolling 7-day window
- [ ] Fills per day: ≥ N (define expected minimum for the strategy)
- [ ] Realized PnL: positive or breakeven over 7-day window (after simulated fees)
- [ ] Expectancy per fill: > 0 with statistical significance (N > 50 fills)
- [ ] PnL governor mult: average > 0.8 over 7-day window

### Gate 4: Observability complete
- [ ] All Prometheus metrics scraping correctly (zero gaps > 5min in 7 days)
- [ ] Grafana dashboards: all panels show data
- [ ] Telegram alerts: test alert received successfully
- [ ] strategy_heartbeat.json updated within 2 minutes at all times
- [ ] Event store: integrity checks passing daily
- [ ] Reconciliation service: no parity failures in 7 days

### Gate 5: Operational readiness
- [ ] Go-live hardening checklist: all items checked (docs/ops/go_live_hardening_checklist.md)
- [ ] Incident playbooks reviewed: 01-06 in docs/ops/incident_playbooks/
- [ ] Secrets management: API keys in .env, .env never committed to git
- [ ] Rollback plan documented and tested: can revert to paper in < 5 minutes
- [ ] Max initial live capital defined and approved (recommended: ≤ 20% of paper allocation)
- [ ] At least one operator available to monitor first 48h of live trading

### Gate 6: Exchange-specific readiness (Bitget)
- [ ] Live API key created with: trade + read permissions only (no withdrawal)
- [ ] IP whitelist configured on Bitget API key
- [ ] Connector tested on Bitget mainnet (balance read, order book read, place/cancel test order)
- [ ] Rate limits verified (Bitget perpetuals REST + WS limits vs bot request rate)
- [ ] Funding rate monitoring confirmed (bot handles 8h funding correctly)
- [ ] Hedge mode vs one-way mode confirmed for account

## Scoring
For each gate, assign:
- PASS (all items checked)
- PARTIAL (some items missing — list which)
- FAIL (critical item missing)

A single FAIL blocks promotion. PARTIAL items must have a remediation plan and deadline.

## Your task
Review each gate and produce:
1. Gate-by-gate verdict (PASS / PARTIAL / FAIL)
2. Blocking items (ranked, with remediation steps)
3. Timeline to resolve all blockers
4. Recommended go-live capital amount and position size limits for first week
5. Monitoring plan for first 48h live
6. Rollback trigger criteria (what would immediately pause live trading)

## Rules
- Do not recommend going live if any Gate is FAIL
- Paper PnL is not a sufficient reason alone to go live — operational readiness matters equally
- First live deployment must use reduced capital (< 50% of paper allocation)
- No promotions during high-impact macro events (FOMC, CPI) in first 30 days live
```
