> **Note (2026-02-26):** References to `paper_engine.py` in this doc are historical. The v1 paper engine has been fully replaced by `controllers/paper_engine_v2/`. All new work should target v2.

# Production Hardening Backlog v2 (Audit Update)

## Purpose
Comprehensive hardening backlog combining Day 27 readiness audit (original v1) with the full codebase technical audit (Day 40+ review). Items are ranked by direct safety impact, then reliability, then operational efficiency.

## Prioritization Model
- Priority 1: direct safety/release risk reduction (live capital at stake).
- Priority 2: reliability, recovery speed, and code quality.
- Priority 3: operational efficiency, developer experience, and maintainability.

---

## Priority 1 — Safety-Critical

### 1) Break up `EppV24Controller` god class (Day 46)
- Scope: `controllers/epp_v2_4.py` (1164 LOC, 10+ responsibilities)
- Why: untestable in isolation; any change risks side effects across regime detection, spread logic, risk checks, fee resolution, CSV logging, edge gating, and external intents
- Acceptance criteria:
  - controller body under 300 lines (thin orchestrator)
  - 5 extracted modules: `RegimeDetector`, `SpreadEngine`, `RiskPolicy`, `FeeManager`, `OrderSizer`
  - each module has ≥80% branch coverage
  - no behavioral change (same minute.csv output for same inputs)

### 2) Add controller unit tests (Day 47)
- Scope: `controllers/epp_v2_4.py` — zero tests for the highest-criticality module
- Why: live capital runs on untested code; any regression is invisible until production
- Acceptance criteria:
  - every regime/edge/risk/fee path has at least one test
  - property-based tests for spread/skew math (hypothesis, 200+ examples)
  - ≥80% line coverage on controller logic
  - test failure blocks promotion gate

### 3) Eliminate monkey-patches (Day 48)
- Scope: `paper_engine.py` (3 patches), `v2_with_controllers.py` (2 patches)
- Why: module-level patches to `ExecutorBase`, `MarketDataProvider`, and `ConnectorManager` make HB upgrades extremely dangerous and testing impossible without full runtime
- Acceptance criteria:
  - zero module-level monkey-patches remain
  - `enable_framework_paper_compat_fallbacks()` removed or converted to instance-level
  - HB compatibility matrix documented
  - all existing tests pass

### 4) Real kill switch — exchange cancel-all + position flatten (Day 50)
- Scope: new `services/kill_switch/kill_switch_service.py`
- Why: current `OpsGuard.force_hard_stop()` only stops new order placement; open orders remain on exchange; positions are not flattened
- Acceptance criteria:
  - kill switch calls exchange cancel-all API
  - optional position flatten via market orders (configurable, default off)
  - audit event + webhook notification on trigger
  - requires manual restart to resume (no auto-recovery)
  - dry-run mode for testing

### 5) Exchange-side fill reconciliation (Day 51)
- Scope: extend `services/reconciliation_service/main.py`
- Why: local fills.csv is never compared against exchange API fills; phantom or missing fills would go undetected
- Acceptance criteria:
  - fetch recent fills from exchange via ccxt `fetch_my_trades()`
  - compare against local fills.csv by order_id/trade_id
  - alert on missing, phantom, or price/amount discrepancy
  - fill reconciliation status visible in Grafana

### 6) Enforce immutable runtime for control-plane services (v1 item #1)
- Status: DONE (Day 8/28)
- Scope: all external profile services
- Evidence: pinned `hbot-control-plane:20260222` image; no runtime pip install

### 7) Add healthchecks for all control-plane services (v1 item #2)
- Status: DONE (Day 28)
- Evidence: compose healthchecks for all critical services

### 8) Make stale control-plane outputs fail-closed for promotion (v1 item #3)
- Status: DONE (Day 28)
- Evidence: freshness gates in promotion runner

### 9) Portfolio risk concentration remediation (v1 item #4)
- Status: PARTIALLY DONE (Day 5/28)
- Remaining: refine concentration false-positive criteria after multi-day live observation

---

## Priority 2 — Reliability + Code Quality

