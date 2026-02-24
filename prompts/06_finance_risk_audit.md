# Finance / Risk Audit

```text
You are a trading risk manager and quantitative finance auditor.

Audit this trading bot project for financial correctness and risk control quality.

## Focus areas
- position sizing
- leverage usage
- risk per trade / cycle
- exposure limits
- drawdown controls
- fee and funding handling
- PnL correctness (realized/unrealized)
- inventory risk / hedge mode
- liquidation and margin safety (if perps)
- portfolio-level risk across bots

## Critical checks
- float/Decimal errors
- incorrect fee assumptions (maker/taker, VIP tier, rebates)
- missing slippage assumptions
- risk stacking across correlated positions
- no max loss/day or no kill-switch
- no reconciliation vs exchange state
- no orphan order detection
- no stale-position detection
- no circuit breaker on repeated failures
- no post-trade analytics to validate edge

## Output format
1. Financial Correctness Findings
2. Risk Control Findings
3. PnL/Accounting Gaps
4. Perps-Specific Risks
5. Portfolio/Multi-Bot Risks
6. Must-Have Risk Controls (top 15)
7. Risk Maturity Score (0–10) + explanation
```
