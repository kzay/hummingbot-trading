---
name: trading-infrastructure-deployment
description: Designs deployment and operations for trading systems using Docker, VPS environments, monitoring, and alerting. Use when the user asks about running bots reliably in production, containerization, uptime, observability, incident response, or release/rollback reliability.
---

# Trading Infrastructure Deployment

## Focus

Run trading systems as reliable services with strong observability.

## When Not to Use

Do not use for pure alpha research questions unless production constraints are part of the request.

## Core Guidance

- Containerize services with explicit resource and restart policies.
- Use environment-specific configuration with secret management.
- Implement health checks for data feed, strategy loop, and execution path.
- Configure alerting for risk events and infrastructure degradation.

## Workflow

1. Package services:
   - Dockerfiles, compose or orchestrator manifests.
2. Define runtime topology:
   - data ingestion, strategy worker, execution gateway, risk service.
3. Add monitoring:
   - metrics dashboards, structured logs, heartbeat checks.
4. Configure alerting:
   - latency spikes, disconnects, PnL anomalies, kill switch activation.
5. Define ops runbooks:
   - deploy, rollback, recovery, and failover procedures.

## Output Template

```markdown
## Deployment Plan

- Runtime target (VPS/cloud):
- Service topology:
- Container strategy:
- Monitoring stack:
- Alert rules:
- Rollback/recovery:
```

## Red Flags

- Single host with no restart supervision.
- No persistent logging or metric retention.
- Secrets hardcoded in images or repo.
- No rollback path for bad releases.
