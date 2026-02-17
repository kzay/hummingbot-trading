"""
PMM + RSI + LLM Sentiment — Hummingbot V2 Market Making Controller
====================================================================

A dynamic market making controller that extends the V2 MarketMakingControllerBase
with RSI mean-reversion signals, NATR-based adaptive spreads, and optional LLM
sentiment overlay (Grok xAI / OpenAI).

Architecture:
  - Inherits order level management, executor refresh, triple barrier, and
    position rebalancing from MarketMakingControllerBase.
  - Overrides ``update_processed_data()`` to compute ``reference_price``
    (shifted by RSI + sentiment) and ``spread_multiplier`` (scaled by NATR +
    sentiment).
  - LLM queries run in a background thread to avoid blocking the async loop.

Usage:
  1. Place this file at ``controllers/market_making/pmm_rsi_llm.py``
  2. Create a controller config YAML in ``conf/controllers/``
  3. Reference it from a ``v2_with_controllers`` script config
  4. ``start --script v2_with_controllers.py --conf <your_config>.yml``
"""

from __future__ import annotations

import json
import logging
import os
import threading
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
# ║  LLM Sentiment Engine (embedded — no external import needed)             ║
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
        self._lock = threading.Lock()
        self._last_ts: float = 0.0
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="llm")
        self._fut: Optional[Future] = None
        self._fails: int = 0

    @property
    def score(self) -> float:
        with self._lock:
            return self._score

    @property
    def reasoning(self) -> str:
        with self._lock:
            return self._reasoning

    def tick(self, now: float, pair: str) -> None:
        if self._fut is not None and self._fut.done():
            try:
                res = self._fut.result()
                if res:
                    with self._lock:
                        self._score = res["score"]
                        self._reasoning = res["reasoning"]
                    self._last_ts = now
                    self._fails = 0
                    logger.info("LLM sentiment: %.1f — %s", self.score, self.reasoning[:80])
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
# ║  Controller Config (Pydantic)                                            ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class PmmRsiLlmConfig(MarketMakingControllerConfigBase):
    """
    Configuration for the PMM + RSI + LLM controller.

    Inherits all MarketMaking fields: connector_name, trading_pair,
    buy_spreads, sell_spreads, leverage, position_mode, stop_loss,
    take_profit, time_limit, trailing_stop, executor_refresh_time, etc.

    Spreads are expressed in units of NATR (like pmm_dynamic).
    Example: buy_spreads="1,2" means 1× and 2× the current NATR.
    """
    controller_name: str = "pmm_rsi_llm"

    # ---- Candle source ----
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
    interval: str = Field(
        default="1m",
        json_schema_extra={
            "prompt": "Candle interval (e.g., 1m, 5m, 15m, 1h): ",
            "prompt_on_new": True})

    # ---- RSI ----
    rsi_length: int = Field(
        default=14,
        json_schema_extra={
            "prompt": "RSI period length (e.g., 14): ",
            "prompt_on_new": True, "is_updatable": True})
    rsi_oversold: float = Field(
        default=30.0,
        json_schema_extra={
            "prompt": "RSI oversold threshold (e.g., 30): ",
            "prompt_on_new": True, "is_updatable": True})
    rsi_overbought: float = Field(
        default=70.0,
        json_schema_extra={
            "prompt": "RSI overbought threshold (e.g., 70): ",
            "prompt_on_new": True, "is_updatable": True})
    rsi_price_shift_factor: float = Field(
        default=0.5,
        json_schema_extra={
            "prompt": "RSI max price shift as fraction of NATR (e.g., 0.5): ",
            "prompt_on_new": True, "is_updatable": True})

    # ---- Volatility (NATR) ----
    natr_length: int = Field(
        default=14,
        json_schema_extra={
            "prompt": "NATR period length (e.g., 14): ",
            "prompt_on_new": True, "is_updatable": True})
    volatility_pause_threshold: float = Field(
        default=0.0,
        json_schema_extra={
            "prompt": "NATR % above which to pause (0 = never pause, e.g., 5.0): ",
            "prompt_on_new": True, "is_updatable": True})

    # ---- LLM Sentiment ----
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
            "prompt": "LLM query interval in seconds (e.g., 600): ",
            "prompt_on_new": True, "is_updatable": True})
    llm_price_shift_factor: float = Field(
        default=0.3,
        json_schema_extra={
            "prompt": "LLM max price shift as fraction of NATR (e.g., 0.3): ",
            "prompt_on_new": True, "is_updatable": True})

    # Override spreads description for NATR-unit context
    buy_spreads: List[float] = Field(
        default="1,2",
        json_schema_extra={
            "prompt": "Buy spreads in NATR units (e.g., '1,2' = 1× and 2× NATR): ",
            "prompt_on_new": True, "is_updatable": True})
    sell_spreads: List[float] = Field(
        default="1,2",
        json_schema_extra={
            "prompt": "Sell spreads in NATR units (e.g., '1,2' = 1× and 2× NATR): ",
            "prompt_on_new": True, "is_updatable": True})

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

