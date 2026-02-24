# Final Decision Prompt (weighted ranking + architecture choice)

```text
You are a principal architect for a semi-pro crypto trading desk.

Based on full audit findings (code quality, performance, strategy logic, risk/finance, execution reliability, observability, migration mapping), make the final platform/architecture decision.

## Candidate options
1) Keep Hummingbot and harden with custom SimBroker + observability
2) Hummingbot live + external sim/research layer (hybrid)
3) Migrate to NautilusTrader (open-source)
4) Migrate to Freqtrade
5) Another free/open-source option (only if clearly superior)

## Weighted criteria
- Free/open-source viability (15)
- Bitget compatibility / connector maturity (15)
- Simulation/paper robustness (20)
- Live execution reliability (15)
- Migration effort / rewrite cost (10)
- Monitoring / observability support (10)
- Multi-bot scaling (5)
- Risk controls & reconciliation capability (5)
- Developer velocity / maintainability (5)

## Required output (strict)
1. Executive Summary (max 12 bullets)
2. Weighted Decision Matrix (scores + rationale)
3. Final Recommendation (one primary recommendation)
4. Why Not the Others
5. Target Architecture Blueprint
6. 30/60/90 Day Plan
7. Top 10 Immediate Tasks
8. Decision Confidence
9. Key Assumptions and Risks
10. Go/No-Go Triggers for Future Migration
```
