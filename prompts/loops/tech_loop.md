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
engineering review for a live algorithmic trading system (BTC-USDT perpetual futures,
paper trading primary, multi-bot architecture with market-making and directional lanes).

## System context

### Core runtime
- Runtime kernel (decomposed mixins): `hbot/controllers/runtime/kernel/`
  - `controller.py` — SharedRuntimeKernel base
  - `quoting_mixin.py`, `supervisory_mixin.py`, `state_mixin.py`,
    `startup_mixin.py`, `regime_mixin.py`, `market_mixin.py`
  - `config.py` — runtime config classes
- Strategy adapter: `hbot/controllers/epp_v2_4.py` (thin adapter over kernel)
- Directional base: `hbot/controllers/runtime/base.py`

### Strategy lanes (isolated per bot)
- Market-making: `hbot/controllers/bots/bot1/`
- Directional: `hbot/controllers/bots/bot5/`, `bot6/`, `bot7/`
- Isolation contract: `hbot/tests/controllers/test_strategy_isolation_contract.py`

### Simulation engine
- Paper simulation: `hbot/simulation/` (desk, matching_engine, portfolio, risk_engine,
  adverse_inference, funding_simulator, fee_models, latency_model, budget_checker)
- Paper bridge: `hbot/simulation/bridge/` (hb_bridge, signal_consumer, event_fire)
- Backward-compat shim: `hbot/controllers/paper_engine_v2/` (re-export only)

### Platform library
- Shared infra (strategy-agnostic): `hbot/platform_lib/`
  - `core/`, `market_data/`, `execution/`, `logging/`, `contracts/`

### ML pipeline
- Feature engineering: `hbot/controllers/ml/feature_pipeline.py`, `_indicators.py`
- Model registry: `hbot/controllers/ml/model_registry.py`
- Label generation: `hbot/controllers/ml/label_generator.py`
- Research: `hbot/controllers/ml/research.py`
- ML feature service: `hbot/services/ml_feature_service/`
- Dataset builders: `hbot/scripts/ml/`

### Research / exploration system
- LLM-driven strategy exploration: `hbot/controllers/research/`
  - exploration_session.py, exploration_prompts.py, llm_client.py,
    experiment_orchestrator.py, hypothesis_registry.py, robustness_scorer.py
- Explore CLI: `hbot/controllers/research/explore_cli.py`
- Research reports: `hbot/data/research/`

### Backtesting / data pipeline
- Data catalog: `hbot/controllers/backtesting/data_catalog.py`
- Data store: `hbot/controllers/backtesting/data_store.py`
- Data requirements: `hbot/controllers/backtesting/data_requirements.py`
- Historical data: `hbot/data/historical/`

### Services (26+ microservices)
- Runtime wrappers: `hbot/scripts/shared/v2_with_controllers.py`
- Critical services: event_store, kill_switch, reconciliation_service,
  bot_metrics_exporter, signal_service, exchange_snapshot_service
- Operational services: ops_db_writer, ops_scheduler, telegram_bot,
  shadow_execution, portfolio_allocator, portfolio_risk_service
- Data services: ml_feature_service, market_data_service, desk_snapshot_service
- UI services: realtime_ui_api (+ apps/realtime_ui_v2/)
- Coordination: coordination_service, execution_gateway

### Infrastructure
- Compose: `hbot/infra/compose/docker-compose.yml`
- Monitoring: `hbot/infra/monitoring/` (Prometheus, Grafana, Alertmanager)
- Observability contract: `hbot/infra/monitoring/OBSERVABILITY_CONTRACT.md`
- Dependencies: `hbot/infra/compose/images/*/requirements-*.txt`
- Env template: `hbot/infra/env/.env.template`

### Tests and gates
- Unit tests: `hbot/tests/` (controllers/, services/, architecture/)
- Architecture contracts: `hbot/tests/architecture/` (import boundaries, regression baseline)
- Run: `PYTHONPATH=hbot python -m pytest hbot/tests/ -x -q --ignore=hbot/tests/integration`
- Coverage: `PYTHONPATH=hbot python -m pytest hbot/tests/ --cov=hbot --cov-report=term-missing`
- Promotion gates: `hbot/scripts/release/run_strict_promotion_cycle.py`
- Backlog: `hbot/BACKLOG.md`

### Scope rule
Listed files/folders are anchors, not limits. Inspect any additional relevant paths.

