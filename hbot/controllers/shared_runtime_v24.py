from __future__ import annotations

import csv
import json
import logging
import math
import os
import time as _time_mod
from collections import deque
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

from pydantic import Field, field_validator
from pydantic_core.core_schema import ValidationInfo

from hummingbot.core.data_type.common import PriceType, TradeType
from hummingbot.core.event.events import MarketOrderFailureEvent, OrderCancelledEvent, OrderFilledEvent
from hummingbot.strategy_v2.controllers.market_making_controller_base import (
    MarketMakingControllerBase,
    MarketMakingControllerConfigBase,
)

from controllers.connector_runtime_adapter import ConnectorRuntimeAdapter
from controllers.runtime.core import (
    artifact_namespace as _artifact_namespace,
    resolve_runtime_compatibility,
    runtime_metadata,
)
from controllers.runtime.contracts import RuntimeFamilyAdapter
from controllers.runtime.data_context import RuntimeDataContext
from controllers.runtime.execution_context import RuntimeExecutionPlan
from controllers.runtime.market_making_core import MarketMakingRuntimeAdapter
from controllers.runtime.market_making_types import (
    MarketConditions,
    RegimeSpec,
    RuntimeLevelState,
    SpreadEdgeState,
    clip,
)
from controllers.runtime.risk_context import RuntimeRiskDecision
from controllers.daily_state_store import DailyStateStore
from controllers.types import ProcessedState
from controllers.runtime.logging import CsvSplitLogger
from controllers.ops_guard import GuardState, OpsGuard, OpsSnapshot
from controllers.price_buffer import MidPriceBuffer
from controllers.regime_detector import RegimeDetector
from controllers.risk_evaluator import RiskEvaluator
from controllers.spread_engine import SpreadEngine
from controllers.tick_emitter import TickEmitter
from controllers.paper_engine_v2.config import PaperEngineConfig
from services.common.exchange_profiles import resolve_profile
from services.common.fee_provider import FeeResolver
from services.common.market_history_policy import runtime_seed_policy, status_meets_policy
from services.common.market_history_provider_impl import MarketHistoryProviderImpl
from services.common.market_history_types import MarketBarKey
from services.common.utils import to_decimal
from services.contracts.stream_names import PORTFOLIO_RISK_STREAM
from controllers.analytics.performance_metrics import max_drawdown_with_metadata

_clip = clip

_ZERO = Decimal("0")
_ONE = Decimal("1")
_TWO = Decimal("2")
_100 = Decimal("100")
_10K = Decimal("10000")
_MIN_SPREAD = Decimal("0.0001")
_MIN_SKEW_CAP = Decimal("0.0005")
_FILL_FACTOR_LO = Decimal("0.05")
_BALANCE_EPSILON = Decimal("1e-8")
_INVENTORY_DERISK_REASONS = frozenset({"base_pct_above_max", "base_pct_below_min", "eod_close_pending"})
_BOT_MODE_WARNED_INVALID = False


def _runtime_bot_mode() -> str:
    """Return canonical runtime mode (`paper`|`live`) from BOT_MODE env."""
    global _BOT_MODE_WARNED_INVALID
    mode = str(os.environ.get("BOT_MODE", "") or "").strip().lower()
    if mode in {"paper", "live"}:
        return mode
    if not _BOT_MODE_WARNED_INVALID:
        logger.warning(
            "Invalid BOT_MODE=%s; defaulting to paper mode. "
            "Deprecated internal_paper_enabled is ignored.",
            mode or "<empty>",
        )
        _BOT_MODE_WARNED_INVALID = True
    return "paper"


def _canonical_connector_name(connector_name: str) -> str:
    if not str(connector_name).endswith("_paper_trade"):
        return connector_name
    profile = resolve_profile(connector_name)
    if isinstance(profile, dict):
        required = profile.get("requires_paper_trade_exchange")
        if isinstance(required, str) and required:
            return required
    return connector_name[:-12]


def _config_is_paper(config: Any) -> bool:
    explicit = getattr(config, "is_paper", None)
    if explicit is not None:
        return bool(explicit)
    return str(getattr(config, "bot_mode", "")).strip().lower() == "paper"


def _paper_reset_state_on_startup_enabled(config: Any) -> bool:
    paper_engine = getattr(config, "paper_engine", None)
    if isinstance(paper_engine, dict):
        return bool(paper_engine.get("paper_reset_state_on_startup", False))
    if paper_engine is None:
        return False
    return bool(getattr(paper_engine, "paper_reset_state_on_startup", False))


def _identity_text(value: Any) -> str:
    """Return routable identity text only for scalar values.

    Test doubles such as ``MagicMock`` should behave like missing identity, not as a
    foreign route, otherwise mock-based unit tests fail closed unintentionally.
    """
    if isinstance(value, (str, int, float)):
        return str(value).strip()
    return ""


def _runtime_family_adapter(controller: Any) -> RuntimeFamilyAdapter:
    adapter = getattr(controller, "_family_adapter", None)
    if adapter is None:
        make_adapter = getattr(controller, "_make_runtime_family_adapter", None)
        if callable(make_adapter):
            adapter = make_adapter()
        else:
            adapter = MarketMakingRuntimeAdapter(controller)
        setattr(controller, "_family_adapter", adapter)
    return adapter


def _market_making_adapter(controller: Any) -> RuntimeFamilyAdapter:
    """Backward-compatible alias for historical helper name."""
    return _runtime_family_adapter(controller)


def _runtime_compat_surface(controller: Any):
    surface = getattr(controller, "_runtime_compat", None)
    if surface is None:
        config = getattr(controller, "config", None)
        surface = resolve_runtime_compatibility(
            config,
            runtime_impl=type(controller).__name__.replace("Controller", "") or "shared_mm_v24",
        )
        setattr(controller, "_runtime_compat", surface)
    return surface


class EppV24Config(MarketMakingControllerConfigBase):
    """Configuration for EPP v2.4 controller.

    Historical note: "EPP" started as the bot1 strategy label. This config and
    controller now serve as shared v2.4 market-making infrastructure used by
    multiple strategy lanes.

    Variants: a = live trading, b/c = disabled stubs, d = no-trade observation.
    """

    controller_name: str = "epp_v2_4"

    connector_type: str = Field(
        default="auto",
        description=(
            "Explicit connector category: 'spot' | 'perp' | 'auto'. "
            "Controls accounting (equity calc, signed vs gross exposure, margin ratio). "
            "'auto' infers from connector_name for backward compat."
        ),
    )

    variant: str = Field(default="a", description="Controller variant: a=live, b/c=disabled, d=no-trade", json_schema_extra={"prompt": "Variant a/b/c/d: ", "prompt_on_new": True})
    enabled: bool = Field(default=True, description="Master enable switch for this controller", json_schema_extra={"prompt": "Enabled (true/false): ", "prompt_on_new": True})
    no_trade: bool = Field(default=False, description="When True, run all logic but place zero orders", json_schema_extra={"prompt": "No-trade mode: ", "prompt_on_new": True})
    instance_name: str = Field(default="bot1", description="Bot instance identifier for logging and multi-bot policies", json_schema_extra={"prompt": "Instance name: ", "prompt_on_new": True})
    artifact_namespace: str = Field(
        default="",
        description=(
            "Optional namespace for persisted runtime artifacts (logs/state/keys). "
            "Empty uses legacy `epp_v24` for `epp_*` controllers and `runtime_v24` otherwise."
        ),
    )
    log_dir: str = Field(default="/home/hummingbot/logs", description="Root directory for CSV logs")
    candles_connector: Optional[str] = Field(default=None, description="Override connector for candle data")
    candles_trading_pair: Optional[str] = Field(default=None, description="Override trading pair for candle data")

    # Exchange profile (VIP0)
    fee_mode: str = Field(default="auto", description="Fee resolution strategy: auto (API first) | project (profile file) | manual (spot_fee_pct)")
    fee_profile: str = Field(default="vip0", description="Fee profile key in fee_profiles.json")
    require_fee_resolution: bool = Field(default=True, description="HARD_STOP if fee resolution fails when True")
    fee_refresh_s: int = Field(default=300, ge=10, le=3600, description="Seconds between fee resolution attempts")
    spot_fee_pct: Decimal = Field(default=Decimal("0.0010"), description="Manual/fallback fee rate as decimal (0.001 = 0.1%)")
    slippage_est_pct: Decimal = Field(default=Decimal("0.0005"), description="Estimated slippage deducted from edge calculation")
    fill_factor: Decimal = Field(default=Decimal("0.4"), description="Global fallback fill factor [0.05..1]. Per-regime fill_factor in RegimeSpec takes precedence when set. Lower = more conservative edge gating.")
    turnover_cap_x: Decimal = Field(default=Decimal("3.0"), description="Daily turnover multiple before spread/level widening kicks in")
    turnover_penalty_step: Decimal = Field(default=Decimal("0.0010"), description="Additional spread cost per 1x turnover beyond turnover_cap_x. Acts as a soft throttle: at 6x turnover the penalty is 0.3%%, suppressing net edge and triggering edge gate before the hard limit fires.")

    # Regime detection
    high_vol_band_pct: Decimal = Field(default=Decimal("0.0080"), description="ATR/price ratio threshold for high-vol regime")
    shock_drift_30s_pct: Decimal = Field(default=Decimal("0.0100"), description="30-second price drift threshold for shock regime (absolute fallback)")
    shock_drift_atr_multiplier: Decimal = Field(default=Decimal("1.25"), description="Shock fires when 30s drift > ATR_band * this multiplier (vol-adaptive)")
    trend_eps_pct: Decimal = Field(default=Decimal("0.0010"), description="Mid vs EMA threshold for up/down trend detection")

    # Runtime controls
    sample_interval_s: int = Field(default=10, ge=5, le=30)
    spread_floor_recalc_s: int = Field(
        default=0,
        description=(
            "DEPRECATED: spread floor now recomputed every tick for consistency with edge gate. "
            "Kept for config compatibility."
        ),
    )
    daily_rollover_hour_utc: int = Field(default=0, ge=0, le=23)
    cancel_budget_per_min: int = Field(default=50)
    min_net_edge_bps: Decimal = Field(default=Decimal("1"))
    cancel_pause_cooldown_s: int = Field(default=120)
    edge_resume_bps: Decimal = Field(default=Decimal("4"))
    edge_state_hold_s: int = Field(default=120, ge=5, le=3600)
    edge_gate_ewma_period: int = Field(default=6, ge=1, le=120, description="EWMA period (in ticks) used for edge gate decision. 1=disabled")
    shared_edge_gate_enabled: bool = Field(
        default=True,
        description=(
            "Enable the shared net-edge soft-pause gate. Baseline market-making lanes should "
            "keep this enabled; dedicated strategy controllers can disable it when edge is not "
            "part of their strategy-local validity checks."
        ),
    )
    adaptive_params_enabled: bool = Field(
        default=True,
        description="Enable history-based auto-adaptation of edge floor and spread floor.",
    )
    adaptive_fill_target_age_s: int = Field(
        default=900, ge=60, le=7200,
        description="Target max age of last fill; older ages relax edge floor to re-activate quoting.",
    )
    adaptive_edge_relax_max_bps: Decimal = Field(
        default=Decimal("8"),
        description="Maximum bps reduction applied to min edge threshold when fills are stale.",
    )
    adaptive_edge_tighten_max_bps: Decimal = Field(
        default=Decimal("3"),
        description="Maximum bps increase applied to min edge threshold when fills are very frequent.",
    )
    adaptive_min_edge_bps_floor: Decimal = Field(
        default=Decimal("1"),
        description="Lower hard bound for adaptive effective min edge threshold (bps).",
    )
    adaptive_min_edge_bps_cap: Decimal = Field(
        default=Decimal("30"),
        description="Upper hard bound for adaptive effective min edge threshold (bps).",
    )
    adaptive_market_spread_ewma_alpha: Decimal = Field(
        default=Decimal("0.08"),
        description="EWMA alpha for market spread bps history used by adaptation logic.",
    )
    adaptive_band_ewma_alpha: Decimal = Field(
        default=Decimal("0.08"),
        description="EWMA alpha for volatility band history used by adaptation logic.",
    )
    adaptive_market_edge_bonus_factor: Decimal = Field(
        default=Decimal("0.25"),
        description="Fraction of market spread bps added as adaptive edge bonus in wider markets.",
    )
    adaptive_market_edge_bonus_cap_bps: Decimal = Field(
        default=Decimal("4"),
        description="Cap for market-spread-derived edge bonus (bps).",
    )
    adaptive_vol_edge_bonus_cap_bps: Decimal = Field(
        default=Decimal("3"),
        description="Cap for volatility-derived edge bonus (bps).",
    )
    adaptive_market_floor_factor: Decimal = Field(
        default=Decimal("0.35"),
        description="Factor applied to spread-bps EWMA to create adaptive market spread floor.",
    )
    adaptive_vol_spread_widen_max: Decimal = Field(
        default=Decimal("0.35"),
        description="Max additional spread widening in high volatility (0.35 = +35%).",
    )
    pnl_governor_enabled: bool = Field(
        default=False,
        description="Enable daily PnL target governor to relax edge gate when behind schedule.",
    )
    daily_pnl_target_pct: Decimal = Field(
        default=Decimal("0"),
        description="Daily PnL target as pct of opening equity (e.g. 1.0 = +1%). Takes priority over quote target.",
    )
    daily_pnl_target_quote: Decimal = Field(
        default=Decimal("0"),
        description="Legacy daily net PnL quote target. Used only when daily_pnl_target_pct <= 0.",
    )
    execution_intent_override_ttl_s: int = Field(
        default=1800,
        ge=0,
        le=86_400,
        description=(
            "Seconds before external execution-intent target overrides expire automatically. "
            "Set 0 to disable expiry."
        ),
    )
    pnl_governor_activation_buffer_pct: Decimal = Field(
        default=Decimal("0.05"),
        description="Required relative deficit buffer before governor activates (0.05 = 5% of target).",
    )
    pnl_governor_max_edge_bps_cut: Decimal = Field(
        default=Decimal("5"),
        description="Maximum bps reduction of effective min edge when materially behind PnL target.",
    )
    pnl_governor_max_size_boost_pct: Decimal = Field(
        default=Decimal("0"),
        description="Maximum sizing boost pct when behind target (e.g. 0.30 = +30%).",
    )
    pnl_governor_size_activation_deficit_pct: Decimal = Field(
        default=Decimal("0.10"),
        description="Minimum normalized deficit before dynamic sizing boost activates.",
    )
    pnl_governor_turnover_soft_cap_x: Decimal = Field(
        default=Decimal("4.0"),
        description="Disable size boost when turnover exceeds this soft cap.",
    )
    pnl_governor_drawdown_soft_cap_pct: Decimal = Field(
        default=Decimal("0.02"),
        description="Disable size boost when drawdown exceeds this soft cap.",
    )
    max_quote_to_market_spread_mult: Decimal = Field(
        default=Decimal("0"),
        description="Cap quote spread as multiple of observed market spread. 0 disables.",
    )
    min_side_spread_bps: Decimal = Field(
        default=Decimal("1.0"),
        description="Minimum side spread floor in bps for competitiveness cap and market safety.",
    )
    min_market_spread_bps: int = Field(default=0, ge=0, le=100)
    auto_calibration_enabled: bool = Field(
        default=False,
        description="Enable bounded runtime auto-calibration of spread/edge knobs.",
    )
    auto_calibration_shadow_mode: bool = Field(
        default=True,
        description="When True, emit suggested tuning decisions without applying them.",
    )
    auto_calibration_update_interval_s: int = Field(
        default=900, ge=60, le=7200,
        description="Seconds between auto-calibration evaluations.",
    )
    auto_calibration_lookback_s: int = Field(
        default=1800, ge=300, le=21600,
        description="Lookback window size for auto-calibration metrics.",
    )
    auto_calibration_required_consecutive_relax_cycles: int = Field(
        default=2, ge=1, le=20,
        description="Consecutive relax signals required before applying relaxation.",
    )
    auto_calibration_max_step_bps: Decimal = Field(
        default=Decimal("0.20"),
        description="Maximum per-evaluation parameter move in bps.",
    )
    auto_calibration_max_total_change_per_hour_bps: Decimal = Field(
        default=Decimal("0.60"),
        description="Maximum absolute cumulative parameter moves (bps) over rolling hour.",
    )
    auto_calibration_min_net_edge_bps_min: Decimal = Field(default=Decimal("1.0"))
    auto_calibration_min_net_edge_bps_max: Decimal = Field(default=Decimal("6.0"))
    auto_calibration_edge_resume_bps_min: Decimal = Field(default=Decimal("1.0"))
    auto_calibration_edge_resume_bps_max: Decimal = Field(default=Decimal("4.0"))
    auto_calibration_min_side_spread_bps_min: Decimal = Field(default=Decimal("0.10"))
    auto_calibration_min_side_spread_bps_max: Decimal = Field(default=Decimal("1.20"))
    auto_calibration_relax_fills_lt: int = Field(default=2, ge=0, le=100)
    auto_calibration_relax_edge_gate_blocked_ratio_gt: Decimal = Field(default=Decimal("0.40"))
    auto_calibration_relax_orders_active_ratio_lt: Decimal = Field(default=Decimal("0.50"))
    auto_calibration_relax_order_book_stale_ratio_lt: Decimal = Field(default=Decimal("0.10"))
    auto_calibration_tighten_slippage_p95_bps_gt: Decimal = Field(default=Decimal("3.5"))
    auto_calibration_tighten_net_pnl_bps_lt: Decimal = Field(default=Decimal("-8.0"))
    auto_calibration_tighten_taker_ratio_gt: Decimal = Field(default=Decimal("0.70"))
    auto_calibration_freeze_drawdown_pct: Decimal = Field(default=Decimal("0.015"))
    auto_calibration_freeze_daily_loss_pct: Decimal = Field(default=Decimal("0.012"))
    auto_calibration_freeze_order_book_stale_ratio_gt: Decimal = Field(default=Decimal("0.15"))
    auto_calibration_rollback_enabled: bool = Field(default=True)
    auto_calibration_rollback_negative_windows: int = Field(default=3, ge=1, le=20)
    max_clock_skew_s: float = Field(default=5.0, description="Maximum allowed clock skew tolerance for order book staleness detection")
    order_book_stale_after_s: float = Field(
        default=30.0,
        ge=5.0,
        le=300.0,
        description=(
            "Seconds of unchanged top-of-book before marking order_book_stale "
            "(before max_clock_skew_s is added)."
        ),
    )
    order_book_stale_soft_pause_after_s: float = Field(
        default=75.0,
        ge=10.0,
        le=600.0,
        description=(
            "Seconds of sustained stale-book age required before forcing SOFT_PAUSE. "
            "Helps avoid cancel/recreate churn on transient websocket reconnects."
        ),
    )
    order_book_reconnect_grace_s: float = Field(
        default=45.0,
        ge=0.0,
        le=300.0,
        description=(
            "Additional grace window after connector reconnect before stale-book "
            "is considered actionable."
        ),
    )
    portfolio_risk_guard_enabled: bool = Field(
        default=True,
        description="When enabled, enforce global portfolio kill-switch snapshots from Redis stream.",
    )
    portfolio_risk_guard_check_s: int = Field(
        default=2, ge=1, le=30,
        description="Seconds between portfolio risk snapshot checks in preflight.",
    )
    portfolio_risk_guard_max_age_s: int = Field(
        default=15, ge=1, le=300,
        description="Ignore portfolio risk snapshots older than this many seconds.",
    )
    portfolio_risk_stream_name: str = Field(
        default=PORTFOLIO_RISK_STREAM,
        description="Redis stream containing portfolio risk snapshots.",
    )
    inventory_skew_cap_pct: Decimal = Field(default=Decimal("0.0030"))
    inventory_skew_vol_multiplier: Decimal = Field(default=Decimal("1.0"))
    perp_target_net_base_pct: Optional[Decimal] = Field(
        default=None,
        description="Perps only: signed net exposure target as fraction of equity (e.g. 0.0 = delta-neutral). When None, defaults to 0 for perps.",
    )
    adverse_drift_ewma_alpha: Decimal = Field(
        default=Decimal("0.25"),
        description="EWMA alpha for adverse drift smoothing used in cost model (0.05=very smooth, 0.5=responsive). Raw drift still used for regime detection.",
    )
    drift_spike_threshold_bps: int = Field(
        default=5, ge=1, le=100,
        description="Excess drift (raw - smooth, in bps) above which spread starts widening. Protects against adverse selection during spikes.",
    )
    drift_spike_mult_max: Decimal = Field(
        default=Decimal("1.8"),
        description="Maximum spread multiplier applied when drift excess hits or exceeds drift_spike_threshold_bps. E.g. 1.8 = spread widens up to 80% during a spike.",
    )
    neutral_trend_guard_pct: Decimal = Field(
        default=Decimal("0"),
        ge=Decimal("0"),
        le=Decimal("0.01"),
        description=(
            "In neutral_low_vol only, suppress the counter-trend side when mid deviates "
            "from EMA by at least this signed pct, even before a full up/down regime flip. "
            "Example: 0.0002 = 2 bps. Set 0 to disable."
        ),
    )

    # Regime / spread tuning (previously hardcoded magic numbers)
    ema_period: int = Field(default=50, ge=5, le=500, description="EMA lookback (in 1-min bars) for trend regime detection. At 10s ticks this spans ~50 min. Lower values (e.g. 20) react faster to trend changes but may flap in chop. The regime_hold_ticks setting provides anti-flap protection.")
    atr_period: int = Field(default=14, ge=2, le=100, description="ATR lookback for volatility band and spread floor")
    trend_skew_factor: Decimal = Field(default=Decimal("0.8"), description="Inventory skew multiplier in trend regimes")
    neutral_skew_factor: Decimal = Field(default=Decimal("0.5"), description="Inventory skew multiplier in neutral regime")
    spread_step_multiplier: Decimal = Field(default=Decimal("0.4"), description="Per-level spread step as fraction of half-spread")
    vol_penalty_multiplier: Decimal = Field(default=Decimal("0.5"), description="ATR-based volatility penalty on spread floor")
    regime_hold_ticks: int = Field(default=3, ge=1, le=30, description="Regime must be detected for N consecutive ticks before switching")
    funding_rate_refresh_s: int = Field(default=300, ge=30, le=3600, description="Seconds between funding rate queries (perps only)")
    adverse_fill_spread_multiplier: Decimal = Field(
        default=Decimal("1.3"),
        description="Spread multiplier when realized fill edge EWMA is persistently negative",
    )
    adverse_fill_count_threshold: int = Field(default=20, ge=5, le=200)
    adverse_fill_soft_pause_enabled: bool = Field(
        default=False,
        description=(
            "When enabled, force SOFT_PAUSE when realized fill-edge EWMA stays "
            "below configured cost-floor threshold with enough samples."
        ),
    )
    adverse_fill_soft_pause_min_fills: int = Field(
        default=120,
        ge=1,
        le=20_000,
        description="Minimum fill observations required before adverse-fill soft-pause may trigger.",
    )
    adverse_fill_soft_pause_cost_floor_mult: Decimal = Field(
        default=Decimal("1.0"),
        description=(
            "Multiplier applied to fee+slippage cost floor for adverse-fill soft-pause trigger "
            "(1.0 = trigger when fill-edge is below estimated execution cost)."
        ),
    )
    edge_confidence_soft_pause_enabled: bool = Field(
        default=False,
        description=(
            "When enabled, pause quoting if the upper confidence bound of realized fill-edge "
            "remains below the configured cost floor."
        ),
    )
    edge_confidence_soft_pause_min_fills: int = Field(
        default=120,
        ge=1,
        le=20_000,
        description="Minimum fill observations required before edge-confidence soft-pause may trigger.",
    )
    edge_confidence_soft_pause_z_score: Decimal = Field(
        default=Decimal("1.96"),
        description="Z-score used for fill-edge confidence bound (1.96 ~= 95% one-sided interval).",
    )
    edge_confidence_soft_pause_cost_floor_mult: Decimal = Field(
        default=Decimal("1.0"),
        description="Cost-floor multiplier applied when evaluating edge-confidence soft-pause trigger.",
    )
    slippage_soft_pause_enabled: bool = Field(
        default=False,
        description=(
            "When enabled, pause quoting if recent realized slippage p95 exceeds configured threshold."
        ),
    )
    slippage_soft_pause_window_fills: int = Field(
        default=300,
        ge=1,
        le=20_000,
        description="Rolling fill window used for slippage soft-pause p95 evaluation.",
    )
    slippage_soft_pause_min_fills: int = Field(
        default=100,
        ge=1,
        le=20_000,
        description="Minimum fills required in slippage window before soft-pause may trigger.",
    )
    slippage_soft_pause_p95_bps: Decimal = Field(
        default=Decimal("25"),
        description="Soft-pause trigger threshold for rolling p95 slippage in bps.",
    )
    selective_quoting_enabled: bool = Field(
        default=False,
        description="Enable stronger selective market-making filters based on recent realized quote quality.",
    )
    selective_quality_min_fills: int = Field(
        default=40,
        ge=1,
        le=20_000,
        description="Minimum fills required before selective quote-quality filters can activate.",
    )
    selective_quality_reduce_threshold: Decimal = Field(
        default=Decimal("0.45"),
        description="Quote-quality score threshold that reduces participation without fully pausing.",
    )
    selective_quality_block_threshold: Decimal = Field(
        default=Decimal("0.85"),
        description="Quote-quality score threshold that fail-closes quoting via soft pause.",
    )
    selective_quality_edge_tighten_max_bps: Decimal = Field(
        default=Decimal("2.0"),
        description="Maximum extra min-edge tightening applied by selective quote-quality filters.",
    )
    selective_neutral_extra_edge_bps: Decimal = Field(
        default=Decimal("1.0"),
        description="Additional fixed edge tightening in neutral_low_vol when selective mode is active.",
    )
    selective_side_bias_pct: Decimal = Field(
        default=Decimal("0.00025"),
        description="EMA displacement required before selective mode allows one-sided quoting.",
    )
    selective_max_levels_per_side: int = Field(
        default=1,
        ge=1,
        le=10,
        description="Maximum levels per side to keep when selective mode reduces participation.",
    )
    alpha_policy_enabled: bool = Field(
        default=True,
        description="Enable forward-looking alpha policy states on top of selective quote quality.",
    )
    alpha_policy_no_trade_threshold: Decimal = Field(
        default=Decimal("0.35"),
        description="Minimum maker score required to quote in neutral_low_vol.",
    )
    alpha_policy_aggressive_threshold: Decimal = Field(
        default=Decimal("0.78"),
        description="Score threshold required before bounded aggressive entry is allowed.",
    )
    alpha_policy_inventory_relief_threshold: Decimal = Field(
        default=Decimal("0.55"),
        description="Inventory urgency needed before biasing strongly toward inventory relief.",
    )
    alpha_policy_cross_spread_mult: Decimal = Field(
        default=Decimal("1.05"),
        description="Multiplier on market side-spread floor used for bounded aggressive entry pricing.",
    )
    close_position_at_rollover: bool = Field(default=True, description="Force position close at daily rollover (UTC midnight)")

    # Order book imbalance signal (ROAD-3)
    ob_imbalance_depth: int = Field(
        default=5, ge=1, le=20,
        description="Number of order book levels to sum for imbalance calculation",
    )
    ob_imbalance_skew_weight: Decimal = Field(
        default=Decimal("0.3"),
        description="Weight of OB imbalance contribution to inventory skew. 0=disabled, 1.0=full weight.",
    )

    # Kelly-adjusted position sizing (ROAD-4)
    use_kelly_sizing: bool = Field(
        default=False,
        description="Enable Kelly-fractional position sizing based on realized fill edge EWMA",
    )
    kelly_fraction: Decimal = Field(
        default=Decimal("0.25"),
        description="Fractional Kelly multiplier (0.25 = quarter-Kelly, conservative)",
    )
    kelly_min_observations: int = Field(
        default=20, ge=10, le=500,
        description="Minimum fill observations before Kelly sizing activates",
    )
    kelly_max_order_quote: Decimal = Field(
        default=Decimal("200"),
        description="Maximum per-order notional when Kelly sizing is active (USDT)",
    )
    kelly_min_order_quote: Decimal = Field(
        default=Decimal("10"),
        description="Minimum per-order notional when Kelly sizing is active (USDT)",
    )

    # ML regime override (ROAD-10)
    ml_regime_enabled: bool = Field(
        default=False,
        description="Accept regime_override signals from ML regime classifier via hb_bridge",
    )
    ml_regime_override_ttl_s: float = Field(
        default=30.0,
        description="Seconds before an ML regime override expires and EMA/ATR detection resumes",
    )

    # Adverse selection classifier (ROAD-11)
    adverse_classifier_enabled: bool = Field(
        default=False,
        description="Enable hb_bridge adverse fill classifier (spread widening + skip quoting)",
    )
    adverse_classifier_model_path: str = Field(
        default="",
        description="Path to adverse selection model joblib file",
    )
    adverse_threshold_widen: Decimal = Field(
        default=Decimal("0.70"),
        description="p_adverse above this widens spread by (1 + p_adverse * 0.5)",
    )
    adverse_threshold_skip: Decimal = Field(
        default=Decimal("0.85"),
        description="p_adverse above this skips quoting for one tick (max 3 consecutive)",
    )
    min_close_notional_quote: Decimal = Field(default=Decimal("5.0"), description="Minimum notional to trigger EOD close")

    # Desk-style hard risk limits
    min_base_pct: Decimal = Field(default=Decimal("0.15"))
    max_base_pct: Decimal = Field(default=Decimal("0.90"))
    max_order_notional_quote: Decimal = Field(default=Decimal("250"))
    max_total_notional_quote: Decimal = Field(default=Decimal("1000"))
    max_daily_turnover_x_hard: Decimal = Field(default=Decimal("6.0"))
    max_daily_loss_pct_hard: Decimal = Field(default=Decimal("0.03"))
    max_drawdown_pct_hard: Decimal = Field(default=Decimal("0.05"))
    max_leverage: int = Field(default=5, ge=1, le=125, description="Maximum allowed leverage — startup rejects if config.leverage exceeds this")
    margin_ratio_soft_pause_pct: Decimal = Field(default=Decimal("0.20"), description="Margin ratio below this triggers SOFT_PAUSE (perps only)")
    margin_ratio_hard_stop_pct: Decimal = Field(default=Decimal("0.10"), description="Margin ratio below this triggers HARD_STOP (perps only)")
    position_recon_interval_s: int = Field(default=300, ge=30, le=3600, description="Seconds between position reconciliation checks")
    position_drift_soft_pause_pct: Decimal = Field(default=Decimal("0.05"), description="Position drift > this triggers SOFT_PAUSE")
    position_rebalance_min_base_mult: Decimal = Field(
        default=Decimal("1.0"),
        ge=Decimal("0"),
        le=Decimal("100"),
        description=(
            "Multiplier over exchange min-base amount used as a floor for position rebalance "
            "trigger size. Higher values suppress dust-sized taker rebalances."
        ),
    )
    startup_position_sync: bool = Field(default=True, description="Query exchange on first tick and adopt actual position if local state disagrees")
    startup_sync_timeout_s: int = Field(
        default=180, ge=30, le=3600,
        description="Maximum seconds to keep startup_position_sync pending before HARD_STOP.",
    )
    protective_stop_enabled: bool = Field(default=False, description="Place server-side stop-loss on exchange that survives bot offline")
    protective_stop_loss_pct: Decimal = Field(default=Decimal("0.03"), description="Stop-loss distance from avg entry price (0.03 = 3%)")
    protective_stop_refresh_s: int = Field(default=60, ge=10, le=600, description="Seconds between protective stop updates")
    order_ack_timeout_s: int = Field(default=30, ge=5, le=120, description="Seconds before an unacked order is considered stuck")
    paper_executor_min_lifetime_s: int = Field(
        default=120,
        ge=0,
        le=3600,
        description=(
            "In paper mode, minimum age before passive active executors are considered stale for refresh "
            "cancels. Keeps makers resting long enough to fill under simulated latency/queue effects."
        ),
    )
    stuck_executor_escalation_ticks: int = Field(default=5, ge=2, le=20, description="Consecutive ticks with stuck executors before OpsGuard escalation")
    reconnect_cooldown_s: float = Field(default=5.0, ge=0, le=60, description="Seconds to suppress quoting after WS reconnect")
    max_active_executors: int = Field(default=10, ge=1, le=50, description="Maximum concurrent active executors")
    derisk_spread_pct: Decimal = Field(
        default=Decimal("0.0003"),
        description=(
            "Spread used when placing de-risk-only orders (base_pct outside band). "
            "Tight by design so the order fills quickly instead of waiting for a large adverse move. "
            "0.0003 = 3 bps. Set to 0 to use the regime spread unchanged."
        ),
    )
    derisk_force_taker_after_s: float = Field(
        default=180.0,
        ge=0.0,
        le=3600.0,
        description=(
            "Seconds allowed in derisk_only without sufficient inventory reduction "
            "before forcing taker-style entries (market open_order_type). Set 0 to disable."
        ),
    )
    derisk_progress_reset_ratio: Decimal = Field(
        default=Decimal("0.02"),
        ge=Decimal("0"),
        le=Decimal("1"),
        description=(
            "Fractional inventory reduction needed to reset derisk force timer. "
            "Example: 0.02 means 2% shrink of abs(position_base)."
        ),
    )
    derisk_force_taker_min_base_mult: Decimal = Field(
        default=Decimal("2.0"),
        ge=Decimal("0"),
        le=Decimal("100"),
        description=(
            "Minimum absolute position (in multiples of exchange min-base amount) "
            "required before derisk force-taker escalation can activate."
        ),
    )
    derisk_force_taker_expectancy_guard_enabled: bool = Field(
        default=False,
        description=(
            "When enabled, block force-taker derisk escalation when recent taker expectancy "
            "is below threshold, unless large-inventory override applies."
        ),
    )
    derisk_force_taker_expectancy_window_fills: int = Field(
        default=300,
        ge=1,
        le=20_000,
        description="Rolling fill window used to estimate taker expectancy for force-derisk guard.",
    )
    derisk_force_taker_expectancy_min_taker_fills: int = Field(
        default=40,
        ge=1,
        le=20_000,
        description="Minimum taker fills required before force-derisk expectancy guard can block.",
    )
    derisk_force_taker_expectancy_min_quote: Decimal = Field(
        default=Decimal("-0.02"),
        description=(
            "Minimum acceptable mean net quote PnL per taker fill for force-derisk escalation. "
            "Force mode is blocked when observed taker expectancy is lower."
        ),
    )
    derisk_force_taker_expectancy_override_base_mult: Decimal = Field(
        default=Decimal("10"),
        ge=Decimal("0"),
        le=Decimal("1000"),
        description=(
            "Large inventory override for expectancy guard in multiples of force-min-base. "
            "Set 0 to disable override."
        ),
    )
    # Paper engine simulation params (only active when BOT_MODE=paper)
    internal_paper_enabled: bool = Field(
        default=False,
        description=(
            "DEPRECATED and ignored at runtime. Use BOT_MODE env var only. "
            "Kept temporarily for backward-compatible config parsing."
        ),
    )
    paper_engine: PaperEngineConfig = Field(
        default_factory=PaperEngineConfig,
        description="Nested paper-engine simulation configuration.",
    )
    override_spread_pct: Optional[Decimal] = Field(default=None, description="Optional fixed spread override for smoke tests.")
    paper_edge_gate_bypass: bool = Field(
        default=True,
        description=(
            "When True and is_paper=True, skip the edge gate so paper orders fill. "
            "Paper mode validates structural behavior (orders placed, fills cycle, "
            "position tracking) -- not edge profitability. Default True."
        ),
    )
    paper_use_portfolio_equity_for_risk: bool = Field(
        default=True,
        description=(
            "In paper mode, use PaperDesk portfolio equity for risk metrics/base_pct "
            "instead of connector cash balance to avoid false daily-loss hard stops."
        ),
    )
    paper_state_reconcile_enabled: bool = Field(
        default=True,
        description=(
            "When enabled in paper mode, reconcile persisted daily state from PaperDesk "
            "when realized-PnL drift exceeds threshold."
        ),
    )
    paper_state_reconcile_realized_pnl_diff_quote: Decimal = Field(
        default=Decimal("5"),
        description="Reconciliation threshold in quote units for daily realized PnL drift.",
    )
    paper_daily_baseline_auto_reset_on_startup: bool = Field(
        default=True,
        description=(
            "In paper mode only, reset daily open/peak baseline on startup when "
            "inherited daily loss is abnormally large and likely stale carryover."
        ),
    )
    paper_daily_baseline_reset_loss_pct_threshold: Decimal = Field(
        default=Decimal("0.25"),
        description=(
            "Startup baseline auto-reset threshold in loss pct of daily_open_equity "
            "(0.25 = 25%% drawdown trigger)."
        ),
    )
    paper_daily_baseline_reset_startup_window_s: int = Field(
        default=300,
        ge=30,
        le=3600,
        description="Only allow startup baseline auto-reset within this many seconds after controller init.",
    )
    regime_specs_override: Optional[Dict[str, Dict[str, Any]]] = Field(
        default=None,
        description=(
            "YAML-driven per-regime overrides merged onto PHASE0_SPECS. "
            "Example: {neutral_low_vol: {spread_min: '0.003', levels_max: 5}}. "
            "Keys not provided fall through to the hardcoded default."
        ),
    )

    @property
    def bot_mode(self) -> str:
        """Canonical mode: 'paper' or 'live'. Single source of truth from BOT_MODE env var."""
        return _runtime_bot_mode()

    @property
    def is_paper(self) -> bool:
        return self.bot_mode == "paper"

    @property
    def paper_engine_config(self):
        """Alias for paper-engine settings."""
        return self.paper_engine

    @property
    def resolved_connector_type(self) -> str:
        """Return 'spot' or 'perp'. Auto-infer from connector_name if connector_type='auto'."""
        ct = str(self.connector_type).strip().lower()
        if ct in ("perp", "perpetual", "futures"):
            return "perp"
        if ct == "spot":
            return "spot"
        return "perp" if "_perpetual" in str(self.connector_name) else "spot"

    @field_validator("variant", mode="before")
    @classmethod
    def _validate_variant(cls, v: str) -> str:
        low = (v or "a").lower()
        if low not in {"a", "b", "c", "d"}:
            raise ValueError("variant must be one of a/b/c/d")
        return low

    @field_validator("fee_mode", mode="before")
    @classmethod
    def _validate_fee_mode(cls, v: str) -> str:
        low = (v or "auto").lower().strip()
        if low not in {"auto", "project", "manual"}:
            raise ValueError("fee_mode must be one of auto/project/manual")
        return low

    @field_validator("candles_connector", mode="before")
    @classmethod
    def _set_candles_connector(cls, v: Optional[str], info: ValidationInfo) -> str:
        if v in (None, ""):
            return str(info.data.get("connector_name", ""))
        return str(v)

    @field_validator("candles_trading_pair", mode="before")
    @classmethod
    def _set_candles_pair(cls, v: Optional[str], info: ValidationInfo) -> str:
        if v in (None, ""):
            return str(info.data.get("trading_pair", ""))
        return str(v)


