from __future__ import annotations

import asyncio
import logging
import os
import time as _time_mod
from collections import deque
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from hummingbot.strategy_v2.controllers.market_making_controller_base import (
    MarketMakingControllerBase,
)

from controllers.auto_calibration_mixin import AutoCalibrationMixin
from controllers.connector_runtime_adapter import ConnectorRuntimeAdapter
from controllers.fill_handler_mixin import FillHandlerMixin
from controllers.ops_guard import GuardState, OpsGuard
from controllers.position_mixin import PositionMixin
from controllers.price_buffer import PriceBuffer
from controllers.regime_detector import RegimeDetector
from controllers.risk_evaluator import RiskEvaluator
from controllers.risk_mixin import RiskMixin
from controllers.runtime.contracts import RuntimeFamilyAdapter
from controllers.runtime.core import resolve_runtime_compatibility
from controllers.runtime.data_context import RuntimeDataContext
from controllers.runtime.execution_context import RuntimeExecutionPlan
from controllers.runtime.kernel.config import (
    EppV24Config,
    _ZERO,
    _ONE,
    _TWO,
    _10K,
    _canonical_connector_name,
    _clip,
    _config_is_paper,
    _paper_reset_state_on_startup_enabled,
    _runtime_family_adapter,
)
from controllers.runtime.kernel.market_mixin import MarketConditionsMixin
from controllers.runtime.kernel.quoting_mixin import QuotingMixin
from controllers.runtime.kernel.regime_mixin import RegimeMixin
from controllers.runtime.kernel.startup_mixin import StartupMixin
from controllers.runtime.kernel.state_mixin import StateMixin
from controllers.runtime.kernel.supervisory_mixin import SupervisoryMixin
from controllers.runtime.logging import CsvSplitLogger
from controllers.runtime.market_making_core import MarketMakingRuntimeAdapter
from controllers.runtime.risk_context import RuntimeRiskDecision
from controllers.runtime.runtime_types import (
    MarketConditions,
    RegimeSpec,
    RuntimeLevelState,
    SpreadEdgeState,
)
from controllers.spread_engine import SpreadEngine
from controllers.telemetry_mixin import TelemetryMixin
from controllers.tick_emitter import TickEmitter
from controllers.types import ProcessedState
from platform_lib.core.daily_state_store import DailyStateStore
from platform_lib.core.utils import to_decimal
from simulation.config import PaperEngineConfig

logger = logging.getLogger(__name__)


