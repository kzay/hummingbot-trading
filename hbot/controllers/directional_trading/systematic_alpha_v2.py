"""
Systematic Alpha V2 — Cost-Aware Regime Long/Short Directional Strategy
========================================================================

Objective:
  Improve return/drawdown balance vs directional_max_min_v1 by combining:
    - Regime-aware trend + mean-reversion factors
    - Explicit long/short support for perpetual markets
    - Cost gate (fees + slippage + funding) before opening risk
    - Volatility-targeted position sizing with hard caps
    - ATR-based asymmetric risk controls for long vs short
"""

from __future__ import annotations

import datetime
import logging
import math
from decimal import Decimal
from typing import List, Optional, Tuple

import pandas as pd
import pandas_ta as ta  # noqa: F401
from pydantic import Field, field_validator
from pydantic_core.core_schema import ValidationInfo

from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.data_feed.candles_feed.data_types import CandlesConfig
from hummingbot.strategy_v2.controllers.directional_trading_controller_base import (
    DirectionalTradingControllerBase,
    DirectionalTradingControllerConfigBase,
)
from hummingbot.strategy_v2.executors.position_executor.data_types import (
    PositionExecutorConfig,
    TrailingStop,
    TripleBarrierConfig,
)

logger = logging.getLogger(__name__)


class SystematicAlphaV2Config(DirectionalTradingControllerConfigBase):
    controller_name: str = "systematic_alpha_v2"

    # Data sources
    candles_connector: Optional[str] = Field(default=None, json_schema_extra={
        "prompt": "Candles connector (empty=same as connector): ", "prompt_on_new": True})
    candles_trading_pair: Optional[str] = Field(default=None, json_schema_extra={
        "prompt": "Candles pair (empty=same as trading_pair): ", "prompt_on_new": True})
    interval_slow: str = Field(default="1h", json_schema_extra={
        "prompt": "Slow interval for trend/ATR (e.g. 1h): ", "prompt_on_new": True})
    interval_fast: str = Field(default="15m", json_schema_extra={
        "prompt": "Fast interval for reversion/vol (e.g. 15m): ", "prompt_on_new": True})

    # Regime + signals
    breakout_lookback: int = Field(default=20, json_schema_extra={"is_updatable": True})
    ema_fast: int = Field(default=20, json_schema_extra={"is_updatable": True})
    ema_slow: int = Field(default=80, json_schema_extra={"is_updatable": True})
    adx_length: int = Field(default=14, json_schema_extra={"is_updatable": True})
    adx_trend_threshold: float = Field(default=24.0, json_schema_extra={"is_updatable": True})
    rsi_length: int = Field(default=14, json_schema_extra={"is_updatable": True})
    bb_length: int = Field(default=20, json_schema_extra={"is_updatable": True})
    bb_std: float = Field(default=2.0, json_schema_extra={"is_updatable": True})
    trend_weight: float = Field(default=0.55, json_schema_extra={"is_updatable": True})
    reversion_weight: float = Field(default=0.45, json_schema_extra={"is_updatable": True})
    breakout_weight: float = Field(default=0.25, json_schema_extra={"is_updatable": True})
    min_signal_threshold: float = Field(default=0.22, json_schema_extra={"is_updatable": True})
    short_enabled: bool = Field(default=True, json_schema_extra={"is_updatable": True})

    # Volatility and sizing
    atr_length: int = Field(default=14, json_schema_extra={"is_updatable": True})
    natr_pause_threshold: float = Field(default=4.5, json_schema_extra={"is_updatable": True})
    target_annual_vol: float = Field(default=0.30, json_schema_extra={"is_updatable": True})
    min_position_scalar: float = Field(default=0.35, json_schema_extra={"is_updatable": True})
    max_position_scalar: float = Field(default=2.0, json_schema_extra={"is_updatable": True})
    signal_power: float = Field(default=1.15, json_schema_extra={"is_updatable": True})

    # Asymmetric risk controls
    atr_sl_mult_long: float = Field(default=1.9, json_schema_extra={"is_updatable": True})
    atr_tp_mult_long: float = Field(default=2.9, json_schema_extra={"is_updatable": True})
    atr_sl_mult_short: float = Field(default=1.6, json_schema_extra={"is_updatable": True})
    atr_tp_mult_short: float = Field(default=2.4, json_schema_extra={"is_updatable": True})
    trailing_enabled: bool = Field(default=True, json_schema_extra={"is_updatable": True})
    trailing_activation_atr_mult: float = Field(default=1.2, json_schema_extra={"is_updatable": True})
    trailing_delta_atr_mult: float = Field(default=0.45, json_schema_extra={"is_updatable": True})
    max_time_limit_seconds: int = Field(default=86400, json_schema_extra={"is_updatable": True})

    # Explicit cost gate
    taker_fee_bps: float = Field(default=6.0, json_schema_extra={"is_updatable": True})
    slippage_bps: float = Field(default=4.0, json_schema_extra={"is_updatable": True})
    funding_bps_per_day: float = Field(default=2.0, json_schema_extra={"is_updatable": True})
    expected_holding_hours: float = Field(default=12.0, json_schema_extra={"is_updatable": True})
    edge_capture_ratio: float = Field(default=0.60, json_schema_extra={"is_updatable": True})
    min_expected_edge_bps: float = Field(default=8.0, json_schema_extra={"is_updatable": True})

    @field_validator("candles_connector", mode="before")
    @classmethod
    def _set_candles_conn(cls, v, info: ValidationInfo):
        return info.data.get("connector_name") if not v else v

    @field_validator("candles_trading_pair", mode="before")
    @classmethod
    def _set_candles_pair(cls, v, info: ValidationInfo):
        return info.data.get("trading_pair") if not v else v


