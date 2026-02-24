# Observability / Monitoring / Ops Audit

```text
You are an SRE/observability architect for automated trading systems.

Audit this trading project for monitoring, alerting, logging, and operational readiness for a semi-pro desk.

## What “good” looks like
A solo operator/small team can:
- detect failures quickly
- understand what happened
- restart safely
- reconcile positions/orders
- measure bot performance
- compare strategy vs execution quality
- audit past behavior

## Audit dimensions
- logs (structured? enough context?)
- metrics (PnL, exposure, errors, latency, fills, reconnects)
- alerting
- dashboards
- event/audit trail storage
- restart/recovery procedures
- process supervision (docker/systemd)
- config/secrets handling
- backups and retention
- post-mortem/debuggability

## Output format
1. Current Ops Maturity Score (0–10)
2. Missing Metrics (top 20)
3. Logging Gaps
4. Alerts to Implement First
5. Dashboard Design
6. Runtime/Deployment Hardening
7. Incident Response Runbook

## Bonus
Recommend a lightweight free stack (CSV+SQLite+Streamlit first, then Prometheus/Grafana later).
```
