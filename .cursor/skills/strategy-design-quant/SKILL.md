---
name: strategy-design-quant
description: Develops trading strategy logic using quant fundamentals such as risk/reward, expectancy, and position sizing. Use when the user asks for strategy rules, edge formulation, entry/exit design, payoff engineering, position sizing, or mathematically grounded trade management.
---

# Strategy Design Quant

## Focus

Translate hypotheses into explicit, testable trading rules.

## When Not to Use

Do not use for infrastructure and deployment setup unless strategy behavior depends on execution topology constraints.

## Core Concepts

- Expected value and expectancy decomposition.
- Win rate vs payoff ratio trade-offs.
- Position sizing tied to volatility and risk budget.
- Entry, exit, and invalidation logic as separate modules.

## Workflow

1. Define market hypothesis and edge source.
2. Specify rule set:
   - setup conditions, trigger, stop, target, time stop.
3. Define sizing model:
   - fixed fractional, volatility-targeted, capped Kelly variant.
4. Specify portfolio interaction:
   - correlation-aware limits and conflict resolution.
5. Write falsifiable acceptance criteria.

## Output Template

```markdown
## Strategy Spec

- Hypothesis:
- Instruments:
- Entry rules:
- Exit rules:
- Sizing model:
- Risk assumptions:
- Failure conditions:
```

## Red Flags

- Vague strategy language with no executable rules.
- Sizing detached from drawdown tolerance.
- Optimizing win rate while ignoring payoff asymmetry.
- No invalidation condition for edge decay.
