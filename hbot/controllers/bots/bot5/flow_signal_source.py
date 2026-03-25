"""Bot5 IFT/JOTA — StrategySignalSource wrapper over flow_signals.py."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from controllers.bots.bot5 import flow_signals as fs
from controllers.runtime.v3.signals import (
    TelemetryField,
    TelemetrySchema,
    TradingSignal,
)
from controllers.runtime.v3.types import MarketSnapshot

_ZERO = Decimal("0")


@dataclass
class FlowConfig:
    imbalance_threshold: Decimal = Decimal("0.18")
    trend_threshold_pct: Decimal = Decimal("0.0008")
    bias_threshold: Decimal = Decimal("0.55")
    directional_threshold: Decimal = Decimal("0.75")
    target_net_base_pct: Decimal = Decimal("0.08")
    max_base_pct: Decimal = Decimal("0.50")


class FlowSignalSource:
    """Bot5 IFT/JOTA flow strategy — wraps pure signal functions."""

    def __init__(self, config: FlowConfig | None = None) -> None:
        self._cfg = config or FlowConfig()

    def evaluate(self, snapshot: MarketSnapshot) -> TradingSignal:
        mid = snapshot.mid
        if mid <= _ZERO:
            return TradingSignal.no_trade("no_mid")

        cfg = self._cfg
        ema_val = snapshot.indicators.ema.get(20, _ZERO)
        imbalance = snapshot.order_book.imbalance

        if ema_val <= _ZERO:
            return TradingSignal.no_trade("no_ema")

        conviction, signed_signal, direction, aligned = fs.compute_flow_conviction(
            imbalance=imbalance,
            mid=mid,
            ema_val=ema_val,
            imbalance_threshold=cfg.imbalance_threshold,
            trend_threshold_pct=cfg.trend_threshold_pct,
        )

        bias_active = fs.check_bias_active(
            direction=direction,
            conviction=conviction,
            bias_threshold=cfg.bias_threshold,
        )

        if not bias_active:
            return TradingSignal.no_trade(f"no_bias_dir={direction}_conv={conviction}")

        directional = fs.check_directional_allowed(
            bias_active=bias_active,
            conviction=conviction,
            direction=direction,
            regime_name=snapshot.regime.name,
            directional_threshold=cfg.directional_threshold,
            bias_threshold=cfg.bias_threshold,
        )

        target = fs.compute_target_net_base_pct(
            direction=direction,
            conviction=conviction,
            bias_active=bias_active,
            is_perp=snapshot.position.is_perp,
            target_base_pct=cfg.target_net_base_pct,
            max_base_pct=cfg.max_base_pct,
        )

        family = "hybrid" if directional else "hybrid"
        reason = f"flow_{direction}" if directional else f"bias_{direction}"

        return TradingSignal(
            family=family,
            direction=direction,
            conviction=conviction,
            target_net_base_pct=target,
            metadata={
                "imbalance": imbalance,
                "signed_signal": signed_signal,
                "conviction": conviction,
                "aligned": aligned,
                "bias_active": bias_active,
                "directional_allowed": directional,
                "regime": snapshot.regime.name,
            },
            reason=reason,
        )

    def warmup_bars_required(self) -> int:
        return 100

    def telemetry_schema(self) -> TelemetrySchema:
        return TelemetrySchema(fields=(
            TelemetryField(name="bot5_conviction", key="conviction", type="decimal", default=_ZERO),
            TelemetryField(name="bot5_imbalance", key="imbalance", type="decimal", default=_ZERO),
            TelemetryField(name="bot5_signed_signal", key="signed_signal", type="decimal", default=_ZERO),
            TelemetryField(name="bot5_directional", key="directional_allowed", type="bool", default=False),
        ))


__all__ = ["FlowConfig", "FlowSignalSource"]
