from __future__ import annotations

import logging
import os
from decimal import Decimal
from typing import Any, Literal

from hummingbot.strategy_v2.controllers.market_making_controller_base import (
    MarketMakingControllerConfigBase,
)
from pydantic import Field, field_validator, model_validator
from pydantic_core.core_schema import ValidationInfo

from simulation.config import PaperEngineConfig
from platform_lib.market_data.exchange_profiles import resolve_profile
from controllers.runtime.contracts import RuntimeFamilyAdapter
from controllers.runtime.core import resolve_runtime_compatibility
from controllers.runtime.market_making_core import MarketMakingRuntimeAdapter
from controllers.runtime.runtime_types import clip
from platform_lib.contracts.stream_names import PORTFOLIO_RISK_STREAM

logger = logging.getLogger(__name__)

_clip = clip

_RESOLUTION_TO_MINUTES: dict[str, int] = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}

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
        controller._family_adapter = adapter
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
        controller._runtime_compat = surface
    return surface


class EppV24Config(MarketMakingControllerConfigBase):
    """Configuration for EPP v2.4 controller.

    Historical note: "EPP" started as the bot1 strategy label. This config and
    controller now serve as shared v2.4 market-making infrastructure used by
    multiple strategy lanes.

    Variants: a = live trading, b/c = disabled stubs, d = no-trade observation.
    """

    controller_name: str = "epp_v2_4"

    strategy_type: str = Field(
        default="mm",
        description="Strategy archetype: 'mm' (market-making) or 'directional'. Controls which dashboard gates are displayed.",
    )

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
    candles_connector: str | None = Field(default=None, description="Override connector for candle data")
    candles_trading_pair: str | None = Field(default=None, description="Override trading pair for candle data")

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
    price_buffer_source: str = Field(
        default="mid",
        description=(
            "Price source fed into PriceBuffer for indicator computation. "
            "'mid' = order-book mid price (default, suits spot/MM). "
            "'mark' = exchange mark price / spot index (best for perp directional bots). "
            "'last_trade' = last executed trade price."
        ),
    )
    indicator_resolution: Literal["1m", "5m", "15m", "1h"] = Field(
        default="1m",
        description=(
            "Bar resolution for indicator computation (BB, RSI, ADX, ATR, EMA). "
            "PriceBuffer always stores 1m bars internally; at higher resolutions, "
            "indicators operate on resampled bars automatically. "
            "Default '1m' preserves existing behavior for all bots."
        ),
    )
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
    perp_target_net_base_pct: Decimal | None = Field(
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
    close_position_at_rollover: bool = Field(default=True, description="Force position close at daily rollover (timezone.utc midnight)")

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

    # ML Feature Service integration
    ml_features_enabled: bool = Field(
        default=False,
        description="Consume predictions from hb.ml_features.v1 stream",
    )
    ml_confidence_threshold: float = Field(
        default=0.60,
        description="Minimum confidence to act on ML predictions. "
        "For the 4-class regime model, random baseline is 0.25; "
        "0.60 requires meaningful conviction before overriding.",
    )
    ml_regime_override_enabled: bool = Field(
        default=False,
        description="Allow ML feature service to override regime classification",
    )
    ml_direction_hint_enabled: bool = Field(
        default=False,
        description="Accept directional hints from ML feature service",
    )
    ml_sizing_hint_enabled: bool = Field(
        default=False,
        description="Accept sizing multiplier hints from ML feature service",
    )

    # Regime risk gate (v3 trading desk)
    regime_risk_gate_enabled: bool = Field(
        default=False,
        description="Enable regime-aware risk layer in v3 TradingDesk. "
        "Enforces per-regime constraints on strategy selection, sizing, and risk limits.",
    )
    regime_policy_path: str | None = Field(
        default=None,
        description="Path to regime_policy.json. Uses built-in defaults if not set.",
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
    drift_escalation_count: int = Field(default=5, ge=2, le=20, description="Number of drift corrections within 1 hour before escalating to HARD_STOP.")
    drift_escalation_cooldown_s: int = Field(default=900, ge=60, le=3600, description="Minimum seconds between counted drift corrections for escalation.")
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
    position_recovery_enabled: bool = Field(
        default=True,
        description=(
            "After restart, if a position exists with no managing executor, "
            "activate a code-side SL/TP guard using the bot triple-barrier config "
            "until the strategy creates its own executor or the position flattens."
        ),
    )
    ghost_position_guard_enabled: bool = Field(
        default=False,
        description=(
            "Force-close positions that accumulated from ghost fills while "
            "all gates were blocking.  After 10 consecutive blocked ticks "
            "with a non-trivial position (>5 USDT), emits a MARKET close."
        ),
    )
    order_ack_timeout_s: int = Field(default=30, ge=5, le=120, description="Seconds before an unacked order is considered stuck")
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
    override_spread_pct: Decimal | None = Field(default=None, description="Optional fixed spread override for smoke tests.")
    regime_specs_override: dict[str, dict[str, Any]] | None = Field(
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
    def paper_engine_config(self) -> PaperEngineConfig:
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
    def _set_candles_connector(cls, v: str | None, info: ValidationInfo) -> str:
        if v in (None, ""):
            return str(info.data.get("connector_name", ""))
        return str(v)

    @field_validator("candles_trading_pair", mode="before")
    @classmethod
    def _set_candles_pair(cls, v: str | None, info: ValidationInfo) -> str:
        if v in (None, ""):
            return str(info.data.get("trading_pair", ""))
        return str(v)

    @model_validator(mode="after")
    def _validate_base_pct_bounds(self) -> EppV24Config:
        if self.min_base_pct >= self.max_base_pct:
            raise ValueError(
                f"min_base_pct ({self.min_base_pct}) must be less than max_base_pct ({self.max_base_pct})"
            )
        return self