class SystematicAlphaV2Controller(DirectionalTradingControllerBase):
    def __init__(self, config: SystematicAlphaV2Config, *args, **kwargs):
        self.config = config

        slow_lookback = max(
            config.ema_slow,
            config.breakout_lookback,
            config.adx_length,
            config.atr_length,
        ) + 30
        fast_lookback = max(
            config.rsi_length,
            config.bb_length,
            config.atr_length,
        ) + 40

        if len(self.config.candles_config) == 0:
            self.config.candles_config = [
                CandlesConfig(
                    connector=config.candles_connector,
                    trading_pair=config.candles_trading_pair,
                    interval=config.interval_slow,
                    max_records=slow_lookback,
                ),
                CandlesConfig(
                    connector=config.candles_connector,
                    trading_pair=config.candles_trading_pair,
                    interval=config.interval_fast,
                    max_records=fast_lookback,
                ),
            ]

        self._slow_lookback = slow_lookback
        self._fast_lookback = fast_lookback
        super().__init__(config, *args, **kwargs)

    async def update_processed_data(self):
        df_slow = self.market_data_provider.get_candles_df(
            connector_name=self.config.candles_connector,
            trading_pair=self.config.candles_trading_pair,
            interval=self.config.interval_slow,
            max_records=self._slow_lookback,
        )
        df_fast = self.market_data_provider.get_candles_df(
            connector_name=self.config.candles_connector,
            trading_pair=self.config.candles_trading_pair,
            interval=self.config.interval_fast,
            max_records=self._fast_lookback,
        )

        if df_slow is None or df_slow.empty or len(df_slow) < self.config.ema_slow + 2:
            self.processed_data = {"signal": 0.0, "signal_type": "warmup", "meta": "Waiting for slow candles"}
            return

        close_s = df_slow["close"].astype(float)
        high_s = df_slow["high"].astype(float)
        low_s = df_slow["low"].astype(float)
        price = float(close_s.iloc[-1])

        atr_price = self._last(ta.atr(high_s, low_s, close_s, length=self.config.atr_length), price * 0.01)
        atr_pct = atr_price / price if price > 0 else 0.01
        adx_val = self._adx_value(high_s, low_s, close_s)
        is_trending = adx_val > self.config.adx_trend_threshold

        ema_f = self._last(ta.ema(close_s, length=self.config.ema_fast), price)
        ema_l = self._last(ta.ema(close_s, length=self.config.ema_slow), price)
        ema_delta = (ema_f - ema_l) / price if price > 0 else 0.0
        trend_factor = max(-1.0, min(1.0, ema_delta * 40.0))

        n_high, n_low = self._n_extremes(close_s)
        breakout_factor = self._breakout_factor(price, n_high, n_low)

        rsi_val = 50.0
        bb_pctb = 0.5
        natr_fast_pct = atr_pct * 100.0
        if df_fast is not None and not df_fast.empty and len(df_fast) >= self.config.bb_length + 2:
            close_f = df_fast["close"].astype(float)
            high_f = df_fast["high"].astype(float)
            low_f = df_fast["low"].astype(float)
            rsi_val = self._last(ta.rsi(close_f, length=self.config.rsi_length), 50.0)
            bb_pctb = self._bb_pctb(close_f)
            natr_s = ta.natr(high_f, low_f, close_f, length=self.config.atr_length)
            if natr_s is not None and not natr_s.empty:
                natr_fast_pct = float(natr_s.iloc[-1])

        if self.config.natr_pause_threshold > 0 and natr_fast_pct > self.config.natr_pause_threshold:
            self.processed_data = {
                "signal": 0.0,
                "signal_type": "paused",
                "meta": f"Volatility pause NATR={natr_fast_pct:.2f}%",
                "current_price": price,
                "regime": "trending" if is_trending else "ranging",
                "adx": adx_val,
                "natr_fast_pct": natr_fast_pct,
            }
            return

        # Mean-reversion score: positive when oversold/lower band.
        rev_rsi = -(rsi_val - 50.0) / 50.0
        rev_bb = -(bb_pctb - 0.5) * 2.0
        reversion_factor = 0.55 * rev_rsi + 0.45 * rev_bb

        if is_trending:
            composite = (
                self.config.trend_weight * trend_factor +
                self.config.breakout_weight * breakout_factor +
                0.15 * reversion_factor
            )
        else:
            composite = (
                self.config.reversion_weight * reversion_factor +
                0.20 * trend_factor +
                0.10 * breakout_factor
            )

        # Mild seasonality bias, kept small to avoid overfit.
        hour_utc = self._current_hour_utc()
        if hour_utc in (21, 22):
            composite *= 1.05
        elif hour_utc in (3, 4):
            composite *= 0.90

        signal = max(-1.0, min(1.0, composite))
        signal = math.copysign(abs(signal) ** self.config.signal_power, signal)
        if not self.config.short_enabled and signal < 0:
            signal = 0.0
        if abs(signal) < self.config.min_signal_threshold:
            signal = 0.0

        cost_bps = self._estimated_cost_bps()
        expected_edge_bps = abs(signal) * atr_pct * 10000.0 * self.config.edge_capture_ratio - cost_bps
        if expected_edge_bps < self.config.min_expected_edge_bps:
            signal = 0.0

        vol_scalar = self._vol_scalar(atr_pct)

        sl_long = max(0.005, min(0.12, self.config.atr_sl_mult_long * atr_pct))
        tp_long = max(0.008, min(0.20, self.config.atr_tp_mult_long * atr_pct))
        sl_short = max(0.005, min(0.12, self.config.atr_sl_mult_short * atr_pct))
        tp_short = max(0.008, min(0.20, self.config.atr_tp_mult_short * atr_pct))
        trail_activation = max(0.004, self.config.trailing_activation_atr_mult * atr_pct)
        trail_delta = max(0.002, self.config.trailing_delta_atr_mult * atr_pct)

        signal_type = "flat"
        if signal > 0:
            signal_type = "long_trend" if is_trending else "long_reversion"
        elif signal < 0:
            signal_type = "short_trend" if is_trending else "short_reversion"

        self.processed_data = {
            "signal": signal,
            "signal_type": signal_type,
            "meta": "cost-gated directional composite",
            "current_price": price,
            "regime": "trending" if is_trending else "ranging",
            "adx": adx_val,
            "atr_pct": atr_pct * 100,
            "natr_fast_pct": natr_fast_pct,
            "rsi": rsi_val,
            "bb_pctb": bb_pctb,
            "trend_factor": trend_factor,
            "breakout_factor": breakout_factor,
            "reversion_factor": reversion_factor,
            "expected_edge_bps": expected_edge_bps,
            "cost_bps": cost_bps,
            "vol_scalar": vol_scalar,
            "sl_long": sl_long,
            "tp_long": tp_long,
            "sl_short": sl_short,
            "tp_short": tp_short,
            "trail_activation": trail_activation,
            "trail_delta": trail_delta,
        }

    def get_executor_config(self, level_id: str, price: Decimal, amount: Decimal):
        signal = float(self.processed_data.get("signal", 0.0))
        side = TradeType.BUY if signal >= 0 else TradeType.SELL
        signal_type = self.processed_data.get("signal_type", "flat")

        sl = self.processed_data.get("sl_long", 0.015) if signal >= 0 else self.processed_data.get("sl_short", 0.015)
        tp = self.processed_data.get("tp_long", 0.025) if signal >= 0 else self.processed_data.get("tp_short", 0.02)

        trailing = None
        if self.config.trailing_enabled and signal_type in ("long_trend", "short_trend"):
            trailing = TrailingStop(
                activation_price=Decimal(str(self.processed_data.get("trail_activation", 0.01))),
                trailing_delta=Decimal(str(self.processed_data.get("trail_delta", 0.004))),
            )

        tb = TripleBarrierConfig(
            stop_loss=Decimal(str(sl)),
            take_profit=Decimal(str(tp)),
            time_limit=self.config.max_time_limit_seconds,
            trailing_stop=trailing,
            open_order_type=OrderType.MARKET,
            take_profit_order_type=OrderType.LIMIT,
            stop_loss_order_type=OrderType.MARKET,
        )

        vol_scalar = float(self.processed_data.get("vol_scalar", 1.0))
        adj_amount = Decimal(str(float(amount) * max(0.0, min(2.5, vol_scalar)) * min(abs(signal), 1.0)))
        adj_amount = max(adj_amount, Decimal("0"))

        return PositionExecutorConfig(
            timestamp=self.market_data_provider.time(),
            level_id=level_id,
            connector_name=self.config.connector_name,
            trading_pair=self.config.trading_pair,
            entry_price=price,
            amount=adj_amount,
            triple_barrier_config=tb,
            leverage=self.config.leverage,
            side=side,
        )

    def to_format_status(self) -> List[str]:
        d = self.processed_data
        lines = [
            "Systematic Alpha V2",
            f"Signal: {d.get('signal', 0):+.3f} ({d.get('signal_type', 'flat')})",
            f"Regime: {d.get('regime', '?')} ADX={d.get('adx', 0):.1f}",
            f"RSI={d.get('rsi', 50):.1f} BB%B={d.get('bb_pctb', 0.5):.2f}",
            f"Edge={d.get('expected_edge_bps', 0):.2f} bps Cost={d.get('cost_bps', 0):.2f} bps",
            f"ATR={d.get('atr_pct', 0):.2f}% NATR_fast={d.get('natr_fast_pct', 0):.2f}%",
            f"Size scalar={d.get('vol_scalar', 1):.2f}",
        ]
        return lines

    def get_custom_info(self) -> dict:
        keys = [
            "signal", "signal_type", "regime", "adx", "rsi",
            "trend_factor", "breakout_factor", "reversion_factor",
            "expected_edge_bps", "cost_bps", "vol_scalar",
        ]
        return {k: self.processed_data.get(k) for k in keys}

    def _n_extremes(self, close: pd.Series) -> Tuple[float, float]:
        window = close.tail(self.config.breakout_lookback).astype(float)
        return float(window.max()), float(window.min())

    def _breakout_factor(self, price: float, n_high: float, n_low: float) -> float:
        rng = max(1e-12, n_high - n_low)
        pct = (price - n_low) / rng
        if pct > 0.92:
            return min(1.0, (pct - 0.92) / 0.08 + 0.2)
        if pct < 0.08:
            return max(-1.0, -((0.08 - pct) / 0.08 + 0.2))
        return (pct - 0.5) * 0.4

    def _estimated_cost_bps(self) -> float:
        roundtrip_taker = self.config.taker_fee_bps * 2.0
        slippage = self.config.slippage_bps * 2.0
        funding = self.config.funding_bps_per_day * max(0.0, self.config.expected_holding_hours) / 24.0
        return roundtrip_taker + slippage + funding

    def _vol_scalar(self, atr_pct: float) -> float:
        annual_vol = max(0.01, atr_pct * math.sqrt(365 * 24))
        scalar = self.config.target_annual_vol / annual_vol
        return max(self.config.min_position_scalar, min(self.config.max_position_scalar, scalar))

    def _current_hour_utc(self) -> int:
        try:
            return datetime.datetime.utcfromtimestamp(self.market_data_provider.time()).hour
        except Exception:
            return datetime.datetime.utcnow().hour

    def _last(self, series: Optional[pd.Series], fallback: float) -> float:
        if series is not None and not series.empty and pd.notna(series.iloc[-1]):
            return float(series.iloc[-1])
        return fallback

    def _adx_value(self, high: pd.Series, low: pd.Series, close: pd.Series) -> float:
        adx_df = ta.adx(high, low, close, length=self.config.adx_length)
        if adx_df is not None and not adx_df.empty:
            cols = [c for c in adx_df.columns if c.startswith("ADX")]
            if cols and pd.notna(adx_df[cols[0]].iloc[-1]):
                return float(adx_df[cols[0]].iloc[-1])
        return 20.0

    def _bb_pctb(self, close: pd.Series) -> float:
        bb = ta.bbands(close, length=self.config.bb_length, std=self.config.bb_std)
        if bb is not None and not bb.empty:
            cols = [c for c in bb.columns if c.startswith("BBP")]
            if cols and pd.notna(bb[cols[0]].iloc[-1]):
                return float(bb[cols[0]].iloc[-1])
        return 0.5
