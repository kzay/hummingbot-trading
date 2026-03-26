## Context

The hbot codebase is a Hummingbot-based trading desk with 535 Python files (~127K lines) across controllers, services, scripts, and tests. It grew from a single-bot MM setup into a multi-bot, multi-strategy platform over 40+ dev days. The `controllers/` directory alone holds 161 files and ~48K lines, mixing strategy logic, simulation engines, backtesting infrastructure, ML pipelines, and HB loader compatibility shims in one namespace.

The previous infra refactoring (`project-structure-refactoring`) moved compose/monitoring/env/security into `infra/`. This phase tackles the **code architecture**: splitting god modules, fixing layer violations, extracting misplaced packages, and establishing enforceable import boundaries.

**Constraints:**
- Hummingbot resolves controllers by `controller_type/module_name` paths — loader shims must remain functional.
- Bot1 is the only active paper-trading bot; bots 2-7 are inactive.
- All changes must be pure refactoring — zero behavior changes.
- Docker mounts bind `hbot/` as `/workspace/hbot` — top-level directory moves affect container volume paths.

## Goals / Non-Goals

**Goals:**
- G1: Every Python module has a single, clear responsibility (no file > 800 lines).
- G2: Dependencies flow strictly downward: `platform` → `simulation` → `controllers` → `services` → `scripts`. No upward imports.
- G3: `controllers/` contains only strategy logic and runtime kernel — no simulation engines, no service code.
- G4: Import boundaries are machine-enforced via a contract test that fails CI.
- G5: New contributors can understand the codebase structure from directory names alone.
- G6: All existing tests pass with zero behavior changes.

**Non-Goals:**
- Rewriting strategy logic or tuning parameters.
- Changing YAML config schemas or controller_name strings.
- Migrating to async/await or changing the event loop model.
- Splitting the monorepo into multiple packages/repos.
- Optimizing performance (this is purely structural).
- Refactoring the frontend (`apps/realtime_ui_v2/`).

## Decisions

### D1: Extract simulation library to `hbot/simulation/`

**Decision:** Move `controllers/paper_engine_v2/` to `hbot/simulation/` as a standalone package.

**Why:** Paper Engine v2 is a simulation library (matching engine, portfolio, accounting, risk) consumed by both `services/paper_exchange_service/` and `controllers/backtesting/`. Having it under `controllers/` creates a false dependency — it's not a controller, it's infrastructure.

**Alternative considered:** Keep it under `controllers/` but rename to `controllers/simulation/`. Rejected because it would preserve the import-depth problem: services would still import `controllers.*`.

**Migration:** Add `from simulation import *` re-export shim in a temporary `controllers/paper_engine_v2/__init__.py` for the transition period, then remove after all imports are updated.

### D2: Break `shared_runtime_v24.py` into kernel submodules

**Decision:** Split the 4,376-line file into `controllers/runtime/kernel/` with these modules:
- `startup.py` — initialization, config validation, daily state restore (~300 lines)
- `quoting.py` — spread computation, order sizing, quote placement (~600 lines)
- `risk_guards.py` — risk evaluation, gate checks, soft-pause logic (~500 lines)
- `regime_bridge.py` — regime detection integration, spec overrides (~200 lines)
- `paper_hooks.py` — PaperDesk bridge installation, paper-mode wiring (~300 lines)
- `telemetry.py` — minute logging, heartbeat, metrics emission (~400 lines)
- `state.py` — daily state, fill cache, position tracking (~400 lines)
- `calibration.py` — auto-calibration, percentile calculations (~300 lines)
- `controller.py` — `EppV24Controller` class tying everything together (~500 lines)

**Why:** A 4,376-line file is unmaintainable. Every change risks merge conflicts. The file mixes 8 distinct concerns.

**Alternative considered:** Mixin-based decomposition (already partially done with `risk_mixin.py`, `position_mixin.py`). Rejected because mixins create implicit coupling via `self` — explicit composition with typed interfaces is cleaner.

**Risk:** The split must preserve the exact `__init__` order and method resolution. Regression test `test_epp_v2_4_core.py` (3,737 lines) validates behavior.

### D3: Break `hb_bridge.py` into focused modules

**Decision:** Split the 2,655-line file into:
- `simulation/bridge/event_router.py` — HB event translation and firing (~600 lines)
- `simulation/bridge/subscriber_manager.py` — subscriber registration and lifecycle (~400 lines)
- `simulation/bridge/connector_patches.py` — HB connector monkey-patches (~400 lines)
- `simulation/bridge/signal_handler.py` — external signal consumption and HARD_STOP (~300 lines)

**Why:** The bridge is the most-touched file after `shared_runtime_v24.py` and mixes 4 unrelated concerns.

