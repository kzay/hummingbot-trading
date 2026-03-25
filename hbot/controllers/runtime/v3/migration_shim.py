"""Strategy Migration Shim — wraps legacy bot controllers as signal sources.

During incremental migration, this shim adapts existing bot controllers
(which inherit from SharedRuntimeKernel) into the StrategySignalSource
protocol. Each bot's internal state dict is translated to a TradingSignal.

The shim also supports shadow mode: run both shim and native signal source
on the same snapshot, compare outputs, log divergences.
"""

from __future__ import annotations

import logging
import time
from decimal import Decimal
from typing import Any

from controllers.runtime.v3.signals import SignalLevel, TelemetrySchema, TradingSignal
from controllers.runtime.v3.types import MarketSnapshot

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")


# ── Per-bot state extractors ─────────────────────────────────────────

def _extract_bot1(ctrl: Any) -> TradingSignal:
    """Extract signal from Bot1 baseline controller."""
    state = getattr(ctrl, "_alpha_policy_state", "maker_two_sided")
    reason = getattr(ctrl, "_alpha_policy_reason", "startup")
    maker_score = getattr(ctrl, "_alpha_maker_score", _ZERO)
    aggressive_score = getattr(ctrl, "_alpha_aggressive_score", _ZERO)
    score = max(maker_score, aggressive_score)

    # Map alpha state to direction
    if state in ("maker_two_sided",):
        direction = "both"
    elif state in ("maker_bias_buy", "aggressive_buy"):
        direction = "buy"
    elif state in ("maker_bias_sell", "aggressive_sell"):
        direction = "sell"
    elif state in ("no_trade",):
        return TradingSignal.no_trade(reason)
    else:
        direction = "both"

    return TradingSignal(
        family="mm_grid",
        direction=direction,
        conviction=score if isinstance(score, Decimal) else Decimal(str(score)),
        metadata={
            "alpha_state": state,
            "alpha_reason": reason,
            "maker_score": maker_score,
            "aggressive_score": aggressive_score,
        },
        reason=reason,
    )


def _extract_bot5(ctrl: Any) -> TradingSignal:
    """Extract signal from Bot5 IFT/JOTA controller."""
    state = getattr(ctrl, "_bot5_flow_state", {})
    if not state:
        return TradingSignal.no_trade("no_flow_state")

    direction = state.get("direction", "off")
    conviction = state.get("conviction", _ZERO)
    target = state.get("target_net_base_pct", _ZERO)
    directional = state.get("directional_allowed", False)
    reason = state.get("reason", "unknown")

    if direction == "off" or not directional:
        if state.get("bias_active", False):
            family = "hybrid"
        else:
            return TradingSignal.no_trade(reason)
    else:
        family = "hybrid"

    return TradingSignal(
        family=family,
        direction=direction,
        conviction=_to_decimal(conviction),
        target_net_base_pct=_to_decimal(target),
        metadata={k: v for k, v in state.items()},
        reason=reason,
    )


def _extract_bot6(ctrl: Any) -> TradingSignal:
    """Extract signal from Bot6 CVD divergence controller."""
    state = getattr(ctrl, "_bot6_signal_state", {})
    if not state:
        return TradingSignal.no_trade("no_signal_state")

    direction = state.get("direction", "off")
    directional = state.get("directional_allowed", False)
    target = state.get("target_net_base_pct", _ZERO)
    active_score = state.get("active_score", 0)
    reason = state.get("reason", "unknown")

    if direction == "off" or not directional:
        return TradingSignal.no_trade(reason)

    # Normalize score to [0, 1] — threshold is typically 5
    threshold = 10  # max reasonable score
    conviction = min(Decimal(str(active_score)) / Decimal(str(threshold)), Decimal("1"))

    return TradingSignal(
        family="directional",
        direction=direction,
        conviction=conviction,
        target_net_base_pct=_to_decimal(target),
        metadata={k: v for k, v in state.items()},
        reason=reason,
    )


def _extract_bot7(ctrl: Any) -> TradingSignal:
    """Extract signal from Bot7 pullback controller."""
    state = getattr(ctrl, "_pb_state", {})
    if not state:
        return TradingSignal.no_trade("no_pb_state")

    active = state.get("active", False)
    side = state.get("side", "off")
    score = state.get("signal_score", _ZERO)
    target = state.get("target_net_base_pct", _ZERO)
    grid_levels = state.get("grid_levels", 0)
    reason = state.get("reason", "inactive")

    if not active or side == "off":
        return TradingSignal.no_trade(reason)

    # Build signal levels from grid_levels count
    spacing = state.get("grid_spacing_pct", Decimal("0.001"))
    levels = []
    for i in range(grid_levels):
        levels.append(SignalLevel(
            side=side,
            spread_pct=_to_decimal(spacing) * (i + 1),
            size_quote=_ZERO,  # Sized by adapter from config
            level_id=f"pb_{side}_{i}",
        ))

    return TradingSignal(
        family="directional",
        direction=side,
        conviction=_to_decimal(score),
        target_net_base_pct=_to_decimal(target),
        levels=tuple(levels),
        metadata={k: v for k, v in state.items()},
        reason=reason,
    )