## Discovery protocol (mandatory)
1. Verify the active controller entrypoint by checking `hbot/controllers/runtime/kernel/controller.py`
   and the strategy adapter `hbot/controllers/epp_v2_4.py`.
2. List running containers from `docker-compose.yml` to identify the active service set.
3. Check each strategy lane under `hbot/controllers/bots/` for any new bots or removed bots.
4. Verify `hbot/tests/architecture/` contract tests still pass.
5. If a component moved, review the current equivalent and note the substitution.
6. Check `hbot/BACKLOG.md` header for current promotion gate status.
7. Read `hbot/infra/monitoring/OBSERVABILITY_CONTRACT.md` for current metric namespace rules.

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
- Architecture contract test result (pass/fail): {{X}}
- Lint / mypy error count: {{N}}
- Largest files (name: lines): {{list}}
- Disk usage on log/data volumes: {{X GB, trend}}
- Dep versions that are outdated or have CVEs: {{list or "none checked"}}
- Active bot count and lanes: {{e.g. bot1=MM-paper, bot7=directional-paper}}
- ML model staleness (days since last retrain): {{N or "no models deployed"}}
- Known debt from last cycle: {{paste or "first run"}}
- Recent incidents (brief): {{list or "none"}}
- Last cycle's sprint items and their outcomes: {{list or "first run"}}

## Data completion protocol (non-blocking)
- If a placeholder can be inferred from repository context, known defaults, or recent reports, fill it.
- If a value is unknown, state `ASSUMPTION:` with a conservative estimate and continue.
- If evidence is missing for a claim, state `DATA_GAP:` and reduce confidence for that finding.
- Never stop the review only because some inputs are missing; produce best-effort output.
- When filling assumptions, cite the source of inference (e.g. "from docker-compose.yml mem_limit").

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
| Architecture contracts | | | |
| Strategy isolation | | | |

### If MODE=ITERATION
For each dimension: current score vs last cycle score + what changed.
Confirm: did last cycle's fixes have the expected effect?
Identify: any new regressions introduced since last cycle?
Report: which of last sprint's items were completed vs deferred?

---

## PHASE 2 — Architecture contract verification

### Import boundaries (automated check)
- Run: `PYTHONPATH=hbot python -m pytest hbot/tests/architecture/test_import_boundaries.py -v`
- Rules enforced:
  1. `platform_lib/` must NOT import controllers, services, or simulation
  2. `simulation/` must NOT import controllers or services (exception: bridge → execution_gateway)
  3. `controllers/` must NOT import services (exception: paper_engine_v2 shim)
  4. No cross-service imports
- If any violations exist, list them as P0 findings.

### Strategy isolation
- Run: `PYTHONPATH=hbot python -m pytest hbot/tests/controllers/test_strategy_isolation_contract.py -v`
- Verify: shared/runtime code (`controllers/runtime/*`, `epp_v2_4.py`, `regime_detector.py`,
  `spread_engine.py`, `tick_emitter.py`) does not import `controllers/bots/*`
- Verify: no strategy lane imports another lane
- Verify: `DirectionalRuntimeController` extends `SharedRuntimeKernel`, not `EppV24Controller`

### Regression baseline
- Run: `PYTHONPATH=hbot python -m pytest hbot/tests/architecture/test_regression_baseline.py -v`
- Confirm test counts have not dropped below baseline

### Zero-tolerance checks (from project rules)
- Zero `print()` in production code (controllers/services/simulation/platform_lib, excluding CLI dirs)
- All `except Exception: pass` blocks have justification comments
- All `# type: ignore` comments have mypy error codes
- Minimum test counts per module area (controllers≥50, services≥50, architecture≥5)

---

## PHASE 3 — Reliability audit

### Freeze and hang analysis
- Root cause of each freeze event (blocking call in hot path? Exception not caught?
  Redis timeout? Pydantic ValidationError in config reload?)
- Is the graceful config reload (v2_with_controllers.py) preventing all ValidationError freezes?
- Are all exception paths in kernel mixins (`on_tick`, `_compute_levels_and_sizing`,
  `_build_tick_snapshot`) guarded with try/except that log and continue?
- Are there any `time.sleep()` or blocking `socket.recv()` calls in the async tick loop?
- Do kernel mixins (`quoting_mixin.py`, `supervisory_mixin.py`, `state_mixin.py`)
  handle internal exceptions without propagating to the parent tick loop?

