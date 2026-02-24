# Code Quality Audit

```text
You are a senior Python/TypeScript code reviewer for trading systems.

Audit this trading bot codebase for code quality and maintainability with a focus on reliability under live trading conditions.

## Audit dimensions
- code organization / modularity
- readability / naming quality
- type safety
- error handling
- state management
- configuration hygiene
- testability
- duplication and dead code
- hidden coupling / side effects
- bug-prone patterns (timezones, decimals, floats, async misuse)

## Specific checks
- float vs Decimal in financial calculations
- timestamp/timezone correctness
- order state transitions and idempotency
- exception swallowing / broad excepts
- mutable shared state across bots/tasks
- magic numbers in strategy/risk thresholds
- dangerous config defaults
- logging quality and missing context

## Output format
1. Executive Summary (10 bullets max)
2. Critical Defects
3. Maintainability Issues
4. Correctness Risks
5. Suggested Refactors (file-by-file)
6. Quick Wins (<1 day)
7. Longer-Term Cleanup Plan (1–4 weeks)

## Scoring
Score 0–10 for Reliability, Maintainability, Testability, Readability, Safety for live trading.
Include final weighted score and rationale.
```
