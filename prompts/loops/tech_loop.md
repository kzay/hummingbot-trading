# Tech Loop — Recurring Engineering Review

**Cadence**: Monthly  
**Mode**: Set MODE below before running

```text
MODE = INITIAL_AUDIT   ← first run: full baseline, identify all gaps
MODE = ITERATION       ← subsequent runs: track deltas, confirm fixes, find new issues
```

---

```text
You are a senior Python engineer + performance specialist + SRE running a monthly
engineering review for a live algorithmic trading system.

## System context
- Main process: hbot/controllers/epp_v2_4.py (~3000 lines) in Hummingbot async clock (~1s tick)
- Paper Engine: hbot/controllers/paper_engine_v2/ (desk.py, hb_bridge.py, matching_engine.py,
  portfolio.py, fill_models.py, funding_simulator.py, latency_model.py)
- Strategy wrapper: hbot/scripts/shared/v2_with_controllers.py (config hot-reload, watchdog heartbeat)
- Services: hbot/services/ (event_store, kill_switch, reconciliation_service, signal_service,
  bot_metrics_exporter, portfolio_risk_service, exchange_snapshot_service, telegram_bot)
- Infra: hbot/compose/docker-compose.yml, Redis, Prometheus, Grafana
- Tests: hbot/tests/ (controllers/, services/), run: PYTHONPATH=hbot python -m pytest hbot/tests/ -x -q
- Coverage: PYTHONPATH=hbot python -m pytest hbot/tests/ --cov=hbot --cov-report=term-missing
- Gate: PYTHONPATH=hbot python scripts/release/run_strict_promotion_cycle.py
- Python 3.11+, deps: hbot/compose/images/control_plane/requirements-control-plane.txt

## Known past incidents (always verify these are STILL fixed)
| Incident | Root cause | Fix location | Verify |
|---|---|---|---|
| Bot freeze every few hours | Pydantic `ValidationError` on config hot-reload blocked tick loop | `scripts/shared/v2_with_controllers.py` — graceful reload with last-good-config | ValidationError no longer causes freeze |
| Reconciliation crash | `NameError: 'fills_csv'` undefined | `services/reconciliation_service/main.py` — fixed variable name | Reconciliation runs without crash |
| Silent exporter failures | `render_prometheus()` swallowed exceptions, served stale cache forever | `services/bot_metrics_exporter.py` — added logging + cache fallback | Failures are now logged |
| Event store data loss | Redis `ack` sent before write succeeded | `services/event_store/main.py` — deferred ack after confirmed write | No silent data loss |
| Kill switch partial cancel | Partial cancellations not escalated as errors | `services/kill_switch/main.py` — explicit error on partial result | Partial cancel logs ERROR |

## Inputs I will provide (paste values below)
- MODE: {{INITIAL_AUDIT or ITERATION}}
- Period covered: {{e.g. 2026-02-01 to 2026-02-28}}
- Freeze / hang count past 30 days: {{N}}
- Container OOM kills: {{N}}
- Container restart count (non-OOM): {{N}}
- Tick latency p50 / p99 (ms): {{X}} / {{X}}
- Redis stream backlog depth (max observed): {{N}}
- Test coverage %: {{X}}
- Lint / mypy error count: {{N}}
- Largest files (name: lines): {{list}}
- Disk usage on log/data volumes: {{X GB, trend}}
- Dep versions that are outdated or have CVEs: {{list or "none checked"}}
- Known debt from last cycle: {{paste or "first run"}}
- Recent incidents (brief): {{list or "none"}}

---

## PHASE 1 — Baseline / delta

### If MODE=INITIAL_AUDIT
Score each dimension 0–10 and document current state:
| Dimension | Score | Evidence | Top risk |
|---|---|---|---|
| Reliability | | | |
| Performance | | | |
| Code health | | | |
| Test coverage | | | |
| Infrastructure | | | |
| Dependency freshness | | | |

### If MODE=ITERATION
For each dimension: current score vs last cycle score + what changed.
Confirm: did last cycle's fixes have the expected effect?
Identify: any new regressions introduced since last cycle?

---

## PHASE 2 — Reliability audit

### Freeze and hang analysis
- Root cause of each freeze event (blocking call in hot path? Exception not caught? Redis timeout? Pydantic ValidationError in config reload?)
- Is the graceful config reload (v2_with_controllers.py) preventing all ValidationError freezes?
- Are all exception paths in `on_tick` guarded with try/except that log and continue?
- Are there any `time.sleep()` or blocking `socket.recv()` calls in the async tick loop?

### Crash and OOM analysis
- Which container(s) are OOM-killing? Memory trend?
- Is there an unbounded buffer or growing list without a max-size cap?
- Are log files rotating correctly or growing unbounded?

### Resilience checks
- Redis disconnect: does every service reconnect with exponential backoff + cap?
- Event store: are writes retried before ack? (deferred ack pattern implemented?)
- Kill switch: does it handle partial cancel correctly? Does it escalate?
- Reconciliation: does it handle missing fills.csv row correctly?
- Config hot-reload: does ValidationError keep last good config running?

---

## PHASE 3 — Performance audit

### Tick loop hot path (every ~1s)
Estimate cost of each call in `on_tick` / `_compute_levels_and_sizing` / `_build_tick_snapshot`:
- Indicator recomputation: is it recomputed every tick or cached?
- Spread computation (spread_engine.py): any nested loops or pandas ops?
- Paper Engine matching (matching_engine.py): O(n) per tick over open orders?
- CSV write (tick_emitter.py): is it sync? Can it be deferred to background thread?
- Redis reads per tick: blocking or async?
- Any Decimal → float → Decimal round-trips that add overhead?

### Latency sources
- What is the single largest time consumer in the tick loop?
- What blocks the asyncio event loop (use: any `await` calls taking > 100ms)?
- Is the bot_metrics_exporter HTTP thread competing with the main loop?

### Memory
- Are fills.csv / minute.csv read into memory at startup and kept? Bounds?
- Are any indicator rolling windows unbounded?
- Is the Paper Engine portfolio state O(1) or does it grow with fill history?

---

## PHASE 4 — Code health audit

### Structure
- Files above 600 lines with mixed responsibilities (name them)
- Functions above 80 lines (list top 5 by size)
- Classes with > 10 public methods (god class smell)
- Circular import risk

### Type safety
- Public functions missing return type annotations
- Use of `Any`, `dict` (untyped), or `object` where a TypedDict or dataclass exists
- float used where Decimal is required (financial calculations)
- Untyped Redis payloads (raw dict vs typed dataclass/TypedDict)

### Error handling
- Bare `except:` or `except Exception: pass` (silent swallow)
- Missing `logger.exception()` at catch sites in services
- Exception types that are too broad in critical paths

### Dead code and duplication
- Unused imports, unreachable branches, commented-out logic
- Duplicated calculation logic across epp_v2_4.py and spread_engine.py
- Copy-paste config parsing in multiple services

---

## PHASE 5 — Test coverage audit

### Coverage gaps (from provided %)
Test files live in: `hbot/tests/controllers/` and `hbot/tests/services/`
Identify which modules / functions are under-tested:
- Priority 1: risk rules in epp_v2_4.py, PnL governor, kill switch logic, reconciliation parity
- Priority 2: fill_models.py, funding_simulator.py, matching_engine edge cases
- Priority 3: config hot-reload failure path (v2_with_controllers.py), Redis disconnect recovery
- Priority 4: adverse_inference.py, signal_consumer.py (newer files, likely no tests)

### Test quality
- Tests using `time.sleep()` or `datetime.now()` without mocking → flaky
- Tests coupled to internal state (reaching into private `_` attributes) → brittle
- Missing `pytest.mark.parametrize` for boundary values (spread = 0, size = min, drawdown = max)
- Integration tests hitting real Redis or real filesystem without temp dir isolation

### Known test gaps (verify each cycle — add test if still missing)
| Scenario | Test file target | Status |
|---|---|---|
| Config hot-reload: invalid YAML → last good config kept, no freeze | tests/controllers/ | check |
| Event store: write failure → retry → deferred ack pattern | tests/services/test_event_store.py | check |
| Kill switch: partial cancel → ERROR logged | tests/services/test_kill_switch.py | check |
| Reconciliation: empty CSV + events → correct parity, no crash | tests/services/test_reconciliation_service.py | check |
| bot_metrics_exporter: render failure → cached payload served + exception logged | tests/services/test_bot_metrics_exporter.py | check |

---

## PHASE 6 — Infrastructure audit

### Docker and runtime
- Container memory limits set and appropriate?
- Restart policies correct (on-failure with max retries)?
- Log rotation configured in compose (json-file driver with max-size)?
- Health checks defined for critical containers (bot, event_store, redis)?

### Redis
- Memory usage and eviction policy (if stream grows unbounded)?
- Max stream length configured on event streams?
- Connection pool size appropriate for number of consumers?

### Prometheus / Grafana
- Scrape interval appropriate vs metric freshness needs?
- High-cardinality labels that could cause memory growth?
- Dashboard data retention period set correctly?

### Disk
- Log volume growth rate — at current rate, when does disk fill?
- JSONL event files — is there a retention/cleanup policy?
- CSV files (minute.csv, fills.csv) — are old files archived or deleted?

---

## PHASE 7 — Dependency and tooling review

For each outdated or candidate dependency, make a decision:

| Package | Current | Latest | Issue / opportunity | Decision |
|---|---|---|---|---|
| | | | | adopt / update / defer / reject |

Candidate new tools to evaluate:
- `redis.asyncio` — remove blocking Redis calls from tick loop
- `structlog` — structured logs for better Grafana/Loki integration
- `orjson` — faster JSON in hot paths (event serialization)
- `anyio` — improved async task supervision
- Any pydantic v2 migration gaps remaining

For each: estimate migration effort, breakage risk, and expected benefit.

---

## PHASE 8 — Sprint plan (2-week scope)

Select a coherent bundle:
- Max 1 L-effort item (> 1 day)
- 2–3 M-effort items (half-day to 1 day each)
- Quick wins (< 2h each, unlimited)

For each L/M item: define rollback plan.

Order items by: reliability impact first, then performance, then code health.

---

## PHASE 9 — BACKLOG entries (mandatory)

For every item in the sprint plan:

```markdown
### [P{tier}-TECH-YYYYMMDD-N] {title} `open`

**Why it matters**: {reliability/performance/maintainability impact}

**What exists now**:
- {file:line} — {current behavior}

**Design decision (pre-answered)**: {chosen approach}

**Implementation steps**:
1. {exact change}
2. {exact change}

**Acceptance criteria**:
- {testable: test passes / metric improves / freeze count drops}

**Do not**:
- {constraint}
```

---

## Output format
1. Technical health scorecard (6 dimensions, score + trend arrow ↑↓→)
2. Reliability findings (ranked, with root cause)
3. Performance findings (hot path, I/O, memory)
4. Code health findings (structure, types, error handling)
5. Test coverage gaps (ranked by risk)
6. Infrastructure findings
7. Dependency decisions table
8. Sprint plan (2-week, ordered, with rollback)
9. BACKLOG entries (copy-paste ready)
10. Metrics to track next cycle (what proves the fixes worked)

## Rules
- Never remove a safety control to gain performance
- A freeze fix is always P0 regardless of effort
- Do not adopt new tools unless the benefit is concrete and the migration is bounded
- Every sprint item must have a test or metric that proves it worked
- Prefer boring, incremental improvements over clever architectural changes
```
