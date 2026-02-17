"""
Systematic Directional MAX/MIN Strategy — Hummingbot V2 Controller
===================================================================

Research-backed directional trading strategy for BTC combining three
academically documented anomalies:

  Paper 1 — Padysak & Vojtko (SSRN 4081000):
    - BTC at 10-day HIGH → momentum continuation   (Ret/Vol = 1.71)
    - BTC at 10-day LOW  → mean-reversion bounce   (Ret/Vol = 0.74)
    - Combined MAX10+MIN10: 98% annual, Ret/Vol = 2.06, MDD = -37.67%
    - Shorter lookbacks (10d) outperform longer ones (20-50d)
    - Seasonality: 21:00-23:00 UTC = best hours (33% annual, 20.9% vol)

  Paper 2 — Hanicová & Vojtko (SSRN 3982120):
    - Daily rebalanced crypto portfolio: Sharpe 2.25 vs 1.28 buy-hold
    - Rebalancing premium exists when no single crypto dominates

Strategy Signals
----------------
  1. MOMENTUM (at N-day MAX):
     Price >= max(daily closes, N days) → LONG
     Rationale: BTC trends at local highs (momentum continuation)
     Exit: TP 3%, SL 1.5%, trailing 1.5%/0.5%, time 48h

  2. BOUNCE (at N-day MIN):
     Price <= min(daily closes, N days) → LONG
     Rationale: BTC bounces at local lows (mean-reversion)
     Exit: TP 2%, SL 1%, time 24h (no trailing — take profit quickly)

  3. SHORT (optional, experimental — not in original paper):
     Price breaks below N-day MIN + strong downtrend → SHORT
     Exit: TP 2.5%, SL 1.5%, time 24h

Filters
-------
  - EMA 8/21 trend alignment: boosts/penalizes signal quality
  - ADX regime detection: trending vs ranging market state
  - Seasonality overlay: boost during 21-23 UTC, reduce during 03-04 UTC
  - NATR volatility pause: extreme vol → stay flat
  - Falling knife protection: MIN + bearish trend + high ADX → reduce signal

Architecture
------------
  - Extends DirectionalTradingControllerBase (Hummingbot V2)
  - Two candle feeds: 1d (MAX/MIN + EMA/ADX) + 1h (NATR + timing)
  - Signal stored in processed_data["signal"] for V2 orchestrator
  - Custom triple barrier per signal type via get_executor_config()

Usage
-----
  1. Place at controllers/directional_trading/directional_max_min_v1.py
  2. Create controller config in conf/controllers/
  3. Reference from v2_with_controllers script config
  4. start --script v2_with_controllers.py --conf <config>.yml
"""

from __future__ import annotations

