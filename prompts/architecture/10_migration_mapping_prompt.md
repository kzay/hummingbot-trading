# Migration Mapping Prompt (Hummingbot → Nautilus/Freqtrade/Hybrid)

> Use this prompt only when migration is explicitly requested, or when the trigger
> conditions from `architecture/01_master_decision_prompt.md` are met.

```text
You are a migration architect for trading systems.

Create a migration map for this project from the current Hummingbot-based implementation to the best target architecture.

## Mission
0. Validate migration triggers first (or confirm explicit migration request). If triggers are not met, recommend hardening-in-place and stop migration planning.
1. Analyze current code and identify portable vs Hummingbot-coupled components.
2. Propose migration options:
   - Hummingbot + custom SimBroker
   - Hummingbot + external research/sim layer (hybrid)
   - NautilusTrader migration
   - Freqtrade migration (if directional)
3. Estimate migration effort and risk.
4. Recommend a phased migration path.

## Required outputs
1. Component Portability Matrix
2. Target Architecture Candidates (top 3)
3. Migration Cost/Risk Table
4. Recommended Migration Path (or no migration)
5. Phase-by-Phase Plan with rollback
6. Parity Validation Plan (strategy logic, fills, PnL, risk controls)

## Important
- Be explicit about Bitget support implications.
- Be explicit about simulation/paper quality differences.
- Do not assume testnet parity with production.
- Optimize for free/open-source tools.
```
