"""Paper Engine v2 configuration models.

This module centralizes all paper simulation knobs so strategy/controller files
only provide values, while paper_engine_v2 owns interpretation and defaults.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any
from urllib.parse import quote


@dataclass(frozen=True)
class PaperEngineConfig:
    paper_equity_quote: Decimal = Decimal("500")
    paper_reset_state_on_startup: bool = False
    paper_seed: int = 7
    paper_realism_profile: str = "custom"
    paper_fill_model: str = "queue_position"
    paper_latency_model: str = "configured_latency_ms"
    paper_latency_ms: int = 150
    paper_insert_latency_ms: int = 0
    paper_cancel_latency_ms: int = 0
    paper_liquidity_consumption: bool = False
    paper_queue_participation: Decimal = Decimal("0.35")
    paper_slippage_bps: Decimal = Decimal("1.0")
    paper_adverse_selection_bps: Decimal = Decimal("1.5")
    paper_prob_fill_on_limit: float = 0.4
    paper_prob_slippage: float = 0.0
    paper_partial_fill_min_ratio: Decimal = Decimal("0.15")
    paper_partial_fill_max_ratio: Decimal = Decimal("0.85")
    paper_depth_levels: int = 3
    paper_depth_decay: Decimal = Decimal("0.70")
    paper_queue_position_enabled: bool = False
    paper_queue_ahead_ratio: Decimal = Decimal("0.50")
    paper_queue_trade_through_ratio: Decimal = Decimal("0.35")
    paper_price_protection_points: int = 0
    paper_margin_model_type: str = "leveraged"
    paper_max_fills_per_order: int = 8
    fee_profile: str = "vip0"
    instance_name: str = "bot1"
    variant: str = "a"
    log_dir: str = "/tmp"
    artifact_namespace: str = "epp_v24"

    @staticmethod
    def _presets() -> dict[str, dict[str, Any]]:
        return {
            "conservative": {
                "paper_fill_model": "queue_position",
                "paper_latency_model": "configured_latency_ms",
                "paper_latency_ms": 220,
                "paper_insert_latency_ms": 35,
                "paper_cancel_latency_ms": 120,
                "paper_queue_participation": Decimal("0.25"),
                "paper_slippage_bps": Decimal("1.6"),
                "paper_adverse_selection_bps": Decimal("2.2"),
                "paper_prob_fill_on_limit": 0.30,
                "paper_prob_slippage": 0.05,
                "paper_partial_fill_min_ratio": Decimal("0.10"),
                "paper_partial_fill_max_ratio": Decimal("0.55"),
                "paper_depth_levels": 7,
                "paper_depth_decay": Decimal("0.60"),
                "paper_queue_position_enabled": True,
                "paper_queue_ahead_ratio": Decimal("0.60"),
                "paper_queue_trade_through_ratio": Decimal("0.28"),
                "paper_liquidity_consumption": True,
                "paper_price_protection_points": 15,
                "paper_margin_model_type": "leveraged",
            },
            "balanced": {
                "paper_fill_model": "latency_aware",
                "paper_latency_model": "configured_latency_ms",
                "paper_latency_ms": 150,
                "paper_insert_latency_ms": 20,
                "paper_cancel_latency_ms": 80,
                "paper_queue_participation": Decimal("0.35"),
                "paper_slippage_bps": Decimal("1.0"),
                "paper_adverse_selection_bps": Decimal("1.5"),
                "paper_prob_fill_on_limit": 0.40,
                "paper_prob_slippage": 0.02,
                "paper_partial_fill_min_ratio": Decimal("0.15"),
                "paper_partial_fill_max_ratio": Decimal("0.85"),
                "paper_depth_levels": 5,
                "paper_depth_decay": Decimal("0.70"),
                "paper_queue_position_enabled": True,
                "paper_queue_ahead_ratio": Decimal("0.45"),
                "paper_queue_trade_through_ratio": Decimal("0.35"),
                "paper_liquidity_consumption": True,
                "paper_price_protection_points": 8,
                "paper_margin_model_type": "leveraged",
            },
            "aggressive": {
                "paper_fill_model": "best_price",
                "paper_latency_model": "configured_latency_ms",
                "paper_latency_ms": 80,
                "paper_insert_latency_ms": 5,
                "paper_cancel_latency_ms": 30,
                "paper_queue_participation": Decimal("0.60"),
                "paper_slippage_bps": Decimal("0.4"),
                "paper_adverse_selection_bps": Decimal("0.8"),
                "paper_prob_fill_on_limit": 0.75,
                "paper_prob_slippage": 0.0,
                "paper_partial_fill_min_ratio": Decimal("0.35"),
                "paper_partial_fill_max_ratio": Decimal("1.00"),
                "paper_depth_levels": 3,
                "paper_depth_decay": Decimal("0.85"),
                "paper_queue_position_enabled": False,
                "paper_queue_ahead_ratio": Decimal("0.30"),
                "paper_queue_trade_through_ratio": Decimal("0.50"),
                "paper_liquidity_consumption": False,
                "paper_price_protection_points": 3,
                "paper_margin_model_type": "leveraged",
            },
        }

    @classmethod
    def from_controller_config(cls, cfg: Any) -> PaperEngineConfig:
        nested_payload: dict[str, Any] = {}
        nested = getattr(cfg, "paper_engine", None)
        if nested is not None:
            if isinstance(nested, PaperEngineConfig):
                nested_payload = asdict(nested)
            if isinstance(nested, dict):
                nested_payload = dict(nested)
            elif hasattr(nested, "model_dump"):
                try:
                    nested_payload = dict(nested.model_dump())
                except Exception:
                    nested_payload = {}
            else:
                for k in cls.__dataclass_fields__:
                    if hasattr(nested, k):
                        nested_payload[k] = getattr(nested, k)
            if nested_payload:
                profile = str(nested_payload.get("paper_realism_profile", "custom") or "custom").strip().lower()
                chosen = cls._presets().get(profile, {})
                merged = dict(nested_payload)
                merged.update({k: v for k, v in chosen.items()})
                merged["paper_realism_profile"] = profile
                # Keep PaperDesk persistence keys bot-scoped.
                # Identity comes from the controller-level config (instance/variant/log_dir),
                # even when paper_engine nested defaults carry "bot1".
                merged["instance_name"] = str(
                    getattr(cfg, "instance_name", merged.get("instance_name", cls.instance_name))
                    or merged.get("instance_name", cls.instance_name)
                )
                merged["variant"] = str(
                    getattr(cfg, "variant", merged.get("variant", cls.variant))
                    or merged.get("variant", cls.variant)
                )
                merged["log_dir"] = str(
                    getattr(cfg, "log_dir", merged.get("log_dir", cls.log_dir))
                    or merged.get("log_dir", cls.log_dir)
                )
                controller_name = str(getattr(cfg, "controller_name", "") or "").strip().lower()
                default_artifact_namespace = "epp_v24" if controller_name.startswith("epp_") else "runtime_v24"
                merged["artifact_namespace"] = str(
                    getattr(cfg, "artifact_namespace", merged.get("artifact_namespace", default_artifact_namespace))
                    or merged.get("artifact_namespace", default_artifact_namespace)
                ).strip() or default_artifact_namespace
                return cls(**merged)
            # Pydantic model or namespace-like object
        from simulation.exceptions import ConfigurationError

        raise ConfigurationError("Missing nested paper_engine config")

    @staticmethod
    def resolve_redis_url_from_env() -> str | None:
        """Build redis URL from env; include REDIS_PASSWORD when set (matches requirepass)."""
        explicit = (os.environ.get("REDIS_URL") or "").strip()
        if explicit:
            return explicit
        rh = (os.environ.get("REDIS_HOST") or "").strip()
        if not rh:
            return None
        rp = (os.environ.get("REDIS_PORT") or "6379").strip()
        db = (os.environ.get("REDIS_DB") or "0").strip()
        pwd = (os.environ.get("REDIS_PASSWORD") or "").strip()
        if pwd:
            enc = quote(pwd, safe="")
            return f"redis://:{enc}@{rh}:{rp}/{db}"
        return f"redis://{rh}:{rp}/{db}"