# ── Extractor registry ───────────────────────────────────────────────

_EXTRACTORS: dict[str, Any] = {
    "bot1": _extract_bot1,
    "bot5": _extract_bot5,
    "bot6": _extract_bot6,
    "bot7": _extract_bot7,
}


# ── Shim class ───────────────────────────────────────────────────────

class StrategyMigrationShim:
    """Wraps a legacy bot controller as a StrategySignalSource.

    Usage::

        shim = StrategyMigrationShim(legacy_controller, bot_id="bot7")
        signal = shim.evaluate(snapshot)  # returns TradingSignal
    """

    def __init__(self, legacy_controller: Any, bot_id: str) -> None:
        self._ctrl = legacy_controller
        self._bot_id = bot_id
        self._extractor = _EXTRACTORS.get(bot_id)
        if self._extractor is None:
            raise ValueError(
                f"No extractor for bot_id='{bot_id}'. "
                f"Available: {sorted(_EXTRACTORS.keys())}"
            )

    def evaluate(self, snapshot: MarketSnapshot) -> TradingSignal:
        """Extract a TradingSignal from the legacy controller's state."""
        return self._extractor(self._ctrl)

    def warmup_bars_required(self) -> int:
        """Delegate to legacy controller's config if available."""
        cfg = getattr(self._ctrl, "config", None)
        if cfg is not None:
            val = getattr(cfg, "warmup_bars", None)
            if isinstance(val, int):
                return val
        return 200

    def telemetry_schema(self) -> TelemetrySchema:
        """Legacy bots declare telemetry via the old hook — return empty."""
        return TelemetrySchema()


# ── Shadow mode ──────────────────────────────────────────────────────

class ShadowComparator:
    """Runs both shim and native signal source, compares outputs.

    The shim's signal is used for actual execution.  Divergences are logged.
    """

    def __init__(
        self,
        shim: StrategyMigrationShim,
        native: Any,  # StrategySignalSource
        *,
        divergence_threshold: Decimal = Decimal("0.05"),
        instance_name: str = "",
    ) -> None:
        self._shim = shim
        self._native = native
        self._threshold = divergence_threshold
        self._instance = instance_name
        self._total_ticks: int = 0
        self._divergent_ticks: int = 0
        self._max_divergence: Decimal = _ZERO

    def evaluate(self, snapshot: MarketSnapshot) -> TradingSignal:
        """Run both, compare, return shim's signal."""
        shim_signal = self._shim.evaluate(snapshot)
        native_signal = self._native.evaluate(snapshot)

        self._total_ticks += 1
        self._compare(shim_signal, native_signal, snapshot.timestamp_ms)

        return shim_signal  # Shim is authoritative during migration

    def warmup_bars_required(self) -> int:
        return max(
            self._shim.warmup_bars_required(),
            self._native.warmup_bars_required(),
        )

    def telemetry_schema(self) -> TelemetrySchema:
        return self._native.telemetry_schema()

    def _compare(
        self,
        shim: TradingSignal,
        native: TradingSignal,
        ts_ms: int,
    ) -> None:
        """Compare two signals and log divergences."""
        divergences: list[str] = []

        if shim.family != native.family:
            divergences.append(f"family: {shim.family} vs {native.family}")

        if shim.direction != native.direction:
            divergences.append(f"direction: {shim.direction} vs {native.direction}")

        conviction_delta = abs(shim.conviction - native.conviction)
        if conviction_delta > self._threshold:
            divergences.append(
                f"conviction: {shim.conviction} vs {native.conviction} "
                f"(delta={conviction_delta})"
            )

        target_delta = abs(shim.target_net_base_pct - native.target_net_base_pct)
        if target_delta > self._threshold:
            divergences.append(
                f"target: {shim.target_net_base_pct} vs {native.target_net_base_pct}"
            )

        if divergences:
            self._divergent_ticks += 1
            self._max_divergence = max(self._max_divergence, conviction_delta)
            logger.warning(
                "Shadow divergence [%s] tick=%d: %s",
                self._instance,
                ts_ms,
                "; ".join(divergences),
            )

    @property
    def divergence_ratio(self) -> Decimal:
        if self._total_ticks == 0:
            return _ZERO
        return Decimal(str(self._divergent_ticks)) / Decimal(str(self._total_ticks))

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "total_ticks": self._total_ticks,
            "divergent_ticks": self._divergent_ticks,
            "divergence_ratio": self.divergence_ratio,
            "max_conviction_delta": self._max_divergence,
        }


# ── Helpers ──────────────────────────────────────────────────────────

def _to_decimal(val: Any) -> Decimal:
    if isinstance(val, Decimal):
        return val
    if val is None:
        return _ZERO
    try:
        return Decimal(str(val))
    except Exception:
        return _ZERO


__all__ = [
    "ShadowComparator",
    "StrategyMigrationShim",
]
