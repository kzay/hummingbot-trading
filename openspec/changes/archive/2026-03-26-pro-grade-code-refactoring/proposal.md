## Why

This is a live trading desk. Performance, robustness, and correctness are non-negotiable. The codebase has grown organically over 40+ development days and now carries significant architectural debt AND production-grade gaps that create real risk of silent failures, data corruption, and latency spikes. Key symptoms:

**Architectural debt:**
- **God modules**: `shared_runtime_v24.py` (4,376 lines), `hb_bridge.py` (2,655 lines), `paper_exchange_service/main.py` (3,529 lines), `run_promotion_gates.py` (4,692 lines) concentrate change risk.
- **Layer violations**: 28+ controller modules import `services.*`, making "pure strategy logic" impossible to test without service stubs.
- **Misplaced packages**: `paper_engine_v2/` (a simulation library) lives inside `controllers/` despite being consumed by both services and backtesting — wrong abstraction layer.
- **Triple import shims**: Every strategy exists in 3 locations (`bots/botN/`, root `controllers/`, and `directional/` or `market_making/`) creating a confusing naming surface.
- **Empty/dead packages**: `controllers/strategies/` is empty; `shared_mm_v24.py` is a rename shim.
- **Flat mega-directories**: `backtesting/` has 35 files flat; `scripts/` has 116 files with mixed ops/analysis/release/ML concerns.
- **Controllers ↔ runtime cycle**: `shared_runtime_v24` ↔ `runtime/` have mutual imports creating fragile initialization order.

**Robustness gaps (verified by static audit 2026-03-22):**
- **Silent exception swallowing**: ~61 `except Exception: pass` blocks across controllers and services — including in hot paths like `hb_event_fire.py`, `data_feeds.py`, `desk.py`, and `hb_bridge.py`. These hide bugs in production.
- **Type safety holes**: ~50 `# type: ignore` directives, 90+ uses of `Any` in core files (`hb_bridge` alone has 67), missing return type annotations on critical public methods like `update_processed_data()`.
- **`print()` in production code**: 76 `print()` calls in controllers (6 in `hb_bridge.py`), 9 in services — bypasses structured logging, invisible in log aggregation.
- **Mutable module-level singletons**: `_bridge_state = BridgeState()` in `hb_bridge.py` holding Redis handles and caches with no thread-safety documentation or enforcement.
- **Test coverage gaps**: No dedicated tests for `sim_broker`, `telemetry_mixin`, `auto_calibration_mixin`, `risk_mixin` — critical trading infrastructure untested.
- **Unconstrained config fields**: `regime_specs_override` and similar `dict[str, Any]` fields accept arbitrary nested structures with no schema validation.

This refactoring standardizes the codebase to a clean, pro-grade layered architecture where each module has one job, dependencies flow downward, the structure communicates intent, exceptions are never silently swallowed, types are enforced, and every critical path has test coverage.

## What Changes

- **BREAKING**: Extract `controllers/paper_engine_v2/` to top-level `hbot/simulation/` — all imports change from `controllers.paper_engine_v2` to `simulation`.
- **BREAKING**: Break `shared_runtime_v24.py` (4,376 LOC) into ~8 focused submodules under `controllers/runtime/kernel/` — quoting, risk, state, paper hooks, telemetry, calibration, regime, startup.
- **BREAKING**: Break `paper_engine_v2/hb_bridge.py` (2,655 LOC) into ~4 modules — event routing, subscriber management, connector patches, signal handling.
- Extract `services/common/` into `hbot/platform/` (shared library consumed by both controllers and services, not a "service" itself).
- Consolidate loader shims: merge `controllers/directional/`, `controllers/market_making/`, and root wrapper files into `controllers/hb_loader_shims/` with explicit documentation.
- Delete dead code: `controllers/strategies/` (empty), `shared_mm_v24.py` (pure alias), stale root shims after consolidation.
- Reorganize `scripts/` from flat 116-file directory into `scripts/{ops,release,analysis,backtest,ml}/` subpackages (partially done, finish it).
- Split god services: `paper_exchange_service/main.py` (3,529 LOC) into service wiring + protocol handlers + lifecycle.
- Split god tests alongside their code modules to maintain 1:1 test correspondence.
- Add `__all__` exports and module docstrings to every public package `__init__.py`.
- Establish import boundary enforcement via a contract test.

## Capabilities

### New Capabilities
- `simulation-extraction`: Extract paper_engine_v2 from controllers to standalone `hbot/simulation/` library with clean public API.
- `runtime-kernel-split`: Decompose shared_runtime_v24.py god module into coherent kernel submodules.
- `hb-bridge-split`: Decompose hb_bridge.py into focused modules (events, subscribers, patches, signals).
- `platform-library`: Extract services/common into hbot/platform as a shared dependency layer below both controllers and services.
- `loader-shim-consolidation`: Merge all HB controller-loader shims into a single documented package.
- `scripts-reorganization`: Complete scripts/ directory reorganization into purpose-based subpackages.
- `service-decomposition`: Split god service main.py files into wiring + handlers + lifecycle.
- `import-boundary-enforcement`: Contract test preventing upward/lateral import violations.
- `dead-code-cleanup`: Remove empty packages, unused shims, and stale aliases.
- `error-handling-hardening`: Eliminate silent exception swallowing, replace with typed exceptions, metrics counters, and degraded-mode flags across all hot paths.
- `type-safety-enforcement`: Add return type annotations to all public methods, eliminate `Any` from core trading paths, add strict mypy config for critical modules.
- `logging-standardization`: Replace all `print()` in production code with structured logger calls, enforce structured logging contract.
- `test-coverage-critical-paths`: Add targeted tests for untested trading-critical modules (sim_broker, telemetry_mixin, auto_calibration_mixin, risk_mixin, hb_bridge edge cases).
- `concurrency-safety`: Document and enforce single-threaded access contracts on mutable singletons, add runtime guards where needed.

### Modified Capabilities
<!-- No existing OpenSpec specs have requirements changes — this is a structural refactoring. -->

## Impact

- **All Python imports** referencing `controllers.paper_engine_v2` change to `simulation`.
- **All Python imports** referencing `services.common` change to `platform` (or thin re-export shim during migration).
- **controllers/shared_runtime_v24.py** splits into ~8 files — every file importing from it needs path updates.
- **controllers/paper_engine_v2/hb_bridge.py** splits into ~4 files — importers need updates.
- **Test files** that import split modules need corresponding updates.
- **Docker containers** unaffected (mount paths unchanged; this is Python-internal).
- **YAML configs** unaffected (controller_name resolution preserved by loader shims).
- **No strategy logic changes** — pure structural refactoring, behavior must be identical.
