"""Bot7 Pullback — StrategySignalSource wrapper over pullback_signals.py.

Adapts the existing pure signal functions into the v3 protocol.
This module imports only pullback_signals (pure) and v3 types.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from controllers.bots.bot7 import pullback_signals as ps
from controllers.runtime.v3.signals import (
    SignalLevel,
    TelemetryField,
    TelemetrySchema,
    TradingSignal,
)
from controllers.runtime.v3.types import MarketSnapshot

_ZERO = Decimal("0")
_ONE = Decimal("1")


@dataclass
class PullbackConfig:
    """Configuration for the pullback strategy."""

    bb_period: int = 20
    rsi_period: int = 14
    adx_period: int = 14
    atr_period: int = 14
    rsi_long_min: Decimal = Decimal("35")
    rsi_long_max: Decimal = Decimal("55")
    rsi_short_min: Decimal = Decimal("45")
    rsi_short_max: Decimal = Decimal("65")
    adx_min: Decimal = Decimal("18")
    adx_max: Decimal = Decimal("45")
    pullback_zone_pct: Decimal = Decimal("0.0015")
    zone_atr_mult: Decimal = Decimal("0.25")
    max_grid_legs: int = 3
    per_leg_risk_pct: Decimal = Decimal("0.008")
    grid_spacing_atr_mult: Decimal = Decimal("0.50")
    sl_atr_mult: Decimal = Decimal("1.5")
    tp_atr_mult: Decimal = Decimal("3.0")
    min_basis_slope_pct: Decimal = Decimal("0.0002")
    trend_sma_period: int = 20
    signal_score_threshold: Decimal = Decimal("0.40")
    target_net_base_pct: Decimal = Decimal("0.04")
    session_filter_enabled: bool = True
    quality_hours_utc: str = "1-4,8-16,20-23"


class PullbackSignalSource:
    """Bot7 pullback strategy — wraps pure signal functions.

    Reads indicators from MarketSnapshot, calls pullback_signals
    functions, returns a TradingSignal.
    """

    def __init__(self, config: PullbackConfig | None = None) -> None:
        self._cfg = config or PullbackConfig()

    def evaluate(self, snapshot: MarketSnapshot) -> TradingSignal:
        mid = snapshot.mid
        if mid <= _ZERO:
            return TradingSignal.no_trade("no_mid")

        cfg = self._cfg
        ind = snapshot.indicators

        # Check indicator availability
        atr = ind.atr.get(cfg.atr_period)
        rsi = ind.rsi.get(cfg.rsi_period)
        adx = ind.adx.get(cfg.adx_period)

        if atr is None or rsi is None or adx is None:
            return TradingSignal.no_trade("indicators_not_ready")

        # Regime gate: only active in up/down regimes
        regime = snapshot.regime.name
        if regime not in ("up", "down"):
            return TradingSignal.no_trade(f"regime_{regime}")

        # Compute BB from snapshot (simplified — use EMA as basis proxy)
        ema = ind.ema.get(cfg.bb_period, mid)
        bb_basis = ema
        bb_std = atr * Decimal("0.5")  # Approximation using ATR
        bb_lower = bb_basis - 2 * bb_std
        bb_upper = bb_basis + 2 * bb_std

        # ADX gate
        adx_ok = ps.check_adx_gate(adx, cfg.adx_min, cfg.adx_max)
        if not adx_ok:
            return TradingSignal.no_trade("adx_out_of_range")

        # Determine candidate sides based on regime
        sides: list[str] = []
        if regime == "up":
            sides.append("buy")
        elif regime == "down":
            sides.append("sell")

        best_signal: TradingSignal | None = None
        best_score = _ZERO

        for side in sides:
            # Pullback zone check — returns (long_zone, short_zone)
            long_zone, short_zone = ps.detect_pullback_zone(
                mid=mid,
                bb_lower=bb_lower,
                bb_basis=bb_basis,
                bb_upper=bb_upper,
                atr=atr,
                zone_pct=cfg.pullback_zone_pct,
                zone_atr_mult=cfg.zone_atr_mult,
            )
            in_zone = long_zone if side == "buy" else short_zone
            if not in_zone:
                continue

            # RSI gate
            if side == "buy":
                rsi_ok = ps.check_rsi_gate(rsi, cfg.rsi_long_min, cfg.rsi_long_max)
            else:
                rsi_ok = ps.check_rsi_gate(rsi, cfg.rsi_short_min, cfg.rsi_short_max)
            if not rsi_ok:
                continue

            # Session quality
            if cfg.session_filter_enabled:
                session_ok = ps.in_quality_session(hours_spec=cfg.quality_hours_utc)
                if not session_ok:
                    continue

            # Signal score (simplified — use key indicators)
            score = ps.compute_signal_score(
                absorption=False,
                delta_trap=False,
                depth_imbalance=_ZERO,
                funding_aligned=True,
                rsi_divergence=False,
            )

            if score < cfg.signal_score_threshold:
                continue

            if score > best_score:
                best_score = score

                # Compute grid
                grid_levels = ps.compute_grid_levels(
                    score=score,
                    max_legs=cfg.max_grid_legs,
                )
                grid_spacing = ps.compute_grid_spacing(
                    atr=atr,
                    mid=mid,
                    atr_mult=cfg.grid_spacing_atr_mult,
                )

                # Build levels
                levels = []
                for i in range(grid_levels):
                    levels.append(SignalLevel(
                        side=side,
                        spread_pct=grid_spacing * (i + 1),
                        size_quote=mid * cfg.per_leg_risk_pct,
                        level_id=f"pb_{side[0]}{i}",
                    ))

                # Dynamic barriers
                sl, tp = ps.compute_dynamic_barriers(
                    atr=atr,
                    mid=mid,
                    sl_mult=cfg.sl_atr_mult,
                    tp_mult=cfg.tp_atr_mult,
                )

                best_signal = TradingSignal(
                    family="directional",
                    direction=side,
                    conviction=score,
                    target_net_base_pct=cfg.target_net_base_pct if side == "buy" else -cfg.target_net_base_pct,
                    levels=tuple(levels),
                    metadata={
                        "bb_basis": bb_basis,
                        "bb_lower": bb_lower,
                        "bb_upper": bb_upper,
                        "rsi": rsi,
                        "adx": adx,
                        "atr": atr,
                        "signal_score": score,
                        "grid_levels": grid_levels,
                        "grid_spacing": grid_spacing,
                        "dynamic_sl": sl,
                        "dynamic_tp": tp,
                        "regime": regime,
                        "in_zone": True,
                    },
                    reason=f"pullback_{side}",
                )

        if best_signal is not None:
            return best_signal

        return TradingSignal.no_trade("no_pullback_signal")

    def warmup_bars_required(self) -> int:
        return 200  # Need enough bars for BB(20), SMA(50), indicators

    def telemetry_schema(self) -> TelemetrySchema:
        return TelemetrySchema(fields=(
            TelemetryField(name="pb_signal_score", key="signal_score", type="decimal", default=_ZERO),
            TelemetryField(name="pb_grid_levels", key="grid_levels", type="int", default=0),
            TelemetryField(name="pb_rsi", key="rsi", type="decimal", default=_ZERO),
            TelemetryField(name="pb_adx", key="adx", type="decimal", default=_ZERO),
            TelemetryField(name="pb_atr", key="atr", type="decimal", default=_ZERO),
            TelemetryField(name="pb_regime", key="regime", type="str", default=""),
            TelemetryField(name="pb_dynamic_sl", key="dynamic_sl", type="decimal", default=_ZERO),
            TelemetryField(name="pb_dynamic_tp", key="dynamic_tp", type="decimal", default=_ZERO),
        ))


__all__ = ["PullbackConfig", "PullbackSignalSource"]
