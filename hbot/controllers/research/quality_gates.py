"""Hard reject gates and overfitting defenses for research candidates.

Hard gates run before composite ranking. A candidate that fails any hard gate
is rejected regardless of its composite robustness score.

Overfitting defenses are computed alongside gates and persisted as named
flags in the experiment manifest so operators can see exactly why a
candidate was flagged as fragile.

Usage::

    from controllers.research.quality_gates import run_quality_gates, GateReport

    report = run_quality_gates(candidate, metrics, sweep_results)
    if not report.hard_gates_pass:
        # reject candidate
        ...
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default gate thresholds
# ---------------------------------------------------------------------------

_DEFAULT_NET_PNL_MIN = 0.0           # positive after fees
_DEFAULT_MAX_DRAWDOWN = 20.0         # percent
_DEFAULT_MIN_PROFIT_FACTOR = 1.15
_DEFAULT_MIN_OOS_SHARPE = 0.5
_DEFAULT_MIN_OOS_DEGRADATION = 0.6
_DEFAULT_DSR_THRESHOLD = 0.0         # deflated Sharpe must be > 0
_TRADE_COUNT_BY_FREQ = {
    "low": 20,
    "medium": 40,
    "high": 80,
}

# Overfitting defense thresholds
_MAX_PERIOD_CONCENTRATION = 0.50     # max single-month share of total PnL
_MAX_TRADE_CONCENTRATION = 0.15      # max single-trade share of total PnL
_MIN_PARAM_NEIGHBOR_RETENTION = 0.80 # neighbors must retain >= 80% of center score
_COMPLEXITY_PENALTY_THRESHOLD = 6    # > 6 parameters incurs simplicity penalty


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SingleGate:
    """Result of a single quality gate check."""

    name: str
    passed: bool
    reason: str
    value: float | None = None
    threshold: float | None = None


@dataclass
class OverfitFlag:
    """A named overfitting defense signal."""

    name: str
    flagged: bool
    detail: str


@dataclass
class GateReport:
    """Full quality gate and overfitting defense report for a candidate."""

    hard_gates: list[SingleGate] = field(default_factory=list)
    overfit_flags: list[OverfitFlag] = field(default_factory=list)
    complexity_penalty: float = 0.0
    hard_gates_pass: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict for manifest storage."""
        return {
            "hard_gates_pass": self.hard_gates_pass,
            "hard_gates": [
                {
                    "name": g.name,
                    "passed": g.passed,
                    "reason": g.reason,
                    "value": g.value,
                    "threshold": g.threshold,
                }
                for g in self.hard_gates
            ],
            "overfit_flags": [
                {"name": f.name, "flagged": f.flagged, "detail": f.detail}
                for f in self.overfit_flags
            ],
            "complexity_penalty": self.complexity_penalty,
        }


# ---------------------------------------------------------------------------
# Hard gate checks
# ---------------------------------------------------------------------------

def _gate_net_pnl(bt: Any, thresholds: dict[str, Any]) -> SingleGate:
    min_pnl = thresholds.get("min_net_pnl", _DEFAULT_NET_PNL_MIN)
    if bt is None:
        return SingleGate("net_pnl", False, "No backtest result available")
    try:
        net_pnl = float(bt.realized_net_pnl_quote)
    except (AttributeError, TypeError, ValueError):
        return SingleGate("net_pnl", False, "Could not read net PnL from backtest result")
    passed = net_pnl > min_pnl
    return SingleGate(
        "net_pnl",
        passed,
        f"net PnL {net_pnl:.4f} {'>' if passed else '<='} {min_pnl}",
        value=net_pnl,
        threshold=min_pnl,
    )


def _gate_drawdown(bt: Any, thresholds: dict[str, Any]) -> SingleGate:
    max_dd = thresholds.get("max_drawdown_pct", _DEFAULT_MAX_DRAWDOWN)
    if bt is None:
        return SingleGate("max_drawdown", False, "No backtest result available")
    try:
        dd = float(bt.max_drawdown_pct)
    except (AttributeError, TypeError, ValueError):
        return SingleGate("max_drawdown", False, "Could not read max drawdown")
    passed = dd <= max_dd
    return SingleGate(
        "max_drawdown",
        passed,
        f"max drawdown {dd:.2f}% {'<=' if passed else '>'} {max_dd}%",
        value=dd,
        threshold=max_dd,
    )


def _gate_profit_factor(bt: Any, thresholds: dict[str, Any]) -> SingleGate:
    min_pf = thresholds.get("min_profit_factor", _DEFAULT_MIN_PROFIT_FACTOR)
    if bt is None:
        return SingleGate("profit_factor", False, "No backtest result available")
    try:
        pf = float(bt.profit_factor)
    except (AttributeError, TypeError, ValueError):
        return SingleGate("profit_factor", False, "Could not read profit factor")
    passed = pf >= min_pf
    return SingleGate(
        "profit_factor",
        passed,
        f"profit factor {pf:.3f} {'>=' if passed else '<'} {min_pf}",
        value=pf,
        threshold=min_pf,
    )


