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


@dataclass
class StrategyCandidate:
    """Unified research interface for a strategy candidate.

    Captures the hypothesis, formal entry/exit logic, parameter space,
    required tests, and base backtest configuration.
    """

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
        )

    def to_yaml(self, path: str | Path) -> None:
        """Save the candidate definition to a YAML file."""
        data = {
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
        }
        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
