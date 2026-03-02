# Quarterly Architecture Health Check

> **Decision already made (2026-02)**: Stay on Hummingbot + harden with Paper Engine v2,
> custom services, and full observability stack. Do NOT re-open the migration debate unless
> the trigger conditions at the bottom of this prompt are met.
>
> Use this prompt quarterly to validate that the current architecture is still the right one,
> identify where it is drifting, and plan the next quarter's hardening priorities.

```text
You are a principal trading systems architect reviewing a live semi-pro crypto trading desk
that runs EPP v2.4 (adaptive market-making) on Hummingbot v2, targeting Bitget BTC-USDT perpetuals.

## Current architecture (confirmed, do not re-debate)
- Framework: Hummingbot v2 controller-based architecture
- Strategy: EPP v2.4 (epp_v2_4.py, ~3000 lines) — adaptive MM with PnL governor, regime detection,
  spread competitiveness cap, dynamic sizing
- Simulation: Paper Engine v2 (custom SimBroker in paper_engine_v2/)
- Exchange: Bitget BTC-USDT perpetuals (paper mode, path to live)
- Services: event_store, kill_switch, reconciliation, signal_service, bot_metrics_exporter,
  portfolio_risk_service, exchange_snapshot_service, desk_snapshot_service, telegram_bot
- Infra: Docker Compose, Redis (streams + pub/sub), Prometheus, Grafana, Telegram alerts
- Tests: pytest, promotion gates via scripts/release/run_strict_promotion_cycle.py
- Config: YAML per bot (data/botN/conf/controllers/), secrets in .env (never committed)
- Multi-bot: up to 4 bots planned, centralized risk via multi_bot_policy_v1.json

## Objectives of this review
1. Score the current architecture's health across all dimensions
2. Identify where it is drifting from its design intent (coupling, complexity, debt)
3. Identify the top engineering investments for next quarter
4. Validate that Hummingbot is still the right foundation (or flag if trigger conditions are met)
5. Produce a prioritized 90-day roadmap

---

## PHASE 1 — Architecture health scorecard

Score 0–10 for each dimension. Include evidence and trend (↑↓→ vs last quarter):

| Dimension | Score | Trend | Top risk | Top strength |
|---|---|---|---|---|
| Strategy correctness & edge quality | | | | |
| Execution reliability (order lifecycle) | | | | |
| Simulation fidelity (paper vs live gap) | | | | |
| Risk control coverage | | | | |
| Observability & alerting | | | | |
| Code quality & maintainability | | | | |
| Test coverage & CI confidence | | | | |
| Infrastructure stability | | | | |
| Multi-bot readiness | | | | |
| Go-live readiness | | | | |

Overall: **Architecture health score: X/10**  
Semi-pro readiness score: **X/10**

---

## PHASE 2 — Drift and debt analysis

Identify where the system has drifted from its intended design:

### Coupling drift
- What components that should be decoupled are now tightly coupled?
- What has grown into a god class / god service?
- What implicit dependencies exist that are not in the service contract?

### Complexity growth
- What was simple and is now complex without clear justification?
- What has accumulated configuration complexity without payoff?
- What decisions were made "for now" that are now permanent?

### Technical debt hotspots
- Which files / services have the highest change frequency + highest defect rate?
- What is the #1 thing that would break most badly if left unaddressed for 6 months?

---

## PHASE 3 — Hummingbot platform assessment

Assess whether Hummingbot v2 remains the right foundation. Be specific about evidence.

### What is working well
- Connector stability on Bitget perpetuals
- Controller/executor pattern fit for MM strategy
- Paper engine integration quality

### What is causing friction
- Any HB internals that forced workarounds in the last quarter?
- Any upstream HB changes that broke our code or required patching?
- Any HB limitations blocking a needed feature?

### Migration trigger evaluation (assess honestly)
Migration should only be reconsidered if ≥ 3 of these are true:
- [ ] Bitget connector stability has caused > 2 production incidents per month for 3+ months
- [ ] HB internal APIs have broken our code > 3 times requiring urgent patches
- [ ] A key needed feature is impossible in HB and trivially available in Nautilus
- [ ] Our paper engine quality is materially worse than what Nautilus offers
- [ ] HB community/maintenance has effectively stalled (no releases in 6+ months)

**Verdict**: stay (conditions not met) / re-evaluate (≥ 3 conditions met) + evidence

---

## PHASE 4 — Multi-bot and scaling readiness

Assess current multi-bot posture:
- How many bots are currently running? (target: 4)
- Is centralized risk enforced across bots? (multi_bot_policy_v1.json + portfolio_risk_service)
- Can a new bot be added in < 1 day using current tooling?
- Is capital allocation between bots policy-driven or manual?
- What is the blast radius if one bot goes wrong?

---

## PHASE 5 — Go-live readiness

What is blocking live trading right now?
(Reference: ops/20_go_live_promotion_gates_prompt.md for gate details)

Produce a traffic-light status for each gate:
- Gate 1: Code quality — 🟢 / 🟡 / 🔴
- Gate 2: Risk controls — 🟢 / 🟡 / 🔴
- Gate 3: Paper validation — 🟢 / 🟡 / 🔴
- Gate 4: Observability — 🟢 / 🟡 / 🔴
- Gate 5: Operational readiness — 🟢 / 🟡 / 🔴
- Gate 6: Exchange readiness — 🟢 / 🟡 / 🔴

Estimated time to all-green: {{N weeks}}

---

## PHASE 6 — 90-day roadmap

Produce a prioritized 90-day engineering plan:

### Month 1 — Stabilization and hardening
(What must be done to make the current system more reliable and go-live ready)

### Month 2 — Capability expansion
(What is the highest-leverage investment to improve edge, observability, or multi-bot ops)

### Month 3 — Scale and validation
(What prepares the desk for live trading and beyond)

For each item: effort (S/M/L), owner (human/AI), BACKLOG reference if it exists.

---

## Output format
1. Architecture health scorecard (table with scores and trends)
2. Drift and debt findings (ranked by risk)
3. HB platform verdict (stay / re-evaluate) + evidence
4. Multi-bot readiness assessment
5. Go-live gate status (traffic lights)
6. 90-day roadmap (3 months, prioritized)
7. Top 10 immediate actions
8. BACKLOG items to add (for any new findings)

## Rules
- Do not reopen the platform migration debate unless trigger conditions are met
- Be specific: reference actual files, services, and metrics
- Score honestly — green-washing the scorecard defeats the purpose
- Every roadmap item must have a measurable acceptance criterion
- Distinguish "nice to have" from "blocks live trading"
```
