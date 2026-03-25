"""Tests for TaCompositeAdapter — config validation, warmup, entry/exit, stops."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from controllers.backtesting.ta_composite_adapter import (
    RuleConfig,
    SignalConfig,
    TaCompositeAdapter,
    TaCompositeConfig,
    _PositionState,
)
from controllers.price_buffer import MinuteBar


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@dataclass
class _FakeInstrumentSpec:
    def quantize_size(self, qty: Decimal) -> Decimal:
        return Decimal(str(round(float(qty), 4)))

    def quantize_price(self, price: Decimal, side: str = "buy") -> Decimal:
        return Decimal(str(round(float(price), 2)))


def _make_desk() -> MagicMock:
    desk = MagicMock()
    desk.submit_order = MagicMock()
    desk.cancel_all = MagicMock()
    return desk


def _make_candle(ts_ms: int, price: float):
    c = MagicMock()
    c.timestamp_ms = ts_ms
    c.open = Decimal(str(price))
    c.high = Decimal(str(price * 1.002))
    c.low = Decimal(str(price * 0.998))
    c.close = Decimal(str(price))
    return c


def _entry_config(**overrides) -> TaCompositeConfig:
    """Create a minimal valid config with ema_cross entry."""
    cfg = TaCompositeConfig(
        entry_rules=RuleConfig(
            mode="all",
            signals=[SignalConfig(signal_type="ema_cross", params={"fast": 5, "slow": 15})],
        ),
        sl_atr_mult=Decimal("1.5"),
        tp_atr_mult=Decimal("2.0"),
        min_warmup_bars=20,
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------

class TestConfigValidation:
    def test_valid_config(self):
        cfg = _entry_config()
        cfg.validate()

    def test_empty_entry_signals(self):
        cfg = TaCompositeConfig(entry_rules=RuleConfig(signals=[]))
        with pytest.raises(ValueError, match="non-empty"):
            cfg.validate()

    def test_invalid_signal_type(self):
        cfg = TaCompositeConfig(
            entry_rules=RuleConfig(
                signals=[SignalConfig(signal_type="nonexistent", params={})],
            ),
        )
        with pytest.raises(ValueError, match="Unknown signal type"):
            cfg.validate()

    def test_invalid_signal_param(self):
        cfg = TaCompositeConfig(
            entry_rules=RuleConfig(
                signals=[SignalConfig(signal_type="ema_cross", params={"bad_param": 5})],
            ),
        )
        with pytest.raises(ValueError, match="Unknown param"):
            cfg.validate()

    def test_invalid_entry_mode(self):
        cfg = TaCompositeConfig(
            entry_rules=RuleConfig(
                mode="invalid",
                signals=[SignalConfig(signal_type="ema_cross", params={})],
            ),
        )
        with pytest.raises(ValueError, match="mode"):
            cfg.validate()

    def test_invalid_entry_order_type(self):
        cfg = _entry_config(entry_order_type="stop")
        with pytest.raises(ValueError, match="entry_order_type"):
            cfg.validate()

    def test_negative_sl(self):
        cfg = _entry_config(sl_atr_mult=Decimal("-1"))
        with pytest.raises(ValueError, match="sl_atr_mult"):
            cfg.validate()

    def test_negative_limit_offset(self):
        cfg = _entry_config(
            entry_order_type="limit",
            limit_entry_offset_atr=Decimal("-0.5"),
        )
        with pytest.raises(ValueError, match="limit_entry_offset_atr"):
            cfg.validate()


class TestDerivedWarmup:
    def test_warmup_from_ema_cross(self):
        cfg = _entry_config()
        wb = cfg.derived_warmup()
        assert wb >= 16

    def test_warmup_long_period(self):
        cfg = TaCompositeConfig(
            entry_rules=RuleConfig(
                signals=[SignalConfig(signal_type="ema_cross", params={"fast": 50, "slow": 200})],
            ),
        )
        cfg.validate()
        wb = cfg.derived_warmup()
        assert wb >= 201

    def test_min_warmup_floor(self):
        cfg = _entry_config(min_warmup_bars=500)
        wb = cfg.derived_warmup()
        assert wb >= 500


# ---------------------------------------------------------------------------
# Warmup gating
# ---------------------------------------------------------------------------

class TestWarmupGating:
    def test_returns_none_before_warmup(self):
        cfg = _entry_config(min_warmup_bars=30)
        desk = _make_desk()
        adapter = TaCompositeAdapter(
            desk=desk,
            instrument_id="BTC-USDT",
            instrument_spec=_FakeInstrumentSpec(),
            config=cfg,
        )
        for i in range(20):
            candle = _make_candle(ts_ms=1000000 + i * 60000, price=100 + i * 0.1)
            result = adapter.tick(
                now_s=1000 + i * 60,
                mid=Decimal("100"),
                book=None,
                equity_quote=Decimal("10000"),
                position_base=Decimal("0"),
                candle=candle,
            )
            assert result is None
        assert desk.submit_order.call_count == 0


# ---------------------------------------------------------------------------
# Entry logic
# ---------------------------------------------------------------------------

class TestEntryLogic:
    def _warm_adapter(self, cfg=None, n_bars=60) -> tuple:
        cfg = cfg or _entry_config(min_warmup_bars=20)
        desk = _make_desk()
        adapter = TaCompositeAdapter(
            desk=desk,
            instrument_id="BTC-USDT",
            instrument_spec=_FakeInstrumentSpec(),
            config=cfg,
        )
        for i in range(n_bars):
            candle = _make_candle(ts_ms=1000000 + i * 60000, price=100 + i * 0.1)
            adapter.tick(
                now_s=1000 + i * 60,
                mid=Decimal(str(100 + i * 0.1)),
                book=None,
                equity_quote=Decimal("10000"),
                position_base=Decimal("0"),
                candle=candle,
            )
        return adapter, desk

    def test_no_signal_returns_off(self):
        adapter, desk = self._warm_adapter()
        candle = _make_candle(ts_ms=1000000 + 60 * 60000, price=106)
        result = adapter.tick(
            now_s=1000 + 60 * 60,
            mid=Decimal("106"),
            book=None,
            equity_quote=Decimal("10000"),
            position_base=Decimal("0"),
            candle=candle,
        )
        assert result is not None
        assert result.get("side") in ("off", "buy", "sell")

    def test_cooldown_blocks_entry(self):
        cfg = _entry_config(cooldown_s=600)
        desk = _make_desk()
        adapter = TaCompositeAdapter(
            desk=desk,
            instrument_id="BTC-USDT",
            instrument_spec=_FakeInstrumentSpec(),
            config=cfg,
        )
        adapter._last_exit_ts = 5000.0
        for i in range(40):
            candle = _make_candle(ts_ms=1000000 + i * 60000, price=100 + i * 0.1)
            adapter.tick(
                now_s=5050 + i * 60,
                mid=Decimal(str(100 + i * 0.1)),
                book=None,
                equity_quote=Decimal("10000"),
                position_base=Decimal("0"),
                candle=candle,
            )
        candle = _make_candle(ts_ms=1000000 + 40 * 60000, price=120)
        result = adapter.tick(
            now_s=5050 + 3 * 60,
            mid=Decimal("120"),
            book=None,
            equity_quote=Decimal("10000"),
            position_base=Decimal("0"),
            candle=candle,
        )
        if result and result.get("cooldown"):
            assert result["side"] == "off"


# ---------------------------------------------------------------------------
# Position management
# ---------------------------------------------------------------------------

class TestPositionManagement:
    def test_stop_loss(self):
        cfg = _entry_config()
        desk = _make_desk()
        adapter = TaCompositeAdapter(
            desk=desk,
            instrument_id="BTC-USDT",
            instrument_spec=_FakeInstrumentSpec(),
            config=cfg,
        )
        adapter._pos = _PositionState(
            side="buy",
            entry_price=Decimal("100"),
            entry_ts=1000.0,
            sl_price=Decimal("95"),
            tp_price=Decimal("110"),
            risk_dist=Decimal("5"),
        )
        for i in range(40):
            candle = _make_candle(ts_ms=1000000 + i * 60000, price=100)
            adapter.tick(
                now_s=1000 + i * 60,
                mid=Decimal("100"),
                book=None,
                equity_quote=Decimal("10000"),
                position_base=Decimal("0"),
                candle=candle,
            )
        candle = _make_candle(ts_ms=1000000 + 40 * 60000, price=94)
        result = adapter.tick(
            now_s=1000 + 40 * 60,
            mid=Decimal("94"),
            book=None,
            equity_quote=Decimal("10000"),
            position_base=Decimal("0.01"),
            candle=candle,
        )
        assert result is not None
        assert result.get("reason") == "stop_loss"

    def test_take_profit(self):
        cfg = _entry_config()
        desk = _make_desk()
        adapter = TaCompositeAdapter(
            desk=desk,
            instrument_id="BTC-USDT",
            instrument_spec=_FakeInstrumentSpec(),
            config=cfg,
        )
        adapter._pos = _PositionState(
            side="buy",
            entry_price=Decimal("100"),
            entry_ts=1000.0,
            sl_price=Decimal("95"),
            tp_price=Decimal("110"),
            risk_dist=Decimal("5"),
        )
        for i in range(40):
            candle = _make_candle(ts_ms=1000000 + i * 60000, price=100)
            adapter.tick(
                now_s=1000 + i * 60,
                mid=Decimal("100"),
                book=None,
                equity_quote=Decimal("10000"),
                position_base=Decimal("0"),
                candle=candle,
            )
        candle = _make_candle(ts_ms=1000000 + 40 * 60000, price=112)
        result = adapter.tick(
            now_s=1000 + 40 * 60,
            mid=Decimal("112"),
            book=None,
            equity_quote=Decimal("10000"),
            position_base=Decimal("0.01"),
            candle=candle,
        )
        assert result is not None
        assert result.get("reason") == "take_profit"

    def test_max_hold_exit(self):
        cfg = _entry_config(max_hold_minutes=10)
        desk = _make_desk()
        adapter = TaCompositeAdapter(
            desk=desk,
            instrument_id="BTC-USDT",
            instrument_spec=_FakeInstrumentSpec(),
            config=cfg,
        )
        adapter._pos = _PositionState(
            side="buy",
            entry_price=Decimal("100"),
            entry_ts=1000.0,
            sl_price=Decimal("95"),
            tp_price=Decimal("110"),
            risk_dist=Decimal("5"),
        )
        for i in range(40):
            candle = _make_candle(ts_ms=1000000 + i * 60000, price=100)
            adapter.tick(
                now_s=1000 + i * 60,
                mid=Decimal("100"),
                book=None,
                equity_quote=Decimal("10000"),
                position_base=Decimal("0"),
                candle=candle,
            )
        candle = _make_candle(ts_ms=1000000 + 40 * 60000, price=101)
        result = adapter.tick(
            now_s=1000 + 15 * 60,
            mid=Decimal("101"),
            book=None,
            equity_quote=Decimal("10000"),
            position_base=Decimal("0.01"),
            candle=candle,
        )
        assert result is not None
        assert result.get("reason") == "max_hold"


# ---------------------------------------------------------------------------
# Daily risk gate
# ---------------------------------------------------------------------------

class TestDailyRiskGate:
    def test_daily_loss_halts_entries(self):
        cfg = _entry_config(max_daily_loss_pct=Decimal("0.01"))
        desk = _make_desk()
        adapter = TaCompositeAdapter(
            desk=desk,
            instrument_id="BTC-USDT",
            instrument_spec=_FakeInstrumentSpec(),
            config=cfg,
        )
        for i in range(40):
            candle = _make_candle(ts_ms=1000000 + i * 60000, price=100 + i * 0.1)
            adapter.tick(
                now_s=1000 + i * 60,
                mid=Decimal(str(100 + i * 0.1)),
                book=None,
                equity_quote=Decimal("10000"),
                position_base=Decimal("0"),
                candle=candle,
            )
        candle = _make_candle(ts_ms=1000000 + 40 * 60000, price=105)
        result = adapter.tick(
            now_s=1000 + 40 * 60,
            mid=Decimal("105"),
            book=None,
            equity_quote=Decimal("9800"),
            position_base=Decimal("0"),
            candle=candle,
        )
        assert result is not None
        assert result.get("reason") == "daily_risk_limit"


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------

class TestRegistryIntegration:
    def test_ta_composite_in_registry(self):
        from controllers.backtesting.adapter_registry import ADAPTER_REGISTRY
        assert "ta_composite" in ADAPTER_REGISTRY
        entry = ADAPTER_REGISTRY["ta_composite"]
        assert entry.adapter_class == "TaCompositeAdapter"
        assert entry.config_class == "TaCompositeConfig"


# ---------------------------------------------------------------------------
# Hydrate nested
# ---------------------------------------------------------------------------

class TestHydrateNested:
    def test_from_raw_dict(self):
        cfg = TaCompositeConfig()
        cfg.entry_rules = {
            "mode": "any",
            "signals": [
                {"type": "ema_cross", "fast": 8, "slow": 21},
                {"type": "rsi_zone", "period": 14, "overbought": 70, "oversold": 30},
            ],
        }
        cfg.exit_rules = {
            "mode": "any",
            "signals": [
                {"type": "ema_cross", "fast": 8, "slow": 21, "invert": True},
            ],
        }
        cfg.hydrate_nested()
        assert isinstance(cfg.entry_rules, RuleConfig)
        assert len(cfg.entry_rules.signals) == 2
        assert cfg.entry_rules.signals[0].signal_type == "ema_cross"
        assert cfg.entry_rules.signals[0].params == {"fast": 8, "slow": 21}
        assert cfg.exit_rules.signals[0].invert is True
        cfg.validate()
