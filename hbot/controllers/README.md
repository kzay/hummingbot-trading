# Controllers Architecture Guide

This folder now supports strategy-specific lanes on top of shared runtime
modules. The goal is to avoid strategy-name coupling (for example, "EPP") in
new code while preserving backward compatibility for existing deployments.

## Layer Boundaries

- Data/feature ingestion:
  - `connector_runtime_adapter.py`
  - `price_buffer.py`
- Shared runtime kernel:
  - `shared_runtime_v24.py` (SharedRuntimeKernel + EppV24Controller subclass)
  - `runtime/kernel.py` (re-export of SharedRuntimeKernel)
  - `runtime/base.py` (shared v2.4 base aliases)
  - `runtime/contracts.py` (neutral lane/runtime hook contracts)
  - `runtime/core.py` (compatibility surface helpers for artifacts and telemetry)
  - `runtime/data_context.py` (neutral runtime input assembly)
  - `runtime/directional_core.py` (explicit directional execution-family adapter)
  - `runtime/directional_config.py` (directional config with MM defaults locked)
  - `runtime/directional_runtime.py` (directional runtime extending kernel)
  - `runtime/risk_context.py` (neutral risk decision contract)
  - `runtime/execution_context.py` (neutral execution plan contract)
  - `runtime/market_making_core.py` (explicit market-making family adapter)
  - `runtime/runtime_types.py` (shared runtime dataclasses and helpers)
  - `runtime/logging.py` (CSV/WAL logger exports)
- Strategy lanes (bot-specific behavior):
  - `bots/bot5/ift_jota_v1.py`
  - `bots/bot6/cvd_divergence_v1.py`
  - `bots/bot7/pullback_v1.py`
- Neutral lane entrypoints:
  - `bot5_ift_jota_v1.py`
  - `bot6_cvd_divergence_v1.py`
  - `bot7_pullback_v1.py`
- Legacy compatibility entrypoints:
  - `epp_v2_4.py`
  - `epp_v2_4_bot5.py`
  - `epp_v2_4_bot6.py`
  - `epp_v2_4_bot7.py`
  - `core.py`
  - `epp_logging.py`

## Canonical Imports For New Code

### Market-making lanes (bot1):
- Use `from controllers.runtime.base import StrategyRuntimeV24Config, StrategyRuntimeV24Controller`

### Directional lanes (bot5, bot6, bot7):
- Use `from controllers.runtime.base import DirectionalStrategyRuntimeV24Config, DirectionalStrategyRuntimeV24Controller`

### Shared across both:
- Use `from controllers.runtime.data_context import RuntimeDataContext`
- Use `from controllers.runtime.execution_context import RuntimeExecutionPlan`
- Use `from controllers.runtime.risk_context import RuntimeRiskDecision`
- Use `from controllers.runtime.runtime_types import RegimeSpec, SpreadEdgeState, ...`
- Use `from controllers.runtime.logging import CsvSplitLogger`

## Strategy Isolation Contract

- Shared/runtime modules must never import `controllers.bots.*`.
- A bot strategy lane in `controllers/bots/` must not import another bot lane.
- `controllers/market_making/` is reserved for market-making loader shims only.
- Non-market-making strategy code must not be placed under `controllers/market_making/`.
- Legacy `epp_v2_4_bot*` modules are wrappers only; strategy logic belongs in `controllers/bots/`.
- Validate boundaries with:
  - `PYTHONPATH=hbot python -m pytest hbot/tests/controllers/test_strategy_isolation_contract.py -q`
  - `PYTHONPATH=hbot python -m pytest hbot/tests/controllers/test_market_making_shim_contract.py -q`

## New Strategy Naming

For new strategy lanes, prefer neutral controller names and files that describe
the lane behavior instead of legacy family labels. Example pattern:

- controller module: `<lane_name>_v1.py`
- controller name: `<lane_name>_v1`
- market-making shim: `controllers/market_making/<lane_name>_v1.py`

The `shared_runtime_v24` entrypoint is available as a neutral base for new market-
making lanes that do not want to inherit EPP naming.

Legacy `epp_v2_4_bot*` modules are now compatibility wrappers over the strategy
lane modules.

## Artifact Namespace

- Controllers can set `artifact_namespace` to choose runtime artifact/log paths.
- Defaults:
  - legacy `epp_*` controllers -> `epp_v24`
  - neutral controllers -> `runtime_v24`
- Runtime contract metadata is additive-only:
  - `controller_contract_version`
  - `runtime_impl`
- Keep existing v1 stream names, `controller_id`, artifact namespaces, and daily-state prefixes stable while migrating internals.
