"""Backtest adapter for bot7 pullback strategy.

Implements the ``BacktestTickAdapter`` protocol using:
- ``PriceBuffer`` (production-shared) for BB, RSI, ADX, ATR, SMA
- ``RegimeDetector`` for directional regime detection (up/down)
- Shared signal functions from ``controllers.bots.bot7.pullback_signals``
- ``PaperDesk`` for order submission

Dependencies kept to:
- controllers.price_buffer (shared with production — single source of truth)
- controllers.regime_detector (shared with production)
- controllers.bots.bot7.pullback_signals (shared pure functions)
- controllers.paper_engine_v2 (simulation engine)
- controllers.backtesting.types (own package)

Signals that require live trade flow (absorption, delta trap, depth imbalance)
are skipped — the pullback zone + indicator gates alone drive entries.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from controllers.backtesting.types import CandleRow
from controllers.common.ict.state import ICTConfig, ICTState
from controllers.bots.bot7.pullback_signals import (
    check_adx_gate,
    check_basis_slope,
    check_htf_trend,
    check_rsi_gate,
    check_trend_sma,
    compute_dynamic_barriers,
    compute_entry_spreads,
    compute_grid_spacing,
    compute_multi_signal_score,
    compute_rsi_momentum_score,
    compute_target_exposure,
    compute_trend_confidence,
    compute_volatility_sizing_mult,
    detect_mean_reversion,
    detect_momentum_breakout,
    detect_pullback_zone,
    in_quality_session,
)
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

_ZERO = Decimal("0")
_ONE = Decimal("1")


_RESOLUTION_TO_MINUTES: dict[str, int] = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}


@dataclass
class PullbackAdapterConfig:
    """All tunable parameters matching PullbackV1Config defaults."""

    # Indicator periods
    bb_period: int = 20
    bb_stddev: Decimal = Decimal("2.0")
    rsi_period: int = 14
    adx_period: int = 14
    atr_period: int = 14
    indicator_resolution: str = "1m"

    # RSI entry windows
    rsi_long_min: Decimal = Decimal("35")
    rsi_long_max: Decimal = Decimal("55")
    rsi_short_min: Decimal = Decimal("45")
    rsi_short_max: Decimal = Decimal("65")

    # ADX range
    adx_min: Decimal = Decimal("22")
    adx_max: Decimal = Decimal("40")

    # Pullback zone
    pullback_zone_pct: Decimal = Decimal("0.0015")
    band_floor_pct: Decimal = Decimal("0.0010")
    zone_atr_mult: Decimal = Decimal("0.25")

    # Grid sizing
    max_grid_legs: int = 3
    per_leg_risk_pct: Decimal = Decimal("0.008")
    total_grid_exposure_cap_pct: Decimal = Decimal("0.025")
    grid_spacing_bb_fraction: Decimal = Decimal("0.12")
    grid_spacing_atr_mult: Decimal = Decimal("0.50")
    grid_spacing_floor_pct: Decimal = Decimal("0.0015")
    grid_spacing_cap_pct: Decimal = Decimal("0.0100")

    # Dynamic barriers
    sl_atr_mult: Decimal = Decimal("1.5")
    tp_atr_mult: Decimal = Decimal("3.0")
    sl_floor_pct: Decimal = Decimal("0.003")
    sl_cap_pct: Decimal = Decimal("0.01")
    tp_floor_pct: Decimal = Decimal("0.006")
    tp_cap_pct: Decimal = Decimal("0.02")

    # Trend quality
    trend_quality_enabled: bool = True
    basis_slope_bars: int = 5
    min_basis_slope_pct: Decimal = Decimal("0.0002")
    trend_sma_period: int = 50

    # Entry
    limit_entry_enabled: bool = True
    entry_offset_pct: Decimal = Decimal("0.001")

    # Session filter
    session_filter_enabled: bool = True
    quality_hours_utc: str = "1-4,8-16,20-23"
    low_quality_size_mult: Decimal = Decimal("0.5")

    # Cooldown
    signal_cooldown_s: int = 180

    # Signal freshness
    signal_freshness_enabled: bool = True
    signal_max_age_s: int = 120

    # Trailing stop
    trailing_stop_enabled: bool = True
    trail_activate_atr_mult: Decimal = Decimal("1.0")
    trail_offset_atr_mult: Decimal = Decimal("0.5")

    # Partial take
    partial_take_pct: Decimal = Decimal("0.33")

    # Risk limits
    max_base_pct: Decimal = Decimal("0.55")
    max_daily_loss_pct: Decimal = Decimal("0.020")
    max_drawdown_pct: Decimal = Decimal("0.035")

    # Hedge ratio
    hedge_ratio: Decimal = Decimal("0.30")

    # Regime detector thresholds
    high_vol_band_pct: Decimal = Decimal("0.0080")
    shock_drift_30s_pct: Decimal = Decimal("0.0050")

    # Warmup
    min_warmup_bars: int = 60

    # Trend confidence
    confidence_min_mult: Decimal = Decimal("0.5")

    # Quote sizing as fraction of equity
    quote_size_pct: Decimal = Decimal("0.03")

    # Hard stop-loss: close position when unrealized loss exceeds this
    hard_sl_enabled: bool = True
    hard_sl_atr_mult: Decimal = Decimal("1.5")

    # Maximum holding time (minutes) — close stale positions
    max_hold_minutes: int = 480

    # Close positions on regime reversal
    regime_reversal_exit: bool = True

    # Block new entries when already positioned in the same direction
    no_add_to_position: bool = True

    # --- Limit exit orders (place TP as limit on entry) ---
    limit_exit_enabled: bool = False
    limit_exit_spread_pct: Decimal = Decimal("0.002")

    # --- Higher-timeframe filter (reduce 1m noise) ---
    htf_filter_enabled: bool = False
    htf_factor: int = 5
    htf_sma_period: int = 12
    htf_slope_bars: int = 3
    htf_min_slope_pct: Decimal = Decimal("0.0005")

    # --- ICT shadow mode ---
    ict_shadow_enabled: bool = False

    # --- Enhanced v2: Multi-signal modes ---
    # Momentum breakout mode
    momentum_enabled: bool = False
    momentum_adx_min: Decimal = Decimal("25")
    momentum_rsi_long_threshold: Decimal = Decimal("55")
    momentum_rsi_short_threshold: Decimal = Decimal("45")
    momentum_breakout_atr_mult: Decimal = Decimal("0.3")
    momentum_sl_atr_mult: Decimal = Decimal("0.6")
    momentum_tp_atr_mult: Decimal = Decimal("1.5")
    momentum_size_mult: Decimal = Decimal("0.7")

    # Mean-reversion mode
    meanrev_enabled: bool = False
    meanrev_adx_max: Decimal = Decimal("22")
    meanrev_rsi_oversold: Decimal = Decimal("28")
    meanrev_rsi_overbought: Decimal = Decimal("72")
    meanrev_band_touch_pct: Decimal = Decimal("0.002")
    meanrev_sl_atr_mult: Decimal = Decimal("0.5")
    meanrev_tp_atr_mult: Decimal = Decimal("1.0")
    meanrev_size_mult: Decimal = Decimal("0.5")

    # Volatility-scaled sizing
    vol_sizing_enabled: bool = False
    vol_target_pct: Decimal = Decimal("0.005")
    vol_sizing_min: Decimal = Decimal("0.3")
    vol_sizing_max: Decimal = Decimal("2.0")


class BacktestPullbackAdapter:
    """Backtest adapter implementing bot7 pullback signal logic.

    Satisfies the ``BacktestTickAdapter`` protocol.
    """

    def __init__(
        self,
        desk: PaperDesk,
        instrument_id: InstrumentId,
        instrument_spec: InstrumentSpec,
        config: PullbackAdapterConfig | None = None,
    ) -> None:
        self._desk = desk
        self._instrument_id = instrument_id
        self._instrument_spec = instrument_spec
        self._cfg = config or PullbackAdapterConfig()

        self._ict: ICTState | None = None
        if self._cfg.ict_shadow_enabled:
            self._ict = ICTState(ICTConfig(atr_period=self._cfg.atr_period))

        _res_min = _RESOLUTION_TO_MINUTES.get(self._cfg.indicator_resolution, 1)
        self._price_buffer = PriceBuffer(
            sample_interval_sec=60,
            max_minutes=2880,
            resolution_minutes=_res_min,
        )
        self._regime_detector = RegimeDetector(
            specs=_default_regime_specs(),
            high_vol_band_pct=self._cfg.high_vol_band_pct,
            shock_drift_30s_pct=self._cfg.shock_drift_30s_pct,
        )

        self._regime_name: str = "neutral_low_vol"
        self._last_submitted_count: int = 0
        self._tick_count: int = 0

        # Daily tracking
        self._daily_equity_open: Decimal = _ZERO
        self._daily_equity_peak: Decimal = _ZERO
        self._current_day: int = -1

        # Signal cooldown
        self._last_signal_ts: dict[str, float] = {}

        # Signal freshness
        self._signal_timestamp: float = 0.0
        self._signal_last_side: str = "off"

        # Position tracking for hard SL and max hold
        self._position_entry_price: Decimal | None = None
        self._position_entry_side: str = "off"
        self._position_entry_ts: float = 0.0
        self._position_sl_pct: Decimal = _ZERO

        # Trailing stop state
        self._trail_state: str = "inactive"
        self._trail_hwm: Decimal | None = None
        self._trail_lwm: Decimal | None = None
        self._partial_taken: bool = False

        # Fill tracking
        self._traded_notional_today: Decimal = _ZERO

        # OHLCV bar tracking — prevents duplicate bar injection when
        # multiple ticks fall within the same candle.
        self._last_candle_ts: int = 0

        # Order persistence across ticks
        self._active_side: str = "off"
        self._orders_submitted_at: float = 0.0

    # ------------------------------------------------------------------
    # BacktestTickAdapter protocol
    # ------------------------------------------------------------------

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
                open=c.open,
                high=c.high,
                low=c.low,
                close=c.close,
            )
            for c in candles
        ]
        if bars:
            self._price_buffer.seed_bars(bars, reset=True)
        if self._ict is not None:
            for c in candles:
                self._ict.add_bar(c.open, c.high, c.low, c.close, c.volume)
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
            if self._ict is not None:
                self._ict.add_bar(candle.open, candle.high, candle.low, candle.close, candle.volume)
            self._last_candle_ts = candle.timestamp_ms
        elif mid > _ZERO:
            self._price_buffer.add_sample(now_s, mid)

        # Daily reset
        day = int(now_s // 86400)
        if day != self._current_day:
            self._current_day = day
            self._daily_equity_open = equity_quote
            self._daily_equity_peak = equity_quote
            self._traded_notional_today = _ZERO
        self._daily_equity_peak = max(self._daily_equity_peak, equity_quote)

        if not self._price_buffer.ready(cfg.min_warmup_bars):
            return None

        if mid <= _ZERO or equity_quote <= _ZERO:
            return None

        # --- Indicators from production PriceBuffer ---
        bands = self._price_buffer.bollinger_bands(cfg.bb_period, cfg.bb_stddev)
        rsi_val = self._price_buffer.rsi(cfg.rsi_period)
        adx_val = self._price_buffer.adx(cfg.adx_period)
        atr_val = self._price_buffer.atr(cfg.atr_period)
        sma_val = self._price_buffer.sma(cfg.trend_sma_period)

        if bands is None or rsi_val is None or adx_val is None:
            return None

        bb_lower, bb_basis, bb_upper = bands

        # --- Regime detection ---
        ema_val = self._price_buffer.ema(cfg.trend_sma_period) or mid
        band_pct = self._price_buffer.band_pct(cfg.atr_period) or _ZERO
        drift = self._price_buffer.adverse_drift_30s(now_s)
        regime_name, _spec = self._regime_detector.detect(
            mid=mid,
            ema_val=ema_val,
            band_pct=band_pct,
            drift=drift,
            regime_source_tag="backtest",
        )
        self._regime_name = regime_name

        regime_up = regime_name == "up"
        regime_down = regime_name == "down"
        has_position = abs(position_base) > Decimal("1e-8")

        # Reset stale entry tracking when position is flat
        if not has_position and self._position_entry_price is not None:
            self._reset_position_tracking()

        # --- Hard stop-loss: close immediately if loss exceeds threshold ---
        if has_position and self._position_entry_price is not None:
            exit_reason = self._check_forced_exit(
                mid, position_base, atr_val, now_s, regime_name,
            )
            if exit_reason:
                self._close_position(mid, position_base)
                self._last_submitted_count = 0
                return {"side": "exit", "regime": regime_name, "reason": exit_reason}

        # --- Risk checks ---
        base_pct = abs(position_base * mid / equity_quote) if equity_quote > _ZERO else _ZERO
        daily_loss = (
            (self._daily_equity_open - equity_quote) / self._daily_equity_open
            if self._daily_equity_open > _ZERO else _ZERO
        )
        drawdown = (
            (self._daily_equity_peak - equity_quote) / self._daily_equity_peak
            if self._daily_equity_peak > _ZERO else _ZERO
        )
        if base_pct > cfg.max_base_pct or daily_loss > cfg.max_daily_loss_pct or drawdown > cfg.max_drawdown_pct:
            if has_position:
                self._close_position(mid, position_base)
            self._cancel_all()
            self._last_submitted_count = 0
            return None

        # --- Trailing stop management ---
        self._manage_trailing_stop(mid, position_base, atr_val)

        # --- Signal evaluation: multi-mode (pullback + momentum + mean-reversion) ---
        adx_ok = check_adx_gate(adx_val, cfg.adx_min, cfg.adx_max)

        closes = self._price_buffer.closes
        slope_long_ok, basis_slope = check_basis_slope(
            closes, "buy", cfg.bb_period, cfg.basis_slope_bars, cfg.min_basis_slope_pct,
        ) if cfg.trend_quality_enabled else (True, _ZERO)
        slope_short_ok, _ = check_basis_slope(
            closes, "sell", cfg.bb_period, cfg.basis_slope_bars, cfg.min_basis_slope_pct,
        ) if cfg.trend_quality_enabled else (True, _ZERO)

        sma_long_ok = check_trend_sma(mid, sma_val, "buy") if cfg.trend_quality_enabled else True
        sma_short_ok = check_trend_sma(mid, sma_val, "sell") if cfg.trend_quality_enabled else True
        htf_long_ok, htf_long_slope, _ = check_htf_trend(
            closes,
            "buy",
            cfg.htf_factor,
            cfg.htf_sma_period,
            cfg.htf_slope_bars,
            cfg.htf_min_slope_pct,
        ) if cfg.htf_filter_enabled else (True, _ZERO, None)
        htf_short_ok, htf_short_slope, _ = check_htf_trend(
            closes,
            "sell",
            cfg.htf_factor,
            cfg.htf_sma_period,
            cfg.htf_slope_bars,
            cfg.htf_min_slope_pct,
        ) if cfg.htf_filter_enabled else (True, _ZERO, None)

        in_zone_long, in_zone_short = detect_pullback_zone(
            mid, bb_lower, bb_basis, bb_upper, atr_val,
            cfg.pullback_zone_pct, cfg.band_floor_pct, cfg.zone_atr_mult,
        )

        rsi_long_ok = check_rsi_gate(rsi_val, "buy", cfg.rsi_long_min, cfg.rsi_long_max)
        rsi_short_ok = check_rsi_gate(rsi_val, "sell", cfg.rsi_short_min, cfg.rsi_short_max)

        session_quality, session_mult = in_quality_session(
            now_s, cfg.quality_hours_utc, cfg.session_filter_enabled, cfg.low_quality_size_mult,
        )
        session_block = not session_quality and session_mult <= _ZERO

        # --- Mode 1: Pullback (original) ---
        pb_long = (
            regime_up and adx_ok and slope_long_ok and sma_long_ok
            and htf_long_ok and in_zone_long and rsi_long_ok and not session_block
        )
        pb_short = (
            regime_down and adx_ok and slope_short_ok and sma_short_ok
            and htf_short_ok and in_zone_short and rsi_short_ok and not session_block
        )
        pullback_active = pb_long or pb_short
        pb_side = "buy" if pb_long and not pb_short else ("sell" if pb_short and not pb_long else "off")

        # --- Mode 2: Momentum breakout ---
        mo_side, mo_strength = "off", _ZERO
        if cfg.momentum_enabled and not session_block:
            mo_side, mo_strength = detect_momentum_breakout(
                mid, bb_upper, bb_lower, adx_val, rsi_val, atr_val,
                cfg.momentum_adx_min, cfg.momentum_rsi_long_threshold,
                cfg.momentum_rsi_short_threshold, cfg.momentum_breakout_atr_mult,
            )
        momentum_active = mo_side != "off"

        # --- Mode 3: Mean-reversion ---
        mr_side, mr_strength = "off", _ZERO
        if cfg.meanrev_enabled and not session_block:
            mr_side, mr_strength = detect_mean_reversion(
                mid, bb_upper, bb_lower, bb_basis, rsi_val, adx_val,
                cfg.meanrev_adx_max, cfg.meanrev_rsi_oversold,
                cfg.meanrev_rsi_overbought, cfg.meanrev_band_touch_pct,
            )
            if (mr_side == "buy" and not htf_long_ok) or (mr_side == "sell" and not htf_short_ok):
                mr_side, mr_strength = "off", _ZERO
        meanrev_active = mr_side != "off"

        # --- Signal arbitration: pick the best signal, with priority ---
        # Priority: pullback > momentum > mean-reversion (pullback has best proven edge)
        side = "off"
        active_mode = "none"
        mode_size_mult = _ONE

        if pb_side != "off":
            side = pb_side
            active_mode = "pullback"
        elif mo_side != "off":
            side = mo_side
            active_mode = "momentum"
            mode_size_mult = cfg.momentum_size_mult
        elif mr_side != "off":
            side = mr_side
            active_mode = "meanrev"
            mode_size_mult = cfg.meanrev_size_mult

        # Block new entries if already positioned in the same direction
        if cfg.no_add_to_position and side != "off" and has_position:
            pos_side = "buy" if position_base > _ZERO else "sell"
            if pos_side == side:
                side = "off"

        # Cooldown check
        if side != "off" and self._cooldown_active(side, now_s):
            side = "off"

        # Record signal timestamp
        if side != "off":
            self._last_signal_ts[side] = now_s
            if side != self._signal_last_side:
                self._signal_timestamp = now_s
                self._signal_last_side = side
        else:
            self._signal_last_side = "off"

        # Signal freshness check
        if side != "off" and cfg.signal_freshness_enabled and self._signal_timestamp > 0:
            if (now_s - self._signal_timestamp) > cfg.signal_max_age_s:
                side = "off"

        # --- Order lifecycle ---
        order_refresh_s = 300
        side_changed = side != self._active_side
        orders_stale = (now_s - self._orders_submitted_at) > order_refresh_s

        if side == "off":
            if self._active_side != "off":
                self._cancel_all()
                self._active_side = "off"
            self._last_submitted_count = 0
            return {"side": "off", "regime": regime_name}

        if not side_changed and not orders_stale:
            return {"side": side, "regime": regime_name, "holding_orders": True}

        self._cancel_all()
        self._last_submitted_count = 0
        self._active_side = side
        self._orders_submitted_at = now_s

        # Record entry tracking — use mode-specific SL
        if self._position_entry_price is None:
            self._position_entry_price = mid
            self._position_entry_side = side
            self._position_entry_ts = now_s
            sl_mult = cfg.hard_sl_atr_mult
            if active_mode == "momentum":
                sl_mult = cfg.momentum_sl_atr_mult
            elif active_mode == "meanrev":
                sl_mult = cfg.meanrev_sl_atr_mult
            sl_pct, _ = compute_dynamic_barriers(
                mid, atr_val, sl_mult, cfg.tp_atr_mult,
                cfg.sl_floor_pct, cfg.sl_cap_pct, cfg.tp_floor_pct, cfg.tp_cap_pct,
            )
            self._position_sl_pct = sl_pct

        # --- Signal score using multi-signal confluence ---
        adx_range = cfg.adx_max - cfg.adx_min
        adx_norm = ((adx_val - cfg.adx_min) / adx_range) if adx_range > _ZERO else _ZERO
        adx_norm = max(_ZERO, min(_ONE, adx_norm))
        rsi_score = compute_rsi_momentum_score(rsi_val, side)
        slope_confirms = slope_long_ok if side == "buy" else slope_short_ok
        htf_slope = htf_long_slope if side == "buy" else htf_short_slope
        sma_confirms = (check_trend_sma(mid, sma_val, "buy") if side == "buy"
                        else check_trend_sma(mid, sma_val, "sell"))

        signal_score = compute_multi_signal_score(
            pullback_active=(active_mode == "pullback"),
            momentum_active=(active_mode == "momentum"),
            momentum_strength=mo_strength,
            meanrev_active=(active_mode == "meanrev"),
            meanrev_strength=mr_strength,
            adx_norm=adx_norm,
            rsi_score=rsi_score,
            sma_confirms=sma_confirms,
            slope_confirms=slope_confirms,
        )
        if cfg.htf_filter_enabled and htf_slope != _ZERO:
            signal_score *= Decimal("1.10")
        signal_score = max(signal_score, Decimal("0.25"))

        trend_conf = compute_trend_confidence(
            side, adx_val, basis_slope, mid, sma_val,
            cfg.adx_min, cfg.adx_max, cfg.min_basis_slope_pct, cfg.confidence_min_mult,
        )

        spacing_pct = compute_grid_spacing(
            bb_upper, bb_lower, mid, atr_val,
            cfg.grid_spacing_bb_fraction, cfg.grid_spacing_atr_mult,
            cfg.grid_spacing_floor_pct, cfg.grid_spacing_cap_pct,
        )

        levels = min(
            cfg.max_grid_legs,
            max(1, int((signal_score * Decimal(cfg.max_grid_legs)).to_integral_value(rounding="ROUND_CEILING"))),
        )

        spreads = compute_entry_spreads(
            mid, bb_basis, side, levels, spacing_pct,
            cfg.entry_offset_pct, cfg.grid_spacing_floor_pct,
            cfg.limit_entry_enabled,
        )

        _target_net, _ = compute_target_exposure(
            side, levels, cfg.per_leg_risk_pct, cfg.total_grid_exposure_cap_pct,
            _ONE, False, Decimal("0.5"), cfg.hedge_ratio,
        )

        # Volatility-scaled sizing
        vol_mult = _ONE
        if cfg.vol_sizing_enabled:
            vol_mult = compute_volatility_sizing_mult(
                atr_val, mid, cfg.vol_target_pct, cfg.vol_sizing_min, cfg.vol_sizing_max,
            )

        size_mult = session_mult * trend_conf * mode_size_mult * vol_mult
        quote_per_level = equity_quote * cfg.quote_size_pct * size_mult

        submitted = 0
        for spread_pct in spreads:
            if side == "buy":
                price = self._instrument_spec.quantize_price(mid * (_ONE - spread_pct), "buy")
            else:
                price = self._instrument_spec.quantize_price(mid * (_ONE + spread_pct), "sell")

            base_qty = quote_per_level / price if price > _ZERO else _ZERO
            quantity = self._instrument_spec.quantize_size(base_qty)

            if quantity > _ZERO and price > _ZERO:
                order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL
                self._desk.submit_order(
                    instrument_id=self._instrument_id,
                    side=order_side,
                    order_type=PaperOrderType.LIMIT,
                    price=price,
                    quantity=quantity,
                    source_bot=f"backtest_{active_mode}",
                )
                submitted += 1

        # Place limit exit orders for open positions
        if cfg.limit_exit_enabled and has_position and submitted == 0:
            pos_side = "buy" if position_base > _ZERO else "sell"
            entry_p = self._position_entry_price
            if entry_p is not None and entry_p > _ZERO:
                exit_spread = cfg.limit_exit_spread_pct
                if pos_side == "buy":
                    exit_price = self._instrument_spec.quantize_price(
                        entry_p * (_ONE + exit_spread), "sell",
                    )
                    exit_side = OrderSide.SELL
                else:
                    exit_price = self._instrument_spec.quantize_price(
                        entry_p * (_ONE - exit_spread), "buy",
                    )
                    exit_side = OrderSide.BUY
                exit_qty = self._instrument_spec.quantize_size(abs(position_base))
                if exit_qty > _ZERO and exit_price > _ZERO:
                    self._desk.submit_order(
                        instrument_id=self._instrument_id,
                        side=exit_side,
                        order_type=PaperOrderType.LIMIT,
                        price=exit_price,
                        quantity=exit_qty,
                        source_bot="backtest_limit_exit",
                    )

        self._last_submitted_count = submitted
        result = {
            "side": side,
            "regime": regime_name,
            "mode": active_mode,
            "levels": levels,
            "rsi": float(rsi_val),
            "adx": float(adx_val),
            "signal_score": float(signal_score),
            "vol_mult": float(vol_mult),
            "htf_factor": cfg.htf_factor,
        }

        if self._ict is not None:
            result["ict_trend"] = self._ict.trend
            result["ict_active_fvgs"] = len(self._ict.active_fvgs)
            result["ict_active_obs"] = len(self._ict.active_obs)
            result["ict_active_breakers"] = len(self._ict.all_breakers)
            result["ict_pd_zone"] = self._ict.zone_for_price(mid)
            last_s = self._ict.last_structure
            if last_s is not None:
                result["ict_last_struct"] = last_s.event_type
                result["ict_last_struct_dir"] = last_s.direction

        return result

    def record_fill_notional(self, notional: Decimal) -> None:
        self._traded_notional_today += notional

    # ------------------------------------------------------------------
    # Forced exit checks
    # ------------------------------------------------------------------

    def _check_forced_exit(
        self,
        mid: Decimal,
        position_base: Decimal,
        atr: Decimal | None,
        now_s: float,
        regime_name: str,
    ) -> str:
        """Return a non-empty reason string if the position must be closed."""
        cfg = self._cfg
        entry_price = self._position_entry_price
        entry_side = self._position_entry_side

        if entry_price is None or entry_price <= _ZERO:
            return ""

        # Unrealized PnL
        if entry_side == "buy":
            pnl_pct = (mid - entry_price) / entry_price
        elif entry_side == "sell":
            pnl_pct = (entry_price - mid) / entry_price
        else:
            return ""

        # Hard stop-loss
        if cfg.hard_sl_enabled and self._position_sl_pct > _ZERO:
            if pnl_pct <= -self._position_sl_pct:
                return "hard_sl"

        # Max holding time
        if cfg.max_hold_minutes > 0:
            hold_s = now_s - self._position_entry_ts
            if hold_s > cfg.max_hold_minutes * 60:
                return "max_hold"

        # Regime reversal exit
        if cfg.regime_reversal_exit:
            if entry_side == "buy" and regime_name == "down":
                return "regime_reversal"
            if entry_side == "sell" and regime_name == "up":
                return "regime_reversal"

        return ""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _close_position(self, mid: Decimal, position_base: Decimal) -> None:
        """Close the entire position at the current mid price."""
        self._cancel_all()
        close_qty = abs(position_base)
        if close_qty <= _ZERO:
            self._reset_position_tracking()
            return
        close_side = OrderSide.SELL if position_base > _ZERO else OrderSide.BUY
        qty = self._instrument_spec.quantize_size(close_qty)
        if qty > _ZERO:
            self._desk.submit_order(
                instrument_id=self._instrument_id,
                side=close_side,
                order_type=PaperOrderType.LIMIT,
                price=mid,
                quantity=qty,
                source_bot="backtest_pullback_exit",
            )
        self._reset_position_tracking()

    def _cancel_all(self) -> None:
        try:
            self._desk.cancel_all(self._instrument_id)
        except Exception:
            pass  # Justification: best-effort teardown during simulation — desk may already be closed

    def _cooldown_active(self, side: str, now_s: float) -> bool:
        cooldown_s = self._cfg.signal_cooldown_s
        if cooldown_s <= 0:
            return False
        last_ts = self._last_signal_ts.get(side, 0.0)
        return (now_s - last_ts) < cooldown_s

    def _reset_position_tracking(self) -> None:
        self._position_entry_price = None
        self._position_entry_side = "off"
        self._position_entry_ts = 0.0
        self._position_sl_pct = _ZERO
        self._trail_state = "inactive"
        self._trail_hwm = None
        self._trail_lwm = None
        self._partial_taken = False
        self._active_side = "off"

    def _manage_trailing_stop(
        self, mid: Decimal, position_base: Decimal, atr: Decimal | None,
    ) -> None:
        """Trailing stop + partial take state machine."""
        if not self._cfg.trailing_stop_enabled:
            return

        if abs(position_base) < Decimal("1e-8"):
            if self._position_entry_price is not None or self._trail_state != "inactive":
                self._reset_position_tracking()
            return

        if mid <= _ZERO:
            return

        entry_price = self._position_entry_price
        if entry_price is None or entry_price <= _ZERO:
            return

        entry_side = self._position_entry_side
        if atr is None or atr <= _ZERO:
            return

        if entry_side == "buy":
            pnl_pct = (mid - entry_price) / entry_price
        elif entry_side == "sell":
            pnl_pct = (entry_price - mid) / entry_price
        else:
            return

        # Partial take at 1R
        if not self._partial_taken and self._position_sl_pct > _ZERO:
            if pnl_pct >= self._position_sl_pct:
                partial_qty = abs(position_base) * self._cfg.partial_take_pct
                if partial_qty > _ZERO:
                    close_side = OrderSide.SELL if entry_side == "buy" else OrderSide.BUY
                    qty = self._instrument_spec.quantize_size(partial_qty)
                    if qty > _ZERO:
                        self._desk.submit_order(
                            instrument_id=self._instrument_id,
                            side=close_side,
                            order_type=PaperOrderType.LIMIT,
                            price=mid,
                            quantity=qty,
                            source_bot="backtest_pullback_partial",
                        )
                    self._partial_taken = True

        # Trailing stop activation / tracking / trigger
        activate_threshold = self._cfg.trail_activate_atr_mult * atr / mid
        trail_offset = self._cfg.trail_offset_atr_mult * atr

        if self._trail_state == "inactive":
            if pnl_pct >= activate_threshold:
                self._trail_state = "tracking"
                if entry_side == "buy":
                    self._trail_hwm = mid
                else:
                    self._trail_lwm = mid

        elif self._trail_state == "tracking":
            if entry_side == "buy":
                if mid > (self._trail_hwm or mid):
                    self._trail_hwm = mid
                retrace = (self._trail_hwm or mid) - mid
                if retrace >= trail_offset:
                    self._trail_state = "triggered"
            else:
                if mid < (self._trail_lwm or mid):
                    self._trail_lwm = mid
                retrace = mid - (self._trail_lwm or mid)
                if retrace >= trail_offset:
                    self._trail_state = "triggered"

        if self._trail_state == "triggered":
            self._close_position(mid, position_base)
