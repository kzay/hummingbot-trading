---
name: professional-trading-architecture
description: Defines professional architecture patterns for trading platforms, separating data, strategy, execution, and risk engine layers with clear interfaces. Use when the user asks for scalable system design, layered architecture, service boundaries, refactoring monolith bots, or institutional-grade trading platform design.
---

# Professional Trading Architecture

## Focus

Enforce clean boundaries across data, strategy, execution, and risk.

## When Not to Use

Do not use for small single-file fixes unless they impact layer boundaries or interface contracts.

## Architecture Principles

- Data layer is source-of-truth ingestion and normalization only.
- Strategy layer generates intents, not direct exchange calls.
- Execution layer translates intents into broker/exchange actions.
- Risk engine has veto power on all orders before placement.
- Event contracts are versioned and backward-compatible.

## Reference Layering

1. Data layer:
   - adapters, schema normalization, feature-serving interfaces.
2. Strategy layer:
   - signal generation, portfolio construction, intent emission.
3. Execution layer:
   - smart order routing, retries, fill reconciliation.
4. Risk engine:
   - pre-trade checks, exposure and drawdown governance.
5. Platform ops:
   - monitoring, audit trails, and control-plane tooling.

## Output Template

```markdown
## Target Architecture

- Data layer responsibilities:
- Strategy layer responsibilities:
- Execution layer responsibilities:
- Risk engine responsibilities:
- Cross-layer contracts:
- Migration plan:
```

## Red Flags

- Strategy code directly calling exchange clients.
- Risk checks bypassable by execution services.
- Shared database schema with no ownership boundaries.
- No audit trail for order lifecycle decisions.
