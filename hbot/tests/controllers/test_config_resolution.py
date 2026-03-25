"""Tests for indicator_resolution config field and kernel wiring."""
from __future__ import annotations

import importlib.util

import pytest


def _hummingbot_available() -> bool:
    try:
        return importlib.util.find_spec("hummingbot") is not None
    except ValueError:
        return False


HUMMINGBOT_AVAILABLE = _hummingbot_available()

pytestmark = pytest.mark.skipif(not HUMMINGBOT_AVAILABLE, reason="hummingbot not installed")


class TestResolutionConfig:
    def test_default_is_1m(self):
        from controllers.runtime.kernel.config import EppV24Config
        cfg = EppV24Config(connector_name="paper_trade", trading_pair="BTC-USDT")
        assert cfg.indicator_resolution == "1m"

    def test_valid_15m(self):
        from controllers.runtime.kernel.config import EppV24Config
        cfg = EppV24Config(
            connector_name="paper_trade", trading_pair="BTC-USDT",
            indicator_resolution="15m",
        )
        assert cfg.indicator_resolution == "15m"

    def test_valid_5m(self):
        from controllers.runtime.kernel.config import EppV24Config
        cfg = EppV24Config(
            connector_name="paper_trade", trading_pair="BTC-USDT",
            indicator_resolution="5m",
        )
        assert cfg.indicator_resolution == "5m"

    def test_valid_1h(self):
        from controllers.runtime.kernel.config import EppV24Config
        cfg = EppV24Config(
            connector_name="paper_trade", trading_pair="BTC-USDT",
            indicator_resolution="1h",
        )
        assert cfg.indicator_resolution == "1h"

    def test_invalid_3m_rejected(self):
        from controllers.runtime.kernel.config import EppV24Config
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            EppV24Config(
                connector_name="paper_trade", trading_pair="BTC-USDT",
                indicator_resolution="3m",
            )

    def test_resolution_to_minutes_map(self):
        from controllers.runtime.kernel.config import _RESOLUTION_TO_MINUTES
        assert _RESOLUTION_TO_MINUTES == {"1m": 1, "5m": 5, "15m": 15, "1h": 60}


class TestSeedBarCalculation:
    """Seed bar tests use StartupMixin directly (no hummingbot dependency)."""

    def test_seed_bars_at_1m(self):
        from controllers.runtime.kernel.startup_mixin import StartupMixin

        class _FakeMixin(StartupMixin):
            def __init__(self):
                self.config = type("C", (), {
                    "ema_period": 20, "atr_period": 14,
                    "bot7_bb_period": 0, "bot7_rsi_period": 0,
                    "bot7_adx_period": 0,
                })()
                self._resolution_minutes = 1

        m = _FakeMixin()
        result = m._required_seed_bars()
        # max([20, 14+1=15]) = 20 → (20+5)*1 = 25
        assert result == 25

    def test_seed_bars_at_15m(self):
        from controllers.runtime.kernel.startup_mixin import StartupMixin

        class _FakeMixin(StartupMixin):
            def __init__(self):
                self.config = type("C", (), {
                    "ema_period": 20, "atr_period": 14,
                    "bot7_bb_period": 20, "bot7_rsi_period": 14,
                    "bot7_adx_period": 14,
                })()
                self._resolution_minutes = 15

        m = _FakeMixin()
        result = m._required_seed_bars()
        # max([20, 15, 20, 14, 14*2=28]) = 28 → (28+5)*15 = 495
        assert result == 495

    def test_seed_bars_no_resolution_attr_defaults_to_1(self):
        from controllers.runtime.kernel.startup_mixin import StartupMixin

        class _FakeMixin(StartupMixin):
            def __init__(self):
                self.config = type("C", (), {
                    "ema_period": 20, "atr_period": 14,
                    "bot7_bb_period": 0, "bot7_rsi_period": 0,
                    "bot7_adx_period": 0,
                })()

        m = _FakeMixin()
        result = m._required_seed_bars()
        assert result >= 25
        assert result < 60