### Crash and OOM analysis
- Which container(s) are OOM-killing? Memory trend?
- Is there an unbounded buffer or growing list without a max-size cap?
- Are log files rotating correctly or growing unbounded?
- Check: ML feature service memory usage (model loading, feature caching)
- Check: ops_db_writer database connection pool leaks

### Resilience checks
- Redis disconnect: does every service reconnect with exponential backoff + cap?
- Event store: are writes retried before ack? (deferred ack pattern implemented?)
- Kill switch: does it handle partial cancel correctly? Does it escalate?
- Reconciliation: does it handle missing fills.csv row correctly?
- Config hot-reload: does ValidationError keep last good config running?
- Signal consumer: does it handle missed Redis stream entries gracefully?
- Paper exchange bridge: does it recover from matching engine state corruption?
- Shadow execution: does it degrade gracefully when shadow fills diverge?

### Multi-bot resilience
- If one bot crashes, do other bots continue operating independently?
- Are shared services (event_store, Redis) properly namespaced per bot?
- Is there a coordination deadlock risk between bots via shared resources?

---

## PHASE 4 — Performance audit

### Tick loop hot path (every ~1s)
Trace through the kernel mixin call chain:
- `controller.on_tick()` → `startup_mixin` → `state_mixin._build_tick_snapshot()`
  → `regime_mixin` → `quoting_mixin._compute_levels_and_sizing()` → `supervisory_mixin`
- Estimate cost of each mixin in the chain

Specific checks:
- Indicator recomputation (`controllers/ml/_indicators.py`): cached or recomputed every tick?
- Spread computation (`spread_engine.py`): any nested loops or pandas ops?
- Paper Engine matching (`simulation/matching_engine.py`): O(n) per tick over open orders?
- CSV write (tick_emitter.py): sync or deferred to background thread?
- Redis reads per tick: blocking or async?
- Any Decimal → float → Decimal round-trips that add overhead?
- ML feature lookups: are they cached or re-fetched per tick?
- Regime detection: frequency of recalculation vs tick frequency?

### Latency sources
- What is the single largest time consumer in the tick loop?
- What blocks the asyncio event loop (any `await` calls taking > 100ms)?
- Is the bot_metrics_exporter HTTP thread competing with the main loop?
- Are ops_db_writer ingestions creating backpressure on Redis streams?

### Memory
- Are fills.csv / minute.csv read into memory at startup and kept? Bounds?
- Are any indicator rolling windows unbounded?
- Is the Paper Engine portfolio state O(1) or does it grow with fill history?
- Historical data parquet files: are they loaded lazily or eagerly?
- ML model sizes in memory (model_registry.py)
- Research exploration session artifacts: cleaned up after session ends?

---

## PHASE 5 — Code health audit

### Structure
- Files above 600 lines with mixed responsibilities (name them)
- Functions above 80 lines (list top 5 by size)
- Classes with > 10 public methods (god class smell)
- Circular import risk
- Kernel mixins: is each mixin focused on a single responsibility?
- Are there any kernel mixins that have grown beyond their original scope?

### Type safety
- Public functions missing return type annotations
- Use of `Any`, `dict` (untyped), or `object` where a TypedDict or dataclass exists
- float used where Decimal is required (financial calculations)
- Untyped Redis payloads (raw dict vs typed dataclass/TypedDict)
- ML pipeline: are feature vectors typed (numpy dtype, dataclass)?
- Research system: are LLM response schemas validated (StrategyCandidate)?

### Error handling
- Bare `except:` or `except Exception: pass` (silent swallow)
- Missing `logger.exception()` at catch sites in services
- Exception types that are too broad in critical paths
- Kernel mixin exception boundaries: does a failure in one mixin poison others?

### Dead code and duplication
- Unused imports, unreachable branches, commented-out logic
- Duplicated calculation logic across kernel mixins
- Copy-paste config parsing in multiple services
- Orphaned strategy lane files (old bot configs without active bot)
- Paper_engine_v2 shim: is it still needed or can it be removed?

---

## PHASE 6 — Test coverage audit

### Coverage gaps (from provided %)
Test files live in: `hbot/tests/controllers/`, `hbot/tests/services/`, `hbot/tests/architecture/`
Identify which modules / functions are under-tested:
- Priority 1: risk rules in kernel mixins (`supervisory_mixin`, `quoting_mixin`),
  PnL governor, kill switch logic, reconciliation parity
- Priority 2: simulation engine edge cases (matching_engine, adverse_inference,
  budget_checker, funding_simulator)
