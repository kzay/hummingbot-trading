"""Tests for V3DeskIntegration — feature flag, shadow mode, lazy init."""

from __future__ import annotations

import os
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from controllers.runtime.v3.desk_integration import V3DeskIntegration


def _mock_legacy_strategy():
    """Build a mock legacy strategy with a controller."""
    strategy = MagicMock()
    controller = MagicMock()
    controller.controller_id = "test_ctrl"
    controller._tick_count = 1
    controller._last_mid = Decimal("65000")
    controller._last_book_bid = Decimal("64950")
    controller._last_book_ask = Decimal("65050")
    controller._last_book_bid_size = Decimal("1")
    controller._last_book_ask_size = Decimal("1")
    controller._ob_imbalance = Decimal("0")
    controller._book_stale_since_ts = 0
    controller._position_base = Decimal("0")
    controller._base_pct_net = Decimal("0")
    controller._base_pct_gross = Decimal("0")
    controller._avg_entry_price = Decimal("0")
    controller._is_perp = False
    controller._equity_quote = Decimal("5000")
    controller._daily_equity_open = Decimal("5000")
    controller._daily_equity_peak = Decimal("5000")
    controller._traded_notional_today = Decimal("0")
    controller._active_regime = "neutral_low_vol"
    controller._band_pct_ewma = Decimal("0")
    controller._regime_ema_value = Decimal("0")
    controller._regime_atr_value = Decimal("0")
    controller._funding_rate = Decimal("0")
    controller._mark_price = Decimal("0")
    controller._ml_direction_hint = ""
    controller._ml_direction_hint_confidence = 0.0
    controller._last_external_model_version = ""
    controller._external_regime_override = None
    controller._resolved_specs = {}
    # Bot1-specific attributes for migration shim
    controller._alpha_policy_state = "maker_two_sided"
    controller._alpha_policy_reason = "normal"
    controller._alpha_maker_score = Decimal("0.5")
    controller._alpha_aggressive_score = Decimal("0")
    controller._quote_side_mode = "off"

    pb = MagicMock()
    pb.ema = lambda p: Decimal("64800") if p == 20 else None
    pb.atr = lambda p: Decimal("350") if p == 14 else None
    pb.rsi = lambda p: Decimal("50") if p == 14 else None
    pb.adx = lambda p: Decimal("25") if p == 14 else None
    pb.bars_available = 250
    controller._price_buffer = pb

    cfg = MagicMock()
    cfg.connector_name = "bitget_perpetual"
    cfg.trading_pair = "BTC-USDT"
    cfg.leverage = 1
    cfg.max_daily_loss_pct_hard = Decimal("0.02")
    cfg.max_drawdown_pct_hard = Decimal("0.035")
    cfg.max_daily_turnover_x_hard = Decimal("14")
    cfg.min_net_edge_bps = Decimal("5.5")
    cfg.edge_resume_bps = Decimal("6.0")
    cfg.warmup_bars = 50
    for attr in ["total_amount_quote", "buy_spreads", "sell_spreads",
                 "executor_refresh_time", "stop_loss", "take_profit", "time_limit"]:
        setattr(cfg, attr, None)
    controller.config = cfg

    strategy.controllers = {"test_ctrl": controller}
    strategy._bus_client = None
    return strategy


class TestDisabledByDefault:
    def test_from_env_disabled(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("V3_DESK_ENABLED", None)
            desk = V3DeskIntegration.from_env(MagicMock())
            assert desk.enabled is False

    def test_tick_noop_when_disabled(self):
        desk = V3DeskIntegration(enabled=False)
        desk.tick()  # Should not raise
        assert desk._tick_count == 0


class TestShadowMode:
    def test_shadow_with_shim_only(self):
        with patch.dict(os.environ, {
            "V3_DESK_ENABLED": "true",
            "V3_DESK_MODE": "shadow",
            "V3_DESK_BOT_ID": "bot1",
            "V3_STRATEGY": "",
        }):
            strategy = _mock_legacy_strategy()
            desk = V3DeskIntegration.from_env(strategy)
            assert desk.enabled is True
            assert desk.mode == "shadow"

            # Tick should work (shim only, no native comparison)
            desk.tick()
            assert desk._tick_count == 1

    def test_shadow_with_native_comparison(self):
        with patch.dict(os.environ, {
            "V3_DESK_ENABLED": "true",
            "V3_DESK_MODE": "shadow",
            "V3_DESK_BOT_ID": "bot1",
            "V3_STRATEGY": "bot1_baseline",
        }):
            strategy = _mock_legacy_strategy()
            desk = V3DeskIntegration.from_env(strategy)
            desk.tick()
            assert desk._tick_count == 1

            # Should have shadow stats
            stats = desk.stats
            assert "total_ticks" in stats


class TestActiveMode:
    def test_active_mode_dry_run(self):
        with patch.dict(os.environ, {
            "V3_DESK_ENABLED": "true",
            "V3_DESK_MODE": "active",
            "V3_STRATEGY": "bot1_baseline",
        }):
            strategy = _mock_legacy_strategy()
            desk = V3DeskIntegration.from_env(strategy)
            desk.tick()
            assert desk._tick_count == 1


class TestFailSafe:
    def test_init_failure_disables_gracefully(self):
        with patch.dict(os.environ, {
            "V3_DESK_ENABLED": "true",
            "V3_DESK_MODE": "shadow",
            "V3_DESK_BOT_ID": "bot99",  # Invalid bot ID
            "V3_STRATEGY": "",
        }):
            strategy = _mock_legacy_strategy()
            desk = V3DeskIntegration.from_env(strategy)
            desk.tick()  # Should not raise
            assert desk.enabled is False  # Auto-disabled after init error
            assert "No extractor" in desk._init_error

    def test_no_controller_disables_gracefully(self):
        with patch.dict(os.environ, {
            "V3_DESK_ENABLED": "true",
            "V3_DESK_MODE": "shadow",
            "V3_DESK_BOT_ID": "bot1",
        }):
            strategy = MagicMock()
            strategy.controllers = {}  # No controllers
            desk = V3DeskIntegration.from_env(strategy)
            desk.tick()
            assert desk.enabled is False
            assert "No active controller" in desk._init_error