class SharedRuntimeKernel(FillHandlerMixin, RiskMixin, TelemetryMixin, AutoCalibrationMixin, PositionMixin, StartupMixin, QuotingMixin, RegimeMixin, StateMixin, MarketConditionsMixin, SupervisoryMixin, MarketMakingControllerBase):
    """Shared runtime kernel for all strategy lanes (MM and directional).

    Historical note: "EPP" and "shared_mm" are legacy names retained for
    compatibility with existing controller IDs, configs, and artifacts.
    The class was renamed from ``shared_mm_v24`` to ``shared_runtime_v24``
    to reflect that it serves as the shared base for both market-making
    (EppV24Controller) and directional (DirectionalRuntimeController) bots.

    A regime-aware controller kernel that dynamically adjusts spread,
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

    PHASE0_SPECS: dict[str, RegimeSpec] = {
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
    def _resolve_specs(cls, overrides: dict[str, dict[str, Any]] | None) -> dict[str, RegimeSpec]:
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
        self._validate_config(config)
        self._init_core_components(config)
        self._init_price_buffer(config)
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
        self._daily_equity_open: Decimal | None = None
        self._daily_key: str | None = None
        # One equity sample per logged minute (used for daily max drawdown).
        self._equity_samples_today: list[Decimal] = []
        self._equity_sample_ts_today: list[str] = []
        self._cancel_events_ts: list[float] = []
        self._cancel_fail_streak: int = 0
        self._consecutive_stuck_ticks: int = 0
        self._soft_pause_edge: bool = False
        self._external_soft_pause: bool = False
        self._external_pause_reason: str = ""
        self._external_target_base_pct_override: Decimal | None = None
        self._external_daily_pnl_target_pct_override: Decimal | None = None
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
        self._net_edge_ewma: Decimal | None = None
        self._net_edge_gate: Decimal = _ZERO
        self._daily_equity_peak: Decimal | None = None
        self._fees_paid_today_quote: Decimal = Decimal("0")
        self._fee_rate_mismatch_warned_today: bool = False
        self._paper_fill_count: int = 0
        self._paper_reject_count: int = 0
        self._paper_avg_queue_delay_ms: Decimal = Decimal("0")
        self._tick_duration_ms: float = 0.0
        self._tick_duration_ewma_ms: float = 0.0
        self._tick_count: int = 0
        self._tick_slow_count: int = 0
        self._indicator_duration_ms: float = 0.0
        self._connector_io_duration_ms: float = 0.0
        self._preflight_hot_path_duration_ms: float = 0.0
        self._governance_duration_ms: float = 0.0
        self._execution_plan_duration_ms: float = 0.0
        self._risk_duration_ms: float = 0.0
        self._emit_tick_duration_ms: float = 0.0
        self._active_regime: str = "neutral_low_vol"
        self._pending_regime: str = "neutral_low_vol"
        self._regime_source: str = "price_buffer"
        self._regime_hold_counter: int = 0
        self._regime_ema_value: Decimal | None = None
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
        self._last_spread_state: SpreadEdgeState | None = None
        self._pending_stale_cancel_actions: list[Any] = []
        self._recently_issued_levels: dict[str, float] = {}
        self._fill_edge_ewma: Decimal | None = None
        self._fill_edge_variance: Decimal | None = None
        self._fill_count_for_kelly: int = 0
        self._adverse_fill_count: int = 0
        self._pending_eod_close: bool = False
        self._ob_imbalance: Decimal = _ZERO
        self._external_regime_override: str | None = None
        self._external_regime_override_expiry: float = 0.0
        self._ml_direction_hint: str = ""
        self._ml_direction_hint_confidence: float = 0.0
        self._ml_sizing_multiplier: float = 1.0
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
        self._pnl_governor_activation_reason_counts: dict[str, int] = {}
        self._pnl_governor_size_boost_reason_counts: dict[str, int] = {}
        self._runtime_size_mult_applied: Decimal = _ONE
        self._spread_competitiveness_cap_active: bool = False
        self._spread_competitiveness_cap_side_pct: Decimal = _ZERO
        self._auto_calibration_minute_history: deque[dict[str, Any]] = deque(maxlen=20_000)
        self._auto_calibration_fill_history: deque[dict[str, Any]] = deque(maxlen=20_000)
        self._auto_calibration_change_events: deque[tuple[float, Decimal]] = deque(maxlen=1_000)
        self._auto_calibration_last_eval_ts: float = 0.0
        self._auto_calibration_relax_signal_streak: int = 0
        self._auto_calibration_negative_window_streak: int = 0
        self._auto_calibration_applied_changes: list[dict[str, Any]] = []
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
        self._last_drift_correction_ts: float = 0.0
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
        redis_url = (os.environ.get("REDIS_URL") or "").strip() or None
        if not redis_url:
            redis_url = PaperEngineConfig.resolve_redis_url_from_env()
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
        self._telemetry_redis: Any | None = None
        self._telemetry_redis_init_done: bool = False
        self._last_portfolio_risk_check_ts: float = 0.0
        self._portfolio_risk_hard_stop_latched: bool = False
        self._startup_position_sync_done: bool = False
        self._startup_sync_retries: int = 0
        self._startup_sync_first_ts: float = 0.0
        self._startup_orphan_check_done: bool = False
        self._startup_recon_attempt: int = 0
        self._startup_recon_next_retry_ts: float = 0.0
        self._startup_recon_soft_pause: bool = False
        self._seen_fill_order_ids: set[str] = set()
        self._seen_fill_order_ids_fifo: deque[str] = deque()
        self._seen_fill_order_ids_cap: int = 50_000
        self._seen_fill_event_keys: set[str] = set()
        self._seen_fill_event_keys_fifo: deque[str] = deque()
        self._seen_fill_event_keys_cap: int = 120_000
        self._recovery_guard: Any | None = None
        self._recovery_close_emitted: bool = False
        self._recovery_zombie_cleaned: bool = False
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

    # ── Framework boundary: encapsulated access to shared state ────────

    def enqueue_stale_cancels(self, actions: list[Any]) -> None:
        """Append StopExecutorActions to the pending stale-cancel queue.

        Bot lanes and mixins MUST use this instead of direct list mutation.
        """
        self._pending_stale_cancel_actions.extend(actions)

    def replace_stale_cancels(self, actions: list[Any]) -> None:
        """Replace the pending stale-cancel queue wholesale.

        Used by regime_mixin when a regime flip requires a fresh cancel set.
        """
        self._pending_stale_cancel_actions = list(actions)

    def _reset_issued_levels(self) -> None:
        """Clear the recently-issued-levels tracking dict.

        Bot lanes MUST call this instead of direct dict assignment.
        """
        self._recently_issued_levels.clear()

    def _strategy_extra_actions(self) -> list[Any]:
        """Hook for bot-lane-specific actions to be merged into determine_executor_actions.

        Override in subclasses that need to inject extra actions (e.g. trailing
        stops, partial takes) without overriding determine_executor_actions.
        Default returns empty list.
        """
        return []

    # ── Init helpers (extracted from __init__ for readability) ─────────

    def _validate_config(self, config: EppV24Config) -> None:
        if self._bot_mode == "paper" and not config.connector_name.endswith("_paper_trade"):
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

    def _init_core_components(self, config: EppV24Config) -> None:
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

    def _init_price_buffer(self, config: EppV24Config) -> None:
        from controllers.runtime.kernel.config import _RESOLUTION_TO_MINUTES
        self._resolution_minutes: int = _RESOLUTION_TO_MINUTES.get(
            getattr(config, "indicator_resolution", "1m"), 1
        )
        self._price_buffer = PriceBuffer(
            sample_interval_sec=config.sample_interval_s,
            resolution_minutes=self._resolution_minutes,
        )
        self._price_sampler_task: asyncio.Task | None = None
        self._history_provider = None
        self._history_seed_attempted = False
        self._history_seed_status = "disabled"
        self._history_seed_reason = ""
        self._history_seed_source = ""
        self._history_seed_bars = 0
        self._history_seed_latency_ms = 0.0

    # ── Tick loop ───────────────────────────────────────────────────────

    async def update_processed_data(self):
        """Main tick coordinator — delegates to sub-methods for testability."""
        _t0 = _time_mod.perf_counter()
        now = float(self.market_data_provider.time())

        _t_preflight = _time_mod.perf_counter()
        self._preflight_hot_path(now)
        self._preflight_hot_path_duration_ms = (_time_mod.perf_counter() - _t_preflight) * 1000.0
        if self.config.require_fee_resolution and self._fee_resolution_error:
            self._ops_guard.force_hard_stop("fee_unresolved")
            return

        self._ensure_price_sampler_started()

        _t_conn_start = _time_mod.perf_counter()
        mid = self._get_reference_price()
        if mid <= 0:
            return
        self._maybe_seed_price_buffer(now)
        buffer_price = self._get_price_for_buffer()
        if buffer_price > _ZERO:
            self._price_buffer.add_sample(now, buffer_price)
        self._maybe_roll_day(now)
        if self._pending_eod_close and abs(self._position_base) < self._min_base_amount(mid):
            self._pending_eod_close = False

        equity_quote, base_pct_gross, base_pct_net = self._compute_equity_and_base_pcts(mid)
        self._track_daily_equity(equity_quote)
        self._maybe_reconcile_desk_state(mid)

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
        _t_execution = _time_mod.perf_counter()
        runtime_execution_plan = self.build_runtime_execution_plan(runtime_data_context)
        self._execution_plan_duration_ms = (_time_mod.perf_counter() - _t_execution) * 1000.0
        _t_risk = _time_mod.perf_counter()
        try:
            risk_reasons, risk_hard_stop, daily_loss_pct, drawdown_pct = self._evaluate_all_risk(
                spread_state, base_pct_gross, equity_quote, runtime_execution_plan.projected_total_quote, market,
            )
        except Exception:
            logger.exception("RISK_EVAL_FAILURE — failing closed to HARD_STOP")
            risk_reasons = ["risk_eval_exception"]
            risk_hard_stop = True
            daily_loss_pct = _ZERO
            drawdown_pct = _ZERO
        self._risk_duration_ms = (_time_mod.perf_counter() - _t_risk) * 1000.0
        self._connector_io_duration_ms = (_time_mod.perf_counter() - _t_conn_start) * 1000.0
        try:
            state = self._resolve_guard_state(now, market, risk_reasons, risk_hard_stop)
        except Exception:
            logger.exception("GUARD_STATE_FAILURE — failing closed to HARD_STOP")
            state = GuardState.HARD_STOP
        runtime_risk_decision = RuntimeRiskDecision(
            risk_reasons=list(risk_reasons),
            risk_hard_stop=risk_hard_stop,
            daily_loss_pct=daily_loss_pct,
            drawdown_pct=drawdown_pct,
            guard_state=state,
        )

        projected_total_quote = runtime_execution_plan.projected_total_quote
        self._apply_runtime_execution_plan(runtime_data_context, runtime_execution_plan)
        _t_emit = _time_mod.perf_counter()
        self._emit_tick_output(
            _t0, now, mid, regime_name, target_base_pct, target_net_base_pct,
            base_pct_gross, base_pct_net, equity_quote, spread_state, market,
            risk_hard_stop, risk_reasons, daily_loss_pct, drawdown_pct,
            projected_total_quote, state,
            runtime_data_context=runtime_data_context,
            runtime_execution_plan=runtime_execution_plan,
            runtime_risk_decision=runtime_risk_decision,
        )
        self._emit_tick_duration_ms = (_time_mod.perf_counter() - _t_emit) * 1000.0
        _t_governance = _time_mod.perf_counter()
        self._run_supervisory_maintenance(now)
        self._governance_duration_ms = (_time_mod.perf_counter() - _t_governance) * 1000.0
        _tick_elapsed_ms = (_time_mod.perf_counter() - _t0) * 1000.0
        self._tick_duration_ms = _tick_elapsed_ms
        self._tick_count += 1
        self._tick_duration_ewma_ms = (
            0.1 * _tick_elapsed_ms + 0.9 * self._tick_duration_ewma_ms
        )
        if _tick_elapsed_ms > 50.0:
            self._tick_slow_count += 1
            logger.warning("Slow tick: %.1f ms (ewma=%.1f ms, tick #%d)", _tick_elapsed_ms, self._tick_duration_ewma_ms, self._tick_count)
        if self._tick_count % 60 == 0:
            slow_pct = (self._tick_slow_count / self._tick_count * 100.0) if self._tick_count else 0.0
            logger.info(
                "Tick profiling [%d ticks]: ewma=%.1f ms, slow(>50ms)=%d (%.1f%%)",
                self._tick_count, self._tick_duration_ewma_ms, self._tick_slow_count, slow_pct,
            )

        if isinstance(self.processed_data, dict):
            self.processed_data["_tick_duration_ms"] = _tick_elapsed_ms
            self.processed_data["_preflight_hot_path_duration_ms"] = self._preflight_hot_path_duration_ms
            self.processed_data["_execution_plan_duration_ms"] = self._execution_plan_duration_ms
            self.processed_data["_risk_duration_ms"] = self._risk_duration_ms
            self.processed_data["_emit_tick_duration_ms"] = self._emit_tick_duration_ms
            self.processed_data["_governance_duration_ms"] = self._governance_duration_ms

    # ── Edge gate ───────────────────────────────────────────────────────

    def _update_edge_gate_ewma(self, now: float, spread_state: SpreadEdgeState) -> None:
        """Apply EWMA smoothing to net edge, then update edge gate hysteresis."""
        if not bool(getattr(self.config, "shared_edge_gate_enabled", True)):
            self._net_edge_gate = spread_state.net_edge
            self._risk_evaluator.reset_edge_gate(now)
            self._soft_pause_edge = False
            self._edge_gate_blocked = False
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

    # ── Spread / edge orchestration ─────────────────────────────────────

    def _compute_spread_and_edge(
        self,
        now_ts: float,
        regime_name: str,
        regime_spec: RegimeSpec,
        target_base_pct: Decimal,
        base_pct: Decimal,
        equity_quote: Decimal,
        *,
        band_pct: Decimal | None = None,
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
        band_pct: Decimal | None = None,
        market_spread_pct: Decimal | None = None,
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
    ) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
        """Compute adaptive edge floor and spread knobs with strict safety bounds."""
        cache_key = (
            regime_name,
            int(now_ts),
            int(equity_quote * 10),
            int(self._market_spread_bps_ewma * 100),
            int(self._band_pct_ewma * 10000),
            int(self._last_fill_ts),
        )
        cached = getattr(self, "_adaptive_knobs_cache", None)
        if cached is not None and cached[0] == cache_key:
            self._adaptive_knobs_cache_hits = getattr(self, "_adaptive_knobs_cache_hits", 0) + 1
            return cached[1]
        selective_metrics = self._compute_selective_quote_quality(regime_name)
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
            self._increment_governor_reason_count(
                "_pnl_governor_activation_reason_counts", "adaptive_params_disabled"
            )
            self._increment_governor_reason_count(
                "_pnl_governor_size_boost_reason_counts", "adaptive_params_disabled"
            )
            return None, None, None

        edge_result = self._compute_adaptive_edge_bps(now_ts, regime_name, selective_state, selective_score)
        effective_min_edge_bps = edge_result["effective_min_edge_bps"]
        fill_age_s = edge_result["fill_age_s"]
        vol_ratio = edge_result["vol_ratio"]
        stale_ratio = edge_result["stale_ratio"]
        edge_relax_bps = edge_result["edge_relax_bps"]

        gov = self._compute_pnl_governor(
            now_ts, equity_quote, effective_min_edge_bps, stale_ratio, selective_state,
        )
        effective_min_edge_bps = gov["effective_min_edge_bps"]
        governor_edge_relax_bps = gov["governor_edge_relax_bps"]

        if effective_min_edge_bps < _ZERO:
            fee_drag_bps = edge_relax_bps + governor_edge_relax_bps
            logger.warning(
                "Effective edge floor negative (%.2f bps): total drag %.2f bps "
                "exceeds base edge %.2f bps — clamping to 0",
                float(effective_min_edge_bps),
                float(fee_drag_bps),
                float(Decimal(self.config.min_net_edge_bps)),
            )
            effective_min_edge_bps = _ZERO

        effective_min_edge_bps = _clip(
            effective_min_edge_bps,
            max(_ZERO, to_decimal(self.config.adaptive_min_edge_bps_floor)),
            to_decimal(self.config.adaptive_min_edge_bps_cap),
        )
        effective_min_edge_pct = effective_min_edge_bps / _10K

        market_floor_pct = (self._market_spread_bps_ewma / _10K) * to_decimal(self.config.adaptive_market_floor_factor)
        market_floor_pct = max(_ZERO, market_floor_pct)

        self._adaptive_effective_min_edge_pct = effective_min_edge_pct
        self._adaptive_fill_age_s = fill_age_s
        self._adaptive_market_floor_pct = market_floor_pct
        self._adaptive_vol_ratio = vol_ratio
        self._pnl_governor_active = gov["governor_active"]
        self._pnl_governor_day_progress = gov["governor_day_progress"]
        self._pnl_governor_target_pnl_pct = gov["governor_target_pct"]
        self._pnl_governor_target_pnl_quote = gov["governor_target_quote"]
        self._pnl_governor_expected_pnl_quote = gov["governor_expected_quote"]
        self._pnl_governor_actual_pnl_quote = gov["governor_actual_quote"]
        self._pnl_governor_deficit_ratio = gov["governor_deficit_ratio"]
        self._pnl_governor_edge_relax_bps = governor_edge_relax_bps
        self._pnl_governor_target_mode = gov["governor_target_mode"]
        self._pnl_governor_target_source = gov["governor_target_source"]
        self._pnl_governor_target_equity_open_quote = gov["open_equity"]
        self._pnl_governor_target_effective_pct = gov["governor_target_effective_pct"]
        self._pnl_governor_activation_reason = gov["governor_activation_reason"]
        self._increment_governor_reason_count(
            "_pnl_governor_activation_reason_counts", gov["governor_activation_reason"]
        )
        result = (effective_min_edge_pct, market_floor_pct, vol_ratio)
        self._adaptive_knobs_cache = (cache_key, result)
        return result

    def _compute_adaptive_edge_bps(
        self, now_ts: float, regime_name: str, selective_state: str, selective_score: Decimal,
    ) -> dict:
        """Compute fill-age ratios, market/vol bonuses, and selective tightening."""
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
        if self._fill_edge_below_cost_floor():
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
        return {
            "effective_min_edge_bps": effective_min_edge_bps,
            "fill_age_s": fill_age_s,
            "vol_ratio": vol_ratio,
            "stale_ratio": stale_ratio,
            "edge_relax_bps": edge_relax_bps,
        }

    def _compute_pnl_governor(
        self,
        now_ts: float,
        equity_quote: Decimal,
        effective_min_edge_bps: Decimal,
        stale_ratio: Decimal,
        selective_state: str,
    ) -> dict:
        """Daily PnL governor: relax min-edge when behind target to recover fill cadence."""
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
            dt = datetime.fromtimestamp(now_ts, tz=UTC)
            seconds_today = Decimal(dt.hour * 3600 + dt.minute * 60 + dt.second)
            governor_day_progress = _clip(seconds_today / Decimal(86400), _ZERO, _ONE)
            governor_expected_quote = governor_target_quote * governor_day_progress
            deficit_quote = governor_expected_quote - governor_actual_quote
            activation_buffer_quote = governor_target_quote * _clip(
                to_decimal(self.config.pnl_governor_activation_buffer_pct), _ZERO, Decimal("0.50")
            )
            if deficit_quote > activation_buffer_quote:
                if self._fill_edge_below_cost_floor():
                    governor_activation_reason = "fill_edge_below_cost_floor"
                elif selective_state != "inactive":
                    governor_activation_reason = "selective_quote_filter"
                elif stale_ratio > _ZERO:
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

        return {
            "effective_min_edge_bps": effective_min_edge_bps,
            "governor_active": governor_active,
            "governor_day_progress": governor_day_progress,
            "governor_target_pct": governor_target_pct,
            "governor_target_quote": governor_target_quote,
            "governor_expected_quote": governor_expected_quote,
            "governor_actual_quote": governor_actual_quote,
            "governor_deficit_ratio": governor_deficit_ratio,
            "governor_edge_relax_bps": governor_edge_relax_bps,
            "governor_target_mode": governor_target_mode,
            "governor_target_source": governor_target_source,
            "open_equity": open_equity,
            "governor_target_effective_pct": governor_target_effective_pct,
            "governor_activation_reason": governor_activation_reason,
        }


# ── Alias subclasses ────────────────────────────────────────────────────


class EppV24Controller(SharedRuntimeKernel):
    """Market-making runtime -- full MM machinery on top of the shared kernel.

    Bot1 and any future MM lanes extend this class (via ``SharedMmV24Controller``).
    As the kernel extraction matures, MM-specific method overrides (edge gate,
    PnL governor, selective quoting, alpha policy, adaptive spread knobs,
    auto-calibration, Kelly sizing) will migrate from ``SharedRuntimeKernel``
    into this class.
    """


class SharedRuntimeV24Config(EppV24Config):
    """Preferred config alias for the shared runtime v2.4 base."""

    controller_name: str = "shared_runtime_v24"


class SharedRuntimeV24Controller(EppV24Controller):
    """Preferred controller alias for the shared runtime v2.4 base."""


# Backward-compatible aliases (legacy name)
SharedMmV24Config = SharedRuntimeV24Config
SharedMmV24Controller = SharedRuntimeV24Controller


__all__ = [
    "EppV24Config",
    "EppV24Controller",
    "SharedMmV24Config",
    "SharedMmV24Controller",
    "SharedRuntimeKernel",
    "SharedRuntimeV24Config",
    "SharedRuntimeV24Controller",
]
