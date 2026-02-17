"""
PMM Avellaneda V2 — Adaptive Regime-Aware Market Making Controller
====================================================================

A quantitative market making controller for Hummingbot V2 that fixes critical
bugs in pmm_rsi_llm and adds regime-aware adaptive quoting.

Fixes over pmm_rsi_llm
-----------------------
  - FIXED: RSI signal was INVERTED (bought overbought, sold oversold)
  - FIXED: Minimum spread was below exchange fees (guaranteed loss)
  - FIXED: TP/SL ratio inappropriate for market making (3%/1.5% → 0.6%/0.35%)
  - FIXED: Executor refresh too slow (300s → 60s recommended)
  - FIXED: No regime detection (mean-reverted in trends → blown up)

New features
------------
  - Multi-timeframe analysis: 1m for volatility, 5m for directional signals
  - ADX regime detection: automatically switches trend-follow vs mean-revert
  - EMA trend filter: follows momentum in trending regimes
  - Fee-aware spread floor: guarantees profitability above exchange fees
  - Avellaneda-Stoikov inspired γ parameter: single knob for risk/reward
  - Smarter RSI: mean-reverts in ranges, fades in trends (with correct sign)
  - Optional LLM overlay: capped at 15% influence, not a primary signal

Architecture
------------
  - Inherits order levels, executors, triple barrier from MarketMakingControllerBase
  - Overrides ``update_processed_data()`` for reference_price + spread_multiplier
  - Two candle feeds: interval_vol (1m) for NATR, interval_signal (5m) for RSI/EMA/ADX
  - LLM queries run in background thread (non-blocking)

Spread Model
------------
  spread_multiplier = max(NATR × regime_factor × extreme_adj, fee_floor)

  fee_floor = (maker_fee + min_profit) / min(buy_spreads)

  This ensures the tightest order level always earns more than the exchange fee.

Reference Price Model
---------------------
  ref = mid × (1 + rsi_shift + trend_shift + llm_shift)

  rsi_shift   = -RSI_norm × NATR × rsi_factor × regime_weight
                 (negative = overbought shifts DOWN → sell bias ✓)
  trend_shift = EMA_delta × trend_factor × regime_weight
                 (follows momentum in trends, muted in ranges)
  llm_shift   = -LLM_norm × NATR × llm_weight
                 (bullish shifts DOWN → cheaper buys)

Usage
-----
  1. Place at ``controllers/market_making/pmm_avellaneda_v2.py``
  2. Create controller config in ``conf/controllers/``
  3. Reference from ``v2_with_controllers`` script config
  4. ``start --script v2_with_controllers.py --conf <your_config>.yml``
"""

from __future__ import annotations

import json
import logging
import os
import time as _time
from concurrent.futures import Future, ThreadPoolExecutor
from decimal import Decimal
from typing import Any, Dict, List, Optional

import pandas_ta as ta  # noqa: F401  (available in Hummingbot image)
from pydantic import Field, field_validator
from pydantic_core.core_schema import ValidationInfo

from hummingbot.core.data_type.common import TradeType
from hummingbot.data_feed.candles_feed.data_types import CandlesConfig
from hummingbot.strategy_v2.controllers.market_making_controller_base import (
    MarketMakingControllerBase,
    MarketMakingControllerConfigBase,
)
from hummingbot.strategy_v2.executors.position_executor.data_types import PositionExecutorConfig

