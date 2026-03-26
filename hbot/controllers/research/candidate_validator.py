"""Pre-backtest candidate validation.

Validates a StrategyCandidate before any compute is consumed.
Raises ``CandidateValidationError`` with a descriptive reason on failure.

Checks:
    - adapter_mode consistency with base_config.strategy_class
    - supported strategy family (if governed)
    - required-data availability
    - invalid parameter combinations
    - position-risk and complexity-budget checks
    - family-specific parameter bounds
    - monotonicity of fast/slow and stop/target pairs

Usage::

    from controllers.research.candidate_validator import validate_candidate
    validate_candidate(candidate)  # raises on failure
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from controllers.research import StrategyCandidate

from controllers.backtesting.adapter_registry import ADAPTER_REGISTRY
from controllers.research.family_registry import (
    FAMILY_REGISTRY,
    is_phase_one_unsupported,
    is_supported_family,
)

logger = logging.getLogger(__name__)

_DEFAULT_RESEARCH_DIR = Path("hbot/data/research")


class CandidateValidationError(ValueError):
    """Raised when a candidate fails pre-backtest validation."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _check_adapter_consistency(candidate: StrategyCandidate) -> None:
    """Verify adapter_mode and base_config.strategy_class refer to the same path."""
    adapter_mode = candidate.adapter_mode
    strategy_class = candidate.base_config.get("strategy_class", "")

    if adapter_mode not in ADAPTER_REGISTRY:
        # Blueprint candidates skip backtest — nothing to validate here
        return

    if strategy_class and strategy_class != adapter_mode:
        raise CandidateValidationError(
            f"Adapter mismatch: adapter_mode='{adapter_mode}' but "
            f"base_config.strategy_class='{strategy_class}'. "
            f"They must match for the backtest engine to resolve the correct adapter."
        )


def _check_family(candidate: StrategyCandidate) -> None:
    """Reject unsupported or explicitly deferred phase-one families."""
    family_name = candidate.strategy_family
    if not family_name:
        # Legacy candidate — no family declared, allow through with a warning
        logger.warning(
            "Candidate '%s' has no strategy_family (legacy schema). "
            "Consider upgrading to schema_version 2.",
            candidate.name,
        )
        return

    if is_phase_one_unsupported(family_name):
        raise CandidateValidationError(
            f"Family '{family_name}' is not a supported phase-one family. "
            f"It requires dedicated first-class data support before it can be used."
        )

    if not is_supported_family(family_name):
        raise CandidateValidationError(
            f"Unknown strategy family: '{family_name}'. "
            f"Supported phase-one families: {sorted(FAMILY_REGISTRY.keys())}"
        )


def _check_required_data(
    candidate: StrategyCandidate,
    research_dir: Path,
) -> None:
    """Reject candidate if required data inputs are unavailable."""
    required = candidate.required_data

    # Check family-level required data too
    if candidate.strategy_family and candidate.strategy_family in FAMILY_REGISTRY:
        family = FAMILY_REGISTRY[candidate.strategy_family]
        required = list(set(required) | set(family.required_data))

    for data_type in required:
        if data_type == "funding":
            # Funding data must exist in the data catalog or as a file
            funding_paths = [
                research_dir / "data" / "funding",
                Path("hbot/data/historical/funding"),
                Path("data/historical/funding"),
            ]
            has_funding = any(p.exists() and any(p.iterdir()) for p in funding_paths if p.exists())
            if not has_funding:
                raise CandidateValidationError(
                    f"Candidate '{candidate.name}' requires funding data "
                    f"(required_data includes 'funding') but no funding dataset "
                    f"was found. Either supply funding data or remove the funding "
                    f"dependency from the candidate definition."
                )


