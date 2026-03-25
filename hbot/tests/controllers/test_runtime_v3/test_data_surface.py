"""Tests for KernelDataSurface — snapshot assembly, caching, immutability."""

from __future__ import annotations

import dataclasses
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from controllers.runtime.v3.data_surface import KernelDataSurface
from controllers.runtime.v3.types import MarketSnapshot

_ZERO = Decimal("0")


def _make_mock_kernel(**overrides):
    """Build a minimal mock kernel with defaults for all attributes."""
    k = MagicMock()
    k._tick_count = 1
    k._last_book_bid = Decimal("64900")
    k._last_book_ask = Decimal("65100")
    k._last_book_bid_size = Decimal("1.5")
    k._last_book_ask_size = Decimal("2.0")
    k._last_mid = Decimal("65000")
    k._ob_imbalance = Decimal("0.15")
    k._book_stale_since_ts = 0
    k._position_base = Decimal("0.01")
    k._base_pct_net = Decimal("0.05")
    k._base_pct_gross = Decimal("0.05")
    k._avg_entry_price = Decimal("64500")
    k._is_perp = True
    k._equity_quote = Decimal("5000")
    k._daily_equity_open = Decimal("4950")
    k._daily_equity_peak = Decimal("5050")
    k._traded_notional_today = Decimal("25000")
    k._active_regime = "up"
    k._band_pct_ewma = Decimal("0.012")
    k._regime_ema_value = Decimal("64800")
    k._regime_atr_value = Decimal("350")
    k._funding_rate = Decimal("0.0001")
    k._mark_price = Decimal("65010")
    k._ml_direction_hint = ""
    k._ml_direction_hint_confidence = 0.0
    k._last_external_model_version = ""
    k._external_regime_override = None

    # Regime specs
    regime_spec = MagicMock()
    regime_spec.spread_min = Decimal("0.001")
    regime_spec.spread_max = Decimal("0.004")
    regime_spec.levels_min = 1
    regime_spec.levels_max = 3
    regime_spec.target_base_pct = Decimal("0")
    regime_spec.one_sided = "off"
    regime_spec.fill_factor = Decimal("0.40")
    regime_spec.refresh_s = 30
    k._resolved_specs = {"up": regime_spec}

    # Price buffer
    pb = MagicMock()
    pb.ema = lambda p: Decimal("64800") if p == 20 else None
    pb.atr = lambda p: Decimal("350") if p == 14 else None
    pb.rsi = lambda p: Decimal("55") if p == 14 else None
    pb.adx = lambda p: Decimal("28") if p == 14 else None
    pb.bars = [1] * 250  # 250 bars available
    k._price_buffer = pb

    # Config
    cfg = MagicMock()
    cfg.connector_name = "bitget_perpetual"
    cfg.trading_pair = "BTC-USDT"
    cfg.leverage = 1
    cfg.total_amount_quote = Decimal("500")
    cfg.buy_spreads = "0.001,0.002"
    cfg.sell_spreads = "0.001,0.002"
    cfg.executor_refresh_time = 60
    cfg.stop_loss = Decimal("0.005")
    cfg.take_profit = Decimal("0.010")
    cfg.time_limit = 3600
    cfg.min_net_edge_bps = Decimal("5.5")
    cfg.edge_resume_bps = Decimal("6.0")
    cfg.max_daily_loss_pct_hard = Decimal("0.02")
    cfg.max_drawdown_pct_hard = Decimal("0.035")
    cfg.max_daily_turnover_x_hard = Decimal("14")
    k.config = cfg

    for key, val in overrides.items():
        setattr(k, key, val)
    return k


