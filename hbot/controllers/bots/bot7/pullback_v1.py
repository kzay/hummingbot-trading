"""Trend-aligned pullback grid strategy for bot7.

Philosophy
----------
Mean-reversion fails on BTC perps in trending regimes (ADX 22-40).  This lane
enters WITH the trend during controlled pullbacks to the BB basis, not at band
extremes.  Entries are only enabled when the market has directional structure
(regime == "up" or "down") and ADX is in the productive 22-40 range.

Signal logic
------------
pullback_long (only in "up" regime):
  1. regime == "up"
  2. pb_adx_min <= ADX <= pb_adx_max  (22-40: enough trend, not too chaotic)
  3. price in pullback zone: mid <= bb_basis*(1+pb_pullback_zone_pct)
                             mid >= bb_lower*(1+pb_band_floor_pct)
  4. pb_rsi_long_min <= RSI <= pb_rsi_long_max  (35-55: momentum dip)
  5. absorption_long OR delta_trap_long  (vs pullback zone, not band extreme)
  6. NOT signal_cooldown_active

pullback_short (only in "down" regime): symmetric

probe_long/probe_short: depth imbalance + primary signal but relaxed RSI
no_entry: neutral_*, high_vol_shock regimes
"""
from __future__ import annotations

import logging
import time as _time_mod
from collections import deque
from decimal import Decimal
from typing import Any

from pydantic import Field

from controllers.runtime.base import DirectionalStrategyRuntimeV24Config, DirectionalStrategyRuntimeV24Controller
from controllers.runtime.data_context import RuntimeDataContext
from controllers.runtime.execution_context import RuntimeExecutionPlan
from controllers.runtime.risk_context import RuntimeRiskDecision
from controllers.runtime.runtime_types import MarketConditions, RegimeSpec, SpreadEdgeState, clip
from platform_lib.market_data.market_data_plane import CanonicalMarketDataReader, MarketTrade
from platform_lib.core.utils import to_decimal

_logger = logging.getLogger(__name__)

_ZERO = Decimal("0")
_ONE = Decimal("1")
_NEG_ONE = Decimal("-1")
_FOUR = Decimal("4")


class PullbackV1Config(DirectionalStrategyRuntimeV24Config):
    """Bot7 trend-aligned pullback grid strategy."""

    controller_name: str = "bot7_pullback_v1"

    # ── Indicator periods ────────────────────────────────────────────────
    pb_bb_period: int = Field(default=20, ge=10, le=100)
    pb_bb_stddev: Decimal = Field(default=Decimal("2.0"))
    pb_rsi_period: int = Field(default=14, ge=5, le=50)
    pb_adx_period: int = Field(default=14, ge=5, le=50)
    atr_period: int = Field(default=14, ge=5, le=50)

    # ── RSI entry windows ───────────────────────────────────────────────
    # Long: momentum dip (not oversold exhaustion)
    pb_rsi_long_min: Decimal = Field(default=Decimal("35"))
    pb_rsi_long_max: Decimal = Field(default=Decimal("55"))
    # Short: momentum pop (not overbought exhaustion)
    pb_rsi_short_min: Decimal = Field(default=Decimal("45"))
    pb_rsi_short_max: Decimal = Field(default=Decimal("65"))
    # Probe RSI windows (slightly wider)
    pb_rsi_probe_long_min: Decimal = Field(default=Decimal("38"))
    pb_rsi_probe_long_max: Decimal = Field(default=Decimal("58"))
    pb_rsi_probe_short_min: Decimal = Field(default=Decimal("42"))
    pb_rsi_probe_short_max: Decimal = Field(default=Decimal("62"))

    # ── ADX range gate ──────────────────────────────────────────────────
    pb_adx_min: Decimal = Field(default=Decimal("22"))   # needs directional structure
    pb_adx_max: Decimal = Field(default=Decimal("40"))   # not too choppy/chaotic

    # ── Pullback zone ───────────────────────────────────────────────────
    # Long zone: price <= bb_basis*(1+zone_pct) AND price >= bb_lower*(1+floor_pct)
    # zone_pct is the static floor; when ATR is available the zone widens to
    # max(zone_pct, atr/mid * pb_zone_atr_mult) — adapts to current volatility.
    pb_pullback_zone_pct: Decimal = Field(default=Decimal("0.0015"))
    pb_band_floor_pct: Decimal = Field(default=Decimal("0.0010"))
    pb_zone_atr_mult: Decimal = Field(default=Decimal("0.25"))

    # ── Trade flow ──────────────────────────────────────────────────────
    pb_trade_window_count: int = Field(default=160, ge=20, le=600)
    pb_trade_stale_after_ms: int = Field(default=20_000, ge=1000, le=120_000)
    pb_trade_reader_enabled: bool = Field(default=True)

    # ── Absorption detection ────────────────────────────────────────────
    pb_absorption_window: int = Field(default=20, ge=6, le=100)
    pb_absorption_min_trade_mult: Decimal = Field(default=Decimal("2.5"))
    pb_absorption_max_price_drift_pct: Decimal = Field(default=Decimal("0.0015"))

    # ── Delta trap detection ────────────────────────────────────────────
    pb_delta_trap_window: int = Field(default=24, ge=8, le=120)
    pb_delta_trap_reversal_share: Decimal = Field(default=Decimal("0.30"))
    pb_delta_trap_max_price_drift_pct: Decimal = Field(default=Decimal("0.0020"))
    pb_recent_delta_window: int = Field(default=20, ge=6, le=100)

    # ── Depth imbalance ─────────────────────────────────────────────────
    pb_depth_imbalance_threshold: Decimal = Field(default=Decimal("0.20"))

    # ── Grid sizing ─────────────────────────────────────────────────────
    pb_max_grid_legs: int = Field(default=3, ge=1, le=6)
    pb_per_leg_risk_pct: Decimal = Field(default=Decimal("0.008"))
    pb_total_grid_exposure_cap_pct: Decimal = Field(default=Decimal("0.025"))
    pb_grid_spacing_atr_mult: Decimal = Field(default=Decimal("0.50"))
    pb_grid_spacing_floor_pct: Decimal = Field(default=Decimal("0.0015"))
    pb_grid_spacing_cap_pct: Decimal = Field(default=Decimal("0.0100"))
    pb_grid_spacing_bb_fraction: Decimal = Field(default=Decimal("0.12"))

    # ── Risk / hedging ──────────────────────────────────────────────────
    pb_hedge_ratio: Decimal = Field(default=Decimal("0.30"))
    pb_funding_long_bias_threshold: Decimal = Field(default=Decimal("-0.0003"))
    pb_funding_short_bias_threshold: Decimal = Field(default=Decimal("0.0003"))
    pb_funding_vol_reduce_threshold: Decimal = Field(default=Decimal("0.0010"))
    # Block entry when funding actively opposes direction (longs pay on short bias, etc.)
    pb_block_contra_funding: bool = Field(default=True)

    # ── Probe mode ──────────────────────────────────────────────────────
    pb_probe_enabled: bool = Field(default=True)
    pb_probe_grid_legs: int = Field(default=1, ge=1, le=2)
    pb_probe_size_mult: Decimal = Field(default=Decimal("0.50"))

    # ── Signal cooldown ─────────────────────────────────────────────────
    pb_signal_cooldown_s: int = Field(default=180, ge=0, le=3600)

    # ── Warmup quotes (disabled by default to avoid unmanaged fills) ────
    pb_warmup_quote_levels: int = Field(default=0, ge=0, le=2)
    pb_warmup_quote_max_bars: int = Field(default=3, ge=0, le=20)

    # ── ATR-scaled dynamic barriers ──────────────────────────────────────
    pb_dynamic_barriers_enabled: bool = Field(default=True)
    pb_sl_atr_mult: Decimal = Field(default=Decimal("1.5"))
    pb_tp_atr_mult: Decimal = Field(default=Decimal("3.0"))
    pb_sl_floor_pct: Decimal = Field(default=Decimal("0.003"))
    pb_sl_cap_pct: Decimal = Field(default=Decimal("0.01"))
    pb_tp_floor_pct: Decimal = Field(default=Decimal("0.006"))
    pb_tp_cap_pct: Decimal = Field(default=Decimal("0.02"))

    # ── Trend quality gates ──────────────────────────────────────────────
    pb_trend_quality_enabled: bool = Field(default=True)
    pb_basis_slope_bars: int = Field(default=5, ge=2, le=30)
    pb_min_basis_slope_pct: Decimal = Field(default=Decimal("0.0002"))
    pb_trend_sma_period: int = Field(default=50, ge=10, le=200)

    # ── Trailing stop ────────────────────────────────────────────────────
    pb_trailing_stop_enabled: bool = Field(default=True)
    pb_trail_activate_atr_mult: Decimal = Field(default=Decimal("1.0"))
    pb_trail_offset_atr_mult: Decimal = Field(default=Decimal("0.5"))

    # ── Partial profit-taking ────────────────────────────────────────────
    pb_partial_take_pct: Decimal = Field(default=Decimal("0.33"))

    # ── Entry quality ────────────────────────────────────────────────────
    pb_limit_entry_enabled: bool = Field(default=True)
    pb_entry_offset_pct: Decimal = Field(default=Decimal("0.001"))
    pb_entry_timeout_s: int = Field(default=30, ge=5, le=300)
    pb_adverse_selection_enabled: bool = Field(default=True)
    pb_max_entry_spread_pct: Decimal = Field(default=Decimal("0.0008"))
    pb_max_entry_imbalance: Decimal = Field(default=Decimal("0.5"))

    # ── Z-score absorption ───────────────────────────────────────────────
    pb_absorption_zscore_enabled: bool = Field(default=True)
    pb_absorption_zscore_threshold: Decimal = Field(default=Decimal("2.0"))

    # ── Probe SL tightening ───────────────────────────────────────────────
    pb_probe_sl_mult: Decimal = Field(default=Decimal("0.75"))

    # ── Limit-order exits ─────────────────────────────────────────────────
    pb_trail_exit_order_type: str = Field(default="LIMIT")
    pb_partial_exit_order_type: str = Field(default="LIMIT")
    pb_exit_limit_timeout_s: int = Field(default=15, ge=1, le=120)

    # ── Volume-declining pullback filter ──────────────────────────────────
    pb_vol_decline_enabled: bool = Field(default=True)
    pb_vol_decline_lookback: int = Field(default=5, ge=2, le=20)

    # ── Time-of-day quality filter ────────────────────────────────────────
    pb_session_filter_enabled: bool = Field(default=True)
    pb_quality_hours_utc: str = Field(default="1-4,8-16,20-23")
    pb_low_quality_size_mult: Decimal = Field(default=Decimal("0.5"))

    # ── Gradient trend confidence ─────────────────────────────────────────
    pb_trend_confidence_enabled: bool = Field(default=True)
    pb_trend_confidence_min_mult: Decimal = Field(default=Decimal("0.5"))

    # ── RSI divergence booster ────────────────────────────────────────────
    pb_rsi_divergence_enabled: bool = Field(default=True)
    pb_rsi_divergence_lookback: int = Field(default=10, ge=4, le=40)

    # ── Signal freshness timeout ──────────────────────────────────────────
    pb_signal_freshness_enabled: bool = Field(default=True)
    pb_signal_max_age_s: int = Field(default=120, ge=10, le=600)

    # ── Adaptive cooldown ─────────────────────────────────────────────────
    pb_adaptive_cooldown_enabled: bool = Field(default=True)
    pb_cooldown_min_s: int = Field(default=90, ge=0, le=3600)
    pb_cooldown_max_s: int = Field(default=360, ge=0, le=3600)

    # ── Signal diagnostics ───────────────────────────────────────────────
    pb_signal_diagnostics_enabled: bool = Field(default=True)
    pb_min_signals_warn: int = Field(default=3, ge=0, le=100)

    @property
    def triple_barrier_config(self):
        """Return ATR-scaled dynamic TBC when available, else static parent."""
        dynamic_tbc = getattr(self, "_pb_dynamic_tbc", None)
        if dynamic_tbc is not None:
            return dynamic_tbc
        return super().triple_barrier_config


