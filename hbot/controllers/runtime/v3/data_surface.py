"""KernelDataSurface — typed read-only facade over SharedRuntimeKernel.

The kernel still computes everything; this class provides a clean API
boundary so that strategy code never touches private attributes.
Snapshots are assembled once per tick and cached.
"""

from __future__ import annotations

import logging
import time
from decimal import Decimal
from typing import Any

from controllers.runtime.v3.types import (
    EquitySnapshot,
    FundingSnapshot,
    IndicatorSnapshot,
    MarketSnapshot,
    MlSnapshot,
    OrderBookSnapshot,
    PositionSnapshot,
    RegimeSnapshot,
    TradeFlowSnapshot,
)

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")


class KernelDataSurface:
    """Typed read-only facade over the existing SharedRuntimeKernel.

    Usage::

        surface = KernelDataSurface(kernel)
        snap = surface.snapshot()  # assembled once per tick
        snap.mid                   # Decimal
        snap.indicators.ema[20]    # Decimal
        snap.regime.name           # str
    """

    def __init__(self, kernel: Any) -> None:
        self._kernel = kernel
        self._cached_snapshot: MarketSnapshot | None = None
        self._cached_tick_id: int = -1

    # ── Public API ────────────────────────────────────────────────────

    def snapshot(self) -> MarketSnapshot:
        """Assemble a full MarketSnapshot from kernel state.

        Cached for the duration of one tick (identified by _tick_count).
        """
        tick_id = getattr(self._kernel, "_tick_count", 0)
        if self._cached_snapshot is not None and self._cached_tick_id == tick_id:
            return self._cached_snapshot

        snap = self._assemble()
        self._cached_snapshot = snap
        self._cached_tick_id = tick_id
        return snap

    def invalidate(self) -> None:
        """Force re-computation on next snapshot() call."""
        self._cached_snapshot = None
        self._cached_tick_id = -1

    @property
    def price_buffer(self) -> Any:
        """Direct access to PriceBuffer for warmup / seeding."""
        return self._kernel._price_buffer

    @property
    def connector_info(self) -> dict[str, Any]:
        """Exchange metadata."""
        cfg = self._kernel.config
        return {
            "connector_name": getattr(cfg, "connector_name", ""),
            "trading_pair": getattr(cfg, "trading_pair", ""),
            "is_perp": getattr(self._kernel, "_is_perp", False),
            "leverage": getattr(cfg, "leverage", 1),
        }

    # ── Snapshot assembly ─────────────────────────────────────────────

    def _assemble(self) -> MarketSnapshot:
        k = self._kernel
        cfg = k.config
        is_perp = getattr(k, "_is_perp", False)

        mid = self._safe_decimal(k, "_last_mid", _ZERO)
        if mid == _ZERO:
            bid = self._safe_decimal(k, "_last_book_bid", _ZERO)
            ask = self._safe_decimal(k, "_last_book_ask", _ZERO)
            if bid > _ZERO and ask > _ZERO:
                mid = (bid + ask) / 2

        return MarketSnapshot(
            timestamp_ms=int(time.time() * 1000),
            mid=mid,
            indicators=self._build_indicators(k),
            order_book=self._build_order_book(k),
            position=self._build_position(k, cfg, is_perp),
            equity=self._build_equity(k),
            regime=self._build_regime(k),
            trade_flow=self._build_trade_flow(k),
            funding=self._build_funding(k) if is_perp else None,
            ml=self._build_ml(k),
            config=self._extract_config(cfg),
        )

    # ── Sub-snapshot builders ─────────────────────────────────────────

    def _build_indicators(self, k: Any) -> IndicatorSnapshot:
        pb = getattr(k, "_price_buffer", None)
        if pb is None:
            return IndicatorSnapshot()

        ema_periods = [9, 20, 50, 100, 200]
        atr_periods = [14]
        rsi_periods = [14]
        adx_periods = [14]

        ema = {}
        for p in ema_periods:
            try:
                val = pb.ema(p)
                if val is not None:
                    ema[p] = Decimal(str(val)) if not isinstance(val, Decimal) else val
            except Exception:
                pass

        atr = {}
        for p in atr_periods:
            try:
                val = pb.atr(p)
                if val is not None:
                    atr[p] = Decimal(str(val)) if not isinstance(val, Decimal) else val
            except Exception:
                pass

        rsi = {}
        for p in rsi_periods:
            try:
                val = pb.rsi(p)
                if val is not None:
                    rsi[p] = Decimal(str(val)) if not isinstance(val, Decimal) else val
            except Exception:
                pass

        adx = {}
        for p in adx_periods:
            try:
                val = pb.adx(p)
                if val is not None:
                    adx[p] = Decimal(str(val)) if not isinstance(val, Decimal) else val
            except Exception:
                pass

        band_pct = self._safe_decimal(k, "_band_pct_ewma", _ZERO)
        bars = 0
        raw_bars = getattr(pb, "bars_available", None)
        if isinstance(raw_bars, int):
            bars = raw_bars
        elif raw_bars is None:
            try:
                bar_list = getattr(pb, "bars", None)
                if bar_list is not None and hasattr(bar_list, "__len__"):
                    bars = len(bar_list)
            except Exception:
                pass
        else:
            try:
                bar_list = getattr(pb, "bars", None)
                if bar_list is not None and hasattr(bar_list, "__len__"):
                    bars = len(bar_list)
            except Exception:
                pass

        return IndicatorSnapshot(
            ema=ema,
            atr=atr,
            rsi=rsi,
            adx=adx,
            band_pct=band_pct,
            bars_available=bars,
        )

    def _build_order_book(self, k: Any) -> OrderBookSnapshot:
        bid = self._safe_decimal(k, "_last_book_bid", _ZERO)
        ask = self._safe_decimal(k, "_last_book_ask", _ZERO)
        mid = (bid + ask) / 2 if bid > _ZERO and ask > _ZERO else _ZERO
        spread_pct = (ask - bid) / mid if mid > _ZERO else _ZERO

        return OrderBookSnapshot(
            best_bid=bid,
            best_ask=ask,
            spread_pct=spread_pct,
            best_bid_size=self._safe_decimal(k, "_last_book_bid_size", _ZERO),
            best_ask_size=self._safe_decimal(k, "_last_book_ask_size", _ZERO),
            imbalance=self._safe_decimal(k, "_ob_imbalance", _ZERO),
            stale=bool(getattr(k, "_book_stale_since_ts", 0) > 0),
        )

    def _build_position(self, k: Any, cfg: Any, is_perp: bool) -> PositionSnapshot:
        return PositionSnapshot(
            base_amount=self._safe_decimal(k, "_position_base", _ZERO),
            quote_balance=_ZERO,  # Derived from equity - base*mid in desk
            net_base_pct=self._safe_decimal(k, "_base_pct_net", _ZERO),
            gross_base_pct=self._safe_decimal(k, "_base_pct_gross", _ZERO),
            avg_entry_price=self._safe_decimal(k, "_avg_entry_price", _ZERO),
            is_perp=is_perp,
            leverage=getattr(cfg, "leverage", 1),
        )

    def _build_equity(self, k: Any) -> EquitySnapshot:
        equity = self._safe_decimal(k, "_equity_quote", _ZERO)
        daily_open = self._safe_decimal(k, "_daily_equity_open", _ZERO)
        daily_peak = self._safe_decimal(k, "_daily_equity_peak", _ZERO)
        daily_pnl = equity - daily_open if daily_open > _ZERO else _ZERO

        # Daily loss and drawdown from kernel's risk metrics
        daily_loss_pct = _ZERO
        drawdown_pct = _ZERO
        if daily_open > _ZERO:
            daily_loss_pct = max(_ZERO, (daily_open - equity) / daily_open)
        if daily_peak > _ZERO:
            drawdown_pct = max(_ZERO, (daily_peak - equity) / daily_peak)

        turnover = self._safe_decimal(k, "_traded_notional_today", _ZERO)
        turnover_x = turnover / equity if equity > _ZERO else _ZERO

        return EquitySnapshot(
            equity_quote=equity,
            daily_open_equity=daily_open,
            daily_peak_equity=daily_peak,
            daily_pnl_quote=daily_pnl,
            daily_loss_pct=daily_loss_pct,
            max_drawdown_pct=drawdown_pct,
            daily_turnover_x=turnover_x,
        )

    def _build_regime(self, k: Any) -> RegimeSnapshot:
        resolved = getattr(k, "_resolved_specs", {})
        active = getattr(k, "_active_regime", "neutral_low_vol")
        spec = resolved.get(active)

        if spec is None:
            return RegimeSnapshot(name=active)

        return RegimeSnapshot(
            name=active,
            band_pct=self._safe_decimal(k, "_band_pct_ewma", _ZERO),
            ema_value=self._safe_decimal(k, "_regime_ema_value", _ZERO),
            atr_value=self._safe_decimal(k, "_regime_atr_value", _ZERO),
            spread_min=getattr(spec, "spread_min", _ZERO),
            spread_max=getattr(spec, "spread_max", _ZERO),
            levels_min=getattr(spec, "levels_min", 1),
            levels_max=getattr(spec, "levels_max", 3),
            target_base_pct=getattr(spec, "target_base_pct", _ZERO),
            one_sided=getattr(spec, "one_sided", "off"),
            fill_factor=getattr(spec, "fill_factor", Decimal("0.40")),
            refresh_s=getattr(spec, "refresh_s", 30),
        )

    def _build_trade_flow(self, k: Any) -> TradeFlowSnapshot | None:
        """Build trade flow snapshot if trade data is available."""
        # Trade flow is populated by bot controllers (bot6, bot7) that
        # maintain their own state dicts.  At the kernel level we only
        # have _ob_imbalance.  Return a minimal snapshot.
        return TradeFlowSnapshot(
            cvd=_ZERO,
            delta_volume=self._safe_decimal(k, "_ob_imbalance", _ZERO),
        ) if hasattr(k, "_ob_imbalance") else None

    def _build_funding(self, k: Any) -> FundingSnapshot:
        return FundingSnapshot(
            funding_rate=self._safe_decimal(k, "_funding_rate", _ZERO),
            mark_price=self._safe_decimal(k, "_mark_price", _ZERO),
        )

    def _build_ml(self, k: Any) -> MlSnapshot | None:
        hint = getattr(k, "_ml_direction_hint", "")
        confidence = getattr(k, "_ml_direction_hint_confidence", 0.0)
        if not hint and confidence == 0.0:
            return None
        return MlSnapshot(
            confidence=Decimal(str(confidence)),
            regime_override=getattr(k, "_external_regime_override", "") or "",
            model_version=getattr(k, "_last_external_model_version", ""),
        )

    def _extract_config(self, cfg: Any) -> dict[str, Any]:
        """Extract strategy-relevant config as a plain dict."""
        keys = [
            "connector_name", "trading_pair", "total_amount_quote",
            "buy_spreads", "sell_spreads", "executor_refresh_time",
            "stop_loss", "take_profit", "time_limit", "leverage",
            "min_net_edge_bps", "edge_resume_bps",
            "max_daily_loss_pct_hard", "max_drawdown_pct_hard",
            "max_daily_turnover_x_hard",
        ]
        result = {}
        for key in keys:
            val = getattr(cfg, key, None)
            if val is not None:
                result[key] = val
        return result

    # ── Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _safe_decimal(obj: Any, attr: str, default: Decimal) -> Decimal:
        val = getattr(obj, attr, None)
        if val is None:
            return default
        if isinstance(val, Decimal):
            return val
        try:
            return Decimal(str(val))
        except Exception:
            return default


__all__ = ["KernelDataSurface"]
