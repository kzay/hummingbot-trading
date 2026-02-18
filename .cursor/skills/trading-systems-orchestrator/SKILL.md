---
name: trading-systems-orchestrator
description: Orchestrates end-to-end design and improvement of algorithmic trading systems across strategy, data, execution, risk, validation, and deployment. Use when the user asks for a complete trading system plan, architecture review, full-stack bot design, production readiness, or coordinated changes across multiple trading domains.
---

# Trading Systems Orchestrator

## When to Use

Use this skill when requests span multiple domains, such as:
- "Design a production-ready trading bot"
- "Review my strategy, risk, and deployment setup together"
- "Build a full stack from research to live execution"

Trigger phrases include:
- "end-to-end", "full system", "production-ready", "institutional-grade"
- "architecture + strategy + risk", "go live safely", "hardening plan"

## When Not to Use

Avoid this skill for narrowly scoped requests that are clearly single-domain.
Route directly to the specialized domain skill instead.

## Execution Model

1. Classify the request into these domains:
   - Core programming and APIs
   - Market data and technical analysis
   - Strategy and quant logic
   - Backtesting and validation
   - Risk management
   - Optional ML usage
   - Infrastructure and deployment
   - Professional architecture
2. Identify the minimum viable path first, then hardening tasks.
3. Produce a phased plan with acceptance criteria per phase.
4. Explicitly call out assumptions, unknowns, and failure modes.
5. If routing is unclear, consult [ROUTING.md](ROUTING.md).

## Automatic Improvement Mode

When the request is broad or under-specified, proactively improve the result by:
1. Adding missing risk controls if they are absent.
2. Adding realistic validation assumptions (fees, slippage, latency).
3. Adding deployment observability and incident response requirements.
4. Highlighting top 3 leverage points for performance and reliability.

## Response Contract

For substantial requests, provide output in this format:

```markdown
# Trading System Plan

## Objective
[Target behavior, market, and constraints]

## Architecture
- Data layer:
- Strategy layer:
- Execution layer:
- Risk engine:
- Ops/monitoring:

## Phase Plan
1. Research and data quality
2. Strategy implementation
3. Backtest validation
4. Paper trading
5. Live rollout and controls

## Risk Controls
- Max drawdown:
- Exposure caps:
- Kill switch:

## Validation
- Out-of-sample:
- Walk-forward:
- Stress tests:

## Deployment
- Runtime:
- Monitoring:
- Alerting:
```

## Quality Gates

- No live deployment plan without explicit risk limits.
- No performance claims without fees/slippage assumptions.
- No ML recommendation without baseline non-ML comparison.
- No architecture proposal without operational observability.
