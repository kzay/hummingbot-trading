---
name: trading-risk-management
description: Establishes risk controls for algorithmic trading, including drawdown limits, kill switches, and exposure caps at strategy and portfolio levels. Use when the user asks to prevent catastrophic loss, enforce risk budgets, set max loss/exposure policies, or design safety controls for live trading.
---

# Trading Risk Management

## Focus

Protect capital first, then optimize returns.

## When Not to Use

Do not use for pure indicator selection or model architecture decisions unless they are part of a risk-control discussion.

## Required Controls

- Hard max drawdown and soft warning thresholds.
- Kill switch triggers for abnormal behavior or infra failures.
- Per-instrument, per-strategy, and portfolio exposure caps.
- Max order size, max daily loss, and max concurrent positions.

## Workflow

1. Define risk budget by strategy and portfolio.
2. Implement pre-trade controls:
   - exposure checks, leverage checks, liquidity checks.
3. Implement in-trade controls:
   - stop logic, time stops, trailing controls where justified.
4. Implement post-trade controls:
   - daily loss lockout, cooldowns, and auto-disable policy.
5. Add incident response runbook and manual override process.

## Output Template

```markdown
## Risk Policy

- Risk budget:
- Drawdown limits:
- Exposure caps:
- Kill switch conditions:
- Daily loss limits:
- Incident response:
```

## Red Flags

- Risk checks after order submission instead of before.
- Missing fail-closed behavior on connectivity loss.
- Unlimited averaging down.
- No operator alert path for kill switch events.
