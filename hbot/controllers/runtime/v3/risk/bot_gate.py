"""Per-bot risk gate — daily loss, drawdown, turnover, margin."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from controllers.runtime.v3.risk_types import RiskDecision
from controllers.runtime.v3.signals import SignalLevel, TradingSignal
from controllers.runtime.v3.types import MarketSnapshot

_ZERO = Decimal("0")
_ONE = Decimal("1")


@dataclass
class BotRiskConfig:
    """Risk thresholds for per-bot gating."""

    max_daily_loss_pct_hard: Decimal = Decimal("0.02")
    max_drawdown_pct_hard: Decimal = Decimal("0.035")
    max_daily_turnover_x_hard: Decimal = Decimal("14")
    turnover_soft_cap_ratio: Decimal = Decimal("0.80")
    margin_ratio_critical: Decimal = Decimal("0.05")


class BotRiskGate:
    """Layer 2: Per-bot risk limits.

    Checks daily loss, drawdown, turnover caps, and margin ratio.
    Can reduce sizing when approaching turnover cap (soft cap).
    """

    def __init__(self, config: BotRiskConfig | None = None) -> None:
        self._cfg = config or BotRiskConfig()

    def evaluate(
        self,
        signal: TradingSignal,
        snapshot: MarketSnapshot,
    ) -> RiskDecision:
        cfg = self._cfg

        # Daily loss hard stop
        if snapshot.equity.daily_loss_pct >= cfg.max_daily_loss_pct_hard:
            return RiskDecision.reject(
                "bot",
                "daily_loss_hard_stop",
                daily_loss_pct=snapshot.equity.daily_loss_pct,
                threshold=cfg.max_daily_loss_pct_hard,
            )

        # Drawdown hard stop
        if snapshot.equity.max_drawdown_pct >= cfg.max_drawdown_pct_hard:
            return RiskDecision.reject(
                "bot",
                "drawdown_hard_stop",
                drawdown_pct=snapshot.equity.max_drawdown_pct,
                threshold=cfg.max_drawdown_pct_hard,
            )

        # Margin ratio critical (perp only)
        if snapshot.position.is_perp:
            margin_ratio = snapshot.config.get("margin_ratio", _ONE)
            if isinstance(margin_ratio, (int, float)):
                margin_ratio = Decimal(str(margin_ratio))
            if margin_ratio < cfg.margin_ratio_critical:
                return RiskDecision.reject(
                    "bot",
                    "margin_ratio_critical",
                    margin_ratio=margin_ratio,
                    threshold=cfg.margin_ratio_critical,
                )

        # Turnover hard stop
        turnover_x = snapshot.equity.daily_turnover_x
        if turnover_x >= cfg.max_daily_turnover_x_hard:
            return RiskDecision.reject(
                "bot",
                "turnover_hard_stop",
                turnover_x=turnover_x,
                threshold=cfg.max_daily_turnover_x_hard,
            )

        # Turnover soft cap — reduce sizing
        soft_threshold = cfg.max_daily_turnover_x_hard * cfg.turnover_soft_cap_ratio
        if turnover_x >= soft_threshold and cfg.max_daily_turnover_x_hard > _ZERO:
            remaining_ratio = (cfg.max_daily_turnover_x_hard - turnover_x) / (
                cfg.max_daily_turnover_x_hard - soft_threshold
            )
            remaining_ratio = max(_ZERO, min(_ONE, remaining_ratio))

            if signal.levels:
                reduced_levels = tuple(
                    SignalLevel(
                        side=lv.side,
                        spread_pct=lv.spread_pct,
                        size_quote=lv.size_quote * remaining_ratio,
                        level_id=lv.level_id,
                    )
                    for lv in signal.levels
                )
                modified = TradingSignal(
                    family=signal.family,
                    direction=signal.direction,
                    conviction=signal.conviction,
                    target_net_base_pct=signal.target_net_base_pct,
                    levels=reduced_levels,
                    metadata=signal.metadata,
                    reason=signal.reason,
                )
                return RiskDecision.modify(
                    "bot",
                    modified,
                    reason="turnover_soft_cap",
                    turnover_x=turnover_x,
                    remaining_ratio=remaining_ratio,
                )

        return RiskDecision.approve("bot")


__all__ = ["BotRiskConfig", "BotRiskGate"]
