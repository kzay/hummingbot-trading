"""Strategy Research Lab — robust strategy evaluation and lifecycle management.

This module wraps the existing backtest/sweep/walk-forward infrastructure
with governance, robustness scoring, and experiment tracking.  It never
imports production strategy code (controllers.bots.*) directly.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class StrategyLifecycle(enum.Enum):
    """Lifecycle stages for a strategy candidate."""

    CANDIDATE = "candidate"
    REJECTED = "rejected"
    REVISE = "revise"
    PAPER = "paper"
    PROMOTED = "promoted"

    def can_transition_to(self, target: StrategyLifecycle) -> bool:
        return target.value in _VALID_TRANSITIONS.get(self.value, set())


_VALID_TRANSITIONS: dict[str, set[str]] = {
    "candidate": {"rejected", "revise", "paper"},
    "revise": {"candidate", "rejected", "paper"},
    "paper": {"rejected", "revise", "promoted"},
    "rejected": set(),
    "promoted": set(),
}

# Governed schema version; legacy YAML files are treated as schema_version 1.
_CURRENT_SCHEMA_VERSION = 2


@dataclass
class StrategyCandidate:
    """Unified research interface for a strategy candidate.

    Captures the hypothesis, formal entry/exit logic, parameter space,
    required tests, and base backtest configuration.

    Governed additive fields (schema_version 2):
        - schema_version: int distinguishing legacy (1) from governed (2) YAML
        - strategy_family: one of the phase-one family names
        - template_id: specific template within the family
        - search_space: governed search definition (preferred over parameter_space)
        - constraints: invalid-combination rules for this candidate
        - required_data: data inputs the candidate needs (e.g. ["funding"])
        - market_conditions: conditions under which the hypothesis holds
        - expected_trade_frequency: "low" | "medium" | "high"
        - evaluation_rules: overrides for gate thresholds
        - promotion_policy: overrides for promotion requirements
        - complexity_budget: max allowed tunable parameters
    """

    # Legacy required fields
    name: str
    hypothesis: str
    adapter_mode: str
    parameter_space: dict[str, Any]
    entry_logic: str
    exit_logic: str
    base_config: dict[str, Any]
    required_tests: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    lifecycle: StrategyLifecycle = StrategyLifecycle.CANDIDATE
    new_adapter_description: str = ""

    # Governed fields (schema_version 2) — all optional for backward compat
    schema_version: int = 1
    strategy_family: str = ""
    template_id: str = ""
    search_space: dict[str, Any] = field(default_factory=dict)
    constraints: list[str] = field(default_factory=list)
    required_data: list[str] = field(default_factory=list)
    market_conditions: str = ""
    expected_trade_frequency: str = "medium"  # "low" | "medium" | "high"
    evaluation_rules: dict[str, Any] = field(default_factory=dict)
    promotion_policy: dict[str, Any] = field(default_factory=dict)
    complexity_budget: int = 6

    @property
    def effective_search_space(self) -> dict[str, Any]:
        """Return the governed search_space if present, else parameter_space.

        This normalizes legacy ``parameter_space`` and governed ``search_space``
        into one definition that callers (sweep, walk-forward) should use.
        """
        return self.search_space if self.search_space else self.parameter_space

    @property
    def is_governed(self) -> bool:
        """True when the candidate has the full governed schema."""
        return self.schema_version >= 2 and bool(self.strategy_family)

    @classmethod
    def from_yaml(cls, path: str | Path) -> StrategyCandidate:
        """Load a candidate definition from a YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f)

        required_fields = ["name", "hypothesis", "adapter_mode", "parameter_space",
                           "entry_logic", "exit_logic", "base_config"]
        for fld in required_fields:
            if fld not in data:
                raise ValueError(f"Missing required field: {fld}")

        lifecycle_str = data.pop("lifecycle", "candidate")
        lifecycle = StrategyLifecycle(lifecycle_str)

        # Determine schema version: if governed fields are present treat as v2,
        # otherwise mark as legacy v1.
        has_governed = bool(
            data.get("strategy_family") or
            data.get("search_space") or
            data.get("schema_version", 0) >= 2
        )
        schema_version = int(data.get("schema_version", 2 if has_governed else 1))

        return cls(
            name=data["name"],
            hypothesis=data["hypothesis"],
            adapter_mode=data["adapter_mode"],
            parameter_space=data.get("parameter_space", {}),
            entry_logic=data["entry_logic"],
            exit_logic=data["exit_logic"],
            base_config=data["base_config"],
            required_tests=data.get("required_tests", []),
            metadata=data.get("metadata", {}),
            lifecycle=lifecycle,
            new_adapter_description=data.get("new_adapter_description", ""),
            # Governed fields
            schema_version=schema_version,
            strategy_family=data.get("strategy_family", ""),
            template_id=data.get("template_id", ""),
            search_space=data.get("search_space", {}),
            constraints=data.get("constraints", []),
            required_data=data.get("required_data", []),
            market_conditions=data.get("market_conditions", ""),
            expected_trade_frequency=data.get("expected_trade_frequency", "medium"),
            evaluation_rules=data.get("evaluation_rules", {}),
            promotion_policy=data.get("promotion_policy", {}),
            complexity_budget=int(data.get("complexity_budget", 6)),
        )

    def to_yaml(self, path: str | Path) -> None:
        """Save the candidate definition to a YAML file."""
        data: dict[str, Any] = {
            "name": self.name,
            "hypothesis": self.hypothesis,
            "adapter_mode": self.adapter_mode,
            "parameter_space": self.parameter_space,
            "entry_logic": self.entry_logic,
            "exit_logic": self.exit_logic,
            "base_config": self.base_config,
            "required_tests": self.required_tests,
            "metadata": self.metadata,
            "lifecycle": self.lifecycle.value,
            "schema_version": self.schema_version,
        }
        if self.new_adapter_description:
            data["new_adapter_description"] = self.new_adapter_description
        # Always serialise governed fields when present
        if self.strategy_family:
            data["strategy_family"] = self.strategy_family
        if self.template_id:
            data["template_id"] = self.template_id
        if self.search_space:
            data["search_space"] = self.search_space
        if self.constraints:
            data["constraints"] = self.constraints
        if self.required_data:
            data["required_data"] = self.required_data
        if self.market_conditions:
            data["market_conditions"] = self.market_conditions
        if self.expected_trade_frequency != "medium":
            data["expected_trade_frequency"] = self.expected_trade_frequency
        if self.evaluation_rules:
            data["evaluation_rules"] = self.evaluation_rules
        if self.promotion_policy:
            data["promotion_policy"] = self.promotion_policy
        if self.complexity_budget != 6:
            data["complexity_budget"] = self.complexity_budget
        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
