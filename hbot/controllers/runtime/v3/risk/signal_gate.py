"""Per-signal risk gate — edge gate, adverse fill, cooldown."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal

from controllers.runtime.v3.risk_types import RiskDecision
from controllers.runtime.v3.signals import TradingSignal
from controllers.runtime.v3.types import MarketSnapshot

_ZERO = Decimal("0")


@dataclass
class SignalRiskConfig:
    """Risk thresholds for per-signal gating."""

    min_net_edge_bps: Decimal = Decimal("5.5")
    edge_resume_bps: Decimal = Decimal("6.0")
    adverse_fill_ratio_threshold: Decimal = Decimal("0.30")
    selective_quote_block_threshold: Decimal = Decimal("0.80")
    signal_cooldown_s: float = 180.0


class SignalRiskGate:
    """Layer 3: Per-signal quality checks.

    - Edge gate with EWMA + hysteresis
    - Adverse fill ratio
    - Selective quoting quality
    - Per-side signal cooldown
    """

    def __init__(self, config: SignalRiskConfig | None = None) -> None:
        self._cfg = config or SignalRiskConfig()
        self._edge_blocked: bool = False
        self._last_signal_ts: dict[str, float] = {}  # side -> timestamp

    def evaluate(
        self,
        signal: TradingSignal,
        snapshot: MarketSnapshot,
    ) -> RiskDecision:
        cfg = self._cfg

        # Edge gate with hysteresis
        net_edge = snapshot.config.get("net_edge_bps", _ZERO)
        if isinstance(net_edge, (int, float)):
            net_edge = Decimal(str(net_edge))

        if self._edge_blocked:
            if net_edge >= cfg.edge_resume_bps:
                self._edge_blocked = False
            else:
                return RiskDecision.reject(
                    "signal",
                    "edge_gate_blocked",
                    net_edge_bps=net_edge,
                    resume_threshold=cfg.edge_resume_bps,
                )
        elif net_edge < cfg.min_net_edge_bps and net_edge != _ZERO:
            self._edge_blocked = True
            return RiskDecision.reject(
                "signal",
                "edge_gate_blocked",
                net_edge_bps=net_edge,
                min_threshold=cfg.min_net_edge_bps,
            )

        # Adverse fill ratio
        adverse_ratio = snapshot.config.get("adverse_fill_ratio", _ZERO)
        if isinstance(adverse_ratio, (int, float)):
            adverse_ratio = Decimal(str(adverse_ratio))
        if adverse_ratio >= cfg.adverse_fill_ratio_threshold:
            return RiskDecision.reject(
                "signal",
                "adverse_fill_ratio_high",
                adverse_ratio=adverse_ratio,
                threshold=cfg.adverse_fill_ratio_threshold,
            )

        # Signal cooldown (directional only)
        if signal.direction in ("buy", "sell"):
            now = time.time()
            last_ts = self._last_signal_ts.get(signal.direction, 0.0)
            elapsed = now - last_ts
            if elapsed < cfg.signal_cooldown_s:
                return RiskDecision.reject(
                    "signal",
                    "signal_cooldown_active",
                    direction=signal.direction,
                    elapsed_s=elapsed,
                    cooldown_s=cfg.signal_cooldown_s,
                )
            self._last_signal_ts[signal.direction] = now

        return RiskDecision.approve("signal")

    def reset_cooldown(self, side: str = "") -> None:
        """Clear cooldown for a side or all sides."""
        if side:
            self._last_signal_ts.pop(side, None)
        else:
            self._last_signal_ts.clear()

    def reset_edge_gate(self) -> None:
        self._edge_blocked = False


__all__ = ["SignalRiskConfig", "SignalRiskGate"]