class EppV24Controller(MarketMakingControllerBase):
    """EPP v2.4 — VIP0 Survival Yield Engine.

    Historical note: "EPP" is a legacy name retained for compatibility with
    existing controller IDs, configs, and artifacts. The implementation is a
    shared market-making base used by bot1 and bot-specific wrappers.

    A regime-aware market-making controller that dynamically adjusts spread,
    inventory skew, and order sizing based on detected market conditions.

    Key mechanisms:
    - **Regime detection** (neutral / up / down / high_vol_shock) via EMA trend
      and ATR volatility band.
    - **Edge gating** — pauses quoting when estimated net edge (after fees,
      slippage, adverse drift) drops below a configurable threshold.
    - **Spread floor** — computes a minimum spread that is mathematically
      capable of clearing the edge gate given the current cost structure.
    - **Risk policy** — enforces hard limits on daily loss, drawdown, and
      turnover.  Breaching a hard limit triggers ``HARD_STOP``.
    - **OpsGuard state machine** — RUNNING / SOFT_PAUSE / HARD_STOP lifecycle
      with automatic transition and external intent support.

    The controller's tick output is stored in ``self.processed_data``
    (typed as ``ProcessedState``) and consumed by the CSV logger, Prometheus
    exporter, and Redis bus publisher.
    """

    PHASE0_SPECS: Dict[str, RegimeSpec] = {
        "neutral_low_vol": RegimeSpec(
            spread_min=Decimal("0.0025"),
            spread_max=Decimal("0.0045"),
            levels_min=2,
            levels_max=4,
            refresh_s=90,
            target_base_pct=Decimal("0.50"),
            quote_size_pct_min=Decimal("0.0008"),
            quote_size_pct_max=Decimal("0.0012"),
            one_sided="off",
            fill_factor=Decimal("0.45"),
        ),
        "up": RegimeSpec(
            spread_min=Decimal("0.0030"),
            spread_max=Decimal("0.0055"),
            levels_min=2,
            levels_max=3,
            refresh_s=70,
            target_base_pct=Decimal("0.60"),
            quote_size_pct_min=Decimal("0.0006"),
            quote_size_pct_max=Decimal("0.0010"),
            one_sided="buy_only",
            fill_factor=Decimal("0.35"),
        ),
        "down": RegimeSpec(
            spread_min=Decimal("0.0035"),
            spread_max=Decimal("0.0080"),
            levels_min=2,
            levels_max=3,
            refresh_s=60,
            target_base_pct=Decimal("0.35"),
            quote_size_pct_min=Decimal("0.0005"),
            quote_size_pct_max=Decimal("0.0008"),
            one_sided="sell_only",
            fill_factor=Decimal("0.35"),
        ),
        "neutral_high_vol": RegimeSpec(
            spread_min=Decimal("0.0040"),
            spread_max=Decimal("0.0080"),
            levels_min=1,
            levels_max=3,
            refresh_s=100,
            target_base_pct=Decimal("0.0"),
            quote_size_pct_min=Decimal("0.0005"),
            quote_size_pct_max=Decimal("0.0008"),
            one_sided="off",
            fill_factor=Decimal("0.35"),
        ),
        "high_vol_shock": RegimeSpec(
            spread_min=Decimal("0.0080"),
            spread_max=Decimal("0.0200"),
            levels_min=1,
            levels_max=2,
            refresh_s=120,
            target_base_pct=Decimal("0.40"),
            quote_size_pct_min=Decimal("0.0003"),
            quote_size_pct_max=Decimal("0.0005"),
            one_sided="off",
            fill_factor=Decimal("0.25"),
        ),
    }

    @classmethod
    def _resolve_specs(cls, overrides: Optional[Dict[str, Dict[str, Any]]]) -> Dict[str, RegimeSpec]:
        """Merge optional YAML overrides onto PHASE0_SPECS defaults."""
        if not overrides:
            return dict(cls.PHASE0_SPECS)
        import dataclasses
        merged = dict(cls.PHASE0_SPECS)
        for regime_name, patch in overrides.items():
            if regime_name not in merged:
                logger.warning("regime_specs_override: unknown regime '%s' — skipped", regime_name)
                continue
            base = merged[regime_name]
            kwargs = {}
            for f in dataclasses.fields(base):
                default_val = getattr(base, f.name)
                if f.name in patch:
                    raw = patch[f.name]
                    if isinstance(default_val, Decimal):
                        kwargs[f.name] = Decimal(str(raw))
                    elif isinstance(default_val, int):
                        kwargs[f.name] = int(raw)
                    else:
                        kwargs[f.name] = raw
                else:
                    kwargs[f.name] = default_val
            merged[regime_name] = RegimeSpec(**kwargs)
            logger.info("regime_specs_override: applied to '%s'", regime_name)
        return merged

    def __init__(self, config: EppV24Config, *args, **kwargs):
        super().__init__(config, *args, **kwargs)
        self.config = config
        self.processed_data: ProcessedState = {}
        self._is_perp = config.resolved_connector_type == "perp"
        self._resolved_specs = self._resolve_specs(config.regime_specs_override)
        self._bot_mode = config.bot_mode
        if self._bot_mode == "paper" and not config.connector_name.endswith("_paper_trade"):
            # In Paper Engine v2 mode we often use the "real" connector name for market data,
            # while execution is intercepted by the paper desk bridge. Keep this as an info
            # breadcrumb (not a scary warning) so ops can sanity-check routing.
            logger.info(
                "BOT_MODE=paper with connector_name=%s (no '_paper_trade' suffix). "
                "Ensure the PaperDesk bridge is installed and no live trading keys are at risk.",
                config.connector_name,
            )
        if config.internal_paper_enabled:
            logger.warning(
                "internal_paper_enabled is deprecated and ignored at runtime. "
                "Set BOT_MODE=paper|live via environment."
            )
        if int(config.leverage) > config.max_leverage:
            raise ValueError(
                f"leverage={config.leverage} exceeds max_leverage={config.max_leverage}. "
                f"Increase max_leverage in config if intentional."
            )
        self._regime_detector = RegimeDetector(
            specs=self._resolved_specs,
            high_vol_band_pct=config.high_vol_band_pct,
            shock_drift_30s_pct=config.shock_drift_30s_pct,
            shock_drift_atr_multiplier=config.shock_drift_atr_multiplier,
            trend_eps_pct=config.trend_eps_pct,
            regime_hold_ticks=config.regime_hold_ticks,
        )
        self._spread_engine = SpreadEngine(
            turnover_cap_x=config.turnover_cap_x,
            spread_step_multiplier=config.spread_step_multiplier,
            vol_penalty_multiplier=config.vol_penalty_multiplier,
            high_vol_band_pct=config.high_vol_band_pct,
            trend_skew_factor=config.trend_skew_factor,
            neutral_skew_factor=config.neutral_skew_factor,
            inventory_skew_cap_pct=config.inventory_skew_cap_pct,
            inventory_skew_vol_multiplier=config.inventory_skew_vol_multiplier,
            slippage_est_pct=config.slippage_est_pct,
            min_net_edge_bps=config.min_net_edge_bps,
            edge_resume_bps=config.edge_resume_bps,
            drift_spike_threshold_bps=config.drift_spike_threshold_bps,
            drift_spike_mult_max=config.drift_spike_mult_max,
            adverse_fill_spread_multiplier=config.adverse_fill_spread_multiplier,
            adverse_fill_count_threshold=config.adverse_fill_count_threshold,
            turnover_penalty_step=config.turnover_penalty_step,
            adaptive_vol_spread_widen_max=config.adaptive_vol_spread_widen_max,
        )
        self._risk_evaluator = RiskEvaluator(
            min_base_pct=config.min_base_pct,
            max_base_pct=config.max_base_pct,
            max_total_notional_quote=config.max_total_notional_quote,
            max_daily_turnover_x_hard=config.max_daily_turnover_x_hard,
            max_daily_loss_pct_hard=config.max_daily_loss_pct_hard,
            max_drawdown_pct_hard=config.max_drawdown_pct_hard,
            edge_state_hold_s=config.edge_state_hold_s,
            margin_ratio_hard_stop_pct=config.margin_ratio_hard_stop_pct,
            margin_ratio_soft_pause_pct=config.margin_ratio_soft_pause_pct,
            position_drift_soft_pause_pct=config.position_drift_soft_pause_pct,
        )
        self._runtime_adapter = ConnectorRuntimeAdapter(self)
        self._runtime_compat = resolve_runtime_compatibility(
            config,
            runtime_impl=type(self).__name__.replace("Controller", "") or "shared_mm_v24",
        )
        self._family_adapter = self._make_runtime_family_adapter()
        self._runtime_levels = RuntimeLevelState(
            buy_spreads=[to_decimal(x) for x in config.buy_spreads],
            sell_spreads=[to_decimal(x) for x in config.sell_spreads],
            buy_amounts_pct=[to_decimal(x) for x in config.buy_amounts_pct],
            sell_amounts_pct=[to_decimal(x) for x in config.sell_amounts_pct],
            total_amount_quote=to_decimal(config.total_amount_quote),
            executor_refresh_time=int(config.executor_refresh_time),
            cooldown_time=int(config.cooldown_time),
        )
        self._price_buffer = MidPriceBuffer(sample_interval_sec=config.sample_interval_s)
        self._history_provider = None
        self._history_seed_attempted = False
        self._history_seed_status = "disabled"
        self._history_seed_reason = ""
        self._history_seed_source = ""
        self._history_seed_bars = 0
        self._history_seed_latency_ms = 0.0
        self._ops_guard = OpsGuard()
        self._artifact_namespace = self._runtime_compat.artifact_namespace
        self._csv = CsvSplitLogger(
            config.log_dir,
            config.instance_name,
            config.variant,
            namespace=self._artifact_namespace,
        )
        self._tick_emitter = TickEmitter(self._csv)
        self._last_floor_recalc_ts: float = 0
        self._spread_floor_pct: Decimal = Decimal("0.0025")
        self._traded_notional_today: Decimal = Decimal("0")
        self._fills_count_today: int = 0
        self._daily_equity_open: Optional[Decimal] = None
        self._daily_key: Optional[str] = None
        # One equity sample per logged minute (used for daily max drawdown).
        self._equity_samples_today: List[Decimal] = []
        self._equity_sample_ts_today: List[str] = []
        self._cancel_events_ts: List[float] = []
        self._cancel_fail_streak: int = 0
        self._consecutive_stuck_ticks: int = 0
        self._soft_pause_edge: bool = False
        self._external_soft_pause: bool = False
        self._external_pause_reason: str = ""
        self._external_target_base_pct_override: Optional[Decimal] = None
        self._external_daily_pnl_target_pct_override: Optional[Decimal] = None
        self._last_external_model_version: str = ""
        self._last_external_intent_reason: str = ""
        self._last_external_intent_ts: float = 0.0
        self._external_target_base_pct_override_ts: float = 0.0
        self._external_daily_pnl_target_pct_override_ts: float = 0.0
        self._external_target_base_pct_override_expires_ts: float = 0.0
        self._external_daily_pnl_target_pct_override_expires_ts: float = 0.0
        self._cancel_pause_until: float = 0
        self._fee_source: str = "manual"
        self._fee_resolved: bool = False
        self._fee_resolution_error: str = ""
        self._maker_fee_pct: Decimal = to_decimal(self.config.spot_fee_pct)
        self._taker_fee_pct: Decimal = to_decimal(self.config.spot_fee_pct)
        self._last_fee_resolve_ts: float = 0.0
        self._edge_gate_blocked: bool = False
        self._net_edge_ewma: Optional[Decimal] = None
        self._net_edge_gate: Decimal = _ZERO
        self._daily_equity_peak: Optional[Decimal] = None
        self._fees_paid_today_quote: Decimal = Decimal("0")
        self._fee_rate_mismatch_warned_today: bool = False
        self._paper_fill_count: int = 0
        self._paper_reject_count: int = 0
        self._paper_avg_queue_delay_ms: Decimal = Decimal("0")
        self._tick_duration_ms: float = 0.0
        self._indicator_duration_ms: float = 0.0
        self._connector_io_duration_ms: float = 0.0
        self._active_regime: str = "neutral_low_vol"
        self._pending_regime: str = "neutral_low_vol"
        self._regime_source: str = "price_buffer"
        self._regime_hold_counter: int = 0
        self._regime_ema_value: Optional[Decimal] = None
        self._quote_side_mode: str = "off"
        self._quote_side_reason: str = "regime"
        self._selective_quote_score: Decimal = _ZERO
        self._selective_quote_state: str = "inactive"
        self._selective_quote_reason: str = "disabled"
        self._selective_quote_adverse_ratio: Decimal = _ZERO
        self._selective_quote_slippage_p95_bps: Decimal = _ZERO
        self._alpha_policy_state: str = "maker_two_sided"
        self._alpha_policy_reason: str = "startup"
        self._alpha_maker_score: Decimal = _ZERO
        self._alpha_aggressive_score: Decimal = _ZERO
        self._alpha_cross_allowed: bool = False
        self._alpha_no_trade_last_paper_cancel_ts: float = 0.0
        self._inventory_urgency_score: Decimal = _ZERO
        self._last_spread_state: Optional[SpreadEdgeState] = None
        self._pending_stale_cancel_actions: List[Any] = []
        self._recently_issued_levels: Dict[str, float] = {}
        self._fill_edge_ewma: Optional[Decimal] = None
        self._fill_edge_variance: Optional[Decimal] = None
        self._fill_count_for_kelly: int = 0
        self._adverse_fill_count: int = 0
        self._pending_eod_close: bool = False
        self._ob_imbalance: Decimal = _ZERO
        self._external_regime_override: Optional[str] = None
        self._external_regime_override_expiry: float = 0.0
        self._adverse_skip_count: int = 0
        self._derisk_runtime_recovery_count: int = 0
        self._derisk_cycle_started_ts: float = 0.0
        self._derisk_cycle_start_abs_base: Decimal = _ZERO
        self._derisk_force_taker: bool = False
        self._derisk_force_taker_expectancy_guard_blocked: bool = False
        self._derisk_force_taker_expectancy_guard_reason: str = "inactive"
        self._derisk_force_taker_expectancy_mean_quote: Decimal = _ZERO
        self._derisk_force_taker_expectancy_taker_fills: int = 0
        self._derisk_trace_enabled: bool = os.getenv("HB_DERISK_TRACE_ENABLED", "true").lower() in {"1", "true", "yes"}
        self._derisk_trace_cooldown_s: float = max(
            1.0,
            float(os.getenv("HB_DERISK_TRACE_COOLDOWN_S", "20")),
        )
        self._derisk_trace_last_ts: float = 0.0
        self._last_fill_ts: float = 0.0
        self._market_spread_bps_ewma: Decimal = _ZERO
        self._band_pct_ewma: Decimal = _ZERO
        self._adaptive_effective_min_edge_pct: Decimal = Decimal(self.config.min_net_edge_bps) / _10K
        self._adaptive_fill_age_s: Decimal = _ZERO
        self._adaptive_market_floor_pct: Decimal = _ZERO
        self._adaptive_vol_ratio: Decimal = _ZERO
        self._pnl_governor_active: bool = False
        self._pnl_governor_day_progress: Decimal = _ZERO
        self._pnl_governor_target_pnl_pct: Decimal = _ZERO
        self._pnl_governor_target_pnl_quote: Decimal = _ZERO
        self._pnl_governor_expected_pnl_quote: Decimal = _ZERO
        self._pnl_governor_actual_pnl_quote: Decimal = _ZERO
        self._pnl_governor_deficit_ratio: Decimal = _ZERO
        self._pnl_governor_edge_relax_bps: Decimal = _ZERO
        self._pnl_governor_size_mult: Decimal = _ONE
        self._pnl_governor_size_boost_active: bool = False
        self._pnl_governor_target_mode: str = "disabled"
        self._pnl_governor_target_source: str = "none"
        self._pnl_governor_target_equity_open_quote: Decimal = _ZERO
        self._pnl_governor_target_effective_pct: Decimal = _ZERO
        self._pnl_governor_activation_reason: str = "disabled"
        self._pnl_governor_size_boost_reason: str = "governor_disabled"
        self._pnl_governor_activation_reason_counts: Dict[str, int] = {}
        self._pnl_governor_size_boost_reason_counts: Dict[str, int] = {}
        self._runtime_size_mult_applied: Decimal = _ONE
        self._spread_competitiveness_cap_active: bool = False
        self._spread_competitiveness_cap_side_pct: Decimal = _ZERO
        self._auto_calibration_minute_history: Deque[Dict[str, Any]] = deque(maxlen=20_000)
        self._auto_calibration_fill_history: Deque[Dict[str, Any]] = deque(maxlen=20_000)
        self._auto_calibration_change_events: Deque[Tuple[float, Decimal]] = deque(maxlen=1_000)
        self._auto_calibration_last_eval_ts: float = 0.0
        self._auto_calibration_relax_signal_streak: int = 0
        self._auto_calibration_negative_window_streak: int = 0
        self._auto_calibration_applied_changes: List[Dict[str, Any]] = []
        self._auto_calibration_last_decision: str = "idle"
        self._auto_calibration_last_report_ts: float = 0.0
        self._funding_rate: Decimal = _ZERO
        self._funding_cost_today_quote: Decimal = _ZERO
        self._last_funding_rate_ts: float = 0.0
        self._margin_ratio: Decimal = _ONE
        self._cancel_budget_breach_count: int = 0
        self._avg_entry_price: Decimal = _ZERO
        self._position_base: Decimal = _ZERO
        self._position_gross_base: Decimal = _ZERO
        self._position_long_base: Decimal = _ZERO
        self._position_short_base: Decimal = _ZERO
        self._avg_entry_price_long: Decimal = _ZERO
        self._avg_entry_price_short: Decimal = _ZERO
        self._realized_pnl_today: Decimal = _ZERO
        self._last_position_recon_ts: float = 0.0
        self._position_recon_fail_count: int = 0
        self._position_drift_pct: Decimal = _ZERO
        self._position_drift_correction_count: int = 0
        self._first_drift_correction_ts: float = 0.0
        self._reconnect_cooldown_until: float = 0.0
        self._last_book_bid: Decimal = _ZERO
        self._last_book_ask: Decimal = _ZERO
        self._last_book_bid_size: Decimal = _ZERO
        self._last_book_ask_size: Decimal = _ZERO
        self._book_stale_since_ts: float = 0.0
        self._book_reconnect_grace_until_ts: float = 0.0
        self._ws_reconnect_count: int = 0
        self._last_connector_ready: bool = True
        self._last_daily_state_save_ts: float = 0.0
        self._paper_state_reconcile_last_ts: float = 0.0
        self._paper_state_reconcile_log_cooldown_s: float = float(
            os.getenv("HB_PAPER_STATE_RECONCILE_LOG_COOLDOWN_S", "60")
        )
        self._controller_start_ts: float = _time_mod.time()
        self._paper_daily_baseline_reset_done: bool = False
        redis_url = os.environ.get("REDIS_URL") or None
        if redis_url is None:
            rh = os.environ.get("REDIS_HOST", "")
            rp = os.environ.get("REDIS_PORT", "6379")
            if rh:
                redis_url = f"redis://{rh}:{rp}/0"
        self._state_store = DailyStateStore(
            file_path=self._daily_state_path(),
            redis_key=f"{self._runtime_compat.daily_state_prefix}:daily_state:{config.instance_name}:{config.variant}",
            redis_url=redis_url,
        )
        if _config_is_paper(self.config) and _paper_reset_state_on_startup_enabled(self.config):
            logger.warning(
                "Clearing controller daily state on startup for %s:%s",
                config.instance_name,
                config.variant,
            )
            self._state_store.clear()
        self._telemetry_redis: Optional[Any] = None
        self._telemetry_redis_init_done: bool = False
        self._last_portfolio_risk_check_ts: float = 0.0
        self._portfolio_risk_hard_stop_latched: bool = False
        self._startup_position_sync_done: bool = False
        self._startup_sync_retries: int = 0
        self._startup_sync_first_ts: float = 0.0
        self._startup_orphan_check_done: bool = False
        self._seen_fill_order_ids: set[str] = set()
        self._seen_fill_order_ids_fifo: Deque[str] = deque()
        self._seen_fill_order_ids_cap: int = 50_000
        self._seen_fill_event_keys: set[str] = set()
        self._seen_fill_event_keys_fifo: Deque[str] = deque()
        self._seen_fill_event_keys_cap: int = 120_000
        self._protective_stop = None
        if self.config.protective_stop_enabled and not self.config.no_trade:
            from controllers.protective_stop import ProtectiveStopManager
            self._protective_stop = ProtectiveStopManager(
                exchange_id=self.config.connector_name,
                trading_pair=self.config.trading_pair,
                stop_loss_pct=self.config.protective_stop_loss_pct,
                refresh_interval_s=self.config.protective_stop_refresh_s,
            )
            if not self._protective_stop.initialize():
                logger.warning("Protective stop manager failed to initialize — continuing without")
                self._protective_stop = None
        self._load_daily_state()
        self._hydrate_seen_fill_order_ids_from_csv()
        cfg_is_paper = _config_is_paper(self.config)

        logger.info(
            "═══ Runtime v2.4 STARTUP ═══  mode=%s  connector=%s  type=%s  pair=%s  "
            "instance=%s  variant=%s  equity=%s  leverage=%d  "
            "paper_equity=%s  artifact_ns=%s  state_path=%s",
            self._bot_mode.upper(),
            self.config.connector_name,
            self.config.resolved_connector_type,
            self.config.trading_pair,
            self.config.instance_name,
            self.config.variant,
            self.config.paper_engine.paper_equity_quote if cfg_is_paper else "REAL",
            int(self.config.leverage),
            self.config.paper_engine.paper_equity_quote if cfg_is_paper else "N/A",
            self._artifact_namespace,
            self._daily_state_path(),
        )
        if self._bot_mode == "live":
            logger.warning(
                "══════════════════════════════════════════════════════════════\n"
                "  *** LIVE MODE — REAL MONEY AT RISK ***\n"
                "  connector=%s  pair=%s  leverage=%d\n"
                "══════════════════════════════════════════════════════════════",
                self.config.connector_name, self.config.trading_pair, int(self.config.leverage),
            )

    async def update_processed_data(self):
        """Main tick coordinator — delegates to sub-methods for testability."""
        _t0 = _time_mod.perf_counter()
        now = float(self.market_data_provider.time())

        self._preflight(now)
        if self.config.require_fee_resolution and self._fee_resolution_error:
            self._ops_guard.force_hard_stop("fee_unresolved")
            return

        _t_conn_start = _time_mod.perf_counter()
        mid = self._get_mid_price()
        if mid <= 0:
            return
        # In Paper Engine v2, sync controller shadow accounting from PaperDesk
        # so Grafana-facing minute snapshots remain canonical.
        self._sync_from_paper_desk_v2(mid=mid)
        self._maybe_seed_price_buffer(now)
        self._price_buffer.add_sample(now, mid)
        self._maybe_roll_day(now)
        if self._pending_eod_close and abs(self._position_base) < self._min_base_amount(mid):
            self._pending_eod_close = False

        equity_quote, base_pct_gross, base_pct_net = self._compute_equity_and_base_pcts(mid)
        self._sync_from_paper_desk_v2(mid=mid, equity_quote=equity_quote)
        self._track_daily_equity(equity_quote)

        _t_ind_start = _time_mod.perf_counter()
        regime_name, regime_spec, target_base_pct, target_net_base_pct, regime_band_pct = self._resolve_regime_and_targets(mid)
        spread_state = self._compute_spread_and_edge(
            now_ts=now, regime_name=regime_name, regime_spec=regime_spec,
            target_base_pct=target_net_base_pct, base_pct=base_pct_net,
            equity_quote=equity_quote,
            band_pct=regime_band_pct,
        )
        self._update_edge_gate_ewma(now, spread_state)
        self._indicator_duration_ms = (_time_mod.perf_counter() - _t_ind_start) * 1000.0

        market = self._evaluate_market_conditions(now_ts=now, band_pct=spread_state.band_pct)
        self._update_adaptive_history(market_spread_pct=market.market_spread_pct)
        self._compute_alpha_policy(
            regime_name=regime_name,
            spread_state=spread_state,
            market=market,
            target_net_base_pct=target_net_base_pct,
            base_pct_net=base_pct_net,
        )
        runtime_data_context = RuntimeDataContext(
            now_ts=now,
            mid=mid,
            regime_name=regime_name,
            regime_spec=regime_spec,
            spread_state=spread_state,
            market=market,
            equity_quote=equity_quote,
            target_base_pct=target_base_pct,
            target_net_base_pct=target_net_base_pct,
            base_pct_gross=base_pct_gross,
            base_pct_net=base_pct_net,
        )
        runtime_execution_plan = self.build_runtime_execution_plan(runtime_data_context)
        risk_reasons, risk_hard_stop, daily_loss_pct, drawdown_pct = self._evaluate_all_risk(
            spread_state, base_pct_gross, equity_quote, runtime_execution_plan.projected_total_quote, market,
        )
        self._connector_io_duration_ms = (_time_mod.perf_counter() - _t_conn_start) * 1000.0
        state = self._resolve_guard_state(now, market, risk_reasons, risk_hard_stop)
        runtime_risk_decision = RuntimeRiskDecision(
            risk_reasons=list(risk_reasons),
            risk_hard_stop=risk_hard_stop,
            daily_loss_pct=daily_loss_pct,
            drawdown_pct=drawdown_pct,
            guard_state=state,
        )

        projected_total_quote = runtime_execution_plan.projected_total_quote
        self._apply_runtime_execution_plan(runtime_data_context, runtime_execution_plan)
        self._emit_tick_output(
            _t0, now, mid, regime_name, target_base_pct, target_net_base_pct,
            base_pct_gross, base_pct_net, equity_quote, spread_state, market,
            risk_hard_stop, risk_reasons, daily_loss_pct, drawdown_pct,
            projected_total_quote, state,
            runtime_data_context=runtime_data_context,
            runtime_execution_plan=runtime_execution_plan,
            runtime_risk_decision=runtime_risk_decision,
        )

    # ── Tick sub-steps ─────────────────────────────────────────────────

    def _preflight(self, now: float) -> None:
        """Startup sync, fee resolution, funding rate, reconciliation, protective stop."""
        self._expire_external_intent_overrides(now)
        self._runtime_adapter.refresh_connector_cache()
        if not self._startup_position_sync_done:
            self._run_startup_position_sync()
        self._ensure_fee_config(now)
        self._refresh_funding_rate(now)
        self._check_portfolio_risk_guard(now)
        self._check_position_reconciliation(now)
        if self._protective_stop is not None:
            self._protective_stop.update(self._position_base, self._avg_entry_price)

    def _history_provider_enabled(self) -> bool:
        return str(os.getenv("HB_HISTORY_PROVIDER_ENABLED", "false")).strip().lower() in {"1", "true", "yes", "on"}

    def _history_seed_enabled(self) -> bool:
        return str(os.getenv("HB_HISTORY_SEED_ENABLED", "false")).strip().lower() in {"1", "true", "yes", "on"}

    def _get_history_provider(self):
        if self._history_provider is None and (self._history_provider_enabled() or self._history_seed_enabled()):
            self._history_provider = MarketHistoryProviderImpl()
        return self._history_provider

    def _required_seed_bars(self) -> int:
        bot_periods = [
            int(getattr(self.config, "ema_period", 0) or 0),
            int(getattr(self.config, "atr_period", 0) or 0) + 1,
            int(getattr(self.config, "bot7_bb_period", 0) or 0),
            int(getattr(self.config, "bot7_rsi_period", 0) or 0),
            int(getattr(self.config, "bot7_adx_period", 0) or 0) * 2,
        ]
        required = max([period for period in bot_periods if period > 0] or [30])
        return max(5, required + 5)

    def _history_seed_policy(self):
        return runtime_seed_policy(default_min_bars=self._required_seed_bars())

    def _maybe_seed_price_buffer(self, now: float) -> None:
        if self._history_seed_attempted or not self._history_seed_enabled():
            return
        self._history_seed_attempted = True
        provider = self._get_history_provider()
        if provider is None:
            self._history_seed_status = "disabled"
            self._history_seed_reason = "provider_unavailable"
            return
        connector_name = _canonical_connector_name(str(getattr(self.config, "connector_name", "") or "").strip())
        if not connector_name:
            self._history_seed_status = "empty"
            self._history_seed_reason = "connector_name_missing"
            return
        trading_pair = str(getattr(self.config, "trading_pair", "") or "").strip()
        policy = self._history_seed_policy()
        source_order = list(policy.preferred_sources or ["quote_mid"])
        if not bool(policy.allow_fallback):
            source_order = source_order[:1]
        started = _time_mod.perf_counter()
        try:
            status = None
            for source in source_order:
                self._price_buffer.seed_bars([], reset=True)
                attempt_status = provider.seed_midprice_buffer(
                    self._price_buffer,
                    MarketBarKey(
                        connector_name=connector_name,
                        trading_pair=trading_pair,
                        bar_source=source,
                    ),
                    bars_needed=int(policy.min_bars_before_trading),
                    now_ms=int(now * 1000.0),
                )
                status = attempt_status
                if status_meets_policy(attempt_status, policy):
                    break
            if status is None:
                self._history_seed_status = "empty"
                self._history_seed_reason = "no_history_sources_attempted"
                return
            if not status_meets_policy(status, policy):
                self._price_buffer.seed_bars([], reset=True)
            self._history_seed_latency_ms = (_time_mod.perf_counter() - started) * 1000.0
            self._history_seed_status = str(status.status)
            self._history_seed_reason = str(status.degraded_reason or "")
            self._history_seed_source = str(status.source_used or "")
            self._history_seed_bars = int(status.bars_returned or 0)
            logger.info(
                "History seed result status=%s bars=%s source=%s latency_ms=%.1f reason=%s pair=%s",
                self._history_seed_status,
                self._history_seed_bars,
                self._history_seed_source or "none",
                self._history_seed_latency_ms,
                self._history_seed_reason or "none",
                self.config.trading_pair,
            )
        except Exception as exc:
            self._history_seed_latency_ms = (_time_mod.perf_counter() - started) * 1000.0
            self._history_seed_status = "degraded"
            self._history_seed_reason = str(exc)
            logger.warning(
                "History seed failed for %s; continuing with live warmup.",
                self.config.trading_pair,
                exc_info=True,
            )

    def _expire_external_intent_overrides(self, now_ts: float) -> None:
        """Expire stale external execution-intent overrides to prevent sticky state."""
        ttl_s = int(max(0, int(self.config.execution_intent_override_ttl_s)))
        ttl = float(ttl_s)

        base_override = getattr(self, "_external_target_base_pct_override", None)
        base_override_ts = float(getattr(self, "_external_target_base_pct_override_ts", 0.0) or 0.0)
        base_override_expires_ts = float(
            getattr(self, "_external_target_base_pct_override_expires_ts", 0.0) or 0.0
        )
        base_expired = False
        if base_override is not None:
            if base_override_expires_ts > 0.0:
                base_expired = now_ts >= base_override_expires_ts
            elif ttl_s > 0:
                base_expired = base_override_ts <= 0.0 or (now_ts - base_override_ts) > ttl
        if base_override is not None and base_expired:
            self._external_target_base_pct_override = None
            self._external_target_base_pct_override_ts = 0.0
            self._external_target_base_pct_override_expires_ts = 0.0
            logger.info("Expired stale external target_base_pct override (ttl=%ss)", ttl_s)

        daily_target_override = getattr(self, "_external_daily_pnl_target_pct_override", None)
        daily_target_override_ts = float(
            getattr(self, "_external_daily_pnl_target_pct_override_ts", 0.0) or 0.0
        )
        daily_target_override_expires_ts = float(
            getattr(self, "_external_daily_pnl_target_pct_override_expires_ts", 0.0) or 0.0
        )
        daily_expired = False
        if daily_target_override is not None:
            if daily_target_override_expires_ts > 0.0:
                daily_expired = now_ts >= daily_target_override_expires_ts
            elif ttl_s > 0:
                daily_expired = daily_target_override_ts <= 0.0 or (now_ts - daily_target_override_ts) > ttl
        if daily_target_override is not None and daily_expired:
            self._external_daily_pnl_target_pct_override = None
            self._external_daily_pnl_target_pct_override_ts = 0.0
            self._external_daily_pnl_target_pct_override_expires_ts = 0.0
            logger.info("Expired stale external daily_pnl_target_pct override (ttl=%ss)", ttl_s)

    @staticmethod
    def _intent_expires_ts(intent: Dict[str, object], now_ts: float) -> float:
        expires_at_ms = intent.get("expires_at_ms")
        try:
            if expires_at_ms is None:
                return 0.0
            expires_ts = float(expires_at_ms) / 1000.0
            if expires_ts <= now_ts:
                return 0.0
            return expires_ts
        except Exception:
            return 0.0

    def _track_daily_equity(self, equity_quote: Decimal) -> None:
        """Initialize and update daily equity open/peak watermarks."""
        if self._daily_equity_open is None and equity_quote > 0:
            self._daily_equity_open = equity_quote
        if self._daily_equity_peak is None:
            self._daily_equity_peak = equity_quote
        if equity_quote > (self._daily_equity_peak or _ZERO):
            self._daily_equity_peak = equity_quote

    def _resolve_regime_and_targets(self, mid: Decimal) -> Tuple[str, RegimeSpec, Decimal, Decimal, Decimal]:
        """Detect regime and resolve target base pct (spot vs perp).

        Returns ``(regime_name, regime_spec, target_base_pct, target_net_base_pct, band_pct)``
        where ``band_pct`` is the volatility measure actually used for regime classification,
        ensuring spread/edge and high-vol checks use the same ATR source.
        """
        regime_name, regime_spec, band_pct = self._detect_regime(mid)
        target_base_pct = regime_spec.target_base_pct
        if self._external_target_base_pct_override is not None:
            target_base_pct = _clip(self._external_target_base_pct_override, _ZERO, _ONE)
        if self._is_perp:
            target_net_base_pct = to_decimal(self.config.perp_target_net_base_pct) if self.config.perp_target_net_base_pct is not None else _ZERO
        else:
            target_net_base_pct = target_base_pct
        return regime_name, regime_spec, target_base_pct, target_net_base_pct, band_pct

    def _update_edge_gate_ewma(self, now: float, spread_state: SpreadEdgeState) -> None:
        """Apply EWMA smoothing to net edge, then update edge gate hysteresis.

        Paper bypass: when paper_edge_gate_bypass=True and is_paper=True,
        the edge gate is disabled so paper fills can occur regardless of edge.
        """
        if not bool(getattr(self.config, "shared_edge_gate_enabled", True)):
            self._net_edge_gate = spread_state.net_edge
            self._risk_evaluator.reset_edge_gate(now)
            self._soft_pause_edge = False
            self._edge_gate_blocked = False
            return
        if _config_is_paper(self.config) and self.config.paper_edge_gate_bypass:
            self._soft_pause_edge = False
            self._edge_gate_blocked = False
            self._risk_evaluator.reset_edge_gate(now)
            return
        raw_net_edge = spread_state.net_edge
        net_edge_gate = raw_net_edge
        period = max(1, int(self.config.edge_gate_ewma_period))
        if period > 1:
            alpha = _TWO / Decimal(period + 1)
            if self._net_edge_ewma is None:
                self._net_edge_ewma = raw_net_edge
            else:
                self._net_edge_ewma = alpha * raw_net_edge + (_ONE - alpha) * self._net_edge_ewma
            # Keep EWMA as the smoothing baseline, but do not let a stale average
            # force a soft-pause when the current edge already clears the live bar.
            net_edge_gate = max(self._net_edge_ewma, raw_net_edge)
        self._net_edge_gate = net_edge_gate
        self._edge_gate_update(now, net_edge_gate, spread_state.min_edge_threshold, spread_state.edge_resume_threshold)
        self._soft_pause_edge = self._edge_gate_blocked

    def _compute_levels_and_sizing(
        self, regime_name: str, regime_spec: RegimeSpec, spread_state: SpreadEdgeState,
        equity_quote: Decimal, mid: Decimal, market: MarketConditions,
    ) -> Tuple[List[Decimal], List[Decimal], Decimal, Decimal]:
        """Compatibility wrapper over the neutral runtime execution-plan hook."""
        plan = self.build_runtime_execution_plan(
            RuntimeDataContext(
                now_ts=float(self.market_data_provider.time()),
                mid=mid,
                regime_name=regime_name,
                regime_spec=regime_spec,
                spread_state=spread_state,
                market=market,
                equity_quote=equity_quote,
                target_base_pct=regime_spec.target_base_pct,
                target_net_base_pct=regime_spec.target_base_pct,
                base_pct_gross=to_decimal(self.processed_data.get("base_pct", _ZERO)) if isinstance(self.processed_data, dict) else _ZERO,
                base_pct_net=to_decimal(self.processed_data.get("net_base_pct", _ZERO)) if isinstance(self.processed_data, dict) else _ZERO,
            )
        )
        return plan.buy_spreads, plan.sell_spreads, plan.projected_total_quote, plan.size_mult

    def build_runtime_execution_plan(self, data_context: RuntimeDataContext) -> RuntimeExecutionPlan:
        """Neutral lane hook that resolves into the active execution-family adapter."""
        return _runtime_family_adapter(self).build_execution_plan(data_context)

    def _apply_runtime_execution_plan(self, data_context: RuntimeDataContext, execution_plan: RuntimeExecutionPlan) -> None:
        _runtime_family_adapter(self).apply_execution_plan(
            execution_plan,
            equity_quote=data_context.equity_quote,
            mid=data_context.mid,
            quote_size_pct=data_context.regime_spec.quote_size_pct,
        )

    def _make_runtime_family_adapter(self) -> RuntimeFamilyAdapter:
        return MarketMakingRuntimeAdapter(self)

    def _resolve_quote_side_mode(
        self,
        *,
        mid: Decimal,
        regime_name: str,
        regime_spec: RegimeSpec,
    ) -> str:
        """Resolve effective quote side mode, including neutral pre-trend filtering."""
        one_sided = regime_spec.one_sided
        reason = "regime"
        alpha_state = str(getattr(self, "_alpha_policy_state", "maker_two_sided"))
        if alpha_state == "no_trade":
            one_sided = "off"
            reason = "alpha_no_trade"
        elif alpha_state in {"maker_bias_buy", "aggressive_buy"}:
            one_sided = "buy_only"
            reason = "alpha_buy_bias"
        elif alpha_state in {"maker_bias_sell", "aggressive_sell"}:
            one_sided = "sell_only"
            reason = "alpha_sell_bias"

        neutral_guard_pct = max(_ZERO, to_decimal(getattr(self.config, "neutral_trend_guard_pct", _ZERO)))
        ema_val = getattr(self, "_regime_ema_value", None)
        ema_val = None if ema_val is None else to_decimal(ema_val)

        if (
            regime_name == "neutral_low_vol"
            and one_sided == "off"
            and alpha_state not in {"no_trade", "maker_bias_buy", "maker_bias_sell", "aggressive_buy", "aggressive_sell"}
            and neutral_guard_pct > _ZERO
            and ema_val is not None
            and ema_val > _ZERO
            and mid > _ZERO
        ):
            displacement_pct = (mid - ema_val) / ema_val
            if displacement_pct >= neutral_guard_pct:
                one_sided = "buy_only"
                reason = "neutral_trend_guard_up"
            elif displacement_pct <= -neutral_guard_pct:
                one_sided = "sell_only"
                reason = "neutral_trend_guard_down"
        if (
            regime_name == "neutral_low_vol"
            and one_sided == "off"
            and alpha_state not in {"no_trade", "maker_bias_buy", "maker_bias_sell", "aggressive_buy", "aggressive_sell"}
            and str(getattr(self, "_selective_quote_state", "inactive")) == "reduced"
            and ema_val is not None
            and ema_val > _ZERO
            and mid > _ZERO
        ):
            selective_bias_pct = max(
                neutral_guard_pct,
                to_decimal(getattr(self.config, "selective_side_bias_pct", neutral_guard_pct)),
            )
            displacement_pct = (mid - ema_val) / ema_val
            if displacement_pct >= selective_bias_pct:
                one_sided = "buy_only"
                reason = "selective_with_trend_up"
            elif displacement_pct <= -selective_bias_pct:
                one_sided = "sell_only"
                reason = "selective_with_trend_down"

        previous_mode = str(getattr(self, "_quote_side_mode", "off") or "off")
        if previous_mode != one_sided:
            self._pending_stale_cancel_actions.extend(
                self._cancel_stale_side_executors(previous_mode, one_sided)
            )
        if alpha_state == "no_trade":
            # Fail-closed for alpha no-trade: ensure already-placed quote executors
            # are canceled immediately instead of waiting for refresh cadence.
            self._pending_stale_cancel_actions.extend(
                EppV24Controller._cancel_active_quote_executors(self)
            )
            EppV24Controller._cancel_alpha_no_trade_paper_orders(self)
        else:
            requested_ids = getattr(self, "_alpha_no_trade_cancel_requested_ids", None)
            if isinstance(requested_ids, set):
                requested_ids.clear()
            self._alpha_no_trade_last_paper_cancel_ts = 0.0
        self._quote_side_mode = one_sided
        self._quote_side_reason = reason
        return one_sided

    def _apply_spread_competitiveness_cap(
        self,
        buy_spreads: List[Decimal],
        sell_spreads: List[Decimal],
        market: MarketConditions,
    ) -> Tuple[List[Decimal], List[Decimal]]:
        cap_mult = max(_ZERO, to_decimal(self.config.max_quote_to_market_spread_mult))
        market_spread = max(_ZERO, to_decimal(market.market_spread_pct))
        if cap_mult <= _ZERO or market_spread <= _ZERO:
            self._spread_competitiveness_cap_active = False
            self._spread_competitiveness_cap_side_pct = _ZERO
            return buy_spreads, sell_spreads
        cap_side = max(to_decimal(market.side_spread_floor), (market_spread * cap_mult) / _TWO)
        buy = [min(max(to_decimal(v), to_decimal(market.side_spread_floor)), cap_side) for v in buy_spreads]
        sell = [min(max(to_decimal(v), to_decimal(market.side_spread_floor)), cap_side) for v in sell_spreads]
        self._spread_competitiveness_cap_side_pct = cap_side
        self._spread_competitiveness_cap_active = (buy != buy_spreads) or (sell != sell_spreads)
        return buy, sell

    def _increment_governor_reason_count(self, attr_name: str, reason: str) -> None:
        """Keep governor counters robust when tests use lightweight controller stubs."""
        counts = getattr(self, attr_name, None)
        if not isinstance(counts, dict):
            counts = {}
            setattr(self, attr_name, counts)
        key = str(reason or "unknown")
        counts[key] = int(counts.get(key, 0)) + 1

    def _compute_pnl_governor_size_mult(self, equity_quote: Decimal, turnover_x: Decimal) -> Decimal:
        """Return dynamic sizing multiplier derived from PnL deficit with safety clamps."""
        self._pnl_governor_size_mult = _ONE
        self._pnl_governor_size_boost_active = False
        reason = "governor_disabled"
        if not self.config.pnl_governor_enabled:
            self._pnl_governor_size_boost_reason = reason
            EppV24Controller._increment_governor_reason_count(self, "_pnl_governor_size_boost_reason_counts", reason)
            return _ONE
        max_boost_pct = max(_ZERO, to_decimal(self.config.pnl_governor_max_size_boost_pct))
        if max_boost_pct <= _ZERO:
            reason = "max_boost_zero"
            self._pnl_governor_size_boost_reason = reason
            EppV24Controller._increment_governor_reason_count(self, "_pnl_governor_size_boost_reason_counts", reason)
            return _ONE
        deficit_ratio = _clip(self._pnl_governor_deficit_ratio, _ZERO, _ONE)
        activation = _clip(to_decimal(self.config.pnl_governor_size_activation_deficit_pct), _ZERO, _ONE)
        if deficit_ratio <= activation:
            reason = "deficit_below_activation"
            self._pnl_governor_size_boost_reason = reason
            EppV24Controller._increment_governor_reason_count(self, "_pnl_governor_size_boost_reason_counts", reason)
            return _ONE
        turnover_soft_cap = max(_ZERO, to_decimal(self.config.pnl_governor_turnover_soft_cap_x))
        if turnover_soft_cap > _ZERO and turnover_x >= turnover_soft_cap:
            reason = "turnover_soft_cap"
            self._pnl_governor_size_boost_reason = reason
            EppV24Controller._increment_governor_reason_count(self, "_pnl_governor_size_boost_reason_counts", reason)
            return _ONE
        _, drawdown_pct = self._risk_loss_metrics(equity_quote)
        drawdown_soft_cap = max(_ZERO, to_decimal(self.config.pnl_governor_drawdown_soft_cap_pct))
        if drawdown_soft_cap > _ZERO and drawdown_pct >= drawdown_soft_cap:
            reason = "drawdown_soft_cap"
            self._pnl_governor_size_boost_reason = reason
            EppV24Controller._increment_governor_reason_count(self, "_pnl_governor_size_boost_reason_counts", reason)
            return _ONE
        margin_soft_floor = max(_ZERO, to_decimal(self.config.margin_ratio_soft_pause_pct))
        if margin_soft_floor > _ZERO and self._margin_ratio <= margin_soft_floor:
            reason = "margin_soft_floor"
            self._pnl_governor_size_boost_reason = reason
            EppV24Controller._increment_governor_reason_count(self, "_pnl_governor_size_boost_reason_counts", reason)
            return _ONE
        if EppV24Controller._fill_edge_below_cost_floor(self):
            reason = "fill_edge_below_cost_floor"
            self._pnl_governor_size_boost_reason = reason
            EppV24Controller._increment_governor_reason_count(
                self, "_pnl_governor_size_boost_reason_counts", reason
            )
            return _ONE
        normalized = _clip((deficit_ratio - activation) / max(Decimal("0.0001"), (_ONE - activation)), _ZERO, _ONE)
        size_mult = _ONE + (normalized * max_boost_pct)
        size_mult = _clip(size_mult, _ONE, _ONE + max_boost_pct)
        self._pnl_governor_size_mult = size_mult
        self._pnl_governor_size_boost_active = size_mult > _ONE
        reason = "active" if self._pnl_governor_size_boost_active else "inactive"
        self._pnl_governor_size_boost_reason = reason
        EppV24Controller._increment_governor_reason_count(self, "_pnl_governor_size_boost_reason_counts", reason)
        return size_mult

    def _fill_edge_below_cost_floor(self) -> bool:
        """Return True when realized fill edge is worse than estimated maker cost floor."""
        fill_edge_ewma = getattr(self, "_fill_edge_ewma", None)
        if fill_edge_ewma is None:
            return False
        cost_floor_bps = (
            max(_ZERO, to_decimal(getattr(self, "_maker_fee_pct", _ZERO)))
            + max(_ZERO, to_decimal(getattr(self.config, "slippage_est_pct", _ZERO)))
        ) * _10K
        return to_decimal(fill_edge_ewma) < -cost_floor_bps

    def _adverse_fill_soft_pause_active(self) -> bool:
        """Return True when realized fill-edge quality warrants temporary no-trade pause."""
        if not bool(getattr(self.config, "adverse_fill_soft_pause_enabled", False)):
            return False
        if self._fill_edge_ewma is None:
            return False
        min_fills = max(1, int(getattr(self.config, "adverse_fill_soft_pause_min_fills", 120)))
        if int(getattr(self, "_fill_count_for_kelly", 0)) < min_fills:
            return False
        adverse_threshold = max(1, int(getattr(self.config, "adverse_fill_count_threshold", 20)))
        if int(getattr(self, "_adverse_fill_count", 0)) < adverse_threshold:
            return False
        cost_floor_mult = max(_ZERO, to_decimal(getattr(self.config, "adverse_fill_soft_pause_cost_floor_mult", _ONE)))
        if cost_floor_mult == _ONE:
            return EppV24Controller._fill_edge_below_cost_floor(self)
        cost_floor_bps = (
            max(_ZERO, to_decimal(getattr(self, "_maker_fee_pct", _ZERO)))
            + max(_ZERO, to_decimal(getattr(self.config, "slippage_est_pct", _ZERO)))
        ) * _10K * cost_floor_mult
        return self._fill_edge_ewma < -cost_floor_bps

    def _edge_confidence_soft_pause_active(self) -> bool:
        """Pause when the confidence-adjusted edge upper bound remains below cost floor."""
        if not bool(getattr(self.config, "edge_confidence_soft_pause_enabled", False)):
            return False
        edge_mean_bps = self._fill_edge_ewma
        edge_var_bps2 = self._fill_edge_variance
        if edge_mean_bps is None or edge_var_bps2 is None:
            return False
        n_fills = max(0, int(getattr(self, "_fill_count_for_kelly", 0)))
        min_fills = max(1, int(getattr(self.config, "edge_confidence_soft_pause_min_fills", 120)))
        if n_fills < min_fills:
            return False
        safe_var = max(_ZERO, to_decimal(edge_var_bps2))
        if safe_var <= _ZERO:
            return False

        z_score = max(_ZERO, to_decimal(getattr(self.config, "edge_confidence_soft_pause_z_score", Decimal("1.96"))))
        std_err = Decimal(str(math.sqrt(float(safe_var)) / max(1.0, math.sqrt(float(n_fills)))))
        upper_edge_bps = to_decimal(edge_mean_bps) + (z_score * std_err)

        cost_floor_mult = max(
            _ZERO,
            to_decimal(getattr(self.config, "edge_confidence_soft_pause_cost_floor_mult", _ONE)),
        )
        cost_floor_bps = (
            max(_ZERO, to_decimal(getattr(self, "_maker_fee_pct", _ZERO)))
            + max(_ZERO, to_decimal(getattr(self.config, "slippage_est_pct", _ZERO)))
        ) * _10K * cost_floor_mult
        return upper_edge_bps < -cost_floor_bps

    def _slippage_soft_pause_active(self) -> bool:
        """Pause when recent realized slippage p95 exceeds a configured budget."""
        if not bool(getattr(self.config, "slippage_soft_pause_enabled", False)):
            return False
        fill_history = getattr(self, "_auto_calibration_fill_history", None)
        if fill_history is None:
            return False
        min_fills = max(1, int(getattr(self.config, "slippage_soft_pause_min_fills", 100)))
        window_fills = max(
            min_fills,
            int(getattr(self.config, "slippage_soft_pause_window_fills", 300)),
        )
        window = list(fill_history)[-window_fills:]
        if len(window) < min_fills:
            return False
        positive_slippage_bps = [
            max(_ZERO, to_decimal(row.get("slippage_bps", _ZERO)))
            for row in window
            if isinstance(row, dict)
        ]
        if len(positive_slippage_bps) < min_fills:
            return False
        p95_slippage_bps = EppV24Controller._auto_calibration_p95(positive_slippage_bps)
        trigger_bps = max(_ZERO, to_decimal(getattr(self.config, "slippage_soft_pause_p95_bps", Decimal("25"))))
        return p95_slippage_bps >= trigger_bps

    def _recent_positive_slippage_p95_bps(
        self,
        *,
        window_fills: Optional[int] = None,
        min_fills: Optional[int] = None,
    ) -> Decimal:
        fill_history = getattr(self, "_auto_calibration_fill_history", None)
        if fill_history is None:
            return _ZERO
        min_fills_resolved = max(
            1,
            int(
                min_fills
                if min_fills is not None
                else getattr(self.config, "slippage_soft_pause_min_fills", 100)
            ),
        )
        window_fills_resolved = max(
            min_fills_resolved,
            int(
                window_fills
                if window_fills is not None
                else getattr(self.config, "slippage_soft_pause_window_fills", 300)
            ),
        )
        window = list(fill_history)[-window_fills_resolved:]
        if len(window) < min_fills_resolved:
            return _ZERO
        positive_slippage_bps = [
            max(_ZERO, to_decimal(row.get("slippage_bps", _ZERO)))
            for row in window
            if isinstance(row, dict)
        ]
        if len(positive_slippage_bps) < min_fills_resolved:
            return _ZERO
        return EppV24Controller._auto_calibration_p95(positive_slippage_bps)

    def _compute_selective_quote_quality(self, regime_name: str) -> Dict[str, Decimal | str]:
        if not bool(getattr(self.config, "selective_quoting_enabled", False)):
            metrics: Dict[str, Decimal | str] = {
                "score": _ZERO,
                "state": "inactive",
                "reason": "disabled",
                "adverse_ratio": _ZERO,
                "slippage_p95_bps": _ZERO,
            }
        else:
            min_fills = max(1, int(getattr(self.config, "selective_quality_min_fills", 40)))
            fill_count = max(0, int(getattr(self, "_fill_count_for_kelly", 0)))
            if fill_count < min_fills:
                metrics = {
                    "score": _ZERO,
                    "state": "inactive",
                    "reason": "insufficient_history",
                    "adverse_ratio": _ZERO,
                    "slippage_p95_bps": _ZERO,
                }
            else:
                cost_floor_bps = (
                    max(_ZERO, to_decimal(getattr(self, "_maker_fee_pct", _ZERO)))
                    + max(_ZERO, to_decimal(getattr(self.config, "slippage_est_pct", _ZERO)))
                ) * _10K
                fill_edge_ewma = getattr(self, "_fill_edge_ewma", None)
                fill_edge_ewma = None if fill_edge_ewma is None else to_decimal(fill_edge_ewma)
                negative_edge_ratio = _ZERO
                if (
                    fill_edge_ewma is not None
                    and cost_floor_bps > _ZERO
                    and fill_edge_ewma < -cost_floor_bps
                ):
                    negative_edge_ratio = _clip(
                        ((-fill_edge_ewma) - cost_floor_bps) / cost_floor_bps,
                        _ZERO,
                        _ONE,
                    )

                adverse_threshold = max(1, int(getattr(self.config, "adverse_fill_count_threshold", 20)))
                adverse_ratio = _clip(
                    Decimal(int(getattr(self, "_adverse_fill_count", 0))) / Decimal(adverse_threshold),
                    _ZERO,
                    _ONE,
                )
                slippage_p95_bps = EppV24Controller._recent_positive_slippage_p95_bps(
                    self,
                    min_fills=min_fills,
                )
                slippage_trigger_bps = max(
                    Decimal("0.1"),
                    to_decimal(getattr(self.config, "slippage_soft_pause_p95_bps", Decimal("25"))),
                )
                slippage_ratio = _clip(slippage_p95_bps / slippage_trigger_bps, _ZERO, _ONE)

                score = (
                    negative_edge_ratio * Decimal("0.50")
                    + adverse_ratio * Decimal("0.25")
                    + slippage_ratio * Decimal("0.25")
                )
                if regime_name == "neutral_low_vol" and fill_edge_ewma is not None and fill_edge_ewma < _ZERO:
                    score += Decimal("0.10")
                score = _clip(score, _ZERO, _ONE)

                reduce_threshold = _clip(
                    to_decimal(getattr(self.config, "selective_quality_reduce_threshold", Decimal("0.45"))),
                    _ZERO,
                    _ONE,
                )
                block_threshold = _clip(
                    to_decimal(getattr(self.config, "selective_quality_block_threshold", Decimal("0.85"))),
                    reduce_threshold,
                    _ONE,
                )
                state = "inactive"
                if score >= block_threshold:
                    state = "blocked"
                elif score >= reduce_threshold:
                    state = "reduced"

                reason = "healthy"
                if state != "inactive":
                    if slippage_ratio >= max(negative_edge_ratio, adverse_ratio) and slippage_ratio > _ZERO:
                        reason = "slippage_shock"
                    elif negative_edge_ratio >= adverse_ratio and negative_edge_ratio > _ZERO:
                        reason = "negative_fill_edge"
                    elif adverse_ratio > _ZERO:
                        reason = "adverse_fill_streak"
                    elif regime_name == "neutral_low_vol":
                        reason = "neutral_low_vol_filter"

                metrics = {
                    "score": score,
                    "state": state,
                    "reason": reason,
                    "adverse_ratio": adverse_ratio,
                    "slippage_p95_bps": slippage_p95_bps,
                }

        self._selective_quote_score = to_decimal(metrics["score"])
        self._selective_quote_state = str(metrics["state"])
        self._selective_quote_reason = str(metrics["reason"])
        self._selective_quote_adverse_ratio = to_decimal(metrics["adverse_ratio"])
        self._selective_quote_slippage_p95_bps = to_decimal(metrics["slippage_p95_bps"])
        return metrics

    def _compute_alpha_policy(
        self,
        *,
        regime_name: str,
        spread_state: SpreadEdgeState,
        market: MarketConditions,
        target_net_base_pct: Decimal,
        base_pct_net: Decimal,
    ) -> Dict[str, Decimal | str | bool]:
        if not bool(getattr(self.config, "alpha_policy_enabled", True)):
            metrics: Dict[str, Decimal | str | bool] = {
                "state": "maker_two_sided",
                "reason": "disabled",
                "maker_score": _ONE,
                "aggressive_score": _ZERO,
                "cross_allowed": False,
            }
        else:
            inv_error = target_net_base_pct - base_pct_net
            max_base = max(
                Decimal("0.05"),
                to_decimal(getattr(self.config, "max_base_pct", Decimal("0.45"))),
            )
            inventory_urgency = _clip(abs(inv_error) / max_base, _ZERO, _ONE)
            self._inventory_urgency_score = inventory_urgency

            edge_buffer = max(_ZERO, spread_state.net_edge - spread_state.min_edge_threshold)
            edge_buffer_score = _clip(
                edge_buffer / max(Decimal("0.0001"), spread_state.min_edge_threshold),
                _ZERO,
                _ONE,
            )
            drift_penalty = _clip(
                max(_ZERO, spread_state.adverse_drift - spread_state.smooth_drift) * Decimal("4000"),
                _ZERO,
                _ONE,
            )
            market_health = _ONE - drift_penalty
            imbalance_abs = _clip(abs(getattr(self, "_ob_imbalance", _ZERO)), _ZERO, _ONE)
            imbalance_alignment = _ZERO
            if inv_error > _ZERO:
                imbalance_alignment = _clip(max(_ZERO, to_decimal(getattr(self, "_ob_imbalance", _ZERO))), _ZERO, _ONE)
            elif inv_error < _ZERO:
                imbalance_alignment = _clip(max(_ZERO, -to_decimal(getattr(self, "_ob_imbalance", _ZERO))), _ZERO, _ONE)

            selective_penalty = _clip(to_decimal(getattr(self, "_selective_quote_score", _ZERO)), _ZERO, _ONE)
            maker_score = _clip(
                edge_buffer_score * Decimal("0.45")
                + market_health * Decimal("0.25")
                + imbalance_abs * Decimal("0.10")
                + imbalance_alignment * Decimal("0.10")
                + inventory_urgency * Decimal("0.10")
                - selective_penalty * Decimal("0.25"),
                _ZERO,
                _ONE,
            )
            aggressive_score = _clip(
                maker_score * Decimal("0.55")
                + imbalance_alignment * Decimal("0.20")
                + inventory_urgency * Decimal("0.25"),
                _ZERO,
                _ONE,
            )

            state = "maker_two_sided"
            reason = "maker_baseline"
            cross_allowed = False
            urgency_threshold = _clip(
                to_decimal(getattr(self.config, "alpha_policy_inventory_relief_threshold", Decimal("0.55"))),
                _ZERO,
                _ONE,
            )
            no_trade_threshold = _clip(
                to_decimal(getattr(self.config, "alpha_policy_no_trade_threshold", Decimal("0.35"))),
                _ZERO,
                _ONE,
            )
            aggressive_threshold = _clip(
                to_decimal(getattr(self.config, "alpha_policy_aggressive_threshold", Decimal("0.78"))),
                no_trade_threshold,
                _ONE,
            )
            bias_state = ""
            if inv_error > _ZERO and inventory_urgency >= urgency_threshold:
                bias_state = "buy"
            elif inv_error < _ZERO and inventory_urgency >= urgency_threshold:
                bias_state = "sell"
            else:
                imbalance = to_decimal(getattr(self, "_ob_imbalance", _ZERO))
                if imbalance >= Decimal("0.25"):
                    bias_state = "buy"
                elif imbalance <= Decimal("-0.25"):
                    bias_state = "sell"

            if market.order_book_stale:
                state = "no_trade"
                reason = "order_book_stale"
            elif market.market_spread_too_small:
                state = "no_trade"
                reason = "market_spread_too_small"
            elif (
                regime_name == "neutral_low_vol"
                and maker_score < no_trade_threshold
                and spread_state.net_edge < spread_state.edge_resume_threshold
            ):
                state = "no_trade"
                reason = "neutral_low_edge"
            elif aggressive_score >= aggressive_threshold and bias_state:
                state = f"aggressive_{bias_state}"
                reason = "inventory_relief" if inventory_urgency >= urgency_threshold else "imbalance_alignment"
                cross_allowed = True
            elif bias_state:
                state = f"maker_bias_{bias_state}"
                reason = "inventory_relief" if inventory_urgency >= urgency_threshold else "imbalance_alignment"

            metrics = {
                "state": state,
                "reason": reason,
                "maker_score": maker_score,
                "aggressive_score": aggressive_score,
                "cross_allowed": cross_allowed,
            }

        self._alpha_policy_state = str(metrics["state"])
        self._alpha_policy_reason = str(metrics["reason"])
        self._alpha_maker_score = to_decimal(metrics["maker_score"])
        self._alpha_aggressive_score = to_decimal(metrics["aggressive_score"])
        self._alpha_cross_allowed = bool(metrics["cross_allowed"])
        if "inventory_urgency" not in locals():
            self._inventory_urgency_score = _ZERO
        return metrics

    def _evaluate_all_risk(
        self, spread_state: SpreadEdgeState, base_pct_gross: Decimal,
        equity_quote: Decimal, projected_total_quote: Decimal, market: MarketConditions,
    ) -> Tuple[List[str], bool, Decimal, Decimal]:
        """Run risk policy, margin, drift, and operational checks."""
        daily_loss_pct, drawdown_pct = self._risk_loss_metrics(equity_quote)
        risk_reasons, risk_hard_stop = self._risk_evaluator.evaluate_all_risk(
            daily_loss_pct=daily_loss_pct,
            drawdown_pct=drawdown_pct,
            base_pct_gross=base_pct_gross,
            turnover_x=spread_state.turnover_x,
            projected_total_quote=projected_total_quote,
            is_perp=self._is_perp,
            margin_ratio=self._margin_ratio,
            startup_position_sync_done=self._startup_position_sync_done,
            position_drift_pct=self._position_drift_pct,
            order_book_stale=market.order_book_stale,
            pending_eod_close=self._pending_eod_close,
        )
        if EppV24Controller._adverse_fill_soft_pause_active(self):
            if "adverse_fill_soft_pause" not in risk_reasons:
                risk_reasons.append("adverse_fill_soft_pause")
        if EppV24Controller._edge_confidence_soft_pause_active(self):
            if "edge_confidence_soft_pause" not in risk_reasons:
                risk_reasons.append("edge_confidence_soft_pause")
        if EppV24Controller._slippage_soft_pause_active(self):
            if "slippage_soft_pause" not in risk_reasons:
                risk_reasons.append("slippage_soft_pause")
        if str(getattr(self, "_selective_quote_state", "inactive")) == "blocked":
            if "selective_quote_soft_pause" not in risk_reasons:
                risk_reasons.append("selective_quote_soft_pause")
        return risk_reasons, risk_hard_stop, daily_loss_pct, drawdown_pct

    def _resolve_guard_state(
        self, now: float, market: MarketConditions,
        risk_reasons: List[str], risk_hard_stop: bool,
    ) -> GuardState:
        """Feed OpsGuard, apply overrides, and manage cancel budget."""
        balance_ok = self._balances_consistent()
        if self._runtime_adapter.balance_read_failed:
            balance_ok = False
        state = self._ops_guard.update(
            OpsSnapshot(
                connector_ready=market.connector_ready,
                balances_consistent=balance_ok,
                cancel_fail_streak=self._cancel_fail_streak,
                edge_gate_blocked=self._soft_pause_edge,
                high_vol=market.is_high_vol,
                market_spread_too_small=market.market_spread_too_small,
                risk_reasons=risk_reasons,
                risk_hard_stop=risk_hard_stop,
            )
        )
        pause_reasons = {"adverse_fill_soft_pause", "edge_confidence_soft_pause", "slippage_soft_pause"}
        if set(risk_reasons).intersection(pause_reasons) and state != GuardState.HARD_STOP:
            state = GuardState.SOFT_PAUSE
        # Fail-closed on stale order book to avoid quoting off a frozen top-of-book.
        if market.order_book_stale and state != GuardState.HARD_STOP:
            stale_soft_pause_after_s = max(
                float(self.config.order_book_stale_after_s),
                float(self.config.order_book_stale_soft_pause_after_s),
            )
            if self._order_book_stale_age_s(now) >= stale_soft_pause_after_s:
                state = GuardState.SOFT_PAUSE
        if now < self._reconnect_cooldown_until and state == GuardState.RUNNING:
            state = GuardState.SOFT_PAUSE
        if self._consecutive_stuck_ticks >= self.config.stuck_executor_escalation_ticks:
            state = GuardState.SOFT_PAUSE
            if self._consecutive_stuck_ticks >= self.config.stuck_executor_escalation_ticks + self._ops_guard.max_operational_pause_cycles:
                state = self._ops_guard.force_hard_stop("stuck_executors_persistent")
        if not self.config.enabled or self.config.variant in {"b", "c"}:
            state = self._ops_guard.force_hard_stop("phase0_stub_disabled")
        if self.config.no_trade or self.config.variant == "d":
            state = GuardState.SOFT_PAUSE
        if self._external_soft_pause:
            state = GuardState.SOFT_PAUSE

        cancel_rate = self._cancel_per_min(now)
        if cancel_rate > self.config.cancel_budget_per_min:
            self._cancel_budget_breach_count += 1
            self._cancel_pause_until = now + self.config.cancel_pause_cooldown_s
            if self._cancel_budget_breach_count >= 3:
                state = self._ops_guard.force_hard_stop("cancel_budget_repeated_breach")
                logger.error("Cancel budget breached %d times — escalating to HARD_STOP", self._cancel_budget_breach_count)
        if now < self._cancel_pause_until and state != GuardState.HARD_STOP:
            state = GuardState.SOFT_PAUSE
        if cancel_rate <= self.config.cancel_budget_per_min and now >= self._cancel_pause_until:
            self._cancel_budget_breach_count = 0
        return state

    def _extend_processed_data_before_log(
        self,
        *,
        processed_data: ProcessedState,
        snapshot: Dict[str, Any],
        state: GuardState,
        regime_name: str,
        market: MarketConditions,
        projected_total_quote: Decimal,
    ) -> None:
        """Subclass hook for injecting extra processed-data fields before minute logging."""
        return None

    def extend_runtime_processed_data(
        self,
        *,
        processed_data: ProcessedState,
        data_context: RuntimeDataContext,
        risk_decision: RuntimeRiskDecision,
        execution_plan: RuntimeExecutionPlan,
        snapshot: Dict[str, Any],
    ) -> None:
        """Neutral runtime hook that preserves the legacy processed-data extension point."""
        self._extend_processed_data_before_log(
            processed_data=processed_data,
            snapshot=snapshot,
            state=risk_decision.guard_state,
            regime_name=data_context.regime_name,
            market=data_context.market,
            projected_total_quote=execution_plan.projected_total_quote,
        )

    def _emit_tick_output(
        self, _t0: float, now: float, mid: Decimal,
        regime_name: str, target_base_pct: Decimal, target_net_base_pct: Decimal,
        base_pct_gross: Decimal, base_pct_net: Decimal,
        equity_quote: Decimal, spread_state: SpreadEdgeState, market: MarketConditions,
        risk_hard_stop: bool, risk_reasons: List[str],
        daily_loss_pct: Decimal, drawdown_pct: Decimal,
        projected_total_quote: Decimal, state: GuardState,
        runtime_data_context: Optional[RuntimeDataContext] = None,
        runtime_execution_plan: Optional[RuntimeExecutionPlan] = None,
        runtime_risk_decision: Optional[RuntimeRiskDecision] = None,
    ) -> None:
        """Build ProcessedState, blank levels on pause, and log the minute row."""
        risk_reasons_for_log = list(risk_reasons)
        derisk_only = False
        derisk_runtime_recovered = False
        rr = set(risk_reasons)
        inventory_derisk_reasons = rr.intersection(_INVENTORY_DERISK_REASONS)
        hard_stop_flatten_floor = EppV24Controller._position_rebalance_floor(self, mid)
        hard_stop_inventory_flatten = (
            state == GuardState.HARD_STOP
            and abs(self._position_base) > hard_stop_flatten_floor
        )
        hard_stop_residual_below_floor = (
            state == GuardState.HARD_STOP
            and abs(self._position_base) > _BALANCE_EPSILON
            and not hard_stop_inventory_flatten
        )
        if state == GuardState.SOFT_PAUSE and not risk_hard_stop and inventory_derisk_reasons:
            derisk_only = True
            risk_reasons_for_log.append("derisk_only")
        if hard_stop_inventory_flatten:
            risk_reasons_for_log.append("derisk_hard_stop_flatten")
        elif hard_stop_residual_below_floor:
            risk_reasons_for_log.append("derisk_hard_stop_residual_below_floor")
        derisk_force_taker = self._update_derisk_force_mode(now, derisk_only, rr)
        if hard_stop_inventory_flatten:
            # When hard-stop is triggered while inventory is still open, allow only
            # force-taker rebalance flow so risk can be reduced instead of frozen.
            derisk_force_taker = True
            self._derisk_force_taker = True
        if derisk_force_taker:
            risk_reasons_for_log.append("derisk_force_taker")
        if bool(getattr(self, "_derisk_force_taker_expectancy_guard_blocked", False)):
            risk_reasons_for_log.append("derisk_force_taker_expectancy_blocked")
        selective_state = str(getattr(self, "_selective_quote_state", "inactive"))
        if selective_state == "reduced":
            risk_reasons_for_log.append("selective_quote_reduced")
        elif selective_state == "blocked" and "selective_quote_soft_pause" not in risk_reasons_for_log:
            risk_reasons_for_log.append("selective_quote_soft_pause")

        base_bal, quote_bal = self._get_balances()
        snapshot = self._build_tick_snapshot(equity_quote)
        self.processed_data = self._tick_emitter.build_tick_output(
            mid=mid, regime_name=regime_name, target_base_pct=target_base_pct,
            base_pct=base_pct_gross, state=state, spread_state=spread_state,
            market=market, equity_quote=equity_quote,
            base_bal=base_bal, quote_bal=quote_bal,
            risk_hard_stop=risk_hard_stop, risk_reasons=risk_reasons_for_log,
            daily_loss_pct=daily_loss_pct, drawdown_pct=drawdown_pct,
            projected_total_quote=projected_total_quote, snapshot=snapshot,
        )
        self.processed_data["net_base_pct"] = base_pct_net
        self.processed_data["target_net_base_pct"] = target_net_base_pct
        self.processed_data["net_edge_gate_pct"] = self._net_edge_gate
        self.processed_data["net_edge_ewma_pct"] = self._net_edge_ewma if self._net_edge_ewma is not None else spread_state.net_edge
        self.processed_data["adverse_fill_soft_pause_active"] = snapshot["adverse_fill_soft_pause_active"]
        self.processed_data["edge_confidence_soft_pause_active"] = snapshot["edge_confidence_soft_pause_active"]
        self.processed_data["slippage_soft_pause_active"] = snapshot["slippage_soft_pause_active"]
        self.processed_data["adaptive_effective_min_edge_pct"] = snapshot["adaptive_effective_min_edge_pct"]
        self.processed_data["adaptive_fill_age_s"] = snapshot["adaptive_fill_age_s"]
        self.processed_data["adaptive_market_spread_bps_ewma"] = snapshot["adaptive_market_spread_bps_ewma"]
        self.processed_data["adaptive_band_pct_ewma"] = snapshot["adaptive_band_pct_ewma"]
        self.processed_data["adaptive_market_floor_pct"] = snapshot["adaptive_market_floor_pct"]
        self.processed_data["adaptive_vol_ratio"] = snapshot["adaptive_vol_ratio"]
        self.processed_data["pnl_governor_active"] = snapshot["pnl_governor_active"]
        self.processed_data["pnl_governor_day_progress"] = snapshot["pnl_governor_day_progress"]
        self.processed_data["pnl_governor_target_pnl_pct"] = snapshot["pnl_governor_target_pnl_pct"]
        self.processed_data["pnl_governor_target_pnl_quote"] = snapshot["pnl_governor_target_pnl_quote"]
        self.processed_data["pnl_governor_expected_pnl_quote"] = snapshot["pnl_governor_expected_pnl_quote"]
        self.processed_data["pnl_governor_actual_pnl_quote"] = snapshot["pnl_governor_actual_pnl_quote"]
        self.processed_data["pnl_governor_deficit_ratio"] = snapshot["pnl_governor_deficit_ratio"]
        self.processed_data["pnl_governor_edge_relax_bps"] = snapshot["pnl_governor_edge_relax_bps"]
        self.processed_data["pnl_governor_size_mult"] = snapshot["pnl_governor_size_mult"]
        self.processed_data["pnl_governor_size_boost_active"] = snapshot["pnl_governor_size_boost_active"]
        self.processed_data["pnl_governor_activation_reason"] = snapshot["pnl_governor_activation_reason"]
        self.processed_data["pnl_governor_size_boost_reason"] = snapshot["pnl_governor_size_boost_reason"]
        self.processed_data["pnl_governor_activation_reason_counts"] = snapshot["pnl_governor_activation_reason_counts"]
        self.processed_data["pnl_governor_size_boost_reason_counts"] = snapshot["pnl_governor_size_boost_reason_counts"]
        self.processed_data["derisk_force_taker_min_base"] = snapshot["derisk_force_taker_min_base"]
        self.processed_data["derisk_force_taker_expectancy_guard_blocked"] = snapshot[
            "derisk_force_taker_expectancy_guard_blocked"
        ]
        self.processed_data["derisk_force_taker_expectancy_guard_reason"] = snapshot[
            "derisk_force_taker_expectancy_guard_reason"
        ]
        self.processed_data["derisk_force_taker_expectancy_mean_quote"] = snapshot[
            "derisk_force_taker_expectancy_mean_quote"
        ]
        self.processed_data["derisk_force_taker_expectancy_taker_fills"] = snapshot[
            "derisk_force_taker_expectancy_taker_fills"
        ]
        self.processed_data["selective_quote_state"] = snapshot["selective_quote_state"]
        self.processed_data["selective_quote_score"] = snapshot["selective_quote_score"]
        self.processed_data["selective_quote_reason"] = snapshot["selective_quote_reason"]
        self.processed_data["selective_quote_adverse_ratio"] = snapshot["selective_quote_adverse_ratio"]
        self.processed_data["selective_quote_slippage_p95_bps"] = snapshot["selective_quote_slippage_p95_bps"]
        self.processed_data["alpha_policy_state"] = snapshot["alpha_policy_state"]
        self.processed_data["alpha_policy_reason"] = snapshot["alpha_policy_reason"]
        self.processed_data["alpha_maker_score"] = snapshot["alpha_maker_score"]
        self.processed_data["alpha_aggressive_score"] = snapshot["alpha_aggressive_score"]
        self.processed_data["alpha_cross_allowed"] = snapshot["alpha_cross_allowed"]
        self.processed_data["inventory_urgency_pct"] = snapshot["inventory_urgency_pct"]
        self.processed_data["quote_side_mode"] = self._quote_side_mode
        self.processed_data["quote_side_reason"] = self._quote_side_reason
        self.processed_data["history_seed_status"] = self._history_seed_status
        self.processed_data["history_seed_reason"] = self._history_seed_reason
        self.processed_data["history_seed_source"] = self._history_seed_source
        self.processed_data["history_seed_bars"] = self._history_seed_bars
        self.processed_data["history_seed_latency_ms"] = self._history_seed_latency_ms
        runtime_data_context = runtime_data_context or RuntimeDataContext(
            now_ts=now,
            mid=mid,
            regime_name=regime_name,
            regime_spec=self._resolved_specs[regime_name],
            spread_state=spread_state,
            market=market,
            equity_quote=equity_quote,
            target_base_pct=target_base_pct,
            target_net_base_pct=target_net_base_pct,
            base_pct_gross=base_pct_gross,
            base_pct_net=base_pct_net,
        )
        runtime_execution_plan = runtime_execution_plan or RuntimeExecutionPlan(
            family="market_making",
            buy_spreads=list(self._runtime_levels.buy_spreads),
            sell_spreads=list(self._runtime_levels.sell_spreads),
            projected_total_quote=projected_total_quote,
            size_mult=to_decimal(snapshot.get("pnl_governor_size_mult", _ONE)),
        )
        runtime_risk_decision = runtime_risk_decision or RuntimeRiskDecision(
            risk_reasons=list(risk_reasons_for_log),
            risk_hard_stop=risk_hard_stop,
            daily_loss_pct=daily_loss_pct,
            drawdown_pct=drawdown_pct,
            guard_state=state,
        )
        self.extend_runtime_processed_data(
            processed_data=self.processed_data,
            data_context=runtime_data_context,
            risk_decision=runtime_risk_decision,
            execution_plan=runtime_execution_plan,
            snapshot=snapshot,
        )

        self._tick_duration_ms = (_time_mod.perf_counter() - _t0) * 1000.0
        self.processed_data["_tick_duration_ms"] = self._tick_duration_ms

        if state != GuardState.RUNNING and not derisk_only:
            self._runtime_levels.buy_spreads = []
            self._runtime_levels.sell_spreads = []
            self._runtime_levels.buy_amounts_pct = []
            self._runtime_levels.sell_amounts_pct = []
            self._runtime_levels.total_amount_quote = Decimal("0")
        elif derisk_only:
            tight = self.config.derisk_spread_pct
            buy_only = False
            if "base_pct_below_min" in rr:
                buy_only = True
            elif "base_pct_above_max" in rr or "eod_close_pending" in rr:
                buy_only = base_pct_net < _ZERO
            if buy_only:
                self._runtime_levels.sell_spreads = []
                self._runtime_levels.sell_amounts_pct = []
                active_side_count = max(1, len(self._runtime_levels.buy_spreads))
                if tight > _ZERO:
                    self._runtime_levels.buy_spreads = [tight] * active_side_count
                if not self._runtime_levels.buy_amounts_pct:
                    per_level = Decimal("100") / Decimal(active_side_count)
                    self._runtime_levels.buy_amounts_pct = [per_level] * active_side_count
                if self._runtime_levels.total_amount_quote <= _ZERO:
                    self._runtime_levels.total_amount_quote = self.config.total_amount_quote
                    derisk_runtime_recovered = True
                if self.config.max_order_notional_quote > 0:
                    max_total = self.config.max_order_notional_quote * Decimal(active_side_count)
                    self._runtime_levels.total_amount_quote = min(self._runtime_levels.total_amount_quote, max_total)
            else:
                self._runtime_levels.buy_spreads = []
                self._runtime_levels.buy_amounts_pct = []
                active_side_count = max(1, len(self._runtime_levels.sell_spreads))
                if tight > _ZERO:
                    self._runtime_levels.sell_spreads = [tight] * active_side_count
                if not self._runtime_levels.sell_amounts_pct:
                    per_level = Decimal("100") / Decimal(active_side_count)
                    self._runtime_levels.sell_amounts_pct = [per_level] * active_side_count
                if self._runtime_levels.total_amount_quote <= _ZERO:
                    self._runtime_levels.total_amount_quote = self.config.total_amount_quote
                    derisk_runtime_recovered = True
                if self.config.max_order_notional_quote > 0:
                    max_total = self.config.max_order_notional_quote * Decimal(active_side_count)
                    self._runtime_levels.total_amount_quote = min(self._runtime_levels.total_amount_quote, max_total)

            if derisk_force_taker and mid > _ZERO:
                close_notional_quote = abs(self._position_base) * mid
                target_total_quote = close_notional_quote * Decimal("1.05")
                if self.config.max_total_notional_quote > 0:
                    target_total_quote = min(target_total_quote, self.config.max_total_notional_quote)
                if target_total_quote > self._runtime_levels.total_amount_quote:
                    self._runtime_levels.total_amount_quote = target_total_quote

        if derisk_runtime_recovered:
            self._derisk_runtime_recovery_count += 1
            risk_reasons_for_log.append("derisk_runtime_recovered")
            logger.warning(
                "Recovered derisk runtime sizing after soft-pause zeroing; "
                "recovery_count=%s total_amount_quote=%s",
                self._derisk_runtime_recovery_count,
                self._runtime_levels.total_amount_quote,
            )
        self.processed_data["derisk_runtime_recovered"] = derisk_runtime_recovered
        self.processed_data["derisk_runtime_recovery_count"] = self._derisk_runtime_recovery_count
        self.processed_data["derisk_force_taker"] = derisk_force_taker

        event_ts = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()
        snapshot["tick_duration_ms"] = self._tick_duration_ms
        snapshot["order_book_stale"] = self._is_order_book_stale(now)
        snapshot["cancel_per_min"] = self._cancel_per_min(now)
        runtime_orders_active = sum(1 for ex in self.executors_info if getattr(ex, "is_active", False))
        snapshot["orders_active"] = max(runtime_orders_active, EppV24Controller._paper_open_order_count(self))
        minute_row = self._tick_emitter.log_minute(
            now, event_ts, self.processed_data, state, risk_reasons_for_log, snapshot
        )
        self._publish_bot_minute_snapshot_telemetry(event_ts, minute_row)
        self._auto_calibration_record_minute(
            now_ts=now,
            state=state,
            risk_reasons=risk_reasons_for_log,
            snapshot=snapshot,
            daily_loss_pct=daily_loss_pct,
            drawdown_pct=drawdown_pct,
        )
        try:
            eq = self.processed_data.get("equity_quote", _ZERO)
            eq = eq if isinstance(eq, Decimal) else to_decimal(eq)
            self._equity_samples_today.append(eq)
            self._equity_sample_ts_today.append(event_ts)
        except Exception:
            logger.debug("Equity sample recording failed", exc_info=True)
        self._auto_calibration_maybe_run(
            now_ts=now,
            state=state,
            risk_reasons=risk_reasons_for_log,
            daily_loss_pct=daily_loss_pct,
            drawdown_pct=drawdown_pct,
        )
        self._save_daily_state()

    def get_executor_config(self, level_id: str, price: Decimal, amount: Decimal):
        return _runtime_family_adapter(self).get_executor_config(level_id, price, amount)

    def _derisk_force_min_base_amount(self) -> Decimal:
        """Resolve minimum absolute inventory required to allow force-taker mode."""
        min_force_base = _BALANCE_EPSILON
        min_base_mult = max(_ZERO, to_decimal(getattr(self.config, "derisk_force_taker_min_base_mult", Decimal("2.0"))))
        if min_base_mult <= _ZERO:
            return min_force_base

        reference_price = _ZERO
        processed_data = getattr(self, "processed_data", {})
        if isinstance(processed_data, dict):
            reference_price = to_decimal(processed_data.get("reference_price", _ZERO))
        if reference_price <= _ZERO:
            reference_price = max(_ZERO, to_decimal(getattr(self, "_avg_entry_price", _ZERO)))
        if reference_price <= _ZERO:
            return min_force_base

        min_base_amount_fn = getattr(self, "_min_base_amount", None)
        if not callable(min_base_amount_fn):
            return min_force_base
        try:
            min_exchange_base = max(_ZERO, to_decimal(min_base_amount_fn(reference_price)))
        except Exception:
            logger.debug("derisk force min-base resolution failed", exc_info=True)
            return min_force_base
        return max(min_force_base, min_exchange_base * min_base_mult)

    def _derisk_force_expectancy_allows(self, abs_position_base: Decimal, min_force_base: Decimal) -> bool:
        """Return True when force-taker derisk is allowed by recent taker expectancy."""
        self._derisk_force_taker_expectancy_guard_blocked = False
        self._derisk_force_taker_expectancy_guard_reason = "disabled"
        self._derisk_force_taker_expectancy_mean_quote = _ZERO
        self._derisk_force_taker_expectancy_taker_fills = 0

        if not bool(getattr(self.config, "derisk_force_taker_expectancy_guard_enabled", False)):
            return True

        fill_history = getattr(self, "_auto_calibration_fill_history", None)
        if fill_history is None:
            self._derisk_force_taker_expectancy_guard_reason = "no_fill_history"
            return True

        window_fills = max(
            1,
            int(getattr(self.config, "derisk_force_taker_expectancy_window_fills", 300)),
        )
        min_taker_fills = max(
            1,
            int(getattr(self.config, "derisk_force_taker_expectancy_min_taker_fills", 40)),
        )

        window = list(fill_history)[-window_fills:]
        taker_rows = [
            row
            for row in window
            if isinstance(row, dict) and not bool(row.get("is_maker", False))
        ]
        taker_nets = [to_decimal(row.get("net_pnl_quote", _ZERO)) for row in taker_rows]
        taker_fills = len(taker_nets)
        self._derisk_force_taker_expectancy_taker_fills = taker_fills

        if taker_fills < min_taker_fills:
            self._derisk_force_taker_expectancy_guard_reason = "insufficient_data"
            return True

        taker_mean_quote = sum(taker_nets, _ZERO) / Decimal(taker_fills)
        self._derisk_force_taker_expectancy_mean_quote = taker_mean_quote

        min_expectancy_quote = to_decimal(
            getattr(self.config, "derisk_force_taker_expectancy_min_quote", Decimal("-0.02"))
        )
        if taker_mean_quote >= min_expectancy_quote:
            self._derisk_force_taker_expectancy_guard_reason = "pass"
            return True

        override_mult = max(
            _ZERO,
            to_decimal(getattr(self.config, "derisk_force_taker_expectancy_override_base_mult", Decimal("10"))),
        )
        if override_mult > _ZERO and min_force_base > _BALANCE_EPSILON:
            override_abs_base = max(min_force_base, min_force_base * override_mult)
            if abs_position_base >= override_abs_base:
                self._derisk_force_taker_expectancy_guard_reason = "override_large_inventory"
                return True

        self._derisk_force_taker_expectancy_guard_blocked = True
        self._derisk_force_taker_expectancy_guard_reason = "negative_taker_expectancy"
        return False

    def _update_derisk_force_mode(self, now_ts: float, derisk_only: bool, rr: set[str]) -> bool:
        self._derisk_force_taker_expectancy_guard_blocked = False
        self._derisk_force_taker_expectancy_guard_reason = "inactive"
        self._derisk_force_taker_expectancy_mean_quote = _ZERO
        self._derisk_force_taker_expectancy_taker_fills = 0

        tracked_rr = bool(rr.intersection(_INVENTORY_DERISK_REASONS))
        if not derisk_only or not tracked_rr:
            self._derisk_cycle_started_ts = 0.0
            self._derisk_cycle_start_abs_base = _ZERO
            self._derisk_force_taker = False
            self._derisk_force_taker_expectancy_guard_reason = "inactive"
            return False

        abs_position_base = abs(self._position_base)
        if abs_position_base <= _BALANCE_EPSILON:
            self._derisk_cycle_started_ts = 0.0
            self._derisk_cycle_start_abs_base = _ZERO
            self._derisk_force_taker = False
            self._derisk_force_taker_expectancy_guard_reason = "flat_position"
            return False
        min_force_base = EppV24Controller._derisk_force_min_base_amount(self)
        if abs_position_base <= min_force_base:
            self._derisk_cycle_started_ts = 0.0
            self._derisk_cycle_start_abs_base = _ZERO
            self._derisk_force_taker = False
            self._derisk_force_taker_expectancy_guard_reason = "below_force_min_base"
            return False

        progress_reset_ratio = _clip(
            to_decimal(self.config.derisk_progress_reset_ratio),
            _ZERO,
            _ONE,
        )
        if self._derisk_cycle_started_ts <= 0 or self._derisk_cycle_start_abs_base <= _ZERO:
            self._derisk_cycle_started_ts = now_ts
            self._derisk_cycle_start_abs_base = abs_position_base
        else:
            progress_ratio = (
                (self._derisk_cycle_start_abs_base - abs_position_base) / self._derisk_cycle_start_abs_base
                if self._derisk_cycle_start_abs_base > _ZERO
                else _ZERO
            )
            if progress_ratio >= progress_reset_ratio:
                self._derisk_cycle_started_ts = now_ts
                self._derisk_cycle_start_abs_base = abs_position_base
                self._derisk_force_taker = False

        force_after_s = float(max(0.0, self.config.derisk_force_taker_after_s))
        if force_after_s <= 0:
            self._derisk_force_taker = False
            self._derisk_force_taker_expectancy_guard_reason = "force_disabled"
            return False

        should_force = (now_ts - self._derisk_cycle_started_ts) >= force_after_s
        if should_force:
            if not EppV24Controller._derisk_force_expectancy_allows(self, abs_position_base, min_force_base):
                should_force = False
                trace_derisk = getattr(self, "_trace_derisk", None)
                if callable(trace_derisk):
                    trace_derisk(
                        now_ts,
                        "force_mode_blocked_expectancy",
                        force=True,
                        abs_position_base=abs_position_base,
                        taker_expectancy_mean_quote=self._derisk_force_taker_expectancy_mean_quote,
                        taker_fills=self._derisk_force_taker_expectancy_taker_fills,
                        guard_reason=self._derisk_force_taker_expectancy_guard_reason,
                    )
        else:
            self._derisk_force_taker_expectancy_guard_reason = "timer_not_elapsed"

        if should_force and not self._derisk_force_taker:
            logger.warning(
                "Derisk force mode enabled after %.0fs without enough progress "
                "(abs_position_base=%s start_abs=%s threshold=%.2f%%)",
                now_ts - self._derisk_cycle_started_ts,
                abs_position_base,
                self._derisk_cycle_start_abs_base,
                float(progress_reset_ratio * _100),
            )
            trace_derisk = getattr(self, "_trace_derisk", None)
            if callable(trace_derisk):
                trace_derisk(
                    now_ts,
                    "force_mode_enabled",
                    force=True,
                    abs_position_base=abs_position_base,
                    cycle_start_abs_base=self._derisk_cycle_start_abs_base,
                    progress_reset_ratio=progress_reset_ratio,
                    force_after_s=force_after_s,
                )
            self._enqueue_force_derisk_executor_cancels()
            self._recently_issued_levels = {}
        self._derisk_force_taker = should_force
        return should_force

    def _enqueue_force_derisk_executor_cancels(self) -> None:
        """Cancel active executors so force-taker entries can be issued immediately."""
        try:
            from hummingbot.strategy_v2.models.executor_actions import StopExecutorAction
        except Exception:
            logger.debug("Unable to import StopExecutorAction for force-derisk", exc_info=True)
            return

        existing = {
            str(getattr(a, "executor_id", ""))
            for a in self._pending_stale_cancel_actions
            if getattr(a, "executor_id", None) is not None
        }
        active_executors = self.filter_executors(
            executors=self.executors_info,
            filter_func=lambda x: bool(getattr(x, "is_active", False)),
        )
        for ex in active_executors:
            ex_id = str(getattr(ex, "id", ""))
            if not ex_id or ex_id in existing:
                continue
            self._pending_stale_cancel_actions.append(
                StopExecutorAction(controller_id=self.config.id, executor_id=ex_id)
            )

    def _trace_derisk(self, now_ts: float, stage: str, force: bool = False, **fields: Any) -> None:
        if not self._derisk_trace_enabled:
            return
        if not force and (now_ts - self._derisk_trace_last_ts) < self._derisk_trace_cooldown_s:
            return
        self._derisk_trace_last_ts = now_ts
        details = " ".join(f"{k}={v}" for k, v in fields.items())
        logger.warning("DERISK_TRACE stage=%s %s", stage, details)

    @staticmethod
    def _auto_calibration_p95(values: List[Decimal]) -> Decimal:
        if not values:
            return _ZERO
        ordered = sorted(values)
        idx = int((len(ordered) - 1) * 0.95)
        return ordered[max(0, min(idx, len(ordered) - 1))]

    def _auto_calibration_report_path(self) -> Path:
        return Path(__file__).resolve().parents[1] / "reports" / "strategy" / "auto_tune_latest.json"

    def _auto_calibration_report_paths(self) -> List[Path]:
        paths = [self._auto_calibration_report_path()]
        try:
            paths.append(Path(self.config.log_dir) / "auto_tune_latest.json")
        except Exception:
            pass
        try:
            paths.append(Path(self._daily_state_path()).parent / "auto_tune_latest.json")
        except Exception:
            pass
        dedup: List[Path] = []
        seen: set[str] = set()
        for p in paths:
            key = str(p)
            if key in seen:
                continue
            seen.add(key)
            dedup.append(p)
        return dedup

    def _auto_calibration_write_report(self, payload: Dict[str, Any]) -> None:
        try:
            blob = json.dumps(payload, indent=2, default=str)
            for path in self._auto_calibration_report_paths():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(blob, encoding="utf-8")
            self._auto_calibration_last_report_ts = float(self.market_data_provider.time())
        except Exception:
            logger.debug("auto_calibration report write failed", exc_info=True)

    def _auto_calibration_record_minute(
        self,
        now_ts: float,
        state: GuardState,
        risk_reasons: List[str],
        snapshot: Dict[str, Any],
        daily_loss_pct: Decimal,
        drawdown_pct: Decimal,
    ) -> None:
        self._auto_calibration_minute_history.append(
            {
                "ts": now_ts,
                "state": str(getattr(state, "value", state)),
                "risk_reasons": list(risk_reasons),
                "edge_gate_blocked": bool(snapshot.get("edge_gate_blocked", False)),
                "orders_active": int(to_decimal(snapshot.get("orders_active", _ZERO))),
                "order_book_stale": bool(snapshot.get("order_book_stale", False)),
                "net_edge_pct": to_decimal(self.processed_data.get("net_edge_pct", _ZERO)),
                "net_edge_gate_pct": to_decimal(self.processed_data.get("net_edge_gate_pct", _ZERO)),
                "daily_loss_pct": to_decimal(daily_loss_pct),
                "drawdown_pct": to_decimal(drawdown_pct),
            }
        )

    def _auto_calibration_record_fill(
        self,
        now_ts: float,
        notional_quote: Decimal,
        fee_quote: Decimal,
        realized_pnl_quote: Decimal,
        slippage_bps: Decimal,
        is_maker: bool,
        fill_edge_bps: Decimal = _ZERO,
    ) -> None:
        net_pnl_quote = realized_pnl_quote - fee_quote
        self._auto_calibration_fill_history.append(
            {
                "ts": now_ts,
                "notional_quote": max(_ZERO, to_decimal(notional_quote)),
                "fee_quote": max(_ZERO, to_decimal(fee_quote)),
                "realized_pnl_quote": to_decimal(realized_pnl_quote),
                "net_pnl_quote": to_decimal(net_pnl_quote),
                "slippage_bps": to_decimal(slippage_bps),
                "fill_edge_bps": to_decimal(fill_edge_bps),
                "is_maker": bool(is_maker),
            }
        )

    def _auto_calibration_maybe_run(
        self,
        now_ts: float,
        state: GuardState,
        risk_reasons: List[str],
        daily_loss_pct: Decimal,
        drawdown_pct: Decimal,
    ) -> None:
        if not self.config.auto_calibration_enabled:
            return
        interval_s = float(max(60, int(self.config.auto_calibration_update_interval_s)))
        if (now_ts - self._auto_calibration_last_eval_ts) < interval_s:
            return
        self._auto_calibration_last_eval_ts = now_ts

        lookback_s = float(max(300, int(self.config.auto_calibration_lookback_s)))
        window_start = now_ts - lookback_s
        minutes = [m for m in self._auto_calibration_minute_history if float(m.get("ts", 0.0)) >= window_start]
        fills = [f for f in self._auto_calibration_fill_history if float(f.get("ts", 0.0)) >= window_start]
        rows = max(1, len(minutes))

        edge_gate_blocked_ratio = Decimal(sum(1 for m in minutes if bool(m.get("edge_gate_blocked", False)))) / Decimal(rows)
        orders_active_ratio = Decimal(sum(1 for m in minutes if int(m.get("orders_active", 0)) > 0)) / Decimal(rows)
        stale_ratio = Decimal(sum(1 for m in minutes if bool(m.get("order_book_stale", False)))) / Decimal(rows)
        fills_count = len(fills)
        taker_ratio = (
            Decimal(sum(1 for f in fills if not bool(f.get("is_maker", False)))) / Decimal(fills_count)
            if fills_count > 0 else _ZERO
        )
        notional_total = sum((to_decimal(f.get("notional_quote", _ZERO)) for f in fills), _ZERO)
        net_pnl_total = sum((to_decimal(f.get("net_pnl_quote", _ZERO)) for f in fills), _ZERO)
        net_pnl_bps = (net_pnl_total / notional_total * _10K) if notional_total > _ZERO else _ZERO
        slippage_p95_bps = self._auto_calibration_p95([to_decimal(f.get("slippage_bps", _ZERO)) for f in fills])

        freeze_reasons: List[str] = []
        if to_decimal(drawdown_pct) >= to_decimal(self.config.auto_calibration_freeze_drawdown_pct):
            freeze_reasons.append("drawdown_cap")
        if to_decimal(daily_loss_pct) >= to_decimal(self.config.auto_calibration_freeze_daily_loss_pct):
            freeze_reasons.append("daily_loss_cap")
        if stale_ratio > to_decimal(self.config.auto_calibration_freeze_order_book_stale_ratio_gt):
            freeze_reasons.append("order_book_stale_ratio")
        if self._external_soft_pause:
            freeze_reasons.append("external_guard")
        if state == GuardState.HARD_STOP:
            freeze_reasons.append("hard_stop")

        relax_signal = (
            fills_count < int(self.config.auto_calibration_relax_fills_lt)
            and edge_gate_blocked_ratio > to_decimal(self.config.auto_calibration_relax_edge_gate_blocked_ratio_gt)
            and orders_active_ratio < to_decimal(self.config.auto_calibration_relax_orders_active_ratio_lt)
            and stale_ratio < to_decimal(self.config.auto_calibration_relax_order_book_stale_ratio_lt)
        )
        tighten_signal = (
            (fills_count > 0 and slippage_p95_bps > to_decimal(self.config.auto_calibration_tighten_slippage_p95_bps_gt))
            or (fills_count > 0 and net_pnl_bps < to_decimal(self.config.auto_calibration_tighten_net_pnl_bps_lt))
            or (
                fills_count > 0
                and taker_ratio > to_decimal(self.config.auto_calibration_tighten_taker_ratio_gt)
                and net_pnl_bps < _ZERO
            )
        )

        if fills_count > 0 and net_pnl_bps < _ZERO:
            self._auto_calibration_negative_window_streak += 1
        elif fills_count > 0:
            self._auto_calibration_negative_window_streak = 0

        if relax_signal:
            self._auto_calibration_relax_signal_streak += 1
        else:
            self._auto_calibration_relax_signal_streak = 0

        decision = "hold"
        direction = _ZERO
        if freeze_reasons:
            decision = "freeze"
        elif tighten_signal:
            decision = "tighten"
            direction = _ONE
            self._auto_calibration_relax_signal_streak = 0
        elif relax_signal and self._auto_calibration_relax_signal_streak >= int(self.config.auto_calibration_required_consecutive_relax_cycles):
            decision = "relax"
            direction = Decimal("-1")

        max_hourly = max(_ZERO, to_decimal(self.config.auto_calibration_max_total_change_per_hour_bps))
        while self._auto_calibration_change_events and (now_ts - float(self._auto_calibration_change_events[0][0])) > 3600:
            self._auto_calibration_change_events.popleft()
        used_hourly = sum((to_decimal(v[1]) for v in self._auto_calibration_change_events), _ZERO)
        remaining_hourly = max(_ZERO, max_hourly - used_hourly)
        step_bps = max(_ZERO, to_decimal(self.config.auto_calibration_max_step_bps))
        step_bps = min(step_bps, remaining_hourly / Decimal("3") if remaining_hourly > _ZERO else _ZERO)

        old_min_edge = to_decimal(self.config.min_net_edge_bps)
        old_resume = to_decimal(self.config.edge_resume_bps)
        old_side_floor = to_decimal(self.config.min_side_spread_bps)
        new_min_edge = old_min_edge
        new_resume = old_resume
        new_side_floor = old_side_floor

        if decision in {"relax", "tighten"} and step_bps > _ZERO:
            new_min_edge = _clip(
                old_min_edge + (direction * step_bps),
                to_decimal(self.config.auto_calibration_min_net_edge_bps_min),
                to_decimal(self.config.auto_calibration_min_net_edge_bps_max),
            )
            new_resume = _clip(
                old_resume + (direction * step_bps),
                to_decimal(self.config.auto_calibration_edge_resume_bps_min),
                to_decimal(self.config.auto_calibration_edge_resume_bps_max),
            )
            new_side_floor = _clip(
                old_side_floor + (direction * step_bps),
                to_decimal(self.config.auto_calibration_min_side_spread_bps_min),
                to_decimal(self.config.auto_calibration_min_side_spread_bps_max),
            )

        change_abs = abs(new_min_edge - old_min_edge) + abs(new_resume - old_resume) + abs(new_side_floor - old_side_floor)
        applied = False
        shadow = bool(self.config.auto_calibration_shadow_mode)
        rollback_applied = False

        if decision in {"relax", "tighten"} and change_abs <= _ZERO:
            decision = "hold_no_budget_or_bound"
        elif decision in {"relax", "tighten"}:
            if shadow:
                decision = f"{decision}_shadow"
            else:
                self.config.min_net_edge_bps = new_min_edge
                self.config.edge_resume_bps = new_resume
                self.config.min_side_spread_bps = new_side_floor
                self._spread_engine._min_net_edge_bps = new_min_edge
                self._spread_engine._edge_resume_bps = new_resume
                self._auto_calibration_change_events.append((now_ts, change_abs))
                self._auto_calibration_applied_changes.append(
                    {
                        "ts": now_ts,
                        "prev": {
                            "min_net_edge_bps": str(old_min_edge),
                            "edge_resume_bps": str(old_resume),
                            "min_side_spread_bps": str(old_side_floor),
                        },
                        "new": {
                            "min_net_edge_bps": str(new_min_edge),
                            "edge_resume_bps": str(new_resume),
                            "min_side_spread_bps": str(new_side_floor),
                        },
                    }
                )
                applied = True
                logger.warning(
                    "AUTO_TUNE applied decision=%s min_net_edge_bps=%s edge_resume_bps=%s min_side_spread_bps=%s",
                    decision, str(new_min_edge), str(new_resume), str(new_side_floor),
                )

        if (
            self.config.auto_calibration_rollback_enabled
            and not shadow
            and self._auto_calibration_negative_window_streak >= int(self.config.auto_calibration_rollback_negative_windows)
            and len(self._auto_calibration_applied_changes) > 0
        ):
            last = self._auto_calibration_applied_changes.pop()
            prev = last.get("prev", {})
            rb_min_edge = to_decimal(prev.get("min_net_edge_bps", self.config.min_net_edge_bps))
            rb_resume = to_decimal(prev.get("edge_resume_bps", self.config.edge_resume_bps))
            rb_side_floor = to_decimal(prev.get("min_side_spread_bps", self.config.min_side_spread_bps))
            rb_change = (
                abs(to_decimal(self.config.min_net_edge_bps) - rb_min_edge)
                + abs(to_decimal(self.config.edge_resume_bps) - rb_resume)
                + abs(to_decimal(self.config.min_side_spread_bps) - rb_side_floor)
            )
            self.config.min_net_edge_bps = rb_min_edge
            self.config.edge_resume_bps = rb_resume
            self.config.min_side_spread_bps = rb_side_floor
            self._spread_engine._min_net_edge_bps = rb_min_edge
            self._spread_engine._edge_resume_bps = rb_resume
            self._auto_calibration_change_events.append((now_ts, rb_change))
            self._auto_calibration_negative_window_streak = 0
            rollback_applied = True
            decision = "rollback"
            logger.warning(
                "AUTO_TUNE rollback applied min_net_edge_bps=%s edge_resume_bps=%s min_side_spread_bps=%s",
                str(rb_min_edge), str(rb_resume), str(rb_side_floor),
            )

        self._auto_calibration_last_decision = decision
        report = {
            "ts_utc": datetime.fromtimestamp(now_ts, tz=timezone.utc).isoformat(),
            "enabled": bool(self.config.auto_calibration_enabled),
            "shadow_mode": shadow,
            "decision": decision,
            "applied": applied,
            "rollback_applied": rollback_applied,
            "freeze_reasons": freeze_reasons,
            "metrics": {
                "lookback_s": int(lookback_s),
                "minute_rows": len(minutes),
                "fills": fills_count,
                "edge_gate_blocked_ratio": float(edge_gate_blocked_ratio),
                "orders_active_ratio": float(orders_active_ratio),
                "order_book_stale_ratio": float(stale_ratio),
                "taker_ratio": float(taker_ratio),
                "slippage_p95_bps": float(slippage_p95_bps),
                "net_pnl_bps": float(net_pnl_bps),
                "net_pnl_quote": float(net_pnl_total),
                "negative_window_streak": self._auto_calibration_negative_window_streak,
                "relax_signal_streak": self._auto_calibration_relax_signal_streak,
            },
            "knobs_before": {
                "min_net_edge_bps": str(old_min_edge),
                "edge_resume_bps": str(old_resume),
                "min_side_spread_bps": str(old_side_floor),
            },
            "knobs_after": {
                "min_net_edge_bps": str(to_decimal(self.config.min_net_edge_bps)),
                "edge_resume_bps": str(to_decimal(self.config.edge_resume_bps)),
                "min_side_spread_bps": str(to_decimal(self.config.min_side_spread_bps)),
            },
            "limits": {
                "max_step_bps": str(to_decimal(self.config.auto_calibration_max_step_bps)),
                "remaining_hourly_budget_bps": str(max(_ZERO, remaining_hourly)),
            },
        }
        self._auto_calibration_write_report(report)

    def _get_telemetry_redis(self) -> Optional[Any]:
        """Lazy-init a shared Redis client for fill telemetry. Never raises."""
        if self._telemetry_redis_init_done:
            return self._telemetry_redis
        self._telemetry_redis_init_done = True
        try:
            import redis as _redis_lib
            host = os.environ.get("REDIS_HOST", "")
            if not host:
                return None
            self._telemetry_redis = _redis_lib.Redis(
                host=host,
                port=int(os.environ.get("REDIS_PORT", "6379")),
                db=int(os.environ.get("REDIS_DB", "0")),
                password=os.environ.get("REDIS_PASSWORD") or None,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
                socket_keepalive=True,
            )
        except Exception:
            logger.debug("Telemetry Redis init failed", exc_info=True)
        return self._telemetry_redis

    def _publish_bot_minute_snapshot_telemetry(self, event_ts: str, minute_row: Optional[Dict[str, Any]]) -> None:
        """Publish a compact per-minute runtime snapshot to the shared telemetry stream."""
        if not isinstance(minute_row, dict) or not minute_row:
            return
        try:
            import json as _json_tel
            import uuid as _uuid_mod
            from datetime import datetime as _dt, timezone as _tz
            from pathlib import Path as _Path
            from services.contracts.event_identity import validate_event_identity as _validate_event_identity
            from services.contracts.stream_names import BOT_TELEMETRY_STREAM
            runtime_compat = _runtime_compat_surface(self)

            payload = {
                "event_type": "bot_minute_snapshot",
                "event_version": "v1",
                "schema_version": "1.0",
                "ts_utc": event_ts,
                "producer": f"{runtime_compat.telemetry_producer_prefix}.{self.config.instance_name}",
                "instance_name": self.config.instance_name,
                "controller_id": str(getattr(self, "id", "") or ""),
                "connector_name": self.config.connector_name,
                "trading_pair": self.config.trading_pair,
                "state": str(minute_row.get("state", "")),
                "regime": str(minute_row.get("regime", "")),
                "mid_price": float(to_decimal(minute_row.get("mid", _ZERO))),
                "equity_quote": float(to_decimal(minute_row.get("equity_quote", _ZERO))),
                "base_pct": float(to_decimal(minute_row.get("base_pct", _ZERO))),
                "target_base_pct": float(to_decimal(minute_row.get("target_base_pct", _ZERO))),
                "spread_pct": float(to_decimal(minute_row.get("spread_pct", _ZERO))),
                "net_edge_pct": float(to_decimal(minute_row.get("net_edge_pct", _ZERO))),
                "turnover_x": float(to_decimal(minute_row.get("turnover_today_x", _ZERO))),
                "daily_loss_pct": float(to_decimal(minute_row.get("daily_loss_pct", _ZERO))),
                "drawdown_pct": float(to_decimal(minute_row.get("drawdown_pct", _ZERO))),
                "fills_count_today": int(minute_row.get("fills_count_today", 0) or 0),
                "fees_paid_today_quote": float(to_decimal(minute_row.get("fees_paid_today_quote", _ZERO))),
                "fee_source": str(minute_row.get("fee_source", "")),
                "maker_fee_pct": float(to_decimal(minute_row.get("maker_fee_pct", _ZERO))),
                "taker_fee_pct": float(to_decimal(minute_row.get("taker_fee_pct", _ZERO))),
                "risk_reasons": str(minute_row.get("risk_reasons", "")),
                "metadata": {
                    "bot_mode": str(minute_row.get("bot_mode", "")),
                    "accounting_source": str(minute_row.get("accounting_source", "")),
                    "variant": str(minute_row.get("bot_variant", "")),
                    "quote_side_mode": str(minute_row.get("quote_side_mode", "off")),
                    "quote_side_reason": str(minute_row.get("quote_side_reason", "unknown")),
                    "alpha_policy_state": str(minute_row.get("alpha_policy_state", "unknown")),
                    "alpha_policy_reason": str(minute_row.get("alpha_policy_reason", "unknown")),
                    "projected_total_quote": str(minute_row.get("projected_total_quote", "0")),
                    "soft_pause_edge": str(minute_row.get("soft_pause_edge", "False")),
                    "orders_active": str(minute_row.get("orders_active", "0")),
                    **runtime_metadata(runtime_compat),
                },
            }
            identity_ok, identity_reason = _validate_event_identity(payload)
            if not identity_ok:
                logger.warning("Minute snapshot telemetry dropped due to identity contract: %s", identity_reason)
                return
            redis_published = False
            try:
                _r = self._get_telemetry_redis()
                if _r is not None:
                    _r.xadd(BOT_TELEMETRY_STREAM, {"payload": _json_tel.dumps(payload)}, maxlen=100_000, approximate=True)
                    redis_published = True
            except Exception:
                logger.debug("Minute snapshot telemetry Redis publish failed", exc_info=True)

            if not redis_published:
                if _Path("/.dockerenv").exists():
                    root = _Path("/workspace/hbot")
                else:
                    try:
                        import controllers.epp_v2_4 as _legacy_runtime_module

                        root = _Path(_legacy_runtime_module.__file__).resolve().parents[1]
                    except Exception:
                        root = _Path(__file__).resolve().parents[1]
                out_dir = root / "reports" / "event_store"
                out_dir.mkdir(parents=True, exist_ok=True)
                out_path = out_dir / f"events_{_dt.now(_tz.utc).strftime('%Y%m%d')}.jsonl"
                envelope = {
                    "event_id": str(_uuid_mod.uuid4()),
                    "event_type": "bot_minute_snapshot",
                    "event_version": "v1",
                    "ts_utc": event_ts,
                    "producer": payload["producer"],
                    "instance_name": payload["instance_name"],
                    "controller_id": payload["controller_id"],
                    "connector_name": payload["connector_name"],
                    "trading_pair": payload["trading_pair"],
                    "correlation_id": str(_uuid_mod.uuid4()),
                    "stream": "local.epp_v2_4.minute_snapshot_fallback",
                    "stream_entry_id": "",
                    "payload": payload,
                    "ingest_ts_utc": _dt.now(_tz.utc).isoformat(),
                    "schema_validation_status": "ok",
                }
                with out_path.open("a", encoding="utf-8") as handle:
                    handle.write(_json_tel.dumps(envelope, ensure_ascii=True) + "\n")
        except Exception:
            logger.debug("Minute snapshot telemetry publish failed", exc_info=True)

    @staticmethod
    def _is_excluded_fill_for_risk_accounting(order_id: object) -> bool:
        """Return True when a fill should be ignored for strategy accounting.

        Probe orders are synthetic verification artifacts and can be emitted in the
        same stream as strategy fills. They must not mutate runtime strategy state
        (turnover, fill-risk, position, realized PnL, adaptive fill-age), otherwise
        they can trigger false derisk/rebalance cascades.
        """
        oid = str(order_id or "").strip().lower()
        return oid.startswith("probe-ord-")

    @staticmethod
    def _normalize_fill_key_ts(value: object) -> str:
        """Normalize fill timestamp into a stable event-key component."""
        if value is None:
            return ""
        try:
            return f"{float(value):.6f}"
        except Exception:
            pass
        raw = str(value or "").strip()
        if not raw:
            return ""
        try:
            return f"{datetime.fromisoformat(raw.replace('Z', '+00:00')).timestamp():.6f}"
        except Exception:
            return raw

    @staticmethod
    def _normalize_fill_key_decimal(value: object) -> str:
        """Normalize numeric fill fields so row/event keys match reliably."""
        try:
            dec = to_decimal(value).normalize()
            return format(dec, "f")
        except Exception:
            return str(value or "").strip()

    @staticmethod
    def _fill_event_dedupe_key(event: object) -> str:
        """Build replay-safe dedupe key for a fill event."""
        order_id = str(getattr(event, "order_id", "") or "").strip()
        for attr in ("exchange_trade_id", "trade_id", "fill_id", "trade_fill_id"):
            trade_id = str(getattr(event, attr, "") or "").strip()
            if trade_id:
                return f"trade:{trade_id}"
        ts_key = EppV24Controller._normalize_fill_key_ts(getattr(event, "timestamp", None))
        side = str(getattr(getattr(event, "trade_type", None), "name", "") or "").strip().lower()
        price = EppV24Controller._normalize_fill_key_decimal(getattr(event, "price", ""))
        amount = EppV24Controller._normalize_fill_key_decimal(getattr(event, "amount", ""))
        if not (order_id or ts_key):
            return ""
        return f"legacy:{order_id}|{ts_key}|{side}|{price}|{amount}"

    @staticmethod
    def _fill_row_dedupe_key(row: Dict[str, object]) -> str:
        """Build dedupe key from a fills.csv row for warm-restart hydration."""
        for key in ("exchange_trade_id", "trade_id", "fill_id", "trade_fill_id"):
            trade_id = str(row.get(key, "") or "").strip()
            if trade_id:
                return f"trade:{trade_id}"
        order_id = str(row.get("order_id", "") or "").strip()
        ts_key = EppV24Controller._normalize_fill_key_ts(row.get("ts"))
        side = str(row.get("side", "") or "").strip().lower()
        price = EppV24Controller._normalize_fill_key_decimal(row.get("price", ""))
        amount = EppV24Controller._normalize_fill_key_decimal(row.get("amount_base", ""))
        if not (order_id or ts_key):
            return ""
        return f"legacy:{order_id}|{ts_key}|{side}|{price}|{amount}"

    @staticmethod
    def _record_fill_event_key(self: Any, event_key: str) -> bool:
        """Register fill key; return False when event was already seen."""
        key = str(event_key or "").strip()
        if not key:
            return True
        seen = getattr(self, "_seen_fill_event_keys", None)
        if not isinstance(seen, set):
            seen = set()
            setattr(self, "_seen_fill_event_keys", seen)
        fifo = getattr(self, "_seen_fill_event_keys_fifo", None)
        if not isinstance(fifo, deque):
            fifo = deque()
            setattr(self, "_seen_fill_event_keys_fifo", fifo)
        cap = int(getattr(self, "_seen_fill_event_keys_cap", 120_000) or 120_000)
        cap = max(1_000, cap)
        if key in seen:
            return False
        seen.add(key)
        fifo.append(key)
        while len(fifo) > cap:
            evicted = fifo.popleft()
            seen.discard(evicted)
        return True

    @staticmethod
    def _record_seen_fill_order_id(self: Any, order_id: object) -> None:
        """Track order IDs for diagnostics and restart cache hydration."""
        oid = str(order_id or "").strip()
        if not oid:
            return
        seen = getattr(self, "_seen_fill_order_ids", None)
        if not isinstance(seen, set):
            seen = set()
            setattr(self, "_seen_fill_order_ids", seen)
        fifo = getattr(self, "_seen_fill_order_ids_fifo", None)
        if not isinstance(fifo, deque):
            fifo = deque()
            setattr(self, "_seen_fill_order_ids_fifo", fifo)
        cap = int(getattr(self, "_seen_fill_order_ids_cap", 50_000) or 50_000)
        cap = max(1_000, cap)
        if oid in seen:
            return
        seen.add(oid)
        fifo.append(oid)
        while len(fifo) > cap:
            evicted = fifo.popleft()
            seen.discard(evicted)

    def did_fill_order(self, event: OrderFilledEvent):
        event_instance_name = _identity_text(getattr(event, "instance_name", ""))
        controller_instance_name = _identity_text(getattr(self.config, "instance_name", ""))
        if event_instance_name and controller_instance_name and event_instance_name.lower() != controller_instance_name.lower():
            logger.warning(
                "Ignoring foreign fill event order_id=%s event_instance=%s controller_instance=%s",
                str(getattr(event, "order_id", "") or ""),
                event_instance_name,
                controller_instance_name,
            )
            return
        notional = to_decimal(event.amount) * to_decimal(event.price)
        order_id = str(getattr(event, "order_id", "") or "")
        fill_event_key = EppV24Controller._fill_event_dedupe_key(event)
        if not EppV24Controller._record_fill_event_key(self, fill_event_key):
            logger.debug("Skipping duplicate fill event order_id=%s key=%s", order_id, fill_event_key)
            return
        EppV24Controller._record_seen_fill_order_id(self, order_id)
        excluded_from_risk_accounting = EppV24Controller._is_excluded_fill_for_risk_accounting(order_id)
        if not excluded_from_risk_accounting:
            try:
                ts = getattr(event, "timestamp", None)
                if ts is not None:
                    self._last_fill_ts = float(ts)
                else:
                    self._last_fill_ts = float(self.market_data_provider.time())
            except Exception:
                self._last_fill_ts = float(self.market_data_provider.time())
        if not excluded_from_risk_accounting:
            self._traded_notional_today += notional
            self._fills_count_today += 1
        fee_quote = Decimal("0")
        quote_asset = self.config.trading_pair.split("-")[1]
        try:
            fee_quote = to_decimal(event.trade_fee.fee_amount_in_token(quote_asset, event.price, event.amount))
        except Exception:
            fee_quote = notional * self._taker_fee_pct
            logger.warning("Fee extraction failed for order %s, using estimate %.6f", order_id, fee_quote)
        if not excluded_from_risk_accounting:
            self._fees_paid_today_quote += fee_quote

        # Paper-trade skepticism: warn if effective fee rate deviates wildly from the
        # configured fee schedule (usually indicates wrong venue key / profile lookup).
        if (
            _config_is_paper(self.config)
            and not self._fee_rate_mismatch_warned_today
            and self._fills_count_today >= 10
            and self._traded_notional_today > _ZERO
        ):
            eff = self._fees_paid_today_quote / self._traded_notional_today
            expected_hi = max(self._maker_fee_pct, self._taker_fee_pct)
            expected_lo = min(self._maker_fee_pct, self._taker_fee_pct)
            # Warn when effective fee rate is 2.5× too high (over-billing) OR
            # 10× too low (near-zero fees → paper PnL looks unrealistically good).
            if expected_hi > _ZERO and eff > expected_hi * Decimal("2.5"):
                logger.warning(
                    "Effective fee_rate %.4fbps is OVER configured maker/taker %.4f/%.4fbps (source=%s). "
                    "Paper stats may be misleading until fee model is reconciled.",
                    float(eff * Decimal("10000")),
                    float(self._maker_fee_pct * Decimal("10000")),
                    float(self._taker_fee_pct * Decimal("10000")),
                    self._fee_source,
                )
                self._fee_rate_mismatch_warned_today = True
            elif expected_lo > _ZERO and eff < expected_lo * Decimal("0.1"):
                logger.warning(
                    "Effective fee_rate %.4fbps is UNDER configured maker/taker %.4f/%.4fbps (source=%s). "
                    "Paper engine may be using near-zero fees — live performance will be worse.",
                    float(eff * Decimal("10000")),
                    float(self._maker_fee_pct * Decimal("10000")),
                    float(self._taker_fee_pct * Decimal("10000")),
                    self._fee_source,
                )
                self._fee_rate_mismatch_warned_today = True
        expected_spread = to_decimal(self.processed_data.get("spread_pct", Decimal("0")))
        mid_ref = to_decimal(self.processed_data.get("mid", event.price))
        adverse_ref = to_decimal(self.processed_data.get("adverse_drift_30s", Decimal("0")))
        fill_price = to_decimal(event.price)
        is_maker = None
        try:
            trade_fee_is_maker = getattr(event.trade_fee, "is_maker", None)
            if trade_fee_is_maker is not None:
                is_maker = bool(trade_fee_is_maker)
        except Exception:
            logger.debug("is_maker extraction failed for order %s", order_id, exc_info=True)
        if is_maker is None:
            event_is_maker = getattr(event, "is_maker", None)
            if isinstance(event_is_maker, bool):
                is_maker = event_is_maker
            elif event_is_maker is not None:
                marker = str(event_is_maker).strip().lower()
                if marker in {"1", "true", "yes", "y", "on"}:
                    is_maker = True
                elif marker in {"0", "false", "no", "n", "off"}:
                    is_maker = False
        if is_maker is None and notional > _ZERO and fee_quote > _ZERO:
            maker_fee_pct = max(_ZERO, to_decimal(getattr(self, "_maker_fee_pct", _ZERO)))
            taker_fee_pct = max(_ZERO, to_decimal(getattr(self, "_taker_fee_pct", _ZERO)))
            if maker_fee_pct > _ZERO or taker_fee_pct > _ZERO:
                fee_rate_pct = abs(fee_quote / notional)
                maker_gap = abs(fee_rate_pct - maker_fee_pct)
                taker_gap = abs(fee_rate_pct - taker_fee_pct)
                if maker_gap < taker_gap:
                    is_maker = True
                elif taker_gap < maker_gap:
                    is_maker = False
        if is_maker is None:
            is_maker = False
            if event.trade_type.name.lower() == "buy" and fill_price < mid_ref:
                is_maker = True
            elif event.trade_type.name.lower() == "sell" and fill_price > mid_ref:
                is_maker = True

        realized_pnl = _ZERO
        if not excluded_from_risk_accounting:
            fill_amount = to_decimal(event.amount)
            fill_position_action = str(getattr(event, "position_action", "auto") or "auto").strip().lower()
            position_mode = str(getattr(self.config, "position_mode", "ONEWAY") or "ONEWAY").upper()
            if "HEDGE" not in position_mode:
                # In one-way mode, opposite fills must net position; explicit
                # leg hints are hedge-mode semantics.
                fill_position_action = "auto"
            if fill_position_action in {"open_long", "close_long", "open_short", "close_short"}:
                if fill_position_action == "open_long":
                    new_qty = self._position_long_base + fill_amount
                    if new_qty > _ZERO:
                        old_cost = self._avg_entry_price_long * self._position_long_base
                        new_cost = fill_price * fill_amount
                        self._avg_entry_price_long = (old_cost + new_cost) / new_qty
                    self._position_long_base = new_qty
                elif fill_position_action == "close_long":
                    close_amount = min(fill_amount, self._position_long_base)
                    fee_portion = fee_quote * close_amount / fill_amount if fill_amount > _ZERO else fee_quote
                    if close_amount > _ZERO and self._avg_entry_price_long > _ZERO:
                        realized_pnl = (fill_price - self._avg_entry_price_long) * close_amount - fee_portion
                    self._position_long_base = max(_ZERO, self._position_long_base - fill_amount)
                    if self._position_long_base <= _BALANCE_EPSILON:
                        self._avg_entry_price_long = _ZERO
                elif fill_position_action == "open_short":
                    new_qty = self._position_short_base + fill_amount
                    if new_qty > _ZERO:
                        old_cost = self._avg_entry_price_short * self._position_short_base
                        new_cost = fill_price * fill_amount
                        self._avg_entry_price_short = (old_cost + new_cost) / new_qty
                    self._position_short_base = new_qty
                elif fill_position_action == "close_short":
                    close_amount = min(fill_amount, self._position_short_base)
                    fee_portion = fee_quote * close_amount / fill_amount if fill_amount > _ZERO else fee_quote
                    if close_amount > _ZERO and self._avg_entry_price_short > _ZERO:
                        realized_pnl = (self._avg_entry_price_short - fill_price) * close_amount - fee_portion
                    self._position_short_base = max(_ZERO, self._position_short_base - fill_amount)
                    if self._position_short_base <= _BALANCE_EPSILON:
                        self._avg_entry_price_short = _ZERO
            else:
                if event.trade_type.name.lower() == "buy":
                    if self._position_base < _ZERO and self._avg_entry_price > _ZERO:
                        close_amount = min(fill_amount, abs(self._position_base))
                        fee_portion = fee_quote * close_amount / fill_amount if fill_amount > _ZERO else fee_quote
                        realized_pnl = (self._avg_entry_price - fill_price) * close_amount - fee_portion
                    new_pos = self._position_base + fill_amount
                    if new_pos > _ZERO and fill_amount > _ZERO:
                        existing_long = max(_ZERO, self._position_base)
                        opening_amount = new_pos - existing_long
                        old_cost = self._avg_entry_price * existing_long
                        new_cost = fill_price * opening_amount
                        self._avg_entry_price = (old_cost + new_cost) / new_pos if new_pos > _ZERO else fill_price
                    self._position_base = new_pos
                else:
                    if self._position_base > _ZERO and self._avg_entry_price > _ZERO:
                        close_amount = min(fill_amount, self._position_base)
                        fee_portion = fee_quote * close_amount / fill_amount if fill_amount > _ZERO else fee_quote
                        realized_pnl = (fill_price - self._avg_entry_price) * close_amount - fee_portion
                    new_pos = self._position_base - fill_amount
                    if new_pos < _ZERO and fill_amount > _ZERO:
                        existing_short = max(_ZERO, -self._position_base)
                        opening_amount = abs(new_pos) - existing_short
                        old_cost = self._avg_entry_price * existing_short
                        new_cost = fill_price * opening_amount
                        self._avg_entry_price = (old_cost + new_cost) / abs(new_pos) if abs(new_pos) > _ZERO else fill_price
                    self._position_base = new_pos
                if self._position_base > _ZERO:
                    self._position_long_base = self._position_base
                    self._avg_entry_price_long = self._avg_entry_price
                    self._position_short_base = _ZERO
                    self._avg_entry_price_short = _ZERO
                elif self._position_base < _ZERO:
                    self._position_short_base = abs(self._position_base)
                    self._avg_entry_price_short = self._avg_entry_price
                    self._position_long_base = _ZERO
                    self._avg_entry_price_long = _ZERO
                else:
                    self._position_long_base = _ZERO
                    self._position_short_base = _ZERO
                    self._avg_entry_price_long = _ZERO
                    self._avg_entry_price_short = _ZERO
                    self._avg_entry_price = _ZERO
            self._position_base = self._position_long_base - self._position_short_base
            self._position_gross_base = self._position_long_base + self._position_short_base
            if self._position_base > _ZERO:
                self._avg_entry_price = self._avg_entry_price_long
            elif self._position_base < _ZERO:
                self._avg_entry_price = self._avg_entry_price_short
            elif self._position_gross_base <= _BALANCE_EPSILON:
                self._avg_entry_price = _ZERO
            self._realized_pnl_today += realized_pnl

        # Fill-edge EWMA for auto-widen (P1-2) and Kelly variance tracking (ROAD-4).
        if mid_ref > _ZERO and not excluded_from_risk_accounting:
            side_sign = Decimal("-1") if event.trade_type.name.lower() == "buy" else _ONE
            fill_edge_bps = (fill_price - mid_ref) * side_sign / mid_ref * _10K
            _alpha = Decimal("0.05")
            if self._fill_edge_ewma is None:
                self._fill_edge_ewma = fill_edge_bps
                self._fill_edge_variance = fill_edge_bps ** 2
            else:
                prev_ewma = self._fill_edge_ewma
                self._fill_edge_ewma = _alpha * fill_edge_bps + (_ONE - _alpha) * prev_ewma
                deviation_sq = (fill_edge_bps - prev_ewma) ** 2
                if self._fill_edge_variance is None:
                    self._fill_edge_variance = deviation_sq
                else:
                    self._fill_edge_variance = _alpha * deviation_sq + (_ONE - _alpha) * self._fill_edge_variance
            self._fill_count_for_kelly += 1
            cost_floor_bps = (self._maker_fee_pct + self.config.slippage_est_pct) * _10K
            if self._fill_edge_ewma < -cost_floor_bps:
                self._adverse_fill_count += 1
            elif self._fill_edge_ewma >= -cost_floor_bps * Decimal("0.5"):
                self._adverse_fill_count = 0

        if mid_ref > _ZERO:
            price_deviation_pct = abs(fill_price - mid_ref) / mid_ref
            if price_deviation_pct > Decimal("0.01"):
                logger.warning("Fill price deviation %.4f%% for order %s (fill=%.2f mid=%.2f)",
                               float(price_deviation_pct * _100), order_id, float(fill_price), float(mid_ref))

        slippage_bps = _ZERO
        if mid_ref > _ZERO:
            if event.trade_type.name.lower() == "buy":
                slippage_bps = (fill_price - mid_ref) / mid_ref * _10K
            else:
                slippage_bps = (mid_ref - fill_price) / mid_ref * _10K
        auto_calibration_record_fill = getattr(self, "_auto_calibration_record_fill", None)
        if callable(auto_calibration_record_fill) and not excluded_from_risk_accounting:
            auto_calibration_record_fill(
                now_ts=float(event.timestamp),
                notional_quote=notional,
                fee_quote=fee_quote,
                realized_pnl_quote=realized_pnl,
                slippage_bps=slippage_bps,
                fill_edge_bps=fill_edge_bps if mid_ref > _ZERO else _ZERO,
                is_maker=bool(is_maker),
            )

        event_ts = datetime.fromtimestamp(event.timestamp, tz=timezone.utc).isoformat()
        self._csv.log_fill(
            {
                "bot_variant": self.config.variant,
                "exchange": self.config.connector_name,
                "trading_pair": self.config.trading_pair,
                "side": event.trade_type.name.lower(),
                "price": str(event.price),
                "amount_base": str(event.amount),
                "notional_quote": str(notional),
                "fee_quote": str(fee_quote),
                "order_id": order_id,
                "state": self._ops_guard.state.value,
                "regime": str(self.processed_data.get("regime", "")),
                "alpha_policy_state": str(self.processed_data.get("alpha_policy_state", "maker_two_sided")),
                "alpha_policy_reason": str(self.processed_data.get("alpha_policy_reason", "unknown")),
                "mid_ref": str(mid_ref),
                "expected_spread_pct": str(expected_spread),
                "adverse_drift_30s": str(adverse_ref),
                "fee_source": self._fee_source,
                "is_maker": str(is_maker),
                "realized_pnl_quote": str(realized_pnl),
            },
            ts=event_ts,
        )

        # Publish fill to hb.bot_telemetry.v1 so live and paper fills are
        # ingested symmetrically by the event_store service.
        # Paper fills publish from hb_bridge; this covers the live path.
        if not _config_is_paper(self.config):
            try:
                import json as _json_tel
                import uuid as _uuid_tel
                from services.contracts.event_identity import validate_event_identity as _validate_event_identity
                runtime_compat = _runtime_compat_surface(self)
                _r = self._get_telemetry_redis()
                if _r is not None:
                    _p = {
                        "event_id": str(_uuid_tel.uuid4()),
                        "event_type": "bot_fill",
                        "event_version": "v1",
                        "schema_version": "1.0",
                        "ts_utc": event_ts,
                        "producer": f"{runtime_compat.telemetry_producer_prefix}.{self.config.instance_name}",
                        "instance_name": self.config.instance_name,
                        "controller_id": str(getattr(self, "id", "") or ""),
                        "connector_name": self.config.connector_name,
                        "trading_pair": self.config.trading_pair,
                        "side": event.trade_type.name.lower(),
                        "price": float(event.price),
                        "amount_base": float(event.amount),
                        "notional_quote": float(notional),
                        "fee_quote": float(fee_quote),
                        "order_id": order_id,
                        "accounting_source": "live_connector",
                        "is_maker": bool(is_maker),
                        "realized_pnl_quote": float(realized_pnl),
                        "bot_state": self._ops_guard.state.value,
                        "metadata": runtime_metadata(runtime_compat),
                    }
                    _identity_ok, _identity_reason = _validate_event_identity(_p)
                    if _identity_ok:
                        _r.xadd("hb.bot_telemetry.v1", {"payload": _json_tel.dumps(_p)}, maxlen=100_000, approximate=True)
                    else:
                        logger.warning(
                            "Fill telemetry dropped for order %s due to identity contract: %s",
                            order_id,
                            _identity_reason,
                        )
            except Exception:
                logger.debug("Fill telemetry publish failed for order %s", order_id, exc_info=True)

        if not excluded_from_risk_accounting:
            self._save_daily_state()

    def did_cancel_order(self, cancelled_event: OrderCancelledEvent):
        self._cancel_events_ts.append(float(self.market_data_provider.time()))
        self._cancel_fail_streak = 0

    def did_fail_order(self, order_failed_event: MarketOrderFailureEvent):
        msg = (order_failed_event.error_message or "").lower()
        if "cancel" in msg:
            self._cancel_fail_streak += 1

    def to_format_status(self) -> List[str]:
        lines = [
            "EPP v2.4 - VIP0 Survival Yield Engine",
            f"variant={self.config.variant} state={self._ops_guard.state.value}",
            f"regime={self.processed_data.get('regime', 'n/a')}",
            f"spread={self.processed_data.get('spread_pct', Decimal('0')) * Decimal('100'):.3f}%",
            f"net_edge={self.processed_data.get('net_edge_pct', Decimal('0')) * Decimal('100'):.4f}%",
            f"base_pct={self.processed_data.get('base_pct', Decimal('0')) * Decimal('100'):.2f}%",
            f"target_base={self.processed_data.get('target_base_pct', Decimal('0')) * Decimal('100'):.2f}%",
            f"turnover_today={self.processed_data.get('turnover_x', Decimal('0')):.3f}x",
            f"mkt_spread={self.processed_data.get('market_spread_bps', Decimal('0')):.2f}bps",
            f"drawdown={self.processed_data.get('drawdown_pct', Decimal('0')) * Decimal('100'):.2f}%",
            (
                f"selective_state={self.processed_data.get('selective_quote_state', 'inactive')} "
                f"score={self.processed_data.get('selective_quote_score', Decimal('0')):.2f} "
                f"reason={self.processed_data.get('selective_quote_reason', 'n/a')}"
            ),
            (
                f"alpha_state={self.processed_data.get('alpha_policy_state', 'maker_two_sided')} "
                f"maker={self.processed_data.get('alpha_maker_score', Decimal('0')):.2f} "
                f"aggr={self.processed_data.get('alpha_aggressive_score', Decimal('0')):.2f} "
                f"inv_urgency={self.processed_data.get('inventory_urgency_pct', Decimal('0')):.2f}"
            ),
            f"paper fills={self.processed_data.get('paper_fill_count', 0)} rejects={self.processed_data.get('paper_reject_count', 0)} avg_qdelay_ms={self.processed_data.get('paper_avg_queue_delay_ms', Decimal('0')):.1f}",
            f"fees maker={self._maker_fee_pct * Decimal('100'):.4f}% taker={self._taker_fee_pct * Decimal('100'):.4f}% source={self._fee_source}",
            f"guard_reasons={','.join(self._ops_guard.reasons) if self._ops_guard.reasons else 'none'}",
            f"position_base={float(self._position_base):.8f} avg_entry={float(self._avg_entry_price):.2f} realized_pnl={float(self._realized_pnl_today):.4f}",
        ]
        if abs(self._position_base) > _BALANCE_EPSILON:
            stop_info = "NO PROTECTIVE STOP"
            if self._protective_stop and self._protective_stop.active_stop_order_id:
                stop_price = float(self._avg_entry_price * (Decimal("1") - self.config.protective_stop_loss_pct))
                stop_info = f"STOP @ {stop_price:.2f} (order={self._protective_stop.active_stop_order_id})"
            lines.append(
                f"** OPEN POSITION: {float(self._position_base):.8f} {self.config.trading_pair} "
                f"(entry={float(self._avg_entry_price):.2f}) — {stop_info} **"
            )
        return lines

    def get_custom_info(self) -> dict:
        return dict(self.processed_data)

    def set_external_soft_pause(self, active: bool, reason: str) -> None:
        self._external_soft_pause = bool(active)
        if self._external_soft_pause:
            resolved_reason = str(reason or "").strip()
            self._external_pause_reason = resolved_reason or "external_intent"
        else:
            # Keep pause reason empty when inactive to avoid stale guard side effects.
            self._external_pause_reason = ""

    def apply_execution_intent(self, intent: Dict[str, object]) -> Tuple[bool, str]:
        action = str(intent.get("action", "")).strip()
        metadata = intent.get("metadata", {})
        metadata = metadata if isinstance(metadata, dict) else {}
        provider = getattr(self, "market_data_provider", None)
        now_ts = float(provider.time()) if provider is not None else float(_time_mod.time())
        self._last_external_intent_ts = now_ts
        self._last_external_model_version = str(metadata.get("model_version", ""))
        self._last_external_intent_reason = str(metadata.get("reason", ""))
        if action == "soft_pause":
            reason = str(metadata.get("reason", "external_intent"))
            self.set_external_soft_pause(True, reason)
            return True, "ok"
        if action == "resume":
            self.set_external_soft_pause(False, "")
            return True, "ok"
        if action == "kill_switch":
            self._ops_guard.force_hard_stop("external_kill_switch")
            return True, "ok"
        if action == "set_target_base_pct":
            value = intent.get("target_base_pct")
            if value is None:
                return False, "missing_target_base_pct"
            try:
                candidate = to_decimal(value)
                if candidate < Decimal("0") or candidate > Decimal("1"):
                    return False, "target_base_pct_out_of_range"
                self._external_target_base_pct_override = _clip(candidate, Decimal("0"), Decimal("1"))
                self._external_target_base_pct_override_ts = now_ts
                self._external_target_base_pct_override_expires_ts = EppV24Controller._intent_expires_ts(
                    intent, now_ts
                )
                return True, "ok"
            except Exception:
                return False, "invalid_target_base_pct"
        if action == "set_daily_pnl_target_pct":
            value = intent.get("daily_pnl_target_pct")
            if value is None:
                value = metadata.get("daily_pnl_target_pct")
            if value is None:
                return False, "missing_daily_pnl_target_pct"
            try:
                candidate = to_decimal(value)
                if candidate < Decimal("0") or candidate > Decimal("100"):
                    return False, "daily_pnl_target_pct_out_of_range"
                self._external_daily_pnl_target_pct_override = _clip(candidate, Decimal("0"), Decimal("100"))
                self._external_daily_pnl_target_pct_override_ts = now_ts
                self._external_daily_pnl_target_pct_override_expires_ts = EppV24Controller._intent_expires_ts(
                    intent, now_ts
                )
                return True, "ok"
            except Exception:
                return False, "invalid_daily_pnl_target_pct"
        if action == "adverse_skip_tick":
            if not self.config.adverse_classifier_enabled:
                return False, "adverse_classifier_not_enabled"
            p_adverse = float(metadata.get("p_adverse", 0))
            self._runtime_levels.buy_spreads = []
            self._runtime_levels.sell_spreads = []
            self._runtime_levels.buy_amounts_pct = []
            self._runtime_levels.sell_amounts_pct = []
            logger.debug("Adverse skip: cleared spreads (p_adverse=%.3f skip_count=%d)", p_adverse, self._adverse_skip_count)
            return True, "ok"
        if action == "adverse_widen_spreads":
            if not self.config.adverse_classifier_enabled:
                return False, "adverse_classifier_not_enabled"
            p_adverse_d = to_decimal(metadata.get("p_adverse", 0))
            widen_mult = _ONE + p_adverse_d * Decimal("0.5")
            for i in range(len(self._runtime_levels.buy_spreads)):
                self._runtime_levels.buy_spreads[i] = self._runtime_levels.buy_spreads[i] * widen_mult
            for i in range(len(self._runtime_levels.sell_spreads)):
                self._runtime_levels.sell_spreads[i] = self._runtime_levels.sell_spreads[i] * widen_mult
            logger.debug("Adverse widen: spread × %.3f (p_adverse=%.3f)", float(widen_mult), float(p_adverse_d))
            return True, "ok"
        if action == "set_regime_override":
            if not self.config.ml_regime_enabled:
                return False, "ml_regime_not_enabled"
            regime = str(intent.get("regime", metadata.get("regime", ""))).strip()
            if not regime or regime not in self._resolved_specs:
                return False, f"unknown_regime:{regime}"
            now = float(self.market_data_provider.time())
            self._external_regime_override = regime
            self._external_regime_override_expiry = now + self.config.ml_regime_override_ttl_s
            logger.debug("ML regime override set: %s (expires in %.0fs)", regime, self.config.ml_regime_override_ttl_s)
            return True, "ok"
        return False, "unsupported_action"

    def _get_kelly_order_quote(self, equity_quote: Decimal) -> Decimal:
        """Compute Kelly-fractional order size. Returns 0 when insufficient history."""
        if (
            not self.config.use_kelly_sizing
            or self._fill_count_for_kelly < self.config.kelly_min_observations
            or self._fill_edge_ewma is None
            or self._fill_edge_variance is None
            or self._fill_edge_variance <= _ZERO
        ):
            return _ZERO
        kelly_size = (self._fill_edge_ewma / self._fill_edge_variance) * self.config.kelly_fraction * equity_quote
        return _clip(kelly_size, self.config.kelly_min_order_quote, self.config.kelly_max_order_quote)

    def _get_ohlcv_ema_and_atr(self) -> Tuple[Optional[Decimal], Optional[Decimal]]:
        """Fetch 1m OHLCV candles and compute EMA/band_pct. Returns (None, None) on failure."""
        connector = self.config.candles_connector
        if not connector:
            return None, None
        pair = self.config.candles_trading_pair or self.config.trading_pair
        needed = self.config.ema_period + 5
        try:
            df = self.market_data_provider.get_candles_df(connector, pair, "1m", needed)
        except Exception:
            return None, None
        if df is None or df.empty or len(df) < self.config.ema_period:
            return None, None
        # Drop the last (still-forming) candle to prevent lookahead/repaint bias.
        # HB candles DataFrames carry 'timestamp' in milliseconds (epoch ms).
        # If the last bar opened within the last 60 s it is not yet closed.
        try:
            if "timestamp" in df.columns:
                now_s = float(self.market_data_provider.time())
                last_ts = float(df["timestamp"].iloc[-1])
                # Convert ms → s when the value looks like a millisecond timestamp.
                last_ts_s = last_ts / 1000.0 if last_ts > 1e10 else last_ts
                if now_s - last_ts_s < 60.0:
                    df = df.iloc[:-1]
        except Exception:
            pass
        if df.empty or len(df) < self.config.ema_period:
            return None, None
        try:
            closes = [to_decimal(c) for c in df["close"].values]
            alpha = _TWO / Decimal(self.config.ema_period + 1)
            ema_val = closes[0]
            for c in closes[1:]:
                ema_val = alpha * c + (_ONE - alpha) * ema_val
            highs = [to_decimal(h) for h in df["high"].values]
            lows = [to_decimal(lo) for lo in df["low"].values]
            trs: List[Decimal] = []
            for i in range(1, len(closes)):
                tr = max(
                    highs[i] - lows[i],
                    abs(highs[i] - closes[i - 1]),
                    abs(lows[i] - closes[i - 1]),
                )
                trs.append(tr)
            atr_period = min(self.config.atr_period, len(trs))
            if atr_period <= 0 or closes[-1] <= _ZERO:
                return ema_val, None
            atr_val = sum(trs[-atr_period:], _ZERO) / Decimal(atr_period)
            band_pct = atr_val / closes[-1]
            return ema_val, band_pct
        except Exception:
            return None, None

    def _detect_regime(self, mid: Decimal) -> Tuple[str, RegimeSpec, Decimal]:
        """Classify regime and return the band_pct that was actually used.

        Returns ``(regime_name, regime_spec, band_pct)`` so callers can thread
        the same volatility measure into spread/edge and high-vol checks, ensuring
        all three consumers see a consistent view of current volatility.
        """
        if self.config.ml_regime_enabled and self._external_regime_override:
            now = float(self.market_data_provider.time())
            if now < self._external_regime_override_expiry:
                regime = self._external_regime_override
                self._active_regime = regime
                self._regime_source = "ml"
                # ML path: derive band_pct from price buffer (OHLCV not used here).
                ml_band = self._price_buffer.band_pct(self.config.atr_period) or _ZERO
                return regime, self._resolved_specs[regime], ml_band
            else:
                self._external_regime_override = None

        ohlcv_ema, ohlcv_band = self._get_ohlcv_ema_and_atr()
        if ohlcv_ema is not None and ohlcv_band is not None:
            ema_val, band_pct, source_tag = ohlcv_ema, ohlcv_band, "ohlcv"
        else:
            ema_val = self._price_buffer.ema(self.config.ema_period)
            band_pct = self._price_buffer.band_pct(self.config.atr_period) or _ZERO
            source_tag = "price_buffer"
        drift = self._price_buffer.adverse_drift_30s(float(self.market_data_provider.time()))
        self._regime_ema_value = ema_val

        regime_name, regime_spec = self._regime_detector.detect(
            mid, ema_val, band_pct, drift, source_tag,
        )
        self._active_regime = self._regime_detector._active_regime
        self._pending_regime = self._regime_detector._pending_regime
        self._regime_hold_counter = self._regime_detector._regime_hold_counter
        self._regime_source = self._regime_detector._regime_source

        if self._regime_detector.changed_one_sided is not None:
            self._pending_stale_cancel_actions = self._cancel_stale_side_executors(
                self._regime_detector.changed_one_sided, regime_spec.one_sided,
            )

        return regime_name, regime_spec, band_pct

    def _cancel_stale_side_executors(self, old_one_sided: str, new_one_sided: str) -> List[Any]:
        """Return StopExecutorActions for active executors on a side the new regime disabled."""
        from hummingbot.strategy_v2.models.executor_actions import StopExecutorAction

        cancel_buy = (
            (new_one_sided == "sell_only" and old_one_sided != "sell_only")
            or (new_one_sided == "off" and old_one_sided != "off")
        )
        cancel_sell = (
            (new_one_sided == "buy_only" and old_one_sided != "buy_only")
            or (new_one_sided == "off" and old_one_sided != "off")
        )
        if not cancel_buy and not cancel_sell:
            return []
        actions: List[Any] = []
        for executor in self.executors_info:
            if not executor.is_active:
                continue
            custom = getattr(executor, "custom_info", None) or {}
            level_id = custom.get("level_id", "") if isinstance(custom, dict) else ""
            if cancel_buy and level_id.startswith("buy"):
                actions.append(StopExecutorAction(controller_id=self.config.id, executor_id=executor.id))
            elif cancel_sell and level_id.startswith("sell"):
                actions.append(StopExecutorAction(controller_id=self.config.id, executor_id=executor.id))
        if actions:
            logger.info("Regime transition %s→%s: canceling %d stale-side executors", old_one_sided, new_one_sided, len(actions))
        return actions

    def _cancel_active_quote_executors(self) -> List[Any]:
        """Return StopExecutorActions for all active quote executors.

        Used by alpha no-trade fail-closed behavior so outstanding buy/sell quote
        executors do not keep resting and filling after the policy disabled quoting.
        """
        try:
            from hummingbot.strategy_v2.models.executor_actions import StopExecutorAction
        except Exception:
            logger.debug("Unable to import StopExecutorAction for alpha no-trade cancel", exc_info=True)
            return []

        requested_ids = getattr(self, "_alpha_no_trade_cancel_requested_ids", None)
        if not isinstance(requested_ids, set):
            requested_ids = set()
            self._alpha_no_trade_cancel_requested_ids = requested_ids

        existing_pending = {
            str(getattr(a, "executor_id", ""))
            for a in self._pending_stale_cancel_actions
            if getattr(a, "executor_id", None) is not None
        }

        actions: List[Any] = []
        for executor in self.executors_info:
            if not bool(getattr(executor, "is_active", False)):
                continue
            custom = getattr(executor, "custom_info", None) or {}
            level_id = str(custom.get("level_id", "") if isinstance(custom, dict) else "")
            if not (level_id.startswith("buy") or level_id.startswith("sell")):
                continue
            ex_id = str(getattr(executor, "id", "") or "")
            if not ex_id or ex_id in existing_pending or ex_id in requested_ids:
                continue
            actions.append(StopExecutorAction(controller_id=self.config.id, executor_id=ex_id))
            requested_ids.add(ex_id)

        if actions:
            logger.info("Alpha no-trade: canceling %d active quote executors", len(actions))
        return actions

    def _cancel_alpha_no_trade_paper_orders(self) -> int:
        """Cancel lingering PaperDesk orders while alpha policy is in no-trade.

        Quote executors can be stopped quickly, but their underlying PaperDesk
        orders may remain briefly during restart/recovery races. This fail-closed
        path keeps alpha no-trade behavior strict in paper mode.
        """
        if not _config_is_paper(self.config):
            return 0

        provider = getattr(self, "market_data_provider", None)
        time_fn = getattr(provider, "time", None) if provider is not None else None
        now_ts = float(time_fn()) if callable(time_fn) else float(_time_mod.time())
        cooldown_s = 5.0
        last_ts = float(getattr(self, "_alpha_no_trade_last_paper_cancel_ts", 0.0) or 0.0)
        if (now_ts - last_ts) < cooldown_s:
            return 0
        self._alpha_no_trade_last_paper_cancel_ts = now_ts

        try:
            canceled = EppV24Controller._cancel_stale_paper_orders(
                self,
                stale_age_s=0.25,
                now_ts=now_ts,
            )
        except Exception:
            logger.debug("Alpha no-trade paper-order cleanup skipped", exc_info=True)
            return 0

        if canceled > 0:
            logger.info("Alpha no-trade: canceled %d lingering paper order(s)", canceled)
        return canceled

    def _pick_spread_pct(self, regime_spec: RegimeSpec, turnover_x: Decimal) -> Decimal:
        if self.config.override_spread_pct is not None:
            return max(Decimal("0"), to_decimal(self.config.override_spread_pct))
        return self._spread_engine.pick_spread_pct(regime_spec, turnover_x)

    def _pick_levels(self, regime_spec: RegimeSpec, turnover_x: Decimal) -> int:
        return self._spread_engine.pick_levels(regime_spec, turnover_x)

    def _build_side_spreads(
        self, spread_pct: Decimal, skew: Decimal, levels: int, one_sided: str, min_side_spread: Decimal
    ) -> Tuple[List[Decimal], List[Decimal]]:
        return self._spread_engine.build_side_spreads(spread_pct, skew, levels, one_sided, min_side_spread)

    def _apply_runtime_spreads_and_sizing(
        self,
        buy_spreads: List[Decimal],
        sell_spreads: List[Decimal],
        levels: int,
        equity_quote: Decimal,
        mid: Decimal,
        quote_size_pct: Decimal,
        size_mult: Decimal = _ONE,
    ) -> None:
        safe_mult = max(_ONE, to_decimal(size_mult))
        self._runtime_size_mult_applied = safe_mult
        self._spread_engine.apply_runtime_spreads_and_sizing(
            runtime_levels=self._runtime_levels,
            buy_spreads=buy_spreads,
            sell_spreads=sell_spreads,
            equity_quote=equity_quote,
            mid=mid,
            quote_size_pct=quote_size_pct,
            size_mult=safe_mult,
            kelly_order_quote=self._get_kelly_order_quote(equity_quote),
            min_notional_quote=self._min_notional_quote(),
            min_base_amount=self._min_base_amount(mid),
            max_order_notional_quote=self.config.max_order_notional_quote,
            max_total_notional_quote=self.config.max_total_notional_quote,
            cooldown_time=int(self.config.cooldown_time),
            no_trade=self.config.no_trade,
            variant=self.config.variant,
            enabled=self.config.enabled,
        )

    def _connector(self):
        return self._runtime_adapter.get_connector()

    def _paper_portfolio_snapshot(self, mid: Decimal) -> Optional[Dict[str, Decimal]]:
        """Return canonical PaperDesk accounting snapshot for current instrument."""
        if not _config_is_paper(self.config):
            return None
        connector = self._connector()
        desk = getattr(connector, "_paper_desk_v2", None)
        iid = getattr(connector, "_paper_desk_v2_instrument_id", None)
        if desk is None or iid is None:
            # Fallback path: when connector cache resolves to a connector proxy that
            # does not carry bridge attrs, read from strategy-level bridge registry.
            strategy = getattr(self, "strategy", None) or getattr(self, "_strategy", None)
            bridges = getattr(strategy, "_paper_desk_v2_bridges", {}) if strategy is not None else {}
            if isinstance(bridges, dict):
                bridge = bridges.get(str(self.config.connector_name), {})
                if isinstance(bridge, dict):
                    desk = bridge.get("desk", desk)
                    iid = bridge.get("instrument_id", iid)
        if desk is None or iid is None:
            return None
        try:
            portfolio = getattr(desk, "portfolio", None)
            if portfolio is None:
                return None
            get_pos = getattr(portfolio, "get_position", None)
            if not callable(get_pos):
                return None
            pos = get_pos(iid)
            if pos is None:
                return None
            snapshot: Dict[str, Decimal] = {
                "position_base": to_decimal(getattr(pos, "quantity", _ZERO)),
                "position_gross_base": to_decimal(getattr(pos, "gross_quantity", abs(getattr(pos, "quantity", _ZERO)))),
                "position_long_base": to_decimal(getattr(pos, "long_quantity", max(_ZERO, getattr(pos, "quantity", _ZERO)))),
                "position_short_base": to_decimal(getattr(pos, "short_quantity", max(_ZERO, -to_decimal(getattr(pos, "quantity", _ZERO))))),
                "position_mode": str(getattr(pos, "position_mode", "ONEWAY") or "ONEWAY").upper(),
                "avg_entry_price": to_decimal(getattr(pos, "avg_entry_price", _ZERO)),
                "avg_entry_price_long": to_decimal(getattr(pos, "long_avg_entry_price", _ZERO)),
                "avg_entry_price_short": to_decimal(getattr(pos, "short_avg_entry_price", _ZERO)),
                "unrealized_pnl": to_decimal(getattr(pos, "unrealized_pnl", _ZERO)),
                "realized_pnl": to_decimal(getattr(pos, "realized_pnl", _ZERO)),
                "daily_open_equity": to_decimal(getattr(portfolio, "daily_open_equity", _ZERO) or _ZERO),
                "equity_quote": _ZERO,
            }
            if hasattr(portfolio, "equity_quote"):
                try:
                    quote_asset = getattr(iid, "quote_asset", "USDT")
                    mid_d = to_decimal(mid)
                    eq = portfolio.equity_quote({iid.key: mid_d}, quote_asset=quote_asset)
                    snapshot["equity_quote"] = to_decimal(eq)
                except Exception:
                    # Keep partial snapshot; caller can still use position/open-equity data.
                    pass
            return snapshot
        except Exception:
            return None

    def _paper_open_order_level_ids(self) -> List[str]:
        """Return side level_ids that are still live in PaperDesk.

        Paper executor runtime state can occasionally drop before the underlying
        PaperDesk order disappears. In that case, treat the side as occupied so
        the controller does not layer a duplicate maker on top of the lingering
        paper order.
        """
        if not _config_is_paper(self.config):
            return []
        connector = self._connector()
        desk = getattr(connector, "_paper_desk_v2", None)
        iid = getattr(connector, "_paper_desk_v2_instrument_id", None)
        if desk is None or iid is None:
            strategy = getattr(self, "strategy", None) or getattr(self, "_strategy", None)
            bridges = getattr(strategy, "_paper_desk_v2_bridges", {}) if strategy is not None else {}
            if isinstance(bridges, dict):
                bridge = bridges.get(str(self.config.connector_name), {})
                if isinstance(bridge, dict):
                    desk = bridge.get("desk", desk)
                    iid = bridge.get("instrument_id", iid)
        if desk is None or iid is None:
            return []
        try:
            engine = getattr(desk, "_engines", {}).get(iid.key)
            open_orders_fn = getattr(engine, "open_orders", None)
            if not callable(open_orders_fn):
                return []
            connector_name = str(getattr(self.config, "connector_name", "") or "")
            occupied: set[str] = set()
            working_orders = list(open_orders_fn() or [])
            for inflight in list(getattr(engine, "_inflight", []) or []):
                if not isinstance(inflight, tuple) or len(inflight) < 3:
                    continue
                _due_ns, action, order = inflight
                if str(action or "").lower() != "accept":
                    continue
                working_orders.append(order)
            for order in working_orders:
                source_bot = str(getattr(order, "source_bot", "") or "")
                if connector_name and source_bot and source_bot != connector_name:
                    continue
                side = str(getattr(getattr(order, "side", None), "value", getattr(order, "side", "")) or "").lower()
                if side == "buy":
                    occupied.update(
                        self.get_level_id_from_side(TradeType.BUY, level)
                        for level in range(len(self._runtime_levels.buy_spreads))
                    )
                elif side == "sell":
                    occupied.update(
                        self.get_level_id_from_side(TradeType.SELL, level)
                        for level in range(len(self._runtime_levels.sell_spreads))
                    )
            return sorted(occupied)
        except Exception:
            return []

    def _paper_open_order_count(self) -> int:
        """Return live PaperDesk order count for this controller."""
        if not _config_is_paper(self.config):
            return 0
        connector = self._connector()
        desk = getattr(connector, "_paper_desk_v2", None)
        iid = getattr(connector, "_paper_desk_v2_instrument_id", None)
        if desk is None or iid is None:
            strategy = getattr(self, "strategy", None) or getattr(self, "_strategy", None)
            bridges = getattr(strategy, "_paper_desk_v2_bridges", {}) if strategy is not None else {}
            if isinstance(bridges, dict):
                bridge = bridges.get(str(self.config.connector_name), {})
                if isinstance(bridge, dict):
                    desk = bridge.get("desk", desk)
                    iid = bridge.get("instrument_id", iid)
        if desk is None or iid is None:
            return 0
        try:
            engine = getattr(desk, "_engines", {}).get(iid.key)
            open_orders_fn = getattr(engine, "open_orders", None)
            if not callable(open_orders_fn):
                return 0
            connector_name = str(getattr(self.config, "connector_name", "") or "")
            count = 0
            working_orders = list(open_orders_fn() or [])
            for inflight in list(getattr(engine, "_inflight", []) or []):
                if not isinstance(inflight, tuple) or len(inflight) < 3:
                    continue
                _due_ns, action, order = inflight
                if str(action or "").lower() != "accept":
                    continue
                working_orders.append(order)
            for order in working_orders:
                source_bot = str(getattr(order, "source_bot", "") or "")
                if connector_name and source_bot and source_bot != connector_name:
                    continue
                count += 1
            return count
        except Exception:
            return 0

    def _cancel_orphan_paper_orders_on_startup(self) -> int:
        """Cancel restored PaperDesk orders when no executor owns them after restart.

        In paper mode, the desk can restore resting orders across process restarts,
        but controller executors are not reconstructed from that persisted state.
        Those orphaned makers then block duplicate level creation while never
        participating in normal refresh/reprice logic. Clean them up once at
        startup so fresh runtime executors can re-quote near market.
        """
        if not _config_is_paper(self.config):
            return 0
        if not bool(getattr(self.config, "paper_state_reconcile_enabled", False)):
            return 0

        connector = self._connector()
        desk = getattr(connector, "_paper_desk_v2", None)
        iid = getattr(connector, "_paper_desk_v2_instrument_id", None)
        if desk is None or iid is None:
            strategy = getattr(self, "strategy", None) or getattr(self, "_strategy", None)
            bridges = getattr(strategy, "_paper_desk_v2_bridges", {}) if strategy is not None else {}
            if isinstance(bridges, dict):
                bridge = bridges.get(str(self.config.connector_name), {})
                if isinstance(bridge, dict):
                    desk = bridge.get("desk", desk)
                    iid = bridge.get("instrument_id", iid)
        if desk is None or iid is None:
            return 0

        try:
            active_executors = self.filter_executors(
                executors=self.executors_info,
                filter_func=lambda x: getattr(x, "is_active", False),
            )
        except Exception:
            active_executors = [x for x in list(getattr(self, "executors_info", []) or []) if getattr(x, "is_active", False)]
        if active_executors:
            return 0

        try:
            engine = getattr(desk, "_engines", {}).get(iid.key)
            open_orders_fn = getattr(engine, "open_orders", None)
            if not callable(open_orders_fn):
                return 0
            connector_name = str(getattr(self.config, "connector_name", "") or "")
            cancel_ids: List[str] = []
            for order in list(open_orders_fn() or []):
                source_bot = str(getattr(order, "source_bot", "") or "")
                if connector_name and source_bot and source_bot != connector_name:
                    continue
                order_id = str(getattr(order, "order_id", "") or "")
                if order_id:
                    cancel_ids.append(order_id)
            canceled = 0
            cancel_order_fn = getattr(desk, "cancel_order", None)
            if not callable(cancel_order_fn):
                return 0
            for order_id in cancel_ids:
                event = cancel_order_fn(iid, order_id)
                if event is not None:
                    canceled += 1
            if canceled > 0:
                self._recently_issued_levels = {}
            return canceled
        except Exception:
            logger.debug("Startup orphan paper-order cleanup failed for %s", self.config.trading_pair, exc_info=True)
            return 0

    def _cancel_stale_paper_orders(self, stale_age_s: float, now_ts: Optional[float] = None) -> int:
        """Cancel PaperDesk makers that outlive the refresh window in paper mode.

        Paper executor stop actions can occasionally race with PaperDesk state,
        leaving the underlying order live after its executor is already being
        refreshed. When that happens, the lingering paper order keeps the side
        marked as occupied and blocks a fresh near-market re-quote. Explicitly
        cancel stale paper orders so refresh-driven repricing works reliably.
        """
        if not _config_is_paper(self.config):
            return 0
        if not bool(getattr(self.config, "paper_state_reconcile_enabled", False)):
            return 0
        stale_age_s = max(0.0, float(stale_age_s or 0.0))
        if stale_age_s <= 0.0:
            return 0

        connector = self._connector()
        desk = getattr(connector, "_paper_desk_v2", None)
        iid = getattr(connector, "_paper_desk_v2_instrument_id", None)
        if desk is None or iid is None:
            strategy = getattr(self, "strategy", None) or getattr(self, "_strategy", None)
            bridges = getattr(strategy, "_paper_desk_v2_bridges", {}) if strategy is not None else {}
            if isinstance(bridges, dict):
                bridge = bridges.get(str(self.config.connector_name), {})
                if isinstance(bridge, dict):
                    desk = bridge.get("desk", desk)
                    iid = bridge.get("instrument_id", iid)
        if desk is None or iid is None:
            return 0

        try:
            engine = getattr(desk, "_engines", {}).get(iid.key)
            open_orders_fn = getattr(engine, "open_orders", None)
            if not callable(open_orders_fn):
                return 0
            cancel_order_fn = getattr(desk, "cancel_order", None)
            if not callable(cancel_order_fn):
                return 0

            now_epoch = float(now_ts if now_ts is not None else self.market_data_provider.time())
            connector_name = str(getattr(self.config, "connector_name", "") or "")
            cancel_ids: List[str] = []
            for order in list(open_orders_fn() or []):
                source_bot = str(getattr(order, "source_bot", "") or "")
                if connector_name and source_bot and source_bot != connector_name:
                    continue
                order_id = str(getattr(order, "order_id", "") or "")
                if not order_id:
                    continue
                created_at_ns = int(
                    getattr(order, "created_at_ns", 0)
                    or getattr(order, "updated_at_ns", 0)
                    or 0
                )
                if created_at_ns <= 0:
                    continue
                order_age_s = now_epoch - (created_at_ns / 1e9)
                if order_age_s >= stale_age_s:
                    cancel_ids.append(order_id)

            canceled = 0
            for order_id in cancel_ids:
                event = cancel_order_fn(iid, order_id)
                if event is not None:
                    canceled += 1
            if canceled > 0:
                self._recently_issued_levels = {}
            return canceled
        except Exception:
            logger.debug("Runtime stale paper-order cleanup failed for %s", self.config.trading_pair, exc_info=True)
            return 0

    def _sync_from_paper_desk_v2(self, *, mid: Decimal, equity_quote: Optional[Decimal] = None) -> None:
        """In Paper Engine v2 mode, treat PaperDesk as the canonical accounting source.

        This prevents `minute.csv` (Grafana source) from drifting away from PaperDesk's
        position/avg entry/unrealized when fills are routed through the bridge.
        """
        if not _config_is_paper(self.config):
            return
        snap = self._paper_portfolio_snapshot(mid)
        if not isinstance(snap, dict):
            return
        try:
            self._position_base = to_decimal(snap.get("position_base", _ZERO))
            self._position_gross_base = to_decimal(snap.get("position_gross_base", abs(self._position_base)))
            self._position_long_base = to_decimal(snap.get("position_long_base", max(_ZERO, self._position_base)))
            self._position_short_base = to_decimal(snap.get("position_short_base", max(_ZERO, -self._position_base)))
            entry_px = to_decimal(snap.get("avg_entry_price", _ZERO))
            if entry_px > _ZERO:
                self._avg_entry_price = entry_px
            self._avg_entry_price_long = to_decimal(snap.get("avg_entry_price_long", self._avg_entry_price if self._position_long_base > _ZERO else _ZERO))
            self._avg_entry_price_short = to_decimal(snap.get("avg_entry_price_short", self._avg_entry_price if self._position_short_base > _ZERO else _ZERO))

            open_eq_d = to_decimal(snap.get("daily_open_equity", _ZERO))
            if open_eq_d <= _ZERO and self._daily_equity_open is not None and self._daily_equity_open > _ZERO:
                open_eq_d = self._daily_equity_open
            if open_eq_d > _ZERO:
                self._daily_equity_open = open_eq_d

            eq_used = to_decimal(snap.get("equity_quote", _ZERO))
            if eq_used <= _ZERO and equity_quote is not None:
                eq_used = to_decimal(equity_quote)
            if eq_used > _ZERO:
                if self._daily_equity_peak is None or eq_used > self._daily_equity_peak:
                    self._daily_equity_peak = eq_used

            provider = getattr(self, "market_data_provider", None)
            now_ts = float(provider.time()) if provider is not None else float(_time_mod.time())
            startup_reset_enabled = bool(getattr(self.config, "paper_daily_baseline_auto_reset_on_startup", False))
            startup_window_s = float(getattr(self.config, "paper_daily_baseline_reset_startup_window_s", 300.0))
            loss_reset_threshold = max(
                _ZERO,
                to_decimal(getattr(self.config, "paper_daily_baseline_reset_loss_pct_threshold", Decimal("0.25"))),
            )
            if (
                startup_reset_enabled
                and not self._paper_daily_baseline_reset_done
                and open_eq_d > _ZERO
                and eq_used > _ZERO
                and (now_ts - self._controller_start_ts) <= max(1.0, startup_window_s)
            ):
                inherited_loss_pct = max(_ZERO, (open_eq_d - eq_used) / open_eq_d)
                if inherited_loss_pct >= loss_reset_threshold:
                    logger.warning(
                        "Paper startup baseline reset applied: open_equity %.4f -> %.4f "
                        "(inherited_loss_pct=%.2f%% threshold=%.2f%%).",
                        float(open_eq_d),
                        float(eq_used),
                        float(inherited_loss_pct * _100),
                        float(loss_reset_threshold * _100),
                    )
                    open_eq_d = eq_used
                    self._daily_equity_open = eq_used
                    if self._daily_equity_peak is None or eq_used > self._daily_equity_peak:
                        self._daily_equity_peak = eq_used
                    self._traded_notional_today = _ZERO
                    self._fills_count_today = 0
                    self._fees_paid_today_quote = _ZERO
                    self._funding_cost_today_quote = _ZERO
                    self._paper_daily_baseline_reset_done = True
                    self._save_daily_state(force=True)

            if open_eq_d > _ZERO and eq_used > _ZERO:
                # Canonical realized attribution for paper mode:
                # realized = (equity - open_equity) - unrealized.
                unreal = to_decimal(snap.get("unrealized_pnl", _ZERO))
                reconciled_realized = (eq_used - open_eq_d) - unreal
                prev_realized = self._realized_pnl_today
                self._realized_pnl_today = reconciled_realized

                if bool(getattr(self.config, "paper_state_reconcile_enabled", False)):
                    reconcile_threshold = max(
                        _ZERO,
                        to_decimal(getattr(self.config, "paper_state_reconcile_realized_pnl_diff_quote", _ZERO)),
                    )
                    if abs(prev_realized - reconciled_realized) > reconcile_threshold:
                        if (
                            now_ts - self._paper_state_reconcile_last_ts
                            >= max(1.0, self._paper_state_reconcile_log_cooldown_s)
                        ):
                            logger.warning(
                                "Paper state reconciled from PaperDesk: realized_pnl %.4f -> %.4f "
                                "(threshold=%.4f).",
                                float(prev_realized),
                                float(reconciled_realized),
                                float(reconcile_threshold),
                            )
                            self._paper_state_reconcile_last_ts = now_ts
                        self._save_daily_state(force=True)
        except Exception:
            # Never block trading/ops on accounting sync.
            return

    def _trading_rule(self):
        return self._runtime_adapter.get_trading_rule()

    def get_levels_to_execute(self) -> List[str]:
        if self._derisk_force_taker:
            # When force mode is active, route through market rebalance only.
            return []
        if str(getattr(self, "_selective_quote_state", "inactive")) == "blocked":
            return []
        cooldown = max(1, int(self._runtime_levels.cooldown_time))
        reissue_cooldown_s = cooldown
        now = self.market_data_provider.time()
        self._recently_issued_levels = {
            k: v for k, v in self._recently_issued_levels.items() if now - v < reissue_cooldown_s
        }
        active_count = 0
        working_levels = self.filter_executors(
            executors=self.executors_info,
            filter_func=lambda x: x.is_active
            or (str(getattr(x, "close_type", "")) == "CloseType.STOP_LOSS" and now - x.close_timestamp < cooldown),
        )
        stopping_level_ids = set()
        for ex in self.executors_info:
            if ex.is_active:
                active_count += 1
            if getattr(ex, "close_type", None) is not None and ex.is_active:
                lid = ex.custom_info.get("level_id", "")
                if lid:
                    stopping_level_ids.add(lid)
        if active_count >= self.config.max_active_executors:
            return []
        working_levels_ids = [executor.custom_info["level_id"] for executor in working_levels]
        working_levels_ids.extend(stopping_level_ids)
        if _config_is_paper(self.config):
            working_levels_ids.extend(EppV24Controller._paper_open_order_level_ids(self))
        candidates = self.get_not_active_levels_ids(working_levels_ids)
        result = [lid for lid in candidates if lid not in self._recently_issued_levels]
        if str(getattr(self, "_selective_quote_state", "inactive")) == "reduced" and result:
            max_levels_per_side = max(1, int(getattr(self.config, "selective_max_levels_per_side", 1)))
            grouped: Dict[str, List[Tuple[int, str]]] = {}
            for lid in result:
                side = str(lid).split("_", 1)[0]
                try:
                    level_idx = int(str(lid).rsplit("_", 1)[1])
                except Exception:
                    level_idx = 0
                grouped.setdefault(side, []).append((level_idx, lid))
            allowed: set[str] = set()
            for side_items in grouped.values():
                side_items.sort(key=lambda item: item[0], reverse=True)
                allowed.update(lid for _, lid in side_items[:max_levels_per_side])
            result = [lid for lid in result if lid in allowed]
        for lid in result:
            self._recently_issued_levels[lid] = now
        return result

    def executors_to_refresh(self) -> List[Any]:
        return _runtime_family_adapter(self).executors_to_refresh()

    def _in_reconnect_refresh_suppression_window(self, now_ts: float) -> bool:
        """Return True when executor refresh cancels should be suppressed.

        Reconnect churn can repeatedly tear down/recreate orders before they have a
        chance to rest/fill. Suppressing refresh-driven cancels during this window
        keeps inventory-neutral makers live until feeds stabilize.
        """
        reconnect_cooldown_until = float(getattr(self, "_reconnect_cooldown_until", 0.0) or 0.0)
        reconnect_grace_until = float(getattr(self, "_book_reconnect_grace_until_ts", 0.0) or 0.0)
        return float(now_ts) < max(reconnect_cooldown_until, reconnect_grace_until)

    def get_not_active_levels_ids(self, active_levels_ids: List[str]) -> List[str]:
        buy_ids_missing = [
            self.get_level_id_from_side(TradeType.BUY, level)
            for level in range(len(self._runtime_levels.buy_spreads))
            if self.get_level_id_from_side(TradeType.BUY, level) not in active_levels_ids
        ]
        sell_ids_missing = [
            self.get_level_id_from_side(TradeType.SELL, level)
            for level in range(len(self._runtime_levels.sell_spreads))
            if self.get_level_id_from_side(TradeType.SELL, level) not in active_levels_ids
        ]
        return buy_ids_missing + sell_ids_missing

    def get_price_and_amount(self, level_id: str) -> Tuple[Decimal, Decimal]:
        return _runtime_family_adapter(self).get_price_and_amount(level_id)

    def _runtime_spreads_and_amounts_in_quote(self, trade_type: TradeType) -> Tuple[List[Decimal], List[Decimal]]:
        return _runtime_family_adapter(self)._runtime_spreads_and_amounts_in_quote(trade_type)

    def _runtime_required_base_amount(self, reference_price: Decimal) -> Decimal:
        return _runtime_family_adapter(self).runtime_required_base_amount(reference_price)

    def _perp_target_base_amount(self, reference_price: Decimal) -> Decimal:
        """Signed base amount implied by the current perp net-exposure target."""
        if reference_price <= 0:
            return Decimal("0")
        processed = getattr(self, "processed_data", {}) or {}
        equity_quote = to_decimal(processed.get("equity_quote", _ZERO))
        if equity_quote <= 0:
            return Decimal("0")
        target_net_base_pct = to_decimal(processed.get("target_net_base_pct", _ZERO))
        return (equity_quote * target_net_base_pct) / reference_price

    def _position_rebalance_floor(self, reference_price: Decimal) -> Decimal:
        """Minimum base size required to issue a rebalance order."""
        return _runtime_family_adapter(self).position_rebalance_floor(reference_price)

    def check_position_rebalance(self):
        is_perp_connector = "_perpetual" in self.config.connector_name
        ops_guard = getattr(self, "_ops_guard", None)
        guard_reasons = set(getattr(ops_guard, "reasons", []) or [])
        inventory_derisk_active = bool(guard_reasons.intersection(_INVENTORY_DERISK_REASONS))
        guard_state = getattr(ops_guard, "state", None)
        derisk_only_active = (
            guard_state == GuardState.SOFT_PAUSE
            and inventory_derisk_active
        )
        hard_stop_flatten_active = (
            guard_state == GuardState.HARD_STOP
            and abs(self._position_base) > _BALANCE_EPSILON
        )
        if "reference_price" not in self.processed_data or (
            self.config.skip_rebalance
            and not (self._derisk_force_taker or derisk_only_active or hard_stop_flatten_active)
        ):
            return None
        # Perps normally skip rebalance orders, but when derisk_only is active we must
        # actively flatten inventory even before force-taker escalation kicks in.
        if is_perp_connector and not (self._derisk_force_taker or derisk_only_active or hard_stop_flatten_active):
            return None
        active_rebalance = self.filter_executors(
            executors=self.executors_info,
            filter_func=lambda x: x.is_active and x.custom_info.get("level_id") == "position_rebalance",
        )
        if len(active_rebalance) > 0:
            if derisk_only_active:
                trace_derisk = getattr(self, "_trace_derisk", None)
                if callable(trace_derisk):
                    trace_derisk(
                        self.market_data_provider.time(),
                        "rebalance_skipped_active_executor",
                        active_rebalance=len(active_rebalance),
                    )
            return None
        reference_price = to_decimal(self.processed_data["reference_price"])
        if is_perp_connector:
            required_base_amount = EppV24Controller._perp_target_base_amount(self, reference_price)
        else:
            required_base_amount = self._runtime_required_base_amount(reference_price)
        current_base_amount = self._position_base if is_perp_connector else self.get_current_base_position()
        base_amount_diff = required_base_amount - current_base_amount
        threshold_amount = required_base_amount * self.config.position_rebalance_threshold_pct
        # Guard against zero-threshold churn when target inventory is near flat.
        # Without this floor, tiny residual inventory can trigger repeated
        # min-notional taker rebalances (buy/sell ping-pong).
        min_rebalance_floor = EppV24Controller._position_rebalance_floor(self, reference_price)
        threshold_amount = max(threshold_amount, min_rebalance_floor)
        if derisk_only_active:
            trace_derisk = getattr(self, "_trace_derisk", None)
            if callable(trace_derisk):
                trace_derisk(
                    self.market_data_provider.time(),
                    "rebalance_eval",
                    required_base_amount=required_base_amount,
                    current_base_amount=current_base_amount,
                    base_amount_diff=base_amount_diff,
                    threshold_amount=threshold_amount,
                    skip_rebalance=self.config.skip_rebalance,
                    force_taker=self._derisk_force_taker,
                )
        if abs(base_amount_diff) > threshold_amount:
            if derisk_only_active:
                trace_derisk = getattr(self, "_trace_derisk", None)
                if callable(trace_derisk):
                    trace_derisk(
                        self.market_data_provider.time(),
                        "rebalance_proposed",
                        required_base_amount=required_base_amount,
                        current_base_amount=current_base_amount,
                        base_amount_diff=base_amount_diff,
                        threshold_amount=threshold_amount,
                    )
            if base_amount_diff > 0:
                return self.create_position_rebalance_order(TradeType.BUY, abs(base_amount_diff))
            return self.create_position_rebalance_order(TradeType.SELL, abs(base_amount_diff))
        if derisk_only_active:
            trace_derisk = getattr(self, "_trace_derisk", None)
            if callable(trace_derisk):
                trace_derisk(
                    self.market_data_provider.time(),
                    "rebalance_skipped_threshold",
                    required_base_amount=required_base_amount,
                    current_base_amount=current_base_amount,
                    base_amount_diff=base_amount_diff,
                    threshold_amount=threshold_amount,
                )
        return None

    def _quantize_price(self, price: Decimal, side: TradeType) -> Decimal:
        rule = self._trading_rule()
        if rule is None or price <= 0:
            return price
        step = Decimal("0")
        for attr in ("min_price_increment", "min_price_tick_size", "price_step", "min_price_step"):
            value = getattr(rule, attr, None)
            if value is not None:
                step = to_decimal(value)
                break
        if step <= 0:
            return price
        rounding = ROUND_DOWN if side == TradeType.BUY else ROUND_UP
        steps = (price / step).to_integral_value(rounding=rounding)
        return max(step, steps * step)

    def _quantize_amount(self, amount: Decimal) -> Decimal:
        rule = self._trading_rule()
        if amount <= 0:
            return amount
        min_amount = Decimal("0")
        step = Decimal("0")
        if rule is not None:
            for attr in ("min_order_size", "min_base_amount", "min_amount"):
                value = getattr(rule, attr, None)
                if value is not None:
                    min_amount = max(min_amount, to_decimal(value))
            for attr in ("min_base_amount_increment", "min_order_size_increment", "amount_step"):
                value = getattr(rule, attr, None)
                if value is not None:
                    step = to_decimal(value)
                    break
        paper_min_amount, paper_step = EppV24Controller._paper_engine_order_size_constraints(self)
        min_amount = max(min_amount, paper_min_amount)
        if paper_step > 0:
            step = max(step, paper_step)
        if min_amount <= 0 and step <= 0:
            return amount
        q_amount = max(amount, min_amount)
        if step > 0:
            units = (q_amount / step).to_integral_value(rounding=ROUND_DOWN)
            q_amount = max(min_amount, units * step)
        return q_amount

    def _quantize_amount_up(self, amount: Decimal) -> Decimal:
        rule = self._trading_rule()
        if amount <= 0:
            return amount
        min_amount = Decimal("0")
        step = Decimal("0")
        if rule is not None:
            for attr in ("min_order_size", "min_base_amount", "min_amount"):
                value = getattr(rule, attr, None)
                if value is not None:
                    min_amount = max(min_amount, to_decimal(value))
            for attr in ("min_base_amount_increment", "min_order_size_increment", "amount_step"):
                value = getattr(rule, attr, None)
                if value is not None:
                    step = to_decimal(value)
                    break
        paper_min_amount, paper_step = EppV24Controller._paper_engine_order_size_constraints(self)
        min_amount = max(min_amount, paper_min_amount)
        if paper_step > 0:
            step = max(step, paper_step)
        if min_amount <= 0 and step <= 0:
            return amount
        q_amount = max(amount, min_amount)
        if step > 0:
            units = (q_amount / step).to_integral_value(rounding=ROUND_UP)
            q_amount = max(min_amount, units * step)
        return q_amount

    def _ensure_fee_config(self, now_ts: float) -> None:
        mode = self.config.fee_mode
        connector = self._connector()
        canonical_name = _canonical_connector_name(self.config.connector_name)

        # Manual/project modes are static after first successful resolution.
        if mode in {"manual", "project"} and self._fee_resolved:
            return
        # In auto mode, allow periodic refresh attempts until API source is obtained.
        if mode == "auto" and self._fee_resolved and self._fee_source.startswith("api:"):
            return
        if self._last_fee_resolve_ts > 0 and (now_ts - self._last_fee_resolve_ts) < self.config.fee_refresh_s:
            return
        self._last_fee_resolve_ts = now_ts

        if mode == "manual":
            self._fee_source = "manual:spot_fee_pct"
            self._maker_fee_pct = to_decimal(self.config.spot_fee_pct)
            self._taker_fee_pct = to_decimal(self.config.spot_fee_pct)
            self._fee_resolved = self._maker_fee_pct > 0
            if not self._fee_resolved:
                self._fee_resolution_error = "manual_fee_non_positive"
            else:
                self._fee_resolution_error = ""
            return

        if mode == "auto":
            live_api = FeeResolver.from_exchange_api(connector, self.config.connector_name, self.config.trading_pair)
            # For framework paper connectors, credentials may only exist on the base connector.
            if live_api is None and self.config.connector_name.endswith("_paper_trade"):
                try:
                    base_connector = self.market_data_provider.get_connector(canonical_name)
                except Exception:
                    base_connector = None
                live_api = FeeResolver.from_exchange_api(base_connector, canonical_name, self.config.trading_pair)
            if live_api is not None:
                self._maker_fee_pct = live_api.maker
                self._taker_fee_pct = live_api.taker
                self._fee_source = live_api.source
                self._fee_resolved = True
                self._fee_resolution_error = ""
                return
            runtime = FeeResolver.from_connector_runtime(connector, self.config.trading_pair)
            if runtime is not None:
                self._maker_fee_pct = runtime.maker
                self._taker_fee_pct = runtime.taker
                self._fee_source = runtime.source
                self._fee_resolved = True
                self._fee_resolution_error = ""
                return

        profile = FeeResolver.from_project_profile(self.config.connector_name, self.config.fee_profile)
        if profile is not None:
            self._maker_fee_pct = profile.maker
            self._taker_fee_pct = profile.taker
            self._fee_source = profile.source
            self._fee_resolved = True
            self._fee_resolution_error = ""
            return

        if self._maker_fee_pct > 0:
            self._fee_source = "manual_fallback:spot_fee_pct"
            self._taker_fee_pct = self._maker_fee_pct
            self._fee_resolved = not self.config.require_fee_resolution
            if self.config.require_fee_resolution:
                self._fee_resolution_error = "resolver_failed_with_require_true"
            else:
                self._fee_resolution_error = ""
        else:
            self._fee_resolution_error = "no_fee_available"
        return

    def _refresh_funding_rate(self, now_ts: float) -> None:
        """Fetch funding rate for perpetual connectors."""
        if "_perpetual" not in self.config.connector_name:
            return
        if now_ts - self._last_funding_rate_ts < self.config.funding_rate_refresh_s:
            return
        self._last_funding_rate_ts = now_ts
        connector = self._connector()
        if connector is None:
            return
        try:
            funding_info = getattr(connector, "get_funding_info", None)
            if callable(funding_info):
                info = funding_info(self.config.trading_pair)
                rate = getattr(info, "rate", None) or getattr(info, "funding_rate", None)
                if rate is not None:
                    self._funding_rate = to_decimal(rate)
                    return
            funding_rates = getattr(connector, "funding_rates", None)
            if isinstance(funding_rates, dict):
                rate = funding_rates.get(self.config.trading_pair)
                if rate is not None:
                    self._funding_rate = to_decimal(rate)
                    return
        except Exception:
            logger.debug("Funding rate fetch failed for %s", self.config.trading_pair)

    def _check_portfolio_risk_guard(self, now_ts: float) -> None:
        """Fail-closed when portfolio_risk_service broadcasts global kill_switch."""
        if not self.config.portfolio_risk_guard_enabled:
            return
        if now_ts - self._last_portfolio_risk_check_ts < float(self.config.portfolio_risk_guard_check_s):
            return
        self._last_portfolio_risk_check_ts = now_ts
        if self._portfolio_risk_hard_stop_latched:
            return
        stream_name = str(self.config.portfolio_risk_stream_name or PORTFOLIO_RISK_STREAM)
        max_age_s = int(self.config.portfolio_risk_guard_max_age_s)
        r = self._get_telemetry_redis()
        if r is None:
            return
        try:
            rows = r.xrevrange(stream_name, "+", "-", count=1)
            if not rows:
                return
            _entry_id, data = rows[0]
            payload_raw = data.get("payload") if isinstance(data, dict) else None
            if not isinstance(payload_raw, str) or not payload_raw:
                return
            import json as _json_pr
            payload = _json_pr.loads(payload_raw)
            if not isinstance(payload, dict):
                return
            if str(payload.get("portfolio_action", "allow")) != "kill_switch":
                return
            ts_ms = float(payload.get("timestamp_ms") or 0)
            if ts_ms > 0:
                age_s = max(0.0, now_ts - ts_ms / 1000.0)
                if age_s > float(max_age_s):
                    return
            scope = payload.get("risk_scope_bots", [])
            if isinstance(scope, list) and scope:
                scope_s = {str(x) for x in scope}
                if self.config.instance_name not in scope_s:
                    return
            self._portfolio_risk_hard_stop_latched = True
            self._ops_guard.force_hard_stop("portfolio_risk_global_breach")
            logger.error(
                "Portfolio risk guard triggered HARD_STOP for %s (stream=%s).",
                self.config.instance_name, stream_name,
            )
        except Exception:
            logger.debug("Portfolio risk guard check failed", exc_info=True)

    def _check_position_reconciliation(self, now_ts: float) -> None:
        """Periodically compare local position with exchange-reported position.

        When drift exceeds the soft-pause threshold, auto-corrects local state
        to match the exchange (source of truth) and saves immediately.
        """
        if now_ts - self._last_position_recon_ts < self.config.position_recon_interval_s:
            return
        self._last_position_recon_ts = now_ts
        connector = self._connector()
        if connector is None:
            return
        try:
            if self._is_perp:
                pos_fn = getattr(connector, "get_position", None) or getattr(connector, "account_positions", None)
                if callable(pos_fn):
                    try:
                        pos = pos_fn(self.config.trading_pair)
                    except TypeError:
                        pos = pos_fn()
                    if hasattr(pos, "amount"):
                        exchange_pos = to_decimal(pos.amount)
                    elif isinstance(pos, dict):
                        exchange_pos = to_decimal(pos.get(self.config.trading_pair, {}).get("amount", 0))
                    else:
                        return
                else:
                    return
            else:
                exchange_pos = self._compute_total_base_with_locked(connector)
            local_pos = self._position_base
            if exchange_pos == _ZERO and local_pos == _ZERO:
                self._position_drift_pct = _ZERO
                return
            ref = max(abs(exchange_pos), abs(local_pos), _MIN_SPREAD)
            self._position_drift_pct = abs(exchange_pos - local_pos) / ref
            if self._position_drift_pct > self.config.position_drift_soft_pause_pct:
                logger.warning(
                    "Position drift %.4f%% exceeds threshold — auto-correcting: "
                    "local=%.8f -> exchange=%.8f",
                    float(self._position_drift_pct * _100), float(local_pos), float(exchange_pos),
                )
                self._position_base = exchange_pos
                self._save_daily_state(force=True)
                self._position_drift_correction_count += 1
                if self._position_drift_correction_count == 1:
                    self._first_drift_correction_ts = now_ts
                elif self._position_drift_correction_count >= 3:
                    if now_ts - self._first_drift_correction_ts < 3600:
                        logger.error("Position drift corrected %d times in %.0fs — HARD_STOP",
                                     self._position_drift_correction_count, now_ts - self._first_drift_correction_ts)
                        self._ops_guard.force_hard_stop("position_drift_repeated")
            else:
                self._position_drift_correction_count = 0
            self._position_recon_fail_count = 0
        except Exception:
            self._position_recon_fail_count += 1
            if self._position_recon_fail_count <= 3:
                logger.warning("Position reconciliation failed (%d consecutive) for %s",
                               self._position_recon_fail_count, self.config.trading_pair, exc_info=True)
            else:
                logger.error("Position reconciliation failing repeatedly (%d) for %s — position may be out of sync",
                             self._position_recon_fail_count, self.config.trading_pair, exc_info=True)

    _STARTUP_SYNC_MAX_RETRIES: int = 10

    def _run_startup_position_sync(self) -> None:
        """On first tick, query the exchange for actual position and adopt it.

        Covers two critical scenarios:
        1. Cross-day restart where daily_state.json day_key doesn't match
           (position_base was already carried forward, but may be stale).
        2. Crash/kill where daily_state.json was never written or is outdated.

        If exchange reports a position that differs from local state, the
        exchange value wins — because the exchange is the source of truth and
        an untracked position can lead to liquidation.

        Retries up to _STARTUP_SYNC_MAX_RETRIES ticks if the connector is not
        ready yet. Blocks order placement via SOFT_PAUSE until sync succeeds.
        """
        if self._startup_position_sync_done:
            return
        if not bool(getattr(self.config, "startup_position_sync", True)):
            self._startup_position_sync_done = True
            logger.info("Startup position sync disabled by config")
            return
        if _config_is_paper(self.config):
            self._startup_position_sync_done = True
            logger.info("Startup position sync auto-skipped in paper mode")
            if not self._startup_orphan_check_done:
                self._startup_orphan_check_done = True
                canceled = EppV24Controller._cancel_orphan_paper_orders_on_startup(self)
                if canceled > 0:
                    logger.warning(
                        "Startup orphan paper-order cleanup canceled %d restored order(s) for %s; "
                        "fresh runtime executors will re-quote on the next tick.",
                        canceled,
                        self.config.trading_pair,
                    )
                else:
                    logger.info(
                        "Startup orphan paper-order cleanup found no restored orders for %s",
                        self.config.trading_pair,
                    )
            return
        provider = getattr(self, "market_data_provider", None)
        now_ts = float(provider.time()) if provider is not None else float(_time_mod.time())
        if self._startup_sync_first_ts <= 0:
            self._startup_sync_first_ts = now_ts
        if now_ts - self._startup_sync_first_ts >= float(getattr(self.config, "startup_sync_timeout_s", 180.0)):
            self._startup_position_sync_done = True
            self._ops_guard.force_hard_stop("startup_sync_timeout")
            logger.error(
                "Startup position sync TIMED OUT after %.0fs (retries=%d). HARD_STOP activated.",
                now_ts - self._startup_sync_first_ts,
                self._startup_sync_retries,
            )
            return
        connector = self._connector()
        if connector is None:
            self._startup_sync_retries += 1
            if self._startup_sync_retries >= self._STARTUP_SYNC_MAX_RETRIES:
                self._startup_position_sync_done = True
                self._ops_guard.force_hard_stop("startup_sync_failed")
                logger.error(
                    "Startup position sync FAILED after %d retries: connector never became available. "
                    "HARD_STOP activated — position may be out of sync with exchange.",
                    self._startup_sync_retries,
                )
            else:
                logger.warning(
                    "Startup position sync deferred: connector not available (attempt %d/%d)",
                    self._startup_sync_retries, self._STARTUP_SYNC_MAX_RETRIES,
                )
            return
        try:
            exchange_pos: Optional[Decimal] = None
            if self._is_perp:
                pos_fn = getattr(connector, "get_position", None) or getattr(connector, "account_positions", None)
                if callable(pos_fn):
                    try:
                        pos = pos_fn(self.config.trading_pair)
                    except TypeError:
                        pos = pos_fn()
                    if hasattr(pos, "amount"):
                        exchange_pos = to_decimal(pos.amount)
                        # If the connector exposes an entry price (live perp or PaperDesk v2),
                        # adopt it so PnL/avg entry are consistent immediately after restart.
                        try:
                            entry_px = getattr(pos, "entry_price", None) or getattr(pos, "avg_entry_price", None)
                            entry_px_d = to_decimal(entry_px) if entry_px is not None else _ZERO
                            if entry_px_d > _ZERO:
                                if self._avg_entry_price <= _ZERO:
                                    self._avg_entry_price = entry_px_d
                                else:
                                    drift = abs(self._avg_entry_price - entry_px_d) / max(entry_px_d, _MIN_SPREAD)
                                    if drift > Decimal("0.001"):  # >10 bps drift: trust connector
                                        self._avg_entry_price = entry_px_d
                        except Exception:
                            logger.debug("Entry price extraction failed", exc_info=True)
                    elif isinstance(pos, dict):
                        entry = pos.get(self.config.trading_pair, {})
                        exchange_pos = to_decimal(entry.get("amount", 0)) if isinstance(entry, dict) else None
            else:
                exchange_pos = self._compute_total_base_with_locked(connector)
            if exchange_pos is None:
                self._startup_sync_retries += 1
                if self._startup_sync_retries >= self._STARTUP_SYNC_MAX_RETRIES:
                    self._startup_position_sync_done = True
                    self._ops_guard.force_hard_stop("startup_sync_failed")
                    logger.error(
                        "Startup position sync FAILED: could not read exchange position after %d attempts. HARD_STOP activated.",
                        self._startup_sync_retries,
                    )
                else:
                    logger.warning("Startup position sync: could not read exchange position (attempt %d/%d)", self._startup_sync_retries, self._STARTUP_SYNC_MAX_RETRIES)
                return
            self._startup_position_sync_done = True
            local_pos = self._position_base
            if exchange_pos == local_pos:
                logger.info(
                    "Startup position sync OK: local=%.8f matches exchange",
                    float(local_pos),
                )
                return
            if exchange_pos == _ZERO and local_pos == _ZERO:
                return
            ref = max(abs(exchange_pos), abs(local_pos), _MIN_SPREAD)
            drift_pct = abs(exchange_pos - local_pos) / ref
            logger.warning(
                "STARTUP POSITION SYNC: adopting exchange position. "
                "local=%.8f -> exchange=%.8f (drift=%.4f%%)",
                float(local_pos), float(exchange_pos), float(drift_pct * _100),
            )
            if local_pos == _ZERO and exchange_pos != _ZERO:
                logger.warning(
                    "ORPHAN POSITION DETECTED on exchange (%.8f %s). "
                    "Bot had no local record. Adopting to prevent untracked liquidation risk.",
                    float(exchange_pos), self.config.trading_pair,
                )
            self._position_base = exchange_pos
            if self._avg_entry_price == _ZERO and exchange_pos != _ZERO:
                mid = self._get_mid_price()
                if mid > _ZERO:
                    self._avg_entry_price = mid
                    logger.info("Startup sync: avg_entry_price set to current mid %.2f (no prior entry price)", float(mid))
            self._position_drift_pct = drift_pct
            self._save_daily_state(force=True)
        except Exception:
            self._startup_sync_retries += 1
            if self._startup_sync_retries >= self._STARTUP_SYNC_MAX_RETRIES:
                self._startup_position_sync_done = True
                self._ops_guard.force_hard_stop("startup_sync_failed")
                logger.error(
                    "Startup position sync FAILED with repeated exceptions (%d attempts). HARD_STOP activated.",
                    self._startup_sync_retries,
                    exc_info=True,
                )
            else:
                logger.warning(
                    "Startup position sync failed for %s (attempt %d/%d)",
                    self.config.trading_pair, self._startup_sync_retries, self._STARTUP_SYNC_MAX_RETRIES,
                    exc_info=True,
                )
        finally:
            if self._startup_position_sync_done and not self._startup_orphan_check_done:
                self._startup_orphan_check_done = True
                if _config_is_paper(self.config):
                    canceled = EppV24Controller._cancel_orphan_paper_orders_on_startup(self)
                    if canceled > 0:
                        logger.warning(
                            "Startup orphan paper-order cleanup canceled %d restored order(s) for %s; "
                            "fresh runtime executors will re-quote on the next tick.",
                            canceled,
                            self.config.trading_pair,
                        )
                    else:
                        logger.info(
                            "Startup orphan paper-order cleanup found no restored orders for %s",
                            self.config.trading_pair,
                        )
                else:
                    logger.warning(
                        "Orphan order check: manual verification recommended on exchange UI "
                        "for %s — framework does not expose open orders at controller level. "
                        "If stale limit/stop orders exist from a previous session, cancel them manually.",
                        self.config.trading_pair,
                    )

    def _get_mid_price(self) -> Decimal:
        return self._runtime_adapter.get_mid_price()

    def _get_balances(self) -> Tuple[Decimal, Decimal]:
        return self._runtime_adapter.get_balances()

    def _compute_equity_and_base_pcts(self, mid: Decimal) -> Tuple[Decimal, Decimal, Decimal]:
        base_bal, quote_bal = self._get_balances()
        paper_snap = self._paper_portfolio_snapshot(mid)
        if self._is_perp:
            pos_base = self._position_base if abs(self._position_base) > _BALANCE_EPSILON else base_bal
            pos_gross_base = (
                to_decimal(getattr(self, "_position_gross_base", _ZERO))
                if abs(to_decimal(getattr(self, "_position_gross_base", _ZERO))) > _BALANCE_EPSILON
                else abs(pos_base)
            )
            use_paper_equity = _config_is_paper(self.config) and bool(
                getattr(self.config, "paper_use_portfolio_equity_for_risk", False)
            )
            position_mode = str(getattr(self.config, "position_mode", "ONEWAY") or "ONEWAY").upper()
            if use_paper_equity and isinstance(paper_snap, dict):
                paper_pos = to_decimal(paper_snap.get("position_base", pos_base))
                paper_pos_gross = to_decimal(paper_snap.get("position_gross_base", abs(paper_pos)))
                position_mode = str(paper_snap.get("position_mode", position_mode) or position_mode).upper()
                paper_eq = to_decimal(paper_snap.get("equity_quote", _ZERO))
                if abs(paper_pos) > _BALANCE_EPSILON:
                    pos_base = paper_pos
                if paper_pos_gross > _BALANCE_EPSILON:
                    pos_gross_base = paper_pos_gross
                if position_mode != "HEDGE":
                    pos_gross_base = abs(pos_base)
                equity = paper_eq if paper_eq > _ZERO else (quote_bal if quote_bal > _ZERO else abs(pos_base) * mid)
                gross_value = paper_pos_gross * mid
            else:
                if position_mode != "HEDGE":
                    pos_gross_base = abs(pos_base)
                equity = quote_bal if quote_bal > _ZERO else abs(pos_base) * mid
                gross_value = pos_gross_base * mid
            if position_mode != "HEDGE":
                gross_value = abs(pos_base) * mid
            net_value = pos_base * mid
            base_pct_gross = gross_value / equity if equity > _ZERO else _ZERO
            base_pct_net = net_value / equity if equity > _ZERO else _ZERO
            try:
                self._refresh_margin_ratio(mid, pos_base, quote_bal, gross_base=pos_gross_base)
            except TypeError:
                self._refresh_margin_ratio(mid, pos_base, quote_bal)
        else:
            equity = quote_bal + base_bal * mid
            base_pct_gross = (base_bal * mid) / equity if equity > _ZERO else _ZERO
            base_pct_net = base_pct_gross
        if equity <= _ZERO:
            return _ZERO, _ZERO, _ZERO
        return equity, base_pct_gross, base_pct_net

    def _refresh_margin_ratio(
        self,
        mid: Decimal,
        base_bal: Decimal,
        quote_bal: Decimal,
        gross_base: Optional[Decimal] = None,
    ) -> None:
        """Update margin ratio for perp connectors."""
        if not self._is_perp:
            return
        connector = self._connector()
        if connector is None:
            return
        try:
            margin_info = getattr(connector, "get_margin_info", None)
            if callable(margin_info):
                info = margin_info(self.config.trading_pair)
                ratio = getattr(info, "margin_ratio", None)
                if ratio is not None:
                    self._margin_ratio = to_decimal(ratio)
                    return
        except Exception:
            logger.debug("Margin info read failed for %s", self.config.trading_pair, exc_info=True)
        position_notional = max(abs(base_bal), to_decimal(gross_base or _ZERO)) * mid
        if position_notional > _ZERO and quote_bal > _ZERO:
            # margin_ratio = available_margin / required_margin.
            # required_margin = position_notional / leverage (initial margin).
            # Without leverage correction this reads optimistically high at leverage > 1.
            leverage_d = Decimal(max(1, int(self.config.leverage)))
            self._margin_ratio = (quote_bal * leverage_d) / position_notional
        else:
            self._margin_ratio = _ONE

    def _connector_ready(self) -> bool:
        return self._runtime_adapter.ready()

    def _balances_consistent(self) -> bool:
        return self._runtime_adapter.balances_consistent()

    def _compute_total_base_with_locked(self, connector: Any) -> Decimal:
        """Available base + base locked in open sell orders.

        For spot-style connectors ``get_balance()`` returns *available* balance only,
        excluding base locked in open sell orders. This method adds back the locked
        portion so reconciliation and startup sync see the true total position.
        """
        base_asset = self._runtime_adapter._base_asset
        total = to_decimal(connector.get_balance(base_asset))
        try:
            open_orders_fn = getattr(connector, "get_open_orders", None)
            if callable(open_orders_fn):
                for o in (open_orders_fn() or []):
                    if str(getattr(o, "trading_pair", "")) != self.config.trading_pair:
                        continue
                    side_str = str(getattr(o, "trade_type", None) or getattr(o, "side", None)).lower()
                    if "sell" not in side_str:
                        continue
                    amt = getattr(o, "amount", None) or getattr(o, "quantity", None) or getattr(o, "base_asset_amount", None)
                    if amt is None:
                        continue
                    executed = getattr(o, "executed_amount_base", None) or getattr(o, "filled_amount", None) or getattr(o, "executed_amount", None)
                    remaining = to_decimal(amt) - to_decimal(executed or 0)
                    if remaining > _ZERO:
                        total += remaining
        except Exception:
            logger.debug("Locked-base scan failed for %s", self.config.trading_pair, exc_info=True)
        return total

    def _cancel_per_min(self, now: float) -> int:
        recent = [ts for ts in self._cancel_events_ts if now - ts <= 60.0]
        self._cancel_events_ts = recent
        return len(recent)

    def _min_notional_quote(self) -> Decimal:
        rule = self._trading_rule()
        if rule is None:
            return Decimal("0")
        for attr in ("min_notional_size", "min_notional", "min_order_value"):
            value = getattr(rule, attr, None)
            if value is not None:
                return to_decimal(value)
        return Decimal("0")

    def _paper_engine_order_size_constraints(self) -> Tuple[Decimal, Decimal]:
        """Return PaperDesk (min_base, base_step) constraints when available."""
        if not _config_is_paper(self.config):
            return _ZERO, _ZERO
        try:
            connector = self._connector()
        except Exception:
            return _ZERO, _ZERO
        desk = getattr(connector, "_paper_desk_v2", None)
        instrument_id = getattr(connector, "_paper_desk_v2_instrument_id", None)
        if desk is None or instrument_id is None:
            strategy = getattr(self, "strategy", None) or getattr(self, "_strategy", None)
            bridges = getattr(strategy, "_paper_desk_v2_bridges", {}) if strategy is not None else {}
            if isinstance(bridges, dict):
                bridge = bridges.get(str(self.config.connector_name), {})
                if isinstance(bridge, dict):
                    desk = bridge.get("desk", desk)
                    instrument_id = bridge.get("instrument_id", instrument_id)
        if desk is None or instrument_id is None:
            return _ZERO, _ZERO
        try:
            key = str(getattr(instrument_id, "key", "") or instrument_id)
            spec = None
            specs = getattr(desk, "_specs", None)
            if isinstance(specs, dict):
                spec = specs.get(key)
            if spec is None:
                engines = getattr(desk, "_engines", None)
                if isinstance(engines, dict):
                    engine = engines.get(key)
                    spec = getattr(engine, "_spec", None) if engine is not None else None
            if spec is None:
                return _ZERO, _ZERO
            min_qty = max(_ZERO, to_decimal(getattr(spec, "min_quantity", _ZERO)))
            size_step = max(_ZERO, to_decimal(getattr(spec, "size_increment", _ZERO)))
            return max(min_qty, size_step), size_step
        except Exception:
            logger.debug("Paper size constraints lookup failed", exc_info=True)
            return _ZERO, _ZERO

    def _min_base_amount(self, ref_price: Decimal) -> Decimal:
        min_base = _ZERO
        quote_min = EppV24Controller._min_notional_quote(self)
        if quote_min > 0 and ref_price > 0:
            min_base = max(min_base, quote_min / ref_price)
        rule = self._trading_rule()
        if rule is not None:
            for attr in ("min_order_size", "min_base_amount", "min_amount"):
                value = getattr(rule, attr, None)
                if value is not None:
                    min_base = max(min_base, to_decimal(value))
        paper_min_base, _ = EppV24Controller._paper_engine_order_size_constraints(self)
        min_base = max(min_base, paper_min_base)
        return min_base

    def _project_total_amount_quote(
        self,
        equity_quote: Decimal,
        mid: Decimal,
        quote_size_pct: Decimal,
        total_levels: int,
        size_mult: Decimal = _ONE,
    ) -> Decimal:
        level_count = max(0, int(total_levels))
        if level_count <= 0:
            return _ZERO
        safe_mult = max(_ONE, to_decimal(size_mult))
        per_order_quote = max(self._min_notional_quote(), equity_quote * quote_size_pct * safe_mult)
        if self.config.max_order_notional_quote > 0:
            per_order_quote = min(per_order_quote, self.config.max_order_notional_quote)
        projected = per_order_quote * Decimal(level_count)
        if self.config.max_total_notional_quote > 0:
            projected = min(projected, self.config.max_total_notional_quote)
        min_base = self._min_base_amount(mid)
        if min_base > 0 and mid > 0 and projected > 0:
            min_total_quote = min_base * mid * Decimal(level_count)
            if projected < min_total_quote:
                projected = min_total_quote
        if self.config.max_total_notional_quote > 0:
            projected = min(projected, self.config.max_total_notional_quote)
        return projected

    def _risk_loss_metrics(self, equity_quote: Decimal) -> Tuple[Decimal, Decimal]:
        open_equity = self._daily_equity_open or equity_quote
        peak_equity = self._daily_equity_peak or equity_quote
        return RiskEvaluator.risk_loss_metrics(equity_quote, open_equity, peak_equity)

    def _risk_policy_checks(
        self,
        base_pct: Decimal,
        turnover_x: Decimal,
        projected_total_quote: Decimal,
        daily_loss_pct: Decimal,
        drawdown_pct: Decimal,
    ) -> Tuple[List[str], bool]:
        return self._risk_evaluator.risk_policy_checks(
            base_pct=base_pct, turnover_x=turnover_x,
            projected_total_quote=projected_total_quote,
            daily_loss_pct=daily_loss_pct, drawdown_pct=drawdown_pct,
        )

    def _edge_gate_update(
        self,
        now_ts: float,
        net_edge: Decimal,
        pause_threshold: Decimal,
        resume_threshold: Decimal,
    ) -> None:
        self._risk_evaluator.edge_gate_update(now_ts, net_edge, pause_threshold, resume_threshold)
        self._edge_gate_blocked = self._risk_evaluator.edge_gate_blocked

    def _compute_spread_and_edge(
        self,
        now_ts: float,
        regime_name: str,
        regime_spec: RegimeSpec,
        target_base_pct: Decimal,
        base_pct: Decimal,
        equity_quote: Decimal,
        *,
        band_pct: Optional[Decimal] = None,
    ) -> SpreadEdgeState:
        # Use the band_pct from regime detection when provided so spread/edge,
        # regime classification, and is_high_vol all reference the same ATR source.
        # Falls back to price-buffer when called without a pre-computed value
        # (e.g. from unit tests that call this method directly).
        if band_pct is None:
            band_pct = self._price_buffer.band_pct(self.config.atr_period) or _ZERO
        self._update_adaptive_history(band_pct=band_pct)
        raw_drift = self._price_buffer.adverse_drift_30s(now_ts)
        drift_alpha = _clip(to_decimal(self.config.adverse_drift_ewma_alpha), Decimal("0.05"), Decimal("0.95"))
        smooth_drift = self._price_buffer.adverse_drift_smooth(now_ts, drift_alpha)
        adaptive_min_edge_pct, adaptive_market_floor_pct, adaptive_vol_ratio = self._compute_adaptive_spread_knobs(
            now_ts, equity_quote, regime_name
        )

        state, floor = self._spread_engine.compute_spread_and_edge(
            regime_name=regime_name,
            regime_spec=regime_spec,
            band_pct=band_pct,
            raw_drift=raw_drift,
            smooth_drift=smooth_drift,
            target_base_pct=target_base_pct,
            base_pct=base_pct,
            equity_quote=equity_quote,
            traded_notional_today=self._traded_notional_today,
            ob_imbalance=self._ob_imbalance,
            ob_imbalance_skew_weight=self.config.ob_imbalance_skew_weight,
            maker_fee_pct=self._maker_fee_pct,
            is_perp=self._is_perp,
            funding_rate=self._funding_rate,
            adverse_fill_count=self._adverse_fill_count,
            fill_edge_ewma=self._fill_edge_ewma,
            override_spread_pct=self.config.override_spread_pct if self.config.override_spread_pct is not None else None,
            min_edge_threshold_override_pct=adaptive_min_edge_pct,
            market_spread_floor_pct=adaptive_market_floor_pct,
            adaptive_vol_ratio=adaptive_vol_ratio,
        )
        self._spread_floor_pct = floor
        self._last_spread_state = state
        return state

    def _update_adaptive_history(
        self,
        *,
        band_pct: Optional[Decimal] = None,
        market_spread_pct: Optional[Decimal] = None,
    ) -> None:
        """Update EWMA history used by adaptive spread/edge logic."""
        if not self.config.adaptive_params_enabled:
            return
        if band_pct is not None and band_pct >= _ZERO:
            alpha_band = _clip(to_decimal(self.config.adaptive_band_ewma_alpha), Decimal("0.01"), Decimal("0.50"))
            if self._band_pct_ewma <= _ZERO:
                self._band_pct_ewma = band_pct
            else:
                self._band_pct_ewma = alpha_band * band_pct + (_ONE - alpha_band) * self._band_pct_ewma
        if market_spread_pct is not None and market_spread_pct >= _ZERO:
            spread_bps = market_spread_pct * _10K
            alpha_spread = _clip(to_decimal(self.config.adaptive_market_spread_ewma_alpha), Decimal("0.01"), Decimal("0.50"))
            if self._market_spread_bps_ewma <= _ZERO:
                self._market_spread_bps_ewma = spread_bps
            else:
                self._market_spread_bps_ewma = alpha_spread * spread_bps + (_ONE - alpha_spread) * self._market_spread_bps_ewma

    def _compute_adaptive_spread_knobs(
        self, now_ts: float, equity_quote: Decimal, regime_name: str = "neutral_low_vol"
    ) -> Tuple[Optional[Decimal], Optional[Decimal], Optional[Decimal]]:
        """Compute adaptive edge floor and spread knobs with strict safety bounds."""
        selective_metrics = EppV24Controller._compute_selective_quote_quality(self, regime_name)
        selective_state = str(selective_metrics["state"])
        selective_score = to_decimal(selective_metrics["score"])
        if not self.config.adaptive_params_enabled:
            base_min_edge_pct = Decimal(self.config.min_net_edge_bps) / _10K
            self._adaptive_effective_min_edge_pct = base_min_edge_pct
            self._adaptive_fill_age_s = _ZERO
            self._adaptive_market_floor_pct = _ZERO
            self._adaptive_vol_ratio = _ZERO
            self._pnl_governor_active = False
            self._pnl_governor_day_progress = _ZERO
            self._pnl_governor_target_pnl_pct = _ZERO
            self._pnl_governor_target_pnl_quote = _ZERO
            self._pnl_governor_expected_pnl_quote = _ZERO
            self._pnl_governor_actual_pnl_quote = _ZERO
            self._pnl_governor_deficit_ratio = _ZERO
            self._pnl_governor_edge_relax_bps = _ZERO
            self._pnl_governor_size_mult = _ONE
            self._pnl_governor_size_boost_active = False
            self._pnl_governor_target_mode = "disabled"
            self._pnl_governor_target_source = "none"
            self._pnl_governor_target_equity_open_quote = _ZERO
            self._pnl_governor_target_effective_pct = _ZERO
            self._pnl_governor_activation_reason = "adaptive_params_disabled"
            self._pnl_governor_size_boost_reason = "adaptive_params_disabled"
            EppV24Controller._increment_governor_reason_count(
                self, "_pnl_governor_activation_reason_counts", "adaptive_params_disabled"
            )
            EppV24Controller._increment_governor_reason_count(
                self, "_pnl_governor_size_boost_reason_counts", "adaptive_params_disabled"
            )
            return None, None, None

        target_age_s = Decimal(max(60, int(self.config.adaptive_fill_target_age_s)))
        fill_age_s = target_age_s * Decimal("2")
        if self._last_fill_ts > 0:
            fill_age_s = max(_ZERO, to_decimal(now_ts - self._last_fill_ts))
        stale_ratio = _clip((fill_age_s - target_age_s) / target_age_s, _ZERO, _ONE)
        fast_ratio = _ZERO
        if fill_age_s < (target_age_s / Decimal("3")):
            fast_ratio = _clip((_ONE - (fill_age_s / (target_age_s / Decimal("3")))), _ZERO, _ONE)

        market_edge_bonus_bps = _clip(
            self._market_spread_bps_ewma * to_decimal(self.config.adaptive_market_edge_bonus_factor),
            _ZERO,
            to_decimal(self.config.adaptive_market_edge_bonus_cap_bps),
        )
        vol_ratio = _ZERO
        if self.config.high_vol_band_pct > _ZERO and self._band_pct_ewma > _ZERO:
            vol_ratio = _clip(self._band_pct_ewma / self.config.high_vol_band_pct, _ZERO, _ONE)
        vol_edge_bonus_bps = vol_ratio * to_decimal(self.config.adaptive_vol_edge_bonus_cap_bps)
        edge_relax_bps = stale_ratio * to_decimal(self.config.adaptive_edge_relax_max_bps)
        if EppV24Controller._fill_edge_below_cost_floor(self):
            # Do not lower the entry standard just because fills are stale when
            # recent realized edge already says the strategy is trading below cost.
            edge_relax_bps = _ZERO
        elif selective_state == "blocked":
            edge_relax_bps = _ZERO
        edge_tighten_bps = fast_ratio * to_decimal(self.config.adaptive_edge_tighten_max_bps)
        selective_edge_tighten_bps = _ZERO
        if selective_state != "inactive":
            selective_edge_tighten_bps = selective_score * to_decimal(
                getattr(self.config, "selective_quality_edge_tighten_max_bps", Decimal("0"))
            )
            if regime_name == "neutral_low_vol":
                selective_edge_tighten_bps += max(
                    _ZERO,
                    to_decimal(getattr(self.config, "selective_neutral_extra_edge_bps", Decimal("0"))),
                )

        base_min_edge_bps = Decimal(self.config.min_net_edge_bps)
        effective_min_edge_bps = (
            base_min_edge_bps
            + market_edge_bonus_bps
            + vol_edge_bonus_bps
            + edge_tighten_bps
            + selective_edge_tighten_bps
            - edge_relax_bps
        )

        # Daily PnL governor: when behind target by more than a buffer, relax min-edge
        # threshold to increase fill probability while preserving bounded risk controls.
        governor_active = False
        governor_day_progress = _ZERO
        external_daily_target_pct_override = getattr(self, "_external_daily_pnl_target_pct_override", None)
        governor_target_override_pct = (
            max(_ZERO, to_decimal(external_daily_target_pct_override))
            if external_daily_target_pct_override is not None
            else None
        )
        governor_target_pct = (
            governor_target_override_pct
            if governor_target_override_pct is not None
            else max(_ZERO, to_decimal(self.config.daily_pnl_target_pct))
        )
        open_equity = self._daily_equity_open if self._daily_equity_open is not None else equity_quote
        open_equity = max(_ZERO, to_decimal(open_equity))
        governor_target_quote = (
            open_equity * (governor_target_pct / Decimal("100"))
            if governor_target_pct > _ZERO and open_equity > _ZERO
            else max(_ZERO, to_decimal(self.config.daily_pnl_target_quote))
        )
        governor_expected_quote = _ZERO
        governor_actual_quote = equity_quote - open_equity
        governor_deficit_ratio = _ZERO
        governor_edge_relax_bps = _ZERO
        governor_target_mode = "disabled"
        governor_target_source = (
            "execution_intent_daily_pnl_target_pct"
            if governor_target_override_pct is not None
            else "none"
        )
        governor_target_effective_pct = _ZERO
        governor_activation_reason = "governor_disabled"
        if governor_target_pct > _ZERO:
            governor_target_mode = "pct_equity"
            if governor_target_source == "none":
                governor_target_source = "daily_pnl_target_pct"
            governor_target_effective_pct = governor_target_pct
        elif governor_target_quote > _ZERO and open_equity > _ZERO:
            governor_target_mode = "quote_legacy"
            governor_target_source = "daily_pnl_target_quote"
            governor_target_effective_pct = (governor_target_quote / open_equity) * Decimal("100")
        if self.config.pnl_governor_enabled and governor_target_quote > _ZERO:
            dt = datetime.fromtimestamp(now_ts, tz=timezone.utc)
            seconds_today = Decimal(dt.hour * 3600 + dt.minute * 60 + dt.second)
            governor_day_progress = _clip(seconds_today / Decimal(86400), _ZERO, _ONE)
            governor_expected_quote = governor_target_quote * governor_day_progress
            deficit_quote = governor_expected_quote - governor_actual_quote
            activation_buffer_quote = governor_target_quote * _clip(
                to_decimal(self.config.pnl_governor_activation_buffer_pct), _ZERO, Decimal("0.50")
            )
            if deficit_quote > activation_buffer_quote:
                if EppV24Controller._fill_edge_below_cost_floor(self):
                    governor_activation_reason = "fill_edge_below_cost_floor"
                elif selective_state != "inactive":
                    governor_activation_reason = "selective_quote_filter"
                elif stale_ratio > _ZERO:
                    # Stale-fill relaxation already lowers the entry threshold to
                    # recover cadence. Avoid stacking a second discount from the
                    # daily governor, which can collapse the effective min-edge
                    # all the way to the hard floor.
                    governor_activation_reason = "stale_fill_relaxation_active"
                else:
                    governor_active = True
                    governor_activation_reason = "active"
                    governor_deficit_ratio = _clip(deficit_quote / governor_target_quote, _ZERO, _ONE)
                    governor_edge_relax_bps = governor_deficit_ratio * max(
                        _ZERO, to_decimal(self.config.pnl_governor_max_edge_bps_cut)
                    )
                    effective_min_edge_bps -= governor_edge_relax_bps
            else:
                governor_activation_reason = "within_activation_buffer"
        elif self.config.pnl_governor_enabled:
            governor_activation_reason = "no_target"

        effective_min_edge_bps = _clip(
            effective_min_edge_bps,
            to_decimal(self.config.adaptive_min_edge_bps_floor),
            to_decimal(self.config.adaptive_min_edge_bps_cap),
        )
        effective_min_edge_pct = effective_min_edge_bps / _10K

        market_floor_pct = (self._market_spread_bps_ewma / _10K) * to_decimal(self.config.adaptive_market_floor_factor)
        market_floor_pct = max(_ZERO, market_floor_pct)

        self._adaptive_effective_min_edge_pct = effective_min_edge_pct
        self._adaptive_fill_age_s = fill_age_s
        self._adaptive_market_floor_pct = market_floor_pct
        self._adaptive_vol_ratio = vol_ratio
        self._pnl_governor_active = governor_active
        self._pnl_governor_day_progress = governor_day_progress
        self._pnl_governor_target_pnl_pct = governor_target_pct
        self._pnl_governor_target_pnl_quote = governor_target_quote
        self._pnl_governor_expected_pnl_quote = governor_expected_quote
        self._pnl_governor_actual_pnl_quote = governor_actual_quote
        self._pnl_governor_deficit_ratio = governor_deficit_ratio
        self._pnl_governor_edge_relax_bps = governor_edge_relax_bps
        self._pnl_governor_target_mode = governor_target_mode
        self._pnl_governor_target_source = governor_target_source
        self._pnl_governor_target_equity_open_quote = open_equity
        self._pnl_governor_target_effective_pct = governor_target_effective_pct
        self._pnl_governor_activation_reason = governor_activation_reason
        EppV24Controller._increment_governor_reason_count(
            self, "_pnl_governor_activation_reason_counts", governor_activation_reason
        )
        return effective_min_edge_pct, market_floor_pct, vol_ratio

    def _evaluate_market_conditions(self, now_ts: float, band_pct: Decimal) -> MarketConditions:
        """Build market condition snapshot with reconnect-aware stale-book detection."""
        is_high_vol = band_pct >= self.config.high_vol_band_pct
        bid_p, ask_p, market_spread_pct, best_bid_size, best_ask_size = self._get_top_of_book()
        if self.config.ob_imbalance_skew_weight > _ZERO:
            self._ob_imbalance = self._compute_ob_imbalance(self.config.ob_imbalance_depth)

        connector_ready_now = self._connector_ready()
        if not self._last_connector_ready and connector_ready_now:
            self._ws_reconnect_count += 1
            self._reconnect_cooldown_until = now_ts + self.config.reconnect_cooldown_s
            reconnect_grace_s = max(0.0, float(self.config.order_book_reconnect_grace_s))
            self._book_reconnect_grace_until_ts = now_ts + reconnect_grace_s
            # Reset stale clock at reconnect boundary; keep fail-closed logic for true long stale windows.
            if self._book_stale_since_ts > 0.0:
                self._book_stale_since_ts = now_ts
            logger.info("Connector reconnected (count=%d), cooldown %.0fs",
                        self._ws_reconnect_count, self.config.reconnect_cooldown_s)
        self._last_connector_ready = connector_ready_now

        if bid_p > _ZERO and ask_p > _ZERO:
            # Treat the book as "fresh" if either top prices OR top sizes change.
            # Price-only checks trigger false staleness during calm markets.
            if (
                bid_p == self._last_book_bid
                and ask_p == self._last_book_ask
                and best_bid_size == self._last_book_bid_size
                and best_ask_size == self._last_book_ask_size
            ):
                if self._book_stale_since_ts <= 0:
                    self._book_stale_since_ts = now_ts
            else:
                self._book_stale_since_ts = 0.0
                self._last_book_bid = bid_p
                self._last_book_ask = ask_p
                self._last_book_bid_size = best_bid_size
                self._last_book_ask_size = best_ask_size
        order_book_stale = self._is_order_book_stale(now_ts)
        market_spread_threshold = Decimal(self.config.min_market_spread_bps) / _10K
        market_spread_too_small = (
            self.config.min_market_spread_bps > 0 and market_spread_pct > 0 and market_spread_pct < market_spread_threshold
        )

        # Keep a tiny absolute floor to avoid zero-distance quoting edge cases.
        side_spread_floor = max(Decimal("0.000001"), to_decimal(self.config.min_side_spread_bps) / _10K)
        if market_spread_pct > 0:
            half_market = market_spread_pct / _TWO + side_spread_floor
            if half_market > side_spread_floor:
                side_spread_floor = half_market

        return MarketConditions(
            is_high_vol=is_high_vol,
            bid_p=bid_p,
            ask_p=ask_p,
            market_spread_pct=market_spread_pct,
            best_bid_size=best_bid_size,
            best_ask_size=best_ask_size,
            connector_ready=connector_ready_now,
            order_book_stale=order_book_stale,
            market_spread_too_small=market_spread_too_small,
            side_spread_floor=side_spread_floor,
        )

    def _order_book_stale_age_s(self, now_ts: float) -> float:
        if self._book_stale_since_ts <= 0.0:
            return 0.0
        return max(0.0, float(now_ts) - float(self._book_stale_since_ts))

    def _is_order_book_stale(self, now_ts: float) -> bool:
        if self._book_stale_since_ts <= 0.0:
            return False
        if float(now_ts) < float(getattr(self, "_book_reconnect_grace_until_ts", 0.0) or 0.0):
            return False
        stale_after_s = (
            max(5.0, float(self.config.order_book_stale_after_s))
            + max(0.0, float(self.config.max_clock_skew_s))
        )
        return self._order_book_stale_age_s(now_ts) > stale_after_s

    def _build_tick_snapshot(self, equity_quote: Decimal) -> Dict[str, Any]:
        """Gather controller-level state into a snapshot dict for TickEmitter."""
        adapter_stats: Dict[str, Any] = {}
        connector = self._connector()
        if connector is not None and hasattr(connector, "paper_stats"):
            try:
                adapter_stats = dict(connector.paper_stats)
            except Exception:
                adapter_stats = {}
        self._paper_fill_count = int(adapter_stats.get("paper_fill_count", Decimal("0")))
        self._paper_reject_count = int(adapter_stats.get("paper_reject_count", Decimal("0")))
        self._paper_avg_queue_delay_ms = to_decimal(adapter_stats.get("paper_avg_queue_delay_ms", Decimal("0")))

        return {
            "spread_multiplier": self.config.adverse_fill_spread_multiplier if (
                self._adverse_fill_count >= self.config.adverse_fill_count_threshold
                and self._fill_edge_ewma is not None
            ) else _ONE,
            "spread_floor_pct": self._spread_floor_pct,
            "base_spread_pct": getattr(getattr(self, "_last_spread_state", None), "quote_geometry", None).base_spread_pct
            if getattr(getattr(self, "_last_spread_state", None), "quote_geometry", None) is not None
            else _ZERO,
            "reservation_price_adjustment_pct": getattr(getattr(self, "_last_spread_state", None), "quote_geometry", None).reservation_price_adjustment_pct
            if getattr(getattr(self, "_last_spread_state", None), "quote_geometry", None) is not None
            else _ZERO,
            "inventory_skew_pct": getattr(getattr(self, "_last_spread_state", None), "quote_geometry", None).inventory_skew
            if getattr(getattr(self, "_last_spread_state", None), "quote_geometry", None) is not None
            else _ZERO,
            "alpha_skew_pct": getattr(getattr(self, "_last_spread_state", None), "quote_geometry", None).alpha_skew
            if getattr(getattr(self, "_last_spread_state", None), "quote_geometry", None) is not None
            else _ZERO,
            "inventory_urgency_pct": self._inventory_urgency_score,
            "adaptive_effective_min_edge_pct": self._adaptive_effective_min_edge_pct,
            "adaptive_fill_age_s": self._adaptive_fill_age_s,
            "adaptive_market_spread_bps_ewma": self._market_spread_bps_ewma,
            "adaptive_band_pct_ewma": self._band_pct_ewma,
            "adaptive_market_floor_pct": self._adaptive_market_floor_pct,
            "adaptive_vol_ratio": self._adaptive_vol_ratio,
            "pnl_governor_active": self._pnl_governor_active,
            "pnl_governor_day_progress": self._pnl_governor_day_progress,
            "pnl_governor_target_pnl_pct": self._pnl_governor_target_pnl_pct,
            "pnl_governor_target_pnl_quote": self._pnl_governor_target_pnl_quote,
            "pnl_governor_expected_pnl_quote": self._pnl_governor_expected_pnl_quote,
            "pnl_governor_actual_pnl_quote": self._pnl_governor_actual_pnl_quote,
            "pnl_governor_deficit_ratio": self._pnl_governor_deficit_ratio,
            "pnl_governor_edge_relax_bps": self._pnl_governor_edge_relax_bps,
            "pnl_governor_size_mult": self._pnl_governor_size_mult,
            "pnl_governor_size_boost_active": self._pnl_governor_size_boost_active,
            "pnl_governor_activation_reason": self._pnl_governor_activation_reason,
            "pnl_governor_size_boost_reason": self._pnl_governor_size_boost_reason,
            "pnl_governor_activation_reason_counts": json.dumps(
                self._pnl_governor_activation_reason_counts, sort_keys=True
            ),
            "pnl_governor_size_boost_reason_counts": json.dumps(
                self._pnl_governor_size_boost_reason_counts, sort_keys=True
            ),
            "pnl_governor_target_mode": self._pnl_governor_target_mode,
            "pnl_governor_target_source": self._pnl_governor_target_source,
            "pnl_governor_target_equity_open_quote": self._pnl_governor_target_equity_open_quote,
            "pnl_governor_target_effective_pct": self._pnl_governor_target_effective_pct,
            "pnl_governor_size_mult_applied": self._runtime_size_mult_applied,
            "spread_competitiveness_cap_active": self._spread_competitiveness_cap_active,
            "spread_competitiveness_cap_side_pct": self._spread_competitiveness_cap_side_pct,
            "soft_pause_edge": self._soft_pause_edge,
            "edge_gate_blocked": self._edge_gate_blocked,
            "selective_quote_state": self._selective_quote_state,
            "selective_quote_score": self._selective_quote_score,
            "selective_quote_reason": self._selective_quote_reason,
            "selective_quote_adverse_ratio": self._selective_quote_adverse_ratio,
            "selective_quote_slippage_p95_bps": self._selective_quote_slippage_p95_bps,
            "alpha_policy_state": self._alpha_policy_state,
            "alpha_policy_reason": self._alpha_policy_reason,
            "alpha_maker_score": self._alpha_maker_score,
            "alpha_aggressive_score": self._alpha_aggressive_score,
            "alpha_cross_allowed": self._alpha_cross_allowed,
            "adverse_fill_soft_pause_active": EppV24Controller._adverse_fill_soft_pause_active(self),
            "edge_confidence_soft_pause_active": EppV24Controller._edge_confidence_soft_pause_active(self),
            "slippage_soft_pause_active": EppV24Controller._slippage_soft_pause_active(self),
            "fills_count_today": self._fills_count_today,
            "fees_paid_today_quote": self._fees_paid_today_quote,
            "paper_fill_count": self._paper_fill_count,
            "paper_reject_count": self._paper_reject_count,
            "paper_avg_queue_delay_ms": self._paper_avg_queue_delay_ms,
            "traded_notional_today": self._traded_notional_today,
            "daily_equity_open": self._daily_equity_open,
            "external_soft_pause": self._external_soft_pause,
            "external_pause_reason": self._external_pause_reason,
            "external_model_version": self._last_external_model_version,
            "external_intent_reason": self._last_external_intent_reason,
            "external_daily_pnl_target_pct_override": self._external_daily_pnl_target_pct_override,
            "external_daily_pnl_target_pct_override_expires_ts": self._external_daily_pnl_target_pct_override_expires_ts,
            "fee_source": self._fee_source,
            "maker_fee_pct": self._maker_fee_pct,
            "taker_fee_pct": self._taker_fee_pct,
            "balance_read_failed": self._runtime_adapter.balance_read_failed,
            "funding_rate": self._funding_rate,
            "funding_cost_today_quote": self._funding_cost_today_quote,
            "net_realized_pnl_today": self._realized_pnl_today - self._funding_cost_today_quote,
            "margin_ratio": self._margin_ratio,
            "regime_source": self._regime_source,
            "is_perp": self._is_perp,
            "realized_pnl_today": self._realized_pnl_today,
            "avg_entry_price": self._avg_entry_price,
            "avg_entry_price_long": self._avg_entry_price_long,
            "avg_entry_price_short": self._avg_entry_price_short,
            "position_base": self._position_base,
            "position_gross_base": self._position_gross_base,
            "position_long_base": self._position_long_base,
            "position_short_base": self._position_short_base,
            "derisk_force_taker_min_base": EppV24Controller._derisk_force_min_base_amount(self),
            "derisk_force_taker_expectancy_guard_blocked": bool(
                getattr(self, "_derisk_force_taker_expectancy_guard_blocked", False)
            ),
            "derisk_force_taker_expectancy_guard_reason": str(
                getattr(self, "_derisk_force_taker_expectancy_guard_reason", "")
            ),
            "derisk_force_taker_expectancy_mean_quote": to_decimal(
                getattr(self, "_derisk_force_taker_expectancy_mean_quote", _ZERO)
            ),
            "derisk_force_taker_expectancy_taker_fills": int(
                getattr(self, "_derisk_force_taker_expectancy_taker_fills", 0)
            ),
            "position_drift_pct": self._position_drift_pct,
            "fill_edge_ewma": self._fill_edge_ewma,
            "adverse_fill_active": self._adverse_fill_count >= self.config.adverse_fill_count_threshold and self._fill_edge_ewma is not None,
            "ws_reconnect_count": self._ws_reconnect_count,
            "connector_status": self._runtime_adapter.status_summary(),
            "ob_imbalance": self._ob_imbalance,
            "kelly_size_active": self._fill_count_for_kelly >= self.config.kelly_min_observations and self.config.use_kelly_sizing,
            "kelly_order_quote": self._get_kelly_order_quote(equity_quote) if self.config.use_kelly_sizing else _ZERO,
            "ml_regime_override": self._external_regime_override or "",
            "adverse_skip_count": self._adverse_skip_count,
            "indicator_duration_ms": self._indicator_duration_ms,
            "connector_io_duration_ms": self._connector_io_duration_ms,
            # Risk thresholds for exporter/headroom metrics (runtime-accurate per bot config).
            "min_base_pct": self.config.min_base_pct,
            "max_base_pct": self.config.max_base_pct,
            "max_total_notional_quote": self.config.max_total_notional_quote,
            "max_daily_turnover_x_hard": self.config.max_daily_turnover_x_hard,
            "max_daily_loss_pct_hard": self.config.max_daily_loss_pct_hard,
            "max_drawdown_pct_hard": self.config.max_drawdown_pct_hard,
            "margin_ratio_soft_pause_pct": self.config.margin_ratio_soft_pause_pct,
            "margin_ratio_hard_stop_pct": self.config.margin_ratio_hard_stop_pct,
            "position_drift_soft_pause_pct": self.config.position_drift_soft_pause_pct,
            # config fields needed by log_minute
            "variant": self.config.variant,
            "bot_mode": self.config.bot_mode,
            "is_paper": _config_is_paper(self.config),
            "connector_name": self.config.connector_name,
            "trading_pair": self.config.trading_pair,
        }

    def _get_top_of_book(self) -> Tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
        top = self._runtime_adapter.get_top_of_book()
        return top.best_bid, top.best_ask, top.spread_pct, top.best_bid_size, top.best_ask_size

    def _compute_ob_imbalance(self, depth: int = 5) -> Decimal:
        """Compute order book imbalance from top-N levels: (bid_depth - ask_depth) / (bid_depth + ask_depth).

        Returns value in [-1, +1]. Positive = more bids (buy pressure). Guarded by try/except.
        """
        try:
            return _clip(self._runtime_adapter.get_depth_imbalance(depth=depth), Decimal("-1"), _ONE)
        except Exception:
            return _ZERO

    # ext10: roll on day change only, remove hour condition
    def _maybe_roll_day(self, now_ts: float) -> None:
        dt = datetime.fromtimestamp(now_ts, tz=timezone.utc)
        day_key = dt.strftime("%Y-%m-%d")
        if self._daily_key is None:
            self._daily_key = day_key
            return
        if day_key != self._daily_key:
            mid = self._get_mid_price()
            equity_now, _, _ = self._compute_equity_and_base_pcts(mid)
            equity_open = self._daily_equity_open or equity_now
            equity_peak = self._daily_equity_peak or equity_now
            pnl = equity_now - equity_open
            pnl_pct = (pnl / equity_open) if equity_open > 0 else Decimal("0")
            drawdown_pct = (equity_peak - equity_now) / equity_peak if equity_peak > 0 else Decimal("0")

            dd_prices = self._equity_samples_today or [equity_open, equity_now]
            dd_ts = self._equity_sample_ts_today if len(self._equity_sample_ts_today) == len(dd_prices) else None
            dd_meta = max_drawdown_with_metadata(dd_prices, method="percent", timestamps=dd_ts)
            event_ts = datetime.fromtimestamp(now_ts, tz=timezone.utc).isoformat()
            self._csv.log_daily(
                {
                    "bot_variant": self.config.variant,
                    "exchange": self.config.connector_name,
                    "trading_pair": self.config.trading_pair,
                    "state": self._ops_guard.state.value,
                    "equity_open_quote": str(equity_open),
                    "equity_peak_quote": str(equity_peak),
                    "equity_now_quote": str(equity_now),
                    "pnl_quote": str(pnl),
                    "pnl_pct": str(pnl_pct),
                    "drawdown_pct": str(drawdown_pct),
                    "max_drawdown_pct": str(dd_meta.max_drawdown),
                    "max_drawdown_peak_ts": str(dd_meta.peak_ts or ""),
                    "max_drawdown_trough_ts": str(dd_meta.trough_ts or ""),
                    "turnover_x": str(self._traded_notional_today / equity_now) if equity_now > 0 else "0",
                    "fills_count": self._fills_count_today,
                    "fees_paid_today_quote": str(self._fees_paid_today_quote),
                    "funding_cost_today_quote": str(self._funding_cost_today_quote),
                    "realized_pnl_today_quote": str(self._realized_pnl_today),
                    "net_realized_pnl_today_quote": str(self._realized_pnl_today - self._funding_cost_today_quote),
                    "ops_events": "|".join(self._ops_guard.reasons),
                },
                ts=event_ts,
            )
            self._daily_key = day_key
            self._daily_equity_open = equity_now
            self._daily_equity_peak = equity_now
            self._equity_samples_today = []
            self._equity_sample_ts_today = []
            self._traded_notional_today = Decimal("0")
            self._fills_count_today = 0
            self._fees_paid_today_quote = Decimal("0")
            self._fee_rate_mismatch_warned_today = False
            self._funding_cost_today_quote = _ZERO
            self._realized_pnl_today = _ZERO
            self._cancel_events_ts = []
            if (
                self.config.close_position_at_rollover
                and mid > _ZERO
                and abs(self._position_base) * mid > self.config.min_close_notional_quote
            ):
                self._pending_eod_close = True
                logger.info(
                    "EOD close triggered: position_base=%s mid=%s notional=%s",
                    self._position_base, mid, abs(self._position_base) * mid,
                )
            self._save_daily_state(force=True)

    def _daily_state_path(self) -> str:
        from pathlib import Path
        connector_tag = str(self.config.connector_name).replace("_paper_trade", "").replace(" ", "_")
        mode_tag = self.config.bot_mode
        return str(
            Path(self.config.log_dir) / _artifact_namespace(self.config)
            / f"{self.config.instance_name}_{self.config.variant}"
            / f"daily_state_{connector_tag}_{mode_tag}.json"
        )

    def _fills_csv_path(self) -> Path:
        """Return canonical fills.csv path for this instance."""
        csv_logger_dir = getattr(self._csv, "log_dir", None)
        if csv_logger_dir is not None:
            try:
                return Path(str(csv_logger_dir)).expanduser().resolve() / "fills.csv"
            except Exception:
                pass
        return (
            Path(self.config.log_dir).expanduser().resolve()
            / _artifact_namespace(self.config)
            / f"{self.config.instance_name}_{self.config.variant}"
            / "fills.csv"
        )

    def _hydrate_seen_fill_order_ids_from_csv(self) -> None:
        """Warm restart-time fill cache from fills.csv.

        This cache is used for replay-safety diagnostics and live fill-event dedupe.
        It is intentionally best-effort and never blocks startup.
        """
        fills_path = self._fills_csv_path()
        if not fills_path.exists():
            return
        try:
            order_id_cap = int(getattr(self, "_seen_fill_order_ids_cap", 50_000) or 50_000)
            order_id_cap = max(1_000, order_id_cap)
            event_key_cap = int(getattr(self, "_seen_fill_event_keys_cap", 120_000) or 120_000)
            event_key_cap = max(1_000, event_key_cap)
            seen_order_ids = getattr(self, "_seen_fill_order_ids", None)
            if not isinstance(seen_order_ids, set):
                seen_order_ids = set()
                setattr(self, "_seen_fill_order_ids", seen_order_ids)
            seen_order_ids_fifo = getattr(self, "_seen_fill_order_ids_fifo", None)
            if not isinstance(seen_order_ids_fifo, (deque, list)):
                seen_order_ids_fifo = deque()
                setattr(self, "_seen_fill_order_ids_fifo", seen_order_ids_fifo)
            seen_event_keys = getattr(self, "_seen_fill_event_keys", None)
            if not isinstance(seen_event_keys, set):
                seen_event_keys = set()
                setattr(self, "_seen_fill_event_keys", seen_event_keys)
            seen_event_keys_fifo = getattr(self, "_seen_fill_event_keys_fifo", None)
            if not isinstance(seen_event_keys_fifo, (deque, list)):
                seen_event_keys_fifo = deque()
                setattr(self, "_seen_fill_event_keys_fifo", seen_event_keys_fifo)
            order_ids: List[str] = []
            fill_event_keys: List[str] = []
            latest_fill_ts = 0.0
            with fills_path.open("r", newline="", encoding="utf-8") as fp:
                reader = csv.DictReader(fp)
                for row in reader:
                    oid = str(row.get("order_id", "") or "").strip()
                    if oid:
                        order_ids.append(oid)
                    fill_event_key = EppV24Controller._fill_row_dedupe_key(row)
                    if fill_event_key:
                        fill_event_keys.append(fill_event_key)
                    ts_raw = str(row.get("ts", "") or "").strip()
                    if ts_raw:
                        try:
                            parsed_ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00")).timestamp()
                            latest_fill_ts = max(latest_fill_ts, float(parsed_ts))
                        except Exception:
                            pass

            if len(order_ids) > order_id_cap:
                order_ids = order_ids[-order_id_cap:]
            if len(fill_event_keys) > event_key_cap:
                fill_event_keys = fill_event_keys[-event_key_cap:]

            seen_order_ids.clear()
            seen_order_ids_fifo.clear()
            for oid in order_ids:
                if oid in seen_order_ids:
                    continue
                seen_order_ids.add(oid)
                seen_order_ids_fifo.append(oid)
            seen_event_keys.clear()
            seen_event_keys_fifo.clear()
            for event_key in fill_event_keys:
                if event_key in seen_event_keys:
                    continue
                seen_event_keys.add(event_key)
                seen_event_keys_fifo.append(event_key)

            if latest_fill_ts > 0:
                self._last_fill_ts = max(float(getattr(self, "_last_fill_ts", 0.0) or 0.0), latest_fill_ts)

            if seen_order_ids or seen_event_keys:
                logger.info(
                    "Hydrated fill cache: %d unique order_ids, %d unique event_keys from %s (last_fill_ts=%s)",
                    len(seen_order_ids),
                    len(seen_event_keys),
                    fills_path,
                    latest_fill_ts if latest_fill_ts > 0 else "n/a",
                )
        except Exception:
            logger.warning("Failed to hydrate fill cache from %s", fills_path, exc_info=True)

    def _load_daily_state(self) -> None:
        """Restore daily state from Redis or disk.

        Same-day restart: full state restored (counters, position, equity).
        Cross-day restart: only position_base and avg_entry_price are carried
        forward — daily counters reset on the next _maybe_roll_day call.
        This prevents the bot from "forgetting" an open exchange position
        just because the calendar day rolled.
        """
        data = self._state_store.load()
        if data is None:
            return
        try:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            saved_position = to_decimal(data.get("position_base", "0"))
            saved_avg_entry = to_decimal(data.get("avg_entry_price", "0"))
            saved_position_gross = to_decimal(data.get("position_gross_base", abs(saved_position)))
            saved_position_long = to_decimal(data.get("position_long_base", max(_ZERO, saved_position)))
            saved_position_short = to_decimal(data.get("position_short_base", max(_ZERO, -saved_position)))
            saved_avg_entry_long = to_decimal(
                data.get("avg_entry_price_long", saved_avg_entry if saved_position_long > _ZERO else _ZERO)
            )
            saved_avg_entry_short = to_decimal(
                data.get("avg_entry_price_short", saved_avg_entry if saved_position_short > _ZERO else _ZERO)
            )
            saved_last_fill_ts = float(data.get("last_fill_ts", 0.0) or 0.0)
            if saved_last_fill_ts > 0:
                self._last_fill_ts = saved_last_fill_ts
            if data.get("day_key") == today:
                self._daily_key = data.get("day_key")
                self._daily_equity_open = to_decimal(data["equity_open"]) if data.get("equity_open") else None
                self._daily_equity_peak = to_decimal(data["equity_peak"]) if data.get("equity_peak") else None
                self._traded_notional_today = to_decimal(data.get("traded_notional", "0"))
                self._fills_count_today = int(data.get("fills_count", 0))
                self._fees_paid_today_quote = to_decimal(data.get("fees_paid", "0"))
                self._funding_cost_today_quote = to_decimal(data.get("funding_cost", "0"))
                self._realized_pnl_today = to_decimal(data.get("realized_pnl", "0"))
                self._position_base = saved_position
                self._position_gross_base = saved_position_gross
                self._position_long_base = saved_position_long
                self._position_short_base = saved_position_short
                self._avg_entry_price = saved_avg_entry
                self._avg_entry_price_long = saved_avg_entry_long
                self._avg_entry_price_short = saved_avg_entry_short
                logger.info("Restored daily state for %s (fills=%d, traded=%.2f)", today, self._fills_count_today, self._traded_notional_today)
            else:
                self._position_base = saved_position
                self._position_gross_base = saved_position_gross
                self._position_long_base = saved_position_long
                self._position_short_base = saved_position_short
                self._avg_entry_price = saved_avg_entry
                self._avg_entry_price_long = saved_avg_entry_long
                self._avg_entry_price_short = saved_avg_entry_short
                logger.info(
                    "Cross-day restart: carried forward net=%.8f gross=%.8f avg_entry=%.2f from %s",
                    saved_position, saved_position_gross, saved_avg_entry, data.get("day_key", "?"),
                )
        except Exception:
            logger.warning("Failed to load daily state", exc_info=True)

    def _save_daily_state(self, force: bool = False) -> None:
        """Persist daily state to Redis and disk for restart recovery."""
        now_ts = float(self.market_data_provider.time())
        data = {
            "day_key": self._daily_key,
            "equity_open": str(self._daily_equity_open) if self._daily_equity_open else None,
            "equity_peak": str(self._daily_equity_peak) if self._daily_equity_peak else None,
            "traded_notional": str(self._traded_notional_today),
            "fills_count": self._fills_count_today,
            "fees_paid": str(self._fees_paid_today_quote),
            "funding_cost": str(self._funding_cost_today_quote),
            "realized_pnl": str(self._realized_pnl_today),
            "last_fill_ts": float(getattr(self, "_last_fill_ts", 0.0) or 0.0),
            "position_base": str(getattr(self, "_position_base", _ZERO)),
            "position_gross_base": str(getattr(self, "_position_gross_base", abs(getattr(self, "_position_base", _ZERO)))),
            "position_long_base": str(getattr(self, "_position_long_base", max(_ZERO, getattr(self, "_position_base", _ZERO)))),
            "position_short_base": str(getattr(self, "_position_short_base", max(_ZERO, -getattr(self, "_position_base", _ZERO)))),
            "avg_entry_price": str(getattr(self, "_avg_entry_price", _ZERO)),
            "avg_entry_price_long": str(getattr(self, "_avg_entry_price_long", getattr(self, "_avg_entry_price", _ZERO))),
            "avg_entry_price_short": str(getattr(self, "_avg_entry_price_short", getattr(self, "_avg_entry_price", _ZERO))),
        }
        self._state_store.save(data, now_ts, force=force)




class SharedMmV24Config(EppV24Config):
    """Neutral config alias for the shared market-making v2.4 base."""

    controller_name: str = "shared_mm_v24"


class SharedMmV24Controller(EppV24Controller):
    """Neutral controller alias for the shared market-making v2.4 base."""


__all__ = [
    "EppV24Config",
    "EppV24Controller",
    "SharedMmV24Config",
    "SharedMmV24Controller",
]