- Priority 3: config hot-reload failure path (v2_with_controllers.py),
  Redis disconnect recovery, signal_consumer error paths
- Priority 4: ML pipeline (feature_pipeline, model_registry, label_generator)
- Priority 5: research system (exploration_session, robustness_scorer, hypothesis_registry)
- Priority 6: data pipeline (data_catalog, data_store, data_requirements)

### Test quality
- Tests using `time.sleep()` or `datetime.now()` without mocking → flaky
- Tests coupled to internal state (reaching into private `_` attributes) → brittle
- Missing `pytest.mark.parametrize` for boundary values (spread = 0, size = min, drawdown = max)
- Integration tests hitting real Redis or real filesystem without temp dir isolation
- Architecture contract tests: do they cover all current module areas?

### Known test gaps (verify each cycle — add test if still missing)
| Scenario | Test file target | Status |
|---|---|---|
| Config hot-reload: invalid YAML → last good config kept, no freeze | tests/controllers/ | check |
| Event store: write failure → retry → deferred ack pattern | tests/services/test_event_store.py | check |
| Kill switch: partial cancel → ERROR logged | tests/services/test_kill_switch.py | check |
| Reconciliation: empty CSV + events → correct parity, no crash | tests/services/test_reconciliation_service.py | check |
| bot_metrics_exporter: render failure → cached payload + exception logged | tests/services/test_bot_metrics_exporter.py | check |
| Kernel mixin isolation: exception in one mixin → others continue | tests/controllers/test_kernel/ | check |
| Strategy isolation contract: no cross-lane imports | tests/controllers/ | check |
| ML feature pipeline: stale model fallback | tests/controllers/test_ml/ | check |
| Research session: LLM parse error → retry and continue | tests/controllers/test_research/ | check |
| Data catalog: gap detection in historical data | tests/controllers/test_backtesting/ | check |
| Paper exchange bridge: state recovery after crash | tests/test_simulation/ | check |
| Multi-bot: shared Redis namespace isolation | tests/services/ | check |

---

## PHASE 7 — ML pipeline audit

### Model lifecycle
- When were models last retrained? (check `hbot/data/ml/` file dates)
- Is there a staleness threshold that triggers retraining or fallback?
- Does model_registry.py validate model integrity on load?
- Are model artifacts versioned and reproducible?

### Feature pipeline
- Are features computed deterministically (same input → same output)?
- Is there train/serve skew between offline training and live inference?
- Are feature importance metrics tracked to detect drift?
- Does `_indicators.py` share code with the backtesting pipeline or are there duplicates?

### ML feature service
- Memory footprint of loaded models?
- Latency of feature computation per request?
- Graceful degradation when service is unavailable?
- Is the feature service health-checked in docker-compose?

---

## PHASE 8 — Research system audit

### Exploration quality
- Review last 3 exploration session summaries in `hbot/data/research/explorations/`
- Are generated strategies diverse (different adapter_modes, timeframes, hypotheses)?
- What is the typical robustness score distribution?
- Are there diminishing returns across iterations within a session?

### Prompt effectiveness
- Is the SYSTEM_PROMPT in `exploration_prompts.py` aligned with current adapter modes
  and scoring criteria?
- Does the REVISE_PROMPT produce measurable improvements or just noise?
- Temperature decay: is the explore_ratio/temperature_decay config producing good
  explore vs exploit balance?

### Pipeline integrity
- Does the robustness scorer correctly penalize overfitting?
- Are backtest results reproducible across runs?
- Is there a risk of the exploration system accidentally modifying production configs?
- Are exploration artifacts cleaned up to prevent disk growth?

---

## PHASE 9 — Infrastructure audit

### Docker and runtime
- Container memory limits set and appropriate?
- Restart policies correct (on-failure with max retries)?
- Log rotation configured in compose (json-file driver with max-size)?
- Health checks defined for critical containers (bot, event_store, redis)?
- Are all 26+ services actually needed or are some dormant?
- ML feature service: resource limits appropriate for model loading?

### Redis
- Memory usage and eviction policy (if stream grows unbounded)?
- Max stream length configured on event streams?
- Connection pool size appropriate for number of consumers?
- Stream namespacing: are bot-specific streams isolated?
- Stream consumer groups: are there orphaned consumers?

### Prometheus / Grafana
- Scrape interval appropriate vs metric freshness needs?
- High-cardinality labels that could cause memory growth?
- Dashboard data retention period set correctly?
- Cross-reference with OBSERVABILITY_CONTRACT.md: are all documented metrics
  actually being scraped?
