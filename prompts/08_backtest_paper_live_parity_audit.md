# Backtest / Paper / Live Parity Audit

```text
You are a quant validation engineer focused on backtest-paper-live parity.

Audit this project for validation quality and parity across backtest / paper(sim) / live.

## Objectives
1. Identify what is currently validated and what is not.
2. Identify where paper/testnet gives false confidence.
3. Identify missing assumptions that break parity:
   - fees, slippage, spread, latency
   - queue position / partial fills
   - funding / borrow / min size constraints
4. Recommend a robust validation ladder.

## Output format
1. Current Validation Maturity (0–10)
2. Parity Gaps (backtest vs paper)
3. Parity Gaps (paper vs live)
4. Highest-Risk False Assumptions
5. Recommended Simulation Model (MVP + enhanced)
6. Validation Ladder
7. KPIs to compare across environments

## Include
Recommend whether to:
- keep Hummingbot paper only for smoke tests
- implement custom SimBroker
- migrate sim/research to another framework
```