class PmmRsiLlmController(MarketMakingControllerBase):
    """
    Dynamic market making controller that adjusts reference price and spread
    multiplier based on RSI, NATR, and optional LLM sentiment.

    Processing pipeline (runs every ``update_interval``):
      1. Fetch candles from MarketDataProvider
      2. Compute RSI and NATR via pandas_ta
      3. Tick LLM sentiment engine (non-blocking)
      4. Shift reference_price by RSI signal + sentiment signal
      5. Set spread_multiplier from NATR + sentiment confidence
      6. Base class handles order levels, executors, and risk
    """

    def __init__(self, config: PmmRsiLlmConfig, *args, **kwargs):
        self.config = config
        self.max_records = max(config.rsi_length, config.natr_length) + 100

        # Auto-configure candles feed if not set
        if len(self.config.candles_config) == 0:
            self.config.candles_config = [CandlesConfig(
                connector=config.candles_connector,
                trading_pair=config.candles_trading_pair,
                interval=config.interval,
                max_records=self.max_records,
            )]

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
            logger.info("LLM sentiment engine initialized (provider=%s)", config.llm_provider)

    # ── Core: compute reference_price and spread_multiplier ───────────

    async def update_processed_data(self):
        """
        Fetch candles, compute indicators, and produce:
          - reference_price: mid shifted by RSI + sentiment signals
          - spread_multiplier: NATR scaled by sentiment confidence
          - features: full DataFrame for status display
        """
        candles_df = self.market_data_provider.get_candles_df(
            connector_name=self.config.candles_connector,
            trading_pair=self.config.candles_trading_pair,
            interval=self.config.interval,
            max_records=self.max_records,
        )

        if candles_df is None or candles_df.empty:
            # Fallback: plain mid price, no adjustment
            mid = self.market_data_provider.get_price_by_type(
                self.config.connector_name, self.config.trading_pair)
            self.processed_data = {
                "reference_price": Decimal(str(mid)),
                "spread_multiplier": Decimal("1"),
            }
            return

        # ── Indicators ────────────────────────────────────────────────
        high, low, close = candles_df["high"], candles_df["low"], candles_df["close"]

        # NATR: Normalized ATR as a percentage (0–100) → convert to decimal
        natr_series = ta.natr(high, low, close, length=self.config.natr_length)
        natr_pct = float(natr_series.iloc[-1]) if natr_series is not None and not natr_series.empty else 0.0
        natr = natr_pct / 100.0  # decimal form (e.g., 0.015 = 1.5%)

        # RSI
        rsi_series = ta.rsi(close, length=self.config.rsi_length)
        rsi = float(rsi_series.iloc[-1]) if rsi_series is not None and not rsi_series.empty else 50.0

        mid_price = float(close.iloc[-1])

        # ── Volatility pause ─────────────────────────────────────────
        if self.config.volatility_pause_threshold > 0 and natr_pct > self.config.volatility_pause_threshold:
            logger.info("Volatility pause: NATR=%.2f%% > threshold=%.2f%%",
                        natr_pct, self.config.volatility_pause_threshold)
            self.processed_data = {
                "reference_price": Decimal(str(mid_price)),
                "spread_multiplier": Decimal(str(natr * 5)),  # extreme widening
                "features": candles_df,
            }
            return

        # ── LLM tick ─────────────────────────────────────────────────
        sentiment_score = 50.0
        if self._sentiment is not None:
            self._sentiment.tick(_time.time(), self.config.trading_pair)
            sentiment_score = self._sentiment.score

        # ── Price shift computation ───────────────────────────────────
        # RSI signal: normalized to [-1, +1]
        # Negative = oversold (buy bias → shift price UP for easier buy fills)
        # Positive = overbought (sell bias → shift price DOWN for easier sell fills)
        rsi_norm = (rsi - 50.0) / 50.0
        rsi_shift = -rsi_norm * natr * self.config.rsi_price_shift_factor

        # Sentiment signal: normalized to [-1, +1]
        # Positive = bullish (buy bias → shift price DOWN)
        # Negative = bearish (sell bias → shift price UP)
        sent_norm = (sentiment_score - 50.0) / 50.0
        sent_shift = -sent_norm * natr * self.config.llm_price_shift_factor

        price_multiplier = rsi_shift + sent_shift
        reference_price = mid_price * (1.0 + price_multiplier)

        # ── Spread multiplier ─────────────────────────────────────────
        # Base: NATR (so configured spreads of "1" mean 1× current volatility)
        spread_mult = natr

        # Widen at RSI extremes (outside the 30–70 band)
        rsi_extreme = max(0.0, (abs(rsi - 50.0) - 20.0) / 30.0)  # 0 at 30–70, 1 at 0/100
        spread_mult *= (1.0 + rsi_extreme * 0.5)

        # Sentiment confidence adjustment
        sent_confidence = abs(sent_norm)
        # High sentiment confidence → slightly tighter spreads (more directional)
        spread_mult *= (1.0 - sent_confidence * 0.15)

        # Ensure minimum spread
        spread_mult = max(spread_mult, 0.0005)

        # ── Store processed data ──────────────────────────────────────
        candles_df["rsi"] = rsi_series
        candles_df["natr"] = natr_series

        self.processed_data = {
            "reference_price": Decimal(str(reference_price)),
            "spread_multiplier": Decimal(str(spread_mult)),
            "features": candles_df,
            "rsi": rsi,
            "natr_pct": natr_pct,
            "sentiment_score": sentiment_score,
            "sentiment_reasoning": self._sentiment.reasoning if self._sentiment else "",
        }

    # ── Executor config (one per order level) ─────────────────────────

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

    # ── Status display ────────────────────────────────────────────────

    def to_format_status(self) -> List[str]:
        lines = []
        rsi = self.processed_data.get("rsi")
        natr_pct = self.processed_data.get("natr_pct")
        sent = self.processed_data.get("sentiment_score")
        reasoning = self.processed_data.get("sentiment_reasoning", "")
        ref_price = self.processed_data.get("reference_price")
        spread_mult = self.processed_data.get("spread_multiplier")

        lines.append("┌─────────────────────────────────────────┐")
        lines.append("│  PMM + RSI + LLM Controller Status      │")
        lines.append("└─────────────────────────────────────────┘")

        if rsi is not None:
            rsi_label = ""
            if rsi < self.config.rsi_oversold:
                rsi_label = " (OVERSOLD → buy bias)"
            elif rsi > self.config.rsi_overbought:
                rsi_label = " (OVERBOUGHT → sell bias)"
            lines.append(f"  RSI({self.config.rsi_length}):        {rsi:.1f}{rsi_label}")
        else:
            lines.append(f"  RSI({self.config.rsi_length}):        warming up...")

        lines.append(f"  NATR({self.config.natr_length}):       {natr_pct:.2f}%" if natr_pct else "  NATR:        warming up...")
        lines.append(f"  Ref price:     {ref_price}" if ref_price else "  Ref price:     N/A")
        lines.append(f"  Spread mult:   {float(spread_mult):.6f}" if spread_mult else "  Spread mult:   N/A")

        if self._sentiment is not None:
            sent_label = "neutral"
            if sent is not None:
                if sent < 30:
                    sent_label = "BEARISH"
                elif sent > 70:
                    sent_label = "BULLISH"
            lines.append(f"  Sentiment:     {sent:.0f}/100 ({sent_label})" if sent else "  Sentiment:     N/A")
            lines.append(f"  LLM reason:    {reasoning[:60]}")
        else:
            lines.append("  Sentiment:     disabled")

        return lines

    def get_custom_info(self) -> dict:
        return {
            "rsi": self.processed_data.get("rsi"),
            "natr_pct": self.processed_data.get("natr_pct"),
            "sentiment_score": self.processed_data.get("sentiment_score"),
        }
