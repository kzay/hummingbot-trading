"""Tests for the v3 strategy registry — lookup, lazy loading, hydration."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from decimal import Decimal
from types import ModuleType
from typing import Any

import pytest

from controllers.runtime.v3.signals import TelemetrySchema, TradingSignal
from controllers.runtime.v3.strategy_registry import (
    STRATEGY_REGISTRY,
    StrategyEntry,
    _hydrate_config,
    clear_module_cache,
    get_entry,
    list_strategies,
    load_strategy,
)
from controllers.runtime.v3.types import MarketSnapshot


# ── Test fixtures: a fake strategy module ─────────────────────────────

@dataclass
class _FakeConfig:
    spread_pct: Decimal = Decimal("0.001")
    levels: int = 3
    enabled: bool = True


class _FakeSignalSource:
    def __init__(self, config: Any = None):
        self.config = config

    def evaluate(self, snapshot: MarketSnapshot) -> TradingSignal:
        return TradingSignal.no_trade("test")

    def warmup_bars_required(self) -> int:
        return 100

    def telemetry_schema(self) -> TelemetrySchema:
        return TelemetrySchema()


def _install_fake_module():
    """Install a fake strategy module in sys.modules for testing."""
    mod = ModuleType("controllers.bots.test_bot.fake_signals")
    mod.FakeSignalSource = _FakeSignalSource  # type: ignore[attr-defined]
    mod.FakeConfig = _FakeConfig  # type: ignore[attr-defined]
    sys.modules["controllers.bots.test_bot.fake_signals"] = mod
    return mod


def _cleanup_fake_module():
    sys.modules.pop("controllers.bots.test_bot.fake_signals", None)
    clear_module_cache()


# ── Tests ─────────────────────────────────────────────────────────────


class TestStrategyEntry:
    def test_frozen_dataclass(self):
        entry = StrategyEntry(
            module_path="x",
            signal_class="Y",
            execution_family="directional",
        )
        assert entry.execution_family == "directional"
        assert entry.risk_profile == "moderate"  # default


class TestRegistryLookup:
    def test_missing_strategy_raises_key_error(self):
        with pytest.raises(KeyError, match="not_registered"):
            load_strategy("not_registered")

    def test_get_entry_missing_raises(self):
        with pytest.raises(KeyError):
            get_entry("nonexistent")

    def test_list_strategies_returns_sorted(self):
        result = list_strategies()
        assert result == sorted(result)


class TestLazyLoading:
    def setup_method(self):
        _install_fake_module()
        STRATEGY_REGISTRY["test_fake"] = StrategyEntry(
            module_path="controllers.bots.test_bot.fake_signals",
            signal_class="FakeSignalSource",
            config_class="FakeConfig",
            execution_family="mm_grid",
            decimal_attrs=("spread_pct",),
            int_attrs=("levels",),
            bool_attrs=("enabled",),
        )

    def teardown_method(self):
        STRATEGY_REGISTRY.pop("test_fake", None)
        _cleanup_fake_module()

    def test_load_without_config(self):
        source = load_strategy("test_fake")
        assert hasattr(source, "evaluate")
        assert hasattr(source, "warmup_bars_required")

    def test_load_with_config_hydration(self):
        source = load_strategy("test_fake", config={
            "spread_pct": "0.002",
            "levels": "5",
            "enabled": True,
        })
        assert source.config.spread_pct == Decimal("0.002")
        assert source.config.levels == 5
        assert source.config.enabled is True

    def test_config_ignores_unknown_keys(self):
        source = load_strategy("test_fake", config={
            "spread_pct": "0.001",
            "levels": "3",
            "unknown_field": "ignored",
        })
        assert source.config.spread_pct == Decimal("0.001")
        assert not hasattr(source.config, "unknown_field")

    def test_strategy_satisfies_protocol(self):
        source = load_strategy("test_fake")
        snap = MarketSnapshot()
        sig = source.evaluate(snap)
        assert isinstance(sig, TradingSignal)
        assert sig.family == "no_trade"

    def test_warmup_bars(self):
        source = load_strategy("test_fake")
        assert source.warmup_bars_required() == 100

    def test_get_entry(self):
        entry = get_entry("test_fake")
        assert entry.execution_family == "mm_grid"

    def test_list_includes_registered(self):
        assert "test_fake" in list_strategies()


class TestHydrateConfig:
    def test_decimal_hydration(self):
        entry = StrategyEntry(
            module_path="x",
            signal_class="Y",
            decimal_attrs=("value",),
        )
        cfg = _hydrate_config(_FakeConfig, {"spread_pct": "0.005"}, entry)
        # spread_pct is not in decimal_attrs so stays as string
        assert cfg.spread_pct == "0.005"

    def test_int_hydration(self):
        entry = StrategyEntry(
            module_path="x",
            signal_class="Y",
            int_attrs=("levels",),
        )
        cfg = _hydrate_config(_FakeConfig, {"levels": "7"}, entry)
        assert cfg.levels == 7
        assert isinstance(cfg.levels, int)

    def test_bool_hydration(self):
        entry = StrategyEntry(
            module_path="x",
            signal_class="Y",
            bool_attrs=("enabled",),
        )
        cfg = _hydrate_config(_FakeConfig, {"enabled": 0}, entry)
        assert cfg.enabled is False


class TestModuleCache:
    def setup_method(self):
        _install_fake_module()
        STRATEGY_REGISTRY["test_fake"] = StrategyEntry(
            module_path="controllers.bots.test_bot.fake_signals",
            signal_class="FakeSignalSource",
        )

    def teardown_method(self):
        STRATEGY_REGISTRY.pop("test_fake", None)
        _cleanup_fake_module()

    def test_clear_cache(self):
        load_strategy("test_fake")
        clear_module_cache()
        # Should not error — reimports cleanly
        load_strategy("test_fake")
