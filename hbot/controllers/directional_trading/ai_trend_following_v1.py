from __future__ import annotations

import datetime
import logging
import math
import os
import pickle
from decimal import Decimal
from typing import Any, Dict, List, Optional

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


class AITrendFollowingV1Config(DirectionalTradingControllerConfigBase):
    controller_name: str = "ai_trend_following_v1"

    candles_connector: Optional[str] = Field(default=None, json_schema_extra={"is_updatable": True})
    candles_trading_pair: Optional[str] = Field(default=None, json_schema_extra={"is_updatable": True})
    interval_entry: str = Field(default="1h", json_schema_extra={"is_updatable": True})
    interval_filter: str = Field(default="4h", json_schema_extra={"is_updatable": True})
    interval_daily: str = Field(default="1d", json_schema_extra={"is_updatable": True})

    ema_short: int = Field(default=50, json_schema_extra={"is_updatable": True})
    ema_long: int = Field(default=200, json_schema_extra={"is_updatable": True})
    macd_fast: int = Field(default=12, json_schema_extra={"is_updatable": True})
    macd_slow: int = Field(default=26, json_schema_extra={"is_updatable": True})
    macd_signal: int = Field(default=9, json_schema_extra={"is_updatable": True})
    adx_length: int = Field(default=14, json_schema_extra={"is_updatable": True})
    adx_threshold: float = Field(default=25.0, json_schema_extra={"is_updatable": True})
    atr_length: int = Field(default=14, json_schema_extra={"is_updatable": True})
    supertrend_length: int = Field(default=10, json_schema_extra={"is_updatable": True})
    supertrend_mult: float = Field(default=3.0, json_schema_extra={"is_updatable": True})
    volume_osc_fast: int = Field(default=12, json_schema_extra={"is_updatable": True})
    volume_osc_slow: int = Field(default=26, json_schema_extra={"is_updatable": True})
    volume_spike_mult: float = Field(default=1.2, json_schema_extra={"is_updatable": True})
    mesa_fast: int = Field(default=0, json_schema_extra={"is_updatable": True})
    mesa_slow: int = Field(default=0, json_schema_extra={"is_updatable": True})

    ai_model_path: str = Field(
        default="/home/hummingbot/data/models/ai_trend_following_v1/lstm_trend.pt",
        json_schema_extra={"is_updatable": True},
    )
    ai_prob_threshold: float = Field(default=0.70, json_schema_extra={"is_updatable": True})
    ai_confidence_weight: float = Field(default=0.65, json_schema_extra={"is_updatable": True})

    risk_model_path: str = Field(
        default="/home/hummingbot/data/models/ai_trend_following_v1/rf_position_sizer.pkl",
        json_schema_extra={"is_updatable": True},
    )
    min_size_scalar: float = Field(default=0.50, json_schema_extra={"is_updatable": True})
    max_size_scalar: float = Field(default=1.40, json_schema_extra={"is_updatable": True})
    max_portfolio_exposure_pct: float = Field(default=0.10, json_schema_extra={"is_updatable": True})
    max_drawdown_pause_pct: float = Field(default=0.15, json_schema_extra={"is_updatable": True})
    liquidity_min_ratio: float = Field(default=1.0, json_schema_extra={"is_updatable": True})

    atr_sl_mult: float = Field(default=1.5, json_schema_extra={"is_updatable": True})
    atr_tp_mult: float = Field(default=2.5, json_schema_extra={"is_updatable": True})
    atr_trailing_mult: float = Field(default=2.2, json_schema_extra={"is_updatable": True})
    trailing_delta_mult: float = Field(default=0.6, json_schema_extra={"is_updatable": True})
    partial_take_profit_rr: float = Field(default=2.0, json_schema_extra={"is_updatable": True})
    short_enabled: bool = Field(default=True, json_schema_extra={"is_updatable": True})
    pyramiding_levels: int = Field(default=3, json_schema_extra={"is_updatable": True})
    max_time_limit_seconds: int = Field(default=86400, json_schema_extra={"is_updatable": True})

    taker_fee_bps: float = Field(default=10.0, json_schema_extra={"is_updatable": True})
    slippage_bps: float = Field(default=5.0, json_schema_extra={"is_updatable": True})
    funding_bps_per_day: float = Field(default=4.0, json_schema_extra={"is_updatable": True})
    expected_holding_hours: float = Field(default=24.0, json_schema_extra={"is_updatable": True})
    min_expected_edge_bps: float = Field(default=10.0, json_schema_extra={"is_updatable": True})

    @field_validator("candles_connector", mode="before")
    @classmethod
    def _set_candles_connector(cls, v, info: ValidationInfo):
        return info.data.get("connector_name") if not v else v

    @field_validator("candles_trading_pair", mode="before")
    @classmethod
    def _set_candles_pair(cls, v, info: ValidationInfo):
        return info.data.get("trading_pair") if not v else v


