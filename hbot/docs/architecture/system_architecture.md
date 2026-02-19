# System Architecture

## Purpose
Provide the high-level architecture for trading, orchestration, and monitoring.

## Scope
Containerized runtime and inter-service data/control paths.

## Diagram
```mermaid
flowchart LR
  subgraph hbLayer [HummingbotLayer]
    bot1[bot1]
    bot2[bot2]
    bridge[HBBridge]
  end
  subgraph extLayer [ExternalServices]
    redis[Redis]
    signal[SignalService]
    risk[RiskService]
    coord[CoordinationService]
  end
  subgraph monLayer [Monitoring]
    prom[Prometheus]
    grafana[Grafana]
    alerts[Alertmanager]
  end
  bot1 --> bridge
  bot2 --> bridge
  bridge --> redis
  redis --> signal
  signal --> redis
  redis --> risk
  risk --> redis
  redis --> coord
  coord --> redis
  redis --> bridge
  bot1 --> prom
  bot2 --> prom
  prom --> grafana
  prom --> alerts
```

## Key Principles
- Hummingbot remains execution gateway and final local safety.
- External services coordinate signal/risk independently.
- Monitoring separated from trading control plane.

## Owner
- Architecture/Platform
- Last-updated: 2026-02-19

