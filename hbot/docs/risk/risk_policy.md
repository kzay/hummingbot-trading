# Risk Policy

## Purpose
Define hierarchical risk controls across external services and Hummingbot.

## Policy Hierarchy
1. **Global policy (external risk service)**:
   - confidence gates
   - stale/outlier rejection
   - approval/rejection decisions
2. **Local execution authority (Hummingbot)**:
   - connector readiness
   - intent bounds validation
   - controller-level safety state

## Rule Categories
- Market-state gates (volatility, turnover pressure, adverse drift).
- Signal-quality gates (confidence, age, model freshness).
- Execution gates (target bounds, expiry, connector status).

## Escalation
- Repeated rejects or outage -> external soft-pause and operator review.
- Severe anomalies -> hard stop by local or external kill-switch intent.

## Failure Modes
- Signal floods -> notional constraints and soft pause.
- Bus outage -> strategy remains locally controlled with restricted external intent path.

## Owner
- Risk/Trading Engineering
- Last-updated: 2026-02-19

