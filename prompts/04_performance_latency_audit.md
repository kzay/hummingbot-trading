# Performance & Latency Audit

```text
You are a performance engineer specialized in low-latency/event-driven trading systems.

Audit this bot project for performance risks and operational bottlenecks.

## Goal
Identify issues impacting:
- response to market events
- order placement/cancel latency
- event backlog / loop blocking
- CPU/memory growth
- logging overhead
- data processing efficiency
- multi-bot scaling on one machine

## Analyze
- async/task patterns and blocking calls
- CPU-heavy indicator computations in hot paths
- repeated recalculations that should be cached
- I/O and logging frequency (sync writes, CSV writes per event)
- memory leaks / growing arrays/buffers
- inefficient pandas usage or object churn
- lock contention / shared resources
- retry storms / reconnection loops
- per-symbol/per-bot scaling behavior

## Deliverables
1. Hot Path Map
2. Performance Risk Findings (ranked)
3. Probable Latency Sources
4. Instrumentation Plan
5. Optimization Plan (quick wins / medium refactors / architecture upgrades)
6. Multi-Bot Capacity Estimate

## Extra
Propose metrics: event processing lag, order ack latency, ws reconnect count, indicator compute time, queue depth, loop jitter.
```
