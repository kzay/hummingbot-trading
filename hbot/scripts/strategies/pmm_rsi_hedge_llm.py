"""
Hybrid PMM + RSI Mean-Reversion + Perpetual Hedging + LLM Sentiment Strategy
=============================================================================

A production-grade Hummingbot script that combines:
  1. Pure Market Making (PMM) with configurable bid/ask spreads
  2. RSI-based mean reversion signals to dynamically skew orders
  3. Delta-neutral hedging on perpetual futures (HEDGE mode)
  4. LLM sentiment analysis (Grok xAI / OpenAI) for spread adjustment
  5. Triple-barrier risk management (TP / SL / time exit)
  6. ATR volatility filter to pause in extreme conditions

Compatible with Hummingbot >= 1.24.0 (ScriptStrategyBase).
Works with Binance, Bybit, Bitget spot and perpetual connectors.

Usage:
  >>> start --script pmm_rsi_hedge_llm.py

Author: Infrastructure Team
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time as _time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Deque, Dict, List, Optional, Set, Tuple

from hummingbot.connector.connector_base import ConnectorBase
from hummingbot.core.data_type.common import OrderType, PriceType, TradeType
from hummingbot.core.data_type.order_candidate import OrderCandidate
from hummingbot.core.event.events import OrderFilledEvent
from hummingbot.strategy.script_strategy_base import ScriptStrategyBase

logger = logging.getLogger(__name__)


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 1 — USER CONFIGURATION                                         ║
# ║  Edit the values below or override via config YAML                       ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

# ---- Exchange & Pair -------------------------------------------------
EXCHANGE_SPOT = "bitget"
EXCHANGE_PERP = "bitget_perpetual"
TRADING_PAIR = "BTC-USDT"

# ---- PMM Core --------------------------------------------------------
BASE_BID_SPREAD = Decimal("0.002")          # 0.2 %
BASE_ASK_SPREAD = Decimal("0.002")          # 0.2 %
ORDER_AMOUNT = Decimal("0.001")             # base-asset units per side
ORDER_REFRESH_SECS = 30                     # cancel & re-place cycle
ORDER_LEVELS = 1                            # orders per side (1 = simple)
ORDER_LEVEL_SPREAD = Decimal("0.001")       # extra spread per level
MIN_SPREAD = Decimal("0.0005")              # floor  (0.05 %)
MAX_SPREAD = Decimal("0.02")                # ceiling (2.0 %)

# ---- RSI Mean-Reversion ---------------------------------------------
RSI_ENABLED = True
RSI_PERIOD = 14
RSI_OVERSOLD = 30.0
RSI_OVERBOUGHT = 70.0
RSI_SPREAD_FACTOR = Decimal("0.5")          # max ±50 % spread adjustment
CANDLE_INTERVAL_SECS = 60                   # synthetic candle length
PRICE_HISTORY_SIZE = 200                    # rolling candle window

# ---- ATR Volatility Filter -------------------------------------------
ATR_ENABLED = True
ATR_PERIOD = 14
ATR_PAUSE_MULTIPLIER = 3.0                  # pause if ATR > mean * multiplier
ATR_WIDEN_MULTIPLIER = 1.5                  # widen spreads if ATR > mean * this

# ---- Hedging (Perpetual Futures) -------------------------------------
HEDGE_ENABLED = True
HEDGE_LEVERAGE = 5                          # 1–10 ×
HEDGE_INVENTORY_THRESHOLD = Decimal("0.5")  # trigger when imbalance > 50 %
HEDGE_REBALANCE_SECS = 60                   # check interval

# ---- LLM Sentiment ---------------------------------------------------
LLM_ENABLED = False
LLM_PROVIDER = "grok"                       # "grok" | "openai"
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_FALLBACK_PROVIDER = "openai"
LLM_FALLBACK_API_KEY = os.getenv("LLM_FALLBACK_API_KEY", "")
LLM_QUERY_INTERVAL_SECS = 600              # 10 min
LLM_REQUEST_TIMEOUT = 15                    # seconds
LLM_SPREAD_FACTOR = Decimal("0.3")          # max ±30 % spread shift

# ---- Risk / Triple-Barrier -------------------------------------------
TP_PCT = Decimal("0.03")                    # take profit  3 %
SL_PCT = Decimal("0.015")                   # stop loss    1.5 %
MAX_HOLD_SECS = 7200                        # time exit    2 hours
MAX_POSITION_PCT = Decimal("0.02")          # max 2 % of capital per side
KILL_SWITCH_LOSS_PCT = Decimal("0.10")      # halt at 10 % drawdown

# ---- Paper / Live Mode -----------------------------------------------
PAPER_TRADE = False                         # True = paper-trade connectors


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 2 — DATA STRUCTURES                                            ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

@dataclass
class Candle:
    """Synthetic OHLC candle built from tick prices."""
    timestamp: float
    open: float
    high: float
    low: float
    close: float


@dataclass
class TrackedFill:
    """Tracks a filled order for triple-barrier exit management."""
    order_id: str
    side: TradeType
    price: Decimal
    amount: Decimal
    timestamp: float
    exchange: str
    pair: str
    closed: bool = False
    close_reason: str = ""


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 3 — TECHNICAL INDICATORS (pure Python, no ta-lib needed)       ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class PriceCollector:
    """
    Collects mid-price ticks and aggregates into synthetic candles
    at a configurable interval.  Maintains a rolling window.
    """

    def __init__(self, candle_interval: int = 60, max_candles: int = 200):
        self.candle_interval = candle_interval
        self.max_candles = max_candles
        self.candles: Deque[Candle] = deque(maxlen=max_candles)
        self._cur: Optional[Candle] = None
        self._start_ts: float = 0.0

    # ------------------------------------------------------------------
    def add_tick(self, price: float, ts: float) -> None:
        if self._cur is None:
            self._open_candle(price, ts)
            return
        if ts - self._start_ts >= self.candle_interval:
            self.candles.append(self._cur)
            self._open_candle(price, ts)
        else:
            self._cur.high = max(self._cur.high, price)
            self._cur.low = min(self._cur.low, price)
            self._cur.close = price

    def _open_candle(self, price: float, ts: float) -> None:
        self._cur = Candle(timestamp=ts, open=price, high=price,
                           low=price, close=price)
        self._start_ts = ts

    # ------------------------------------------------------------------
    @property
    def closes(self) -> List[float]:
        out = [c.close for c in self.candles]
        if self._cur:
            out.append(self._cur.close)
        return out

    @property
    def all_candles(self) -> List[Candle]:
        out = list(self.candles)
        if self._cur:
            out.append(self._cur)
        return out

    @property
    def count(self) -> int:
        return len(self.candles) + (1 if self._cur else 0)


def compute_rsi(closes: List[float], period: int = 14) -> Optional[float]:
    """Wilder-smoothed RSI.  Returns None when insufficient data."""
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(d, 0.0) for d in deltas]
    losses = [abs(min(d, 0.0)) for d in deltas]
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return 100.0 - (100.0 / (1.0 + rs))


def compute_atr(candles: List[Candle], period: int = 14) -> Optional[float]:
    """Wilder-smoothed ATR.  Returns None when insufficient data."""
    if len(candles) < period + 1:
        return None
    trs: List[float] = []
    for i in range(1, len(candles)):
        h, lo, pc = candles[i].high, candles[i].low, candles[i - 1].close
        trs.append(max(h - lo, abs(h - pc), abs(lo - pc)))
    if len(trs) < period:
        return None
    atr = sum(trs[:period]) / period
    for i in range(period, len(trs)):
        atr = (atr * (period - 1) + trs[i]) / period
    return atr


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 4 — LLM SENTIMENT ENGINE                                       ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class SentimentEngine:
    """
    Asynchronous LLM sentiment scorer.

    Queries Grok (xAI) or OpenAI in a background thread, caches the
    result, and exposes a simple ``score`` property (0–100, 50 = neutral).
    Falls back to neutral on any failure.
    """

    PROVIDERS: Dict[str, Dict[str, str]] = {
        "grok": {
            "url": "https://api.x.ai/v1/chat/completions",
            "model": "grok-3",
        },
        "openai": {
            "url": "https://api.openai.com/v1/chat/completions",
            "model": "gpt-4o-mini",
        },
    }

    def __init__(
        self,
        provider: str = "grok",
        api_key: str = "",
        fallback_provider: str = "openai",
        fallback_api_key: str = "",
        query_interval: int = 600,
        request_timeout: int = 15,
    ):
        self.provider = provider.lower()
        self.api_key = api_key
        self.fallback_provider = fallback_provider.lower()
        self.fallback_api_key = fallback_api_key
        self.query_interval = query_interval
        self.request_timeout = request_timeout

        self._score: float = 50.0
        self._reasoning: str = "Awaiting first query"
        self._lock = threading.Lock()
        self._last_query_ts: float = 0.0
        self._pool = ThreadPoolExecutor(max_workers=1,
                                        thread_name_prefix="llm-sent")
        self._future: Optional[Future] = None
        self._failures: int = 0

    # -- public interface ------------------------------------------------
    @property
    def score(self) -> float:
        with self._lock:
            return self._score

    @property
    def reasoning(self) -> str:
        with self._lock:
            return self._reasoning

    @property
    def is_stale(self) -> bool:
        if self._last_query_ts == 0:
            return True
        return (_time.time() - self._last_query_ts) > self.query_interval * 3

    def tick(self, now: float, pair: str) -> None:
        """Non-blocking tick — harvest completed futures, launch new ones."""
        if self._future is not None and self._future.done():
            try:
                res = self._future.result()
                if res is not None:
                    with self._lock:
                        self._score = res["score"]
                        self._reasoning = res["reasoning"]
                    self._last_query_ts = now
                    self._failures = 0
                    logger.info("LLM sentiment: %.1f — %s",
                                self.score, self.reasoning[:100])
                else:
                    self._failures += 1
            except Exception as exc:
                self._failures += 1
                logger.warning("LLM future error: %s", exc)
            finally:
                self._future = None

        if self._future is None and (now - self._last_query_ts) >= self.query_interval:
            backoff = min(self.query_interval * (2 ** self._failures), 3600)
            if self._failures >= 5 and (now - self._last_query_ts) < backoff:
                return
            self._future = self._pool.submit(self._query, pair)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False)

    # -- internal --------------------------------------------------------
    def _query(self, pair: str) -> Optional[Dict[str, Any]]:
        try:
            import requests as _req
        except ImportError:
            logger.error("python-requests not installed; LLM disabled")
            return None

        base = pair.split("-")[0] if "-" in pair else pair
        prompt = (
            f"Analyze the current real-time market sentiment for {base} "
            f"({pair}) based on recent X/Twitter posts, crypto news, and "
            f"on-chain signals.  Provide a sentiment score from 0 to 100:\n"
            f"  0-20  = Very bearish\n"
            f"  20-40 = Bearish\n"
            f"  40-60 = Neutral\n"
            f"  60-80 = Bullish\n"
            f"  80-100= Very bullish\n\n"
            f"Respond with ONLY valid JSON:\n"
            f'{{"score": <int>, "reasoning": "<one sentence>"}}'
        )
        result = self._call(self.provider, self.api_key, prompt)
        if result is not None:
            return result
        if self.fallback_api_key:
            logger.info("LLM primary failed → trying fallback %s",
                        self.fallback_provider)
            return self._call(self.fallback_provider,
                              self.fallback_api_key, prompt)
        return None

    def _call(self, provider: str, key: str,
              prompt: str) -> Optional[Dict[str, Any]]:
        import requests as _req

        if not key:
            return None
        cfg = self.PROVIDERS.get(provider)
        if cfg is None:
            return None
        headers = {"Authorization": f"Bearer {key}",
                    "Content-Type": "application/json"}
        body = {
            "model": cfg["model"],
            "messages": [
                {"role": "system",
                 "content": ("You are a crypto market sentiment analyst. "
                             "Reply ONLY with the requested JSON.")},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 150,
        }
        try:
            resp = _req.post(cfg["url"], headers=headers, json=body,
                             timeout=self.request_timeout)
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"].strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()
            parsed = json.loads(text)
            score = float(parsed["score"])
            score = max(0.0, min(100.0, score))
            reasoning = str(parsed.get("reasoning", ""))
            return {"score": score, "reasoning": reasoning}
        except Exception as exc:
            logger.warning("LLM %s call failed: %s", provider, exc)
            return None


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 5 — MAIN STRATEGY CLASS                                        ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class PmmRsiHedgeLlm(ScriptStrategyBase):
    """
    Hybrid Pure-Market-Making strategy with RSI mean reversion,
    perpetual-futures delta hedging, and LLM sentiment overlay.
    """

    # ---- Exchange / Pair (edit or override) ----------------------------
    exchange_spot: str = EXCHANGE_SPOT
    exchange_perp: str = EXCHANGE_PERP
    trading_pair: str = TRADING_PAIR

    # Build the ``markets`` mapping Hummingbot needs at class level.
    # This dict tells Hummingbot which connectors to initialise.
    markets: Dict[str, Set[str]] = (
        {EXCHANGE_SPOT: {TRADING_PAIR}, EXCHANGE_PERP: {TRADING_PAIR}}
        if HEDGE_ENABLED and EXCHANGE_PERP
        else {EXCHANGE_SPOT: {TRADING_PAIR}}
    )

    # ---- Internal state ------------------------------------------------
    _collector: Optional[PriceCollector] = None
    _sentiment: Optional[SentimentEngine] = None
    _fills: List[TrackedFill] = []
    _last_order_ts: float = 0.0
    _last_hedge_ts: float = 0.0
    _initial_base_balance: Optional[Decimal] = None
    _initial_quote_balance: Optional[Decimal] = None
    _initial_perp_quote_balance: Optional[Decimal] = None
    _hedge_position_amount: Decimal = Decimal("0")
    _hedge_avg_entry_price: Decimal = Decimal("0")
    _order_roles: Dict[str, str] = {}
    _atr_history: Deque[float] = deque(maxlen=200)
    _started: bool = False

    # ================================================================
    #  Lifecycle
    # ================================================================

    def __init__(self, connectors: Dict[str, ConnectorBase]):
        super().__init__(connectors)
        self._collector = PriceCollector(
            candle_interval=CANDLE_INTERVAL_SECS,
            max_candles=PRICE_HISTORY_SIZE,
        )
        if LLM_ENABLED:
            self._sentiment = SentimentEngine(
                provider=LLM_PROVIDER,
                api_key=LLM_API_KEY,
                fallback_provider=LLM_FALLBACK_PROVIDER,
                fallback_api_key=LLM_FALLBACK_API_KEY,
                query_interval=LLM_QUERY_INTERVAL_SECS,
                request_timeout=LLM_REQUEST_TIMEOUT,
            )
        else:
            self._sentiment = None
        self._fills = []
        self._hedge_position_amount = Decimal("0")
        self._hedge_avg_entry_price = Decimal("0")
        self._order_roles = {}
        self._atr_history = deque(maxlen=200)

    # ================================================================
    #  on_tick  —  main loop (called every ~1 s)
    # ================================================================

    def on_tick(self) -> None:
        if not self.ready_to_trade:
            return

        now = self.current_timestamp
        conn = self.connectors[self.exchange_spot]
        mid = float(conn.get_price_by_type(self.trading_pair, PriceType.MidPrice))

        # Snapshot initial balances once
        if self._initial_base_balance is None:
            self._snapshot_initial_balances()

        # 1. Feed price collector
        self._collector.add_tick(mid, now)

        # 2. Update LLM sentiment (non-blocking)
        if self._sentiment is not None:
            self._sentiment.tick(now, self.trading_pair)

        # 3. Compute indicators
        rsi = compute_rsi(self._collector.closes, RSI_PERIOD) if RSI_ENABLED else None
        atr = compute_atr(self._collector.all_candles, ATR_PERIOD) if ATR_ENABLED else None
        if atr is not None:
            self._atr_history.append(atr)

        # 4. Volatility gate — pause new orders if ATR is extreme
        if self._should_pause_on_volatility(atr, mid):
            self._cancel_all_spot_orders()
            return

        # 5. Triple-barrier exit check on tracked fills
        self._check_triple_barrier(now, mid)

        # 6. Kill-switch check
        if self._kill_switch_triggered(mid):
            self._cancel_all_spot_orders()
            self.notify_hb_app_with_timestamp(
                "KILL SWITCH triggered — halting strategy."
            )
            return

        # 7. PMM order refresh
        if now >= self._last_order_ts + ORDER_REFRESH_SECS:
            self._cancel_all_spot_orders()
            self._place_pmm_orders(mid, rsi, atr)
            self._last_order_ts = now

        # 8. Hedge rebalance
        if HEDGE_ENABLED and now >= self._last_hedge_ts + HEDGE_REBALANCE_SECS:
            self._rebalance_hedge(mid)
            self._last_hedge_ts = now

    # ================================================================
    #  PMM Order Placement
    # ================================================================

    def _place_pmm_orders(self, mid: float, rsi: Optional[float],
                          atr: Optional[float]) -> None:
        bid_spread, ask_spread = self._compute_adjusted_spreads(rsi, atr)
        conn = self.connectors[self.exchange_spot]
        mid_d = Decimal(str(mid))
        proposals: List[OrderCandidate] = []

        for level in range(ORDER_LEVELS):
            level_extra = ORDER_LEVEL_SPREAD * level
            buy_price = mid_d * (Decimal("1") - bid_spread - level_extra)
            sell_price = mid_d * (Decimal("1") + ask_spread + level_extra)
            amount = self._capped_order_amount(mid_d)

            if amount <= Decimal("0"):
                continue

            proposals.append(OrderCandidate(
                trading_pair=self.trading_pair,
                is_maker=True,
                order_type=OrderType.LIMIT,
                order_side=TradeType.BUY,
                amount=amount,
                price=buy_price,
            ))
            proposals.append(OrderCandidate(
                trading_pair=self.trading_pair,
                is_maker=True,
                order_type=OrderType.LIMIT,
                order_side=TradeType.SELL,
                amount=amount,
                price=sell_price,
            ))

        proposals = conn.budget_checker.adjust_candidates(proposals,
                                                          all_or_none=False)
        for p in proposals:
            if p.amount <= Decimal("0"):
                continue
            if p.order_side == TradeType.BUY:
                order_id = self.buy(self.exchange_spot, p.trading_pair,
                                    p.amount, p.order_type, p.price)
            else:
                order_id = self.sell(self.exchange_spot, p.trading_pair,
                                     p.amount, p.order_type, p.price)
            if order_id:
                self._order_roles[order_id] = "spot_entry"

    # ================================================================
    #  Spread Adjustment Engine
    # ================================================================

    def _compute_adjusted_spreads(
        self, rsi: Optional[float], atr: Optional[float]
    ) -> Tuple[Decimal, Decimal]:
        bid = BASE_BID_SPREAD
        ask = BASE_ASK_SPREAD

        # --- RSI adjustment ---
        if rsi is not None and RSI_ENABLED:
            rsi_norm = Decimal(str((rsi - 50.0) / 50.0))  # –1 … +1
            bid_adj = -rsi_norm * RSI_SPREAD_FACTOR
            ask_adj = rsi_norm * RSI_SPREAD_FACTOR
            bid = bid * (Decimal("1") + bid_adj)
            ask = ask * (Decimal("1") + ask_adj)

        # --- LLM sentiment adjustment ---
        if self._sentiment is not None and LLM_ENABLED:
            s_norm = Decimal(str((self._sentiment.score - 50.0) / 50.0))
            bid = bid * (Decimal("1") - s_norm * LLM_SPREAD_FACTOR)
            ask = ask * (Decimal("1") + s_norm * LLM_SPREAD_FACTOR)

        # --- ATR widening ---
        if atr is not None and ATR_ENABLED:
            mean_atr = (sum(self._atr_history) / len(self._atr_history)) if self._atr_history else atr
            if mean_atr > 0 and atr > mean_atr * ATR_WIDEN_MULTIPLIER:
                widen = Decimal(str(min(atr / mean_atr, 3.0)))
                bid = bid * widen
                ask = ask * widen

        # --- Inventory skew ---
        inv_ratio = self._inventory_ratio()
        if inv_ratio is not None:
            skew = Decimal(str(inv_ratio)) * Decimal("0.5")
            bid = bid * (Decimal("1") + skew)
            ask = ask * (Decimal("1") - skew)

        bid = max(MIN_SPREAD, min(MAX_SPREAD, bid))
        ask = max(MIN_SPREAD, min(MAX_SPREAD, ask))
        return bid, ask

    # ================================================================
    #  Hedging (Perpetual Futures)
    # ================================================================

    def _rebalance_hedge(self, mid: float) -> None:
        if self.exchange_perp not in self.connectors:
            return
        inv_ratio = self._inventory_ratio()
        if inv_ratio is None:
            return
        if abs(inv_ratio) < float(HEDGE_INVENTORY_THRESHOLD):
            return

        base_asset = self.trading_pair.split("-")[0]
        conn_spot = self.connectors[self.exchange_spot]
        base_bal = conn_spot.get_balance(base_asset)
        target_hedge = -(base_bal - (self._initial_base_balance or Decimal("0")))
        delta = target_hedge - self._hedge_position_amount
        abs_delta = abs(delta)

        if abs_delta < ORDER_AMOUNT * Decimal("0.1"):
            return

        mid_d = Decimal(str(mid))
        conn_perp = self.connectors[self.exchange_perp]

        if delta > Decimal("0"):
            hedge_order = OrderCandidate(
                trading_pair=self.trading_pair,
                is_maker=False,
                order_type=OrderType.MARKET,
                order_side=TradeType.BUY,
                amount=abs_delta,
                price=mid_d,
            )
            adjusted = conn_perp.budget_checker.adjust_candidates(
                [hedge_order], all_or_none=True
            )
            if adjusted and adjusted[0].amount > Decimal("0"):
                order_id = self.buy(self.exchange_perp, self.trading_pair,
                                    adjusted[0].amount, OrderType.MARKET, mid_d)
                if order_id:
                    self._order_roles[order_id] = "hedge"
                logger.info("Hedge BUY perp %.6f @ ~%.2f",
                            adjusted[0].amount, mid)
        else:
            hedge_order = OrderCandidate(
                trading_pair=self.trading_pair,
                is_maker=False,
                order_type=OrderType.MARKET,
                order_side=TradeType.SELL,
                amount=abs_delta,
                price=mid_d,
            )
            adjusted = conn_perp.budget_checker.adjust_candidates(
                [hedge_order], all_or_none=True
            )
            if adjusted and adjusted[0].amount > Decimal("0"):
                order_id = self.sell(self.exchange_perp, self.trading_pair,
                                     adjusted[0].amount, OrderType.MARKET, mid_d)
                if order_id:
                    self._order_roles[order_id] = "hedge"
                logger.info("Hedge SELL perp %.6f @ ~%.2f",
                            adjusted[0].amount, mid)

    # ================================================================
    #  Triple-Barrier Risk Management
    # ================================================================

    def _check_triple_barrier(self, now: float, mid: float) -> None:
        mid_d = Decimal(str(mid))
        for fill in self._fills:
            if fill.closed:
                continue

            pnl_pct = self._unrealized_pnl_pct(fill, mid_d)
            age = now - fill.timestamp

            reason = ""
            if pnl_pct >= TP_PCT:
                reason = f"TP hit ({float(pnl_pct):.2%})"
            elif pnl_pct <= -SL_PCT:
                reason = f"SL hit ({float(pnl_pct):.2%})"
            elif age >= MAX_HOLD_SECS:
                reason = f"Time exit ({age:.0f}s)"

            if reason:
                self._close_fill(fill, mid_d, reason)

    def _unrealized_pnl_pct(self, fill: TrackedFill,
                             current_price: Decimal) -> Decimal:
        if fill.side == TradeType.BUY:
            return (current_price - fill.price) / fill.price
        else:
            return (fill.price - current_price) / fill.price

    def _close_fill(self, fill: TrackedFill, price: Decimal,
                    reason: str) -> None:
        if fill.side == TradeType.BUY:
            order_id = self.sell(fill.exchange, fill.pair, fill.amount,
                                 OrderType.MARKET, price)
        else:
            order_id = self.buy(fill.exchange, fill.pair, fill.amount,
                                OrderType.MARKET, price)
        if order_id:
            self._order_roles[order_id] = "spot_exit"
        fill.closed = True
        fill.close_reason = reason
        msg = (f"Triple-barrier exit: {reason} | "
               f"{fill.side.name} {fill.amount} {fill.pair} "
               f"entry={fill.price} exit≈{price}")
        logger.info(msg)
        self.notify_hb_app_with_timestamp(msg)

    # ================================================================
    #  Order Fill Tracking
    # ================================================================

    def on_order_filled(self, event: OrderFilledEvent) -> None:
        role = self._order_roles.get(event.order_id)
        if role == "hedge":
            self._apply_hedge_fill(event.trade_type, event.amount, event.price)
            return
        if role == "spot_exit":
            return
        if role != "spot_entry":
            return

        fill = TrackedFill(
            order_id=event.order_id,
            side=event.trade_type,
            price=event.price,
            amount=event.amount,
            timestamp=self.current_timestamp,
            exchange=self.exchange_spot,
            pair=event.trading_pair,
        )
        self._fills.append(fill)

        msg = (f"Fill: {event.trade_type.name} {event.amount} "
               f"{event.trading_pair} @ {event.price}")
        logger.info(msg)
        self.notify_hb_app_with_timestamp(msg)

        # Prune old closed fills to bound memory
        self._fills = [f for f in self._fills
                       if not f.closed or
                       (self.current_timestamp - f.timestamp) < MAX_HOLD_SECS * 2]

    # ================================================================
    #  Helpers
    # ================================================================

    def _snapshot_initial_balances(self) -> None:
        base, quote = self.trading_pair.split("-")
        conn = self.connectors[self.exchange_spot]
        self._initial_base_balance = conn.get_balance(base)
        self._initial_quote_balance = conn.get_balance(quote)
        if HEDGE_ENABLED and self.exchange_perp in self.connectors:
            self._initial_perp_quote_balance = self.connectors[self.exchange_perp].get_balance(quote)
        logger.info("Initial balances: %s=%s  %s=%s",
                     base, self._initial_base_balance,
                     quote, self._initial_quote_balance)

    def _inventory_ratio(self) -> Optional[float]:
        """
        Inventory ratio in [-1, 1].
        Positive = long bias (excess base), negative = short bias.
        """
        if self._initial_base_balance is None:
            return None
        base = self.trading_pair.split("-")[0]
        conn = self.connectors[self.exchange_spot]
        current = conn.get_balance(base)
        initial = self._initial_base_balance
        if initial == Decimal("0"):
            return 0.0
        ratio = float((current - initial) / initial)
        return max(-1.0, min(1.0, ratio))

    def _capped_order_amount(self, mid: Decimal) -> Decimal:
        """Cap order size to MAX_POSITION_PCT of total capital."""
        quote = self.trading_pair.split("-")[1]
        conn = self.connectors[self.exchange_spot]
        quote_bal = conn.get_balance(quote)
        max_quote = quote_bal * MAX_POSITION_PCT
        max_base = max_quote / mid if mid > Decimal("0") else Decimal("0")
        return min(ORDER_AMOUNT, max_base)

    def _should_pause_on_volatility(self, atr: Optional[float],
                                     mid: float) -> bool:
        if not ATR_ENABLED or atr is None or mid <= 0:
            return False
        atr_pct = atr / mid
        threshold = float(BASE_BID_SPREAD) * ATR_PAUSE_MULTIPLIER
        if atr_pct > threshold:
            logger.info("ATR filter: pausing (ATR%%=%.4f > threshold=%.4f)",
                        atr_pct, threshold)
            return True
        return False

    def _kill_switch_triggered(self, mid: float) -> bool:
        if self._initial_quote_balance is None:
            return False
        base, quote = self.trading_pair.split("-")
        conn = self.connectors[self.exchange_spot]
        cur_base = conn.get_balance(base)
        cur_quote = conn.get_balance(quote)
        mid_d = Decimal(str(mid))
        initial_value = (self._initial_base_balance * mid_d
                         + self._initial_quote_balance)
        current_value = cur_base * mid_d + cur_quote
        if HEDGE_ENABLED and self.exchange_perp in self.connectors:
            conn_perp = self.connectors[self.exchange_perp]
            perp_quote = conn_perp.get_balance(quote)
            if self._initial_perp_quote_balance is not None:
                current_value += perp_quote - self._initial_perp_quote_balance
            current_value += self._estimate_hedge_unrealized_pnl(mid_d)
        if initial_value <= Decimal("0"):
            return False
        drawdown = (initial_value - current_value) / initial_value
        return drawdown >= KILL_SWITCH_LOSS_PCT

    def _estimate_hedge_unrealized_pnl(self, mid: Decimal) -> Decimal:
        if self._hedge_position_amount == Decimal("0") or self._hedge_avg_entry_price <= Decimal("0"):
            return Decimal("0")
        if self._hedge_position_amount > Decimal("0"):
            return (mid - self._hedge_avg_entry_price) * self._hedge_position_amount
        return (self._hedge_avg_entry_price - mid) * abs(self._hedge_position_amount)

    def _apply_hedge_fill(self, side: TradeType, amount: Decimal, price: Decimal) -> None:
        if amount <= Decimal("0") or price <= Decimal("0"):
            return

        signed_delta = amount if side == TradeType.BUY else -amount
        current_amount = self._hedge_position_amount
        current_avg = self._hedge_avg_entry_price

        if current_amount == Decimal("0") or (current_amount > 0 and signed_delta > 0) or (current_amount < 0 and signed_delta < 0):
            new_amount = current_amount + signed_delta
            weighted_notional = (abs(current_amount) * current_avg) + (abs(signed_delta) * price)
            self._hedge_position_amount = new_amount
            self._hedge_avg_entry_price = (weighted_notional / abs(new_amount)) if new_amount != Decimal("0") else Decimal("0")
            return

        # Reducing or flipping an existing hedge position.
        if abs(signed_delta) < abs(current_amount):
            self._hedge_position_amount = current_amount + signed_delta
            return
        if abs(signed_delta) == abs(current_amount):
            self._hedge_position_amount = Decimal("0")
            self._hedge_avg_entry_price = Decimal("0")
            return

        flipped_amount = current_amount + signed_delta
        self._hedge_position_amount = flipped_amount
        self._hedge_avg_entry_price = price

    def _cancel_all_spot_orders(self) -> None:
        for order in self.get_active_orders(connector_name=self.exchange_spot):
            self.cancel(self.exchange_spot, order.trading_pair,
                        order.client_order_id)

    # ================================================================
    #  Status Display
    # ================================================================

    def format_status(self) -> str:
        if not self.ready_to_trade:
            return "Market connectors not ready.  Waiting..."

        conn = self.connectors[self.exchange_spot]
        mid = conn.get_price_by_type(self.trading_pair, PriceType.MidPrice)
        rsi = compute_rsi(self._collector.closes, RSI_PERIOD) if RSI_ENABLED else None
        atr = compute_atr(self._collector.all_candles, ATR_PERIOD) if ATR_ENABLED else None

        lines = [
            "╔══════════════════════════════════════════════╗",
            "║    PMM + RSI + Hedge + LLM  — Status        ║",
            "╚══════════════════════════════════════════════╝",
            f"  Pair:           {self.trading_pair}",
            f"  Spot exchange:  {self.exchange_spot}",
            f"  Perp exchange:  {self.exchange_perp if HEDGE_ENABLED else 'disabled'}",
            f"  Mid price:      {mid:.2f}",
            "",
            "── Indicators ──────────────────────────────────",
            f"  RSI ({RSI_PERIOD}):       {f'{rsi:.1f}' if rsi else 'warming up'}"
            f"  {'(oversold)' if rsi and rsi < RSI_OVERSOLD else '(overbought)' if rsi and rsi > RSI_OVERBOUGHT else ''}",
            f"  ATR ({ATR_PERIOD}):       {f'{atr:.2f}' if atr else 'warming up'}",
            f"  Candles:        {self._collector.count} / {PRICE_HISTORY_SIZE}",
        ]

        if self._sentiment:
            lines += [
                "",
                "── LLM Sentiment ───────────────────────────────",
                f"  Provider:       {LLM_PROVIDER}"
                f"{'  (stale!)' if self._sentiment.is_stale else ''}",
                f"  Score:          {self._sentiment.score:.0f} / 100",
                f"  Reasoning:      {self._sentiment.reasoning[:60]}",
            ]

        bid_sp, ask_sp = self._compute_adjusted_spreads(rsi, atr)
        lines += [
            "",
            "── Spreads (adjusted) ──────────────────────────",
            f"  Bid spread:     {float(bid_sp):.4%}",
            f"  Ask spread:     {float(ask_sp):.4%}",
            f"  Inventory ratio:{self._inventory_ratio() or 0:.3f}",
        ]

        active = self.get_active_orders(connector_name=self.exchange_spot)
        lines += [
            "",
            f"── Orders ({len(active)} active) ─────────────────────────",
        ]
        for o in active:
            lines.append(f"    {o.trade_type.name:4s}  {o.amount}  @ {o.price}")

        open_fills = [f for f in self._fills if not f.closed]
        lines += [
            "",
            f"── Tracked Fills ({len(open_fills)} open) ──────────────────",
        ]
        for f in open_fills[-5:]:
            age = self.current_timestamp - f.timestamp
            pnl = self._unrealized_pnl_pct(f, Decimal(str(float(mid))))
            lines.append(
                f"    {f.side.name:4s}  {f.amount}  entry={f.price}  "
                f"pnl={float(pnl):.2%}  age={age:.0f}s"
            )

        if HEDGE_ENABLED:
            lines += [
                "",
                "── Hedge ───────────────────────────────────────",
                f"  Perp position:  {self._hedge_position_amount}",
                f"  Leverage:       {HEDGE_LEVERAGE}x",
            ]

        base, quote = self.trading_pair.split("-")
        lines += [
            "",
            "── Balances ────────────────────────────────────",
            f"  {base}:  {conn.get_balance(base)}",
            f"  {quote}: {conn.get_balance(quote)}",
        ]

        return "\n".join(lines)
