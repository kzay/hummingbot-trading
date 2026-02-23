# Soak Report 20260221 (Preparation + Early Window)

## Scope
- Day 7 controlled-soak readiness package.
- Current mode: **pre-soak / short-window validation**, not final 24h-48h decision window.

## Runtime Context
- Live/scope intent:
  - `bot1`: real exchange scope
  - `bot4`: exchange-configured active test/live scope
  - `bot2`: disabled
  - `bot3`: paper-only validation scope
- Services active:
  - `event-store-service`
  - `reconciliation-service`
  - `shadow-parity-service`
  - `portfolio-risk-service`
  - `day2-gate-monitor`

## Gate Evidence (Current)
- Provisional promotion gates (no strict Day 2 dependency): PASS
  - `reports/promotion_gates/promotion_gates_20260221T234237Z.json`
- Strict promotion gates (`--require-day2-go`): FAIL (expected at this stage)
  - `reports/promotion_gates/promotion_gates_20260221T234239Z.json`
  - Critical blocker: `day2_event_store_gate`
- Day 2 gate status:
  - `reports/event_store/day2_gate_eval_latest.json`
  - Current state: `go=false` (elapsed window not complete yet)

## Stability Signals (Snapshot)
- Reconciliation latest:
  - `reports/reconciliation/latest.json`
  - expected target remains `critical_count=0`
- Parity latest:
  - `reports/parity/latest.json`
  - expected target remains `status=pass`
- Portfolio risk latest:
  - `reports/portfolio_risk/latest.json`
  - expected target remains `status=ok` for normal runs

## Incidents / Risks
- No new critical regression introduced by Day 6/Day 7 prep.
- Main blocker remains temporal Day 2 completion requirement.
- Operational caveat: parity freshness can fail if report is stale at gate time; run one-shot parity before gate if needed.

## Rollback Status
- No destructive migration or irreversible deployment changes introduced.
- All additions are additive and can be disabled by:
  - stopping optional services in compose profile
  - not using strict promotion mode until Day 2 matures

## Next Actions (Day 7 completion path)
1. Continue monitoring until Day 2 flips `go=true`.
2. Re-run strict gates:
   - `python scripts/release/run_promotion_gates.py --require-day2-go`
3. If strict gate passes, finalize readiness decision and start/confirm full 24h-48h soak record.