- Alert rules: do they fire on the correct conditions? Any noisy alerts?

### Disk
- Log volume growth rate — at current rate, when does disk fill?
- JSONL event files — is there a retention/cleanup policy?
- CSV files (minute.csv, fills.csv) — are old files archived or deleted?
- Research exploration artifacts — cumulative size and growth rate?
- Historical parquet data — is the catalog pruning old data?
- ML model artifacts — are old versions cleaned up?

### Ops scheduler
- Is `hbot/services/ops_scheduler/` running its scheduled tasks reliably?
- Are data refresh scripts (`hbot/scripts/ops/data_refresh.py`) completing successfully?
- Is the heartbeat file being updated?

---

## PHASE 10 — Dependency and tooling review

For each outdated or candidate dependency, make a decision:

| Package | Current | Latest | Issue / opportunity | Decision |
|---|---|---|---|---|
| | | | | adopt / update / defer / reject |

Candidate new tools to evaluate:
- `redis.asyncio` — remove blocking Redis calls from tick loop
- `structlog` — structured logs for better Grafana/Loki integration
- `orjson` — faster JSON in hot paths (event serialization)
- `anyio` — improved async task supervision
- Pydantic v2 migration gaps remaining
- `polars` — faster dataframe operations in backtesting/ML pipelines
- `duckdb` — in-process analytics for research/backtesting queries
- ML framework versions (scikit-learn, lightgbm, etc.)

For each: estimate migration effort, breakage risk, and expected benefit.

Check both requirements files:
- `hbot/infra/compose/images/control_plane/requirements-control-plane.txt`
- `hbot/infra/compose/images/ml_feature_service/requirements-ml-feature-service.txt`

---

## PHASE 11 — Sprint plan (2-week scope)

Select a coherent bundle:
- Max 1 L-effort item (> 1 day)
- 2–3 M-effort items (half-day to 1 day each)
- Quick wins (< 2h each, unlimited)

For each L/M item: define rollback plan.

Order items by: reliability impact first, then performance, then code health.

Constraints:
- All changes must compile: `python -m py_compile hbot/controllers/runtime/kernel/controller.py`
- Architecture contracts must pass: `PYTHONPATH=hbot python -m pytest hbot/tests/architecture/ -q`
- Promotion gates must pass: `cd hbot && python scripts/release/run_strict_promotion_cycle.py`
- Never commit `.env` (only `infra/env/.env.template`)
- Bot1 is paper-only. Do not change connector to `bitget` without completing go-live checklist.

---

## PHASE 12 — BACKLOG entries (mandatory)

For every item in the sprint plan, produce entries matching the format in `hbot/BACKLOG.md`:

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

Tiers: P0 = blocks live/safety or hard promotion gate · P1 = affects PnL/reliability · P2 = quality/simulation realism

---

## Output format
1. Technical health scorecard (8 dimensions, score + trend arrow ↑↓→)
2. Architecture contract status (pass/fail + violation details)
3. Strategy isolation status (pass/fail + any cross-contamination)
4. Reliability findings (ranked, with root cause)
5. Performance findings (hot path, I/O, memory)
6. Code health findings (structure, types, error handling)
7. Test coverage gaps (ranked by risk)
8. ML pipeline health (staleness, drift, integrity)
9. Research system health (diversity, prompt effectiveness, reproducibility)
10. Infrastructure findings (Docker, Redis, Prometheus, disk)
11. Dependency decisions table
12. Sprint plan (2-week, ordered, with rollback)
13. BACKLOG entries (copy-paste ready into hbot/BACKLOG.md)
14. Metrics to track next cycle (what proves the fixes worked)
15. Assumptions and data gaps (what was inferred vs explicitly provided)

## Rules
- Never remove a safety control to gain performance
- A freeze fix is always P0 regardless of effort
- Do not adopt new tools unless the benefit is concrete and the migration is bounded
- Every sprint item must have a test or metric that proves it worked
- Prefer boring, incremental improvements over clever architectural changes
- Challenge existing design choices each cycle; keep what works, change what no longer does
- Include at least one creative but bounded experiment proposal per cycle (with rollback)
- Strategy isolation is non-negotiable: shared runtime must never import bot-specific code
- Architecture contract test failures are P0 blockers
- Cross-reference findings with BACKLOG.md to avoid duplicating existing items
- If this is MODE=ITERATION, explicitly diff against last cycle's scorecard
```