### D4: Extract `services/common/` to `hbot/platform/`

**Decision:** Create `hbot/platform/` for shared utilities consumed by both controllers and services: market data plane, Redis helpers, execution gateway protocols, time utilities, logging helpers.

**Why:** 28+ controller modules import `services.common.*`. This is a layer violation — controllers should not depend on the service layer. The common code is actually a platform library, not a service.

**Alternative considered:** Duplicate the needed utilities into `controllers/`. Rejected because it creates maintenance burden and code drift.

**Migration:** Leave a re-export shim at `services/common/__init__.py` importing from `platform/` during transition.

### D5: Consolidate loader shims into `controllers/hb_loader_shims/`

**Decision:** Merge `controllers/directional/`, `controllers/market_making/`, and root-level wrapper files (`epp_v2_4_bot*.py`, `bot*_v1.py`) into `controllers/hb_loader_shims/` with:
- `market_making/` subfolder (for HB `controller_type=market_making` resolution)
- `directional/` subfolder (for HB `controller_type=directional` resolution)
- A `README.md` explaining why these exist and when to add new ones.

**Why:** Currently, strategies exist in 3 import paths. Consolidating makes it obvious which files are "real code" vs "compatibility plumbing."

### D6: Error handling strategy

**Decision:** Replace all `except Exception: pass` in hot paths with a three-tier pattern:
- **Tier 1 (critical path)**: Typed exceptions (`MatchingEngineError`, `BridgeError`, etc.) + Prometheus counter + log at WARNING/ERROR. Never swallow.
- **Tier 2 (degraded mode)**: Broad `except Exception` allowed only if it logs, sets a degraded flag, and returns a safe default. Used for telemetry, serialization, UI.
- **Tier 3 (fatal)**: Errors that indicate data corruption or impossible states. Log at CRITICAL, trigger kill switch notification.

**Why:** 61 silent `except Exception: pass` blocks in production code is unacceptable for a trading desk. A single silently swallowed error in fill processing can cause position desync.

### D7: Type safety approach

**Decision:** Pragmatic strict typing. Full return annotations and `disallow_untyped_defs` for new kernel/simulation/platform modules. Existing code gets annotations opportunistically during splits (when you touch a method, you type it). `Any` banned in trading decision paths (quoting, risk, fills).

**Why:** Full codebase-wide mypy strict is too expensive to retrofit. Focusing on the modules being rewritten gives 80% of the safety for 20% of the effort.

### D8: Phased execution order

**Decision:** Execute in dependency order to minimize breakage:

1. **Phase 0 — Baseline** (readonly): Record exact test pass/fail counts, import violations, compile status.
2. **Phase 1 — Foundation** (no import changes): Dead code cleanup, `__all__` exports, module docstrings, scripts reorganization, logging standardization.
3. **Phase 2 — Platform extraction**: `services/common/` → `hbot/platform/` with re-export shims.
4. **Phase 3 — Simulation extraction**: `controllers/paper_engine_v2/` → `hbot/simulation/` with re-export shims.
5. **Phase 4 — Runtime kernel split**: Break `shared_runtime_v24.py` and `hb_bridge.py`. Apply error handling hardening and type annotations during splits.
6. **Phase 5 — Shim consolidation**: Merge loader shims, remove root wrappers.
7. **Phase 6 — Service splits**: Break god services, split corresponding tests.
8. **Phase 7 — Hardening**: Error handling hardening on remaining hot paths, concurrency safety documentation, `float()` annotation sweep.
9. **Phase 8 — Test coverage**: Add tests for previously untested critical modules.
10. **Phase 9 — Enforcement**: Import boundary contract test, coverage minimums, CI integration.

Each phase has its own validation gate: compile + full pytest + grep for stale imports.

**Key principle:** Robustness hardening (error handling, types, logging) happens **during** the structural splits, not as a separate pass afterward. When you split `shared_runtime_v24.py` into kernel modules, each new module gets proper types and error handling from the start. This avoids touching the same code twice.

## Risks / Trade-offs

