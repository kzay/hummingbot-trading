# Controllers Architecture Guide

This folder now supports strategy-specific lanes on top of shared runtime
modules. The goal is to avoid strategy-name coupling (for example, "EPP") in
new code while preserving backward compatibility for existing deployments.

## Layer Boundaries

- Data/feature ingestion:
  - `connector_runtime_adapter.py`
  - `price_buffer.py`
- Shared market-making runtime:
  - `strategy_runtime_base.py` (shared v2.4 base class aliases)
  - `market_making_types.py` (shared MM dataclasses and helpers)
  - `strategy_runtime_logging.py` (CSV/WAL logger exports)
- Strategy lanes (bot-specific behavior):
  - `bots/bot5/ift_jota_v1.py`
  - `bots/bot6/cvd_divergence_v1.py`
  - `bots/bot7/adaptive_grid_v1.py`
- Compatibility namespace for old imports:
  - `strategies/bot5_ift_jota_v1.py`
  - `strategies/bot6_cvd_divergence_v1.py`
  - `strategies/bot7_adaptive_grid_v1.py`
- Neutral lane entrypoints:
  - `bot5_ift_jota_v1.py`
  - `bot6_cvd_divergence_v1.py`
  - `bot7_adaptive_grid_v1.py`
- Legacy compatibility entrypoints:
  - `epp_v2_4.py`
  - `epp_v2_4_bot5.py`
  - `epp_v2_4_bot6.py`
  - `epp_v2_4_bot7.py`
  - `shared_mm_controller.py`
  - `shared_mm_types.py`
  - `shared_mm_logging.py`
  - `core.py`
  - `epp_logging.py`

## Canonical Imports For New Code

- Use `from controllers.runtime.base import StrategyRuntimeV24Config, StrategyRuntimeV24Controller`
- Use `from controllers.runtime.market_making_types import RegimeSpec, SpreadEdgeState, ...`
- Use `from controllers.runtime.logging import CsvSplitLogger`

## Strategy Isolation Contract

- Shared/runtime modules must never import `controllers.bots.*`.
- A bot strategy lane in `controllers/bots/` must not import another bot lane.
- `controllers/strategies/` is compatibility-only; keep real strategy logic in `controllers/bots/`.
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

The `shared_mm_v24` entrypoint is available as a neutral base for new market-
making lanes that do not want to inherit EPP naming.

Legacy `epp_v2_4_bot*` modules are now compatibility wrappers over the strategy
lane modules.

## Artifact Namespace

- Controllers can set `artifact_namespace` to choose runtime artifact/log paths.
- Defaults:
  - legacy `epp_*` controllers -> `epp_v24`
  - neutral controllers -> `runtime_v24`