class AITrendFollowingV1Controller(DirectionalTradingControllerBase):
    def __init__(self, config: AITrendFollowingV1Config, *args, **kwargs):
        self.config = config
        self._torch_model = None
        self._torch_module = None
        self._risk_model = None
        self._load_models()

        entry_lookback = max(
            config.ema_long,
            config.macd_slow + config.macd_signal,
            config.adx_length,
            config.atr_length,
            config.volume_osc_slow,
            config.supertrend_length,
        ) + 80
        filter_lookback = max(config.ema_long, config.adx_length, config.atr_length) + 40
        daily_lookback = max(config.ema_long, config.adx_length) + 40

        if len(self.config.candles_config) == 0:
            self.config.candles_config = [
                CandlesConfig(
                    connector=config.candles_connector,
                    trading_pair=config.candles_trading_pair,
                    interval=config.interval_entry,
                    max_records=entry_lookback,
                ),
                CandlesConfig(
                    connector=config.candles_connector,
                    trading_pair=config.candles_trading_pair,
                    interval=config.interval_filter,
                    max_records=filter_lookback,
                ),
                CandlesConfig(
                    connector=config.candles_connector,
                    trading_pair=config.candles_trading_pair,
                    interval=config.interval_daily,
                    max_records=daily_lookback,
                ),
            ]

        self._entry_lookback = entry_lookback
        self._filter_lookback = filter_lookback
        self._daily_lookback = daily_lookback
        super().__init__(config, *args, **kwargs)

    async def update_processed_data(self):
        df_entry = self.market_data_provider.get_candles_df(
            connector_name=self.config.candles_connector,
            trading_pair=self.config.candles_trading_pair,
            interval=self.config.interval_entry,
            max_records=self._entry_lookback,
        )
        df_filter = self.market_data_provider.get_candles_df(
            connector_name=self.config.candles_connector,
            trading_pair=self.config.candles_trading_pair,
            interval=self.config.interval_filter,
            max_records=self._filter_lookback,
        )
        df_daily = self.market_data_provider.get_candles_df(
            connector_name=self.config.candles_connector,
            trading_pair=self.config.candles_trading_pair,
            interval=self.config.interval_daily,
            max_records=self._daily_lookback,
        )

        if df_entry is None or df_entry.empty or len(df_entry) < self.config.ema_long + 5:
            self.processed_data = {"signal": 0.0, "signal_type": "warmup", "meta": "Waiting for 1h candles"}
            return

        close = df_entry["close"].astype(float)
        high = df_entry["high"].astype(float)
        low = df_entry["low"].astype(float)
        volume = df_entry["volume"].astype(float) if "volume" in df_entry.columns else pd.Series(dtype=float)
        price = float(close.iloc[-1])

        ema_s = self._last(ta.ema(close, length=self.config.ema_short), price)
        ema_l = self._last(ta.ema(close, length=self.config.ema_long), price)
        adx = self._adx_value(high, low, close)
        atr = self._last(ta.atr(high, low, close, length=self.config.atr_length), max(1e-12, price * 0.01))
        atr_pct = atr / max(1e-12, price)

        macd_line, macd_sig, macd_hist = self._macd_values(close)
        supertrend_dir = self._supertrend_direction(high, low, close)
        mesa_delta = self._mesa_delta(close)

        vol_osc = self._volume_oscillator(volume)
        vol_avg = float(volume.tail(self.config.volume_osc_slow).mean()) if not volume.empty else 0.0
        vol_cur = float(volume.iloc[-1]) if not volume.empty else 0.0
        liquidity_ratio = vol_cur / max(1e-12, vol_avg)

        filter_long_bias, filter_short_bias = self._mtf_filter_bias(df_filter, df_daily)
        drawdown_proxy = self._drawdown_proxy(close)
        vol_regime = self._realized_vol(close)

        feature_vector = [
            (ema_s - ema_l) / max(1e-12, price),
            macd_line - macd_sig,
            adx / 100.0,
            atr_pct,
            vol_osc,
            mesa_delta,
            filter_long_bias,
            filter_short_bias,
        ]
        prob_up = self._predict_up_probability(feature_vector)
        prob_down = 1.0 - prob_up

        long_rules = [
            ema_s > ema_l,
            adx > self.config.adx_threshold,
            macd_line > macd_sig,
            supertrend_dir > 0,
            vol_osc > 0,
            liquidity_ratio >= self.config.liquidity_min_ratio,
            filter_long_bias > 0,
            prob_up >= self.config.ai_prob_threshold,
        ]
        short_rules = [
            self.config.short_enabled,
            ema_s < ema_l,
            adx > self.config.adx_threshold,
            macd_line < macd_sig,
            supertrend_dir < 0,
            vol_osc < 0,
            liquidity_ratio >= self.config.liquidity_min_ratio,
            filter_short_bias > 0,
            prob_down >= self.config.ai_prob_threshold,
        ]

        if drawdown_proxy >= self.config.max_drawdown_pause_pct:
            self.processed_data = {
                "signal": 0.0,
                "signal_type": "risk_pause",
                "meta": f"Drawdown proxy {drawdown_proxy:.2%} >= threshold",
                "current_price": price,
                "ai_prob_up": prob_up,
                "drawdown_proxy": drawdown_proxy,
            }
            return

        long_score = sum(1 for r in long_rules if r) / float(len(long_rules))
        short_score = sum(1 for r in short_rules if r) / float(len(short_rules))
        ai_confidence = max(prob_up, prob_down)
        confidence = (1.0 - self.config.ai_confidence_weight) * max(long_score, short_score)
        confidence += self.config.ai_confidence_weight * ai_confidence

        signal = 0.0
        signal_type = "flat"
        if all(long_rules):
            signal = min(1.0, confidence)
            signal_type = "long_ai_trend"
        elif all(short_rules):
            signal = -min(1.0, confidence)
            signal_type = "short_ai_trend"

        cost_bps = self._estimated_cost_bps()
        expected_edge_bps = max(prob_up, prob_down) * atr_pct * 10000.0 * 2.0 - cost_bps
        if signal != 0.0 and expected_edge_bps < self.config.min_expected_edge_bps:
            signal = 0.0
            signal_type = "flat_cost_gate"

        stop_loss = max(0.004, min(0.12, self.config.atr_sl_mult * atr_pct))
        take_profit = max(0.008, min(0.25, self.config.atr_tp_mult * atr_pct))
        trail_activation = max(0.005, min(0.30, self.config.atr_trailing_mult * atr_pct))
        trail_delta = max(0.002, min(0.20, self.config.trailing_delta_mult * atr_pct))

        size_scalar = self._predict_size_scalar(
            atr_pct=atr_pct,
            realized_vol=vol_regime,
            drawdown_proxy=drawdown_proxy,
            ai_confidence=ai_confidence,
            long_score=long_score,
            short_score=short_score,
        )

        self.processed_data = {
            "signal": signal,
            "signal_type": signal_type,
            "meta": "ai-gated trend following",
            "current_price": price,
            "ema_short": ema_s,
            "ema_long": ema_l,
            "macd_line": macd_line,
            "macd_signal": macd_sig,
            "macd_hist": macd_hist,
            "adx": adx,
            "atr_pct": atr_pct * 100,
            "supertrend_dir": supertrend_dir,
            "mesa_delta": mesa_delta,
            "volume_osc": vol_osc,
            "liquidity_ratio": liquidity_ratio,
            "filter_long_bias": filter_long_bias,
            "filter_short_bias": filter_short_bias,
            "ai_prob_up": prob_up,
            "ai_prob_down": prob_down,
            "expected_edge_bps": expected_edge_bps,
            "cost_bps": cost_bps,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "trail_activation": trail_activation,
            "trail_delta": trail_delta,
            "size_scalar": size_scalar,
            "drawdown_proxy": drawdown_proxy,
            "realized_vol": vol_regime,
            "pyramiding_levels": self.config.pyramiding_levels,
            "partial_take_profit_rr": self.config.partial_take_profit_rr,
            "timestamp_utc": datetime.datetime.utcnow().isoformat(),
        }

    def get_executor_config(self, level_id: str, price: Decimal, amount: Decimal):
        signal = float(self.processed_data.get("signal", 0.0))
        side = TradeType.BUY if signal >= 0 else TradeType.SELL

        trailing = TrailingStop(
            activation_price=Decimal(str(self.processed_data.get("trail_activation", 0.01))),
            trailing_delta=Decimal(str(self.processed_data.get("trail_delta", 0.005))),
        )
        tb = TripleBarrierConfig(
            stop_loss=Decimal(str(self.processed_data.get("stop_loss", 0.015))),
            take_profit=Decimal(str(self.processed_data.get("take_profit", 0.03))),
            time_limit=self.config.max_time_limit_seconds,
            trailing_stop=trailing,
            open_order_type=OrderType.MARKET,
            take_profit_order_type=OrderType.LIMIT,
            stop_loss_order_type=OrderType.MARKET,
        )

        signal_mag = min(1.0, abs(signal))
        size_scalar = float(self.processed_data.get("size_scalar", 1.0))
        exposure_scalar = min(1.0, max(0.1, self.config.max_portfolio_exposure_pct * 10.0))
        adj_amount = Decimal(str(float(amount) * signal_mag * size_scalar * exposure_scalar))
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
        return [
            "AI Trend Following V1",
            f"Signal: {d.get('signal', 0):+.3f} ({d.get('signal_type', 'flat')})",
            f"AI P(up/down): {d.get('ai_prob_up', 0):.2f}/{d.get('ai_prob_down', 0):.2f}",
            f"EMA {self.config.ema_short}/{self.config.ema_long}: {d.get('ema_short', 0):.2f}/{d.get('ema_long', 0):.2f}",
            f"MACD: {d.get('macd_line', 0):.5f} vs signal {d.get('macd_signal', 0):.5f}",
            f"ADX={d.get('adx', 0):.1f} ATR={d.get('atr_pct', 0):.2f}% VolOsc={d.get('volume_osc', 0):+.3f}",
            f"Edge={d.get('expected_edge_bps', 0):.2f}bps Cost={d.get('cost_bps', 0):.2f}bps",
            f"Size={d.get('size_scalar', 1):.2f} DrawdownProxy={d.get('drawdown_proxy', 0):.2%}",
        ]

    def get_custom_info(self) -> dict:
        keys = [
            "signal",
            "signal_type",
            "ai_prob_up",
            "ai_prob_down",
            "expected_edge_bps",
            "cost_bps",
            "size_scalar",
            "drawdown_proxy",
            "realized_vol",
            "pyramiding_levels",
            "partial_take_profit_rr",
        ]
        return {k: self.processed_data.get(k) for k in keys}

    def _load_models(self) -> None:
        try:
            import torch

            self._torch_module = torch
            if self.config.ai_model_path and os.path.isfile(self.config.ai_model_path):
                self._torch_model = torch.jit.load(self.config.ai_model_path)
                self._torch_model.eval()
        except Exception as e:
            logger.debug("Torch model not loaded: %s", e)
            self._torch_model = None
            self._torch_module = None

        try:
            if self.config.risk_model_path and os.path.isfile(self.config.risk_model_path):
                with open(self.config.risk_model_path, "rb") as f:
                    self._risk_model = pickle.load(f)
        except Exception as e:
            logger.debug("Risk model not loaded: %s", e)
            self._risk_model = None

    def _predict_up_probability(self, features: List[float]) -> float:
        if self._torch_model is not None and self._torch_module is not None:
            try:
                tensor = self._torch_module.tensor(features, dtype=self._torch_module.float32).reshape(1, 1, len(features))
                with self._torch_module.no_grad():
                    out = self._torch_model(tensor)
                    if isinstance(out, tuple):
                        out = out[0]
                    score = float(self._torch_module.sigmoid(out).reshape(-1)[0].item())
                return max(0.0, min(1.0, score))
            except Exception as e:
                logger.debug("Torch inference fallback: %s", e)

        # Fallback logistic map from deterministic features.
        x = 0.0
        for idx, v in enumerate(features):
            weight = 0.6 - 0.05 * idx
            x += weight * float(v)
        return 1.0 / (1.0 + math.exp(-max(-8.0, min(8.0, x * 4.0))))

    def _predict_size_scalar(
        self,
        atr_pct: float,
        realized_vol: float,
        drawdown_proxy: float,
        ai_confidence: float,
        long_score: float,
        short_score: float,
    ) -> float:
        features = [[
            float(atr_pct),
            float(realized_vol),
            float(drawdown_proxy),
            float(ai_confidence),
            float(max(long_score, short_score)),
        ]]
        if self._risk_model is not None:
            try:
                pred = float(self._risk_model.predict(features)[0])
                return max(self.config.min_size_scalar, min(self.config.max_size_scalar, pred))
            except Exception as e:
                logger.debug("Risk model fallback: %s", e)

        # Heuristic: reduce size in stress, increase size when confidence is high.
        stress_penalty = 1.0 - min(0.8, drawdown_proxy * 2.5 + max(0.0, realized_vol - 0.04) * 6.0)
        confidence_boost = 0.7 + 0.6 * ai_confidence
        raw = stress_penalty * confidence_boost
        return max(self.config.min_size_scalar, min(self.config.max_size_scalar, raw))

    def _mtf_filter_bias(self, df_filter: Optional[pd.DataFrame], df_daily: Optional[pd.DataFrame]) -> tuple[float, float]:
        long_bias = 0.0
        short_bias = 0.0

        if df_filter is not None and not df_filter.empty and len(df_filter) >= self.config.ema_long + 5:
            cf = df_filter["close"].astype(float)
            ema_f_short = self._last(ta.ema(cf, length=self.config.ema_short), float(cf.iloc[-1]))
            ema_f_long = self._last(ta.ema(cf, length=self.config.ema_long), float(cf.iloc[-1]))
            long_bias += 0.5 if ema_f_short > ema_f_long else 0.0
            short_bias += 0.5 if ema_f_short < ema_f_long else 0.0

        if df_daily is not None and not df_daily.empty and len(df_daily) >= self.config.ema_long + 5:
            cd = df_daily["close"].astype(float)
            ema_d_short = self._last(ta.ema(cd, length=self.config.ema_short), float(cd.iloc[-1]))
            ema_d_long = self._last(ta.ema(cd, length=self.config.ema_long), float(cd.iloc[-1]))
            long_bias += 0.5 if ema_d_short > ema_d_long else 0.0
            short_bias += 0.5 if ema_d_short < ema_d_long else 0.0

        return long_bias, short_bias

    def _macd_values(self, close: pd.Series) -> tuple[float, float, float]:
        macd = ta.macd(
            close,
            fast=self.config.macd_fast,
            slow=self.config.macd_slow,
            signal=self.config.macd_signal,
        )
        if macd is None or macd.empty:
            return 0.0, 0.0, 0.0

        macd_cols = [c for c in macd.columns if c.startswith("MACD_")]
        sig_cols = [c for c in macd.columns if c.startswith("MACDs_")]
        hist_cols = [c for c in macd.columns if c.startswith("MACDh_")]
        macd_line = float(macd[macd_cols[0]].iloc[-1]) if macd_cols else 0.0
        macd_sig = float(macd[sig_cols[0]].iloc[-1]) if sig_cols else 0.0
        macd_hist = float(macd[hist_cols[0]].iloc[-1]) if hist_cols else 0.0
        return macd_line, macd_sig, macd_hist

    def _supertrend_direction(self, high: pd.Series, low: pd.Series, close: pd.Series) -> int:
        st = ta.supertrend(high, low, close, length=self.config.supertrend_length, multiplier=self.config.supertrend_mult)
        if st is None or st.empty:
            return 0
        dir_cols = [c for c in st.columns if c.startswith("SUPERTd_")]
        if not dir_cols:
            return 0
        direction = float(st[dir_cols[0]].iloc[-1])
        return 1 if direction > 0 else (-1 if direction < 0 else 0)

    def _mesa_delta(self, close: pd.Series) -> float:
        # pandas_ta MESA can be unavailable in some builds.
        try:
            mesa = ta.mama(close)
            if mesa is None or mesa.empty:
                return 0.0
            m_cols = [c for c in mesa.columns if c.lower().startswith("mama")]
            f_cols = [c for c in mesa.columns if c.lower().startswith("fama")]
            if not m_cols or not f_cols:
                return 0.0
            m = float(mesa[m_cols[0]].iloc[-1])
            f = float(mesa[f_cols[0]].iloc[-1])
            px = max(1e-12, float(close.iloc[-1]))
            return (m - f) / px
        except Exception:
            return 0.0

    def _volume_oscillator(self, volume: pd.Series) -> float:
        if volume.empty or len(volume) < self.config.volume_osc_slow + 2:
            return 0.0
        v_fast = self._last(ta.ema(volume, length=self.config.volume_osc_fast), float(volume.iloc[-1]))
        v_slow = self._last(ta.ema(volume, length=self.config.volume_osc_slow), float(volume.iloc[-1]))
        return (v_fast - v_slow) / max(1e-12, v_slow)

    def _drawdown_proxy(self, close: pd.Series, lookback: int = 96) -> float:
        if len(close) < lookback + 2:
            return 0.0
        window = close.tail(lookback).astype(float)
        peak = float(window.max())
        current = float(window.iloc[-1])
        return max(0.0, (peak - current) / max(1e-12, peak))

    def _realized_vol(self, close: pd.Series, lookback: int = 96) -> float:
        if len(close) < lookback + 2:
            return 0.0
        rets = close.astype(float).pct_change().dropna().tail(lookback)
        if rets.empty:
            return 0.0
        return float(rets.std() * math.sqrt(24 * 365))

    def _adx_value(self, high: pd.Series, low: pd.Series, close: pd.Series) -> float:
        adx_df = ta.adx(high, low, close, length=self.config.adx_length)
        if adx_df is not None and not adx_df.empty:
            cols = [c for c in adx_df.columns if c.startswith("ADX")]
            if cols and pd.notna(adx_df[cols[0]].iloc[-1]):
                return float(adx_df[cols[0]].iloc[-1])
        return 20.0

    def _estimated_cost_bps(self) -> float:
        roundtrip_taker = self.config.taker_fee_bps * 2.0
        slippage = self.config.slippage_bps * 2.0
        funding = self.config.funding_bps_per_day * max(0.0, self.config.expected_holding_hours) / 24.0
        return roundtrip_taker + slippage + funding

    def _last(self, series: Optional[pd.Series], fallback: float) -> float:
        if series is not None and not series.empty and pd.notna(series.iloc[-1]):
            return float(series.iloc[-1])
        return fallback