def _check_parameter_combinations(candidate: StrategyCandidate) -> None:
    """Detect invalid or nonsensical parameter combinations."""
    search = candidate.effective_search_space
    violations: list[str] = []

    def _all_values(key_part: str) -> list[float]:
        result = []
        for k, v in search.items():
            if key_part in k:
                vals = v if isinstance(v, list) else [v]
                for val in vals:
                    try:
                        result.append(float(val))
                    except (TypeError, ValueError):
                        pass
        return result

    # Stop >= target is always invalid
    stop_vals = _all_values("stop_atr")
    target_vals = _all_values("tp_atr") or _all_values("target_atr")
    if stop_vals and target_vals:
        if min(stop_vals) >= max(target_vals):
            violations.append(
                f"stop_atr_mult min ({min(stop_vals)}) >= tp_atr_mult max "
                f"({max(target_vals)}): stop is above or equal to target"
            )

    # Fast window >= slow window
    for fast_key in [k for k in search if "fast" in k or "short" in k]:
        for slow_key in [k for k in search if "slow" in k or "long" in k]:
            fast_vals = [float(v) for v in (search[fast_key] if isinstance(search[fast_key], list) else [search[fast_key]]) if _is_numeric(v)]
            slow_vals = [float(v) for v in (search[slow_key] if isinstance(search[slow_key], list) else [search[slow_key]]) if _is_numeric(v)]
            if fast_vals and slow_vals:
                if max(fast_vals) >= min(slow_vals):
                    violations.append(
                        f"Window ordering violation: {fast_key} max ({max(fast_vals)}) "
                        f">= {slow_key} min ({min(slow_vals)})"
                    )

    # Per-trade risk above family budget
    family = FAMILY_REGISTRY.get(candidate.strategy_family) if candidate.strategy_family else None
    if family:
        risk_vals = _all_values("risk_pct") or _all_values("per_trade_risk")
        for rv in risk_vals:
            if rv > family.per_trade_risk_max_pct:
                violations.append(
                    f"per_trade_risk {rv:.3f} exceeds family maximum "
                    f"{family.per_trade_risk_max_pct:.3f} for '{family.name}'"
                )

    if violations:
        raise CandidateValidationError(
            f"Invalid parameter combinations in candidate '{candidate.name}':\n"
            + "\n".join(f"  - {v}" for v in violations)
        )


def _is_numeric(v: Any) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def _check_family_bounds(candidate: StrategyCandidate) -> None:
    """Check parameter search space against family bounds."""
    if not candidate.strategy_family:
        return
    family = FAMILY_REGISTRY.get(candidate.strategy_family)
    if not family:
        return

    search = candidate.effective_search_space
    violations = family.check_bounds(search)
    mono_violations = family.check_monotonicity(search)
    all_violations = violations + mono_violations

    if all_violations:
        raise CandidateValidationError(
            f"Parameter bounds violations for family '{family.name}' "
            f"in candidate '{candidate.name}':\n"
            + "\n".join(f"  - {v}" for v in all_violations)
        )


def _check_complexity(candidate: StrategyCandidate) -> None:
    """Warn (not reject) when complexity exceeds budget; log clearly."""
    n_params = len(candidate.effective_search_space)
    budget = candidate.complexity_budget

    # If family defines a budget, use the tighter of the two
    family = FAMILY_REGISTRY.get(candidate.strategy_family) if candidate.strategy_family else None
    if family:
        budget = min(budget, family.default_complexity_budget)

    if n_params > budget:
        logger.warning(
            "Candidate '%s' has %d tunable parameters, exceeding complexity budget %d. "
            "A simplicity penalty will be applied during ranking.",
            candidate.name,
            n_params,
            budget,
        )


def validate_candidate(
    candidate: StrategyCandidate,
    research_dir: str | Path | None = None,
) -> None:
    """Run all pre-backtest validations.

    Raises ``CandidateValidationError`` on the first hard failure.
    Logs warnings for soft issues (complexity, legacy schema).

    Args:
        candidate: The candidate to validate.
        research_dir: Root research data directory for data-availability checks.
    """
    root = Path(research_dir or _DEFAULT_RESEARCH_DIR)

    _check_adapter_consistency(candidate)
    _check_family(candidate)
    _check_required_data(candidate, root)
    _check_parameter_combinations(candidate)
    _check_family_bounds(candidate)
    _check_complexity(candidate)

    logger.info(
        "Candidate '%s' passed pre-backtest validation (family=%s, schema_version=%d)",
        candidate.name,
        candidate.strategy_family or "legacy",
        candidate.schema_version,
    )
