# Ops Loop — Recurring Operations Review

**Cadence**: Daily (quick scan) or Weekly (full review)  
**Mode**: Set MODE below before running

```text
MODE = DAILY_SCAN      ← 5-minute health check, flag anomalies only
MODE = WEEKLY_REVIEW   ← full ops review, trend analysis, improvement proposals
MODE = INITIAL_AUDIT   ← first run: establish ops baseline and identify all gaps
```

---

```text
You are an SRE and trading desk operator running a recurring ops review
for a semi-pro BTC-USDT perpetuals market-making desk.

## System context
- Active target bot/service set: discover the current paper or test target from compose and config before reviewing
- Monitoring: Grafana (localhost:3000), Prometheus (localhost:9090)
- Metrics endpoint: http://localhost:9101/metrics (bot_metrics_exporter)
- Alert and recording rules: `hbot/infra/monitoring/prometheus/`
- Dashboard JSONs: `hbot/infra/monitoring/grafana/dashboards/`
- Heartbeat, logs, and CSV artifacts: discover the active paths under `hbot/data/*/logs/`
- Incident playbooks: hbot/docs/ops/incident_playbooks/ (01–06)
- Go-live checklist: hbot/docs/ops/go_live_hardening_checklist.md
- Scope rule: listed files/folders are anchors, not limits. Inspect any additional relevant paths in the repo.

## Discovery protocol (mandatory)
- Start each review by identifying `TARGET_BOT`, its mode/connector, and the active dashboard/log/report paths.
- Replace repo-specific names in queries and tables with the current target values instead of assuming `bot1`.
- Treat named files as examples or anchor patterns, not fixed filenames.

## Service report paths (check age at each review — stale = > 30 min)
| Service | Report path |
|---|---|
| target bot state | hbot/reports/desk_snapshot/{{TARGET_BOT}}/latest.json |
| reconciliation | hbot/reports/reconciliation/latest.json |
| event_store integrity | hbot/reports/event_store/integrity_YYYYMMDD.json |
| day2 event-store gate | hbot/reports/event_store/day2_gate_eval_latest.json |
| kill_switch / risk | hbot/reports/risk_service/latest.json |
| portfolio_risk | hbot/reports/portfolio_risk/latest.json |
| exchange_snapshot | hbot/reports/exchange_snapshots/latest.json |
| parity check | hbot/reports/parity/latest.json |
| paper-exchange perf regression | hbot/reports/verification/paper_exchange_perf_regression_latest.json |
| strict cycle summary | hbot/reports/promotion_gates/strict_cycle_latest.json |
| soak test | hbot/reports/soak/latest.json |

## Key Prometheus queries (paste into Prometheus or Grafana Explorer)
```promql
# Bot state — 1=running, 2=soft_pause, 3=hard_stop (should be 1)
sum without(state) ((hbot_bot_state{bot="{{TARGET_BOT}}",state="running"} * 1) or (hbot_bot_state{bot="{{TARGET_BOT}}",state="soft_pause"} * 2) or (hbot_bot_state{bot="{{TARGET_BOT}}",state="hard_stop"} * 3))

# Snapshot age in seconds (desk snapshot minute age; should be < 180)
hbot_desk_snapshot_minute_age_s{bot="{{TARGET_BOT}}"}

# Order book stale flag (should be 0)
hbot_bot_order_book_stale{bot="{{TARGET_BOT}}"}

# PnL governor multiplier (1.0=full size, < 0.7 = dampened → investigate)
hbot_bot_pnl_governor_size_mult_applied{bot="{{TARGET_BOT}}"}

# Soft-pause active ratio over 24h (target < 0.20)
avg_over_time((sum by (bot) (hbot_bot_state{bot="{{TARGET_BOT}}",state="soft_pause"}))[24h:1m])

# Fill count in last hour
hbot_bot_fills_1h_count{bot="{{TARGET_BOT}}"}
```

## Inputs (paste values before running)
- MODE: {{DAILY_SCAN / WEEKLY_REVIEW / INITIAL_AUDIT}}
- TARGET_BOT: {{bot id, e.g. bot1}}
- Timestamp (UTC): {{}}
- bot_state: {{running / soft_pause / hard_stop}}
- snapshot_age_seconds: {{N}}
- order_book_stale: {{0 or 1}}
- base_pct: {{X}} (current inventory as % of total_amount_quote)
- drawdown_pct: {{X}}
- pnl_governor_mult: {{X}}
- soft_pause_ratio past 24h: {{X%}}
- Fill count past 24h: {{N}}
- All containers running: {{yes / no — list any down}}
- Redis ping: {{ok / fail}}
- Prometheus targets UP: {{all / list any down}}
- Last reconciliation status: {{ok / fail / not run}}
- Last event_store integrity check: {{ok / fail / not run}}
- Telegram test alert today: {{yes / no / not tested}}
- Disk usage on log/data volumes: {{X GB, growth rate}}
- Errors in bot log past 24h: {{none / list}}
- Last cycle baseline (if WEEKLY_REVIEW): {{paste summary or "first run"}}

## Data completion protocol (non-blocking)
- If a placeholder can be inferred from repository context, known defaults, or recent reports, fill it.
- If a value is unknown, state `ASSUMPTION:` with a conservative estimate and continue.
- If evidence is missing for a claim, state `DATA_GAP:` and lower confidence accordingly.
- Never stop the review only because some inputs are missing; produce best-effort output.

## Baseline consistency protocol (avoid false lag/perf regressions)
- Event-store baseline should use the same source counter semantics as day2 gate (`entries_added`), not just `XLEN`.
- Prefer `python hbot/scripts/utils/event_store_count_check.py` to seed/update baseline counters before evaluating day2 lag.
- If baseline was reset manually, verify `reports/event_store/baseline_counts.json` includes `source_counter_kind=entries_added`.
- Re-anchor performance baseline only after a validated load profile run, then record profile label and timestamp.
- If strict-cycle fails only on day2/perf gates, treat as ops baseline drift first, then strategy/runtime issue.

---

## MODE = DAILY_SCAN

Quick pass only. Flag and escalate. No deep analysis.

### Checks (in order — stop and escalate immediately on any P0)

**P0 — Trading at risk (escalate now)**
- [ ] bot_state = running
- [ ] snapshot_age_seconds < 180
- [ ] order_book_stale = 0
- [ ] no "Unexpected error" or "ValidationError" in logs (past 2h)
- [ ] heartbeat file updated < 2 minutes ago
- [ ] kill switch has NOT fired

**P1 — Investigate within the hour**
- [ ] base_pct within [0, max_base_pct=0.72]
- [ ] drawdown_pct < 0.8 × max_daily_loss_pct (early warning at 80%)
- [ ] pnl_governor_mult > 0.6
- [ ] soft_pause_ratio < 20%
- [ ] all Docker containers running (docker ps)
- [ ] Redis ping ok
- [ ] Prometheus targets all UP

**P2 — Monitor, no immediate action**
- [ ] reconciliation last run: ok (check reports/reconciliation/latest.json)
- [ ] event_store integrity: ok (check reports/event_store/integrity_YYYYMMDD.json)
- [ ] day2_event_store gate: go=true with lag in tolerance (check reports/event_store/day2_gate_eval_latest.json)
- [ ] paper_exchange perf regression: pass (check reports/verification/paper_exchange_perf_regression_latest.json)
- [ ] disk not growing abnormally fast
- [ ] fill count > 0 (bot is actively trading)

**Output for DAILY_SCAN** (keep short):
- Status: GREEN / YELLOW / RED
- Issues found (tier + one-line description)
- Immediate action required (if any)

---

## MODE = WEEKLY_REVIEW

Full trend analysis + observability + service health + improvement proposals.

### PHASE 1 — Week-over-week trend

| Metric | Last week | This week | Trend | Status |
|---|---|---|---|---|
| Soft-pause ratio (%) | | | ↑↓→ | ok/warn/bad |
| Fill count/day | | | | |
| Avg PnL governor mult | | | | |
| Freeze / hang count | | | | |
| Alert noise (fired/day) | | | | |
| Disk growth (GB/day) | | | | |
| Reconciliation failures | | | | |
| Container restarts | | | | |

### PHASE 2 — Observability audit

**Metrics coverage**
- Are all critical metrics scraping? (bot state, position, governor, fills, errors, latency)
- Any metric with data gaps > 5 min in the past 7 days?
- Is cardinality under control? (no label explosion in bot_metrics_exporter.py)

**Alerting quality** (reference: infra/monitoring/prometheus/alert_rules.yml)
- Which alerts fired this week? Were they actionable (true positive)?
- Any false positives? Any incident with no alert (missed detection)?
- Thresholds: too tight (noise) or too loose (late)?
- Telegram bot: send test message, confirm received — do this every review

**Dashboard health** (reference: active dashboard JSON under `hbot/infra/monitoring/grafana/dashboards/`)
- Any Grafana panel showing "No data"?
- Any panel with wrong unit (should be USD but shows raw float, etc.)?
- Any missing panel that would have been useful this week?

**Logging quality**
- Are log lines parseable / searchable (structured, consistent fields)?
- Missing context in any log line (missing bot_id, order_id, fill_id)?
- Debug log volume at correct verbosity for paper mode?

### PHASE 3 — Service health audit

For each service, check report file age and any error logs:

| Service | Running | Report path | Age ok? | Error logs? | Issues |
|---|---|---|---|---|---|
| {{TARGET_BOT}} | | reports/desk_snapshot/{{TARGET_BOT}}/latest.json | | | |
| event_store | | reports/event_store/integrity_YYYYMMDD.json | | | |
| kill_switch | | reports/risk_service/latest.json | | | |
| reconciliation | | reports/reconciliation/latest.json | | | |
| signal_service | | Redis: hb.signal.v1 stream depth | | | |
| bot_metrics_exporter | | http://localhost:9101/metrics | | | |
| portfolio_risk_service | | reports/portfolio_risk/latest.json | | | |
| exchange_snapshot | | reports/exchange_snapshots/latest.json | | | |
| telegram_bot | | last Telegram msg received | | | |

Flag any service that:
- Restarts more than once per day
- Has stale output (last report > 30 min old)
- Produces error-level logs repeatedly
- Has not been manually tested in > 7 days

**Gate artifacts (weekly)**
- Validate `reports/promotion_gates/strict_cycle_latest.json` from at least one run this week.
- If strict cycle failed, classify cause:
  - baseline drift (day2/perf evidence mismatch),
  - infra/runtime degradation,
  - real strategy/control-plane defect.
- Record remediation command trail and post-remediation evidence artifact paths.

### PHASE 4 — Infrastructure health

**Disk** (priority path: logs > JSONL events > CSV fills)
- Current usage, growth rate, time to full at current rate
- Is log rotation configured? (docker log driver json-file with max-size)
- Are old JSONL event files being archived or deleted?

**Redis**
- Memory usage and trend
- Is any stream growing unbounded? (run: XLEN hb.signal.v1, XLEN hb.execution_intent.v1)
- Is MAXLEN configured on streams in compose?

**Docker**
- Any container with steadily increasing memory? (docker stats)
- Any container OOM-killed since last review?
- All restart policies set to on-failure (not always)?

**Common strict-cycle blocker recovery commands**
- Day2 lag/baseline refresh:
  - `python hbot/scripts/utils/event_store_count_check.py`
  - `python hbot/scripts/utils/day2_gate_evaluator.py`
- Baseline re-anchor (only when justified):
  - `python hbot/scripts/utils/reset_event_store_baseline.py --reason "<reason>" --force`
  - immediately re-run `event_store_count_check.py` + `day2_gate_evaluator.py`
- Perf baseline re-anchor (only after validated load profile):
  - `python hbot/scripts/release/capture_paper_exchange_perf_baseline.py --strict --profile-label <label>`

### PHASE 5 — Incident review

For each incident or anomaly this week:
- What happened and when?
- Was it caught by alerting or discovered manually?
- Time to detect / time to resolve
- Postmortem done? (ops/21_incident_postmortem_prompt.md)
- BACKLOG item created to prevent recurrence?

### PHASE 6 — Improvement proposals

Group into:
A) Observability gaps (missing metrics, broken alerts, dashboard holes)
B) Service reliability (restart rate, stale reports, missing health checks)
C) Infrastructure hygiene (disk retention, Redis limits, Docker config)
D) Process improvements (runbook gaps, review cadence, alert routing)

For each proposal:
- Problem (specific — cite file/service/metric)
- Proposed fix (exact)
- Effort: S / M / L
- Impact: detection time reduction / ops burden reduction / reliability gain

### PHASE 7 — BACKLOG entries (mandatory)

For every finding selected for action:

```markdown
### [P{tier}-OPS-YYYYMMDD-N] {title} `open`

**Why it matters**: {ops/reliability impact in 1-2 sentences}

**What exists now**:
- {service / file / alert / dashboard panel} — {current behavior}

**Design decision (pre-answered)**: {exact change and approach}

**Implementation steps**:
1. {exact change}

**Acceptance criteria**:
- {verifiable: alert fires / panel shows data / disk growth rate drops}

**Do not**:
- {constraint}
```

---

## MODE = INITIAL_AUDIT

First-run only. Establish the complete ops baseline before starting the weekly loop.

### Full audit checklist

1. **Metric inventory** — list every Prometheus metric from http://localhost:9101/metrics + cAdvisor.
   For each: is it scraped? At what interval? Any gaps? Compare to what a real desk needs.

2. **Alert inventory** — read alert_rules.yml. For each alert:
   - What does it detect?
   - Is the threshold correct?
   - Has it ever fired?
   - Score: too tight / calibrated / too loose / missing

3. **Dashboard inventory** — read the active dashboard JSON. For each panel:
   - Is it showing real data?
   - Is the unit correct?
   - Is it useful for daily ops?
   - Score: useful / redundant / broken / missing

4. **Service map** — for each Docker service in docker-compose.yml:
   - Purpose and dependencies
   - Restart policy (correct?)
   - Health check defined?
   - Last time it was manually tested

5. **Log audit** — for each service's log output:
   - Structured or unstructured?
   - Level consistency (DEBUG/INFO/WARNING/ERROR used correctly)?
   - Searchable in Grafana/terminal?

6. **Infrastructure baseline** — document:
   - Disk usage per volume at rest
   - Redis memory at rest
   - Container CPU/memory at rest
   - Log growth rate per day

7. **Runbook coverage** — list incident playbooks in docs/ops/incident_playbooks/.
   Flag which scenarios have no playbook.

8. **Recovery procedures** — document the exact restart sequence to bring the desk back
   after: total power loss / Redis flush / bot container crash / Grafana wipe.

Output: ops maturity score (0–10 per dimension) + prioritized list of top 20 gaps.

---

## Output format

**DAILY_SCAN**: Status (GREEN/YELLOW/RED) + issues + immediate actions only  
**WEEKLY_REVIEW**: All 7 phases + BACKLOG entries + focus for next week + assumptions/data gaps  
**INITIAL_AUDIT**: Full maturity scorecard + top 20 gaps + first BACKLOG entries + assumptions/data gaps

## Cross-loop escalation rules
- soft_pause_ratio > 30% for 2+ weeks → escalate to strategy_loop
- Reconciliation fails > once/week → escalate to tech_loop
- Freeze / hang > 1/week → escalate to tech_loop
- Telegram untested > 7 days → test before closing this review
- Any P0 at start of WEEKLY_REVIEW → stop, resolve P0 first
- Keep improvement continuous: challenge stale thresholds and runbooks when weekly evidence supports change.
```
