"""Composite robustness scoring for strategy candidates.

Replaces single-metric ranking with a weighted multi-component score
that penalises overfitting signals: IS/OOS gap, parameter instability,
fee sensitivity, regime fragility, and selection bias.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ComponentScore:
    """Score for a single robustness component."""

    raw_value: float
    normalised: float
    weight: float
    weighted_contribution: float


@dataclass
class ScoreBreakdown:
    """Full breakdown of a composite robustness score."""

    total_score: float
    components: dict[str, ComponentScore]
    recommendation: str  # "reject" | "revise" | "pass"


_DEFAULT_WEIGHTS = {
    "oos_sharpe": 0.25,
    "oos_degradation": 0.20,
    "param_stability": 0.15,
    "fee_stress": 0.15,
    "regime_stability": 0.15,
    "dsr_pass": 0.10,
}


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


class RobustnessScorer:
    """Compute composite robustness score from walk-forward and sweep data."""

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        w = dict(weights or _DEFAULT_WEIGHTS)
        total = sum(w.values())
        if total > 0 and abs(total - 1.0) > 1e-6:
            w = {k: v / total for k, v in w.items()}
        self._weights = w

    def score(self, metrics: dict[str, Any]) -> ScoreBreakdown:
        """Compute the composite score from evaluation metrics.

        Expected keys in metrics:
            - mean_oos_sharpe: float
            - oos_degradation_ratio: float
            - param_cv: dict[str, float]  (coefficient of variation per param)
            - fee_stress_sharpes: list[float] or None
            - base_sharpe: float  (for fee normalisation)
            - regime_oos_degradation: dict[str, float]
            - deflated_sharpe: float
        """
        components: dict[str, ComponentScore] = {}
        available_weight = 0.0
        available_components: dict[str, float] = {}

        oos_sharpe_val = metrics.get("mean_oos_sharpe", 0.0)
        norm_oos = _clamp(oos_sharpe_val / 3.0)
        components["oos_sharpe"] = ComponentScore(oos_sharpe_val, norm_oos, self._weights.get("oos_sharpe", 0), 0)

        oos_deg = metrics.get("oos_degradation_ratio", 0.0)
        threshold = metrics.get("oos_threshold", 0.5)
        norm_deg = 1.0 if oos_deg >= threshold else _clamp(oos_deg / max(threshold, 1e-6))
        components["oos_degradation"] = ComponentScore(oos_deg, norm_deg, self._weights.get("oos_degradation", 0), 0)

        param_cv = metrics.get("param_cv", {})
        if param_cv:
            mean_cv = sum(param_cv.values()) / len(param_cv) if param_cv else 0
            norm_param = _clamp(1.0 - mean_cv)
        else:
            norm_param = 0.5
        components["param_stability"] = ComponentScore(
            1.0 - (sum(param_cv.values()) / max(len(param_cv), 1)),
            norm_param, self._weights.get("param_stability", 0), 0,
        )

        fee_sharpes = metrics.get("fee_stress_sharpes")
        base_sharpe = metrics.get("base_sharpe", metrics.get("mean_oos_sharpe", 1.0))
        if fee_sharpes and base_sharpe and abs(base_sharpe) > 1e-6:
            min_stressed = min(fee_sharpes)
            norm_fee = _clamp(min_stressed / abs(base_sharpe))
        elif fee_sharpes is None:
            norm_fee = 0.0
            available_weight += self._weights.get("fee_stress", 0)
        else:
            norm_fee = 0.0
        components["fee_stress"] = ComponentScore(
            min(fee_sharpes) if fee_sharpes else 0, norm_fee,
            self._weights.get("fee_stress", 0), 0,
        )

        regime_oos = metrics.get("regime_oos_degradation", {})
        overall_oos = metrics.get("mean_oos_sharpe", 0.0)
        if regime_oos and abs(overall_oos) > 1e-6:
            min_regime = min(regime_oos.values()) if regime_oos else overall_oos
            norm_regime = _clamp(min_regime / abs(overall_oos))
        else:
            norm_regime = 0.5
        components["regime_stability"] = ComponentScore(
            min(regime_oos.values()) if regime_oos else 0,
            norm_regime, self._weights.get("regime_stability", 0), 0,
        )

        dsr = metrics.get("deflated_sharpe", 0.0)
        norm_dsr = 1.0 if dsr > 0 else 0.0
        components["dsr_pass"] = ComponentScore(dsr, norm_dsr, self._weights.get("dsr_pass", 0), 0)

        if available_weight > 0:
            remaining = 1.0 - available_weight
            if remaining > 0:
                for name in components:
                    if name != "fee_stress" or fee_sharpes is not None:
                        components[name] = ComponentScore(
                            components[name].raw_value,
                            components[name].normalised,
                            components[name].weight / remaining if remaining > 0 else 0,
                            0,
                        )

        total = 0.0
        for name, cs in components.items():
            wc = cs.normalised * cs.weight
            components[name] = ComponentScore(cs.raw_value, cs.normalised, cs.weight, wc)
            total += wc

        total = _clamp(total)

        if total < 0.35:
            recommendation = "reject"
        elif total < 0.55:
            recommendation = "revise"
        else:
            recommendation = "pass"

        return ScoreBreakdown(
            total_score=total,
            components=components,
            recommendation=recommendation,
        )
