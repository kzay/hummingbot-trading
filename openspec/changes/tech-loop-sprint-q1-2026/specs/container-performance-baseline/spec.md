## container-performance-baseline

Performance baseline for Docker container resource management, CPU/memory right-sizing, and monitoring infrastructure efficiency.

## ADDED Requirements

### Requirement: cadvisor memory limit is sufficient for the container fleet

The `cadvisor` service in `docker-compose.yml` SHALL have a memory limit of at least 256MB. The service SHALL include `--housekeeping_interval=30s` and `--docker_only=true` command-line flags to reduce fs scan frequency and scope. After the change, cadvisor memory usage SHALL remain below 80% of the configured limit under normal operation (27 containers).

### Requirement: realtime-ui-api CPU usage stays below 30% under normal load

The `realtime-ui-api` service SHALL batch stream consumer notifications per read cycle rather than per entry. The default `poll_ms` SHALL be increased from 200 to 500. The full-state broadcast interval SHALL be increased from 30 seconds to 60 seconds. After these changes, CPU usage SHALL drop from ~66% to below 30% under normal message rates (470 ops/s Redis throughput).

### Requirement: Redis XAUTOCLAIM idle threshold is tuned to reduce overhead

All consumer groups using `XAUTOCLAIM` SHALL use an idle threshold of at least 120 seconds (up from 30 seconds). The `COUNT` parameter for XAUTOCLAIM SHALL not exceed 100 per call. After tuning, cumulative XAUTOCLAIM CPU time SHALL decrease by at least 50% compared to the pre-change baseline (44.8 seconds per 10-hour session).

### Requirement: ops-scheduler disk I/O is profiled and bounded

The `ops_scheduler` service SHALL be instrumented with timing metrics on all file read/write operations. The root cause of the anomalous 4GB+ block I/O SHALL be identified and documented. If the cause is repeated full-file rewrites, the write pattern SHALL be changed to append-only or batched.

### Requirement: Container memory limits are evidence-based

Container memory limits SHALL be set to observed peak usage + 30% headroom, rounded to the nearest power-of-two boundary. Specifically:
- cadvisor: 128MB → 256MB
- desk-snapshot: 64MB → 32MB (observed peak 13MB)
- bot7: 512MB → 640MB if stress testing confirms spikes above 400MB

## MODIFIED Requirements

### Requirement: Redis stream trimming uses per-stream MAXLEN where justified

In addition to the uniform `STREAM_RETENTION_MAXLEN` default (50000), the `hb.market_trade.v1` stream SHALL use a MAXLEN of 50000 (down from observed 500K) to match other streams. The `hb.paper_exchange.event.v1` stream (observed 105K) and `hb.audit.v1` (observed 100K) SHALL similarly be capped at 50000 through the existing centralized `xadd()` wrapper.

### Requirement: Docker disk hygiene is maintained

A periodic cleanup process SHALL exist to:
- Prune unused Docker images (`docker image prune -a --filter "until=168h"`)
- Prune build cache older than 7 days (`docker builder prune --filter "until=168h"`)
- Monitor Docker volume usage and alert when total exceeds 300GB

## Metrics to Track Next Cycle

| Metric | Baseline (March 2026) | Target |
|---|---|---|
| cadvisor CPU % | 51% | < 15% |
| cadvisor memory % | 99.5% of 128MB | < 80% of 256MB |
| realtime-ui-api CPU % | 66% | < 30% |
| Redis used_memory | 908MB (46% of 2GB) | < 600MB (30% of 2GB) |
| XAUTOCLAIM cumulative CPU / 10h | 44.8s | < 20s |
| ops-scheduler block I/O / 10h | 9.16GB (R+W) | < 500MB |
| hb.market_trade.v1 XLEN | 500,003 | ≤ 50,000 |
| Docker volume total size | 267.8GB | < 200GB |