class PullbackV1Controller(DirectionalStrategyRuntimeV24Controller):
    """Trend-aligned pullback grid wrapper over the shared runtime controller."""

    def __init__(self, config: PullbackV1Config, *args, **kwargs):
        super().__init__(config, *args, **kwargs)
        self._pb_state: dict[str, Any] = self._empty_pb_state()
        self._pb_last_funding_rate: Decimal = _ZERO
        self._pb_last_signal_ts: dict[str, float] = {}
        self._trade_reader = CanonicalMarketDataReader(
            connector_name=str(config.connector_name),
            trading_pair=str(config.trading_pair),
            enabled=bool(getattr(config, "pb_trade_reader_enabled", True)),
            stale_after_ms=int(getattr(config, "pb_trade_stale_after_ms", 20_000)),
        )
        # ── Trailing stop state ──────────────────────────────────────────
        self._pb_trail_state: str = "inactive"  # inactive / tracking / triggered
        self._pb_trail_hwm: Decimal | None = None
        self._pb_trail_lwm: Decimal | None = None
        self._pb_trail_entry_price: Decimal | None = None
        self._pb_trail_entry_side: str = "off"
        self._pb_trail_sl_distance: Decimal = _ZERO
        self._pb_partial_taken: bool = False
        self._pb_pending_actions: list[Any] = []
        # ── Signal diagnostics ───────────────────────────────────────────
        self._pb_signal_counter: deque[float] = deque()
        self._pb_signal_warn_last_ts: float = 0.0
        # ── Signal freshness ──────────────────────────────────────────────
        self._pb_signal_timestamp: float = 0.0
        self._pb_signal_last_side: str = "off"

    def determine_executor_actions(self) -> list:
        """Drain pending trailing-stop / partial-take actions into the framework."""
        actions = super().determine_executor_actions()
        if self._pb_pending_actions:
            actions.extend(self._pb_pending_actions)
            self._pb_pending_actions = []
        return actions

    def _empty_pb_state(self) -> dict[str, Any]:
        return {
            "active": False,
            "probe_mode": False,
            "side": "off",
            "reason": "inactive",
            "bb_lower": _ZERO,
            "bb_basis": _ZERO,
            "bb_upper": _ZERO,
            "rsi": Decimal("50"),
            "adx": _ZERO,
            "atr": _ZERO,
            "grid_spacing_pct": _ZERO,
            "trade_age_ms": 0,
            "trade_flow_stale": True,
            "cvd": _ZERO,
            "delta_volume": _ZERO,
            "recent_delta": _ZERO,
            "absorption_long": False,
            "absorption_short": False,
            "delta_trap_long": False,
            "delta_trap_short": False,
            "in_pullback_zone_long": False,
            "in_pullback_zone_short": False,
            "signal_score": _ZERO,
            "grid_levels": 0,
            "target_net_base_pct": _ZERO,
            "hedge_target_base_pct": _ZERO,
            "funding_bias": "neutral",
            "funding_risk_scale": _ONE,
            "order_book_imbalance": _ZERO,
            "indicator_ready": False,
            "indicator_missing": "",
            "price_buffer_bars": 0,
            "basis_slope": _ZERO,
            "trend_sma": None,
            "trail_state": "inactive",
            "signal_count_24h": 0,
            "dynamic_sl": _ZERO,
            "dynamic_tp": _ZERO,
            "absorption_zscore": _ZERO,
            "vol_declining": False,
            "session_quality": True,
            "session_size_mult": _ONE,
            "trend_confidence": _ONE,
            "rsi_divergence": False,
            "signal_age_s": 0,
            "adaptive_cooldown_s": 180,
        }

    def _pb_gate_metrics(self) -> dict[str, Any]:
        state = getattr(self, "_pb_state", None) or self._empty_pb_state()
        reason = str(state.get("reason", "inactive"))
        return {
            "state": "active" if bool(state.get("active", False)) else "idle",
            "reason": reason,
            "fail_closed": False,
        }

    def _bot7_gate_metrics(self) -> dict[str, Any]:
        return self._pb_gate_metrics()

    def _compute_alpha_policy(
        self,
        *,
        regime_name: str,
        spread_state: SpreadEdgeState,
        market: MarketConditions,
        target_net_base_pct: Decimal,
        base_pct_net: Decimal,
    ) -> dict[str, Decimal | str | bool]:
        gate = self._pb_gate_metrics()
        signal_score = to_decimal((getattr(self, "_pb_state", None) or {}).get("signal_score", _ZERO))
        metrics: dict[str, Decimal | str | bool] = {
            "state": "pb_strategy_gate",
            "reason": str(gate["reason"]),
            "maker_score": signal_score,
            "aggressive_score": _ZERO,
            "cross_allowed": False,
        }
        self._alpha_policy_state = str(metrics["state"])
        self._alpha_policy_reason = str(metrics["reason"])
        self._alpha_maker_score = signal_score
        self._alpha_aggressive_score = _ZERO
        self._alpha_cross_allowed = False
        return metrics

    def _evaluate_all_risk(
        self,
        spread_state: SpreadEdgeState,
        base_pct_gross: Decimal,
        equity_quote: Decimal,
        projected_total_quote: Decimal,
        market: MarketConditions,
    ) -> tuple[list[str], bool, Decimal, Decimal]:
        risk_reasons, risk_hard_stop, daily_loss_pct, drawdown_pct = super()._evaluate_all_risk(
            spread_state=spread_state,
            base_pct_gross=base_pct_gross,
            equity_quote=equity_quote,
            projected_total_quote=projected_total_quote,
            market=market,
        )
        gate = self._pb_gate_metrics()
        if bool(gate["fail_closed"]):
            gate_reason = f"pb_{gate['reason']}"
            if gate_reason not in risk_reasons:
                risk_reasons.append(gate_reason)
        return risk_reasons, risk_hard_stop, daily_loss_pct, drawdown_pct

    def _trade_age_ms(self, trades: list[MarketTrade]) -> int:
        if not trades:
            return 10**9
        latest_ts_ms = max(int(tr.exchange_ts_ms or tr.ingest_ts_ms or 0) for tr in trades)
        if latest_ts_ms <= 0:
            return 10**9
        provider = getattr(self, "market_data_provider", None)
        if provider is not None:
            now_ms = int(float(provider.time()) * 1000)
        else:
            now_ms = int(_time_mod.time() * 1000)
        return max(0, now_ms - latest_ts_ms)

    def _funding_bias(self, funding_rate: Decimal) -> str:
        if funding_rate <= to_decimal(getattr(self.config, "pb_funding_long_bias_threshold", Decimal("-0.0003"))):
            return "long"
        if funding_rate >= to_decimal(getattr(self.config, "pb_funding_short_bias_threshold", Decimal("0.0003"))):
            return "short"
        return "neutral"

    def _funding_risk_scale(self, funding_rate: Decimal) -> Decimal:
        vol_threshold = to_decimal(getattr(self.config, "pb_funding_vol_reduce_threshold", Decimal("0.0010")))
        delta = abs(funding_rate - getattr(self, "_pb_last_funding_rate", _ZERO))
        self._pb_last_funding_rate = funding_rate
        return Decimal("0.50") if delta >= vol_threshold else _ONE

    def _signal_cooldown_active(self, side: str, now: float) -> bool:
        """Return True when the per-side cooldown is still in effect.

        When adaptive cooldown is enabled, scales cooldown by trend confidence:
        high confidence → short cooldown, low confidence → long cooldown.
        """
        if bool(getattr(self.config, "pb_adaptive_cooldown_enabled", True)):
            cd_min = int(getattr(self.config, "pb_cooldown_min_s", 90))
            cd_max = int(getattr(self.config, "pb_cooldown_max_s", 360))
            confidence = to_decimal(getattr(self, "_pb_state", {}).get("trend_confidence", _ONE))
            cooldown_s = int(cd_max - float(confidence) * (cd_max - cd_min))
            self._pb_state["adaptive_cooldown_s"] = cooldown_s
        else:
            cooldown_s = int(getattr(self.config, "pb_signal_cooldown_s", 180))
        if cooldown_s <= 0:
            return False
        last_ts = self._pb_last_signal_ts.get(side, 0.0)
        return (now - last_ts) < cooldown_s

    # ── ATR-scaled dynamic barriers (tasks 2.1, 2.2, 2.4) ─────────────

    def _compute_dynamic_barriers(self, mid: Decimal, atr: Decimal | None) -> tuple[Decimal, Decimal]:
        """Compute ATR-scaled SL/TP percentages, clamped to floor/cap.

        Returns (sl_pct, tp_pct).  Falls back to static config when ATR is
        unavailable or dynamic barriers are disabled.
        """
        if not bool(getattr(self.config, "pb_dynamic_barriers_enabled", True)):
            return (
                to_decimal(getattr(self.config, "stop_loss", Decimal("0.0045"))),
                to_decimal(getattr(self.config, "take_profit", Decimal("0.0090"))),
            )
        if atr is None or mid <= _ZERO:
            return (
                to_decimal(getattr(self.config, "stop_loss", Decimal("0.0045"))),
                to_decimal(getattr(self.config, "take_profit", Decimal("0.0090"))),
            )
        sl_raw = to_decimal(getattr(self.config, "pb_sl_atr_mult", Decimal("1.5"))) * atr / mid
        tp_raw = to_decimal(getattr(self.config, "pb_tp_atr_mult", Decimal("3.0"))) * atr / mid
        # Tighter SL for probe mode
        pb_state = getattr(self, "_pb_state", None) or {}
        if bool(pb_state.get("probe_mode", False)):
            probe_mult = to_decimal(getattr(self.config, "pb_probe_sl_mult", Decimal("0.75")))
            sl_raw = sl_raw * probe_mult
        sl_pct = clip(
            sl_raw,
            to_decimal(getattr(self.config, "pb_sl_floor_pct", Decimal("0.003"))),
            to_decimal(getattr(self.config, "pb_sl_cap_pct", Decimal("0.01"))),
        )
        tp_pct = clip(
            tp_raw,
            to_decimal(getattr(self.config, "pb_tp_floor_pct", Decimal("0.006"))),
            to_decimal(getattr(self.config, "pb_tp_cap_pct", Decimal("0.02"))),
        )
        # TP must be at least 1.5x SL for minimum reward-to-risk
        min_tp = sl_pct * Decimal("1.5")
        if tp_pct < min_tp:
            tp_pct = min_tp
        return sl_pct, tp_pct

    def _update_dynamic_tbc(self, mid: Decimal, atr: Decimal | None) -> None:
        """Recompute and cache dynamic TripleBarrierConfig on the config object."""
        sl_pct, tp_pct = self._compute_dynamic_barriers(mid, atr)
        try:
            base_tbc = super(PullbackV1Config, self.config).triple_barrier_config
            dynamic_tbc = base_tbc.model_copy(
                update={"stop_loss": float(sl_pct), "take_profit": float(tp_pct)}
            )
            object.__setattr__(self.config, "_pb_dynamic_tbc", dynamic_tbc)
        except Exception:
            _logger.debug("Failed to update dynamic TBC, using static", exc_info=True)
            try:
                object.__setattr__(self.config, "_pb_dynamic_tbc", None)
            except Exception:
                pass
        self._pb_state["dynamic_sl"] = sl_pct
        self._pb_state["dynamic_tp"] = tp_pct

    # ── Trend quality gates (tasks 3.1, 3.2) ────────────────────────────

    def _check_basis_slope(self, side: str) -> tuple[bool, Decimal]:
        """Check that BB basis (SMA) slope confirms the trade direction.

        Uses the BB basis period SMA so the slope reflects the smoothed trend,
        not tick-level noise.  Falls back to permissive during warmup.

        Returns (gate_passed, slope_pct).
        """
        if not bool(getattr(self.config, "pb_trend_quality_enabled", True)):
            return True, _ZERO
        lookback = int(getattr(self.config, "pb_basis_slope_bars", 5))
        bb_period = int(getattr(self.config, "pb_bb_period", 20))
        price_buffer = getattr(self, "_price_buffer", None)
        bars = list(getattr(price_buffer, "bars", []) or [])
        # Need enough bars to compute SMA at two points separated by lookback
        if len(bars) < bb_period + lookback:
            return True, _ZERO  # permissive during warmup
        # Compute SMA (BB basis) at current bar and lookback bars ago
        current_closes = [b.close for b in bars[-bb_period:]]
        past_closes = [b.close for b in bars[-(bb_period + lookback):-(lookback)]]
        current_sma = sum(current_closes, _ZERO) / Decimal(len(current_closes))
        past_sma = sum(past_closes, _ZERO) / Decimal(len(past_closes))
        if past_sma <= _ZERO:
            return True, _ZERO
        slope_pct = (current_sma - past_sma) / past_sma
        min_slope = to_decimal(getattr(self.config, "pb_min_basis_slope_pct", Decimal("0.0002")))
        if side == "buy":
            return slope_pct >= min_slope, slope_pct
        elif side == "sell":
            return slope_pct <= -min_slope, slope_pct
        return True, slope_pct

    def _check_trend_sma(self, mid: Decimal, side: str) -> tuple[bool, Decimal | None]:
        """Check mid is on the correct side of the long-period SMA.

        Returns (gate_passed, sma_value).
        """
        if not bool(getattr(self.config, "pb_trend_quality_enabled", True)):
            return True, None
        period = int(getattr(self.config, "pb_trend_sma_period", 50))
        sma = self._price_buffer.sma(period)
        if sma is None:
            return True, None  # permissive during warmup
        if side == "buy":
            return mid > sma, sma
        elif side == "sell":
            return mid < sma, sma
        return True, sma

    # ── Volume-declining pullback filter ──────────────────────────────────

    def _check_volume_decline(self, trades: list[MarketTrade]) -> bool:
        """Check that trade volume is declining during the pullback.

        Healthy pullbacks see decreasing volume as price retraces.
        Splits recent trades into windows and requires at least 2/3
        of consecutive pairs to show decline (with 10% noise tolerance).
        Permissive when data insufficient.
        """
        if not bool(getattr(self.config, "pb_vol_decline_enabled", True)):
            return True
        lookback = int(getattr(self.config, "pb_vol_decline_lookback", 5))
        if len(trades) < lookback * 2:
            return True
        window_size = len(trades) // lookback
        if window_size < 1:
            return True
        windows: list[Decimal] = []
        for i in range(lookback):
            start = i * window_size
            end = start + window_size
            vol = sum((t.size for t in trades[start:end]), _ZERO)
            windows.append(vol)
        pairs = len(windows) - 1
        if pairs <= 0:
            return True
        declining = sum(
            1 for i in range(1, len(windows))
            if windows[i] <= windows[i - 1] * Decimal("1.1")
        )
        return declining >= max(1, (pairs * 2 + 2) // 3)

    # ── Time-of-day quality filter ──────────────────────────────────────

    def _in_quality_session(self, now: float) -> tuple[bool, Decimal]:
        """Check if current time is within quality trading hours.

        Returns (in_quality, size_multiplier).
        """
        if not bool(getattr(self.config, "pb_session_filter_enabled", True)):
            return True, _ONE
        import datetime as _dt
        utc_hour = _dt.datetime.fromtimestamp(now, tz=_dt.UTC).hour
        hours_str = str(getattr(self.config, "pb_quality_hours_utc", "1-4,8-16,20-23"))
        in_quality = False
        for segment in hours_str.split(","):
            segment = segment.strip()
            if not segment:
                continue
            if "-" in segment:
                parts = segment.split("-", 1)
                try:
                    lo, hi = int(parts[0]), int(parts[1])
                    if lo <= utc_hour <= hi:
                        in_quality = True
                        break
                except (ValueError, IndexError):
                    continue
            else:
                try:
                    if utc_hour == int(segment):
                        in_quality = True
                        break
                except ValueError:
                    continue
        if in_quality:
            return True, _ONE
        mult = to_decimal(getattr(self.config, "pb_low_quality_size_mult", Decimal("0.5")))
        return False, mult

    # ── Gradient trend confidence ──────────────────────────────────────

    def _compute_trend_confidence(
        self, side: str, adx: Decimal, basis_slope: Decimal, mid: Decimal, trend_sma: Decimal | None,
    ) -> Decimal:
        """Compute a [0, 1] trend confidence score from ADX, slope, and SMA distance.

        Maps to a size multiplier: min_mult + score * (1 - min_mult).
        """
        if not bool(getattr(self.config, "pb_trend_confidence_enabled", True)):
            return _ONE
        # Normalize ADX: 22 → 0, 40 → 1
        adx_min = to_decimal(getattr(self.config, "pb_adx_min", Decimal("22")))
        adx_max = to_decimal(getattr(self.config, "pb_adx_max", Decimal("40")))
        adx_range = adx_max - adx_min
        adx_norm = clip((adx - adx_min) / adx_range, _ZERO, _ONE) if adx_range > _ZERO else _ZERO
        # Normalize slope: min_slope → 0, 3*min_slope → 1
        min_slope = to_decimal(getattr(self.config, "pb_min_basis_slope_pct", Decimal("0.0002")))
        abs_slope = abs(basis_slope)
        slope_norm = clip((abs_slope - min_slope) / (min_slope * Decimal("2")), _ZERO, _ONE) if min_slope > _ZERO else _ZERO
        # Normalize SMA distance: 0 → 0, 0.5% → 1
        sma_norm = _ZERO
        if trend_sma is not None and trend_sma > _ZERO and mid > _ZERO:
            sma_dist = abs(mid - trend_sma) / mid
            sma_norm = clip(sma_dist / Decimal("0.005"), _ZERO, _ONE)
        # Average
        score = (adx_norm + slope_norm + sma_norm) / Decimal("3")
        min_mult = to_decimal(getattr(self.config, "pb_trend_confidence_min_mult", Decimal("0.5")))
        return min_mult + score * (_ONE - min_mult)

    # ── RSI divergence booster ──────────────────────────────────────────

    def _detect_rsi_divergence(self, side: str) -> bool:
        """Detect bullish/bearish RSI divergence over recent bars.

        Bullish: price lower low, RSI higher low.
        Bearish: price higher high, RSI lower high.
        """
        if not bool(getattr(self.config, "pb_rsi_divergence_enabled", True)):
            return False
        lookback = int(getattr(self.config, "pb_rsi_divergence_lookback", 10))
        price_buffer = getattr(self, "_price_buffer", None)
        bars = list(getattr(price_buffer, "bars", []) or [])
        rsi_period = int(getattr(self.config, "pb_rsi_period", 14))
        if len(bars) < rsi_period + lookback:
            return False
        recent_bars = bars[-lookback:]
        half = lookback // 2
        first_half = recent_bars[:half]
        second_half = recent_bars[half:]
        if not first_half or not second_half:
            return False
        # Compute RSI for each bar using simple approximation from close deltas
        all_closes = [b.close for b in bars[-(rsi_period + lookback):]]
        # Build per-bar RSI approximation: use rolling gain/loss
        rsi_values: list[Decimal] = []
        for i in range(rsi_period, len(all_closes)):
            gains = _ZERO
            losses = _ZERO
            for j in range(i - rsi_period + 1, i + 1):
                delta = all_closes[j] - all_closes[j - 1]
                if delta > _ZERO:
                    gains += delta
                else:
                    losses += abs(delta)
            avg_gain = gains / Decimal(rsi_period)
            avg_loss = losses / Decimal(rsi_period)
            if avg_loss == _ZERO:
                rsi_values.append(Decimal("100"))
            else:
                rs = avg_gain / avg_loss
                rsi_values.append(Decimal("100") - Decimal("100") / (_ONE + rs))
        if len(rsi_values) < lookback:
            return False
        rsi_recent = rsi_values[-lookback:]
        rsi_first = rsi_recent[:half]
        rsi_second = rsi_recent[half:]
        if side == "buy":
            # Bullish divergence: price lower low, RSI higher low
            price_first_low = min(b.low for b in first_half)
            price_second_low = min(b.low for b in second_half)
            rsi_first_low = min(rsi_first)
            rsi_second_low = min(rsi_second)
            return price_second_low < price_first_low and rsi_second_low > rsi_first_low
        elif side == "sell":
            # Bearish divergence: price higher high, RSI lower high
            price_first_high = max(b.high for b in first_half)
            price_second_high = max(b.high for b in second_half)
            rsi_first_high = max(rsi_first)
            rsi_second_high = max(rsi_second)
            return price_second_high > price_first_high and rsi_second_high < rsi_first_high
        return False

    # ── Trailing stop state machine (tasks 4.2, 4.3, 4.4) ───────────────

    def _reset_trail_state(self) -> None:
        """Reset all trailing stop and partial take state."""
        self._pb_trail_state = "inactive"
        self._pb_trail_hwm = None
        self._pb_trail_lwm = None
        self._pb_trail_entry_price = None
        self._pb_trail_entry_side = "off"
        self._pb_trail_sl_distance = _ZERO
        self._pb_partial_taken = False

    def _manage_trailing_stop(self, mid: Decimal) -> None:
        """Tick-level trailing stop state machine + partial profit-taking.

        Emits close actions into self._pb_pending_actions when triggered.
        """
        if not bool(getattr(self.config, "pb_trailing_stop_enabled", True)):
            return

        position_base = to_decimal(getattr(self, "_position_base", _ZERO))
        if abs(position_base) < Decimal("1e-8"):
            if self._pb_trail_state != "inactive":
                self._reset_trail_state()
            return

        if mid <= _ZERO:
            return

        entry_price = self._pb_trail_entry_price
        if entry_price is None or entry_price <= _ZERO:
            return

        entry_side = self._pb_trail_entry_side
        atr = to_decimal(self._pb_state.get("atr") or _ZERO)
        if atr <= _ZERO:
            return

        # Compute unrealized PnL pct
        if entry_side == "buy":
            pnl_pct = (mid - entry_price) / entry_price
        elif entry_side == "sell":
            pnl_pct = (entry_price - mid) / entry_price
        else:
            return

        # ── Partial profit-taking at 1R ──────────────────────────────
        if not self._pb_partial_taken and self._pb_trail_sl_distance > _ZERO:
            sl_dist_pct = self._pb_trail_sl_distance
            if pnl_pct >= sl_dist_pct:  # 1R reached
                partial_pct = to_decimal(getattr(self.config, "pb_partial_take_pct", Decimal("0.33")))
                partial_amount = abs(position_base) * partial_pct
                if partial_amount > _ZERO:
                    partial_ot = str(getattr(self.config, "pb_partial_exit_order_type", "LIMIT"))
                    self._emit_close_action(partial_amount, entry_side, "pb_partial_take", order_type=partial_ot)
                    self._pb_partial_taken = True

        # ── Trailing stop activation / tracking / trigger ────────────
        activate_threshold = to_decimal(
            getattr(self.config, "pb_trail_activate_atr_mult", Decimal("1.0"))
        ) * atr / mid
        trail_offset = to_decimal(
            getattr(self.config, "pb_trail_offset_atr_mult", Decimal("0.5"))
        ) * atr

        if self._pb_trail_state == "inactive":
            if pnl_pct >= activate_threshold:
                self._pb_trail_state = "tracking"
                if entry_side == "buy":
                    self._pb_trail_hwm = mid
                else:
                    self._pb_trail_lwm = mid

        elif self._pb_trail_state == "tracking":
            if entry_side == "buy":
                if mid > (self._pb_trail_hwm or mid):
                    self._pb_trail_hwm = mid
                retrace = (self._pb_trail_hwm or mid) - mid
                if retrace >= trail_offset:
                    self._pb_trail_state = "triggered"
            else:  # sell
                if mid < (self._pb_trail_lwm or mid):
                    self._pb_trail_lwm = mid
                retrace = mid - (self._pb_trail_lwm or mid)
                if retrace >= trail_offset:
                    self._pb_trail_state = "triggered"

        if self._pb_trail_state == "triggered":
            close_amount = abs(position_base)
            if close_amount > _ZERO:
                try:
                    self._cancel_active_quote_executors()
                except Exception:
                    _logger.debug("trail: cancel executors failed", exc_info=True)
                trail_ot = str(getattr(self.config, "pb_trail_exit_order_type", "LIMIT"))
                self._emit_close_action(close_amount, entry_side, "pb_trail_close", order_type=trail_ot)
            self._reset_trail_state()

        self._pb_state["trail_state"] = self._pb_trail_state

    def _emit_close_action(
        self, amount: Decimal, entry_side: str, level_id: str, *, order_type: str = "MARKET",
    ) -> None:
        """Emit a close action (MARKET or LIMIT) for the given amount.

        When order_type is LIMIT, the close is placed at current mid with a
        time_limit fallback so the executor cancels and retries as MARKET if
        unfilled within pb_exit_limit_timeout_s.
        """
        try:
            from hummingbot.core.data_type.common import OrderType as _HBOrderType
            from hummingbot.core.data_type.common import TradeType as _TradeType
            from hummingbot.strategy_v2.executors.position_executor.data_types import PositionExecutorConfig
            from hummingbot.strategy_v2.models.executor_actions import CreateExecutorAction

            close_side = _TradeType.SELL if entry_side == "buy" else _TradeType.BUY
            q_amount = self._quantize_amount(amount)
            if q_amount <= _ZERO:
                q_amount = amount

            base_tbc = super(PullbackV1Config, self.config).triple_barrier_config
            use_limit = order_type.upper() == "LIMIT"
            timeout_s = int(getattr(self.config, "pb_exit_limit_timeout_s", 15))
            tbc = base_tbc.model_copy(
                update={
                    "open_order_type": _HBOrderType.LIMIT if use_limit else _HBOrderType.MARKET,
                    "stop_loss": None,
                    "take_profit": None,
                    "time_limit": timeout_s if use_limit else None,
                },
            )
            # For LIMIT close, set entry_price to current mid on the close side
            entry_price = None
            if use_limit:
                try:
                    provider = getattr(self, "market_data_provider", None)
                    if provider is not None:
                        mid = to_decimal(provider.get_price_by_type(
                            str(getattr(self.config, "connector_name", "")),
                            str(self.config.trading_pair),
                            "mid",
                        ))
                        if mid > _ZERO:
                            entry_price = mid
                except Exception:
                    pass  # Fall back to None (MARKET behavior)
            executor_config = PositionExecutorConfig(
                timestamp=self.market_data_provider.time(),
                level_id=level_id,
                connector_name=str(getattr(self.config, "connector_name", "")),
                trading_pair=str(self.config.trading_pair),
                entry_price=entry_price,
                amount=q_amount,
                triple_barrier_config=tbc,
                leverage=int(getattr(self.config, "leverage", 1)),
                side=close_side,
            )
            self._pb_pending_actions.append(
                CreateExecutorAction(
                    controller_id=self.config.id,
                    executor_config=executor_config,
                )
            )
            _logger.info(
                "pullback %s: side=%s amount=%.8f order_type=%s",
                level_id, close_side.name, float(q_amount), order_type,
            )
        except Exception:
            _logger.error("Failed to build %s close action", level_id, exc_info=True)

    # ── Signal diagnostics (tasks 7.1, 7.2, 7.3) ────────────────────────

    _SECONDS_24H = 86_400.0

    def _record_signal(self, now: float) -> None:
        """Record a signal activation and prune old entries."""
        cutoff = now - self._SECONDS_24H
        while self._pb_signal_counter and self._pb_signal_counter[0] < cutoff:
            self._pb_signal_counter.popleft()
        self._pb_signal_counter.append(now)

    def _signal_count_24h(self, now: float) -> int:
        """Return number of signals in the last 24 hours."""
        if not bool(getattr(self.config, "pb_signal_diagnostics_enabled", True)):
            return -1
        cutoff = now - self._SECONDS_24H
        while self._pb_signal_counter and self._pb_signal_counter[0] < cutoff:
            self._pb_signal_counter.popleft()
        return len(self._pb_signal_counter)

    def _check_signal_frequency(self, now: float) -> None:
        """Log warning if signal frequency is too low (rate-limited to 1/hour)."""
        if not bool(getattr(self.config, "pb_signal_diagnostics_enabled", True)):
            return
        count = self._signal_count_24h(now)
        threshold = int(getattr(self.config, "pb_min_signals_warn", 3))
        if count < threshold and (now - self._pb_signal_warn_last_ts) >= 3600.0:
            _logger.warning(
                "pullback signal frequency low: %d signals in 24h (threshold: %d)",
                count, threshold,
            )
            self._pb_signal_warn_last_ts = now

    def _effective_zone_pct(self, mid: Decimal, atr: Decimal | None) -> Decimal:
        """Return the adaptive pullback zone width.

        Uses max(static floor, ATR-derived width) so the zone widens
        in high-volatility conditions and doesn't shrink below the floor.
        """
        static_pct = to_decimal(getattr(self.config, "pb_pullback_zone_pct", Decimal("0.0015")))
        if atr is None or mid <= _ZERO:
            return static_pct
        atr_mult = to_decimal(getattr(self.config, "pb_zone_atr_mult", Decimal("0.25")))
        atr_pct = (atr * atr_mult) / mid
        return max(static_pct, atr_pct)

    def _detect_pullback_zone(
        self,
        *,
        mid: Decimal,
        bb_lower: Decimal,
        bb_basis: Decimal,
        bb_upper: Decimal,
        atr: Decimal | None = None,
    ) -> tuple[bool, bool]:
        """Check if price is in the pullback zone near BB basis.

        Long zone:  bb_lower*(1+floor_pct) <= mid <= bb_basis*(1+zone_pct)
        Short zone: bb_upper*(1-floor_pct) >= mid >= bb_basis*(1-zone_pct)

        zone_pct adapts to ATR when available.
        """
        if mid <= _ZERO or bb_basis <= _ZERO:
            return False, False
        zone_pct = self._effective_zone_pct(mid, atr)
        floor_pct = to_decimal(getattr(self.config, "pb_band_floor_pct", Decimal("0.0010")))
        long_ceil = max(_ZERO, bb_basis * (_ONE + zone_pct))
        long_floor = max(_ZERO, bb_lower * (_ONE + floor_pct))
        short_floor = max(_ZERO, bb_basis * (_ONE - zone_pct))
        short_ceil = max(_ZERO, bb_upper * (_ONE - floor_pct))
        long_zone = mid <= long_ceil and mid >= long_floor
        short_zone = mid >= short_floor and mid <= short_ceil
        return long_zone, short_zone

    def _detect_absorption(
        self,
        *,
        trades: list[MarketTrade],
        mid: Decimal,
        bb_lower: Decimal,
        bb_basis: Decimal,
        bb_upper: Decimal,
        atr: Decimal | None = None,
    ) -> tuple[bool, bool]:
        """Detect absorption in the pullback zone (not band extreme)."""
        if len(trades) < 6 or mid <= _ZERO:
            return False, False
        absorption_window = int(getattr(self.config, "pb_absorption_window", 20))
        recent = trades[-absorption_window:]
        sizes = [trade.size for trade in recent]
        avg_size = sum(sizes, _ZERO) / Decimal(len(recent))
        if avg_size <= _ZERO:
            return False, False
        max_trade = max(sizes, default=_ZERO)
        total_delta = sum((trade.delta for trade in recent), _ZERO)
        first_price = recent[0].price
        last_price = recent[-1].price
        if first_price <= _ZERO or last_price <= _ZERO:
            return False, False
        price_drift_pct = abs(last_price - first_price) / first_price
        drift_ok = price_drift_pct <= to_decimal(
            getattr(self.config, "pb_absorption_max_price_drift_pct", Decimal("0.0015"))
        )
        # Z-score absorption: statistically significant large trade
        use_zscore = bool(getattr(self.config, "pb_absorption_zscore_enabled", True))
        if use_zscore and len(sizes) >= 3:
            n = Decimal(len(sizes))
            variance = sum((s - avg_size) ** 2 for s in sizes) / n
            # Decimal doesn't have sqrt — use float bridge
            stddev = to_decimal(float(variance) ** 0.5)
            zscore_thresh = to_decimal(getattr(self.config, "pb_absorption_zscore_threshold", Decimal("2.0")))
            if stddev > _ZERO:
                size_ok = max_trade >= avg_size + zscore_thresh * stddev
            else:
                # Zero stddev (all same size) — fall back to multiplier
                size_ok = max_trade >= avg_size * to_decimal(
                    getattr(self.config, "pb_absorption_min_trade_mult", Decimal("2.5"))
                )
        else:
            size_ok = max_trade >= avg_size * to_decimal(
                getattr(self.config, "pb_absorption_min_trade_mult", Decimal("2.5"))
            )
        # Check zone at last_price using adaptive zone width
        zone_pct = self._effective_zone_pct(mid, atr)
        floor_pct = to_decimal(getattr(self.config, "pb_band_floor_pct", Decimal("0.0010")))
        in_long_zone = (
            last_price <= bb_basis * (_ONE + zone_pct)
            and last_price >= bb_lower * (_ONE + floor_pct)
        )
        in_short_zone = (
            last_price >= bb_basis * (_ONE - zone_pct)
            and last_price <= bb_upper * (_ONE - floor_pct)
        )
        long_absorption = (
            drift_ok and size_ok and in_long_zone
            and total_delta > avg_size * Decimal("0.5")
        )
        short_absorption = (
            drift_ok and size_ok and in_short_zone
            and total_delta < -(avg_size * Decimal("0.5"))
        )
        return long_absorption, short_absorption

    def _detect_delta_trap(
        self,
        *,
        trades: list[MarketTrade],
        mid: Decimal,
        bb_lower: Decimal,
        bb_basis: Decimal,
        bb_upper: Decimal,
        atr: Decimal | None = None,
    ) -> tuple[bool, bool, Decimal]:
        """Detect delta trap reversal in pullback zone."""
        window = max(8, int(getattr(self.config, "pb_delta_trap_window", 24)))
        if len(trades) < window:
            return False, False, _ZERO
        recent = trades[-window:]
        split_idx = max(
            1,
            int(window * (_ONE - to_decimal(getattr(self.config, "pb_delta_trap_reversal_share", Decimal("0.30")))))
        )
        early = recent[:split_idx]
        late = recent[split_idx:]
        if not early or not late or recent[0].price <= _ZERO:
            return False, False, _ZERO
        early_delta = sum((trade.delta for trade in early), _ZERO)
        late_delta = sum((trade.delta for trade in late), _ZERO)
        total_delta = early_delta + late_delta
        price_change_pct = (recent[-1].price - recent[0].price) / recent[0].price

        # Configurable price drift tolerance (wider than old hardcoded 10bps)
        max_drift = to_decimal(
            getattr(self.config, "pb_delta_trap_max_price_drift_pct", Decimal("0.0020"))
        )

        # Pullback zone check using adaptive zone width
        zone_pct = self._effective_zone_pct(mid, atr)
        floor_pct = to_decimal(getattr(self.config, "pb_band_floor_pct", Decimal("0.0010")))
        last_price = recent[-1].price
        in_long_zone = (
            last_price <= bb_basis * (_ONE + zone_pct)
            and last_price >= bb_lower * (_ONE + floor_pct)
        )
        in_short_zone = (
            last_price >= bb_basis * (_ONE - zone_pct)
            and last_price <= bb_upper * (_ONE - floor_pct)
        )
        bullish = (
            in_long_zone
            and total_delta < _ZERO
            and late_delta > _ZERO
            and price_change_pct >= -max_drift
        )
        bearish = (
            in_short_zone
            and total_delta > _ZERO
            and late_delta < _ZERO
            and price_change_pct <= max_drift
        )
        return bullish, bearish, total_delta

    def _load_recent_trades(self) -> list[MarketTrade]:
        reader = getattr(self, "_trade_reader", None)
        if reader is None:
            return []
        try:
            return reader.recent_trades(count=int(getattr(self.config, "pb_trade_window_count", 160)))
        except Exception as exc:
            _logger.debug("pullback _load_recent_trades failed: %s", exc)
            return []

    def _update_pb_state(self, mid: Decimal, regime_name: str) -> dict[str, Any]:
        bb_period = int(getattr(self.config, "pb_bb_period", 20))
        rsi_period = int(getattr(self.config, "pb_rsi_period", 14))
        adx_period = int(getattr(self.config, "pb_adx_period", 14))
        atr_period = int(getattr(self.config, "atr_period", 14))
        price_buffer = getattr(self, "_price_buffer", None)
        bar_count = len(getattr(price_buffer, "bars", []) or [])

        bands = self._price_buffer.bollinger_bands(
            period=bb_period,
            stddev_mult=to_decimal(getattr(self.config, "pb_bb_stddev", Decimal("2.0"))),
        )
        rsi = self._price_buffer.rsi(rsi_period)
        adx = self._price_buffer.adx(adx_period)
        atr = self._price_buffer.atr(atr_period)
        trades = self._load_recent_trades()
        trade_age_ms = self._trade_age_ms(trades)
        trade_stale = trade_age_ms > int(getattr(self.config, "pb_trade_stale_after_ms", 20_000))
        funding_rate = to_decimal(getattr(self, "_funding_rate", _ZERO))
        funding_bias = self._funding_bias(funding_rate)
        funding_risk_scale = self._funding_risk_scale(funding_rate)
        depth_imbalance = _ZERO
        reader = getattr(self, "_trade_reader", None)
        if reader is not None:
            try:
                depth_imbalance = clip(to_decimal(reader.get_depth_imbalance(depth=5)), _NEG_ONE, _ONE)
            except Exception as exc:
                _logger.debug("pullback depth_imbalance read failed: %s", exc)

        provider = getattr(self, "market_data_provider", None)
        now_float: float = float(provider.time()) if provider is not None else _time_mod.time()

        if mid <= _ZERO:
            self._pb_state = self._empty_pb_state()
            self._pb_state.update({
                "reason": "indicator_warmup",
                "trade_age_ms": trade_age_ms,
                "trade_flow_stale": trade_stale,
                "funding_bias": funding_bias,
                "funding_risk_scale": funding_risk_scale,
                "order_book_imbalance": depth_imbalance,
                "indicator_ready": False,
                "indicator_missing": "mid",
                "price_buffer_bars": bar_count,
            })
            return self._pb_state

        indicator_missing: list[str] = []
        if bands is None:
            indicator_missing.append("bands")
        if rsi is None:
            indicator_missing.append("rsi")
        if adx is None:
            indicator_missing.append("adx")
        indicator_ready = len(indicator_missing) == 0
        atr_ready = atr is not None

        if not indicator_ready:
            self._pb_state = self._empty_pb_state()
            self._pb_state.update({
                "reason": "indicator_warmup",
                "trade_age_ms": trade_age_ms,
                "trade_flow_stale": trade_stale,
                "funding_bias": funding_bias,
                "funding_risk_scale": funding_risk_scale,
                "order_book_imbalance": depth_imbalance,
                "indicator_ready": False,
                "indicator_missing": ",".join(indicator_missing),
                "price_buffer_bars": bar_count,
            })
            return self._pb_state

        bb_lower, bb_basis, bb_upper = bands

        # ── Regime gate ─────────────────────────────────────────────────
        # Only "up" and "down" enable entry; neutral/shock block it.
        regime_up = regime_name == "up"
        regime_down = regime_name == "down"
        regime_directional = regime_up or regime_down

        # ── Time-of-day quality filter ──────────────────────────────────
        session_quality, session_size_mult = self._in_quality_session(now_float)

        # ── ADX range gate ───────────────────────────────────────────────
        adx_min = to_decimal(getattr(self.config, "pb_adx_min", Decimal("22")))
        adx_max = to_decimal(getattr(self.config, "pb_adx_max", Decimal("40")))
        adx_in_range = adx_min <= adx <= adx_max

        # ── Trend quality gates (basis slope + long-period SMA) ─────────────
        slope_long_ok, basis_slope = self._check_basis_slope("buy")
        slope_short_ok, _ = self._check_basis_slope("sell")
        sma_long_ok, trend_sma = self._check_trend_sma(mid, "buy")
        sma_short_ok, _ = self._check_trend_sma(mid, "sell")

        # ── Pullback zone (ATR-adaptive) ──────────────────────────────────
        in_pullback_zone_long, in_pullback_zone_short = self._detect_pullback_zone(
            mid=mid,
            bb_lower=bb_lower,
            bb_basis=bb_basis,
            bb_upper=bb_upper,
            atr=atr,
        )

        # ── Volume-declining pullback filter ──────────────────────────────
        vol_declining = self._check_volume_decline(trades)

        # ── Absorption / delta-trap in pullback zone ─────────────────────
        absorption_long, absorption_short = self._detect_absorption(
            trades=trades,
            mid=mid,
            bb_lower=bb_lower,
            bb_basis=bb_basis,
            bb_upper=bb_upper,
            atr=atr,
        )
        delta_trap_long, delta_trap_short, cvd = self._detect_delta_trap(
            trades=trades,
            mid=mid,
            bb_lower=bb_lower,
            bb_basis=bb_basis,
            bb_upper=bb_upper,
            atr=atr,
        )

        # ── RSI gate ────────────────────────────────────────────────────
        rsi_long_min = to_decimal(getattr(self.config, "pb_rsi_long_min", Decimal("35")))
        rsi_long_max = to_decimal(getattr(self.config, "pb_rsi_long_max", Decimal("55")))
        rsi_short_min = to_decimal(getattr(self.config, "pb_rsi_short_min", Decimal("45")))
        rsi_short_max = to_decimal(getattr(self.config, "pb_rsi_short_max", Decimal("65")))
        rsi_probe_long_min = to_decimal(getattr(self.config, "pb_rsi_probe_long_min", Decimal("38")))
        rsi_probe_long_max = to_decimal(getattr(self.config, "pb_rsi_probe_long_max", Decimal("58")))
        rsi_probe_short_min = to_decimal(getattr(self.config, "pb_rsi_probe_short_min", Decimal("42")))
        rsi_probe_short_max = to_decimal(getattr(self.config, "pb_rsi_probe_short_max", Decimal("62")))
        rsi_long_ok = rsi_long_min <= rsi <= rsi_long_max
        rsi_short_ok = rsi_short_min <= rsi <= rsi_short_max
        rsi_probe_long_ok = rsi_probe_long_min <= rsi <= rsi_probe_long_max
        rsi_probe_short_ok = rsi_probe_short_min <= rsi <= rsi_probe_short_max

        # ── Recent delta ────────────────────────────────────────────────
        recent_delta_window = int(getattr(self.config, "pb_recent_delta_window", 20))
        recent_delta = sum((trade.delta for trade in trades[-recent_delta_window:]), _ZERO) if trades else _ZERO
        delta_volume = sum((trade.delta for trade in trades), _ZERO) if trades else _ZERO

        # ── Depth imbalance (secondary confirmation only) ────────────────
        imbalance_threshold = to_decimal(
            getattr(self.config, "pb_depth_imbalance_threshold", Decimal("0.20"))
        )

        # ── Primary signal gates ─────────────────────────────────────────
        primary_long = absorption_long or delta_trap_long
        primary_short = absorption_short or delta_trap_short

        # Session hard-block: if size_mult is 0, block entirely during off-hours
        session_hard_block = not session_quality and session_size_mult <= _ZERO

        long_signal = (
            regime_up
            and adx_in_range
            and slope_long_ok
            and sma_long_ok
            and in_pullback_zone_long
            and vol_declining
            and rsi_long_ok
            and not trade_stale
            and primary_long
            and not session_hard_block
        )
        short_signal = (
            regime_down
            and adx_in_range
            and slope_short_ok
            and sma_short_ok
            and in_pullback_zone_short
            and vol_declining
            and rsi_short_ok
            and not trade_stale
            and primary_short
            and not session_hard_block
        )

        probe_enabled = bool(getattr(self.config, "pb_probe_enabled", True))
        long_probe = (
            probe_enabled
            and regime_up
            and adx_in_range
            and slope_long_ok
            and sma_long_ok
            and in_pullback_zone_long
            and vol_declining
            and rsi_probe_long_ok
            and not trade_stale
            and primary_long
            and not session_hard_block
        )
        short_probe = (
            probe_enabled
            and regime_down
            and adx_in_range
            and slope_short_ok
            and sma_short_ok
            and in_pullback_zone_short
            and vol_declining
            and rsi_probe_short_ok
            and not trade_stale
            and primary_short
            and not session_hard_block
        )

        side = "off"
        probe_mode = False
        reason = "no_entry"

        if long_signal and not short_signal:
            side = "buy"
            reason = "pullback_long"
        elif short_signal and not long_signal:
            side = "sell"
            reason = "pullback_short"
        elif long_probe and not short_probe:
            side = "buy"
            reason = "probe_long"
            probe_mode = True
        elif short_probe and not long_probe:
            side = "sell"
            reason = "probe_short"
            probe_mode = True
        elif session_hard_block:
            reason = "off_hours"
        elif trade_stale:
            reason = "trade_flow_stale"
        elif not regime_directional:
            reason = "regime_inactive"
        elif not adx_in_range:
            reason = "adx_out_of_range"
        elif (regime_up and adx_in_range and not slope_long_ok) or (regime_down and adx_in_range and not slope_short_ok):
            reason = "basis_slope_flat"
        elif (regime_up and adx_in_range and not sma_long_ok) or (regime_down and adx_in_range and not sma_short_ok):
            reason = "trend_sma_against"
        elif not vol_declining:
            reason = "vol_not_declining"

        # ── no_entry sub-reason diagnostic ────────────────────────────────
        no_entry_detail = ""
        if reason == "no_entry":
            missing: list[str] = []
            if regime_up:
                if not in_pullback_zone_long:
                    missing.append("zone")
                if not rsi_long_ok and not rsi_probe_long_ok:
                    missing.append("rsi")
                if not primary_long:
                    if not absorption_long:
                        missing.append("absorption")
                    if not delta_trap_long:
                        missing.append("delta_trap")
            elif regime_down:
                if not in_pullback_zone_short:
                    missing.append("zone")
                if not rsi_short_ok and not rsi_probe_short_ok:
                    missing.append("rsi")
                if not primary_short:
                    if not absorption_short:
                        missing.append("absorption")
                    if not delta_trap_short:
                        missing.append("delta_trap")
            no_entry_detail = ",".join(missing) if missing else "conflict"

        # ── Contra-funding gate ─────────────────────────────────────────
        # Block entry when funding actively opposes trade direction:
        # going long while shorts get paid, or short while longs get paid.
        block_contra = bool(getattr(self.config, "pb_block_contra_funding", True))
        if side != "off" and block_contra:
            contra = (side == "buy" and funding_bias == "short") or (
                side == "sell" and funding_bias == "long"
            )
            if contra:
                side = "off"
                probe_mode = False
                reason = "contra_funding"

        # ── Adverse selection filter ──────────────────────────────────────
        if side != "off" and bool(getattr(self.config, "pb_adverse_selection_enabled", True)):
            max_spread = to_decimal(getattr(self.config, "pb_max_entry_spread_pct", Decimal("0.0008")))
            max_imbalance = to_decimal(getattr(self.config, "pb_max_entry_imbalance", Decimal("0.5")))
            # Check spread width from market data (top-of-book)
            current_spread = _ZERO
            try:
                _reader = getattr(self, "_trade_reader", None)
                if _reader is not None:
                    _tob = _reader.get_top_of_book()
                    if _tob is not None:
                        current_spread = to_decimal(getattr(_tob, "spread_pct", _ZERO))
            except Exception:
                pass
            if current_spread > max_spread and max_spread > _ZERO:
                side = "off"
                probe_mode = False
                reason = "adverse_selection_spread"
            elif (side == "buy" and depth_imbalance < -max_imbalance) or (side == "sell" and depth_imbalance > max_imbalance):
                side = "off"
                probe_mode = False
                reason = "adverse_selection_depth"

        # ── Signal cooldown gate ─────────────────────────────────────────
        if side != "off" and self._signal_cooldown_active(side, now_float):
            side = "off"
            probe_mode = False
            reason = "signal_cooldown"

        # Record activation timestamp for winning side + signal diagnostics
        if side != "off":
            self._pb_last_signal_ts[side] = now_float
            self._record_signal(now_float)

        # ── Signal freshness tracking ──────────────────────────────────────
        if side != "off":
            if side != self._pb_signal_last_side:
                self._pb_signal_timestamp = now_float
                self._pb_signal_last_side = side
        else:
            self._pb_signal_last_side = "off"
        signal_age_s = int(now_float - self._pb_signal_timestamp) if self._pb_signal_timestamp > 0 else 0

        # ── Trend confidence (gradient) ──────────────────────────────────
        trend_confidence = _ONE
        if side != "off":
            trend_confidence = self._compute_trend_confidence(
                side=side, adx=adx, basis_slope=basis_slope,
                mid=mid, trend_sma=trend_sma,
            )

        # ── RSI divergence booster ──────────────────────────────────────
        rsi_divergence = False
        if side != "off":
            rsi_divergence = self._detect_rsi_divergence(side)
            if rsi_divergence:
                trend_confidence = min(trend_confidence * Decimal("1.2"), _ONE)

        # ── Signal score (independent confirmations only) ─────────────────
        # Each component is an independent signal that may or may not co-occur.
        # regime/adx/zone/RSI are prerequisites (always true when side != "off")
        # so they are NOT counted — only additive confirmation matters.
        secondary_long = depth_imbalance >= imbalance_threshold and recent_delta >= _ZERO
        secondary_short = depth_imbalance <= -imbalance_threshold and recent_delta <= _ZERO
        funding_aligned_long = funding_bias in ("long", "neutral")
        funding_aligned_short = funding_bias in ("short", "neutral")
        if side == "buy":
            signal_components = sum(1 for flag in (
                absorption_long, delta_trap_long, secondary_long, funding_aligned_long,
            ) if flag)
        elif side == "sell":
            signal_components = sum(1 for flag in (
                absorption_short, delta_trap_short, secondary_short, funding_aligned_short,
            ) if flag)
        else:
            signal_components = 0
        # Denominator 4 = count of independent confirmation signals:
        # absorption, delta_trap, secondary (depth+delta), funding_aligned
        signal_score = clip(Decimal(signal_components) / _FOUR, _ZERO, _ONE)

        # ── Adaptive grid spacing ────────────────────────────────────────
        bb_width = (bb_upper - bb_lower) / mid if mid > _ZERO else _ZERO
        bb_fraction = to_decimal(getattr(self.config, "pb_grid_spacing_bb_fraction", Decimal("0.12")))
        bb_spacing = bb_width * bb_fraction
        atr_spacing = (
            (atr * to_decimal(getattr(self.config, "pb_grid_spacing_atr_mult", Decimal("0.50"))) / mid)
            if atr is not None and mid > _ZERO
            else None
        )
        raw_spacing = min(bb_spacing, atr_spacing) if atr_spacing is not None else bb_spacing
        spacing_pct = clip(
            raw_spacing if raw_spacing > _ZERO else _ZERO,
            to_decimal(getattr(self.config, "pb_grid_spacing_floor_pct", Decimal("0.0015"))),
            to_decimal(getattr(self.config, "pb_grid_spacing_cap_pct", Decimal("0.0100"))),
        )

        # ── Grid sizing ──────────────────────────────────────────────────
        grid_levels = 0
        if side != "off":
            grid_levels = min(
                int(getattr(self.config, "pb_max_grid_legs", 3)),
                max(1, int((signal_score * Decimal(getattr(self.config, "pb_max_grid_legs", 3))).to_integral_value(rounding="ROUND_CEILING"))),
            )
            if probe_mode:
                grid_levels = min(grid_levels, max(1, int(getattr(self.config, "pb_probe_grid_legs", 1))))

        per_leg_risk = to_decimal(getattr(self.config, "pb_per_leg_risk_pct", Decimal("0.008")))
        target_abs = clip(
            per_leg_risk * Decimal(grid_levels) * funding_risk_scale,
            _ZERO,
            to_decimal(getattr(self.config, "pb_total_grid_exposure_cap_pct", Decimal("0.025"))),
        )
        if probe_mode:
            target_abs *= clip(to_decimal(getattr(self.config, "pb_probe_size_mult", Decimal("0.50"))), _ZERO, _ONE)
        target_net_base_pct = target_abs if side == "buy" else (-target_abs if side == "sell" else _ZERO)
        hedge_target_base_pct = abs(target_net_base_pct) * to_decimal(
            getattr(self.config, "pb_hedge_ratio", Decimal("0.30"))
        )

        self._pb_state = {
            "active": side != "off",
            "probe_mode": probe_mode,
            "side": side,
            "reason": reason,
            "bb_lower": bb_lower,
            "bb_basis": bb_basis,
            "bb_upper": bb_upper,
            "rsi": rsi,
            "adx": adx,
            "atr": atr,
            "grid_spacing_pct": spacing_pct,
            "trade_age_ms": trade_age_ms,
            "trade_flow_stale": trade_stale,
            "cvd": cvd,
            "delta_volume": delta_volume,
            "recent_delta": recent_delta,
            "absorption_long": absorption_long,
            "absorption_short": absorption_short,
            "delta_trap_long": delta_trap_long,
            "delta_trap_short": delta_trap_short,
            "in_pullback_zone_long": in_pullback_zone_long,
            "in_pullback_zone_short": in_pullback_zone_short,
            "signal_score": signal_score,
            "grid_levels": grid_levels,
            "target_net_base_pct": target_net_base_pct,
            "hedge_target_base_pct": hedge_target_base_pct,
            "funding_bias": funding_bias,
            "funding_risk_scale": funding_risk_scale,
            "order_book_imbalance": depth_imbalance,
            "indicator_ready": True,
            "indicator_missing": "" if atr_ready else "atr",
            "price_buffer_bars": bar_count,
            "basis_slope": basis_slope,
            "trend_sma": trend_sma,
            "trail_state": self._pb_trail_state,
            "signal_count_24h": self._signal_count_24h(now_float),
            "dynamic_sl": _ZERO,
            "dynamic_tp": _ZERO,
            "absorption_zscore": _ZERO,
            "no_entry_detail": no_entry_detail,
            "vol_declining": vol_declining,
            "session_quality": session_quality,
            "session_size_mult": session_size_mult,
            "trend_confidence": trend_confidence,
            "rsi_divergence": rsi_divergence,
            "signal_age_s": signal_age_s,
            "adaptive_cooldown_s": int(getattr(self, "_pb_state", {}).get("adaptive_cooldown_s", 180)),
        }

        # Signal frequency diagnostics
        self._check_signal_frequency(now_float)

        return self._pb_state

    def _resolve_regime_and_targets(self, mid: Decimal) -> tuple[str, RegimeSpec, Decimal, Decimal, Decimal]:
        regime_name, regime_spec, target_base_pct, target_net_base_pct, band_pct = super()._resolve_regime_and_targets(mid)
        state = self._update_pb_state(mid=mid, regime_name=regime_name)

        # Update dynamic ATR-scaled barriers for executor creation
        atr = state.get("atr")
        self._update_dynamic_tbc(mid, atr)

        # Record entry price when a new signal fires and we have no position tracking
        if state.get("active") and self._pb_trail_entry_price is None:
            self._pb_trail_entry_price = mid
            self._pb_trail_entry_side = str(state.get("side", "off"))
            sl_pct, _ = self._compute_dynamic_barriers(mid, atr)
            self._pb_trail_sl_distance = sl_pct

        # Run trailing stop + partial take state machine
        self._manage_trailing_stop(mid)

        if bool(getattr(self, "_is_perp", False)):
            target_net_base_pct = to_decimal(state.get("target_net_base_pct", _ZERO))
        return regime_name, regime_spec, target_base_pct, target_net_base_pct, band_pct

    def _force_cancel_orphaned_orders(self) -> int:
        """Cancel orphaned resting orders not managed by any active executor."""
        try:
            connector = self._connector()
            open_orders_fn = getattr(connector, "get_open_orders", None)
            if not callable(open_orders_fn):
                return 0
            strategy = getattr(self, "strategy", None) or getattr(self, "_strategy", None)
            cancel_fn = getattr(strategy, "cancel", None) if strategy is not None else None
            if not callable(cancel_fn):
                return 0

            executor_order_ids: set[str] = set()
            for executor in self.executors_info:
                if not bool(getattr(executor, "is_active", False)):
                    continue
                for attr in ("order_id", "close_order_id"):
                    oid = str(getattr(executor, attr, "") or "")
                    if oid:
                        executor_order_ids.add(oid)
                for ao in getattr(executor, "active_orders", []) or []:
                    oid = str(getattr(ao, "client_order_id", "") or getattr(ao, "order_id", "") or "")
                    if oid:
                        executor_order_ids.add(oid)

            connector_name = str(getattr(self.config, "connector_name", "") or "")
            trading_pair = str(self.config.trading_pair)
            canceled = 0
            for order in list(open_orders_fn() or []):
                if str(getattr(order, "trading_pair", "")) != trading_pair:
                    continue
                order_id = str(
                    getattr(order, "client_order_id", "")
                    or getattr(order, "order_id", "")
                    or ""
                )
                if not order_id or order_id in executor_order_ids:
                    continue
                try:
                    cancel_fn(connector_name, trading_pair, order_id)
                    canceled += 1
                except Exception as exc:
                    _logger.debug("pullback force-cancel failed for order %s: %s", order_id, exc)

            try:
                canceled += self._cancel_active_runtime_orders()
            except Exception as exc:
                _logger.debug("pullback _cancel_active_runtime_orders failed: %s", exc)

            if canceled > 0:
                _logger.info("pullback force-cancel: canceled %d orphaned order(s)", canceled)
                self._recently_issued_levels = {}
            return canceled
        except Exception:
            _logger.debug("pullback force-cancel failed", exc_info=True)
            return 0

    _BLOCKING_REASONS = frozenset({
        "indicator_warmup", "regime_inactive", "trade_flow_stale",
        "off_hours", "contra_funding",
    })

    _PB_CANCEL_SWEEP_COOLDOWN_S: float = 2.0

    def _resolve_quote_side_mode(
        self,
        *,
        mid: Decimal,
        regime_name: str,
        regime_spec: RegimeSpec,
    ) -> str:
        state = getattr(self, "_pb_state", None) or self._empty_pb_state()
        side = str(state.get("side", "off"))
        reason = str(state.get("reason", "inactive"))
        previous_mode = str(getattr(self, "_quote_side_mode", "off") or "off")
        desired_mode = "buy_only" if side == "buy" else ("sell_only" if side == "sell" else "off")
        if previous_mode != desired_mode:
            self._pending_stale_cancel_actions.extend(
                self._cancel_stale_side_executors(previous_mode, desired_mode)
            )
        if desired_mode == "off":
            self._pb_off_ticks = getattr(self, "_pb_off_ticks", 0) + 1
            self._pending_stale_cancel_actions.extend(self._cancel_active_quote_executors())

            now = float(getattr(getattr(self, "market_data_provider", None), "time", lambda: 0)() or 0) or _time_mod.time()
            last_sweep = float(getattr(self, "_pb_cancel_sweep_last_ts", 0.0) or 0.0)
            if (now - last_sweep) >= self._PB_CANCEL_SWEEP_COOLDOWN_S:
                self._pb_cancel_sweep_last_ts = now
                self._force_cancel_orphaned_orders()
                self._cancel_alpha_no_trade_orders()
                try:
                    self._cancel_active_runtime_orders()
                except Exception:
                    _logger.debug("pullback: continuous cancel sweep failed", exc_info=True)
        else:
            self._pb_off_ticks = 0
        self._quote_side_mode = desired_mode
        self._quote_side_reason = f"pb_{reason}"
        return desired_mode

    def _compute_levels_and_sizing(
        self,
        regime_name: str,
        regime_spec: RegimeSpec,
        spread_state: SpreadEdgeState,
        equity_quote: Decimal,
        mid: Decimal,
        market: MarketConditions,
    ) -> tuple[list[Decimal], list[Decimal], Decimal, Decimal]:
        plan = self.build_runtime_execution_plan(
            RuntimeDataContext(
                now_ts=float(self.market_data_provider.time()),
                mid=mid,
                regime_name=regime_name,
                regime_spec=regime_spec,
                spread_state=spread_state,
                market=market,
                equity_quote=equity_quote,
                target_base_pct=regime_spec.target_base_pct,
                target_net_base_pct=to_decimal(getattr(self, "processed_data", {}).get("target_net_base_pct", regime_spec.target_base_pct)),
                base_pct_gross=to_decimal(getattr(self, "processed_data", {}).get("base_pct", _ZERO)),
                base_pct_net=to_decimal(getattr(self, "processed_data", {}).get("net_base_pct", _ZERO)),
            )
        )
        return plan.buy_spreads, plan.sell_spreads, plan.projected_total_quote, plan.size_mult

    def build_runtime_execution_plan(self, data_context: RuntimeDataContext) -> RuntimeExecutionPlan:
        state = getattr(self, "_pb_state", None) or self._update_pb_state(
            mid=data_context.mid,
            regime_name=data_context.regime_name,
        )
        levels = int(state.get("grid_levels", 0) or 0)
        self._runtime_levels.executor_refresh_time = int(data_context.regime_spec.refresh_s)
        self._resolve_quote_side_mode(
            mid=data_context.mid,
            regime_name=data_context.regime_name,
            regime_spec=data_context.regime_spec,
        )
        if not bool(state.get("active")) or levels <= 0:
            warmup_levels = max(0, int(getattr(self.config, "pb_warmup_quote_levels", 0)))
            warmup_quote_max_bars = max(0, int(getattr(self.config, "pb_warmup_quote_max_bars", 3)))
            warmup_price_buffer_bars = int(state.get("price_buffer_bars", 0) or 0)
            if warmup_levels <= 0:
                return RuntimeExecutionPlan(
                    family="directional",
                    buy_spreads=[],
                    sell_spreads=[],
                    projected_total_quote=_ZERO,
                    size_mult=_ZERO,
                    metadata={"strategy_lane": "pb", "quote_side_mode": self._quote_side_mode},
                )
            warmup_reason = str(state.get("reason", "inactive"))
            if warmup_reason != "indicator_warmup" or warmup_price_buffer_bars > warmup_quote_max_bars:
                return RuntimeExecutionPlan(
                    family="directional",
                    buy_spreads=[],
                    sell_spreads=[],
                    projected_total_quote=_ZERO,
                    size_mult=_ZERO,
                    metadata={"strategy_lane": "pb", "quote_side_mode": self._quote_side_mode},
                )
            spacing_pct = max(
                data_context.market.side_spread_floor,
                to_decimal(getattr(self.config, "pb_grid_spacing_floor_pct", Decimal("0.0015"))),
                Decimal("0.000001"),
            )
            buy_spreads = [spacing_pct * Decimal(level + 1) for level in range(warmup_levels)]
            sell_spreads = [spacing_pct * Decimal(level + 1) for level in range(warmup_levels)]
            size_mult = self._compute_pnl_governor_size_mult(
                equity_quote=data_context.equity_quote,
                turnover_x=data_context.spread_state.turnover_x,
            ) * to_decimal(state.get("funding_risk_scale", _ONE))
            projected_total_quote = self._project_total_amount_quote(
                equity_quote=data_context.equity_quote,
                mid=data_context.mid,
                quote_size_pct=data_context.regime_spec.quote_size_pct,
                total_levels=len(buy_spreads) + len(sell_spreads),
                size_mult=size_mult,
            )
            return RuntimeExecutionPlan(
                family="directional",
                buy_spreads=buy_spreads,
                sell_spreads=sell_spreads,
                projected_total_quote=projected_total_quote,
                size_mult=size_mult,
                metadata={
                    "strategy_lane": "pb",
                    "quote_side_mode": self._quote_side_mode,
                    "quote_side_reason": self._quote_side_reason,
                    "grid_levels": warmup_levels,
                    "warmup_quote_excluded_from_viability": True,
                },
            )

        # ── Signal freshness check ──────────────────────────────────────
        if bool(getattr(self.config, "pb_signal_freshness_enabled", True)):
            max_age = int(getattr(self.config, "pb_signal_max_age_s", 120))
            signal_ts = getattr(self, "_pb_signal_timestamp", 0.0)
            if signal_ts > 0 and (data_context.now_ts - signal_ts) > max_age:
                _logger.debug("pullback signal stale: age=%ds > %ds", int(data_context.now_ts - signal_ts), max_age)
                return RuntimeExecutionPlan(
                    family="directional",
                    buy_spreads=[],
                    sell_spreads=[],
                    projected_total_quote=_ZERO,
                    size_mult=_ZERO,
                    metadata={"strategy_lane": "pb", "quote_side_mode": self._quote_side_mode, "stale_signal": True},
                )

        spacing_pct = max(
            data_context.market.side_spread_floor,
            to_decimal(state.get("grid_spacing_pct", data_context.spread_state.spread_pct)),
            Decimal("0.000001"),
        )
        buy_spreads: list[Decimal] = []
        sell_spreads: list[Decimal] = []
        side = str(state.get("side", "off"))

        # ── Limit entry at zone boundary ──────────────────────────────────
        limit_entry = bool(getattr(self.config, "pb_limit_entry_enabled", True))
        bb_basis = to_decimal(state.get("bb_basis", _ZERO))
        entry_offset = to_decimal(getattr(self.config, "pb_entry_offset_pct", Decimal("0.001")))
        floor_spacing = to_decimal(getattr(self.config, "pb_grid_spacing_floor_pct", Decimal("0.0015")))

        if side == "buy":
            if limit_entry and bb_basis > _ZERO and data_context.mid > _ZERO:
                target_price = bb_basis * (_ONE - entry_offset)
                first_spread = max((data_context.mid - target_price) / data_context.mid, floor_spacing)
            else:
                first_spread = spacing_pct
            buy_spreads = [first_spread] + [spacing_pct * Decimal(level + 1) for level in range(1, levels)]
        elif side == "sell":
            if limit_entry and bb_basis > _ZERO and data_context.mid > _ZERO:
                target_price = bb_basis * (_ONE + entry_offset)
                first_spread = max((target_price - data_context.mid) / data_context.mid, floor_spacing)
            else:
                first_spread = spacing_pct
            sell_spreads = [first_spread] + [spacing_pct * Decimal(level + 1) for level in range(1, levels)]

        # Override executor refresh time for limit entry timeout
        if limit_entry and side != "off":
            entry_timeout = int(getattr(self.config, "pb_entry_timeout_s", 30))
            self._runtime_levels.executor_refresh_time = entry_timeout
        size_mult = self._compute_pnl_governor_size_mult(
            equity_quote=data_context.equity_quote,
            turnover_x=data_context.spread_state.turnover_x,
        ) * to_decimal(state.get("funding_risk_scale", _ONE))
        # Apply session quality and trend confidence size multipliers
        session_mult = to_decimal(state.get("session_size_mult", _ONE))
        trend_conf = to_decimal(state.get("trend_confidence", _ONE))
        size_mult = size_mult * session_mult * trend_conf
        projected_total_quote = self._project_total_amount_quote(
            equity_quote=data_context.equity_quote,
            mid=data_context.mid,
            quote_size_pct=data_context.regime_spec.quote_size_pct,
            total_levels=len(buy_spreads) + len(sell_spreads),
            size_mult=size_mult,
        )
        return RuntimeExecutionPlan(
            family="directional",
            buy_spreads=buy_spreads,
            sell_spreads=sell_spreads,
            projected_total_quote=projected_total_quote,
            size_mult=size_mult,
            metadata={
                "strategy_lane": "pb",
                "quote_side_mode": self._quote_side_mode,
                "quote_side_reason": self._quote_side_reason,
                "grid_levels": levels,
            },
        )

    def _extend_processed_data_before_log(
        self,
        *,
        processed_data: dict[str, Any],
        snapshot: dict[str, Any],
        state: Any,
        regime_name: str,
        market: MarketConditions,
        projected_total_quote: Decimal,
    ) -> None:
        pb = getattr(self, "_pb_state", None) or self._empty_pb_state()
        gate = self._pb_gate_metrics()
        processed_data.update({
            "pb_gate_state": str(gate["state"]),
            "pb_gate_reason": str(gate["reason"]),
            "pb_active": bool(pb.get("active", False)),
            "pb_probe_mode": bool(pb.get("probe_mode", False)),
            "pb_signal_side": str(pb.get("side", "off")),
            "pb_signal_reason": str(pb.get("reason", "inactive")),
            "pb_signal_score": to_decimal(pb.get("signal_score", _ZERO)),
            "pb_side": str(pb.get("side", "off")),
            "pb_reason": str(pb.get("reason", "inactive")),
            "pb_cvd": to_decimal(pb.get("cvd", _ZERO)),
            "pb_recent_delta": to_decimal(pb.get("recent_delta", _ZERO)),
            "pb_trade_age_ms": int(pb.get("trade_age_ms", 0) or 0),
            "pb_trade_flow_stale": bool(pb.get("trade_flow_stale", True)),
            "pb_rsi": to_decimal(pb.get("rsi", Decimal("50"))),
            "pb_adx": to_decimal(pb.get("adx", _ZERO)),
            "pb_bb_lower": to_decimal(pb.get("bb_lower", _ZERO)),
            "pb_bb_basis": to_decimal(pb.get("bb_basis", _ZERO)),
            "pb_bb_upper": to_decimal(pb.get("bb_upper", _ZERO)),
            "pb_grid_spacing_pct": to_decimal(pb.get("grid_spacing_pct", _ZERO)),
            "pb_grid_levels": int(pb.get("grid_levels", 0) or 0),
            "pb_hedge_target_base_pct": to_decimal(pb.get("hedge_target_base_pct", _ZERO)),
            "pb_funding_bias": str(pb.get("funding_bias", "neutral")),
            "pb_absorption_long": bool(pb.get("absorption_long", False)),
            "pb_absorption_short": bool(pb.get("absorption_short", False)),
            "pb_delta_trap_long": bool(pb.get("delta_trap_long", False)),
            "pb_delta_trap_short": bool(pb.get("delta_trap_short", False)),
            "pb_in_pullback_zone_long": bool(pb.get("in_pullback_zone_long", False)),
            "pb_in_pullback_zone_short": bool(pb.get("in_pullback_zone_short", False)),
            "pb_indicator_ready": bool(pb.get("indicator_ready", False)),
            "pb_indicator_missing": str(pb.get("indicator_missing", "")),
            "pb_price_buffer_bars": int(pb.get("price_buffer_bars", 0) or 0),
            "pb_basis_slope": to_decimal(pb.get("basis_slope", _ZERO)),
            "pb_trend_sma": to_decimal(pb.get("trend_sma") or _ZERO),
            "pb_trail_state": str(pb.get("trail_state", "inactive")),
            "pb_signal_count_24h": int(pb.get("signal_count_24h", 0) or 0),
            "pb_dynamic_sl": to_decimal(pb.get("dynamic_sl", _ZERO)),
            "pb_dynamic_tp": to_decimal(pb.get("dynamic_tp", _ZERO)),
            "pb_vol_declining": bool(pb.get("vol_declining", False)),
            "pb_session_quality": bool(pb.get("session_quality", True)),
            "pb_trend_confidence": to_decimal(pb.get("trend_confidence", _ONE)),
            "pb_rsi_divergence": bool(pb.get("rsi_divergence", False)),
            "pb_signal_age_s": int(pb.get("signal_age_s", 0) or 0),
            "pb_adaptive_cooldown_s": int(pb.get("adaptive_cooldown_s", 180) or 180),
            "pb_absorption_zscore": to_decimal(pb.get("absorption_zscore", _ZERO)),
            "pb_no_entry_detail": str(pb.get("no_entry_detail", "")),
        })

    def extend_runtime_processed_data(
        self,
        *,
        processed_data: dict[str, Any],
        data_context: RuntimeDataContext,
        risk_decision: RuntimeRiskDecision,
        execution_plan: RuntimeExecutionPlan,
        snapshot: dict[str, Any],
    ) -> None:
        self._extend_processed_data_before_log(
            processed_data=processed_data,
            snapshot=snapshot,
            state=risk_decision.guard_state,
            regime_name=data_context.regime_name,
            market=data_context.market,
            projected_total_quote=execution_plan.projected_total_quote,
        )

    def telemetry_fields(self) -> tuple[tuple[str, str, Any], ...]:
        return (
            ("bot7_gate_state", "pb_gate_state", "idle"),
            ("bot7_gate_reason", "pb_gate_reason", "inactive"),
            ("bot7_signal_side", "pb_signal_side", "off"),
            ("bot7_signal_reason", "pb_signal_reason", "inactive"),
            ("bot7_signal_score", "pb_signal_score", _ZERO),
            ("bot7_adx", "pb_adx", _ZERO),
            ("bot7_rsi", "pb_rsi", Decimal("50")),
            ("bot7_price_buffer_bars", "pb_price_buffer_bars", 0),
            ("bot7_bb_lower", "pb_bb_lower", _ZERO),
            ("bot7_bb_basis", "pb_bb_basis", _ZERO),
            ("bot7_bb_upper", "pb_bb_upper", _ZERO),
            ("bot7_atr", "pb_dynamic_sl", _ZERO),
            ("bot7_basis_slope", "pb_basis_slope", _ZERO),
            ("bot7_trend_sma", "pb_trend_sma", _ZERO),
            ("bot7_vol_declining", "pb_vol_declining", False),
            ("bot7_in_zone_long", "pb_in_pullback_zone_long", False),
            ("bot7_in_zone_short", "pb_in_pullback_zone_short", False),
            ("bot7_absorption_long", "pb_absorption_long", False),
            ("bot7_absorption_short", "pb_absorption_short", False),
            ("bot7_delta_trap_long", "pb_delta_trap_long", False),
            ("bot7_delta_trap_short", "pb_delta_trap_short", False),
            ("bot7_cvd", "pb_cvd", _ZERO),
            ("bot7_trend_confidence", "pb_trend_confidence", "1"),
            ("bot7_session_quality", "pb_session_quality", True),
            ("bot7_funding_bias", "pb_funding_bias", "neutral"),
            ("bot7_dynamic_sl", "pb_dynamic_sl", _ZERO),
            ("bot7_dynamic_tp", "pb_dynamic_tp", _ZERO),
            ("bot7_no_entry_detail", "pb_no_entry_detail", ""),
            ("bot7_signal_count_24h", "pb_signal_count_24h", 0),
        )

    def to_format_status(self) -> list[str]:
        lines = super().to_format_status()
        pb = getattr(self, "_pb_state", None) or self._empty_pb_state()
        lines.append(
            "pullback "
            f"side={pb.get('side', 'off')} reason={pb.get('reason', 'inactive')} "
            f"levels={pb.get('grid_levels', 0)} adx={to_decimal(pb.get('adx', _ZERO)):.1f} "
            f"rsi={to_decimal(pb.get('rsi', Decimal('50'))):.1f} "
            f"zone_long={pb.get('in_pullback_zone_long', False)} "
            f"zone_short={pb.get('in_pullback_zone_short', False)}"
        )
        dynamic_sl = to_decimal(pb.get("dynamic_sl", _ZERO))
        dynamic_tp = to_decimal(pb.get("dynamic_tp", _ZERO))
        trail_state = str(pb.get("trail_state", "inactive"))
        sig_count = int(pb.get("signal_count_24h", 0) or 0)
        sig_threshold = int(getattr(self.config, "pb_min_signals_warn", 3))
        lines.append(
            f"pullback sl={dynamic_sl:.4f} tp={dynamic_tp:.4f} trail={trail_state} "
            f"signals_24h={sig_count} (threshold={sig_threshold})"
        )
        trend_conf = to_decimal(pb.get("trend_confidence", _ONE))
        vol_dec = bool(pb.get("vol_declining", False))
        session_q = "quality" if bool(pb.get("session_quality", True)) else "off"
        rsi_div = bool(pb.get("rsi_divergence", False))
        sig_age = int(pb.get("signal_age_s", 0) or 0)
        cd_s = int(pb.get("adaptive_cooldown_s", 180) or 180)
        lines.append(
            f"pullback vol_decline={vol_dec} session={session_q} "
            f"trend_conf={trend_conf:.2f} rsi_div={rsi_div}"
        )
        lines.append(
            f"pullback signal_age={sig_age}s cooldown={cd_s}s"
        )
        if not bool(pb.get("indicator_ready", False)):
            lines.append(
                "pullback "
                f"warmup_missing={pb.get('indicator_missing', '') or 'unknown'} "
                f"price_buffer_bars={int(pb.get('price_buffer_bars', 0) or 0)}"
            )
        return lines
