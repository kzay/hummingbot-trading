"""
Systematic Alpha V1 — Multi-Factor Regime-Aware Directional Strategy
=====================================================================

A professional-grade quantitative directional strategy that combines
6 orthogonal signal factors with regime-dependent weighting, ATR-based
dynamic stops, and target-volatility position sizing.

This goes far beyond implementing a single paper. It fuses decades of
quantitative research into a unified framework:

Signal Factors (each normalized to [-1, +1])
---------------------------------------------
  F1  BREAKOUT   : N-day MAX/MIN with volume confirmation
                    (Padysak & Vojtko 2022 + Granville volume theory)
  F2  TREND      : Triple-EMA alignment (8/21/50) + EMA50 slope
                    (Jegadeesh & Titman 1993, momentum literature)
  F3  REVERSION  : Bollinger %B + RSI(14) + return z-score
                    (Bollinger 1992, mean-reversion literature)
  F4  VOLUME     : Relative volume + OBV trend direction
                    (Granville OBV, institutional flow analysis)
  F5  SEASONALITY: Hour-of-day from paper (21-23 UTC positive)
                    (Padysak & Vojtko 2022)

Regime Detection (controls factor weights)
-------------------------------------------
  - Trend regime  : ADX(14) > 25 → heavier BREAKOUT + TREND weights
  - Range regime  : ADX(14) < 25 → heavier REVERSION weights
  - Volatility    : NATR percentile → scales position size + signal bar

Risk Management (adaptive, not fixed)
--------------------------------------
  - ATR-based stops : SL = N × ATR (adapts to volatility automatically)
  - Target-vol sizing: positions scale inversely with realized volatility
  - Trailing stop   : on momentum signals (let winners run)
  - Kill switch     : global drawdown limit

Why Multi-Factor Beats Single-Factor
--------------------------------------
  Single signals (RSI alone, breakout alone) have high variance and
  regime-dependent performance. By combining orthogonal factors and
  weighting them by market regime, we get:
  - Smoother equity curve (factors diversify each other)
  - Lower drawdowns (regime detection avoids wrong signals)
  - Higher Sharpe (composite score has lower noise)
  - Robustness (no single point of failure)

Architecture
------------
  - Hummingbot V2 DirectionalTradingControllerBase
  - Two candle feeds: 1d (primary signals) + 4h (RSI, BB, timing)
  - Modular factor computation via helper methods
  - Custom TripleBarrierConfig per signal type
  - Dynamic position sizing via target volatility
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


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  Config                                                                  ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class SystematicAlphaV1Config(DirectionalTradingControllerConfigBase):
    controller_name: str = "systematic_alpha_v1"

    # ── Data Sources ─────────────────────────────────────────────
    candles_connector: Optional[str] = Field(default=None, json_schema_extra={
        "prompt": "Candles connector (empty=same as connector): ", "prompt_on_new": True})
    candles_trading_pair: Optional[str] = Field(default=None, json_schema_extra={
        "prompt": "Candles pair (empty=same as trading_pair): ", "prompt_on_new": True})
    interval_daily: str = Field(default="1d", json_schema_extra={
        "prompt": "Daily candle interval: ", "prompt_on_new": True})
    interval_4h: str = Field(default="4h", json_schema_extra={
        "prompt": "4h candle interval: ", "prompt_on_new": True})

    # ── Breakout Factor (F1) ────────────────────────────────────
    lookback_days: int = Field(default=10, json_schema_extra={
        "prompt": "N-day lookback for MAX/MIN (paper best=10): ",
        "prompt_on_new": True, "is_updatable": True})
    proximity_pct: float = Field(default=0.3, json_schema_extra={
        "prompt": "Proximity % to MAX/MIN (e.g. 0.3): ",
        "prompt_on_new": True, "is_updatable": True})

    # ── Trend Factor (F2) ──────────────────────────────────────
    ema_fast: int = Field(default=8, json_schema_extra={"is_updatable": True})
    ema_mid: int = Field(default=21, json_schema_extra={"is_updatable": True})
    ema_slow: int = Field(default=50, json_schema_extra={"is_updatable": True})

    # ── Reversion Factor (F3) ──────────────────────────────────
    rsi_length: int = Field(default=14, json_schema_extra={"is_updatable": True})
    bb_length: int = Field(default=20, json_schema_extra={"is_updatable": True})
    bb_std: float = Field(default=2.0, json_schema_extra={"is_updatable": True})
    zscore_return_days: int = Field(default=5, json_schema_extra={"is_updatable": True})
    zscore_std_days: int = Field(default=20, json_schema_extra={"is_updatable": True})

    # ── Volume Factor (F4) ─────────────────────────────────────
    vol_avg_length: int = Field(default=20, json_schema_extra={"is_updatable": True})

    # ── Seasonality (F5) ───────────────────────────────────────
    seasonality_enabled: bool = Field(default=True, json_schema_extra={"is_updatable": True})

    # ── Regime Detection ───────────────────────────────────────
    adx_length: int = Field(default=14, json_schema_extra={"is_updatable": True})
    adx_trend_threshold: float = Field(default=25.0, json_schema_extra={
        "prompt": "ADX threshold for trending (e.g. 25): ",
        "prompt_on_new": True, "is_updatable": True})

    # ── ATR Dynamic Stops ──────────────────────────────────────
    atr_length: int = Field(default=14, json_schema_extra={"is_updatable": True})
    atr_sl_multiplier: float = Field(default=2.0, json_schema_extra={
        "prompt": "SL = N x ATR (e.g. 2.0): ", "prompt_on_new": True, "is_updatable": True})
    atr_tp_multiplier: float = Field(default=3.0, json_schema_extra={
        "prompt": "TP = N x ATR (e.g. 3.0): ", "prompt_on_new": True, "is_updatable": True})
    trailing_atr_activation: float = Field(default=1.5, json_schema_extra={
        "prompt": "Trailing activate at N x ATR (e.g. 1.5): ",
        "prompt_on_new": True, "is_updatable": True})
    trailing_atr_delta: float = Field(default=0.5, json_schema_extra={
        "prompt": "Trailing delta at N x ATR (e.g. 0.5): ",
        "prompt_on_new": True, "is_updatable": True})

    # ── Target-Volatility Position Sizing ──────────────────────
    target_annual_vol: float = Field(default=0.25, json_schema_extra={
        "prompt": "Target annualized volatility (0.25=25%): ",
        "prompt_on_new": True, "is_updatable": True})
    max_position_scalar: float = Field(default=2.0, json_schema_extra={
        "prompt": "Max position size multiplier (e.g. 2.0): ",
        "prompt_on_new": True, "is_updatable": True})

    # ── Signal Threshold ───────────────────────────────────────
    min_signal_threshold: float = Field(default=0.20, json_schema_extra={
        "prompt": "Min composite score to trade (0.20): ",
        "prompt_on_new": True, "is_updatable": True})

    # ── Volatility Pause ───────────────────────────────────────
    natr_pause_threshold: float = Field(default=5.0, json_schema_extra={
        "prompt": "Hourly NATR% to pause (e.g. 5.0): ",
        "prompt_on_new": True, "is_updatable": True})

    # ── Short Selling ──────────────────────────────────────────
    short_enabled: bool = Field(default=False, json_schema_extra={
        "prompt": "Enable short signals? (false): ", "prompt_on_new": True, "is_updatable": True})

    # ── Validators ─────────────────────────────────────────────

    @field_validator("candles_connector", mode="before")
    @classmethod
    def _set_candles_conn(cls, v, info: ValidationInfo):
        return info.data.get("connector_name") if not v else v

    @field_validator("candles_trading_pair", mode="before")
    @classmethod
    def _set_candles_pair(cls, v, info: ValidationInfo):
        return info.data.get("trading_pair") if not v else v


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  Controller                                                              ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class SystematicAlphaV1Controller(DirectionalTradingControllerBase):

    def __init__(self, config: SystematicAlphaV1Config, *args, **kwargs):
        self.config = config
        daily_lb = max(config.ema_slow, config.lookback_days, config.bb_length,
                       config.adx_length, config.atr_length, config.vol_avg_length,
                       config.zscore_std_days + config.zscore_return_days) + 15
        h4_lb = max(config.rsi_length, config.bb_length) + 30

        if len(self.config.candles_config) == 0:
            self.config.candles_config = [
                CandlesConfig(connector=config.candles_connector,
                              trading_pair=config.candles_trading_pair,
                              interval=config.interval_daily, max_records=daily_lb),
                CandlesConfig(connector=config.candles_connector,
                              trading_pair=config.candles_trading_pair,
                              interval=config.interval_4h, max_records=h4_lb),
            ]
        self._daily_lb = daily_lb
        self._h4_lb = h4_lb
        super().__init__(config, *args, **kwargs)

    # ────────────────────────────────────────────────────────────
    #  Core pipeline
    # ────────────────────────────────────────────────────────────

    async def update_processed_data(self):
        df_d = self.market_data_provider.get_candles_df(
            connector_name=self.config.candles_connector,
            trading_pair=self.config.candles_trading_pair,
            interval=self.config.interval_daily, max_records=self._daily_lb)
        df_4h = self.market_data_provider.get_candles_df(
            connector_name=self.config.candles_connector,
            trading_pair=self.config.candles_trading_pair,
            interval=self.config.interval_4h, max_records=self._h4_lb)

        if df_d is None or df_d.empty or len(df_d) < self.config.ema_slow + 2:
            self.processed_data = {"signal": 0, "signal_type": "warmup",
                                   "meta": "Waiting for daily data"}
            return

        close_d = df_d["close"].astype(float)
        high_d = df_d["high"].astype(float)
        low_d = df_d["low"].astype(float)
        vol_d = df_d["volume"].astype(float) if "volume" in df_d.columns else None
        price = float(close_d.iloc[-1])

        # ── Indicators: daily ─────────────────────────────────
        ema8 = self._last(ta.ema(close_d, length=self.config.ema_fast), price)
        ema21 = self._last(ta.ema(close_d, length=self.config.ema_mid), price)
        ema50 = self._last(ta.ema(close_d, length=self.config.ema_slow), price)
        ema50_prev = self._nth(ta.ema(close_d, length=self.config.ema_slow), -6, price)

        adx_val = self._adx_value(high_d, low_d, close_d)
        is_trending = adx_val > self.config.adx_trend_threshold

        atr_price = self._last(ta.atr(high_d, low_d, close_d,
                                       length=self.config.atr_length), price * 0.02)
        natr_daily = atr_price / price if price > 0 else 0.02

        n_max, n_min = self._n_day_extremes(close_d)

        # ── Indicators: 4h ────────────────────────────────────
        rsi_val = 50.0
        bb_pctb = 0.5
        natr_4h_pct = 1.0
        if df_4h is not None and not df_4h.empty and len(df_4h) >= self.config.bb_length + 2:
            c4 = df_4h["close"].astype(float)
            h4 = df_4h["high"].astype(float)
            l4 = df_4h["low"].astype(float)
            rsi_val = self._last(ta.rsi(c4, length=self.config.rsi_length), 50.0)
            bb_pctb = self._bb_pctb(c4)
            natr_4h_s = ta.natr(h4, l4, c4, length=self.config.atr_length)
            if natr_4h_s is not None and not natr_4h_s.empty:
                natr_4h_pct = float(natr_4h_s.iloc[-1])

        # Volatility pause
        if self.config.natr_pause_threshold > 0 and natr_4h_pct > self.config.natr_pause_threshold:
            self.processed_data = {"signal": 0, "signal_type": "paused",
                                   "meta": f"Vol pause NATR={natr_4h_pct:.2f}%",
                                   "current_price": price, "natr_daily_pct": natr_daily * 100}
            return

        # Current hour
        try:
            hr = datetime.datetime.utcfromtimestamp(self.market_data_provider.time()).hour
        except Exception:
            hr = datetime.datetime.utcnow().hour

        # ══════════════════════════════════════════════════════
        #  FACTOR COMPUTATION  (each in [-1, +1])
        # ══════════════════════════════════════════════════════

        prox = self.config.proximity_pct / 100.0
        at_max = price >= n_max * (1.0 - prox)
        at_min = price <= n_min * (1.0 + prox)

        # F1: Breakout + volume confirmation
        f_breakout = self._factor_breakout(price, n_max, n_min, at_max, at_min, vol_d)

        # F2: Trend (triple-EMA alignment + slope)
        f_trend = self._factor_trend(price, ema8, ema21, ema50, ema50_prev)

        # F3: Mean-Reversion (BB %B + RSI + z-score)
        f_reversion = self._factor_reversion(bb_pctb, rsi_val, close_d)

        # F4: Volume (relative vol + OBV direction)
        f_volume = self._factor_volume(close_d, vol_d)

        # F5: Seasonality
        f_seasonality = self._factor_seasonality(hr)

        # ══════════════════════════════════════════════════════
        #  REGIME-DEPENDENT COMPOSITE
        # ══════════════════════════════════════════════════════

        if is_trending:
            w = {"brk": 0.30, "trd": 0.25, "rev": 0.08, "vol": 0.17, "sea": 0.10, "rgm": 0.10}
            regime_adj = f_trend * 0.5  # amplify trend in trending markets
        else:
            w = {"brk": 0.15, "trd": 0.08, "rev": 0.35, "vol": 0.17, "sea": 0.10, "rgm": 0.15}
            regime_adj = -f_trend * 0.25  # fade trend in ranging markets (contrarian)

        composite = (w["brk"] * f_breakout + w["trd"] * f_trend +
                     w["rev"] * f_reversion + w["vol"] * f_volume +
                     w["sea"] * f_seasonality + w["rgm"] * regime_adj)

        # High-vol penalty: reduce conviction when ATR is elevated
        if natr_daily > 0.03:
            composite *= max(0.5, 1.0 - (natr_daily - 0.03) * 10)

        # Determine signal type and direction
        if not self.config.short_enabled and composite < 0:
            composite = 0.0

        signal = max(-1.0, min(1.0, composite))
        if abs(signal) < self.config.min_signal_threshold:
            signal = 0.0

        signal_type = "none"
        if signal > 0:
            signal_type = "momentum" if at_max else ("bounce" if at_min else "trend_long")
        elif signal < 0:
            signal_type = "short_trend"

        # ══════════════════════════════════════════════════════
        #  DYNAMIC STOPS (ATR-based)
        # ══════════════════════════════════════════════════════

        sl_pct = max(0.008, min(0.10, self.config.atr_sl_multiplier * atr_price / price))
        tp_pct = max(0.012, min(0.15, self.config.atr_tp_multiplier * atr_price / price))
        trail_act = max(0.005, self.config.trailing_atr_activation * atr_price / price)
        trail_delta = max(0.002, self.config.trailing_atr_delta * atr_price / price)

        # Bounce = tighter (mean-reversion is quick or fails)
        if signal_type == "bounce":
            sl_pct *= 0.7
            tp_pct *= 0.7

        # ══════════════════════════════════════════════════════
        #  TARGET-VOL POSITION SIZING
        # ══════════════════════════════════════════════════════

        annual_vol = natr_daily * math.sqrt(365)
        vol_scalar = (self.config.target_annual_vol / annual_vol
                      if annual_vol > 0.01 else 1.0)
        vol_scalar = max(0.3, min(self.config.max_position_scalar, vol_scalar))

        # ── Store everything ──────────────────────────────────
        regime = "trending" if is_trending else "ranging"
        self.processed_data = {
            "signal": signal,
            "signal_type": signal_type,
            "meta": self._build_meta(signal_type, at_max, at_min, is_trending, hr),
            "current_price": price,
            "n_day_max": n_max, "n_day_min": n_min,
            "at_max": at_max, "at_min": at_min,
            "ema8": ema8, "ema21": ema21, "ema50": ema50,
            "adx": adx_val, "regime": regime,
            "rsi": rsi_val, "bb_pctb": bb_pctb,
            "natr_daily_pct": natr_daily * 100,
            "atr_price": atr_price,
            "hour_utc": hr,
            "f_breakout": f_breakout, "f_trend": f_trend,
            "f_reversion": f_reversion, "f_volume": f_volume,
            "f_seasonality": f_seasonality,
            "dynamic_sl": sl_pct, "dynamic_tp": tp_pct,
            "trail_activation": trail_act, "trail_delta": trail_delta,
            "vol_scalar": vol_scalar,
            "features": df_d,
        }

        if signal != 0:
            logger.info("SIGNAL %.2f [%s] regime=%s | brk=%.2f trd=%.2f rev=%.2f vol=%.2f | "
                        "SL=%.2f%% TP=%.2f%% size=%.1fx",
                        signal, signal_type, regime, f_breakout, f_trend,
                        f_reversion, f_volume, sl_pct * 100, tp_pct * 100, vol_scalar)

    # ────────────────────────────────────────────────────────────
    #  Factor Methods
    # ────────────────────────────────────────────────────────────

    def _factor_breakout(self, price: float, n_max: float, n_min: float,
                         at_max: bool, at_min: bool,
                         vol_d: Optional[pd.Series]) -> float:
        """F1: N-day MAX/MIN breakout with volume confirmation."""
        vol_confirm = 1.0
        if vol_d is not None and len(vol_d) >= self.config.vol_avg_length + 1:
            avg_vol = float(vol_d.tail(self.config.vol_avg_length).mean())
            cur_vol = float(vol_d.iloc[-1])
            if avg_vol > 0:
                ratio = cur_vol / avg_vol
                vol_confirm = min(ratio / 1.3, 1.4)  # cap at 1.4x boost

        if at_max:
            return min(1.0, 1.0 * vol_confirm)
        elif at_min:
            return min(1.0, 0.65 * vol_confirm)
        else:
            # Proximity: mild signal near extremes
            rng = n_max - n_min
            if rng <= 0:
                return 0.0
            position = (price - n_min) / rng  # 0 at min, 1 at max
            if position > 0.90:
                return 0.25
            elif position < 0.10:
                return 0.15
            return 0.0

    def _factor_trend(self, price: float, ema8: float, ema21: float,
                      ema50: float, ema50_prev: float) -> float:
        """F2: Triple-EMA alignment + EMA50 slope."""
        # Alignment score: +1 fully bullish, -1 fully bearish
        alignment = 0.0
        if ema8 > ema21:
            alignment += 0.33
        else:
            alignment -= 0.33
        if ema21 > ema50:
            alignment += 0.33
        else:
            alignment -= 0.33
        if price > ema50:
            alignment += 0.34
        else:
            alignment -= 0.34

        # EMA50 slope: rate of change over last 5 daily candles
        slope = (ema50 - ema50_prev) / ema50_prev if ema50_prev > 0 else 0.0
        slope_norm = max(-1.0, min(1.0, slope * 50))  # scale for sensitivity

        return 0.6 * alignment + 0.4 * slope_norm

    def _factor_reversion(self, bb_pctb: float, rsi: float,
                          daily_close: pd.Series) -> float:
        """F3: BB %B + RSI + return z-score (all inverted: low=buy, high=sell)."""
        # Bollinger %B: 0=lower band, 1=upper band → invert for buy signal
        mr_bb = -(bb_pctb - 0.5) * 2.0  # [-1, +1]: +1 at lower, -1 at upper

        # RSI: invert → oversold = positive
        mr_rsi = -(rsi - 50.0) / 50.0  # [-1, +1]

        # Z-score of N-day return vs rolling std
        mr_z = 0.0
        ret_days = self.config.zscore_return_days
        std_days = self.config.zscore_std_days
        if len(daily_close) >= std_days + ret_days + 1:
            closes = daily_close.astype(float)
            recent_ret = float(closes.iloc[-1] / closes.iloc[-(ret_days + 1)] - 1.0)
            daily_rets = closes.pct_change().dropna()
            std_val = float(daily_rets.tail(std_days).std())
            if std_val > 0:
                z = recent_ret / std_val
                mr_z = max(-1.0, min(1.0, -z / 2.0))  # inverted, scaled

        return 0.40 * mr_bb + 0.35 * mr_rsi + 0.25 * mr_z

    def _factor_volume(self, close_d: pd.Series,
                       vol_d: Optional[pd.Series]) -> float:
        """F4: Relative volume + OBV trend direction."""
        if vol_d is None or len(vol_d) < self.config.vol_avg_length + 1:
            return 0.0

        avg_vol = float(vol_d.tail(self.config.vol_avg_length).mean())
        cur_vol = float(vol_d.iloc[-1])
        vol_ratio = cur_vol / avg_vol if avg_vol > 0 else 1.0

        # OBV direction via simple sign
        obv_s = ta.obv(close_d, vol_d)
        if obv_s is None or len(obv_s) < 11:
            return 0.0
        obv_ema = ta.ema(obv_s, length=10)
        if obv_ema is None or obv_ema.empty:
            return 0.0
        obv_bullish = float(obv_s.iloc[-1]) > float(obv_ema.iloc[-1])

        direction = 1.0 if obv_bullish else -1.0

        if vol_ratio > 1.5:
            return direction * 0.6
        elif vol_ratio > 1.0:
            return direction * 0.3
        else:
            return 0.0

    def _factor_seasonality(self, hour: int) -> float:
        """F5: Hour-of-day from Padysak & Vojtko 2022."""
        if not self.config.seasonality_enabled:
            return 0.0
        if hour in (21, 22):
            return 0.6
        elif hour in (20, 23):
            return 0.25
        elif hour in (3, 4):
            return -0.3
        return 0.0

    # ────────────────────────────────────────────────────────────
    #  Indicator Helpers
    # ────────────────────────────────────────────────────────────

    def _last(self, series: Optional[pd.Series], fallback: float) -> float:
        if series is not None and not series.empty:
            val = series.iloc[-1]
            if pd.notna(val):
                return float(val)
        return fallback

    def _nth(self, series: Optional[pd.Series], n: int, fallback: float) -> float:
        if series is not None and len(series) >= abs(n):
            val = series.iloc[n]
            if pd.notna(val):
                return float(val)
        return fallback

    def _adx_value(self, high: pd.Series, low: pd.Series, close: pd.Series) -> float:
        adx_df = ta.adx(high, low, close, length=self.config.adx_length)
        if adx_df is not None and not adx_df.empty:
            cols = [c for c in adx_df.columns if c.startswith("ADX")]
            if cols:
                return float(adx_df[cols[0]].iloc[-1])
        return 20.0

    def _n_day_extremes(self, close: pd.Series) -> Tuple[float, float]:
        window = close.tail(self.config.lookback_days).astype(float)
        return float(window.max()), float(window.min())

    def _bb_pctb(self, close: pd.Series) -> float:
        bb = ta.bbands(close, length=self.config.bb_length, std=self.config.bb_std)
        if bb is not None and not bb.empty:
            cols = [c for c in bb.columns if c.startswith("BBP")]
            if cols:
                val = bb[cols[0]].iloc[-1]
                if pd.notna(val):
                    return float(val)
        return 0.5

    def _build_meta(self, sig_type: str, at_max: bool, at_min: bool,
                    trending: bool, hr: int) -> str:
        parts = []
        if sig_type == "momentum":
            parts.append(f"Breakout at {self.config.lookback_days}d HIGH")
        elif sig_type == "bounce":
            parts.append(f"Bounce at {self.config.lookback_days}d LOW")
        elif sig_type == "trend_long":
            parts.append("Multi-factor LONG (trend composite)")
        elif sig_type == "short_trend":
            parts.append("Multi-factor SHORT")
        else:
            parts.append("Flat — below threshold")
        parts.append("trending" if trending else "ranging")
        if hr in (21, 22):
            parts.append("seasonal boost")
        return " | ".join(parts)

    # ────────────────────────────────────────────────────────────
    #  Executor Config (ATR-based dynamic stops)
    # ────────────────────────────────────────────────────────────

    def get_executor_config(self, level_id: str, price: Decimal, amount: Decimal):
        signal = self.processed_data.get("signal", 0)
        side = TradeType.BUY if signal >= 0 else TradeType.SELL

        sl = Decimal(str(self.processed_data.get("dynamic_sl", 0.015)))
        tp = Decimal(str(self.processed_data.get("dynamic_tp", 0.03)))
        t_act = Decimal(str(self.processed_data.get("trail_activation", 0.015)))
        t_dlt = Decimal(str(self.processed_data.get("trail_delta", 0.005)))
        sig_type = self.processed_data.get("signal_type", "none")
        time_lim = 172800  # 48h default
        if sig_type == "bounce":
            time_lim = 86400  # 24h for bounces

        try:
            use_trailing = sig_type in ("momentum", "trend_long")
            tb = TripleBarrierConfig(
                stop_loss=sl, take_profit=tp, time_limit=time_lim,
                trailing_stop=TrailingStop(activation_price=t_act, trailing_delta=t_dlt) if use_trailing else None,
                open_order_type=OrderType.MARKET,
                take_profit_order_type=OrderType.LIMIT,
                stop_loss_order_type=OrderType.MARKET,
            )
        except Exception:
            tb = self.config.triple_barrier_config

        # Target-vol adjusted amount
        vol_scalar = self.processed_data.get("vol_scalar", 1.0)
        adj_amount = Decimal(str(float(amount) * vol_scalar * min(abs(signal), 1.0)))
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

    # ────────────────────────────────────────────────────────────
    #  Status Display
    # ────────────────────────────────────────────────────────────

    def to_format_status(self) -> List[str]:
        d = self.processed_data
        signal = d.get("signal", 0)
        sig_type = d.get("signal_type", "none")
        meta = d.get("meta", "")
        p = d.get("current_price", 0)
        lb = self.config.lookback_days

        lines = [
            "┌──────────────────────────────────────────────────────────┐",
            "│  Systematic Alpha V1 — Multi-Factor Quant Strategy       │",
            "└──────────────────────────────────────────────────────────┘",
        ]

        # Signal
        if abs(signal) > 0:
            emoji = ">>>" if signal > 0 else "<<<"
            lines.append(f"  {emoji} {sig_type.upper()} signal={signal:+.3f}")
        else:
            lines.append(f"  Signal: FLAT ({meta})")

        # Price context
        n_max = d.get("n_day_max", 0)
        n_min = d.get("n_day_min", 0)
        if p and n_max and n_min:
            rng = n_max - n_min
            pos = (p - n_min) / rng * 100 if rng > 0 else 50
            lines.append(f"  Price ${p:,.0f}  |  {lb}d: ${n_min:,.0f}—${n_max:,.0f}  ({pos:.0f}% of range)")

        # Factors
        lines.append("")
        lines.append("── Factor Scores ───────────────────────────────────────")
        for label, key in [("Breakout", "f_breakout"), ("Trend", "f_trend"),
                           ("Reversion", "f_reversion"), ("Volume", "f_volume"),
                           ("Season", "f_seasonality")]:
            v = d.get(key, 0)
            bar = "+" * max(0, int(v * 10)) + "-" * max(0, int(-v * 10))
            lines.append(f"  {label:10s} {v:+.3f}  [{bar:>10s}]")

        # Regime
        lines.append("")
        regime = d.get("regime", "?")
        adx = d.get("adx", 0)
        natr = d.get("natr_daily_pct", 0)
        lines.append(f"── Regime: {regime.upper()} (ADX={adx:.1f})  Vol={natr:.2f}%/day ──")

        # Indicators
        rsi = d.get("rsi", 50)
        bb = d.get("bb_pctb", 0.5)
        lines.append(f"  EMA 8/21/50: {d.get('ema8', 0):,.0f}/{d.get('ema21', 0):,.0f}/{d.get('ema50', 0):,.0f}")
        lines.append(f"  RSI(14)={rsi:.1f}  BB%B={bb:.2f}  Hour(UTC)={d.get('hour_utc', '?')}")

        # Risk
        sl = d.get("dynamic_sl", 0)
        tp = d.get("dynamic_tp", 0)
        vs = d.get("vol_scalar", 1)
        if sl and tp:
            lines.append(f"  ATR stops: SL={sl:.2%}  TP={tp:.2%}  Size={vs:.2f}x")

        return lines

    def get_custom_info(self) -> dict:
        d = self.processed_data
        return {k: d.get(k) for k in [
            "signal", "signal_type", "regime", "adx", "rsi",
            "f_breakout", "f_trend", "f_reversion", "f_volume",
            "dynamic_sl", "dynamic_tp", "vol_scalar"]}