logger = logging.getLogger(__name__)


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  LLM Sentiment Engine (optional overlay — kept from pmm_rsi_llm)        ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class _SentimentEngine:
    """Lightweight background-threaded LLM sentiment scorer."""

    PROVIDERS: Dict[str, Dict[str, str]] = {
        "grok": {"url": "https://api.x.ai/v1/chat/completions", "model": "grok-3"},
        "openai": {"url": "https://api.openai.com/v1/chat/completions", "model": "gpt-4o-mini"},
    }

    def __init__(self, provider: str, api_key: str, fallback_provider: str,
                 fallback_api_key: str, interval: int, timeout: int):
        self.provider = provider.lower()
        self.api_key = api_key
        self.fb_provider = fallback_provider.lower()
        self.fb_key = fallback_api_key
        self.interval = interval
        self.timeout = timeout
        self._score: float = 50.0
        self._reasoning: str = "Awaiting first query"
        self._last_ts: float = 0.0
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="llm")
        self._fut: Optional[Future] = None
        self._fails: int = 0

    @property
    def score(self) -> float:
        return self._score

    @property
    def reasoning(self) -> str:
        return self._reasoning

    def tick(self, now: float, pair: str) -> None:
        if self._fut is not None and self._fut.done():
            try:
                res = self._fut.result()
                if res:
                    self._score = res["score"]
                    self._reasoning = res["reasoning"]
                    self._last_ts = now
                    self._fails = 0
                    logger.info("LLM sentiment: %.1f — %s", self._score, self._reasoning[:80])
                else:
                    self._fails += 1
            except Exception as exc:
                self._fails += 1
                logger.warning("LLM error: %s", exc)
            finally:
                self._fut = None
        if self._fut is None and (now - self._last_ts) >= self.interval:
            if self._fails >= 5:
                backoff = min(self.interval * (2 ** self._fails), 3600)
                if (now - self._last_ts) < backoff:
                    return
            self._fut = self._pool.submit(self._query, pair)

    def _query(self, pair: str) -> Optional[Dict[str, Any]]:
        try:
            import requests as _rq
        except ImportError:
            return None
        base = pair.split("-")[0] if "-" in pair else pair
        prompt = (
            f"Analyze the current real-time market sentiment for {base} ({pair}) "
            f"based on recent X/Twitter posts, crypto news, and on-chain signals. "
            f"Provide a sentiment score from 0 to 100 (0=very bearish, 100=very bullish). "
            f"Respond with ONLY valid JSON: "
            f'{{"score": <int>, "reasoning": "<one sentence>"}}'
        )
        result = self._call(self.provider, self.api_key, prompt)
        if result:
            return result
        if self.fb_key:
            return self._call(self.fb_provider, self.fb_key, prompt)
        return None

    def _call(self, provider: str, key: str, prompt: str) -> Optional[Dict[str, Any]]:
        import requests as _rq
        if not key:
            return None
        cfg = self.PROVIDERS.get(provider)
        if not cfg:
            return None
        try:
            resp = _rq.post(cfg["url"], headers={
                "Authorization": f"Bearer {key}", "Content-Type": "application/json"
            }, json={
                "model": cfg["model"],
                "messages": [
                    {"role": "system", "content": "You are a crypto sentiment analyst. Reply ONLY with JSON."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3, "max_tokens": 150,
            }, timeout=self.timeout)
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"].strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()
            parsed = json.loads(text)
            return {"score": max(0.0, min(100.0, float(parsed["score"]))),
                    "reasoning": str(parsed.get("reasoning", ""))}
        except Exception as exc:
            logger.warning("LLM %s failed: %s", provider, exc)
            return None

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False)


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  Controller Config                                                       ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class PmmAvellanedaV2Config(MarketMakingControllerConfigBase):
    """
    Configuration for the Avellaneda V2 adaptive market making controller.

    Inherits all MarketMaking fields: connector_name, trading_pair,
    buy_spreads, sell_spreads, leverage, position_mode, stop_loss,
    take_profit, time_limit, trailing_stop, executor_refresh_time, etc.

    Spreads are expressed in units of NATR (same as pmm_dynamic).
    Example: buy_spreads="1.0,2.5" means 1× and 2.5× the current NATR.
    """
    controller_name: str = "pmm_avellaneda_v2"

    # ── Candle sources (two timeframes) ──────────────────────────
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
    interval_vol: str = Field(
        default="1m",
        json_schema_extra={
            "prompt": "Volatility candle interval (e.g. 1m, 3m): ",
            "prompt_on_new": True})
    interval_signal: str = Field(
        default="5m",
        json_schema_extra={
            "prompt": "Signal candle interval (e.g. 5m, 15m): ",
            "prompt_on_new": True})

    # ── Risk aversion (Avellaneda-Stoikov γ) ─────────────────────
    gamma: float = Field(
        default=0.3,
        json_schema_extra={
            "prompt": "Risk aversion γ (0.1=aggressive tight spreads, 1.0=conservative wide): ",
            "prompt_on_new": True, "is_updatable": True})

    # ── RSI (computed on signal timeframe) ───────────────────────
    rsi_length: int = Field(
        default=14,
        json_schema_extra={
            "prompt": "RSI period (e.g. 14): ",
            "prompt_on_new": True, "is_updatable": True})
    rsi_oversold: float = Field(
        default=30.0,
        json_schema_extra={
            "prompt": "RSI oversold threshold (e.g. 30): ",
            "prompt_on_new": True, "is_updatable": True})
    rsi_overbought: float = Field(
        default=70.0,
        json_schema_extra={
            "prompt": "RSI overbought threshold (e.g. 70): ",
            "prompt_on_new": True, "is_updatable": True})
    rsi_shift_factor: float = Field(
        default=0.4,
        json_schema_extra={
            "prompt": "RSI max price shift as fraction of NATR (e.g. 0.4): ",
            "prompt_on_new": True, "is_updatable": True})

    # ── Trend detection (EMA on signal timeframe) ────────────────
    ema_fast_length: int = Field(
        default=8,
        json_schema_extra={
            "prompt": "Fast EMA period (e.g. 8): ",
            "prompt_on_new": True, "is_updatable": True})
    ema_slow_length: int = Field(
        default=21,
        json_schema_extra={
            "prompt": "Slow EMA period (e.g. 21): ",
            "prompt_on_new": True, "is_updatable": True})
    trend_follow_factor: float = Field(
        default=0.25,
        json_schema_extra={
            "prompt": "Trend following weight (0=ignore trend, 1=full follow): ",
            "prompt_on_new": True, "is_updatable": True})

    # ── Regime detection (ADX on signal timeframe) ───────────────
    adx_length: int = Field(
        default=14,
        json_schema_extra={
            "prompt": "ADX period (e.g. 14): ",
            "prompt_on_new": True, "is_updatable": True})
    adx_trend_threshold: float = Field(
        default=25.0,
        json_schema_extra={
            "prompt": "ADX threshold for trending regime (e.g. 25): ",
            "prompt_on_new": True, "is_updatable": True})

    # ── Volatility (NATR on vol timeframe) ───────────────────────
    natr_length: int = Field(
        default=14,
        json_schema_extra={
            "prompt": "NATR period (e.g. 14): ",
            "prompt_on_new": True, "is_updatable": True})
    volatility_pause_threshold: float = Field(
        default=0.0,
        json_schema_extra={
            "prompt": "NATR % above which to pause (0=never, e.g. 5.0): ",
            "prompt_on_new": True, "is_updatable": True})

    # ── Fee awareness ────────────────────────────────────────────
    maker_fee_bps: float = Field(
        default=2.0,
        json_schema_extra={
            "prompt": "Maker fee in basis points (e.g. 2.0 for 0.02%): ",
            "prompt_on_new": True, "is_updatable": True})
    min_profit_bps: float = Field(
        default=1.0,
        json_schema_extra={
            "prompt": "Min profit above fees per side in bps (e.g. 1.0): ",
            "prompt_on_new": True, "is_updatable": True})

    # ── LLM Sentiment (optional) ────────────────────────────────
    llm_enabled: bool = Field(
        default=False,
        json_schema_extra={
            "prompt": "Enable LLM sentiment overlay? (true/false): ",
            "prompt_on_new": True, "is_updatable": True})
    llm_provider: str = Field(
        default="grok",
        json_schema_extra={
            "prompt": "LLM provider (grok / openai): ",
            "prompt_on_new": True})
    llm_api_key: str = Field(
        default="",
        json_schema_extra={
            "prompt": "LLM API key (or set LLM_API_KEY env var): ",
            "prompt_on_new": True})
    llm_fallback_provider: str = Field(
        default="openai",
        json_schema_extra={
            "prompt": "LLM fallback provider (openai / grok): ",
            "prompt_on_new": True})
    llm_fallback_api_key: str = Field(
        default="",
        json_schema_extra={
            "prompt": "LLM fallback API key (or set LLM_FALLBACK_API_KEY env var): ",
            "prompt_on_new": True})
    llm_query_interval: int = Field(
        default=600,
        json_schema_extra={
            "prompt": "LLM query interval in seconds (e.g. 600): ",
            "prompt_on_new": True, "is_updatable": True})
    llm_weight: float = Field(
        default=0.15,
        json_schema_extra={
            "prompt": "LLM signal weight (0-0.3, keep small, e.g. 0.15): ",
            "prompt_on_new": True, "is_updatable": True})

    # ── Spreads (NATR units) ─────────────────────────────────────
    buy_spreads: List[float] = Field(
        default="1.0,2.5",
        json_schema_extra={
            "prompt": "Buy spreads in NATR units (e.g. '1.0,2.5'): ",
            "prompt_on_new": True, "is_updatable": True})
    sell_spreads: List[float] = Field(
        default="1.0,2.5",
        json_schema_extra={
            "prompt": "Sell spreads in NATR units (e.g. '1.0,2.5'): ",
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

    @field_validator("llm_api_key", mode="before")
    @classmethod
    def resolve_llm_key(cls, v):
        if not v or v == "":
            return os.getenv("LLM_API_KEY", "")
        return v

    @field_validator("llm_fallback_api_key", mode="before")
    @classmethod
    def resolve_llm_fallback_key(cls, v):
        if not v or v == "":
            return os.getenv("LLM_FALLBACK_API_KEY", "")
        return v


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  Controller Logic                                                        ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class PmmAvellanedaV2Controller(MarketMakingControllerBase):
    """
    Regime-aware adaptive market making controller.

    Processing pipeline (runs every ``update_interval``):
      1. Fetch 1m candles → compute NATR (volatility for spread sizing)
      2. Fetch 5m candles → compute RSI, EMA fast/slow, ADX (signals)
      3. Determine market regime: TRENDING (ADX > 25) or RANGING
      4. Tick LLM sentiment engine (non-blocking, optional)
      5. Compute reference_price:
         a. RSI mean-reversion shift (CORRECT sign: overbought → DOWN)
         b. EMA trend-following shift (follow momentum in trends)
         c. LLM sentiment shift (small weight, optional)
         d. Regime weighting (RSI dominant in ranges, EMA in trends)
      6. Compute spread_multiplier:
         a. NATR base
         b. Regime scaling (wider in trends, tighter in ranges)
         c. RSI extreme widening
         d. γ-adjusted Avellaneda spread component
         e. Fee-aware floor enforcement
      7. Base class handles order levels, executors, and risk
    """

    def __init__(self, config: PmmAvellanedaV2Config, *args, **kwargs):
        self.config = config

        # Compute max lookback for both timeframes
        signal_lookback = max(
            config.rsi_length,
            config.ema_slow_length,
            config.adx_length,
        ) + 50
        vol_lookback = config.natr_length + 50

        # Auto-configure candle feeds: two timeframes
        if len(self.config.candles_config) == 0:
            self.config.candles_config = [
                CandlesConfig(
                    connector=config.candles_connector,
                    trading_pair=config.candles_trading_pair,
                    interval=config.interval_vol,
                    max_records=vol_lookback,
                ),
                CandlesConfig(
                    connector=config.candles_connector,
                    trading_pair=config.candles_trading_pair,
                    interval=config.interval_signal,
                    max_records=signal_lookback,
                ),
            ]

        self._vol_lookback = vol_lookback
        self._signal_lookback = signal_lookback

        super().__init__(config, *args, **kwargs)

        # Initialize LLM engine if enabled
        self._sentiment: Optional[_SentimentEngine] = None
        if config.llm_enabled and (config.llm_api_key or os.getenv("LLM_API_KEY")):
            self._sentiment = _SentimentEngine(
                provider=config.llm_provider,
                api_key=config.llm_api_key or os.getenv("LLM_API_KEY", ""),
                fallback_provider=config.llm_fallback_provider,
                fallback_api_key=config.llm_fallback_api_key or os.getenv("LLM_FALLBACK_API_KEY", ""),
                interval=config.llm_query_interval,
                timeout=15,
            )
            logger.info("LLM sentiment engine initialized (provider=%s, weight=%.2f)",
                        config.llm_provider, config.llm_weight)

        # Compute fee floor once (doesn't change at runtime)
        maker_fee_dec = self.config.maker_fee_bps / 10000.0
        min_profit_dec = self.config.min_profit_bps / 10000.0
        min_spread_level = min(self.config.buy_spreads + self.config.sell_spreads) if \
            (self.config.buy_spreads and self.config.sell_spreads) else 1.0
        self._fee_floor = (maker_fee_dec + min_profit_dec) / max(min_spread_level, 0.01)
        logger.info("Fee floor: spread_multiplier >= %.6f (fee=%.1f bps, profit=%.1f bps, min_level=%.2f)",
                     self._fee_floor, self.config.maker_fee_bps,
                     self.config.min_profit_bps, min_spread_level)

    # ── Core: compute reference_price and spread_multiplier ───────

    async def update_processed_data(self):
        """
        Fetch candles from both timeframes, compute indicators, and produce:
          - reference_price: mid shifted by regime-aware RSI + trend + LLM
          - spread_multiplier: NATR scaled by regime, clamped above fee floor
          - features: signal DataFrame for status display
        """

        # ── 1. Fetch 1m candles (volatility) ──────────────────────
        df_vol = self.market_data_provider.get_candles_df(
            connector_name=self.config.candles_connector,
            trading_pair=self.config.candles_trading_pair,
            interval=self.config.interval_vol,
            max_records=self._vol_lookback,
        )

        # ── 2. Fetch 5m candles (signals) ─────────────────────────
        df_sig = self.market_data_provider.get_candles_df(
            connector_name=self.config.candles_connector,
            trading_pair=self.config.candles_trading_pair,
            interval=self.config.interval_signal,
            max_records=self._signal_lookback,
        )

        # ── 3. Fallback if data unavailable ───────────────────────
        if df_vol is None or df_vol.empty:
            mid = self.market_data_provider.get_price_by_type(
                self.config.connector_name, self.config.trading_pair)
            self.processed_data = {
                "reference_price": Decimal(str(mid)),
                "spread_multiplier": Decimal(str(max(0.001, self._fee_floor))),
                "regime": "warmup",
            }
            return

        # ── 4. NATR from 1m candles ───────────────────────────────
        natr_series = ta.natr(df_vol["high"], df_vol["low"], df_vol["close"],
                              length=self.config.natr_length)
        natr_pct = float(natr_series.iloc[-1]) if natr_series is not None and not natr_series.empty else 0.0
        natr = natr_pct / 100.0  # decimal (0.001 = 0.1%)

        mid_price = float(df_vol["close"].iloc[-1])

        # ── 5. Volatility pause ───────────────────────────────────
        if self.config.volatility_pause_threshold > 0 and natr_pct > self.config.volatility_pause_threshold:
            logger.info("VOLATILITY PAUSE: NATR=%.2f%% > threshold=%.2f%%",
                        natr_pct, self.config.volatility_pause_threshold)
            self.processed_data = {
                "reference_price": Decimal(str(mid_price)),
                "spread_multiplier": Decimal(str(natr * 5)),
                "features": df_vol, "regime": "paused",
                "natr_pct": natr_pct,
            }
            return

        # ── 6. Signal indicators from 5m candles ──────────────────
        # Defaults if signal data is unavailable (still warming up)
        rsi = 50.0
        ema_fast_val = mid_price
        ema_slow_val = mid_price
        adx_val = 20.0
        regime = "ranging"

        if df_sig is not None and not df_sig.empty and len(df_sig) >= max(
            self.config.rsi_length, self.config.ema_slow_length, self.config.adx_length
        ) + 2:
            close_sig = df_sig["close"]
            high_sig = df_sig["high"]
            low_sig = df_sig["low"]

            # RSI
            rsi_series = ta.rsi(close_sig, length=self.config.rsi_length)
            if rsi_series is not None and not rsi_series.empty:
                rsi = float(rsi_series.iloc[-1])

            # EMA fast / slow
            ema_f = ta.ema(close_sig, length=self.config.ema_fast_length)
            ema_s = ta.ema(close_sig, length=self.config.ema_slow_length)
            if ema_f is not None and not ema_f.empty:
                ema_fast_val = float(ema_f.iloc[-1])
            if ema_s is not None and not ema_s.empty:
                ema_slow_val = float(ema_s.iloc[-1])

            # ADX for regime detection
            adx_df = ta.adx(high_sig, low_sig, close_sig, length=self.config.adx_length)
            if adx_df is not None and not adx_df.empty:
                # pandas_ta adx() returns DataFrame with columns: ADX_14, DMP_14, DMN_14
                adx_col = [c for c in adx_df.columns if c.startswith("ADX")]
                if adx_col:
                    adx_val = float(adx_df[adx_col[0]].iloc[-1])

        is_trending = adx_val > self.config.adx_trend_threshold
        regime = "trending" if is_trending else "ranging"

        # ── 7. LLM tick ──────────────────────────────────────────
        sentiment_score = 50.0
        if self._sentiment is not None:
            self._sentiment.tick(_time.time(), self.config.trading_pair)
            sentiment_score = self._sentiment.score

        # ═════════════════════════════════════════════════════════
        #  REFERENCE PRICE COMPUTATION
        # ═════════════════════════════════════════════════════════

        total_shift = 0.0

        # A) RSI mean-reversion — CORRECT direction
        #    overbought (RSI>50) → rsi_norm positive → shift NEGATIVE (price DOWN)
        #    This makes sell orders easier to fill (sell bias when overbought) ✓
        #    oversold (RSI<50)   → rsi_norm negative → shift POSITIVE (price UP)
        #    This makes buy orders easier to fill (buy bias when oversold) ✓
        #    In trending regime, RSI weight is reduced to avoid fighting the trend
        rsi_norm = (rsi - 50.0) / 50.0  # [-1, +1]
        rsi_regime_weight = 0.3 if is_trending else 1.0
        rsi_shift = -rsi_norm * natr * self.config.rsi_shift_factor * rsi_regime_weight
        total_shift += rsi_shift

        # B) EMA trend following — follow momentum, stronger in trends
        #    EMA fast > slow → uptrend → positive delta → shift UP (follow the move)
        #    In ranging regime, trend weight is reduced
        if mid_price > 0:
            ema_delta = (ema_fast_val - ema_slow_val) / mid_price  # normalized
        else:
            ema_delta = 0.0
        trend_regime_weight = 1.0 if is_trending else 0.2
        trend_shift = ema_delta * self.config.trend_follow_factor * trend_regime_weight
        total_shift += trend_shift

        # C) LLM sentiment overlay — small weight, secondary signal only
        #    Bullish (score>50) → sent_norm positive → shift NEGATIVE (cheaper buys)
        llm_shift = 0.0
        if self._sentiment is not None and self.config.llm_enabled:
            sent_norm = (sentiment_score - 50.0) / 50.0
            llm_shift = -sent_norm * natr * self.config.llm_weight
            total_shift += llm_shift

        # Clamp total shift to prevent extreme reference price deviation
        max_shift = natr * 2.0  # never shift more than 2× NATR from mid
        total_shift = max(-max_shift, min(max_shift, total_shift))

        reference_price = mid_price * (1.0 + total_shift)

        # ═════════════════════════════════════════════════════════
        #  SPREAD MULTIPLIER COMPUTATION
        # ═════════════════════════════════════════════════════════

        # Base: NATR from 1m candles
        spread_mult = natr

        # Regime scaling
        if is_trending:
            # Wider spreads in trends: more adverse selection risk,
            # and we're less certain about mean-reversion
            spread_mult *= (1.0 + (adx_val - self.config.adx_trend_threshold) * 0.015)
            # e.g. ADX=35 → factor = 1.0 + 10*0.015 = 1.15
        else:
            # Tighter spreads in ranges: more fill probability,
            # safer because mean-reversion works
            range_tightening = max(0.8, 1.0 - (self.config.adx_trend_threshold - adx_val) * 0.01)
            spread_mult *= range_tightening
            # e.g. ADX=15 → factor = max(0.8, 1.0 - 10*0.01) = 0.9

        # RSI extreme widening — at extremes, spread is wider for protection
        rsi_distance = abs(rsi - 50.0)
        if rsi_distance > 20:  # outside the 30-70 band
            extreme_factor = (rsi_distance - 20.0) / 30.0  # 0 at edge, 1 at extreme
            spread_mult *= (1.0 + extreme_factor * 0.25)

        # Avellaneda-Stoikov optimal spread component (blended)
        # δ_AS ≈ γ × σ (simplified for practical use)
        # This adds a risk-aversion premium to the spread
        gamma = self.config.gamma
        as_component = gamma * natr * 0.5
        spread_mult = 0.75 * spread_mult + 0.25 * (spread_mult + as_component)

        # Fee-aware floor: NEVER place orders that lose money on fees
        spread_mult = max(spread_mult, self._fee_floor)

        # Absolute safety floor
        spread_mult = max(spread_mult, 0.0008)

        # ── Store processed data ──────────────────────────────────
        self.processed_data = {
            "reference_price": Decimal(str(reference_price)),
            "spread_multiplier": Decimal(str(spread_mult)),
            "features": df_sig if df_sig is not None else df_vol,
            "rsi": rsi,
            "natr_pct": natr_pct,
            "adx": adx_val,
            "ema_fast": ema_fast_val,
            "ema_slow": ema_slow_val,
            "regime": regime,
            "total_shift_bps": total_shift * 10000,
            "rsi_shift_bps": rsi_shift * 10000,
            "trend_shift_bps": trend_shift * 10000,
            "llm_shift_bps": llm_shift * 10000,
            "fee_floor_bps": self._fee_floor * 10000,
            "sentiment_score": sentiment_score,
            "sentiment_reasoning": self._sentiment.reasoning if self._sentiment else "",
        }

    # ── Executor config (one per order level) ─────────────────────

    def get_executor_config(self, level_id: str, price: Decimal, amount: Decimal):
        trade_type = self.get_trade_type_from_level_id(level_id)
        return PositionExecutorConfig(
            timestamp=self.market_data_provider.time(),
            level_id=level_id,
            connector_name=self.config.connector_name,
            trading_pair=self.config.trading_pair,
            entry_price=price,
            amount=amount,
            triple_barrier_config=self.config.triple_barrier_config,
            leverage=self.config.leverage,
            side=trade_type,
        )

    # ── Status display ────────────────────────────────────────────

    def to_format_status(self) -> List[str]:
        lines = []
        rsi = self.processed_data.get("rsi")
        natr_pct = self.processed_data.get("natr_pct")
        adx = self.processed_data.get("adx")
        regime = self.processed_data.get("regime", "unknown")
        ema_f = self.processed_data.get("ema_fast")
        ema_s = self.processed_data.get("ema_slow")
        sent = self.processed_data.get("sentiment_score")
        reasoning = self.processed_data.get("sentiment_reasoning", "")
        ref_price = self.processed_data.get("reference_price")
        spread_mult = self.processed_data.get("spread_multiplier")
        total_shift = self.processed_data.get("total_shift_bps", 0)
        rsi_shift = self.processed_data.get("rsi_shift_bps", 0)
        trend_shift = self.processed_data.get("trend_shift_bps", 0)
        fee_floor = self.processed_data.get("fee_floor_bps", 0)

        lines.append("┌───────────────────────────────────────────────┐")
        lines.append("│  PMM Avellaneda V2 — Adaptive Market Making   │")
        lines.append("└───────────────────────────────────────────────┘")

        # Regime banner
        regime_icon = "⟳" if regime == "ranging" else ("↗" if regime == "trending" else "⏸")
        lines.append(f"  Regime:        {regime.upper()} {regime_icon}  (ADX={adx:.1f})" if adx else f"  Regime:        {regime}")

        if rsi is not None:
            rsi_label = ""
            if rsi < self.config.rsi_oversold:
                rsi_label = " (OVERSOLD → buy bias)"
            elif rsi > self.config.rsi_overbought:
                rsi_label = " (OVERBOUGHT → sell bias)"
            lines.append(f"  RSI({self.config.rsi_length}):        {rsi:.1f}{rsi_label}")
        else:
            lines.append(f"  RSI({self.config.rsi_length}):        warming up...")

        lines.append(f"  NATR({self.config.natr_length}):       {natr_pct:.3f}%" if natr_pct else "  NATR:          warming up...")

        if ema_f and ema_s:
            ema_dir = "BULL" if ema_f > ema_s else "BEAR"
            lines.append(f"  EMA {self.config.ema_fast_length}/{self.config.ema_slow_length}:      {ema_f:.2f}/{ema_s:.2f} ({ema_dir})")

        lines.append("")
        lines.append("── Quoting ──────────────────────────────────────")
        lines.append(f"  Ref price:     {ref_price}" if ref_price else "  Ref price:     N/A")
        lines.append(f"  Spread mult:   {float(spread_mult):.6f}" if spread_mult else "  Spread mult:   N/A")
        lines.append(f"  Total shift:   {total_shift:+.2f} bps")
        lines.append(f"    RSI shift:   {rsi_shift:+.2f} bps")
        lines.append(f"    Trend shift: {trend_shift:+.2f} bps")
        lines.append(f"  Fee floor:     {fee_floor:.2f} bps")
        lines.append(f"  γ (risk):      {self.config.gamma}")

        if self._sentiment is not None:
            sent_label = "neutral"
            if sent is not None:
                if sent < 30:
                    sent_label = "BEARISH"
                elif sent > 70:
                    sent_label = "BULLISH"
            lines.append("")
            lines.append("── LLM Sentiment ────────────────────────────────")
            lines.append(f"  Score:         {sent:.0f}/100 ({sent_label})" if sent else "  Score:         N/A")
            lines.append(f"  Weight:        {self.config.llm_weight:.0%}")
            lines.append(f"  Reasoning:     {reasoning[:60]}")
        else:
            lines.append("  LLM:           disabled")

        return lines

    def get_custom_info(self) -> dict:
        return {
            "rsi": self.processed_data.get("rsi"),
            "natr_pct": self.processed_data.get("natr_pct"),
            "adx": self.processed_data.get("adx"),
            "regime": self.processed_data.get("regime"),
            "ema_fast": self.processed_data.get("ema_fast"),
            "ema_slow": self.processed_data.get("ema_slow"),
            "total_shift_bps": self.processed_data.get("total_shift_bps"),
            "spread_multiplier": float(self.processed_data.get("spread_multiplier", 0)),
            "sentiment_score": self.processed_data.get("sentiment_score"),
        }
