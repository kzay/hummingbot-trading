from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import Field

from controllers.runtime.base import StrategyRuntimeV24Config, StrategyRuntimeV24Controller
from controllers.runtime.market_making_types import MarketConditions, SpreadEdgeState
from services.common.utils import to_decimal

_ZERO = Decimal("0")


class Bot1BaselineV1Config(StrategyRuntimeV24Config):
    """Dedicated bot1 baseline lane over the shared runtime."""

    controller_name: str = "bot1_baseline_v1"
    shared_edge_gate_enabled: bool = Field(default=True)


class Bot1BaselineV1Controller(StrategyRuntimeV24Controller):
    """Bot1 baseline strategy wrapper used to isolate bot1 from shared aliases."""

    def _bot1_gate_metrics(self) -> dict[str, Any]:
        alpha_state = str(getattr(self, "_alpha_policy_state", "maker_two_sided") or "maker_two_sided")
        alpha_reason = str(getattr(self, "_alpha_policy_reason", "startup") or "startup")
        quote_side_mode = str(getattr(self, "_quote_side_mode", "off") or "off")
        maker_score = to_decimal(getattr(self, "_alpha_maker_score", _ZERO))
        aggressive_score = to_decimal(getattr(self, "_alpha_aggressive_score", _ZERO))
        signal_score = max(maker_score, aggressive_score)
        if alpha_state == "no_trade":
            gate_state = "blocked"
            signal_side = "off"
        elif alpha_state.endswith("_buy"):
            gate_state = "active"
            signal_side = "buy"
        elif alpha_state.endswith("_sell"):
            gate_state = "active"
            signal_side = "sell"
        elif quote_side_mode in {"buy_only", "sell_only"}:
            gate_state = "active"
            signal_side = "buy" if quote_side_mode == "buy_only" else "sell"
        else:
            gate_state = "active"
            signal_side = "two_sided"
        return {
            "state": gate_state,
            "reason": alpha_reason,
            "signal_side": signal_side,
            "signal_reason": alpha_state,
            "signal_score": signal_score,
        }

    def _emit_tick_output(
        self,
        _t0: float,
        now: float,
        mid: Decimal,
        regime_name: str,
        target_base_pct: Decimal,
        target_net_base_pct: Decimal,
        base_pct_gross: Decimal,
        base_pct_net: Decimal,
        equity_quote: Decimal,
        spread_state: SpreadEdgeState,
        market: MarketConditions,
        risk_hard_stop: bool,
        risk_reasons: list[str],
        daily_loss_pct: Decimal,
        drawdown_pct: Decimal,
        projected_total_quote: Decimal,
        state: Any,
        runtime_data_context: Any | None = None,
        runtime_execution_plan: Any | None = None,
        runtime_risk_decision: Any | None = None,
    ) -> None:
        super()._emit_tick_output(
            _t0,
            now,
            mid,
            regime_name,
            target_base_pct,
            target_net_base_pct,
            base_pct_gross,
            base_pct_net,
            equity_quote,
            spread_state,
            market,
            risk_hard_stop,
            risk_reasons,
            daily_loss_pct,
            drawdown_pct,
            projected_total_quote,
            state,
            runtime_data_context=runtime_data_context,
            runtime_execution_plan=runtime_execution_plan,
            runtime_risk_decision=runtime_risk_decision,
        )
        gate = self._bot1_gate_metrics()
        self.processed_data["bot1_gate_state"] = str(gate["state"])
        self.processed_data["bot1_gate_reason"] = str(gate["reason"])
        self.processed_data["bot1_signal_side"] = str(gate["signal_side"])
        self.processed_data["bot1_signal_reason"] = str(gate["signal_reason"])
        self.processed_data["bot1_signal_score"] = to_decimal(gate["signal_score"])