import datetime
import logging
from decimal import Decimal
from typing import List, Optional

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
# ║  Controller Config                                                       ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class DirectionalMaxMinV1Config(DirectionalTradingControllerConfigBase):
    """
    Configuration for the MAX/MIN directional trading controller.

    Inherits: connector_name, trading_pair, total_amount_quote, leverage,
    position_mode, stop_loss, take_profit, time_limit, trailing_stop,
    executor_refresh_time, cooldown_time, candles_config.
    """
    controller_name: str = "directional_max_min_v1"

    # ── Candle sources ───────────────────────────────────────────
    candles_connector: Optional[str] = Field(
        default=None,
        json_schema_extra={
            "prompt": "Candles connector (leave empty = same as connector_name): ",
            "prompt_on_new": True})
    candles_trading_pair: Optional[str] = Field(
        default=None,
        json_schema_extra={
            "prompt": "Candles trading pair (leave empty = same as trading_pair): ",
            "prompt_on_new": True})
    interval_daily: str = Field(
        default="1d",
        json_schema_extra={
            "prompt": "Daily candle interval for MAX/MIN signals (1d): ",
            "prompt_on_new": True})
    interval_intraday: str = Field(
        default="1h",
        json_schema_extra={
            "prompt": "Intraday candle interval for NATR/timing (1h): ",
            "prompt_on_new": True})

    # ── MAX/MIN Signal (from Padysak & Vojtko 2022) ─────────────
    lookback_days: int = Field(
        default=10,
        json_schema_extra={
            "prompt": "N-day lookback for MAX/MIN (paper best: 10): ",
            "prompt_on_new": True, "is_updatable": True})
    proximity_pct: float = Field(
        default=0.3,
        json_schema_extra={
            "prompt": "Proximity % to count as 'at' MAX/MIN (e.g. 0.3): ",
            "prompt_on_new": True, "is_updatable": True})
    max_signal_weight: float = Field(
        default=1.0,
        json_schema_extra={
            "prompt": "Signal weight for momentum (at MAX) entries (1.0): ",
            "prompt_on_new": True, "is_updatable": True})
    min_signal_weight: float = Field(
        default=0.8,
        json_schema_extra={
            "prompt": "Signal weight for bounce (at MIN) entries (0.8): ",
            "prompt_on_new": True, "is_updatable": True})

    # ── Trend Filter (EMA on daily) ──────────────────────────────
    ema_fast_length: int = Field(
        default=8,
        json_schema_extra={
            "prompt": "Fast EMA period on daily candles (e.g. 8): ",
            "prompt_on_new": True, "is_updatable": True})
    ema_slow_length: int = Field(
        default=21,
        json_schema_extra={
            "prompt": "Slow EMA period on daily candles (e.g. 21): ",
            "prompt_on_new": True, "is_updatable": True})

    # ── Regime Detection (ADX on daily) ──────────────────────────
    adx_length: int = Field(
        default=14,
        json_schema_extra={
            "prompt": "ADX period on daily candles (e.g. 14): ",
            "prompt_on_new": True, "is_updatable": True})
    adx_trend_threshold: float = Field(
        default=25.0,
        json_schema_extra={
            "prompt": "ADX threshold for trending regime (e.g. 25): ",
            "prompt_on_new": True, "is_updatable": True})

    # ── Seasonality (from Padysak & Vojtko 2022) ────────────────
    seasonality_enabled: bool = Field(
        default=True,
        json_schema_extra={
            "prompt": "Enable seasonality overlay? (true/false): ",
            "prompt_on_new": True, "is_updatable": True})
    seasonality_boost_factor: float = Field(
        default=0.3,
        json_schema_extra={
            "prompt": "Signal boost during 21-23 UTC (e.g. 0.3 = +30%): ",
            "prompt_on_new": True, "is_updatable": True})

    # ── Volatility (NATR on intraday) ────────────────────────────
    natr_length: int = Field(
        default=14,
        json_schema_extra={
            "prompt": "NATR period on intraday candles (e.g. 14): ",
            "prompt_on_new": True, "is_updatable": True})
    volatility_pause_threshold: float = Field(
        default=5.0,
        json_schema_extra={
            "prompt": "NATR % to pause all entries (e.g. 5.0): ",
            "prompt_on_new": True, "is_updatable": True})

    # ── Risk: Momentum Entries (at MAX) ──────────────────────────
    momentum_take_profit: float = Field(
        default=0.03,
        json_schema_extra={
            "prompt": "Momentum TP % (e.g. 0.03 = 3%): ",
            "prompt_on_new": True, "is_updatable": True})
    momentum_stop_loss: float = Field(
        default=0.015,
        json_schema_extra={
            "prompt": "Momentum SL % (e.g. 0.015 = 1.5%): ",
            "prompt_on_new": True, "is_updatable": True})
    momentum_time_limit: int = Field(
        default=172800,
        json_schema_extra={
            "prompt": "Momentum time limit in seconds (172800 = 48h): ",
            "prompt_on_new": True, "is_updatable": True})
    momentum_trailing_activation: float = Field(
        default=0.015,
        json_schema_extra={
            "prompt": "Momentum trailing stop activation (0.015 = 1.5%): ",
            "prompt_on_new": True, "is_updatable": True})
    momentum_trailing_delta: float = Field(
        default=0.005,
        json_schema_extra={
            "prompt": "Momentum trailing stop delta (0.005 = 0.5%): ",
            "prompt_on_new": True, "is_updatable": True})

    # ── Risk: Bounce Entries (at MIN) ────────────────────────────
    bounce_take_profit: float = Field(
        default=0.02,
        json_schema_extra={
            "prompt": "Bounce TP % (e.g. 0.02 = 2%): ",
            "prompt_on_new": True, "is_updatable": True})
    bounce_stop_loss: float = Field(
        default=0.01,
        json_schema_extra={
            "prompt": "Bounce SL % (e.g. 0.01 = 1%): ",
            "prompt_on_new": True, "is_updatable": True})
    bounce_time_limit: int = Field(
        default=86400,
        json_schema_extra={
            "prompt": "Bounce time limit in seconds (86400 = 24h): ",
            "prompt_on_new": True, "is_updatable": True})

    # ── Short Selling (experimental, not in paper) ───────────────
    short_enabled: bool = Field(
        default=False,
        json_schema_extra={
            "prompt": "Enable experimental short signals? (false): ",
            "prompt_on_new": True, "is_updatable": True})
    short_adx_min: float = Field(
        default=30.0,
        json_schema_extra={
            "prompt": "Min ADX for short signals (e.g. 30): ",
            "prompt_on_new": True, "is_updatable": True})

    # ── Validators ───────────────────────────────────────────────

    @field_validator("candles_connector", mode="before")
    @classmethod
    def set_candles_connector(cls, v, info: ValidationInfo):
        if v is None or v == "":
            return info.data.get("connector_name")
        return v

    @field_validator("candles_trading_pair", mode="before")
    @classmethod
    def set_candles_trading_pair(cls, v, info: ValidationInfo):
        if v is None or v == "":
            return info.data.get("trading_pair")
        return v


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  Controller Logic                                                        ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class DirectionalMaxMinV1Controller(DirectionalTradingControllerBase):
    """
    Systematic directional controller based on N-day MAX/MIN breakout
    signals with seasonality overlay and trend filtering.

    Processing pipeline (runs every update cycle):
      1. Fetch 1d candles → compute N-day MAX/MIN, EMA, ADX
      2. Fetch 1h candles → compute NATR, determine current hour
      3. Check: is current price at N-day MAX? → momentum LONG signal
      4. Check: is current price at N-day MIN? → bounce LONG signal
      5. Apply trend filter (EMA alignment, ADX regime)
      6. Apply seasonality overlay (boost 21-23 UTC, penalize 03-04 UTC)
      7. Apply volatility gate (pause above NATR threshold)
      8. Output: signal direction and magnitude for V2 orchestrator
      9. Custom triple barrier per signal type in executor config
    """

    def __init__(self, config: DirectionalMaxMinV1Config, *args, **kwargs):
        self.config = config

        daily_lookback = max(
            config.lookback_days,
            config.ema_slow_length,
            config.adx_length,
        ) + 10
        intraday_lookback = config.natr_length + 50

        if len(self.config.candles_config) == 0:
            self.config.candles_config = [
                CandlesConfig(
                    connector=config.candles_connector,
                    trading_pair=config.candles_trading_pair,
                    interval=config.interval_daily,
                    max_records=daily_lookback,
                ),
                CandlesConfig(
                    connector=config.candles_connector,
                    trading_pair=config.candles_trading_pair,
                    interval=config.interval_intraday,
                    max_records=intraday_lookback,
                ),
            ]

        self._daily_lookback = daily_lookback
        self._intraday_lookback = intraday_lookback

        super().__init__(config, *args, **kwargs)

    # ── Core: compute directional signal ──────────────────────────

    async def update_processed_data(self):
        """
        Compute the directional signal from multi-timeframe analysis.

        Signal convention (V2 standard):
          signal > 0 → LONG  (magnitude = confidence 0-1)
          signal < 0 → SHORT (magnitude = confidence 0-1)
          signal = 0 → FLAT  (no new positions)
        """

        # ── 1. Fetch daily candles ────────────────────────────────
        df_daily = self.market_data_provider.get_candles_df(
            connector_name=self.config.candles_connector,
            trading_pair=self.config.candles_trading_pair,
            interval=self.config.interval_daily,
            max_records=self._daily_lookback,
        )

        # ── 2. Fetch intraday candles ─────────────────────────────
        df_intra = self.market_data_provider.get_candles_df(
            connector_name=self.config.candles_connector,
            trading_pair=self.config.candles_trading_pair,
            interval=self.config.interval_intraday,
            max_records=self._intraday_lookback,
        )

        # ── 3. Fallback if data unavailable ───────────────────────
        if df_daily is None or df_daily.empty or len(df_daily) < self.config.lookback_days:
            self.processed_data = {
                "signal": 0, "signal_type": "warmup",
                "signal_meta": "Waiting for daily candle data",
            }
            return

        # ── 4. N-day MAX/MIN from daily closes ────────────────────
        lookback = self.config.lookback_days
        daily_closes = df_daily["close"].astype(float)

        # Use the last N completed daily candles for the lookback window
        window = daily_closes.tail(lookback)
        n_day_max = float(window.max())
        n_day_min = float(window.min())

        # Current price: use intraday if available, else last daily
        if df_intra is not None and not df_intra.empty:
            current_price = float(df_intra["close"].iloc[-1])
        else:
            current_price = float(daily_closes.iloc[-1])

        # Proximity threshold (0.3% default = within 0.3% counts as "at")
        prox = self.config.proximity_pct / 100.0

        at_max = current_price >= n_day_max * (1.0 - prox)
        at_min = current_price <= n_day_min * (1.0 + prox)

        dist_from_max_pct = (current_price - n_day_max) / n_day_max * 100.0
        dist_from_min_pct = (current_price - n_day_min) / n_day_min * 100.0

        # ── 5. Trend filter from daily EMA ────────────────────────
        ema_fast_val = current_price
        ema_slow_val = current_price
        ema_bullish = True

        if len(df_daily) >= self.config.ema_slow_length + 2:
            ema_f = ta.ema(daily_closes, length=self.config.ema_fast_length)
            ema_s = ta.ema(daily_closes, length=self.config.ema_slow_length)
            if ema_f is not None and not ema_f.empty:
                ema_fast_val = float(ema_f.iloc[-1])
            if ema_s is not None and not ema_s.empty:
                ema_slow_val = float(ema_s.iloc[-1])
            ema_bullish = ema_fast_val > ema_slow_val

        # ── 6. ADX regime from daily candles ──────────────────────
        adx_val = 20.0
        is_trending = False

        if len(df_daily) >= self.config.adx_length + 2:
            adx_df = ta.adx(
                df_daily["high"].astype(float),
                df_daily["low"].astype(float),
                daily_closes,
                length=self.config.adx_length,
            )
            if adx_df is not None and not adx_df.empty:
                adx_col = [c for c in adx_df.columns if c.startswith("ADX")]
                if adx_col:
                    adx_val = float(adx_df[adx_col[0]].iloc[-1])
            is_trending = adx_val > self.config.adx_trend_threshold

        # ── 7. NATR from intraday candles ─────────────────────────
        natr_pct = 0.0
        if df_intra is not None and not df_intra.empty and len(df_intra) >= self.config.natr_length + 2:
            natr_series = ta.natr(
                df_intra["high"].astype(float),
                df_intra["low"].astype(float),
                df_intra["close"].astype(float),
                length=self.config.natr_length,
            )
            if natr_series is not None and not natr_series.empty:
                natr_pct = float(natr_series.iloc[-1])

        # ── 8. Volatility pause ───────────────────────────────────
        if self.config.volatility_pause_threshold > 0 and natr_pct > self.config.volatility_pause_threshold:
            logger.info("VOLATILITY PAUSE: NATR=%.2f%% > %.2f%%", natr_pct, self.config.volatility_pause_threshold)
            self._store_flat("paused", "Volatility too high",
                             current_price, n_day_max, n_day_min,
                             dist_from_max_pct, dist_from_min_pct,
                             ema_fast_val, ema_slow_val, ema_bullish,
                             adx_val, is_trending, natr_pct)
            return

        # ── 9. Current UTC hour for seasonality ───────────────────
        try:
            ts = self.market_data_provider.time()
            current_hour = datetime.datetime.utcfromtimestamp(ts).hour
        except Exception:
            current_hour = datetime.datetime.utcnow().hour

        in_boost_hours = current_hour in (21, 22)      # Best hours from paper
        in_avoid_hours = current_hour in (3, 4)         # Worst hours from paper

        # ═════════════════════════════════════════════════════════
        #  SIGNAL COMPOSITION
        # ═════════════════════════════════════════════════════════

        signal = 0.0
        signal_type = "none"
        signal_meta = f"Flat: price between {lookback}d extremes"

        if at_max:
            # ── MOMENTUM: price at N-day high → expect continuation ──
            signal = self.config.max_signal_weight
            signal_type = "momentum"
            signal_meta = f"LONG momentum: price at {lookback}d HIGH"

            # Trend alignment: momentum works better with the trend
            if ema_bullish:
                signal *= 1.2
                signal_meta += " | EMA bullish (aligned)"
            else:
                signal *= 0.5
                signal_meta += " | EMA bearish (counter-trend, reduced)"

            # Trending regime boosts momentum signals
            if is_trending:
                signal *= 1.1
                signal_meta += f" | ADX={adx_val:.0f} trending"

        elif at_min:
            # ── BOUNCE: price at N-day low → expect mean-reversion ──
            signal = self.config.min_signal_weight
            signal_type = "bounce"
            signal_meta = f"LONG bounce: price at {lookback}d LOW"

            # Falling knife protection: bearish trend + high ADX = danger
            if not ema_bullish and is_trending:
                signal *= 0.25
                signal_meta += " | FALLING KNIFE warning (strong downtrend)"
            elif ema_bullish:
                signal *= 1.2
                signal_meta += " | EMA bullish (dip in uptrend)"
            else:
                signal *= 0.7
                signal_meta += " | EMA bearish (cautious bounce)"

        elif self.config.short_enabled:
            # ── SHORT (experimental): break below N-day min in downtrend ──
            below_min = current_price < n_day_min * (1.0 - prox)
            if below_min and not ema_bullish and adx_val > self.config.short_adx_min:
                signal = -0.7
                signal_type = "short_trend"
                signal_meta = f"SHORT trend: broke below {lookback}d LOW in strong downtrend"

        # ── Seasonality overlay ───────────────────────────────────
        if signal != 0.0 and self.config.seasonality_enabled:
            if in_boost_hours:
                signal *= (1.0 + self.config.seasonality_boost_factor)
                signal_meta += " | 21-23 UTC boost"
            elif in_avoid_hours:
                signal *= 0.3
                signal_meta += " | 03-04 UTC penalty"

        # ── Clamp to [-1, +1] ────────────────────────────────────
        signal = max(-1.0, min(1.0, signal))

        # Round very small signals to zero
        if abs(signal) < 0.15:
            signal = 0.0
            signal_type = "none"
            signal_meta = "Signal too weak after filters"

        # ── Store processed data ──────────────────────────────────
        self.processed_data = {
            "signal": signal,
            "signal_type": signal_type,
            "signal_meta": signal_meta,
            "current_price": current_price,
            "n_day_max": n_day_max,
            "n_day_min": n_day_min,
            "dist_from_max_pct": dist_from_max_pct,
            "dist_from_min_pct": dist_from_min_pct,
            "at_max": at_max,
            "at_min": at_min,
            "ema_fast": ema_fast_val,
            "ema_slow": ema_slow_val,
            "ema_bullish": ema_bullish,
            "adx": adx_val,
            "is_trending": is_trending,
            "natr_pct": natr_pct,
            "current_hour_utc": current_hour,
            "seasonality_active": in_boost_hours,
            "features": df_daily,
        }

        if signal != 0:
            logger.info("Signal: %.2f (%s) — %s", signal, signal_type, signal_meta)

    # ── Helper to store flat state ────────────────────────────────

    def _store_flat(self, signal_type: str, meta: str,
                    price, n_max, n_min, d_max, d_min,
                    ema_f, ema_s, ema_bull, adx, trending, natr):
        self.processed_data = {
            "signal": 0, "signal_type": signal_type, "signal_meta": meta,
            "current_price": price, "n_day_max": n_max, "n_day_min": n_min,
            "dist_from_max_pct": d_max, "dist_from_min_pct": d_min,
            "at_max": False, "at_min": False,
            "ema_fast": ema_f, "ema_slow": ema_s, "ema_bullish": ema_bull,
            "adx": adx, "is_trending": trending, "natr_pct": natr,
        }

    # ── Executor config with per-signal-type triple barrier ───────

    def get_executor_config(self, level_id: str, price: Decimal, amount: Decimal):
        """
        Create a PositionExecutor config with risk parameters customized
        per signal type: momentum gets wider TP + trailing stop,
        bounce gets tighter TP + faster time exit.
        """
        signal = self.processed_data.get("signal", 0)
        signal_type = self.processed_data.get("signal_type", "none")

        side = TradeType.BUY if signal >= 0 else TradeType.SELL

        # Build signal-specific triple barrier
        tb_config = self._build_triple_barrier(signal_type)

        return PositionExecutorConfig(
            timestamp=self.market_data_provider.time(),
            level_id=level_id,
            connector_name=self.config.connector_name,
            trading_pair=self.config.trading_pair,
            entry_price=price,
            amount=amount,
            triple_barrier_config=tb_config,
            leverage=self.config.leverage,
            side=side,
        )

    def _build_triple_barrier(self, signal_type: str) -> TripleBarrierConfig:
        """Construct a TripleBarrierConfig tuned for the current signal type."""
        try:
            if signal_type == "momentum":
                return TripleBarrierConfig(
                    stop_loss=Decimal(str(self.config.momentum_stop_loss)),
                    take_profit=Decimal(str(self.config.momentum_take_profit)),
                    time_limit=self.config.momentum_time_limit,
                    trailing_stop=TrailingStop(
                        activation_price=Decimal(str(self.config.momentum_trailing_activation)),
                        trailing_delta=Decimal(str(self.config.momentum_trailing_delta)),
                    ),
                    open_order_type=OrderType.MARKET,
                    take_profit_order_type=OrderType.LIMIT,
                    stop_loss_order_type=OrderType.MARKET,
                )
            elif signal_type == "bounce":
                return TripleBarrierConfig(
                    stop_loss=Decimal(str(self.config.bounce_stop_loss)),
                    take_profit=Decimal(str(self.config.bounce_take_profit)),
                    time_limit=self.config.bounce_time_limit,
                    trailing_stop=None,
                    open_order_type=OrderType.MARKET,
                    take_profit_order_type=OrderType.LIMIT,
                    stop_loss_order_type=OrderType.MARKET,
                )
            elif signal_type == "short_trend":
                return TripleBarrierConfig(
                    stop_loss=Decimal("0.015"),
                    take_profit=Decimal("0.025"),
                    time_limit=86400,
                    trailing_stop=None,
                    open_order_type=OrderType.MARKET,
                    take_profit_order_type=OrderType.LIMIT,
                    stop_loss_order_type=OrderType.MARKET,
                )
        except Exception as exc:
            logger.warning("Custom triple barrier failed (%s), using config defaults: %s",
                           signal_type, exc)

        # Fallback to the default config-level triple barrier
        return self.config.triple_barrier_config

    # ── Status display ────────────────────────────────────────────

    def to_format_status(self) -> List[str]:
        lines = []
        signal = self.processed_data.get("signal", 0)
        signal_type = self.processed_data.get("signal_type", "none")
        meta = self.processed_data.get("signal_meta", "")
        price = self.processed_data.get("current_price")
        n_max = self.processed_data.get("n_day_max")
        n_min = self.processed_data.get("n_day_min")
        d_max = self.processed_data.get("dist_from_max_pct", 0)
        d_min = self.processed_data.get("dist_from_min_pct", 0)
        adx = self.processed_data.get("adx")
        ema_bull = self.processed_data.get("ema_bullish")
        trending = self.processed_data.get("is_trending")
        natr = self.processed_data.get("natr_pct")
        hour = self.processed_data.get("current_hour_utc")
        seasonal = self.processed_data.get("seasonality_active")
        lb = self.config.lookback_days

        lines.append("┌──────────────────────────────────────────────────────┐")
        lines.append("│  Directional MAX/MIN V1 — Systematic Trading        │")
        lines.append("│  (Padysak & Vojtko 2022 + Seasonality)              │")
        lines.append("└──────────────────────────────────────────────────────┘")

        # Signal banner
        if signal_type == "momentum":
            lines.append(f"  >>> LONG MOMENTUM — at {lb}-day HIGH  (signal={signal:+.2f})")
            lines.append(f"      Exit: TP {self.config.momentum_take_profit:.1%}"
                         f" / SL {self.config.momentum_stop_loss:.1%}"
                         f" / Trail {self.config.momentum_trailing_activation:.1%}"
                         f" / {self.config.momentum_time_limit // 3600}h")
        elif signal_type == "bounce":
            lines.append(f"  >>> LONG BOUNCE — at {lb}-day LOW  (signal={signal:+.2f})")
            lines.append(f"      Exit: TP {self.config.bounce_take_profit:.1%}"
                         f" / SL {self.config.bounce_stop_loss:.1%}"
                         f" / {self.config.bounce_time_limit // 3600}h")
        elif signal_type == "short_trend":
            lines.append(f"  >>> SHORT TREND — below {lb}-day LOW  (signal={signal:+.2f})")
        elif signal_type == "paused":
            lines.append("  --- PAUSED (extreme volatility) ---")
        else:
            lines.append(f"  Signal: FLAT — waiting for {lb}d MAX or MIN")

        lines.append(f"  Detail: {meta[:70]}")

        lines.append("")
        lines.append(f"── Price vs {lb}-Day Range ──────────────────────────────")
        if price and n_max and n_min:
            range_width = n_max - n_min
            position_in_range = (price - n_min) / range_width * 100 if range_width > 0 else 50
            lines.append(f"  Current:    ${price:,.2f}")
            lines.append(f"  {lb}d MAX:    ${n_max:,.2f}  ({d_max:+.2f}%)")
            lines.append(f"  {lb}d MIN:    ${n_min:,.2f}  ({d_min:+.2f}%)")
            lines.append(f"  Position:   {position_in_range:.0f}% of range")

        lines.append("")
        lines.append("── Filters ─────────────────────────────────────────────")
        trend_dir = "BULL (EMA8 > EMA21)" if ema_bull else "BEAR (EMA8 < EMA21)"
        regime = "TRENDING" if trending else "RANGING"
        lines.append(f"  Trend:      {trend_dir}")
        lines.append(f"  ADX({self.config.adx_length}):     {adx:.1f}  ({regime})" if adx else "  ADX:         warming up")
        lines.append(f"  NATR:       {natr:.2f}%" if natr else "  NATR:        warming up")

        hour_label = ""
        if seasonal:
            hour_label = " (BOOST: best hours)"
        elif hour in (3, 4):
            hour_label = " (AVOID: worst hours)"
        lines.append(f"  Hour (UTC): {hour}:00{hour_label}" if hour is not None else "")

        lines.append("")
        lines.append("── Research Basis ──────────────────────────────────────")
        lines.append("  Padysak & Vojtko (SSRN 4081000)")
        lines.append(f"  MAX{lb} Ret/Vol=1.71 | MIN{lb} Ret/Vol=0.74 | Combined=2.06")
        lines.append("  Seasonality 21-23 UTC: 33% annual, 20.9% vol")

        return lines

    def get_custom_info(self) -> dict:
        return {
            "signal": self.processed_data.get("signal"),
            "signal_type": self.processed_data.get("signal_type"),
            "current_price": self.processed_data.get("current_price"),
            "n_day_max": self.processed_data.get("n_day_max"),
            "n_day_min": self.processed_data.get("n_day_min"),
            "at_max": self.processed_data.get("at_max"),
            "at_min": self.processed_data.get("at_min"),
            "adx": self.processed_data.get("adx"),
            "ema_bullish": self.processed_data.get("ema_bullish"),
            "natr_pct": self.processed_data.get("natr_pct"),
        }
