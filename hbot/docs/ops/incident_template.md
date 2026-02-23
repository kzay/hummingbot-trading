# Incident Report: [TITLE]

## Summary
| Field | Value |
|-------|-------|
| **Severity** | SEV-1 / SEV-2 / SEV-3 |
| **Status** | Active / Mitigated / Resolved |
| **Detected** | YYYY-MM-DD HH:MM UTC |
| **Resolved** | YYYY-MM-DD HH:MM UTC |
| **Duration** | X minutes |
| **Impact** | e.g., "Bot1 placed orders with stale pricing for 5 minutes" |
| **Financial impact** | e.g., "$X estimated loss / no loss" |
| **Affected bots** | bot1, bot4 |
| **Reporter** | Name |

## Timeline
| Time (UTC) | Event |
|------------|-------|
| HH:MM | First anomaly detected (source: alert / manual / log) |
| HH:MM | Investigation started |
| HH:MM | Root cause identified |
| HH:MM | Mitigation applied (describe action) |
| HH:MM | Verification completed |
| HH:MM | Incident resolved |

## Root Cause
Describe the technical root cause in 2-3 sentences.

## Detection
How was the incident detected?
- [ ] Prometheus alert
- [ ] Grafana dashboard observation
- [ ] Slack notification
- [ ] Manual log review
- [ ] Exchange notification

Detection delay: X minutes from first impact to detection.

## Response Actions Taken
1. Action 1 (who, when)
2. Action 2 (who, when)
3. ...

## Evidence
- `reports/kill_switch/latest.json` — kill switch status
- `data/bot1/logs/epp_v24/bot1_a/minute.csv` — last N rows
- `data/bot1/logs/epp_v24/bot1_a/fills.csv` — fills during incident window
- `reports/reconciliation/latest.json` — position reconciliation
- Docker logs: `docker logs hbot-bot1 --since YYYY-MM-DDTHH:MM:SSZ`
- Grafana screenshot: [link]

## Analysis
### What went wrong
- ...

### What went right
- ...

### What was lucky
- ...

## Action Items
| # | Action | Owner | Due | Status |
|---|--------|-------|-----|--------|
| 1 | | | | Open / Done |
| 2 | | | | Open / Done |

## Lessons Learned
- ...

## Metrics
| Metric | Before | During | After |
|--------|--------|--------|-------|
| Daily PnL | | | |
| Drawdown | | | |
| Fill count | | | |
| State | running | hard_stop | running |
