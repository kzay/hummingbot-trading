"""Backtesting adapter for the bot7 ML signal strategy.

Market-making approach: place two-sided quotes, capture spread.
No directional SL/TP — instead uses inventory limits and time-based
flattening. ML regime model controls spread width and sizing.

Semi-pro mechanics:
- Two-sided quoting (buy below mid, sell above mid)
- Inventory cap: flatten if position exceeds max_inventory_pct
- Time-based flatten: close after max_hold_bars
- Daily loss limit, drawdown limit, turnover limit
- Cancel-and-replace stale orders each tick
- Regime-aware spread width from ML signal
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from controllers.backtesting.types import CandleRow
from controllers.bots.bot7.ml_signal_source import MlSignalConfig, MlSignalSource
from controllers.ml.feature_pipeline import compute_features
from controllers.price_buffer import MinuteBar, PriceBuffer
from controllers.runtime.v3.types import (
    EquitySnapshot,
    IndicatorSnapshot,
    MarketSnapshot,
    MlSnapshot,
    OrderBookSnapshot,
    PositionSnapshot,
    RegimeSnapshot,
)
from simulation.desk import PaperDesk
from simulation.types import InstrumentId, InstrumentSpec, OrderSide, PaperOrderType

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")
_ONE = Decimal("1")


@dataclass
class MlSignalAdapterConfig:
    # ── Quoting ───────────────────────────────────────────────────────
    base_size_quote: Decimal = Decimal("500")
    max_inventory_pct: Decimal = Decimal("0.15")  # Flatten if inventory > 15% equity
    max_hold_bars: int = 30                        # Flatten after 30 min
    refresh_interval: int = 5                      # Re-quote every 5 bars
    max_levels: int = 1
    leverage: int = 1

    # ── Risk ──────────────────────────────────────────────────────────
    max_daily_loss_pct: Decimal = Decimal("0.02")
    max_drawdown_pct: Decimal = Decimal("0.035")
    max_daily_turnover_x: Decimal = Decimal("15")
    max_trades_per_day: int = 200

    # ── ML ────────────────────────────────────────────────────────────
    direction_high_confidence: float = 0.70
    direction_med_confidence: float = 0.60
    adverse_confidence_threshold: float = 0.60
    regime_min_confidence: float = 0.40
    use_ml_sizing: bool = False

    # ── Feature ───────────────────────────────────────────────────────
    atr_period: int = 14
    feature_warmup_bars: int = 300


class MlSignalAdapter:
    """Market-making adapter driven by ML regime model.

    Each tick:
    1. If inventory too large → flatten via market order
    2. If position held too long → flatten
    3. Cancel stale orders, place fresh two-sided quotes
    4. ML signal controls spread width and whether to skip (adverse veto)
    """

    def __init__(
        self,
        desk: PaperDesk,
        instrument_id: InstrumentId,
        instrument_spec: InstrumentSpec,
        config: MlSignalAdapterConfig | None = None,
    ) -> None:
        self._desk = desk
        self._iid = instrument_id
        self._spec = instrument_spec
        self._cfg = config or MlSignalAdapterConfig()

        ml_cfg = MlSignalConfig(
            direction_high_confidence=self._cfg.direction_high_confidence,
            direction_med_confidence=self._cfg.direction_med_confidence,
            adverse_confidence_threshold=self._cfg.adverse_confidence_threshold,
            regime_min_confidence=self._cfg.regime_min_confidence,
            use_ml_sizing=self._cfg.use_ml_sizing,
            base_size_quote=self._cfg.base_size_quote,
            max_levels=self._cfg.max_levels,
        )
        self._signal_source = MlSignalSource(ml_cfg)
        self._buf = PriceBuffer()

        self._feature_cache: dict[int, dict[str, float]] = {}
        self._features_precomputed = False

        self._regime_name: str = "neutral_low_vol"
        self._last_submitted_count: int = 0
        self._last_candle_ts: int = 0
        self._ticks_since_quote: int = 0
        self._inventory_entry_ts: float = 0.0
        self._inventory_bars: int = 0

        # Daily tracking
        self._current_day: int = -1
        self._daily_equity_open: Decimal = _ZERO
        self._daily_notional: Decimal = _ZERO
        self._daily_trades: int = 0
        self._equity_peak: Decimal = _ZERO

    @property
    def regime_name(self) -> str:
        return self._regime_name

    @property
    def last_submitted_count(self) -> int:
        return self._last_submitted_count

    def set_all_candles(self, all_candles: list[CandleRow]) -> None:
        self._all_candles = all_candles

    def warmup(self, candles: list[CandleRow]) -> int:
        for c in candles:
            self._buf.append_bar(MinuteBar(
                ts_minute=int(c.timestamp_ms // 1000 // 60) * 60,
                open=c.open, high=c.high, low=c.low, close=c.close,
            ))
        all_candles = getattr(self, "_all_candles", None)
        if all_candles and not self._features_precomputed:
            self._precompute_features(all_candles)
        return len(candles)

    def record_fill_notional(self, notional: Decimal) -> None:
        self._daily_notional += notional

    # ------------------------------------------------------------------
    # Main tick
    # ------------------------------------------------------------------

    def tick(
        self,
        now_s: float,
        mid: Decimal,
        book: Any,
        equity_quote: Decimal,
        position_base: Decimal,
        candle: Any = None,
    ) -> dict[str, Any] | None:
        self._last_submitted_count = 0
        cfg = self._cfg

        if candle is not None and candle.timestamp_ms != self._last_candle_ts:
            self._buf.append_bar(MinuteBar(
                ts_minute=int(candle.timestamp_ms // 1000 // 60) * 60,
                open=candle.open, high=candle.high, low=candle.low, close=candle.close,
            ))
            self._last_candle_ts = candle.timestamp_ms

        # Daily reset
        day = int(now_s // 86400)
        if day != self._current_day:
            self._current_day = day
            self._daily_equity_open = equity_quote
            self._daily_notional = _ZERO
            self._daily_trades = 0
        if equity_quote > self._equity_peak:
            self._equity_peak = equity_quote

        if mid <= _ZERO or equity_quote <= _ZERO:
            return None
        if len(self._buf.bars) < cfg.feature_warmup_bars:
            return None

        has_inventory = abs(position_base) >= self._spec.min_quantity
        inventory_notional = abs(position_base) * mid
        inventory_pct = inventory_notional / equity_quote if equity_quote > _ZERO else _ZERO

        # ── Track inventory age ──────────────────────────────────────
        if has_inventory:
            self._inventory_bars += 1
        else:
            self._inventory_bars = 0
            self._inventory_entry_ts = now_s

        # ── Flatten: inventory too large ─────────────────────────────
        if has_inventory and inventory_pct > cfg.max_inventory_pct:
            self._flatten(mid, position_base)
            return {"side": "flatten", "reason": "inventory_limit", "pct": float(inventory_pct)}

        # ── Flatten: held too long ───────────────────────────────────
        if has_inventory and self._inventory_bars > cfg.max_hold_bars:
            self._flatten(mid, position_base)
            return {"side": "flatten", "reason": "time_limit", "bars": self._inventory_bars}

        # ── Daily risk gates ─────────────────────────────────────────
        if self._daily_equity_open > _ZERO:
            daily_loss = (self._daily_equity_open - equity_quote) / self._daily_equity_open
            if daily_loss > cfg.max_daily_loss_pct:
                self._cancel_all_open_orders()
                return {"side": "off", "reason": "daily_loss_limit"}

        if self._equity_peak > _ZERO:
            dd = (self._equity_peak - equity_quote) / self._equity_peak
            if dd > cfg.max_drawdown_pct:
                self._cancel_all_open_orders()
                return {"side": "off", "reason": "drawdown_limit"}

        turnover_x = self._daily_notional / equity_quote if equity_quote > _ZERO else _ZERO
        if turnover_x > cfg.max_daily_turnover_x:
            self._cancel_all_open_orders()
            return {"side": "off", "reason": "turnover_limit"}

        if self._daily_trades >= cfg.max_trades_per_day:
            return {"side": "off", "reason": "max_trades"}

        # ── Re-quote at refresh interval ─────────────────────────────
        self._ticks_since_quote += 1
        if self._ticks_since_quote < cfg.refresh_interval:
            return {"side": "hold", "ticks": self._ticks_since_quote}

        # ── Get ML signal ────────────────────────────────────────────
        features = self._get_features()
        if features is None:
            return {"side": "off", "reason": "features_unavailable"}

        atr = self._buf.atr(cfg.atr_period) or _ZERO
        snapshot = self._build_snapshot(mid, atr, equity_quote, position_base, features)
        signal = self._signal_source.evaluate(snapshot)
        self._regime_name = signal.metadata.get("regime", "neutral_low_vol")

        if signal.family == "no_trade" or signal.direction == "off":
            self._cancel_all_open_orders()
            return {"side": "off", "reason": signal.reason}

        if not signal.levels:
            return {"side": "off", "reason": "no_levels"}

        # ── Place fresh two-sided quotes ─────────────────────────────
        self._cancel_all_open_orders()
        self._ticks_since_quote = 0

        max_notional = equity_quote * cfg.max_inventory_pct
        placed = 0

        for level in signal.levels:
            notional = min(level.size_quote, max_notional)
            qty = notional / mid if mid > _ZERO else _ZERO
            qty = self._spec.quantize_size(qty)
            if qty <= _ZERO:
                continue

            # Skip side that would increase already-large inventory
            if level.side == "buy" and position_base > _ZERO and inventory_pct > cfg.max_inventory_pct * Decimal("0.5"):
                continue
            if level.side == "sell" and position_base < _ZERO and inventory_pct > cfg.max_inventory_pct * Decimal("0.5"):
                continue

            if level.side == "buy":
                price = self._spec.quantize_price(mid * (_ONE - level.spread_pct), "buy")
            else:
                price = self._spec.quantize_price(mid * (_ONE + level.spread_pct), "sell")

            order_side = OrderSide.BUY if level.side == "buy" else OrderSide.SELL
            self._desk.submit_order(
                instrument_id=self._iid,
                side=order_side,
                order_type=PaperOrderType.LIMIT,
                price=price,
                quantity=qty,
                source_bot="ml_signal",
            )
            placed += 1

        self._last_submitted_count = placed
        if placed > 0:
            self._daily_trades += 1

        return {
            "side": signal.direction,
            "orders": placed,
            "regime": self._regime_name,
            "inventory_pct": float(inventory_pct),
        }

    # ------------------------------------------------------------------
    # Flatten / cancel
    # ------------------------------------------------------------------

    def _flatten(self, mid: Decimal, position_base: Decimal) -> None:
        self._cancel_all_open_orders()
        qty = abs(position_base)
        if qty < self._spec.min_quantity:
            return
        close_side = OrderSide.SELL if position_base > _ZERO else OrderSide.BUY
        self._desk.submit_order(
            instrument_id=self._iid,
            side=close_side,
            order_type=PaperOrderType.MARKET,
            price=mid,
            quantity=qty,
            source_bot="ml_signal",
        )
        self._last_submitted_count += 1
        self._inventory_bars = 0

    def _cancel_all_open_orders(self) -> None:
        try:
            engine = self._desk.get_engine(self._iid)
            if engine is None:
                return
            open_ids = [
                oid for oid, order in engine._orders.items()
                if str(order.status) in ("new", "partially_filled")
            ]
            for oid in open_ids:
                self._desk.cancel_order(self._iid, oid)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Features
    # ------------------------------------------------------------------

    def _precompute_features(self, all_candles: list[CandleRow]) -> None:
        import pandas as pd
        logger.info("Pre-computing ML features for %d candles...", len(all_candles))
        df = pd.DataFrame([{
            "timestamp_ms": int(c.timestamp_ms),
            "open": float(c.open), "high": float(c.high),
            "low": float(c.low), "close": float(c.close),
            "volume": float(c.volume),
        } for c in all_candles])
        features_df = compute_features(df)
        for _, row in features_df.iterrows():
            ts = int(row.get("timestamp_ms", 0))
            if ts > 0:
                self._feature_cache[ts] = {
                    col: float(row[col]) if pd.notna(row[col]) else float("nan")
                    for col in features_df.columns if col != "timestamp_ms"
                }
        self._features_precomputed = True
        logger.info("Pre-computed %d feature rows", len(self._feature_cache))

    def _get_features(self) -> dict[str, float] | None:
        if self._features_precomputed:
            return self._feature_cache.get(self._last_candle_ts)
        return None

    def _build_snapshot(self, mid, atr, equity, position_base, features) -> MarketSnapshot:
        pos_pct = (position_base * mid / equity) if equity > _ZERO else _ZERO
        return MarketSnapshot(
            mid=mid,
            ml=MlSnapshot(features=features),
            indicators=IndicatorSnapshot(
                atr={self._cfg.atr_period: atr},
                bars_available=len(self._buf.bars),
            ),
            regime=RegimeSnapshot(name=self._regime_name),
            order_book=OrderBookSnapshot(spread_pct=Decimal("0.001"), imbalance=_ZERO),
            position=PositionSnapshot(
                net_base_pct=pos_pct, gross_base_pct=abs(pos_pct), base_amount=position_base,
            ),
            equity=EquitySnapshot(
                equity_quote=equity,
                daily_turnover_x=self._daily_notional / equity if equity > _ZERO else _ZERO,
            ),
        )