def _gate_oos_sharpe(metrics: dict[str, Any], thresholds: dict[str, Any]) -> SingleGate:
    min_sharpe = thresholds.get("min_oos_sharpe", _DEFAULT_MIN_OOS_SHARPE)
    oos = metrics.get("mean_oos_sharpe", 0.0)
    passed = oos >= min_sharpe
    return SingleGate(
        "oos_sharpe",
        passed,
        f"mean OOS Sharpe {oos:.3f} {'>=' if passed else '<'} {min_sharpe}",
        value=oos,
        threshold=min_sharpe,
    )


def _gate_oos_degradation(metrics: dict[str, Any], thresholds: dict[str, Any]) -> SingleGate:
    min_deg = thresholds.get("min_oos_degradation", _DEFAULT_MIN_OOS_DEGRADATION)
    deg = metrics.get("oos_degradation_ratio", 0.0)
    passed = deg >= min_deg
    return SingleGate(
        "oos_degradation",
        passed,
        f"OOS degradation ratio {deg:.3f} {'>=' if passed else '<'} {min_deg}",
        value=deg,
        threshold=min_deg,
    )


def _gate_dsr(metrics: dict[str, Any], thresholds: dict[str, Any]) -> SingleGate:
    dsr_thresh = thresholds.get("dsr_threshold", _DEFAULT_DSR_THRESHOLD)
    dsr = metrics.get("deflated_sharpe", 0.0)
    passed = dsr > dsr_thresh
    return SingleGate(
        "deflated_sharpe",
        passed,
        f"DSR {dsr:.4f} {'>' if passed else '<='} {dsr_thresh}",
        value=dsr,
        threshold=dsr_thresh,
    )


def _gate_trade_count(
    bt: Any,
    expected_frequency: str,
    thresholds: dict[str, Any],
) -> SingleGate:
    freq = expected_frequency or "medium"
    default_min = _TRADE_COUNT_BY_FREQ.get(freq, _TRADE_COUNT_BY_FREQ["medium"])
    min_trades = thresholds.get("min_trade_count", default_min)
    if bt is None:
        return SingleGate("trade_count", False, "No backtest result available")
    try:
        count = int(bt.closed_trade_count)
    except (AttributeError, TypeError, ValueError):
        return SingleGate("trade_count", False, "Could not read trade count")
    passed = count >= min_trades
    return SingleGate(
        "trade_count",
        passed,
        f"trade count {count} {'>=' if passed else '<'} {min_trades} (freq={freq})",
        value=float(count),
        threshold=float(min_trades),
    )


# ---------------------------------------------------------------------------
# Overfitting defenses
# ---------------------------------------------------------------------------

def _check_period_concentration(bt: Any) -> OverfitFlag:
    """No single month should contribute > 50% of total PnL."""
    try:
        daily_pnl: dict[str, float] = getattr(bt, "daily_pnl", {}) or {}
        if not daily_pnl:
            return OverfitFlag(
                "period_concentration",
                False,
                "No daily PnL data available for period concentration check",
            )
        # Group by month
        monthly: dict[str, float] = {}
        for date_str, pnl in daily_pnl.items():
            month = str(date_str)[:7]  # "YYYY-MM"
            monthly[month] = monthly.get(month, 0.0) + float(pnl)

        total_pnl = sum(monthly.values())
        if abs(total_pnl) < 1e-9:
            return OverfitFlag(
                "period_concentration",
                False,
                "Total PnL near zero; concentration check not meaningful",
            )
        max_month_pnl = max(monthly.values(), key=abs)
        max_share = abs(max_month_pnl) / abs(total_pnl)
        flagged = max_share > _MAX_PERIOD_CONCENTRATION
        return OverfitFlag(
            "period_concentration",
            flagged,
            f"max single-month PnL share = {max_share:.1%} "
            f"(threshold {_MAX_PERIOD_CONCENTRATION:.0%})",
        )
    except Exception as exc:
        return OverfitFlag(
            "period_concentration",
            False,
            f"Check skipped: {exc}",
        )


def _check_trade_concentration(bt: Any) -> OverfitFlag:
    """No single trade should contribute > 15% of total PnL."""
    try:
        trade_pnls: list[float] = getattr(bt, "trade_pnl_list", []) or []
        if not trade_pnls:
            return OverfitFlag(
                "trade_concentration",
                False,
                "No per-trade PnL data available",
            )
        total_pnl = sum(trade_pnls)
        if abs(total_pnl) < 1e-9:
            return OverfitFlag(
                "trade_concentration",
                False,
                "Total PnL near zero; concentration check not meaningful",
            )
        max_trade = max(trade_pnls, key=abs)
        max_share = abs(max_trade) / abs(total_pnl)
        flagged = max_share > _MAX_TRADE_CONCENTRATION
        return OverfitFlag(
            "trade_concentration",
            flagged,
            f"max single-trade PnL share = {max_share:.1%} "
            f"(threshold {_MAX_TRADE_CONCENTRATION:.0%})",
        )
    except Exception as exc:
        return OverfitFlag(
            "trade_concentration",
            False,
            f"Check skipped: {exc}",
        )


