from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List


class GuardState(str, Enum):
    RUNNING = "running"
    SOFT_PAUSE = "soft_pause"
    HARD_STOP = "hard_stop"


@dataclass
class OpsSnapshot:
    connector_ready: bool
    balances_consistent: bool
    cancel_fail_streak: int
    edge_gate_blocked: bool = False
    high_vol: bool = False
    market_spread_too_small: bool = False


@dataclass
class OpsGuard:
    max_operational_pause_cycles: int = 6
    hard_stop_cancel_fail_streak: int = 8
    state: GuardState = GuardState.RUNNING
    _operational_pause_cycles: int = 0
    reasons: List[str] = field(default_factory=list)

    def update(self, snapshot: OpsSnapshot) -> GuardState:
        reasons: List[str] = []
        operational_failure = False

        if not snapshot.connector_ready:
            reasons.append("connector_not_ready")
            operational_failure = True
        if not snapshot.balances_consistent:
            reasons.append("balance_mismatch")
            operational_failure = True
        if snapshot.edge_gate_blocked:
            reasons.append("edge_gate_blocked")
        if snapshot.high_vol:
            reasons.append("high_vol")
        if snapshot.market_spread_too_small:
            reasons.append("market_spread_too_small")

        if snapshot.cancel_fail_streak >= self.hard_stop_cancel_fail_streak:
            reasons.append("cancel_fail_hard_limit")
            self.reasons = reasons
            self.state = GuardState.HARD_STOP
            return self.state

        if operational_failure:
            self._operational_pause_cycles += 1
            self.reasons = reasons
            if self._operational_pause_cycles >= self.max_operational_pause_cycles:
                self.state = GuardState.HARD_STOP
            else:
                self.state = GuardState.SOFT_PAUSE
            return self.state

        if reasons:
            self.reasons = reasons
            self.state = GuardState.SOFT_PAUSE
            return self.state

        self._operational_pause_cycles = 0
        self.reasons = []
        self.state = GuardState.RUNNING
        return self.state

    def force_hard_stop(self, reason: str) -> GuardState:
        self.state = GuardState.HARD_STOP
        self.reasons = [reason]
        return self.state