class TestSnapshotAssembly:
    def test_basic_snapshot(self):
        k = _make_mock_kernel()
        surface = KernelDataSurface(k)
        snap = surface.snapshot()

        assert isinstance(snap, MarketSnapshot)
        assert snap.mid == Decimal("65000")
        assert snap.timestamp_ms > 0

    def test_order_book_fields(self):
        k = _make_mock_kernel()
        snap = KernelDataSurface(k).snapshot()

        assert snap.order_book.best_bid == Decimal("64900")
        assert snap.order_book.best_ask == Decimal("65100")
        assert snap.order_book.imbalance == Decimal("0.15")
        assert snap.order_book.stale is False

    def test_position_fields(self):
        k = _make_mock_kernel()
        snap = KernelDataSurface(k).snapshot()

        assert snap.position.base_amount == Decimal("0.01")
        assert snap.position.net_base_pct == Decimal("0.05")
        assert snap.position.avg_entry_price == Decimal("64500")
        assert snap.position.is_perp is True

    def test_equity_fields(self):
        k = _make_mock_kernel()
        snap = KernelDataSurface(k).snapshot()

        assert snap.equity.equity_quote == Decimal("5000")
        assert snap.equity.daily_open_equity == Decimal("4950")
        assert snap.equity.daily_pnl_quote == Decimal("50")
        assert snap.equity.daily_turnover_x == Decimal("5")  # 25000/5000

    def test_regime_fields(self):
        k = _make_mock_kernel()
        snap = KernelDataSurface(k).snapshot()

        assert snap.regime.name == "up"
        assert snap.regime.spread_min == Decimal("0.001")
        assert snap.regime.levels_max == 3
        assert snap.regime.one_sided == "off"

    def test_indicators_from_price_buffer(self):
        k = _make_mock_kernel()
        snap = KernelDataSurface(k).snapshot()

        assert snap.indicators.ema[20] == Decimal("64800")
        assert snap.indicators.atr[14] == Decimal("350")
        assert snap.indicators.rsi[14] == Decimal("55")
        assert snap.indicators.adx[14] == Decimal("28")
        assert snap.indicators.bars_available == 250

    def test_funding_present_for_perp(self):
        k = _make_mock_kernel()
        snap = KernelDataSurface(k).snapshot()

        assert snap.funding is not None
        assert snap.funding.funding_rate == Decimal("0.0001")
        assert snap.funding.mark_price == Decimal("65010")

    def test_funding_none_for_spot(self):
        k = _make_mock_kernel(_is_perp=False)
        snap = KernelDataSurface(k).snapshot()
        assert snap.funding is None

    def test_ml_none_when_not_configured(self):
        k = _make_mock_kernel()
        snap = KernelDataSurface(k).snapshot()
        assert snap.ml is None

    def test_ml_present_when_hint_set(self):
        k = _make_mock_kernel(
            _ml_direction_hint="buy",
            _ml_direction_hint_confidence=0.85,
            _last_external_model_version="v2.1",
        )
        snap = KernelDataSurface(k).snapshot()
        assert snap.ml is not None
        assert snap.ml.confidence == Decimal("0.85")
        assert snap.ml.model_version == "v2.1"


class TestSnapshotCaching:
    def test_same_tick_returns_cached(self):
        k = _make_mock_kernel()
        surface = KernelDataSurface(k)

        snap1 = surface.snapshot()
        snap2 = surface.snapshot()
        assert snap1 is snap2  # Same object, not recomputed

    def test_new_tick_recomputes(self):
        k = _make_mock_kernel()
        surface = KernelDataSurface(k)

        snap1 = surface.snapshot()
        k._tick_count = 2  # Simulate next tick
        snap2 = surface.snapshot()
        assert snap1 is not snap2  # Different object

    def test_invalidate_forces_recompute(self):
        k = _make_mock_kernel()
        surface = KernelDataSurface(k)

        snap1 = surface.snapshot()
        surface.invalidate()
        snap2 = surface.snapshot()
        assert snap1 is not snap2


class TestSnapshotImmutability:
    def test_snapshot_is_frozen(self):
        k = _make_mock_kernel()
        snap = KernelDataSurface(k).snapshot()
        with pytest.raises(dataclasses.FrozenInstanceError):
            snap.mid = Decimal("99999")  # type: ignore[misc]

    def test_sub_snapshots_are_frozen(self):
        k = _make_mock_kernel()
        snap = KernelDataSurface(k).snapshot()
        with pytest.raises(dataclasses.FrozenInstanceError):
            snap.order_book.best_bid = Decimal("99999")  # type: ignore[misc]
        with pytest.raises(dataclasses.FrozenInstanceError):
            snap.position.base_amount = Decimal("99")  # type: ignore[misc]


class TestEdgeCases:
    def test_missing_price_buffer(self):
        k = _make_mock_kernel()
        k._price_buffer = None
        snap = KernelDataSurface(k).snapshot()
        assert snap.indicators.ema == {}
        assert snap.indicators.bars_available == 0

    def test_zero_equity(self):
        k = _make_mock_kernel(_equity_quote=_ZERO, _daily_equity_open=_ZERO)
        snap = KernelDataSurface(k).snapshot()
        assert snap.equity.daily_turnover_x == _ZERO

    def test_unknown_regime(self):
        k = _make_mock_kernel(_active_regime="unknown_regime")
        snap = KernelDataSurface(k).snapshot()
        assert snap.regime.name == "unknown_regime"
        assert snap.regime.spread_min == _ZERO  # Defaults

    def test_mid_fallback_from_bid_ask(self):
        k = _make_mock_kernel(_last_mid=_ZERO)
        snap = KernelDataSurface(k).snapshot()
        # Falls back to (bid + ask) / 2
        assert snap.mid == Decimal("65000")

    def test_connector_info(self):
        k = _make_mock_kernel()
        surface = KernelDataSurface(k)
        info = surface.connector_info
        assert info["connector_name"] == "bitget_perpetual"
        assert info["trading_pair"] == "BTC-USDT"
        assert info["is_perp"] is True