def _check_parameter_fragility(
    sweep_results: list[Any] | None,
    center_score: float,
) -> OverfitFlag:
    """Neighboring parameter settings must retain >= 80% of center score."""
    if not sweep_results or len(sweep_results) < 3:
        return OverfitFlag(
            "parameter_fragility",
            False,
            "Insufficient sweep results for fragility check (need >= 3)",
        )
    try:
        scores = []
        for sr in sweep_results:
            if sr.result and hasattr(sr.result, "sharpe_ratio"):
                scores.append(float(sr.result.sharpe_ratio))

        if not scores or abs(center_score) < 1e-6:
            return OverfitFlag(
                "parameter_fragility",
                False,
                "No scored sweep results or center score is zero",
            )

        # Median neighbor score as fraction of center
        median_score = sorted(scores)[len(scores) // 2]
        retention = median_score / abs(center_score) if center_score > 0 else 0.0
        flagged = retention < _MIN_PARAM_NEIGHBOR_RETENTION
        return OverfitFlag(
            "parameter_fragility",
            flagged,
            f"median neighbor retention = {retention:.1%} "
            f"(threshold {_MIN_PARAM_NEIGHBOR_RETENTION:.0%})",
        )
    except Exception as exc:
        return OverfitFlag(
            "parameter_fragility",
            False,
            f"Check skipped: {exc}",
        )


def _compute_complexity_penalty(n_params: int, budget: int = _COMPLEXITY_PENALTY_THRESHOLD) -> float:
    """Return a [0, 1) penalty for candidates with more than budget parameters.

    The penalty scales linearly from 0 at budget params to 0.3 at budget*2 params.
    """
    if n_params <= budget:
        return 0.0
    excess = n_params - budget
    return min(0.30, excess * 0.05)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_quality_gates(
    candidate: Any,
    metrics: dict[str, Any],
    backtest_result: Any = None,
    sweep_results: list[Any] | None = None,
    thresholds: dict[str, Any] | None = None,
) -> GateReport:
    """Run all hard gates and overfitting defenses for a candidate evaluation.

    Args:
        candidate: The StrategyCandidate being evaluated.
        metrics: Score metrics dict as produced by ExperimentOrchestrator.
        backtest_result: Raw BacktestResult from the verification backtest.
        sweep_results: List of SweepResult from parameter sweep (optional).
        thresholds: Override dict for any gate threshold.

    Returns:
        GateReport with gate results, overfit flags, and complexity penalty.
    """
    t = thresholds or {}

    # Apply evaluation_rules overrides from the candidate itself
    if hasattr(candidate, "evaluation_rules") and candidate.evaluation_rules:
        for k, v in candidate.evaluation_rules.items():
            if k not in t:
                t[k] = v

    freq = getattr(candidate, "expected_trade_frequency", "medium") or "medium"
    n_params = len(
        (getattr(candidate, "effective_search_space", None) or
         getattr(candidate, "parameter_space", {}))
    )
    budget = getattr(candidate, "complexity_budget", _COMPLEXITY_PENALTY_THRESHOLD)
    center_score = metrics.get("base_sharpe", 0.0)

    hard_gates: list[SingleGate] = [
        _gate_net_pnl(backtest_result, t),
        _gate_drawdown(backtest_result, t),
        _gate_profit_factor(backtest_result, t),
        _gate_oos_sharpe(metrics, t),
        _gate_oos_degradation(metrics, t),
        _gate_dsr(metrics, t),
        _gate_trade_count(backtest_result, freq, t),
    ]

    overfit_flags: list[OverfitFlag] = [
        _check_period_concentration(backtest_result),
        _check_trade_concentration(backtest_result),
        _check_parameter_fragility(sweep_results, center_score),
    ]

    complexity_penalty = _compute_complexity_penalty(n_params, budget)
    if complexity_penalty > 0:
        overfit_flags.append(OverfitFlag(
            "complexity_penalty",
            True,
            f"{n_params} tunable parameters > budget {budget}; "
            f"penalty = {complexity_penalty:.2f}",
        ))

    all_pass = all(g.passed for g in hard_gates)

    report = GateReport(
        hard_gates=hard_gates,
        overfit_flags=overfit_flags,
        complexity_penalty=complexity_penalty,
        hard_gates_pass=all_pass,
    )

    if not all_pass:
        failed = [g.name for g in hard_gates if not g.passed]
        logger.info(
            "Candidate '%s' failed hard gates: %s",
            getattr(candidate, "name", "?"),
            failed,
        )

    return report
