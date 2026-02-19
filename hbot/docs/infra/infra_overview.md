# Infrastructure Overview

## Purpose
Describe runtime infrastructure and deployment topology for bot, monitoring, and external signal/risk services.

## Scope
Applies to Docker deployments defined in `hbot/compose/docker-compose.yml`.

## Assumptions
- Docker/Compose available.
- `env/.env` is configured from `env/.env.template`.

## Topology
- Trading network:
  - `bot1`, `bot2`, optional `bot3`
  - `redis`
  - `signal-service`, `risk-service`, `coordination-service`
- Monitoring network:
  - `prometheus`, `grafana`, `node-exporter`, `cadvisor`, `alertmanager`

## Inputs / Outputs
- Inputs: exchange market data and credentials loaded by Hummingbot.
- Outputs: orders/executions on exchange, Redis streams, logs/metrics.

## Failure Modes
- Redis down -> external intent handling degraded, local HB safety remains active.
- Bot container restart -> persistent data/logs survive via bind mounts.
- Monitoring down -> trading can continue, observability degraded.

## Source of Truth
- `hbot/compose/docker-compose.yml`
- `hbot/env/.env.template`

## Owner
- Engineering/Infrastructure
- Last-updated: 2026-02-19

