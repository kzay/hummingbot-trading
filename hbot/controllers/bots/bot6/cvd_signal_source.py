"""Bot6 CVD Divergence — StrategySignalSource wrapper over cvd_signals.py."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from controllers.bots.bot6 import cvd_signals as cs
from controllers.runtime.v3.signals import (
    SignalLevel,
    TelemetryField,
    TelemetrySchema,
    TradingSignal,
)
from controllers.runtime.v3.types import MarketSnapshot

_ZERO = Decimal("0")


@dataclass
class CvdConfig:
    sma_fast_period: int = 20
    sma_slow_period: int = 60
    adx_period: int = 14
    adx_threshold: Decimal = Decimal("18")
    signal_score_threshold: int = 5
    divergence_threshold_pct: Decimal = Decimal("0.15")
    target_net_base_pct: Decimal = Decimal("0.12")
    dynamic_size_floor_mult: Decimal = Decimal("0.80")
    dynamic_size_cap_mult: Decimal = Decimal("1.50")
    per_leg_risk_pct: Decimal = Decimal("0.010")
    spread_pct: Decimal = Decimal("0.001")


class CvdSignalSource:
    """Bot6 CVD divergence strategy — wraps pure signal functions."""

    def __init__(self, config: CvdConfig | None = None) -> None:
        self._cfg = config or CvdConfig()

    def evaluate(self, snapshot: MarketSnapshot) -> TradingSignal:
        mid = snapshot.mid
        if mid <= _ZERO:
            return TradingSignal.no_trade("no_mid")

        cfg = self._cfg
        ind = snapshot.indicators

        adx = ind.adx.get(cfg.adx_period)
        if adx is None:
            return TradingSignal.no_trade("no_adx")

        # Trend detection using EMA as SMA proxy
        sma_fast = ind.ema.get(cfg.sma_fast_period, _ZERO)
        sma_slow = ind.ema.get(cfg.sma_slow_period, _ZERO)
        if sma_fast <= _ZERO or sma_slow <= _ZERO:
            return TradingSignal.no_trade("no_sma")

        trend_direction = cs.detect_trend(
            sma_fast=sma_fast,
            sma_slow=sma_slow,
            adx=adx,
            adx_threshold=cfg.adx_threshold,
        )

        if trend_direction == "flat":
            return TradingSignal.no_trade("flat_trend")

        # CVD scoring — trade flow data from snapshot
        tf = snapshot.trade_flow
        futures_cvd = tf.cvd if tf else _ZERO
        stacked_buy = tf.stacked_buy_count if tf else 0
        stacked_sell = tf.stacked_sell_count if tf else 0
        delta_spike = tf.delta_spike_ratio if tf else _ZERO

        long_score, short_score, cvd_div = cs.score_cvd_divergence(
            futures_cvd=futures_cvd,
            spot_cvd=_ZERO,  # Spot CVD not in snapshot — requires spot feed
            stacked_buy_count=stacked_buy,
            stacked_sell_count=stacked_sell,
            delta_spike_ratio=delta_spike,
            trend_direction=trend_direction,
            adx=adx,
            adx_threshold=cfg.adx_threshold,
            divergence_threshold_pct=cfg.divergence_threshold_pct,
        )

        active_score = max(long_score, short_score)
        if active_score < cfg.signal_score_threshold:
            return TradingSignal.no_trade(f"score_low_{active_score}")

        direction = "buy" if long_score > short_score else "sell"

        # Conviction normalized to [0, 1]
        conviction = min(Decimal(str(active_score)) / Decimal("10"), Decimal("1"))

        # Target
        target = cfg.target_net_base_pct if direction == "buy" else -cfg.target_net_base_pct

        # Size multiplier
        div_strength = min(abs(cvd_div), Decimal("1"))
        size_mult = cs.compute_dynamic_size_mult(
            divergence_strength=div_strength,
            floor_mult=cfg.dynamic_size_floor_mult,
            cap_mult=cfg.dynamic_size_cap_mult,
        )

        levels = (
            SignalLevel(
                side=direction,
                spread_pct=cfg.spread_pct,
                size_quote=mid * cfg.per_leg_risk_pct * size_mult,
                level_id=f"cvd_{direction[0]}0",
            ),
        )

        return TradingSignal(
            family="directional",
            direction=direction,
            conviction=conviction,
            target_net_base_pct=target,
            levels=levels,
            metadata={
                "trend_direction": trend_direction,
                "long_score": long_score,
                "short_score": short_score,
                "active_score": active_score,
                "cvd_divergence_ratio": cvd_div,
                "size_mult": size_mult,
                "adx": adx,
                "sma_fast": sma_fast,
                "sma_slow": sma_slow,
            },
            reason=f"cvd_{direction}_{trend_direction}",
        )

    def warmup_bars_required(self) -> int:
        return 200  # Need SMA(60) + ADX warmup

    def telemetry_schema(self) -> TelemetrySchema:
        return TelemetrySchema(fields=(
            TelemetryField(name="bot6_active_score", key="active_score", type="int", default=0),
            TelemetryField(name="bot6_trend", key="trend_direction", type="str", default="flat"),
            TelemetryField(name="bot6_cvd_div", key="cvd_divergence_ratio", type="decimal", default=_ZERO),
            TelemetryField(name="bot6_size_mult", key="size_mult", type="decimal", default=_ZERO),
            TelemetryField(name="bot6_adx", key="adx", type="decimal", default=_ZERO),
        ))


__all__ = ["CvdConfig", "CvdSignalSource"]