### 10) Dependency management + type checking (Day 49)
- Scope: project root — no `setup.py`, `pyproject.toml`, or pinned project deps
- Why: builds are not reproducible; type annotations exist but no checker runs
- Acceptance criteria:
  - `pyproject.toml` with pinned deps, dev deps, and entry points
  - `mypy` strict on `controllers/` and `services/contracts/`
  - `ruff` linting enabled
  - type-check and lint failure blocks promotion

### 11) Graceful shutdown + signal handling (Day 52)
- Scope: all 10 service `main.py` files
- Why: `while True` + `time.sleep()` with no `SIGTERM` handling; containers cannot drain in-flight work
- Acceptance criteria:
  - every service exits cleanly on SIGTERM within 10 seconds
  - no partial/corrupted writes after shutdown
  - shared `services/common/graceful_shutdown.py` utility

### 12) CSV → Redis Stream migration for bot telemetry (Day 53)
- Scope: minute snapshot, fill events, daily rollover
- Why: CSV is primary data source for 6+ services; file-locking risk, O(n) scans, path coupling, no schema versioning
- Acceptance criteria:
  - telemetry events in Redis stream within 1s of CSV write
  - metrics exporter produces identical output from Redis vs CSV
  - CSV kept as backward-compatible secondary export
  - feature flag for gradual rollout

### 13) Multi-exchange fee resolver + rate limit handling (Day 54)
- Scope: `services/common/fee_provider.py` — Bitget-only API support
- Why: adding a second exchange requires code changes to resolver; no exchange rate limit awareness
- Acceptance criteria:
  - pluggable `ExchangeFeeAdapter` protocol
  - Bitget + Binance adapters implemented
  - per-exchange token bucket rate limiter
  - rate limit remaining exposed as Prometheus gauge

### 14) Redis durability recovery drill (v1 item #5)
- Status: DONE (Day 9/18)
- Evidence: controlled outage drill; restart-regression checker passes

### 15) Ops DB writer reliability hardening (v1 item #6)
- Status: DONE (Day 26/28)
- Evidence: healthcheck, idempotent upserts, restart test

### 16) Postgres backup/restore fire drill (v1 item #7)
- Status: NOT STARTED
- Acceptance criteria:
  - scheduled dump job executed and retained
  - restore into clean instance validated
  - Grafana queries pass post-restore

### 17) Service-level SLO ownership formalization (v1 item #8)
- Status: PARTIALLY DONE (Day 27)
- Remaining: explicit owner role and escalation path per SLO; weekly breach summary

### 18) Wire CI to GitHub Actions (extend Day 37)
- Scope: `.github/workflows/ci.yml`
- Why: Day 37 CI is local-only (`run_ci_pipeline.py`); not wired to GitHub PR/push workflow
- Acceptance criteria:
  - `pytest` + `ruff` + `mypy` + promotion gates run on every push/PR
  - merge blocked if any gate fails
  - CI artifacts archived per run

### 19) Decimal precision fix in order pricing pipeline (Day 56)
- Scope: `RuntimeLevelState` stores spreads as `List[float]`; `Decimal(float_value)` at line 734 of `epp_v2_4.py`
- Why: systematic ~\$0.01 price drift per order on a \$10k position due to float→Decimal→float round-trip
- Acceptance criteria:
  - `RuntimeLevelState` spreads are `List[Decimal]`
  - no `float(x) for x in spreads` conversion in pricing pipeline
  - fee extraction has fallback estimation when primary extraction fails

### 20) Logging infrastructure for controllers (Day 56-57)
- Scope: `epp_v2_4.py`, `paper_engine.py`, `connector_runtime_adapter.py`, `fee_provider.py` — zero logging
- Why: 8 critical + 15 high-severity exception-swallowing instances are invisible in production; debugging requires CSV archaeology
- Acceptance criteria:
  - `logging.getLogger(__name__)` in all 4 controller files
  - every caught exception logged at WARNING+
  - balance read failure triggers SOFT_PAUSE
  - fill relay failure logged at ERROR with fill details
  - exception counter exported as Prometheus metric
  - zero `print()` in service code

### 21) ProcessedState type contract (Day 58)
- Scope: `processed_data` dict in `epp_v2_4.py` — 40+ untyped keys consumed by strategy runner, metrics exporter, and bus publisher
- Why: no type safety; key typos and type mismatches caught only at runtime
- Acceptance criteria:
  - `TypedDict` or `@dataclass` with all 40+ keys typed and documented
  - `mypy` catches key/type errors
  - config reference doc auto-generated from Pydantic schema

---

## Priority 3 — Operational Efficiency + Maintainability

### 22) Dead code cleanup + helper consolidation (Day 55)
- Scope: 20+ example scripts in `data/bot{1,2}/scripts/`; duplicated helpers across 8+ files
- Why: clutter, confusion about active code, divergent helper behavior
- Acceptance criteria:
  - inactive examples moved to `docs/examples/` or deleted
  - canonical `services/common/utils.py` replaces all duplicate helpers
  - zero duplicate `_safe_float()` / `_utc_now()` / `_read_json()` outside utils

### 23) Fix settings initialization (Day 55)
- Scope: `services/common/models.py` — `os.getenv()` at class definition time
- Why: values frozen at import; breaks test isolation and dynamic reconfiguration
- Acceptance criteria:
  - `field(default_factory=lambda: os.getenv(...))` pattern
  - `RedisSettings()` can be instantiated in tests without setting env vars

### 24) Fill-path validation for Postgres blotter completeness (v1 item #9)
- Status: NOT STARTED
- Acceptance criteria:
  - at least one controlled fill appears in `fills` table
  - Grafana blotter panel shows rows from Postgres
  - no-fills fallback behavior documented

### 25) Automated readiness report generation (v1 item #10)
- Status: PARTIALLY DONE (Day 21/34)
- Remaining: one command emits updated scorecard with L-level trend vs prior checkpoint

### 26) Implicit variant gating → config-driven (audit finding)
- Scope: `epp_v2_4.py:330-335` — variants b/c force HARD_STOP, d forces SOFT_PAUSE
- Why: business rules hidden in strategy code
- Acceptance criteria:
  - variant behavior defined in config, not hardcoded
  - controller reads `variant_mode` from config (`live`, `paper_only`, `disabled`, `no_trade`)

### 27) Hardcoded path elimination (audit finding)
- Scope: `/home/hummingbot/`, `/workspace/hbot/`, `/.dockerenv` detection across services
- Why: fragile path coupling; breaks local dev without Docker
- Acceptance criteria:
  - all paths resolved via env vars or config with sane defaults
  - local dev works without Docker path assumptions

### 28) Exception swallowing audit (audit finding)
- Scope: pervasive `except Exception: pass` across `paper_engine.py`, `fee_provider.py`, `connector_runtime_adapter.py`
- Why: silent failures; no observability into why operations fail
- Acceptance criteria:
  - every swallowed exception at least logs at WARNING level
  - critical paths (fee resolution, order placement, balance reads) log at ERROR
  - exception count exposed as Prometheus counter

### 29) Running EMA/ATR indicators (Day 60, performance audit)
- Scope: `price_buffer.py` — `ema()` and `atr()` recompute O(2880) from scratch every tick
- Why: ~11,520 Decimal operations per tick from indicators alone; single biggest hot-path cost
- Acceptance criteria:
  - `ema()` and `atr()` are O(1) per call (return cached running value)
  - running values match from-scratch computation to 12 decimal places
  - indicator cost < 0.1ms per tick (measured via Day 63 instrumentation)

### 30) Buffered CSV writer (Day 61, performance audit)
- Scope: `epp_logging.py` — sync open/read-header/write/close on every log call
- Why: blocking filesystem I/O on fill event handler and every-minute tick loop
- Acceptance criteria:
  - file open/close at most once per flush interval (not per row)
  - fill event handler does not block on filesystem I/O
  - no data loss on graceful shutdown

### 31) Service loop efficiency (Day 62, performance audit)
- Scope: reconciliation full-JSONL scan, metrics exporter full-log `readlines()`, coordination 20x/sec policy reads
- Why: `_count_event_fills` scans entire daily JSONL (grows to 864K lines); metrics exporter loads full log into memory
- Acceptance criteria:
  - reconciliation cycle time constant regardless of day length
  - metrics scrape does not load entire log files
  - policy file read at most once per actual file change

### 32) Tick-loop instrumentation (Day 63, performance audit)
- Scope: no timing data exists for the hot path
- Why: cannot validate optimizations or detect regressions without measurements
- Acceptance criteria:
  - tick duration visible in Grafana
  - component breakdown (indicators / connector / CSV) visible
  - alert fires if tick exceeds 100ms

### 33) Strategy logic hardening — regime cooldown + stale-side cancel (Day 64, strategy audit)
- Scope: `epp_v2_4.py` — regime oscillation causes order churn; stale executors persist after regime flip
- Why: regime boundary oscillation creates cancel→place→cancel loops; stale-side fills are adverse
- Acceptance criteria:
  - regime flip requires 3 consecutive ticks before activating
  - stale-side executors canceled immediately on regime transition
  - spread floor recalculated every 30s (not 300s)
  - orders never placed inside the market spread

### 34) Fill factor calibration + edge validation (Day 65, strategy audit)
- Scope: `fill_factor=0.4` is uncalibrated; no empirical edge validation exists
- Why: the strategy may have negative expectancy at VIP0 fees — this is the most critical business risk
- Acceptance criteria:
  - fill_factor calibrated from live fills data
  - daily edge report shows net PnL with fee/slippage breakdown
  - maker/taker ratio visible in fills.csv

### 35) Adverse selection + funding rate modeling (Day 66, strategy audit)
- Scope: shock drift not vol-normalized; no funding rate awareness for perp connectors
- Why: PnL attribution is incomplete without funding costs; shock detection sensitivity is mismatched to vol regime
- Acceptance criteria:
  - shock drift normalized by ATR
  - funding rate cost tracked and visible in processed_data
  - realized adverse selection measurable from fills

### 36) Perp equity correction + leverage cap (Day 67, risk audit — CRITICAL)
- Scope: `_compute_equity_and_base_pct` uses spot formula for perps; no leverage cap
- Why: equity, base_pct, daily loss, and drawdown are all distorted for perpetual connectors; leverage can be set arbitrarily
- Acceptance criteria:
  - perp equity uses margin_balance + unrealized_pnl
  - `leverage > max_leverage` rejected at startup
  - margin ratio < 10% triggers HARD_STOP

### 37) Orphan order scan + HARD_STOP → exchange cancel (Day 68, risk audit — CRITICAL)
- Scope: HARD_STOP doesn't cancel exchange orders; orphan orders survive crashes
- Why: loss can continue after HARD_STOP; crash-restart leaves untracked orders
- Acceptance criteria:
  - HARD_STOP with risk reason publishes kill_switch intent
  - orphan orders detected and canceled on startup
  - cancel budget escalates to HARD_STOP after 3 consecutive breaches

### 38) Realized PnL + persistent daily state (Day 69, risk audit — HIGH)
- Scope: no per-fill realized PnL; daily state resets on restart
- Why: cannot validate edge per fill; daily loss limit is circumvented by restart
- Acceptance criteria:
  - fills.csv has realized_pnl_quote column with cost basis
  - daily state persisted to JSON and restored on restart within same day
  - funding cost accumulated in daily PnL

### 39) Funding in edge model + portfolio kill switch (Day 70, risk audit — HIGH)
- Scope: funding rate not deducted from edge; kill switch is per-instance
- Why: edge appears positive while funding bleeds the account; global breach doesn't stop all bots
- Acceptance criteria:
  - net edge formula includes funding_cost_est
  - global daily loss breach triggers kill_switch for all scoped bots

### 40) Startup order scan + position reconciliation (Day 71, execution audit — CRITICAL)
- Scope: no orphan order detection on restart; no periodic position reconciliation
- Why: crash-restart leaves untracked orders; position drift from missed fills goes undetected
- Acceptance criteria:
  - orphan orders detected and canceled on startup
  - position drift > 5% triggers SOFT_PAUSE
  - position_drift_pct visible in Grafana

### 41) Order ack timeout + cancel-before-place guard (Day 72, execution audit — HIGH)
- Scope: no timeout for orders stuck in "placing"; duplicate orders from cancel/place race
- Why: stuck orders consume margin indefinitely; duplicate orders amplify exposure
- Acceptance criteria:
  - orders in "placing" state > 30s are canceled
  - levels with STOPPING executors excluded from placement
  - max concurrent executors enforced

### 42) WS health monitoring + connector status exposure (Day 73, execution audit — HIGH)
- Scope: no visibility into WS connection health; stale order book undetected
- Why: stale data leads to bad pricing and wrong regime detection
- Acceptance criteria:
  - connector status visible in processed_data
  - order book staleness detected (same top-of-book > 30s)
  - WS reconnection events counted and alerted