- **[Risk] Import breakage in dynamic resolution** — Hummingbot loads controllers by string `module_path` from YAML configs. → **Mitigation:** Loader shims preserved in exact original paths; contract test validates all YAML controller_name strings resolve.
- **[Risk] Merge conflicts with concurrent work** — This touches 200+ files. → **Mitigation:** Phased execution; each phase is a separate commit. Avoid rebasing mid-phase.
- **[Risk] Test failures from import path changes** — Tests use `from controllers.paper_engine_v2 import ...` → **Mitigation:** Update all test imports in the same commit as the code move; never leave partial state.
- **[Risk] `shared_runtime_v24` split breaks initialization order** — The 4K-line file has subtle `__init__` sequencing. → **Mitigation:** Keep `EppV24Controller.__init__` in one file (`controller.py`); use explicit method delegation, not inheritance from split modules.
- **[Risk] Re-export shims become permanent** — Temporary shims have a way of lasting forever. → **Mitigation:** Phase 9 contract test explicitly forbids imports from shim paths; deprecation warnings logged at import time.
- **[Risk] Error handling changes alter behavior** — Replacing `except Exception: pass` with typed catches could surface previously-hidden exceptions that crash the tick loop. → **Mitigation:** Each error handling change is accompanied by a test exercising the error path. Non-critical paths use Tier 2 (log + safe default), never Tier 1 (raise).
- **[Risk] Type annotation effort is unbounded** — Full strict mypy on 127K lines is impractical. → **Mitigation:** Strict only on NEW modules written during the split (kernel, simulation, platform). Existing code gets annotations when touched, not proactively.
- **[Risk] `float()` annotation sweep is tedious** — 380+ `float(` calls in controllers alone. → **Mitigation:** Only annotate `float()` on monetary variables. Telemetry/UI float casts that operate on already-serialized data are lower priority.

## Pre-Existing Test Baseline (verified 2026-03-22)

Before any refactoring begins, the following test state was verified inside Docker (`control-plane-metrics-exporter` container with pytest 8.4.2):

**Passing suites:**
- `test_strategy_isolation_contract.py` — 8/8 pass
- `test_market_making_shim_contract.py` — (part of above) pass
- `test_epp_v2_4_core.py` — 129/130 pass (1 pre-existing failure)
- `test_paper_engine_v2/` — 276/276 pass
- `test_backtesting/` — 14/15 files pass individually (1 OOM-killed by container memory limit)
- `test_epp_v2_4_bot7_pullback.py` — pass (with skips for integration)
- `test_epp_v2_4_bot6.py` — pass
- `test_hb_bridge_signal_routing.py` — pass
- `test_price_buffer.py` — pass
- `test_realtime_ui_api.py` — 55/55 pass

**Pre-existing failures (NOT regressions — do NOT fix as part of this refactoring):**
1. `test_epp_v2_4_core.py::test_publish_bot_minute_snapshot_telemetry_falls_back_to_event_store_file` — path resolution `tmp_path / "hbot" / "reports"` issue
2. `test_ops_build_spec.py::test_recon_exchange_ready_passes_with_complete_env_and_reports` — environment/reports dependency
3. `test_portfolio_risk_service.py::test_run_once_produces_report` — service dependency
4. `test_promotion_gates_logic.py::test_run_event_store_once_falls_back_to_docker_when_host_client_disabled` — Docker-in-Docker dependency
5. `test_ml/test_research.py` — `libgomp.so.1` missing in container image
6. `test_backtesting/test_data_store.py` — OOM-killed (container memory limit, not a code bug)

**Pre-existing import violations (45 total):**
- `controllers → services.common.utils` — 15 files (mostly `to_decimal`, `safe_decimal`)
- `controllers → services.contracts.stream_names` — 8 files
- `controllers → services.contracts.event_identity` — 6 files
- `controllers → services.contracts.event_schemas` — 3 files
- `controllers → services.common.market_data_plane` — 3 files
- `controllers → services.common.exchange_profiles` — 2 files
- `controllers → services.common.fee_provider` — 2 files
- `controllers → services.common.latency_tracker` — 1 file
- `controllers → services.common.market_history_*` — 3 files
- `controllers → services.common.rate_limiter` — 1 file
- `controllers → services.execution_gateway.gateway` — 1 file

**Regression testing strategy:**
- After each phase, run the exact same test commands above
- A regression is defined as: any test that was passing BEFORE that phase now fails AFTER
- Pre-existing failures are excluded from regression detection
- OOM-kills are excluded (they're infrastructure limits, not test failures)
- The import boundary contract test (Phase 7) should initially match the 45 known violations as "allowed legacy", then progressively tighten as phases fix them

## Open Questions

- **Q1:** Should `controllers/backtesting/` also move out of `controllers/` (to `hbot/backtesting/`)? It's research infrastructure, not live strategy. Deferring to Phase 2 of a future refactoring.
- **Q2:** Should `controllers/research/` and `controllers/ml/` move to top-level `hbot/research/` and `hbot/ml/`? Same argument as backtesting. Deferring for now — they're small and well-isolated.
- **Q3:** The `scripts/shared/v2_with_controllers.py` (2,888 lines) is a god script for headless HB startup. Should it be split? Yes, but it's HB-framework-adjacent — defer to a separate change.
