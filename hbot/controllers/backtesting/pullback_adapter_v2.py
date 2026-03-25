"""Backtest adapter v2 for bot7 pullback strategy — quant redesign.

Fixes the fundamental signal geometry problems in v1:
- Pullback zone now correctly detects price dipping BELOW BB basis in uptrends
- Replaces 8-gate AND chain with composite scoring (any 3 of 5 confirmations)
- Adds RSI divergence detection for higher-quality pullback timing
- Volatility-adaptive sizing via inverse ATR scaling
- Multi-stage exit: partial at 1R, trailing from 1.5R, hard stop at -1R
- No regime gate requirement — trend is inferred from indicators, not regime label
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from controllers.backtesting.types import CandleRow
from controllers.core import RegimeSpec
from simulation.desk import PaperDesk
from simulation.types import (
    InstrumentId,
    InstrumentSpec,
    OrderSide,
    PaperOrderType,
)
from controllers.price_buffer import MinuteBar, PriceBuffer
from controllers.regime_detector import RegimeDetector

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")
_ONE = Decimal("1")
_TWO = Decimal("2")


_RESOLUTION_TO_MINUTES: dict[str, int] = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}


@dataclass
class PullbackV2Config:
    # Indicator periods
    bb_period: int = 20
    bb_stddev: Decimal = Decimal("2.0")
    rsi_period: int = 14
    adx_period: int = 14
    atr_period: int = 14
    sma_fast: int = 20
    sma_slow: int = 50
    indicator_resolution: str = "1m"

    # Composite scoring — entry fires when score >= threshold
    entry_score_threshold: Decimal = Decimal("0.55")

    # Component weights in [0, 1] — sum to ~1.0
    w_pullback_zone: Decimal = Decimal("0.30")
    w_trend_slope: Decimal = Decimal("0.25")
    w_rsi_zone: Decimal = Decimal("0.20")
    w_adx_strength: Decimal = Decimal("0.15")
    w_rsi_divergence: Decimal = Decimal("0.10")

    # Pullback zone: how far below BB basis counts as a dip (longs)
    pullback_depth_min_pct: Decimal = Decimal("0.001")
    pullback_depth_max_pct: Decimal = Decimal("0.015")

    # RSI: oversold/overbought zones for pullback entries
    rsi_long_max: Decimal = Decimal("45")
    rsi_short_min: Decimal = Decimal("55")

    # ADX: trend present above this
    adx_trend_min: Decimal = Decimal("18")

    # Trend slope: SMA20 rising/falling rate
    min_slope_pct: Decimal = Decimal("0.0001")

    # RSI divergence lookback
    divergence_lookback: int = 30

    # Position sizing — Kelly-inspired fraction of equity
    base_risk_pct: Decimal = Decimal("0.05")
    vol_scale_atr_target: Decimal = Decimal("0.005")

    # Exit management
    sl_atr_mult: Decimal = Decimal("1.2")
    tp_atr_mult: Decimal = Decimal("2.5")
    partial_take_at_r: Decimal = Decimal("1.0")
    partial_take_pct: Decimal = Decimal("0.50")
    trail_activate_r: Decimal = Decimal("1.5")
    trail_offset_atr: Decimal = Decimal("0.5")

    # Time stops
    max_hold_minutes: int = 360

    # Cooldown (seconds)
    signal_cooldown_s: int = 60

    # Risk limits
    max_daily_loss_pct: Decimal = Decimal("0.02")
    max_drawdown_pct: Decimal = Decimal("0.035")
    max_concurrent_positions: int = 1

    # Session filter
    session_filter_enabled: bool = True
    quality_hours_utc: str = "1-4,8-16,20-23"
    off_session_size_mult: Decimal = Decimal("0.5")
    session_flatten_enabled: bool = False

    # Warmup
    min_warmup_bars: int = 60

    # Regime reversal exit
    regime_reversal_exit: bool = True


def _default_regime_specs() -> dict[str, RegimeSpec]:
    return {
        "neutral_low_vol": RegimeSpec(
            spread_min=Decimal("0.0020"), spread_max=Decimal("0.0040"),
            levels_min=2, levels_max=4, refresh_s=10,
            target_base_pct=Decimal("0.50"),
            quote_size_pct_min=Decimal("0.02"), quote_size_pct_max=Decimal("0.04"),
            one_sided="off",
        ),
        "neutral_high_vol": RegimeSpec(
            spread_min=Decimal("0.0040"), spread_max=Decimal("0.0080"),
            levels_min=1, levels_max=3, refresh_s=5,
            target_base_pct=Decimal("0.50"),
            quote_size_pct_min=Decimal("0.01"), quote_size_pct_max=Decimal("0.03"),
            one_sided="off",
        ),
        "up": RegimeSpec(
            spread_min=Decimal("0.0025"), spread_max=Decimal("0.0050"),
            levels_min=2, levels_max=3, refresh_s=10,
            target_base_pct=Decimal("0.60"),
            quote_size_pct_min=Decimal("0.02"), quote_size_pct_max=Decimal("0.04"),
            one_sided="off",
        ),
        "down": RegimeSpec(
            spread_min=Decimal("0.0025"), spread_max=Decimal("0.0050"),
            levels_min=2, levels_max=3, refresh_s=10,
            target_base_pct=Decimal("0.40"),
            quote_size_pct_min=Decimal("0.02"), quote_size_pct_max=Decimal("0.04"),
            one_sided="off",
        ),
        "high_vol_shock": RegimeSpec(
            spread_min=Decimal("0.0100"), spread_max=Decimal("0.0200"),
            levels_min=1, levels_max=2, refresh_s=3,
            target_base_pct=Decimal("0.50"),
            quote_size_pct_min=Decimal("0.005"), quote_size_pct_max=Decimal("0.01"),
            one_sided="off",
        ),
    }


@dataclass
class _PositionState:
    side: str = "off"
    entry_price: Decimal = _ZERO
    entry_ts: float = 0.0
    sl_price: Decimal = _ZERO
    tp_price: Decimal = _ZERO
    atr_at_entry: Decimal = _ZERO
    partial_taken: bool = False
    trail_active: bool = False
    trail_hwm: Decimal = _ZERO
    trail_lwm: Decimal = Decimal("999999999")


class BacktestPullbackAdapterV2:
    """Quant-redesigned pullback adapter with composite scoring."""

    def __init__(
        self,
        desk: PaperDesk,
        instrument_id: InstrumentId,
        instrument_spec: InstrumentSpec,
        config: PullbackV2Config | None = None,
    ) -> None:
        self._desk = desk
        self._instrument_id = instrument_id
        self._instrument_spec = instrument_spec
        self._cfg = config or PullbackV2Config()

        _res_min = _RESOLUTION_TO_MINUTES.get(self._cfg.indicator_resolution, 1)
        self._price_buffer = PriceBuffer(
            sample_interval_sec=60,
            max_minutes=2880,
            resolution_minutes=_res_min,
        )
        self._regime_detector = RegimeDetector(
            specs=_default_regime_specs(),
            high_vol_band_pct=Decimal("0.0080"),
            shock_drift_30s_pct=Decimal("0.0050"),
        )

        self._regime_name: str = "neutral_low_vol"
        self._last_submitted_count: int = 0
        self._tick_count: int = 0

        self._daily_equity_open: Decimal = _ZERO
        self._daily_equity_peak: Decimal = _ZERO
        self._current_day: int = -1

        self._last_exit_ts: float = 0.0
        self._pos = _PositionState()
        self._active_orders: bool = False
        self._orders_submitted_at: float = 0.0

        self._rsi_history: list[Decimal] = []
        self._close_history: list[Decimal] = []
        self._last_candle_ts: int = 0

    @property
    def regime_name(self) -> str:
        return self._regime_name

    @property
    def last_submitted_count(self) -> int:
        return self._last_submitted_count

    def warmup(self, candles: list[CandleRow]) -> int:
        bars = [
            MinuteBar(
                ts_minute=int(c.timestamp_ms // 1000 // 60) * 60,
                open=c.open, high=c.high, low=c.low, close=c.close,
            )
            for c in candles
        ]
        if bars:
            self._price_buffer.seed_bars(bars, reset=True)
        for c in candles:
            self._close_history.append(c.close)
        return len(bars)

    def tick(
        self,
        now_s: float,
        mid: Decimal,
        book: Any,
        equity_quote: Decimal,
        position_base: Decimal,
        candle: Any = None,
    ) -> Any:
        self._tick_count += 1
        cfg = self._cfg

        if candle is not None and candle.timestamp_ms != self._last_candle_ts:
            bar = MinuteBar(
                ts_minute=int(candle.timestamp_ms // 1000 // 60) * 60,
                open=candle.open, high=candle.high,
                low=candle.low, close=candle.close,
            )
            self._price_buffer.append_bar(bar)
            self._close_history.append(candle.close)
            self._last_candle_ts = candle.timestamp_ms
        elif mid > _ZERO:
            self._price_buffer.add_sample(now_s, mid)

        day = int(now_s // 86400)
        if day != self._current_day:
            self._current_day = day
            self._daily_equity_open = equity_quote
            self._daily_equity_peak = equity_quote
        self._daily_equity_peak = max(self._daily_equity_peak, equity_quote)

        if not self._price_buffer.ready(cfg.min_warmup_bars):
            return None
        if mid <= _ZERO or equity_quote <= _ZERO:
            return None

        bands = self._price_buffer.bollinger_bands(cfg.bb_period, cfg.bb_stddev)
        rsi_val = self._price_buffer.rsi(cfg.rsi_period)
        adx_val = self._price_buffer.adx(cfg.adx_period)
        atr_val = self._price_buffer.atr(cfg.atr_period)
        sma_fast = self._price_buffer.sma(cfg.sma_fast)
        sma_slow = self._price_buffer.sma(cfg.sma_slow)

        if bands is None or rsi_val is None or adx_val is None or atr_val is None:
            return None

        bb_lower, bb_basis, bb_upper = bands

        if not (candle is not None and candle.timestamp_ms == self._last_candle_ts):
            self._close_history.append(mid)
        if len(self._close_history) > 200:
            self._close_history = self._close_history[-200:]
        self._rsi_history.append(rsi_val)
        if len(self._rsi_history) > 200:
            self._rsi_history = self._rsi_history[-200:]

        ema_val = self._price_buffer.ema(cfg.sma_slow) or mid
        band_pct = self._price_buffer.band_pct(cfg.atr_period) or _ZERO
        drift = self._price_buffer.adverse_drift_30s(now_s)
        regime_name, _ = self._regime_detector.detect(
            mid=mid, ema_val=ema_val, band_pct=band_pct, drift=drift,
            regime_source_tag="backtest_v2",
        )
        self._regime_name = regime_name

        has_position = abs(position_base) > Decimal("1e-8")
        session_active = self._session_active(now_s)

        if not session_active and self._active_orders:
            self._cancel_all()
            self._active_orders = False

        if (
            has_position
            and cfg.session_filter_enabled
            and cfg.session_flatten_enabled
            and not session_active
        ):
            self._close_position(mid, position_base, "session_end", now_s)
            return {"side": "exit", "regime": regime_name, "reason": "session_end"}

        # ── Manage existing position ──
        if has_position and self._pos.side != "off":
            action = self._manage_position(mid, position_base, atr_val, now_s, regime_name)
            if action:
                return action

        # ── Risk gates (portfolio-level) ──
        daily_loss = _ZERO
        if self._daily_equity_open > _ZERO:
            daily_loss = (self._daily_equity_open - equity_quote) / self._daily_equity_open
        drawdown = _ZERO
        if self._daily_equity_peak > _ZERO:
            drawdown = (self._daily_equity_peak - equity_quote) / self._daily_equity_peak

        if daily_loss > cfg.max_daily_loss_pct or drawdown > cfg.max_drawdown_pct:
            if has_position:
                self._close_position(mid, position_base, "risk_limit", now_s)
            return {"side": "off", "regime": regime_name, "reason": "risk_limit"}

        # ── Don't open new position if already in one ──
        if has_position:
            self._last_submitted_count = 0
            return {"side": self._pos.side, "regime": regime_name, "holding": True}

        # ── Cooldown (only after a trade exit, not after order submission) ──
        if self._last_exit_ts > 0 and (now_s - self._last_exit_ts) < cfg.signal_cooldown_s:
            self._last_submitted_count = 0
            return {"side": "off", "regime": regime_name, "cooldown": True}

        # ── Cancel stale orders and re-evaluate ──
        if self._active_orders and (now_s - self._orders_submitted_at) > 120:
            self._cancel_all()
            self._active_orders = False

        # ── Compute composite entry score ──
        long_score, short_score, diagnostics = self._compute_entry_scores(
            mid, bb_lower, bb_basis, bb_upper, rsi_val, adx_val, atr_val,
            sma_fast, sma_slow,
        )

        side = "off"
        score = _ZERO
        if long_score >= cfg.entry_score_threshold and long_score > short_score:
            side = "buy"
            score = long_score
        elif short_score >= cfg.entry_score_threshold and short_score > long_score:
            side = "sell"
            score = short_score

        # Session filter scales size, doesn't block
        session_mult = self._session_multiplier(now_s)

        if side == "off":
            if self._active_orders:
                self._cancel_all()
                self._active_orders = False
            self._last_submitted_count = 0
            return {"side": "off", "regime": regime_name, **diagnostics}

        # ── Submit entry order ──
        self._cancel_all()

        vol_scale = self._vol_scale(atr_val, mid)
        size_mult = session_mult * vol_scale * score
        quote_amount = equity_quote * cfg.base_risk_pct * size_mult

        # Place order at mid to ensure fillability in synthetic book
        # The scoring threshold already filters signal quality
        price = self._instrument_spec.quantize_price(mid, side)

        base_qty = quote_amount / price if price > _ZERO else _ZERO
        quantity = self._instrument_spec.quantize_size(base_qty)

        submitted = 0
        if quantity > _ZERO and price > _ZERO:
            self._desk.submit_order(
                instrument_id=self._instrument_id,
                side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
                order_type=PaperOrderType.LIMIT,
                price=price,
                quantity=quantity,
                source_bot="backtest_pullback",
            )
            submitted = 1
            self._active_orders = True
            self._orders_submitted_at = now_s

            sl_dist = atr_val * cfg.sl_atr_mult
            tp_dist = atr_val * cfg.tp_atr_mult
            if side == "buy":
                sl_price = price - sl_dist
                tp_price = price + tp_dist
            else:
                sl_price = price + sl_dist
                tp_price = price - tp_dist

            self._pos = _PositionState(
                side=side,
                entry_price=price,
                entry_ts=now_s,
                sl_price=sl_price,
                tp_price=tp_price,
                atr_at_entry=atr_val,
            )

        self._last_submitted_count = submitted
        return {
            "side": side, "regime": regime_name, "score": float(score),
            **diagnostics,
        }

    def record_fill_notional(self, notional: Decimal) -> None:
        pass

    # ── Composite scoring engine ──

    def _compute_entry_scores(
        self,
        mid: Decimal,
        bb_lower: Decimal,
        bb_basis: Decimal,
        bb_upper: Decimal,
        rsi: Decimal,
        adx: Decimal,
        atr: Decimal,
        sma_fast: Decimal | None,
        sma_slow: Decimal | None,
    ) -> tuple[Decimal, Decimal, dict]:
        """Return (long_score, short_score, diagnostics).

        Each component contributes a weighted fraction.  No hard gates —
        weak signals still contribute partial score.
        """
        cfg = self._cfg
        diag: dict[str, Any] = {}

        # ── 1. Pullback zone (0.30 weight) ──
        # Trend-continuation pullback:
        #   Long: price dips below BB basis in an uptrend (buying the dip)
        #   Short: price rallies above BB basis in a downtrend (selling the rip)
        # The bell curve peaks at mid-depth and decays at extremes
        long_zone = _ZERO
        short_zone = _ZERO
        if bb_basis > _ZERO and mid > _ZERO:
            dip_pct = (bb_basis - mid) / bb_basis
            if dip_pct >= cfg.pullback_depth_min_pct:
                depth_range = cfg.pullback_depth_max_pct - cfg.pullback_depth_min_pct
                if depth_range > _ZERO:
                    normalized = min(_ONE, (dip_pct - cfg.pullback_depth_min_pct) / depth_range)
                    bell = Decimal("4") * normalized * (_ONE - normalized)
                    long_zone = bell
                else:
                    long_zone = _ONE

            rip_pct = (mid - bb_basis) / bb_basis
            if rip_pct >= cfg.pullback_depth_min_pct:
                depth_range = cfg.pullback_depth_max_pct - cfg.pullback_depth_min_pct
                if depth_range > _ZERO:
                    normalized = min(_ONE, (rip_pct - cfg.pullback_depth_min_pct) / depth_range)
                    bell = Decimal("4") * normalized * (_ONE - normalized)
                    short_zone = bell
                else:
                    short_zone = _ONE

        diag["pb_long"] = float(long_zone)
        diag["pb_short"] = float(short_zone)

        # ── 2. Trend slope (0.25 weight) ──
        long_slope = _ZERO
        short_slope = _ZERO
        if sma_fast is not None and sma_slow is not None and sma_slow > _ZERO:
            slope_pct = (sma_fast - sma_slow) / sma_slow
            if slope_pct > cfg.min_slope_pct:
                long_slope = min(_ONE, slope_pct / (cfg.min_slope_pct * Decimal("10")))
            if slope_pct < -cfg.min_slope_pct:
                short_slope = min(_ONE, abs(slope_pct) / (cfg.min_slope_pct * Decimal("10")))

        diag["slope_long"] = float(long_slope)
        diag["slope_short"] = float(short_slope)

        # ── 3. RSI zone (0.20 weight) ──
        long_rsi = _ZERO
        short_rsi = _ZERO
        if rsi <= cfg.rsi_long_max:
            long_rsi = min(_ONE, (cfg.rsi_long_max - rsi) / Decimal("15"))
        if rsi >= cfg.rsi_short_min:
            short_rsi = min(_ONE, (rsi - cfg.rsi_short_min) / Decimal("15"))

        diag["rsi_long"] = float(long_rsi)
        diag["rsi_short"] = float(short_rsi)

        # ── 4. ADX strength (0.15 weight) ──
        adx_score = _ZERO
        if adx >= cfg.adx_trend_min:
            adx_score = min(_ONE, (adx - cfg.adx_trend_min) / Decimal("25"))
        diag["adx_score"] = float(adx_score)

        # ── 5. RSI divergence (0.10 weight) ──
        long_div, short_div = self._detect_rsi_divergence()
        diag["div_long"] = float(long_div)
        diag["div_short"] = float(short_div)

        # ── Composite ──
        w = cfg
        long_score = (
            w.w_pullback_zone * long_zone
            + w.w_trend_slope * long_slope
            + w.w_rsi_zone * long_rsi
            + w.w_adx_strength * adx_score
            + w.w_rsi_divergence * long_div
        )
        short_score = (
            w.w_pullback_zone * short_zone
            + w.w_trend_slope * short_slope
            + w.w_rsi_zone * short_rsi
            + w.w_adx_strength * adx_score
            + w.w_rsi_divergence * short_div
        )
        diag["long_score"] = float(long_score)
        diag["short_score"] = float(short_score)

        return long_score, short_score, diag

    def _detect_rsi_divergence(self) -> tuple[Decimal, Decimal]:
        """Detect bullish/bearish RSI divergence.

        Bullish: price makes lower low but RSI makes higher low.
        Bearish: price makes higher high but RSI makes lower high.
        """
        n = self._cfg.divergence_lookback
        if len(self._close_history) < n or len(self._rsi_history) < n:
            return _ZERO, _ZERO

        prices = self._close_history[-n:]
        rsis = self._rsi_history[-n:]
        half = n // 2

        price_first_half_low = min(prices[:half])
        price_second_half_low = min(prices[half:])
        rsi_first_half_low = min(rsis[:half])
        rsi_second_half_low = min(rsis[half:])

        bullish = _ZERO
        if price_second_half_low < price_first_half_low and rsi_second_half_low > rsi_first_half_low:
            bullish = _ONE

        price_first_half_high = max(prices[:half])
        price_second_half_high = max(prices[half:])
        rsi_first_half_high = max(rsis[:half])
        rsi_second_half_high = max(rsis[half:])

        bearish = _ZERO
        if price_second_half_high > price_first_half_high and rsi_second_half_high < rsi_first_half_high:
            bearish = _ONE

        return bullish, bearish

    # ── Position management ──

    def _manage_position(
        self,
        mid: Decimal,
        position_base: Decimal,
        atr: Decimal,
        now_s: float,
        regime_name: str,
    ) -> dict | None:
        pos = self._pos
        cfg = self._cfg

        if pos.entry_price <= _ZERO:
            return None

        if pos.side == "buy":
            pnl_pct = (mid - pos.entry_price) / pos.entry_price
        else:
            pnl_pct = (pos.entry_price - mid) / pos.entry_price

        r_multiple = _ZERO
        if pos.atr_at_entry > _ZERO:
            risk_dist = pos.atr_at_entry * cfg.sl_atr_mult
            r_multiple = (mid - pos.entry_price) / risk_dist if pos.side == "buy" else (pos.entry_price - mid) / risk_dist

        # Hard stop
        hit_sl = (
            (pos.side == "buy" and mid <= pos.sl_price)
            or (pos.side == "sell" and mid >= pos.sl_price)
        )
        if hit_sl:
            self._close_position(mid, position_base, "hard_sl", now_s)
            return {"side": "exit", "regime": regime_name, "reason": "hard_sl", "pnl_pct": float(pnl_pct)}

        # Max hold time
        hold_minutes = (now_s - pos.entry_ts) / 60
        if hold_minutes > cfg.max_hold_minutes:
            self._close_position(mid, position_base, "max_hold", now_s)
            return {"side": "exit", "regime": regime_name, "reason": "max_hold", "pnl_pct": float(pnl_pct)}

        # Regime reversal — only exit after a sustained reversal (not on the first check)
        # A short in an uptrend IS the pullback thesis (fading the rip), so we give it time
        if cfg.regime_reversal_exit and hold_minutes > 30:
            if pos.side == "buy" and regime_name == "down":
                self._close_position(mid, position_base, "regime_reversal", now_s)
                return {"side": "exit", "regime": regime_name, "reason": "regime_reversal"}
            if pos.side == "sell" and regime_name == "up":
                self._close_position(mid, position_base, "regime_reversal", now_s)
                return {"side": "exit", "regime": regime_name, "reason": "regime_reversal"}

        # Partial take at 1R
        if not pos.partial_taken and r_multiple >= cfg.partial_take_at_r:
            partial_qty = abs(position_base) * cfg.partial_take_pct
            close_side = OrderSide.SELL if pos.side == "buy" else OrderSide.BUY
            qty = self._instrument_spec.quantize_size(partial_qty)
            if qty > _ZERO:
                self._desk.submit_order(
                    instrument_id=self._instrument_id,
                    side=close_side,
                    order_type=PaperOrderType.MARKET,
                    price=mid,
                    quantity=qty,
                    source_bot="backtest_pullback_partial",
                )
            pos.partial_taken = True
            # Move stop to breakeven after partial
            pos.sl_price = pos.entry_price

        # Trailing stop activation
        if not pos.trail_active and r_multiple >= cfg.trail_activate_r:
            pos.trail_active = True
            if pos.side == "buy":
                pos.trail_hwm = mid
            else:
                pos.trail_lwm = mid

        if pos.trail_active:
            trail_dist = atr * cfg.trail_offset_atr
            if pos.side == "buy":
                if mid > pos.trail_hwm:
                    pos.trail_hwm = mid
                trail_stop = pos.trail_hwm - trail_dist
                if mid <= trail_stop:
                    self._close_position(mid, position_base, "trail_stop", now_s)
                    return {"side": "exit", "regime": regime_name, "reason": "trail_stop", "pnl_pct": float(pnl_pct)}
            else:
                if mid < pos.trail_lwm:
                    pos.trail_lwm = mid
                trail_stop = pos.trail_lwm + trail_dist
                if mid >= trail_stop:
                    self._close_position(mid, position_base, "trail_stop", now_s)
                    return {"side": "exit", "regime": regime_name, "reason": "trail_stop", "pnl_pct": float(pnl_pct)}

        # Take profit at TP price
        hit_tp = (
            (pos.side == "buy" and mid >= pos.tp_price)
            or (pos.side == "sell" and mid <= pos.tp_price)
        )
        if hit_tp:
            self._close_position(mid, position_base, "take_profit", now_s)
            return {"side": "exit", "regime": regime_name, "reason": "take_profit", "pnl_pct": float(pnl_pct)}

        return None

    def _close_position(self, mid: Decimal, position_base: Decimal, reason: str, now_s: float = 0.0) -> None:
        close_qty = abs(position_base)
        if close_qty <= _ZERO:
            return
        self._cancel_all()
        close_side = OrderSide.SELL if position_base > _ZERO else OrderSide.BUY
        qty = self._instrument_spec.quantize_size(close_qty)
        if qty > _ZERO:
            self._desk.submit_order(
                instrument_id=self._instrument_id,
                side=close_side,
                order_type=PaperOrderType.MARKET,
                price=mid,
                quantity=qty,
                source_bot="backtest_pullback_exit",
            )
        self._last_exit_ts = now_s
        self._pos = _PositionState()
        self._active_orders = False

    def _cancel_all(self) -> None:
        try:
            self._desk.cancel_all(self._instrument_id)
        except Exception:
            pass  # Justification: best-effort teardown during simulation — desk may already be closed

    def _vol_scale(self, atr: Decimal, mid: Decimal) -> Decimal:
        """Inverse volatility scaling: trade smaller when vol is high."""
        if mid <= _ZERO or atr <= _ZERO:
            return _ONE
        atr_pct = atr / mid
        target = self._cfg.vol_scale_atr_target
        if atr_pct <= _ZERO:
            return _ONE
        raw = target / atr_pct
        return max(Decimal("0.3"), min(_TWO, raw))

    def _session_active(self, now_s: float) -> bool:
        if not self._cfg.session_filter_enabled:
            return True
        import datetime as _dt
        utc_hour = _dt.datetime.fromtimestamp(now_s, tz=_dt.UTC).hour
        for segment in self._cfg.quality_hours_utc.split(","):
            segment = segment.strip()
            if "-" in segment:
                parts = segment.split("-", 1)
                try:
                    lo, hi = int(parts[0]), int(parts[1])
                    if lo <= utc_hour <= hi:
                        return True
                except (ValueError, IndexError):
                    continue
        return False

    def _session_multiplier(self, now_s: float) -> Decimal:
        if self._session_active(now_s):
            return _ONE
        return self._cfg.off_session_size_mult