### 43) Go-live hardening drill (Day 74, execution audit — validation)
- Scope: no validated restart recovery, paper→live parity, or multi-day soak evidence
- Why: cannot safely deploy to live without validated recovery and endurance evidence
- Acceptance criteria:
  - restart recovery tested with orphan detection
  - paper and testnet show consistent behavior
  - 48h soak with no leaks or unplanned stops
  - all 14 go-live checklist items PASS

### 44) Cross-environment parity report (Day 75, validation audit)
- Scope: no tool to compare backtest vs paper vs live metrics
- Why: paper can give 2-7x false confidence on fill rate and PnL
- Acceptance criteria:
  - parity_report.py compares any two environments side-by-side
  - WARNING flags when paper appears unrealistically optimistic
  - parity score included in weekly review artifacts

### 45) Post-trade shadow validator (Day 76, validation audit)
- Scope: fill_factor, adverse_selection, queue_participation are uncalibrated assumptions
- Why: the edge model may show positive edge while live is negative
- Acceptance criteria:
  - realized fill_factor computed from live fills
  - CRITICAL flag if realized < 70% of configured fill_factor
  - automated and included in daily ops report

### 46) Validation ladder gate enforcement (Day 77, validation audit)
- Scope: validation ladder (Level 0-7) exists conceptually but not enforced
- Why: strategy changes can bypass validation and go directly to live
- Acceptance criteria:
  - promotion gates enforce Level 3 (paper soak PASS) for any live promotion
  - validation_level visible in gate output

---

## Exit Definition

### L2 Baseline (Semi-Pro Prod)
- All Priority 1 items complete (9 items, 3 already done).
- At least 6 of 12 Priority 2 items complete, including #10 (dependency management), #11 (graceful shutdown), #19 (Decimal precision), and #20 (logging infrastructure).
- Risk audit critical items #36 (perp equity) and #37 (orphan scan + HARD_STOP cancel) complete.
- Execution audit items #40 (startup order scan) and #41 (ack timeout) complete.
- Two consecutive weekly checkpoints show stable PASS for promotion gates and no unresolved critical safety findings.

### 47) Metrics export gap closure (Day 78, SRE audit)
- Scope: 12 metrics in processed_data not exported to Prometheus
- Why: tick duration, margin ratio, position drift, WS health invisible in Grafana
- Acceptance criteria:
  - all 12 metrics visible in Prometheus
  - 10 new alert rules active
  - Slack alert delivery confirmed

### 48) Execution quality dashboard (Day 79, SRE audit)
- Scope: no dashboard for fill quality, maker ratio, spread capture
- Why: cannot measure execution quality without visual tools
- Acceptance criteria:
  - execution quality + risk/exposure dashboards deployed
  - structured incident template created

### 49) Backup + retention automation (Day 80, SRE audit)
- Scope: no scheduled backup; no event store archival; no /health endpoints
- Why: data loss risk; no external uptime monitoring
- Acceptance criteria:
  - daily Postgres backup verified (restore test)
  - event store archival running automatically
  - /health endpoints respond for external monitoring

### L3 Target (Institutional Grade)
- All Priority 1 and Priority 2 items complete.
- All risk audit items (#36-#39) complete.
- All execution audit items (#40-#43) complete, including go-live drill PASS.
- Validation audit items #44-#46 complete (parity report, post-trade validator, ladder gates).
- SRE audit items #47-#49 complete (metrics export, dashboards, backups).
- At least 5 of 7 Priority 3 items complete.
- Formal SLO ownership with escalation paths.
- Exchange-side reconciliation running in production for ≥30 days.
- Kill switch tested with live exchange API (dry-run + funded testnet).
- Portfolio-wide kill switch operational and tested.
- Realized PnL per fill matches exchange-reported fills within 1 bps tolerance.
- Restart recovery validated with orphan order cleanup.
- 48h continuous soak test passed with no executor/memory leaks.
- Alert delivery to Slack/PagerDuty confirmed and tested.
- Zero `print()` in production code; all logging via structured `logging` module.
- `mypy` strict mode passes on controller + contracts code.
