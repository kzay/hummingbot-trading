# Bot4 Binance Testnet V2 - Validation Results

Use this sheet to record mandatory evidence for each scenario.
Mark scenario as PASS only if all required checks pass.

## Run Metadata

- Date:
- Operator:
- Environment (`hummingbot` image tag):
- Bot4 container id:
- Connector configured (`binance_perpetual_testnet`): yes/no

## Global Mandatory Checks (all scenarios)

- [ ] Strategy starts without exception.
- [ ] Preflight passes (no preflight error lines).
- [ ] Connector transitions to ready.
- [ ] No recurring startup/readiness loop.
- [ ] No traceback in scenario log.

Evidence:
- Log file:
- Minute CSV:
- Fills CSV:

---

## Scenario 1 - Baseline Smoke

- Config: `v2_epp_v2_4_bot4_binance_smoke.yml`
- Expected:
  - [ ] Ready transition observed
  - [ ] Controller ticks continuously
  - [ ] Orders lifecycle appears (create/cancel/fill)

Result: PASS / FAIL
Notes:

---

## Scenario 2 - No-Trade Safety

- Config: `v2_epp_v2_4_bot4_binance_notrade.yml`
- Expected:
  - [ ] State soft_pause/no-trade behavior
  - [ ] No active order creation
  - [ ] No fill events

Result: PASS / FAIL
Notes:

---

## Scenario 3 - Manual Fee Fallback

- Config: `v2_epp_v2_4_bot4_binance_manual_fee.yml`
- Expected:
  - [ ] No fee resolution error
  - [ ] `fee_source` indicates manual path
  - [ ] Controller continues ticking

Result: PASS / FAIL
Notes:

---

## Scenario 4 - Auto Fee Resolution

- Config: `v2_epp_v2_4_bot4_binance_auto_fee.yml`
- Expected:
  - [ ] No `fee_unresolved`
  - [ ] Auto/runtime/API fee source appears
  - [ ] Maker/taker fee values populated

Result: PASS / FAIL
Notes:

---

## Scenario 5 - Edge-Gate Pause

- Config: `v2_epp_v2_4_bot4_binance_edge_pause.yml`
- Expected:
  - [ ] Soft pause triggered by edge gating
  - [ ] Edge thresholds visible in minute.csv
  - [ ] No hard-stop unless separately triggered

Result: PASS / FAIL
Notes:

---

## Scenario 6 - Inventory Guard

- Config: `v2_epp_v2_4_bot4_binance_inventory_guard.yml`
- Expected:
  - [ ] Inventory risk reason appears
  - [ ] Guard state reflects risk policy
  - [ ] Behavior aligns with configured min/max base bounds

Result: PASS / FAIL
Notes:

---

## Scenario 7 - Cancel Budget Throttle

- Config: `v2_epp_v2_4_bot4_binance_cancel_budget.yml`
- Expected:
  - [ ] Cancel budget breach behavior observed
  - [ ] Cooldown soft pause applied
  - [ ] Recovery after cooldown

Result: PASS / FAIL
Notes:

---

## Final Gate

- [ ] All 7 scenarios PASS
- [ ] No critical unresolved errors in logs
- [ ] Evidence files archived

Final Decision: ACCEPT / REJECT
Approver:
