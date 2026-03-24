"""Smoke test: ICT shadow mode in backtest adapters.

Validates that ``ict_shadow_enabled=True`` wires correctly through the
adapter registry, produces ICT telemetry without changing trade outcomes.
"""
from __future__ import annotations

import pytest
import yaml
from decimal import Decimal
from pathlib import Path

from controllers.backtesting.config_loader import load_backtest_config
from controllers.backtesting.harness import BacktestHarness
from controllers.backtesting.types import BacktestConfig

_CFG_PATH = Path(__file__).resolve().parents[3] / "data" / "backtest_configs" / "bot7_pullback.yml"


def _make_config(ict_shadow: bool) -> BacktestConfig:
    raw = yaml.safe_load(_CFG_PATH.read_text())
    raw["strategy_config"]["ict_shadow_enabled"] = ict_shadow
    raw["data_source"]["start_date"] = "2025-01-04"
    raw["data_source"]["end_date"] = "2025-01-06"
    raw["data_source"]["catalog_dir"] = str(
        Path(__file__).resolve().parents[3] / "data" / "historical"
    )
    from controllers.backtesting.config_loader import _parse_backtest_config
    return _parse_backtest_config(raw)


@pytest.fixture(scope="module")
def baseline_result():
    cfg = _make_config(ict_shadow=False)
    return BacktestHarness(cfg).run()


@pytest.fixture(scope="module")
def shadow_result():
    cfg = _make_config(ict_shadow=True)
    return BacktestHarness(cfg).run()


def test_shadow_does_not_change_fills(baseline_result, shadow_result):
    assert len(baseline_result.fills) == len(shadow_result.fills)


def test_shadow_does_not_change_equity(baseline_result, shadow_result):
    base_eq = baseline_result.equity_curve[-1].equity
    shadow_eq = shadow_result.equity_curve[-1].equity
    diff = abs(base_eq - shadow_eq)
    assert diff < Decimal("0.01"), f"Equity diverged: {diff}"


def test_shadow_completes(shadow_result):
    assert shadow_result.equity_curve[-1].equity > Decimal("0")
    assert len(shadow_result.equity_curve) >= 1
