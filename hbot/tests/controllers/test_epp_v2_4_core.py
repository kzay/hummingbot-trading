"""Unit tests for EppV24Controller core logic.

Tests cover: _detect_regime, _compute_spread_and_edge, _risk_policy_checks /
_evaluate_all_risk, did_fill_order (fill-edge EWMA, adverse counter), and
_cancel_per_min.

Uses sys.modules patching so the tests run even when hummingbot is not
installed — the controller's hummingbot dependencies are replaced with
lightweight stubs.
"""
from __future__ import annotations

import json
import sys
import types as _types_mod
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# Re-export so we can import extracted classes after stubs
_EXTRACTED_CLASSES_IMPORTED = False

# ---------------------------------------------------------------------------
# Hummingbot stub injection — must happen before importing epp_v2_4
# ---------------------------------------------------------------------------

_HB_MODULES: dict[str, _types_mod.ModuleType] = {}


def _ensure_mock_module(name: str) -> _types_mod.ModuleType:
    """Create or retrieve a stub module and register it in sys.modules."""
    if name in _HB_MODULES:
        return _HB_MODULES[name]
    mod = _types_mod.ModuleType(name)
    _HB_MODULES[name] = mod
    sys.modules[name] = mod
    parts = name.split(".")
    for i in range(1, len(parts)):
        parent = ".".join(parts[:i])
        _ensure_mock_module(parent)
    return mod


def _install_hb_stubs() -> None:
    if "hummingbot" in sys.modules:
        return

    _ensure_mock_module("hummingbot")
    _ensure_mock_module("hummingbot.core")
    _ensure_mock_module("hummingbot.core.data_type")

    common = _ensure_mock_module("hummingbot.core.data_type.common")
    common.PriceType = MagicMock()
    common.TradeType = MagicMock()

    _ensure_mock_module("hummingbot.core.event")
    events = _ensure_mock_module("hummingbot.core.event.events")
    events.MarketOrderFailureEvent = MagicMock
    events.OrderCancelledEvent = MagicMock
    events.OrderFilledEvent = MagicMock

    _ensure_mock_module("hummingbot.strategy_v2")
    _ensure_mock_module("hummingbot.strategy_v2.controllers")

    mm_base = _ensure_mock_module(
        "hummingbot.strategy_v2.controllers.market_making_controller_base"
    )

    class _FakeMMConfig:
        def __init_subclass__(cls, **kw):
            super().__init_subclass__(**kw)

    class _FakeMMBase:
        def __init__(self, config, *a, **kw):
            pass

    mm_base.MarketMakingControllerConfigBase = _FakeMMConfig
    mm_base.MarketMakingControllerBase = _FakeMMBase

    _ensure_mock_module("hummingbot.strategy_v2.executors")
    _ensure_mock_module("hummingbot.strategy_v2.executors.position_executor")
    pe_dt = _ensure_mock_module(
        "hummingbot.strategy_v2.executors.position_executor.data_types"
    )
    pe_dt.PositionExecutorConfig = MagicMock

    _ensure_mock_module("hummingbot.strategy_v2.models")
    ea = _ensure_mock_module("hummingbot.strategy_v2.models.executor_actions")
    ea.StopExecutorAction = MagicMock


_install_hb_stubs()

# Now safe to import the controller ----------------------------------------
from controllers.core import MarketConditions, QuoteGeometry, SpreadEdgeState
from controllers.epp_v2_4 import (
    _10K,
    _ONE,
    _ZERO,
    EppV24Controller,
    _paper_reset_state_on_startup_enabled,
)
from controllers.ops_guard import GuardState
from controllers.price_buffer import MinuteBar, PriceBuffer
from controllers.regime_detector import RegimeDetector
from controllers.risk_evaluator import RiskEvaluator
from controllers.spread_engine import SpreadEngine

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_SPECS = dict(EppV24Controller.PHASE0_SPECS)


def _make_config(**overrides) -> SimpleNamespace:
    """Minimal config with sane defaults for unit-testing individual methods."""
    defaults = dict(
        id="epp_v2_4_bot_a",
        connector_name="binance_paper_trade",
        trading_pair="BTC-USDT",
        variant="a",
        instance_name="bot1",
        ema_period=50,
        atr_period=14,
        high_vol_band_pct=Decimal("0.0080"),
        shock_drift_30s_pct=Decimal("0.0100"),
        shock_drift_atr_multiplier=Decimal("1.25"),
        trend_eps_pct=Decimal("0.0010"),
        regime_hold_ticks=3,
        ml_regime_enabled=False,
        spot_fee_pct=Decimal("0.0010"),
        slippage_est_pct=Decimal("0.0005"),
        fill_factor=Decimal("0.4"),
        turnover_cap_x=Decimal("3.0"),
        turnover_penalty_step=Decimal("0.0010"),
        vol_penalty_multiplier=Decimal("0.5"),
        min_net_edge_bps=1,
        edge_resume_bps=4,
        shared_edge_gate_enabled=True,
        adaptive_params_enabled=True,
        adaptive_fill_target_age_s=900,
        adaptive_edge_relax_max_bps=Decimal("8"),
        adaptive_edge_tighten_max_bps=Decimal("3"),
        adaptive_min_edge_bps_floor=Decimal("1"),
        adaptive_min_edge_bps_cap=Decimal("30"),
        adaptive_market_spread_ewma_alpha=Decimal("0.08"),
        adaptive_band_ewma_alpha=Decimal("0.08"),
        adaptive_market_edge_bonus_factor=Decimal("0.25"),
        adaptive_market_edge_bonus_cap_bps=Decimal("4"),
        adaptive_vol_edge_bonus_cap_bps=Decimal("3"),
        adaptive_market_floor_factor=Decimal("0.35"),
        adaptive_vol_spread_widen_max=Decimal("0.35"),
        pnl_governor_enabled=False,
        daily_pnl_target_pct=Decimal("0"),
        daily_pnl_target_quote=Decimal("0"),
        execution_intent_override_ttl_s=1800,
        pnl_governor_activation_buffer_pct=Decimal("0.05"),
        pnl_governor_max_edge_bps_cut=Decimal("5"),
        pnl_governor_max_size_boost_pct=Decimal("0"),
        pnl_governor_size_activation_deficit_pct=Decimal("0.10"),
        pnl_governor_turnover_soft_cap_x=Decimal("4.0"),
        pnl_governor_drawdown_soft_cap_pct=Decimal("0.02"),
        max_quote_to_market_spread_mult=Decimal("0"),
        trend_skew_factor=Decimal("0.8"),
        neutral_skew_factor=Decimal("0.5"),
        spread_step_multiplier=Decimal("0.4"),
        inventory_skew_cap_pct=Decimal("0.0030"),
        inventory_skew_vol_multiplier=Decimal("1.0"),
        ob_imbalance_skew_weight=_ZERO,
        adverse_drift_ewma_alpha=Decimal("0.25"),
        drift_spike_threshold_bps=5,
        drift_spike_mult_max=Decimal("1.8"),
        neutral_trend_guard_pct=Decimal("0"),
        adverse_fill_spread_multiplier=Decimal("1.3"),
        adverse_fill_count_threshold=20,
        adverse_fill_soft_pause_enabled=False,
        adverse_fill_soft_pause_min_fills=120,
        adverse_fill_soft_pause_cost_floor_mult=Decimal("1.0"),
        edge_confidence_soft_pause_enabled=False,
        edge_confidence_soft_pause_min_fills=120,
        edge_confidence_soft_pause_z_score=Decimal("1.96"),
        edge_confidence_soft_pause_cost_floor_mult=Decimal("1.0"),
        slippage_soft_pause_enabled=False,
        slippage_soft_pause_window_fills=300,
        slippage_soft_pause_min_fills=100,
        slippage_soft_pause_p95_bps=Decimal("25"),
        selective_quoting_enabled=False,
        selective_quality_min_fills=40,
        selective_quality_reduce_threshold=Decimal("0.45"),
        selective_quality_block_threshold=Decimal("0.85"),
        selective_quality_edge_tighten_max_bps=Decimal("2.0"),
        selective_neutral_extra_edge_bps=Decimal("1.0"),
        selective_side_bias_pct=Decimal("0.00025"),
        selective_max_levels_per_side=1,
        alpha_policy_enabled=True,
        alpha_policy_no_trade_threshold=Decimal("0.35"),
        alpha_policy_aggressive_threshold=Decimal("0.78"),
        alpha_policy_inventory_relief_threshold=Decimal("0.55"),
        alpha_policy_cross_spread_mult=Decimal("1.05"),
        override_spread_pct=None,
        min_base_pct=Decimal("0.15"),
        max_base_pct=Decimal("0.90"),
        max_order_notional_quote=Decimal("250"),
        max_total_notional_quote=Decimal("1000"),
        max_daily_turnover_x_hard=Decimal("6.0"),
        max_daily_loss_pct_hard=Decimal("0.03"),
        max_drawdown_pct_hard=Decimal("0.05"),
        margin_ratio_soft_pause_pct=Decimal("0.20"),
        margin_ratio_hard_stop_pct=Decimal("0.10"),
        position_drift_soft_pause_pct=Decimal("0.05"),
        edge_state_hold_s=120,
        derisk_force_taker_min_base_mult=Decimal("2.0"),
        derisk_force_taker_expectancy_guard_enabled=False,
        derisk_force_taker_expectancy_window_fills=300,
        derisk_force_taker_expectancy_min_taker_fills=40,
        derisk_force_taker_expectancy_min_quote=Decimal("-0.02"),
        derisk_force_taker_expectancy_override_base_mult=Decimal("10"),
        startup_position_sync=True,
        is_paper=False,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _bind_polymorphic_methods(ctrl):
    """Bind methods to a SimpleNamespace stub that are now called via self.

    After the SharedRuntimeKernel refactor, internal class method calls use
    polymorphic self._ dispatch. SimpleNamespace stubs need these bound
    explicitly since they don't inherit from the controller class.
    """
    _methods = [
        "_fill_edge_below_cost_floor",
        "_adverse_fill_soft_pause_active",
        "_edge_confidence_soft_pause_active",
        "_slippage_soft_pause_active",
        "_increment_governor_reason_count",
        "_compute_pnl_governor_size_mult",
        "_recent_positive_slippage_p95_bps",
        "_record_fill_event_key",
        "_record_seen_fill_order_id",
        "_update_position_from_fill",
        "_publish_fill_telemetry",
        "_cancel_active_quote_executors",
        "_cancel_alpha_no_trade_orders",
        "_cancel_active_runtime_orders",
        "_cancel_stale_orders",
        "_cancel_stale_side_executors",
        "_derisk_force_min_base_amount",
        "_derisk_force_expectancy_allows",
        "_open_order_count",
        "_open_order_level_ids",
        "_order_size_constraints",
        "_perp_target_base_amount",
        "_position_rebalance_floor",
        "_min_notional_quote",
        "_cancel_stale_orders",
        "_cancel_orphan_orders_on_startup",
        "_update_adaptive_history",
        "_compute_adaptive_spread_knobs",
        "_compute_selective_quote_quality",
        "_compute_alpha_policy",
        "_pick_spread_pct",
        "_risk_loss_metrics",
        "_risk_policy_checks",
        "_edge_gate_update",
    ]
    for name in _methods:
        if not hasattr(ctrl, name):
            method = getattr(EppV24Controller, name, None)
            if method is not None:
                ctrl.__dict__[name] = _types_mod.MethodType(method, ctrl)
    return ctrl


# --- regime helpers ---

def _make_regime_ctrl(
    *,
    ema_val=Decimal("50000"),
    band_pct=Decimal("0.002"),
    drift=_ZERO,
    active_regime="neutral_low_vol",
    pending_regime="neutral_low_vol",
    hold_counter=0,
    config_overrides=None,
):
    ctrl = SimpleNamespace()
    cfg = _make_config(**(config_overrides or {}))
    ctrl.config = cfg
    ctrl._resolved_specs = dict(_DEFAULT_SPECS)
    ctrl._active_regime = active_regime
    ctrl._pending_regime = pending_regime
    ctrl._regime_hold_counter = hold_counter
    ctrl._regime_source = "price_buffer"
    ctrl._external_regime_override = None
    ctrl._external_regime_override_expiry = 0.0
    ctrl._pending_stale_cancel_actions = []
    ctrl.executors_info = []

    detector = RegimeDetector(
        specs=dict(_DEFAULT_SPECS),
        high_vol_band_pct=cfg.high_vol_band_pct,
        shock_drift_30s_pct=cfg.shock_drift_30s_pct,
        shock_drift_atr_multiplier=cfg.shock_drift_atr_multiplier,
        trend_eps_pct=cfg.trend_eps_pct,
        regime_hold_ticks=cfg.regime_hold_ticks,
    )
    detector._active_regime = active_regime
    detector._pending_regime = pending_regime
    detector._regime_hold_counter = hold_counter
    ctrl._regime_detector = detector

    buf = MagicMock()
    buf.ema.return_value = ema_val
    buf.band_pct.return_value = band_pct
    buf.adverse_drift_30s.return_value = drift
    ctrl._price_buffer = buf

    ctrl.market_data_provider = SimpleNamespace(time=lambda: 1_700_000_000.0)
    ctrl._get_ohlcv_ema_and_atr = lambda: (None, None)
    ctrl._cancel_stale_side_executors = _types_mod.MethodType(
        EppV24Controller._cancel_stale_side_executors, ctrl,
    )
    _bind_polymorphic_methods(ctrl)
    return ctrl


def _detect(ctrl, mid):
    """Thin wrapper that strips the band_pct 3rd value for backward-compat test calls."""
    regime, spec, _band = EppV24Controller._detect_regime(ctrl, mid)
    return regime, spec


# --- spread/edge helpers ---

def _make_spread_ctrl(
    *,
    band_pct=Decimal("0.002"),
    drift_raw=_ZERO,
    drift_smooth=_ZERO,
    turnover_notional=_ZERO,
    equity=Decimal("1000"),
    funding_rate=_ZERO,
    is_perp=False,
    adverse_fill_count=0,
    fill_edge_ewma=None,
    maker_fee=Decimal("0.0010"),
    config_overrides=None,
):
    ctrl = SimpleNamespace()
    cfg = _make_config(**(config_overrides or {}))
    ctrl.config = cfg

    buf = MagicMock()
    buf.band_pct.return_value = band_pct
    buf.adverse_drift_30s.return_value = drift_raw
    buf.adverse_drift_smooth.return_value = drift_smooth
    ctrl._price_buffer = buf

    ctrl._maker_fee_pct = maker_fee
    ctrl._taker_fee_pct = maker_fee
    ctrl._is_perp = is_perp
    ctrl._funding_rate = funding_rate
    ctrl._adverse_fill_count = adverse_fill_count
    ctrl._fill_edge_ewma = fill_edge_ewma
    ctrl._fill_count_for_kelly = 0 if fill_edge_ewma is None else 100
    ctrl._auto_calibration_fill_history = []
    ctrl._traded_notional_today = turnover_notional
    ctrl._spread_floor_pct = Decimal("0.0025")
    ctrl._ob_imbalance = _ZERO
    ctrl._last_fill_ts = 0.0
    ctrl._market_spread_bps_ewma = _ZERO
    ctrl._band_pct_ewma = _ZERO
    ctrl._adaptive_effective_min_edge_pct = Decimal(cfg.min_net_edge_bps) / _10K
    ctrl._adaptive_fill_age_s = _ZERO
    ctrl._adaptive_market_floor_pct = _ZERO
    ctrl._adaptive_vol_ratio = _ZERO
    ctrl._daily_equity_open = equity
    ctrl._pnl_governor_active = False
    ctrl._pnl_governor_day_progress = _ZERO
    ctrl._pnl_governor_target_pnl_pct = _ZERO
    ctrl._pnl_governor_target_pnl_quote = _ZERO
    ctrl._pnl_governor_expected_pnl_quote = _ZERO
    ctrl._pnl_governor_actual_pnl_quote = _ZERO
    ctrl._pnl_governor_deficit_ratio = _ZERO
    ctrl._pnl_governor_edge_relax_bps = _ZERO
    ctrl._pnl_governor_size_mult = _ONE
    ctrl._pnl_governor_size_boost_active = False
    ctrl._external_daily_pnl_target_pct_override = None
    ctrl._selective_quote_score = _ZERO
    ctrl._selective_quote_state = "inactive"
    ctrl._selective_quote_reason = "disabled"
    ctrl._selective_quote_adverse_ratio = _ZERO
    ctrl._selective_quote_slippage_p95_bps = _ZERO
    ctrl._alpha_policy_state = "maker_two_sided"
    ctrl._alpha_policy_reason = "startup"
    ctrl._alpha_maker_score = _ZERO
    ctrl._alpha_aggressive_score = _ZERO
    ctrl._alpha_cross_allowed = False
    ctrl._inventory_urgency_score = _ZERO

    ctrl._spread_engine = SpreadEngine(
        turnover_cap_x=cfg.turnover_cap_x,
        spread_step_multiplier=cfg.spread_step_multiplier,
        vol_penalty_multiplier=cfg.vol_penalty_multiplier,
        high_vol_band_pct=cfg.high_vol_band_pct,
        trend_skew_factor=cfg.trend_skew_factor,
        neutral_skew_factor=cfg.neutral_skew_factor,
        inventory_skew_cap_pct=cfg.inventory_skew_cap_pct,
        inventory_skew_vol_multiplier=cfg.inventory_skew_vol_multiplier,
        slippage_est_pct=cfg.slippage_est_pct,
        min_net_edge_bps=cfg.min_net_edge_bps,
        edge_resume_bps=cfg.edge_resume_bps,
        drift_spike_threshold_bps=cfg.drift_spike_threshold_bps,
        drift_spike_mult_max=cfg.drift_spike_mult_max,
        adverse_fill_spread_multiplier=cfg.adverse_fill_spread_multiplier,
        adverse_fill_count_threshold=cfg.adverse_fill_count_threshold,
        turnover_penalty_step=cfg.turnover_penalty_step,
        adaptive_vol_spread_widen_max=cfg.adaptive_vol_spread_widen_max,
    )
    ctrl._pick_spread_pct = _types_mod.MethodType(
        EppV24Controller._pick_spread_pct, ctrl,
    )
    ctrl._risk_loss_metrics = _types_mod.MethodType(
        EppV24Controller._risk_loss_metrics, ctrl,
    )
    ctrl._update_adaptive_history = _types_mod.MethodType(
        EppV24Controller._update_adaptive_history, ctrl,
    )
    ctrl._compute_adaptive_spread_knobs = _types_mod.MethodType(
        EppV24Controller._compute_adaptive_spread_knobs, ctrl,
    )
    ctrl._recent_positive_slippage_p95_bps = _types_mod.MethodType(
        EppV24Controller._recent_positive_slippage_p95_bps, ctrl,
    )
    ctrl._compute_selective_quote_quality = _types_mod.MethodType(
        EppV24Controller._compute_selective_quote_quality, ctrl,
    )
    ctrl._compute_alpha_policy = _types_mod.MethodType(
        EppV24Controller._compute_alpha_policy, ctrl,
    )
    ctrl._fill_edge_below_cost_floor = _types_mod.MethodType(
        EppV24Controller._fill_edge_below_cost_floor, ctrl,
    )
    ctrl._increment_governor_reason_count = _types_mod.MethodType(
        EppV24Controller._increment_governor_reason_count, ctrl,
    )
    ctrl._compute_pnl_governor_size_mult = _types_mod.MethodType(
        EppV24Controller._compute_pnl_governor_size_mult, ctrl,
    )
    ctrl._adverse_fill_soft_pause_active = _types_mod.MethodType(
        EppV24Controller._adverse_fill_soft_pause_active, ctrl,
    )
    ctrl._edge_confidence_soft_pause_active = _types_mod.MethodType(
        EppV24Controller._edge_confidence_soft_pause_active, ctrl,
    )
    ctrl._slippage_soft_pause_active = _types_mod.MethodType(
        EppV24Controller._slippage_soft_pause_active, ctrl,
    )
    _bind_polymorphic_methods(ctrl)
    return ctrl


def _compute_se(ctrl, regime_name="neutral_low_vol", base_pct=Decimal("0.5"), equity=Decimal("1000")):
    spec = _DEFAULT_SPECS[regime_name]
    return EppV24Controller._compute_spread_and_edge(
        ctrl,
        now_ts=1_700_000_000.0,
        regime_name=regime_name,
        regime_spec=spec,
        target_base_pct=spec.target_base_pct,
        base_pct=base_pct,
        equity_quote=equity,
    )


# --- risk helpers ---

def _make_risk_ctrl(
    *,
    equity=Decimal("1000"),
    daily_equity_open=Decimal("1000"),
    daily_equity_peak=Decimal("1000"),
    traded_notional=_ZERO,
    is_perp=False,
    margin_ratio=_ONE,
    startup_sync_done=True,
    position_drift=_ZERO,
    pending_eod_close=False,
    config_overrides=None,
):
    ctrl = SimpleNamespace()
    cfg = _make_config(**(config_overrides or {}))
    ctrl.config = cfg
    ctrl._daily_equity_open = daily_equity_open
    ctrl._daily_equity_peak = daily_equity_peak
    ctrl._traded_notional_today = traded_notional
    ctrl._is_perp = is_perp
    ctrl._margin_ratio = margin_ratio
    ctrl._startup_position_sync_done = startup_sync_done
    ctrl._position_drift_pct = position_drift
    ctrl._pending_eod_close = pending_eod_close
    ctrl._fill_edge_ewma = None
    ctrl._fill_edge_variance = None
    ctrl._fill_count_for_kelly = 0
    ctrl._adverse_fill_count = 0
    ctrl._selective_quote_score = _ZERO
    ctrl._selective_quote_state = "inactive"
    ctrl._selective_quote_reason = "disabled"
    ctrl._selective_quote_adverse_ratio = _ZERO
    ctrl._selective_quote_slippage_p95_bps = _ZERO
    ctrl._maker_fee_pct = cfg.spot_fee_pct
    ctrl._auto_calibration_fill_history = []

    ctrl._risk_evaluator = RiskEvaluator(
        min_base_pct=cfg.min_base_pct,
        max_base_pct=cfg.max_base_pct,
        max_total_notional_quote=cfg.max_total_notional_quote,
        max_daily_turnover_x_hard=cfg.max_daily_turnover_x_hard,
        max_daily_loss_pct_hard=cfg.max_daily_loss_pct_hard,
        max_drawdown_pct_hard=cfg.max_drawdown_pct_hard,
        edge_state_hold_s=30,
        margin_ratio_hard_stop_pct=cfg.margin_ratio_hard_stop_pct,
        margin_ratio_soft_pause_pct=cfg.margin_ratio_soft_pause_pct,
        position_drift_soft_pause_pct=cfg.position_drift_soft_pause_pct,
    )
    _bind_polymorphic_methods(ctrl)
    return ctrl


def _make_edge_gate_ctrl(*, config_overrides=None, hold_s=30):
    ctrl = SimpleNamespace()
    cfg = _make_config(**(config_overrides or {}))
    ctrl.config = cfg
    ctrl._risk_evaluator = RiskEvaluator(
        min_base_pct=cfg.min_base_pct,
        max_base_pct=cfg.max_base_pct,
        max_total_notional_quote=cfg.max_total_notional_quote,
        max_daily_turnover_x_hard=cfg.max_daily_turnover_x_hard,
        max_daily_loss_pct_hard=cfg.max_daily_loss_pct_hard,
        max_drawdown_pct_hard=cfg.max_drawdown_pct_hard,
        edge_state_hold_s=hold_s,
        margin_ratio_hard_stop_pct=cfg.margin_ratio_hard_stop_pct,
        margin_ratio_soft_pause_pct=cfg.margin_ratio_soft_pause_pct,
        position_drift_soft_pause_pct=cfg.position_drift_soft_pause_pct,
    )
    ctrl._net_edge_ewma = None
    ctrl._net_edge_gate = None
    ctrl._edge_gate_blocked = False
    ctrl._soft_pause_edge = False
    ctrl._edge_gate_update = _types_mod.MethodType(EppV24Controller._edge_gate_update, ctrl)
    ctrl._update_edge_gate_ewma = _types_mod.MethodType(EppV24Controller._update_edge_gate_ewma, ctrl)
    _bind_polymorphic_methods(ctrl)
    return ctrl


def _make_spread_state(**overrides):
    defaults = dict(
        band_pct=Decimal("0.002"),
        spread_pct=Decimal("0.003"),
        net_edge=Decimal("0.0005"),
        skew=_ZERO,
        adverse_drift=_ZERO,
        smooth_drift=_ZERO,
        drift_spread_mult=_ONE,
        turnover_x=Decimal("1.0"),
        min_edge_threshold=Decimal("0.0001"),
        edge_resume_threshold=Decimal("0.0004"),
        fill_factor=Decimal("0.4"),
        quote_geometry=QuoteGeometry(
            base_spread_pct=Decimal("0.0025"),
            spread_floor_pct=Decimal("0.0020"),
            reservation_price_adjustment_pct=_ZERO,
            inventory_urgency=_ZERO,
            inventory_skew=_ZERO,
            alpha_skew=_ZERO,
        ),
    )
    defaults.update(overrides)
    return SpreadEdgeState(**defaults)


def _make_market(**overrides):
    defaults = dict(
        is_high_vol=False,
        bid_p=Decimal("49999"),
        ask_p=Decimal("50001"),
        market_spread_pct=Decimal("0.00004"),
        best_bid_size=Decimal("1"),
        best_ask_size=Decimal("1"),
        connector_ready=True,
        order_book_stale=False,
        market_spread_too_small=False,
        side_spread_floor=_ZERO,
    )
    defaults.update(overrides)
    return MarketConditions(**defaults)


# --- fill helpers ---

def _make_fill_event(price, amount, trade_type_name="buy", order_id="test_order_1"):
    ev = MagicMock()
    ev.price = price
    ev.amount = amount
    ev.order_id = order_id
    ev.timestamp = 1_700_000_000.0

    trade_type = MagicMock()
    trade_type.name = trade_type_name
    ev.trade_type = trade_type

    fee = MagicMock()
    fee.fee_amount_in_token.return_value = Decimal("0")
    fee.is_maker = True
    ev.trade_fee = fee
    return ev


def _make_fill_ctrl(
    *,
    mid=Decimal("50000"),
    spread_pct=Decimal("0.003"),
    position_base=_ZERO,
    avg_entry=_ZERO,
    fill_edge_ewma=None,
    fill_edge_variance=None,
    adverse_fill_count=0,
    maker_fee=Decimal("0.0010"),
):
    ctrl = SimpleNamespace()
    ctrl.config = _make_config()
    ctrl._traded_notional_today = _ZERO
    ctrl._fills_count_today = 0
    ctrl._fees_paid_today_quote = _ZERO
    ctrl._realized_pnl_today = _ZERO
    ctrl._position_base = position_base
    ctrl._avg_entry_price = avg_entry
    ctrl._position_long_base = max(_ZERO, position_base)
    ctrl._position_short_base = max(_ZERO, -position_base)
    ctrl._avg_entry_price_long = avg_entry if position_base > _ZERO else _ZERO
    ctrl._avg_entry_price_short = avg_entry if position_base < _ZERO else _ZERO
    ctrl._fill_edge_ewma = fill_edge_ewma
    ctrl._fill_edge_variance = fill_edge_variance
    ctrl._fill_count_for_kelly = 0
    ctrl._adverse_fill_count = adverse_fill_count
    ctrl._maker_fee_pct = maker_fee
    ctrl._taker_fee_pct = maker_fee
    ctrl._fee_source = "manual"
    ctrl._fee_rate_mismatch_warned_today = False
    ctrl._csv = MagicMock()
    ctrl._ops_guard = MagicMock()
    ctrl._ops_guard.state = MagicMock()
    ctrl._ops_guard.state.value = "RUNNING"
    ctrl._save_daily_state = lambda force=False: None
    ctrl._get_telemetry_redis = lambda: None
    ctrl.market_data_provider = SimpleNamespace(time=lambda: 1_700_000_000.0)
    ctrl.processed_data = {
        "spread_pct": spread_pct,
        "mid": mid,
        "adverse_drift_30s": _ZERO,
    }
    _bind_polymorphic_methods(ctrl)
    return ctrl


# ===================================================================
# 1. _detect_regime  (6 tests)
# ===================================================================


class TestDetectRegime:
    def test_neutral_low_vol(self):
        """band_pct well below threshold, mid near EMA → neutral_low_vol."""
        ctrl = _make_regime_ctrl(
            ema_val=Decimal("50000"),
            band_pct=Decimal("0.002"),
            hold_counter=99,
            pending_regime="neutral_low_vol",
        )
        regime, spec = _detect(ctrl, Decimal("50000"))
        assert regime == "neutral_low_vol"
        assert spec.one_sided == "off"

    def test_neutral_high_vol(self):
        """band_pct between mid-threshold (0.004) and high (0.008) → neutral_high_vol."""
        ctrl = _make_regime_ctrl(
            ema_val=Decimal("50000"),
            band_pct=Decimal("0.005"),
            hold_counter=99,
            pending_regime="neutral_high_vol",
        )
        regime, _ = _detect(ctrl, Decimal("50000"))
        assert regime == "neutral_high_vol"

    def test_up_regime(self):
        """Price above EMA * (1 + trend_eps_pct) → up."""
        ema = Decimal("50000")
        mid = ema * (Decimal("1") + Decimal("0.0020"))
        ctrl = _make_regime_ctrl(
            ema_val=ema,
            band_pct=Decimal("0.002"),
            hold_counter=99,
            pending_regime="up",
        )
        regime, spec = _detect(ctrl, mid)
        assert regime == "up"
        assert spec.one_sided == "buy_only"

    def test_down_regime(self):
        """Price below EMA * (1 - trend_eps_pct) → down."""
        ema = Decimal("50000")
        mid = ema * (Decimal("1") - Decimal("0.0020"))
        ctrl = _make_regime_ctrl(
            ema_val=ema,
            band_pct=Decimal("0.002"),
            hold_counter=99,
            pending_regime="down",
        )
        regime, spec = _detect(ctrl, mid)
        assert regime == "down"
        assert spec.one_sided == "sell_only"

    def test_high_vol_shock(self):
        """band_pct >= high_vol_band_pct → high_vol_shock."""
        ctrl = _make_regime_ctrl(
            ema_val=Decimal("50000"),
            band_pct=Decimal("0.010"),
            hold_counter=99,
            pending_regime="high_vol_shock",
        )
        regime, _ = _detect(ctrl, Decimal("50000"))
        assert regime == "high_vol_shock"

    def test_regime_hold_prevents_immediate_switch(self):
        """A single tick detecting 'up' should NOT switch if hold_ticks=3."""
        ctrl = _make_regime_ctrl(
            ema_val=Decimal("50000"),
            band_pct=Decimal("0.002"),
            active_regime="neutral_low_vol",
            pending_regime="neutral_low_vol",
            hold_counter=0,
        )
        mid_up = Decimal("50000") * Decimal("1.002")

        _detect(ctrl, mid_up)
        assert ctrl._active_regime == "neutral_low_vol", "must NOT switch on first tick"

        _detect(ctrl, mid_up)
        assert ctrl._active_regime == "neutral_low_vol", "must NOT switch on second tick"

        _detect(ctrl, mid_up)
        assert ctrl._active_regime == "up", "must switch after regime_hold_ticks=3"


class TestQuoteSideMode:
    def test_alpha_policy_can_disable_quoting(self):
        buy_executor = SimpleNamespace(
            is_active=True,
            id="exec-buy",
            custom_info={"level_id": "buy_0"},
        )
        ctrl = SimpleNamespace(
            config=_make_config(neutral_trend_guard_pct=Decimal("0.0002")),
            executors_info=[buy_executor],
            _regime_ema_value=Decimal("100"),
            _quote_side_mode="buy_only",
            _quote_side_reason="regime",
            _pending_stale_cancel_actions=[],
            _alpha_policy_state="no_trade",
        )
        ctrl._cancel_stale_side_executors = _types_mod.MethodType(
            EppV24Controller._cancel_stale_side_executors, ctrl,
        )
        ctrl._cancel_active_quote_executors = _types_mod.MethodType(
            EppV24Controller._cancel_active_quote_executors, ctrl,
        )
        ctrl._cancel_alpha_no_trade_orders = _types_mod.MethodType(
            EppV24Controller._cancel_alpha_no_trade_orders, ctrl,
        )

        mode = EppV24Controller._resolve_quote_side_mode(
            ctrl,
            mid=Decimal("100"),
            regime_name="neutral_low_vol",
            regime_spec=_DEFAULT_SPECS["neutral_low_vol"],
        )

        assert mode == "off"
        assert ctrl._quote_side_reason == "alpha_no_trade"
        assert len(ctrl._pending_stale_cancel_actions) == 1

    def test_alpha_policy_no_trade_cancels_quotes_even_when_mode_already_off(self):
        buy_executor = SimpleNamespace(
            is_active=True,
            id="exec-buy",
            custom_info={"level_id": "buy_0"},
        )
        sell_executor = SimpleNamespace(
            is_active=True,
            id="exec-sell",
            custom_info={"level_id": "sell_0"},
        )
        ctrl = SimpleNamespace(
            config=_make_config(neutral_trend_guard_pct=Decimal("0.0002")),
            executors_info=[buy_executor, sell_executor],
            _regime_ema_value=Decimal("100"),
            _quote_side_mode="off",
            _quote_side_reason="regime",
            _pending_stale_cancel_actions=[],
            _alpha_policy_state="no_trade",
            _alpha_no_trade_cancel_requested_ids=set(),
        )
        ctrl._cancel_stale_side_executors = _types_mod.MethodType(
            EppV24Controller._cancel_stale_side_executors, ctrl,
        )
        ctrl._cancel_active_quote_executors = _types_mod.MethodType(
            EppV24Controller._cancel_active_quote_executors, ctrl,
        )
        ctrl._cancel_alpha_no_trade_orders = _types_mod.MethodType(
            EppV24Controller._cancel_alpha_no_trade_orders, ctrl,
        )

        mode = EppV24Controller._resolve_quote_side_mode(
            ctrl,
            mid=Decimal("100"),
            regime_name="neutral_low_vol",
            regime_spec=_DEFAULT_SPECS["neutral_low_vol"],
        )

        assert mode == "off"
        assert ctrl._quote_side_reason == "alpha_no_trade"
        assert len(ctrl._pending_stale_cancel_actions) == 2
        assert {getattr(a, "executor_id", "") for a in ctrl._pending_stale_cancel_actions} == {"exec-buy", "exec-sell"}

        # Re-running in the same no-trade state should not enqueue duplicates.
        EppV24Controller._resolve_quote_side_mode(
            ctrl,
            mid=Decimal("100"),
            regime_name="neutral_low_vol",
            regime_spec=_DEFAULT_SPECS["neutral_low_vol"],
        )
        assert len(ctrl._pending_stale_cancel_actions) == 2

    def test_alpha_no_trade_paper_cleanup_is_throttled(self, monkeypatch):
        now = {"ts": 1000.0}
        cancel_calls = []

        def _fake_cancel_stale(self, stale_age_s: float, now_ts=None):
            cancel_calls.append((float(stale_age_s), float(now_ts or 0.0)))
            return 1

        ctrl = SimpleNamespace(
            config=_make_config(is_paper=True),
            market_data_provider=SimpleNamespace(time=lambda: now["ts"]),
            _alpha_no_trade_last_paper_cancel_ts=0.0,
        )
        ctrl._cancel_stale_orders = lambda **kw: _fake_cancel_stale(ctrl, **kw)
        ctrl._cancel_active_runtime_orders = lambda: 0

        first = EppV24Controller._cancel_alpha_no_trade_orders(ctrl)
        second = EppV24Controller._cancel_alpha_no_trade_orders(ctrl)
        now["ts"] = 1006.0
        third = EppV24Controller._cancel_alpha_no_trade_orders(ctrl)

        assert first == 1
        assert second == 0
        assert third == 1
        assert len(cancel_calls) == 2
        assert cancel_calls[0][0] == 0.25

    def test_alpha_no_trade_runtime_order_cleanup_cancels_active_runtime_orders(self):
        cancel_calls = []
        runtime_order = SimpleNamespace(
            client_order_id="pe-runtime-1",
            order_id="pe-runtime-1",
            trading_pair="BTC-USDT",
            current_state="working",
            is_open=True,
        )
        pending_cancel_order = SimpleNamespace(
            client_order_id="pe-runtime-2",
            order_id="pe-runtime-2",
            trading_pair="BTC-USDT",
            current_state="pending_cancel",
            is_open=True,
        )
        strategy = SimpleNamespace(
            _paper_exchange_runtime_orders={
                "bitget_perpetual": {
                    "pe-runtime-1": runtime_order,
                    "pe-runtime-2": pending_cancel_order,
                }
            },
            cancel=lambda connector_name, trading_pair, order_id: cancel_calls.append(
                (connector_name, trading_pair, order_id)
            ),
        )
        ctrl = SimpleNamespace(
            config=_make_config(is_paper=True, connector_name="bitget_perpetual"),
            strategy=strategy,
            _strategy=None,
        )

        canceled = EppV24Controller._cancel_active_runtime_orders(ctrl)

        assert canceled == 1
        assert cancel_calls == [("bitget_perpetual", "BTC-USDT", "pe-runtime-1")]

    def test_alpha_no_trade_paper_cleanup_includes_runtime_orders(self):
        now = {"ts": 1000.0}

        ctrl = SimpleNamespace(
            config=_make_config(is_paper=True),
            market_data_provider=SimpleNamespace(time=lambda: now["ts"]),
            _alpha_no_trade_last_paper_cancel_ts=0.0,
        )
        ctrl._cancel_stale_orders = lambda **kw: 1
        ctrl._cancel_active_runtime_orders = lambda: 2

        canceled = EppV24Controller._cancel_alpha_no_trade_orders(ctrl)

        assert canceled == 3

    def test_neutral_trend_guard_blocks_buys_when_mid_below_ema(self):
        buy_executor = SimpleNamespace(
            is_active=True,
            id="exec-buy",
            custom_info={"level_id": "buy_0"},
        )
        ctrl = SimpleNamespace(
            config=_make_config(neutral_trend_guard_pct=Decimal("0.0002")),
            executors_info=[buy_executor],
            _regime_ema_value=Decimal("100"),
            _quote_side_mode="off",
            _quote_side_reason="regime",
            _pending_stale_cancel_actions=[],
        )
        ctrl._cancel_stale_side_executors = _types_mod.MethodType(
            EppV24Controller._cancel_stale_side_executors, ctrl,
        )

        mode = EppV24Controller._resolve_quote_side_mode(
            ctrl,
            mid=Decimal("99.97"),
            regime_name="neutral_low_vol",
            regime_spec=_DEFAULT_SPECS["neutral_low_vol"],
        )

        assert mode == "sell_only"
        assert ctrl._quote_side_reason == "neutral_trend_guard_down"
        assert len(ctrl._pending_stale_cancel_actions) == 1

    def test_neutral_trend_guard_ignores_small_mid_ema_deviation(self):
        ctrl = SimpleNamespace(
            config=_make_config(neutral_trend_guard_pct=Decimal("0.0002")),
            executors_info=[],
            _regime_ema_value=Decimal("100"),
            _quote_side_mode="off",
            _quote_side_reason="regime",
            _pending_stale_cancel_actions=[],
        )
        ctrl._cancel_stale_side_executors = _types_mod.MethodType(
            EppV24Controller._cancel_stale_side_executors, ctrl,
        )

        mode = EppV24Controller._resolve_quote_side_mode(
            ctrl,
            mid=Decimal("99.99"),
            regime_name="neutral_low_vol",
            regime_spec=_DEFAULT_SPECS["neutral_low_vol"],
        )

        assert mode == "off"
        assert ctrl._quote_side_reason == "regime"
        assert ctrl._pending_stale_cancel_actions == []

    def test_selective_reduced_mode_quotes_with_trend_only(self):
        ctrl = SimpleNamespace(
            config=_make_config(
                neutral_trend_guard_pct=Decimal("0"),
                selective_side_bias_pct=Decimal("0.0002"),
            ),
            executors_info=[],
            _regime_ema_value=Decimal("100"),
            _quote_side_mode="off",
            _quote_side_reason="regime",
            _pending_stale_cancel_actions=[],
            _selective_quote_state="reduced",
        )
        ctrl._cancel_stale_side_executors = _types_mod.MethodType(
            EppV24Controller._cancel_stale_side_executors, ctrl,
        )

        mode = EppV24Controller._resolve_quote_side_mode(
            ctrl,
            mid=Decimal("100.03"),
            regime_name="neutral_low_vol",
            regime_spec=_DEFAULT_SPECS["neutral_low_vol"],
        )

        assert mode == "buy_only"
        assert ctrl._quote_side_reason == "selective_with_trend_up"

    def test_alpha_policy_bias_overrides_neutral_trend_guard(self):
        ctrl = SimpleNamespace(
            config=_make_config(neutral_trend_guard_pct=Decimal("0.0002")),
            executors_info=[],
            _regime_ema_value=Decimal("100"),
            _quote_side_mode="off",
            _quote_side_reason="regime",
            _pending_stale_cancel_actions=[],
            _alpha_policy_state="maker_bias_buy",
            _selective_quote_state="inactive",
        )
        ctrl._cancel_stale_side_executors = _types_mod.MethodType(
            EppV24Controller._cancel_stale_side_executors, ctrl,
        )

        mode = EppV24Controller._resolve_quote_side_mode(
            ctrl,
            mid=Decimal("99.97"),
            regime_name="neutral_low_vol",
            regime_spec=_DEFAULT_SPECS["neutral_low_vol"],
        )

        assert mode == "buy_only"
        assert ctrl._quote_side_reason == "alpha_buy_bias"


# ===================================================================
# 2. _compute_spread_and_edge  (6 tests)
# ===================================================================


class TestComputeSpreadAndEdge:
    def test_spread_floor_applied(self):
        """Spread must be at least the fee-based floor."""
        ctrl = _make_spread_ctrl(band_pct=_ZERO)
        se = _compute_se(ctrl)
        assert se.spread_pct >= ctrl._spread_floor_pct

    def test_edge_resume_threshold_tracks_effective_min_edge_gap(self):
        """Resume threshold should preserve only the configured gap above the effective pause floor."""
        ctrl = _make_spread_ctrl(
            band_pct=_ZERO,
            config_overrides={
                "min_net_edge_bps": 10,
                "edge_resume_bps": 14,
            },
        )
        state_base, _floor = ctrl._spread_engine.compute_spread_and_edge(
            regime_name="neutral_low_vol",
            regime_spec=_DEFAULT_SPECS["neutral_low_vol"],
            band_pct=_ZERO,
            raw_drift=_ZERO,
            smooth_drift=_ZERO,
            target_base_pct=_DEFAULT_SPECS["neutral_low_vol"].target_base_pct,
            base_pct=Decimal("0.5"),
            equity_quote=Decimal("1000"),
            traded_notional_today=_ZERO,
            ob_imbalance=_ZERO,
            ob_imbalance_skew_weight=_ZERO,
            maker_fee_pct=Decimal("0.001"),
            is_perp=False,
            funding_rate=_ZERO,
            adverse_fill_count=0,
            fill_edge_ewma=None,
        )
        assert state_base.min_edge_threshold == Decimal("0.001")
        assert state_base.edge_resume_threshold == Decimal("0.0014")

        state, _floor = ctrl._spread_engine.compute_spread_and_edge(
            regime_name="neutral_low_vol",
            regime_spec=_DEFAULT_SPECS["neutral_low_vol"],
            band_pct=_ZERO,
            raw_drift=_ZERO,
            smooth_drift=_ZERO,
            target_base_pct=_DEFAULT_SPECS["neutral_low_vol"].target_base_pct,
            base_pct=Decimal("0.5"),
            equity_quote=Decimal("1000"),
            traded_notional_today=_ZERO,
            ob_imbalance=_ZERO,
            ob_imbalance_skew_weight=_ZERO,
            maker_fee_pct=Decimal("0.001"),
            is_perp=False,
            funding_rate=_ZERO,
            adverse_fill_count=0,
            fill_edge_ewma=None,
            min_edge_threshold_override_pct=Decimal("0.00038"),
        )
        assert state.min_edge_threshold == Decimal("0.00038")
        assert state.edge_resume_threshold == Decimal("0.00078")

    def test_selective_quote_quality_tightens_effective_min_edge(self):
        state_base = _compute_se(
            _make_spread_ctrl(
                fill_edge_ewma=Decimal("-35"),
                config_overrides={
                    "selective_quoting_enabled": False,
                },
            )
        )
        ctrl = _make_spread_ctrl(
            fill_edge_ewma=Decimal("-35"),
            config_overrides={
                "selective_quoting_enabled": True,
                "selective_quality_min_fills": 20,
                "selective_quality_edge_tighten_max_bps": Decimal("2.0"),
                "selective_neutral_extra_edge_bps": Decimal("1.0"),
            },
        )
        ctrl._fill_count_for_kelly = 50

        state = _compute_se(ctrl)

        assert state.min_edge_threshold > state_base.min_edge_threshold
        assert ctrl._selective_quote_state == "reduced"
        assert ctrl._selective_quote_reason == "negative_fill_edge"

    def test_spread_state_contains_quote_geometry_breakout(self):
        ctrl = _make_spread_ctrl()
        state = _compute_se(ctrl, base_pct=Decimal("0.35"))

        assert state.quote_geometry.base_spread_pct > 0
        assert state.quote_geometry.spread_floor_pct == ctrl._spread_floor_pct
        assert state.quote_geometry.reservation_price_adjustment_pct == state.skew
        assert state.quote_geometry.inventory_urgency > 0

    def test_alpha_policy_blocks_neutral_when_edge_buffer_is_weak(self):
        ctrl = _make_spread_ctrl()
        ctrl._ob_imbalance = _ZERO
        weak_state = _make_spread_state(
            net_edge=Decimal("0.0001"),
            min_edge_threshold=Decimal("0.0001"),
        )
        metrics = EppV24Controller._compute_alpha_policy(
            ctrl,
            regime_name="neutral_low_vol",
            spread_state=weak_state,
            market=_make_market(),
            target_net_base_pct=Decimal("0.50"),
            base_pct_net=Decimal("0.50"),
        )

        assert metrics["state"] == "no_trade"
        assert ctrl._alpha_policy_reason == "neutral_low_edge"

    def test_alpha_policy_allows_neutral_quote_when_edge_above_resume_threshold(self):
        ctrl = _make_spread_ctrl(
            config_overrides={
                "alpha_policy_no_trade_threshold": Decimal("0.60"),
            }
        )
        ctrl._ob_imbalance = _ZERO
        tradable_state = _make_spread_state(
            net_edge=Decimal("0.00045"),
            min_edge_threshold=Decimal("0.00035"),
            edge_resume_threshold=Decimal("0.00040"),
        )
        metrics = EppV24Controller._compute_alpha_policy(
            ctrl,
            regime_name="neutral_low_vol",
            spread_state=tradable_state,
            market=_make_market(),
            target_net_base_pct=Decimal("0.50"),
            base_pct_net=Decimal("0.50"),
        )

        assert metrics["maker_score"] < Decimal("0.60")
        assert metrics["state"] == "maker_two_sided"
        assert ctrl._alpha_policy_reason == "maker_baseline"

    def test_alpha_policy_allows_aggressive_inventory_relief(self):
        ctrl = _make_spread_ctrl()
        ctrl._ob_imbalance = Decimal("0.60")
        strong_state = _make_spread_state(
            net_edge=Decimal("0.0008"),
            min_edge_threshold=Decimal("0.0001"),
            adverse_drift=Decimal("0.00002"),
            smooth_drift=Decimal("0.00001"),
            quote_geometry=QuoteGeometry(
                base_spread_pct=Decimal("0.0025"),
                spread_floor_pct=Decimal("0.0020"),
                reservation_price_adjustment_pct=Decimal("0.0004"),
                inventory_urgency=Decimal("0.80"),
                inventory_skew=Decimal("0.00025"),
                alpha_skew=Decimal("0.00015"),
            ),
        )
        metrics = EppV24Controller._compute_alpha_policy(
            ctrl,
            regime_name="up",
            spread_state=strong_state,
            market=_make_market(),
            target_net_base_pct=Decimal("0.70"),
            base_pct_net=Decimal("0.05"),
        )

        assert metrics["state"] == "aggressive_buy"
        assert ctrl._alpha_cross_allowed is True

    def test_funding_rate_adds_cost_for_long_perp(self):
        """Positive funding rate on a net-long position increases costs (longs pay shorts)."""
        se_no_funding = _compute_se(
            _make_spread_ctrl(is_perp=True, funding_rate=_ZERO),
            base_pct=Decimal("0.3"),
        )
        se_with_funding = _compute_se(
            _make_spread_ctrl(is_perp=True, funding_rate=Decimal("0.0001")),
            base_pct=Decimal("0.3"),
        )
        assert se_with_funding.spread_pct > se_no_funding.spread_pct, (
            "Long position should pay a cost when funding_rate > 0"
        )

    def test_funding_rate_adds_cost_for_short_perp(self):
        """Negative funding rate on a net-short position increases costs (shorts pay longs)."""
        se_no_funding = _compute_se(
            _make_spread_ctrl(is_perp=True, funding_rate=_ZERO),
            base_pct=Decimal("-0.3"),
        )
        se_with_funding = _compute_se(
            _make_spread_ctrl(is_perp=True, funding_rate=Decimal("-0.0001")),
            base_pct=Decimal("-0.3"),
        )
        assert se_with_funding.spread_pct > se_no_funding.spread_pct, (
            "Short position should pay a cost when funding_rate < 0"
        )


class TestEdgeGateEwma:
    def test_shared_edge_gate_can_be_disabled_per_strategy(self):
        ctrl = _make_edge_gate_ctrl(config_overrides={"shared_edge_gate_enabled": False}, hold_s=30)
        ctrl._net_edge_ewma = Decimal("0.00057")
        ctrl._risk_evaluator._edge_gate_blocked = True
        ctrl._risk_evaluator._edge_gate_changed_ts = 10.0
        ctrl._edge_gate_blocked = True
        ctrl._soft_pause_edge = True

        spread_state = _make_spread_state(
            net_edge=Decimal("0.00005"),
            min_edge_threshold=Decimal("0.000775"),
            edge_resume_threshold=Decimal("0.000825"),
        )

        ctrl._update_edge_gate_ewma(100.0, spread_state)

        assert ctrl._net_edge_gate == spread_state.net_edge
        assert ctrl._risk_evaluator.edge_gate_blocked is False
        assert ctrl._risk_evaluator._edge_gate_changed_ts == 100.0
        assert ctrl._edge_gate_blocked is False
        assert ctrl._soft_pause_edge is False

    def test_raw_edge_above_pause_threshold_does_not_false_pause_from_lagging_ewma(self):
        ctrl = _make_edge_gate_ctrl(config_overrides={"edge_gate_ewma_period": 8}, hold_s=30)
        ctrl._net_edge_ewma = Decimal("0.00046")
        ctrl._risk_evaluator._edge_gate_changed_ts = 10.0

        spread_state = _make_spread_state(
            net_edge=Decimal("0.00093"),
            min_edge_threshold=Decimal("0.000775"),
            edge_resume_threshold=Decimal("0.000825"),
        )

        ctrl._update_edge_gate_ewma(100.0, spread_state)

        assert ctrl._edge_gate_blocked is False
        assert ctrl._soft_pause_edge is False
        assert ctrl._net_edge_gate == spread_state.net_edge
        assert ctrl._net_edge_ewma < spread_state.min_edge_threshold

    def test_raw_edge_above_resume_threshold_unblocks_even_if_ewma_lags(self):
        ctrl = _make_edge_gate_ctrl(config_overrides={"edge_gate_ewma_period": 8}, hold_s=30)
        ctrl._net_edge_ewma = Decimal("0.00057")
        ctrl._risk_evaluator._edge_gate_blocked = True
        ctrl._edge_gate_blocked = True
        ctrl._soft_pause_edge = True
        ctrl._risk_evaluator._edge_gate_changed_ts = 10.0

        spread_state = _make_spread_state(
            net_edge=Decimal("0.00093"),
            min_edge_threshold=Decimal("0.000775"),
            edge_resume_threshold=Decimal("0.000825"),
        )

        ctrl._update_edge_gate_ewma(100.0, spread_state)

        assert ctrl._edge_gate_blocked is False
        assert ctrl._soft_pause_edge is False
        assert ctrl._net_edge_gate == spread_state.net_edge
        assert ctrl._net_edge_ewma < spread_state.edge_resume_threshold

    def test_positive_funding_is_free_for_short_perp(self):
        """Positive funding rate on a net-short position should add ZERO cost (shorts receive)."""
        se_no_funding = _compute_se(
            _make_spread_ctrl(is_perp=True, funding_rate=_ZERO),
            base_pct=Decimal("-0.3"),
        )
        se_with_funding = _compute_se(
            _make_spread_ctrl(is_perp=True, funding_rate=Decimal("0.0001")),
            base_pct=Decimal("-0.3"),
        )
        assert se_with_funding.spread_pct == se_no_funding.spread_pct, (
            "Short position receives positive funding — spread must not increase"
        )

    def test_negative_funding_is_free_for_long_perp(self):
        """Negative funding rate on a net-long position should add ZERO cost (longs receive)."""
        se_no_funding = _compute_se(
            _make_spread_ctrl(is_perp=True, funding_rate=_ZERO),
            base_pct=Decimal("0.3"),
        )
        se_with_funding = _compute_se(
            _make_spread_ctrl(is_perp=True, funding_rate=Decimal("-0.0001")),
            base_pct=Decimal("0.3"),
        )
        assert se_with_funding.spread_pct == se_no_funding.spread_pct, (
            "Long position receives negative funding — spread must not increase"
        )

    def test_drift_spike_multiplier_activates(self):
        """When raw drift exceeds smooth drift, spread_pct widens."""
        raw = Decimal("0.005")
        smooth = Decimal("0.001")
        ctrl = _make_spread_ctrl(drift_raw=raw, drift_smooth=smooth)
        se = _compute_se(ctrl)
        assert se.drift_spread_mult > _ONE

    def test_drift_spike_multiplier_inactive_when_no_spike(self):
        """When raw drift == smooth drift, mult should be exactly 1.0."""
        drift = Decimal("0.001")
        ctrl = _make_spread_ctrl(drift_raw=drift, drift_smooth=drift)
        se = _compute_se(ctrl)
        assert se.drift_spread_mult == _ONE

    def test_adverse_fill_multiplier(self):
        """adverse_fill_count >= threshold + non-None EWMA → spread * 1.3."""
        ctrl_normal = _make_spread_ctrl(adverse_fill_count=0)
        ctrl_adverse = _make_spread_ctrl(
            adverse_fill_count=25,
            fill_edge_ewma=Decimal("-5"),
        )
        se_normal = _compute_se(ctrl_normal)
        se_adverse = _compute_se(ctrl_adverse)
        assert se_adverse.spread_pct > se_normal.spread_pct
        actual_ratio = se_adverse.spread_pct / se_normal.spread_pct
        assert abs(actual_ratio - Decimal("1.3")) < Decimal("0.01")

    def test_net_edge_positive_at_default_spread(self):
        """With default config and low vol, net edge should be positive."""
        ctrl = _make_spread_ctrl(band_pct=Decimal("0.001"))
        se = _compute_se(ctrl)
        assert se.net_edge > _ZERO


# ===================================================================
# 3. _evaluate_all_risk  (5 tests)
# ===================================================================


class TestEvaluateAllRisk:
    def test_normal_operation_no_risk(self):
        """No limits breached → empty reasons, no hard_stop."""
        ctrl = _make_risk_ctrl()
        ss = _make_spread_state(turnover_x=Decimal("1.0"))
        reasons, hard, _, _ = EppV24Controller._evaluate_all_risk(
            ctrl, ss, Decimal("0.5"), Decimal("1000"), Decimal("100"), _make_market(),
        )
        assert reasons == []
        assert hard is False

    def test_daily_loss_hard_limit(self):
        """Daily loss > 3% → hard_stop."""
        ctrl = _make_risk_ctrl(
            daily_equity_open=Decimal("1000"),
        )
        ss = _make_spread_state(turnover_x=Decimal("1.0"))
        reasons, hard, daily_loss, _ = EppV24Controller._evaluate_all_risk(
            ctrl, ss, Decimal("0.5"), Decimal("950"), Decimal("100"), _make_market(),
        )
        assert "daily_loss_hard_limit" in reasons
        assert hard is True
        assert daily_loss > Decimal("0.03")

    def test_drawdown_hard_limit(self):
        """Drawdown from peak > 5% → hard_stop."""
        ctrl = _make_risk_ctrl(
            daily_equity_peak=Decimal("1000"),
        )
        ss = _make_spread_state(turnover_x=Decimal("1.0"))
        reasons, hard, _, dd = EppV24Controller._evaluate_all_risk(
            ctrl, ss, Decimal("0.5"), Decimal("940"), Decimal("100"), _make_market(),
        )
        assert "drawdown_hard_limit" in reasons
        assert hard is True
        assert dd > Decimal("0.05")

    def test_turnover_hard_limit(self):
        """Turnover > max_daily_turnover_x_hard → hard_stop."""
        ctrl = _make_risk_ctrl(traded_notional=Decimal("7000"))
        ss = _make_spread_state(turnover_x=Decimal("7.0"))
        reasons, hard, _, _ = EppV24Controller._evaluate_all_risk(
            ctrl, ss, Decimal("0.5"), Decimal("1000"), Decimal("100"), _make_market(),
        )
        assert "daily_turnover_hard_limit" in reasons
        assert hard is True

    def test_base_pct_out_of_band_is_soft(self):
        """base_pct below min → reason added but NOT hard_stop."""
        ctrl = _make_risk_ctrl()
        ss = _make_spread_state(turnover_x=Decimal("1.0"))
        reasons, hard, _, _ = EppV24Controller._evaluate_all_risk(
            ctrl, ss, Decimal("0.10"), Decimal("1000"), Decimal("100"), _make_market(),
        )
        assert "base_pct_below_min" in reasons
        assert hard is False

    def test_adverse_fill_soft_pause_reason_when_edge_below_cost_floor(self):
        ctrl = _make_risk_ctrl(
            config_overrides={
                "adverse_fill_soft_pause_enabled": True,
                "adverse_fill_soft_pause_min_fills": 10,
                "adverse_fill_count_threshold": 3,
                "adverse_fill_soft_pause_cost_floor_mult": Decimal("1.0"),
            }
        )
        ctrl._fill_count_for_kelly = 12
        ctrl._adverse_fill_count = 3
        ctrl._fill_edge_ewma = Decimal("-30")
        ctrl._maker_fee_pct = Decimal("0.0010")
        ss = _make_spread_state(turnover_x=Decimal("1.0"))
        reasons, hard, _, _ = EppV24Controller._evaluate_all_risk(
            ctrl, ss, Decimal("0.5"), Decimal("1000"), Decimal("100"), _make_market(),
        )
        assert "adverse_fill_soft_pause" in reasons
        assert hard is False

    def test_edge_confidence_soft_pause_reason_when_upper_bound_below_cost_floor(self):
        ctrl = _make_risk_ctrl(
            config_overrides={
                "edge_confidence_soft_pause_enabled": True,
                "edge_confidence_soft_pause_min_fills": 20,
                "edge_confidence_soft_pause_z_score": Decimal("1.96"),
                "edge_confidence_soft_pause_cost_floor_mult": Decimal("1.0"),
            }
        )
        ctrl._fill_count_for_kelly = 50
        ctrl._fill_edge_ewma = Decimal("-25")
        ctrl._fill_edge_variance = Decimal("1")
        ctrl._maker_fee_pct = Decimal("0.0010")
        ss = _make_spread_state(turnover_x=Decimal("1.0"))
        reasons, hard, _, _ = EppV24Controller._evaluate_all_risk(
            ctrl, ss, Decimal("0.5"), Decimal("1000"), Decimal("100"), _make_market(),
        )
        assert "edge_confidence_soft_pause" in reasons
        assert hard is False

    def test_slippage_soft_pause_reason_when_recent_p95_above_budget(self):
        ctrl = _make_risk_ctrl(
            config_overrides={
                "slippage_soft_pause_enabled": True,
                "slippage_soft_pause_window_fills": 10,
                "slippage_soft_pause_min_fills": 5,
                "slippage_soft_pause_p95_bps": Decimal("10"),
            }
        )
        ctrl._auto_calibration_fill_history = [
            {"slippage_bps": Decimal("1")},
            {"slippage_bps": Decimal("2")},
            {"slippage_bps": Decimal("3")},
            {"slippage_bps": Decimal("12")},
            {"slippage_bps": Decimal("25")},
            {"slippage_bps": Decimal("40")},
        ]
        ss = _make_spread_state(turnover_x=Decimal("1.0"))
        reasons, hard, _, _ = EppV24Controller._evaluate_all_risk(
            ctrl, ss, Decimal("0.5"), Decimal("1000"), Decimal("100"), _make_market(),
        )
        assert "slippage_soft_pause" in reasons
        assert hard is False

    def test_selective_quote_soft_pause_reason_when_quality_blocked(self):
        ctrl = _make_risk_ctrl()
        ctrl._selective_quote_state = "blocked"
        ss = _make_spread_state(turnover_x=Decimal("1.0"))

        reasons, hard, _, _ = EppV24Controller._evaluate_all_risk(
            ctrl, ss, Decimal("0.5"), Decimal("1000"), Decimal("100"), _make_market(),
        )

        assert "selective_quote_soft_pause" in reasons
        assert hard is False


# ===================================================================
# 4. did_fill_order — fill edge EWMA & adverse counter  (4 tests)
# ===================================================================


class TestDidFillOrder:
    def test_ewma_initializes_on_first_fill(self):
        """First fill sets _fill_edge_ewma to the fill's edge in bps."""
        ctrl = _make_fill_ctrl(mid=Decimal("50000"))
        ev = _make_fill_event(
            price=Decimal("49985"), amount=Decimal("0.01"), trade_type_name="buy",
        )

        EppV24Controller.did_fill_order(ctrl, ev)

        assert ctrl._fill_edge_ewma is not None
        # buy: side_sign=-1, edge = (49985-50000)*(-1)/50000 * 10000 = 3.0 bps
        expected = (Decimal("49985") - Decimal("50000")) * Decimal("-1") / Decimal("50000") * _10K
        assert ctrl._fill_edge_ewma == expected

    def test_ewma_updates_on_subsequent_fill(self):
        """Second fill blends via EWMA (alpha=0.05), not replaces."""
        ctrl = _make_fill_ctrl(
            mid=Decimal("50000"),
            fill_edge_ewma=Decimal("3.0"),
            fill_edge_variance=Decimal("1.0"),
        )
        ev = _make_fill_event(
            price=Decimal("49985"), amount=Decimal("0.01"), trade_type_name="buy",
        )

        EppV24Controller.did_fill_order(ctrl, ev)

        alpha = Decimal("0.05")
        new_edge = (Decimal("49985") - Decimal("50000")) * Decimal("-1") / Decimal("50000") * _10K
        expected = alpha * new_edge + (_ONE - alpha) * Decimal("3.0")
        assert abs(ctrl._fill_edge_ewma - expected) < Decimal("0.001")

    def test_adverse_count_increments_on_negative_edge(self):
        """Negative EWMA below cost floor → adverse counter goes up."""
        ctrl = _make_fill_ctrl(
            mid=Decimal("50000"),
            fill_edge_ewma=Decimal("-20"),
            fill_edge_variance=Decimal("1.0"),
            adverse_fill_count=5,
        )
        # Buy at 50100 → edge = (50100-50000)*(-1)/50000*10000 = -20 bps
        ev = _make_fill_event(
            price=Decimal("50100"), amount=Decimal("0.01"), trade_type_name="buy",
        )

        EppV24Controller.did_fill_order(ctrl, ev)

        assert ctrl._adverse_fill_count > 5

    def test_adverse_count_resets_when_ewma_recovers(self):
        """EWMA above -cost_floor*0.5 → adverse counter resets to 0."""
        ctrl = _make_fill_ctrl(
            mid=Decimal("50000"),
            fill_edge_ewma=Decimal("5.0"),
            fill_edge_variance=Decimal("1.0"),
            adverse_fill_count=15,
        )
        # Buy at 49985 → good edge = +3 bps, EWMA will stay positive after blend
        ev = _make_fill_event(
            price=Decimal("49985"), amount=Decimal("0.01"), trade_type_name="buy",
        )

        EppV24Controller.did_fill_order(ctrl, ev)

        assert ctrl._adverse_fill_count == 0

    def test_probe_fill_is_excluded_from_strategy_accounting(self):
        """probe-ord fills should be logged but not mutate strategy state."""
        ctrl = _make_fill_ctrl(mid=Decimal("50000"))
        ctrl._auto_calibration_record_fill = MagicMock()
        ctrl._save_daily_state = MagicMock()
        ev = _make_fill_event(
            price=Decimal("50010"),
            amount=Decimal("0.02"),
            trade_type_name="buy",
            order_id="probe-ord-12345",
        )
        ev.trade_fee.fee_amount_in_token.return_value = Decimal("0.7")

        EppV24Controller.did_fill_order(ctrl, ev)

        # Probe fills should not affect position/PnL/fill-age state.
        assert ctrl._position_base == _ZERO
        assert ctrl._realized_pnl_today == _ZERO
        assert not hasattr(ctrl, "_last_fill_ts")
        # Turnover/fill-risk counters must ignore probe fills.
        assert ctrl._fills_count_today == 0
        assert ctrl._traded_notional_today == _ZERO
        assert ctrl._fees_paid_today_quote == _ZERO
        assert ctrl._fill_edge_ewma is None
        assert ctrl._fill_count_for_kelly == 0
        ctrl._auto_calibration_record_fill.assert_not_called()
        ctrl._save_daily_state.assert_not_called()
        ctrl._csv.log_fill.assert_called_once()

    def test_regular_fill_still_updates_turnover_and_fill_counters(self):
        """Non-probe fills must continue updating all risk counters."""
        ctrl = _make_fill_ctrl(mid=Decimal("50000"))
        ev = _make_fill_event(
            price=Decimal("50000"),
            amount=Decimal("0.01"),
            trade_type_name="buy",
            order_id="pe-test-1",
        )
        ev.trade_fee.fee_amount_in_token.return_value = Decimal("0.5")

        EppV24Controller.did_fill_order(ctrl, ev)

        assert ctrl._fills_count_today == 1
        assert ctrl._traded_notional_today == Decimal("500")
        assert ctrl._fees_paid_today_quote == Decimal("0.5")

    def test_is_maker_respects_event_flag_when_trade_fee_has_no_marker(self):
        ctrl = _make_fill_ctrl(mid=Decimal("50000"))
        ctrl._maker_fee_pct = Decimal("0.001")
        ctrl._taker_fee_pct = Decimal("0.003")
        ev = SimpleNamespace(
            price=Decimal("49990"),
            amount=Decimal("0.01"),
            order_id="event-maker-flag",
            timestamp=1_700_000_000.0,
            trade_type=SimpleNamespace(name="sell"),
            trade_fee=SimpleNamespace(
                fee_amount_in_token=lambda *_a, **_k: Decimal("0.4999")
            ),
            is_maker=True,
        )

        EppV24Controller.did_fill_order(ctrl, ev)

        fill_row = ctrl._csv.log_fill.call_args[0][0]
        assert fill_row["is_maker"] == "True"

    def test_is_maker_can_be_inferred_from_fee_rate_when_flags_missing(self):
        ctrl = _make_fill_ctrl(mid=Decimal("50000"))
        ctrl._maker_fee_pct = Decimal("0.001")
        ctrl._taker_fee_pct = Decimal("0.003")
        ev = SimpleNamespace(
            price=Decimal("49990"),
            amount=Decimal("0.01"),
            order_id="event-maker-infer",
            timestamp=1_700_000_000.0,
            trade_type=SimpleNamespace(name="sell"),
            trade_fee=SimpleNamespace(
                fee_amount_in_token=lambda *_a, **_k: Decimal("0.4999")
            ),
        )

        EppV24Controller.did_fill_order(ctrl, ev)

        fill_row = ctrl._csv.log_fill.call_args[0][0]
        assert fill_row["is_maker"] == "True"

    def test_duplicate_fill_event_is_ignored(self):
        """Replayed identical fill events should not double-count accounting."""
        ctrl = _make_fill_ctrl(mid=Decimal("50000"))
        ev = _make_fill_event(
            price=Decimal("50000"),
            amount=Decimal("0.01"),
            trade_type_name="buy",
            order_id="dup_fill_order",
        )
        ev.trade_fee.fee_amount_in_token.return_value = Decimal("0.25")

        EppV24Controller.did_fill_order(ctrl, ev)
        EppV24Controller.did_fill_order(ctrl, ev)

        assert ctrl._fills_count_today == 1
        assert ctrl._traded_notional_today == Decimal("500")
        assert ctrl._fees_paid_today_quote == Decimal("0.25")
        ctrl._csv.log_fill.assert_called_once()


# ===================================================================
# 5. _cancel_per_min  (2 tests)
# ===================================================================


class TestCancelPerMin:
    def test_counts_recent_cancels(self):
        """All cancels within the last 60s are counted."""
        ctrl = SimpleNamespace()
        now = 1_700_000_060.0
        ctrl._cancel_events_ts = [now - 10, now - 20, now - 30, now - 50]
        count = EppV24Controller._cancel_per_min(ctrl, now)
        assert count == 4

    def test_filters_old_cancels(self):
        """Cancels older than 60s are excluded and pruned from the list."""
        ctrl = SimpleNamespace()
        now = 1_700_000_060.0
        ctrl._cancel_events_ts = [
            now - 90,  # old
            now - 70,  # old
            now - 30,  # recent
            now - 10,  # recent
        ]
        count = EppV24Controller._cancel_per_min(ctrl, now)
        assert count == 2
        assert len(ctrl._cancel_events_ts) == 2


# ===================================================================
# 6. _risk_policy_checks (direct)  (3 tests)
# ===================================================================


class TestRiskPolicyChecks:
    def _call(self, ctrl, **kwargs):
        defaults = dict(
            base_pct=Decimal("0.5"),
            turnover_x=Decimal("1.0"),
            projected_total_quote=Decimal("100"),
            daily_loss_pct=_ZERO,
            drawdown_pct=_ZERO,
        )
        defaults.update(kwargs)
        return EppV24Controller._risk_policy_checks(ctrl, **defaults)

    def test_clean_pass(self):
        ctrl = _make_risk_ctrl()
        reasons, hard = self._call(ctrl)
        assert reasons == []
        assert hard is False

    def test_base_pct_above_max(self):
        ctrl = _make_risk_ctrl()
        reasons, hard = self._call(ctrl, base_pct=Decimal("0.95"))
        assert "base_pct_above_max" in reasons
        assert hard is False

    def test_projected_notional_cap(self):
        ctrl = _make_risk_ctrl()
        reasons, hard = self._call(ctrl, projected_total_quote=Decimal("1500"))
        assert "projected_total_quote_above_cap" in reasons
        assert hard is False


# ===================================================================
# 7. derisk force mode  (3 tests)
# ===================================================================


class TestDeriskForceMode:
    def _ctrl(self):
        ctrl = SimpleNamespace(
            config=SimpleNamespace(
                derisk_force_taker_after_s=60.0,
                derisk_progress_reset_ratio=Decimal("0.05"),
                derisk_force_taker_expectancy_guard_enabled=False,
                derisk_force_taker_expectancy_window_fills=300,
                derisk_force_taker_expectancy_min_taker_fills=40,
                derisk_force_taker_expectancy_min_quote=Decimal("-0.02"),
                derisk_force_taker_expectancy_override_base_mult=Decimal("10"),
            ),
            _position_base=Decimal("-1"),
            _derisk_cycle_started_ts=0.0,
            _derisk_cycle_start_abs_base=_ZERO,
            _derisk_force_taker=False,
            _auto_calibration_fill_history=[],
            _recently_issued_levels={"buy_0": 1.0},
            _enqueue_force_derisk_executor_cancels=lambda: None,
        )
        _bind_polymorphic_methods(ctrl)
        return ctrl

    def test_enables_after_timeout_without_progress(self):
        ctrl = self._ctrl()
        active = EppV24Controller._update_derisk_force_mode(
            ctrl, 100.0, True, {"base_pct_above_max"}
        )
        assert active is False
        active = EppV24Controller._update_derisk_force_mode(
            ctrl, 160.0, True, {"base_pct_above_max"}
        )
        assert active is True
        assert ctrl._derisk_force_taker is True

    def test_progress_resets_force_timer(self):
        ctrl = self._ctrl()
        EppV24Controller._update_derisk_force_mode(ctrl, 100.0, True, {"base_pct_above_max"})
        ctrl._position_base = Decimal("-0.90")  # 10% reduction >= 5% reset threshold
        active = EppV24Controller._update_derisk_force_mode(
            ctrl, 130.0, True, {"base_pct_above_max"}
        )
        assert active is False
        assert ctrl._derisk_cycle_started_ts == 130.0
        active = EppV24Controller._update_derisk_force_mode(
            ctrl, 185.0, True, {"base_pct_above_max"}
        )
        assert active is False
        active = EppV24Controller._update_derisk_force_mode(
            ctrl, 191.0, True, {"base_pct_above_max"}
        )
        assert active is True

    def test_non_derisk_state_clears_force_mode(self):
        ctrl = self._ctrl()
        EppV24Controller._update_derisk_force_mode(ctrl, 100.0, True, {"base_pct_above_max"})
        EppV24Controller._update_derisk_force_mode(ctrl, 160.0, True, {"base_pct_above_max"})
        active = EppV24Controller._update_derisk_force_mode(ctrl, 161.0, False, set())
        assert active is False
        assert ctrl._derisk_force_taker is False
        assert ctrl._derisk_cycle_started_ts == 0.0

    def test_force_mode_requires_material_abs_position(self):
        ctrl = self._ctrl()
        ctrl.config.derisk_force_taker_min_base_mult = Decimal("2.0")
        ctrl._position_base = Decimal("-0.0015")
        ctrl._avg_entry_price = Decimal("50000")
        ctrl.processed_data = {"reference_price": Decimal("50000")}
        ctrl._min_base_amount = lambda _ref: Decimal("0.001")
        active = EppV24Controller._update_derisk_force_mode(
            ctrl, 100.0, True, {"base_pct_above_max"}
        )
        assert active is False
        active = EppV24Controller._update_derisk_force_mode(
            ctrl, 180.0, True, {"base_pct_above_max"}
        )
        assert active is False
        assert ctrl._derisk_force_taker is False

    def test_force_mode_blocked_by_negative_taker_expectancy(self):
        ctrl = self._ctrl()
        ctrl.config.derisk_force_taker_expectancy_guard_enabled = True
        ctrl.config.derisk_force_taker_expectancy_window_fills = 20
        ctrl.config.derisk_force_taker_expectancy_min_taker_fills = 3
        ctrl.config.derisk_force_taker_expectancy_min_quote = Decimal("0.0")
        ctrl._auto_calibration_fill_history = [
            {"is_maker": False, "net_pnl_quote": Decimal("-0.30")},
            {"is_maker": False, "net_pnl_quote": Decimal("-0.25")},
            {"is_maker": False, "net_pnl_quote": Decimal("-0.10")},
        ]
        active = EppV24Controller._update_derisk_force_mode(
            ctrl, 100.0, True, {"base_pct_above_max"}
        )
        assert active is False
        active = EppV24Controller._update_derisk_force_mode(
            ctrl, 180.0, True, {"base_pct_above_max"}
        )
        assert active is False
        assert ctrl._derisk_force_taker is False
        assert ctrl._derisk_force_taker_expectancy_guard_blocked is True
        assert ctrl._derisk_force_taker_expectancy_guard_reason == "negative_taker_expectancy"

    def test_force_mode_expectancy_guard_overridden_for_large_inventory(self):
        ctrl = self._ctrl()
        ctrl.config.derisk_force_taker_min_base_mult = Decimal("2.0")
        ctrl.config.derisk_force_taker_expectancy_guard_enabled = True
        ctrl.config.derisk_force_taker_expectancy_window_fills = 20
        ctrl.config.derisk_force_taker_expectancy_min_taker_fills = 3
        ctrl.config.derisk_force_taker_expectancy_min_quote = Decimal("0.0")
        ctrl.config.derisk_force_taker_expectancy_override_base_mult = Decimal("3")
        ctrl._position_base = Decimal("-1.0")
        ctrl._avg_entry_price = Decimal("50000")
        ctrl.processed_data = {"reference_price": Decimal("50000")}
        ctrl._min_base_amount = lambda _ref: Decimal("0.1")
        ctrl._auto_calibration_fill_history = [
            {"is_maker": False, "net_pnl_quote": Decimal("-0.30")},
            {"is_maker": False, "net_pnl_quote": Decimal("-0.25")},
            {"is_maker": False, "net_pnl_quote": Decimal("-0.10")},
        ]
        EppV24Controller._update_derisk_force_mode(ctrl, 100.0, True, {"base_pct_above_max"})
        active = EppV24Controller._update_derisk_force_mode(
            ctrl, 180.0, True, {"base_pct_above_max"}
        )
        assert active is True
        assert ctrl._derisk_force_taker is True
        assert ctrl._derisk_force_taker_expectancy_guard_blocked is False
        assert ctrl._derisk_force_taker_expectancy_guard_reason == "override_large_inventory"

    def test_mixed_inventory_reasons_keep_force_timer_active(self):
        ctrl = self._ctrl()
        mixed_reasons = {"base_pct_above_max", "eod_close_pending"}
        active = EppV24Controller._update_derisk_force_mode(
            ctrl, 100.0, True, mixed_reasons
        )
        assert active is False
        active = EppV24Controller._update_derisk_force_mode(
            ctrl, 160.0, True, mixed_reasons
        )
        assert active is True
        assert ctrl._derisk_force_taker is True

    def test_force_mode_skips_level_creation(self):
        ctrl = SimpleNamespace(_derisk_force_taker=True)
        assert EppV24Controller.get_levels_to_execute(ctrl) == []

    def test_paper_open_orders_block_duplicate_level_creation(self):
        open_buy = SimpleNamespace(
            client_order_id="o1", trading_pair="BTC-USDT",
            trade_type=SimpleNamespace(name="BUY"), source_bot="bitget_perpetual",
        )
        connector = SimpleNamespace(
            get_open_orders=lambda: [open_buy],
        )
        ctrl = SimpleNamespace(
            _derisk_force_taker=False,
            config=SimpleNamespace(
                is_paper=True,
                bot_mode="paper",
                connector_name="bitget_perpetual",
                trading_pair="BTC-USDT",
                max_active_executors=8,
            ),
            _runtime_levels=SimpleNamespace(
                cooldown_time=8,
                executor_refresh_time=120,
                buy_spreads=[Decimal("0.001")],
                sell_spreads=[Decimal("0.001")],
            ),
            market_data_provider=SimpleNamespace(time=lambda: 100.0),
            _recently_issued_levels={},
            executors_info=[],
            filter_executors=lambda executors, filter_func: [],
            get_not_active_levels_ids=lambda active_levels_ids: [
                lid for lid in ["buy_0", "sell_0"] if lid not in active_levels_ids
            ],
            _connector=lambda: connector,
            get_level_id_from_side=lambda side, level: ("buy" if "BUY" in str(side) else "sell") + f"_{level}",
        )
        _bind_polymorphic_methods(ctrl)

        assert EppV24Controller.get_levels_to_execute(ctrl) == ["sell_0"]

    def test_open_order_count_filters_to_controller_connector(self):
        open_buy = SimpleNamespace(
            client_order_id="o1", trading_pair="BTC-USDT",
            trade_type=SimpleNamespace(name="BUY"), source_bot="bitget_perpetual",
        )
        foreign_sell = SimpleNamespace(
            client_order_id="o2", trading_pair="BTC-USDT",
            trade_type=SimpleNamespace(name="SELL"), source_bot="other_connector",
        )
        connector = SimpleNamespace(
            get_open_orders=lambda: [open_buy, foreign_sell],
        )
        ctrl = SimpleNamespace(
            config=SimpleNamespace(is_paper=True, bot_mode="paper", connector_name="bitget_perpetual", trading_pair="BTC-USDT"),
            _connector=lambda: connector,
            strategy=None,
            _strategy=None,
        )
        _bind_polymorphic_methods(ctrl)

        assert EppV24Controller._open_order_count(ctrl) == 1

    def test_paper_inflight_accept_blocks_duplicate_level_reissue(self):
        open_buy = SimpleNamespace(
            client_order_id="o1", trading_pair="BTC-USDT",
            trade_type=SimpleNamespace(name="BUY"), source_bot="bitget_perpetual",
        )
        foreign_sell = SimpleNamespace(
            client_order_id="o2", trading_pair="BTC-USDT",
            trade_type=SimpleNamespace(name="SELL"), source_bot="other_connector",
        )
        connector = SimpleNamespace(
            get_open_orders=lambda: [open_buy, foreign_sell],
        )
        ctrl = SimpleNamespace(
            _derisk_force_taker=False,
            config=SimpleNamespace(
                is_paper=True,
                bot_mode="paper",
                connector_name="bitget_perpetual",
                trading_pair="BTC-USDT",
                max_active_executors=8,
            ),
            _runtime_levels=SimpleNamespace(
                cooldown_time=8,
                executor_refresh_time=120,
                buy_spreads=[Decimal("0.001")],
                sell_spreads=[Decimal("0.001")],
            ),
            market_data_provider=SimpleNamespace(time=lambda: 100.0),
            _recently_issued_levels={},
            executors_info=[],
            filter_executors=lambda executors, filter_func: [],
            get_not_active_levels_ids=lambda active_levels_ids: [
                lid for lid in ["buy_0", "sell_0"] if lid not in active_levels_ids
            ],
            _connector=lambda: connector,
            strategy=None,
            _strategy=None,
            get_level_id_from_side=lambda side, level: ("buy" if "BUY" in str(side) else "sell") + f"_{level}",
        )
        _bind_polymorphic_methods(ctrl)

        assert EppV24Controller._open_order_count(ctrl) == 1
        assert EppV24Controller.get_levels_to_execute(ctrl) == ["sell_0"]

    def test_recently_issued_levels_expire_on_cooldown_not_refresh_window(self):
        ctrl = SimpleNamespace(
            _derisk_force_taker=False,
            config=SimpleNamespace(is_paper=False, bot_mode="live", max_active_executors=8),
            _runtime_levels=SimpleNamespace(
                cooldown_time=8,
                executor_refresh_time=120,
                buy_spreads=[Decimal("0.001")],
                sell_spreads=[Decimal("0.001")],
            ),
            market_data_provider=SimpleNamespace(time=lambda: 110.0),
            _recently_issued_levels={"buy_0": 100.0},
            executors_info=[],
            filter_executors=lambda executors, filter_func: [],
            get_not_active_levels_ids=lambda active_levels_ids: ["buy_0", "sell_0"],
            get_level_id_from_side=lambda side, level: ("buy" if "BUY" in str(side) else "sell") + f"_{level}",
        )
        _bind_polymorphic_methods(ctrl)

        levels = EppV24Controller.get_levels_to_execute(ctrl)

        assert levels == ["buy_0", "sell_0"]
        assert ctrl._recently_issued_levels["buy_0"] == 110.0
        assert ctrl._recently_issued_levels["sell_0"] == 110.0

    def test_recently_issued_levels_still_block_inside_cooldown(self):
        ctrl = SimpleNamespace(
            _derisk_force_taker=False,
            config=SimpleNamespace(is_paper=False, bot_mode="live", max_active_executors=8),
            _runtime_levels=SimpleNamespace(
                cooldown_time=8,
                executor_refresh_time=120,
                buy_spreads=[Decimal("0.001")],
                sell_spreads=[Decimal("0.001")],
            ),
            market_data_provider=SimpleNamespace(time=lambda: 105.0),
            _recently_issued_levels={"buy_0": 100.0},
            executors_info=[],
            filter_executors=lambda executors, filter_func: [],
            get_not_active_levels_ids=lambda active_levels_ids: ["buy_0", "sell_0"],
            get_level_id_from_side=lambda side, level: ("buy" if "BUY" in str(side) else "sell") + f"_{level}",
        )
        _bind_polymorphic_methods(ctrl)

        levels = EppV24Controller.get_levels_to_execute(ctrl)

        assert levels == ["sell_0"]
        assert ctrl._recently_issued_levels["buy_0"] == 100.0
        assert ctrl._recently_issued_levels["sell_0"] == 105.0

    def test_selective_reduced_mode_keeps_only_outermost_levels_per_side(self):
        ctrl = SimpleNamespace(
            _derisk_force_taker=False,
            _selective_quote_state="reduced",
            config=SimpleNamespace(
                is_paper=False,
                bot_mode="live",
                max_active_executors=8,
                selective_max_levels_per_side=1,
            ),
            _runtime_levels=SimpleNamespace(
                cooldown_time=8,
                executor_refresh_time=120,
                buy_spreads=[Decimal("0.001"), Decimal("0.002")],
                sell_spreads=[Decimal("0.001"), Decimal("0.002")],
            ),
            market_data_provider=SimpleNamespace(time=lambda: 105.0),
            _recently_issued_levels={},
            executors_info=[],
            filter_executors=lambda executors, filter_func: [],
            get_not_active_levels_ids=lambda active_levels_ids: ["buy_0", "buy_1", "sell_0", "sell_1"],
            get_level_id_from_side=lambda side, level: ("buy" if "BUY" in str(side) else "sell") + f"_{level}",
        )
        _bind_polymorphic_methods(ctrl)

        levels = EppV24Controller.get_levels_to_execute(ctrl)

        assert levels == ["buy_1", "sell_1"]

    def test_force_mode_allows_perp_market_rebalance(self):
        def _mk_rebalance(side, amount):
            return {"side": side, "amount": amount}

        ctrl = SimpleNamespace(
            config=SimpleNamespace(
                connector_name="bitget_perpetual",
                skip_rebalance=True,
                position_rebalance_threshold_pct=Decimal("0.05"),
            ),
            _derisk_force_taker=True,
            _position_base=Decimal("-0.003"),
            processed_data={"reference_price": Decimal("66000")},
            executors_info=[],
            filter_executors=lambda executors, filter_func: [],
            _runtime_required_base_amount=lambda _ref: Decimal("0"),
            get_current_base_position=lambda: Decimal("0"),
            create_position_rebalance_order=_mk_rebalance,
        )
        _bind_polymorphic_methods(ctrl)
        action = EppV24Controller.check_position_rebalance(ctrl)
        assert action is not None
        assert action["amount"] == Decimal("0.003")

    def test_rebalance_allowed_with_mixed_derisk_reasons_in_soft_pause(self):
        def _mk_rebalance(side, amount):
            return {"side": side, "amount": amount}

        ctrl = SimpleNamespace(
            config=SimpleNamespace(
                connector_name="bitget_perpetual",
                skip_rebalance=True,
                position_rebalance_threshold_pct=Decimal("0.05"),
            ),
            _ops_guard=SimpleNamespace(
                state=GuardState.SOFT_PAUSE,
                reasons=["base_pct_above_max", "eod_close_pending"],
            ),
            _derisk_force_taker=False,
            _position_base=Decimal("-0.003"),
            processed_data={"reference_price": Decimal("66000")},
            executors_info=[],
            filter_executors=lambda executors, filter_func: [],
            _runtime_required_base_amount=lambda _ref: Decimal("0"),
            get_current_base_position=lambda: Decimal("0"),
            create_position_rebalance_order=_mk_rebalance,
        )
        _bind_polymorphic_methods(ctrl)
        action = EppV24Controller.check_position_rebalance(ctrl)
        assert action is not None
        assert action["amount"] == Decimal("0.003")

    def test_rebalance_allowed_for_inventory_flatten_in_hard_stop(self):
        def _mk_rebalance(side, amount):
            return {"side": side, "amount": amount}

        ctrl = SimpleNamespace(
            config=SimpleNamespace(
                connector_name="bitget_perpetual",
                skip_rebalance=True,
                position_rebalance_threshold_pct=Decimal("0.05"),
            ),
            _ops_guard=SimpleNamespace(
                state=GuardState.HARD_STOP,
                reasons=["base_pct_above_max", "daily_loss_hard_limit", "eod_close_pending"],
            ),
            _derisk_force_taker=False,
            _position_base=Decimal("-0.003"),
            processed_data={"reference_price": Decimal("66000")},
            executors_info=[],
            filter_executors=lambda executors, filter_func: [],
            _runtime_required_base_amount=lambda _ref: Decimal("0"),
            get_current_base_position=lambda: Decimal("0"),
            create_position_rebalance_order=_mk_rebalance,
        )
        _bind_polymorphic_methods(ctrl)
        action = EppV24Controller.check_position_rebalance(ctrl)
        assert action is not None
        assert action["amount"] == Decimal("0.003")

    def test_rebalance_allowed_in_hard_stop_even_without_inventory_reason(self):
        def _mk_rebalance(side, amount):
            return {"side": side, "amount": amount}

        ctrl = SimpleNamespace(
            config=SimpleNamespace(
                connector_name="bitget_perpetual",
                skip_rebalance=True,
                position_rebalance_threshold_pct=Decimal("0.05"),
            ),
            _ops_guard=SimpleNamespace(
                state=GuardState.HARD_STOP,
                reasons=["daily_loss_hard_limit"],
            ),
            _derisk_force_taker=False,
            _position_base=Decimal("-0.003"),
            processed_data={"reference_price": Decimal("66000")},
            executors_info=[],
            filter_executors=lambda executors, filter_func: [],
            _runtime_required_base_amount=lambda _ref: Decimal("0"),
            get_current_base_position=lambda: Decimal("0"),
            create_position_rebalance_order=_mk_rebalance,
        )
        _bind_polymorphic_methods(ctrl)
        action = EppV24Controller.check_position_rebalance(ctrl)
        assert action is not None
        assert action["amount"] == Decimal("0.003")

    def test_perp_rebalance_targets_signed_net_exposure_not_sell_ladder_inventory(self):
        def _mk_rebalance(side, amount):
            return {"side": side, "amount": amount}

        ctrl = SimpleNamespace(
            config=SimpleNamespace(
                connector_name="bitget_perpetual",
                skip_rebalance=True,
                position_rebalance_threshold_pct=Decimal("0.05"),
            ),
            _ops_guard=SimpleNamespace(
                state=GuardState.SOFT_PAUSE,
                reasons=["base_pct_above_max"],
            ),
            _derisk_force_taker=False,
            _position_base=Decimal("0.003"),
            processed_data={
                "reference_price": Decimal("66000"),
                "equity_quote": Decimal("1000"),
                "target_net_base_pct": Decimal("0"),
            },
            executors_info=[],
            filter_executors=lambda executors, filter_func: [],
            _runtime_required_base_amount=lambda _ref: Decimal("0.0005"),
            get_current_base_position=lambda: Decimal("0"),
            create_position_rebalance_order=_mk_rebalance,
        )
        _bind_polymorphic_methods(ctrl)
        action = EppV24Controller.check_position_rebalance(ctrl)
        assert action is not None
        assert action["side"] is not None
        assert action["amount"] == Decimal("0.003")

    def test_rebalance_skips_small_residual_position_below_min_floor(self):
        def _mk_rebalance(side, amount):
            return {"side": side, "amount": amount}

        ctrl = SimpleNamespace(
            config=SimpleNamespace(
                connector_name="bitget_perpetual",
                skip_rebalance=True,
                position_rebalance_threshold_pct=Decimal("0.05"),
            ),
            _ops_guard=SimpleNamespace(
                state=GuardState.HARD_STOP,
                reasons=["daily_loss_hard_limit"],
            ),
            _derisk_force_taker=False,
            _position_base=Decimal("0.001"),
            processed_data={"reference_price": Decimal("66000")},
            executors_info=[],
            filter_executors=lambda executors, filter_func: [],
            _runtime_required_base_amount=lambda _ref: Decimal("0"),
            _min_base_amount=lambda _ref: Decimal("0.002"),
            get_current_base_position=lambda: Decimal("0"),
            create_position_rebalance_order=_mk_rebalance,
        )
        _bind_polymorphic_methods(ctrl)
        action = EppV24Controller.check_position_rebalance(ctrl)
        assert action is None

    def test_rebalance_skips_small_residual_position_below_min_floor_multiplier(self):
        def _mk_rebalance(side, amount):
            return {"side": side, "amount": amount}

        ctrl = SimpleNamespace(
            config=SimpleNamespace(
                connector_name="bitget_perpetual",
                skip_rebalance=True,
                position_rebalance_threshold_pct=Decimal("0.05"),
                position_rebalance_min_base_mult=Decimal("5.0"),
            ),
            _ops_guard=SimpleNamespace(
                state=GuardState.HARD_STOP,
                reasons=["daily_loss_hard_limit"],
            ),
            _derisk_force_taker=False,
            _position_base=Decimal("0.0004"),
            processed_data={"reference_price": Decimal("66000")},
            executors_info=[],
            filter_executors=lambda executors, filter_func: [],
            _runtime_required_base_amount=lambda _ref: Decimal("0"),
            _min_base_amount=lambda _ref: Decimal("0.0001"),
            get_current_base_position=lambda: Decimal("0"),
            create_position_rebalance_order=_mk_rebalance,
        )
        _bind_polymorphic_methods(ctrl)
        action = EppV24Controller.check_position_rebalance(ctrl)
        assert action is None

    def test_position_rebalance_floor_scales_with_multiplier(self):
        ctrl = SimpleNamespace(
            config=SimpleNamespace(position_rebalance_min_base_mult=Decimal("5.0")),
            _min_base_amount=lambda _ref: Decimal("0.0001"),
        )
        _bind_polymorphic_methods(ctrl)
        floor = EppV24Controller._position_rebalance_floor(ctrl, Decimal("66000"))
        assert floor == Decimal("0.0005")


class TestSizingQuantizationAlignment:
    def test_quantize_amount_respects_paper_spec_min_lot(self):
        rule = SimpleNamespace(
            min_order_size=Decimal("0.001"),
            min_base_amount_increment=Decimal("0.001"),
        )
        connector = SimpleNamespace()
        ctrl = SimpleNamespace(
            config=SimpleNamespace(is_paper=True, connector_name="bitget_perpetual"),
            _connector=lambda: connector,
            _trading_rule=lambda: rule,
            strategy=None,
            _strategy=None,
        )
        _bind_polymorphic_methods(ctrl)

        q_amount = EppV24Controller._quantize_amount(ctrl, Decimal("0.0001"))
        assert q_amount == Decimal("0.001")

    def test_quantize_amount_falls_back_when_trading_rule_missing(self):
        connector = SimpleNamespace()
        ctrl = SimpleNamespace(
            config=SimpleNamespace(is_paper=True, connector_name="bitget_perpetual"),
            _connector=lambda: connector,
            _trading_rule=lambda: None,
            strategy=None,
            _strategy=None,
        )
        _bind_polymorphic_methods(ctrl)

        q_amount = EppV24Controller._quantize_amount(ctrl, Decimal("0.0001"))
        assert q_amount == Decimal("0.0001")

    def test_project_total_amount_quote_scales_min_base_by_levels(self):
        ctrl = SimpleNamespace(
            config=SimpleNamespace(
                max_order_notional_quote=Decimal("250"),
                max_total_notional_quote=Decimal("1000"),
            ),
            _min_notional_quote=lambda: Decimal("5"),
            _min_base_amount=lambda _mid: Decimal("0.001"),
        )

        projected = EppV24Controller._project_total_amount_quote(
            ctrl,
            equity_quote=Decimal("1000"),
            mid=Decimal("67000"),
            quote_size_pct=Decimal("0.001"),
            total_levels=2,
            size_mult=Decimal("1"),
        )
        assert projected == Decimal("134")

    def test_project_total_amount_quote_respects_total_cap_after_min_base_floor(self):
        ctrl = SimpleNamespace(
            config=SimpleNamespace(
                max_order_notional_quote=Decimal("250"),
                max_total_notional_quote=Decimal("12"),
            ),
            _min_notional_quote=lambda: Decimal("5"),
            _min_base_amount=lambda _mid: Decimal("0.001"),
        )

        projected = EppV24Controller._project_total_amount_quote(
            ctrl,
            equity_quote=Decimal("200"),
            mid=Decimal("67000"),
            quote_size_pct=Decimal("0.001"),
            total_levels=2,
            size_mult=Decimal("1"),
        )

        assert projected == Decimal("12")


class TestExecutorRefreshResilience:
    @staticmethod
    def _make_ctrl(
        *,
        now: float,
        reconnect_cooldown_until: float,
        reconnect_grace_until: float,
        is_paper: bool = False,
        order_ack_timeout_s: int = 10,
        stale_timestamp: float = 0.0,
        stuck_timestamp: float | None = None,
    ):
        if stuck_timestamp is None:
            stuck_timestamp = now - 15.0
        stale_ex = SimpleNamespace(id="ex-stale", is_trading=False, is_active=True, timestamp=0.0)
        stale_ex.timestamp = stale_timestamp
        stuck_ex = SimpleNamespace(id="ex-stuck", is_trading=False, is_active=True, timestamp=stuck_timestamp)
        ctrl = SimpleNamespace(
            config=SimpleNamespace(
                id="ctrl_1",
                order_ack_timeout_s=order_ack_timeout_s,
                is_paper=is_paper,
            ),
            _runtime_levels=SimpleNamespace(executor_refresh_time=40),
            market_data_provider=SimpleNamespace(time=lambda: now),
            executors_info=[stale_ex, stuck_ex],
            filter_executors=lambda executors, filter_func: [e for e in executors if filter_func(e)],
            _pending_stale_cancel_actions=[],
            _consecutive_stuck_ticks=7,
            _reconnect_cooldown_until=reconnect_cooldown_until,
            _book_reconnect_grace_until_ts=reconnect_grace_until,
        )
        ctrl._in_reconnect_refresh_suppression_window = _types_mod.MethodType(
            EppV24Controller._in_reconnect_refresh_suppression_window, ctrl
        )
        return ctrl

    def test_refresh_actions_suppressed_during_reconnect_window(self):
        ctrl = self._make_ctrl(now=100.0, reconnect_cooldown_until=130.0, reconnect_grace_until=0.0)
        actions = EppV24Controller.executors_to_refresh(ctrl)
        assert actions == []
        assert ctrl._consecutive_stuck_ticks == 0

    def test_refresh_actions_resume_after_reconnect_window(self):
        ctrl = self._make_ctrl(now=100.0, reconnect_cooldown_until=0.0, reconnect_grace_until=0.0)
        ctrl._consecutive_stuck_ticks = 0
        actions = EppV24Controller.executors_to_refresh(ctrl)
        assert len(actions) == 2
        assert ctrl._consecutive_stuck_ticks == 1

    def test_stale_refresh_uses_refresh_time_uniformly(self):
        ctrl = self._make_ctrl(
            now=100.0,
            reconnect_cooldown_until=0.0,
            reconnect_grace_until=0.0,
            is_paper=True,
            order_ack_timeout_s=90,
            stale_timestamp=40.0,
            stuck_timestamp=85.0,
        )
        ctrl._consecutive_stuck_ticks = 0
        actions = EppV24Controller.executors_to_refresh(ctrl)
        assert len(actions) == 1
        assert ctrl._consecutive_stuck_ticks == 0

    def test_stale_open_orders_canceled_during_refresh(self):
        canceled: list[str] = []
        open_sell = SimpleNamespace(
            client_order_id="paper_v2_200",
            trading_pair="BTC-USDT",
            trade_type=SimpleNamespace(name="SELL"),
            source_bot="bitget_perpetual",
            creation_timestamp=20.0,
        )
        connector = SimpleNamespace(
            get_open_orders=lambda: [open_sell],
        )
        strategy = SimpleNamespace(
            cancel=lambda conn, pair, oid: canceled.append(f"{conn}:{pair}:{oid}"),
        )
        ctrl = self._make_ctrl(
            now=100.0,
            reconnect_cooldown_until=0.0,
            reconnect_grace_until=0.0,
            is_paper=True,
            order_ack_timeout_s=90,
            stale_timestamp=0.0,
            stuck_timestamp=85.0,
        )
        ctrl.config.connector_name = "bitget_perpetual"
        ctrl.config.trading_pair = "BTC-USDT"
        ctrl._connector = lambda: connector
        ctrl.strategy = strategy
        ctrl._strategy = None
        ctrl._recently_issued_levels = {"sell_0": 12.0}
        ctrl._consecutive_stuck_ticks = 0
        ctrl._cancel_stale_orders = _types_mod.MethodType(
            EppV24Controller._cancel_stale_orders, ctrl,
        )

        actions = EppV24Controller.executors_to_refresh(ctrl)

        assert len(actions) == 1
        assert canceled == ["bitget_perpetual:BTC-USDT:paper_v2_200"]
        assert ctrl._recently_issued_levels == {}
        assert ctrl._consecutive_stuck_ticks == 0


class TestRestartFillAgeHydration:
    def test_hydrate_seen_fill_order_ids_from_csv_restores_last_fill_ts(self, tmp_path):
        fills_path = tmp_path / "fills.csv"
        fills_path.write_text(
            "\n".join(
                [
                    "ts,bot_variant,exchange,trading_pair,side,price,amount_base,notional_quote,fee_quote,order_id,state,mid_ref,expected_spread_pct,adverse_drift_30s,fee_source,is_maker,realized_pnl_quote",
                    "2026-03-06T18:10:00+00:00,a,bitget_perpetual,BTC-USDT,buy,68000,0.001,68,0.01,ord-1,running,68000,0.004,0,fee,true,0",
                    "2026-03-06T18:12:30+00:00,a,bitget_perpetual,BTC-USDT,sell,68100,0.001,68.1,0.01,ord-2,running,68100,0.004,0,fee,true,0",
                ]
            ),
            encoding="utf-8",
        )
        ctrl = SimpleNamespace(
            _fills_csv_path=lambda: fills_path,
            _seen_fill_order_ids_cap=10,
            _seen_fill_order_ids=set(),
            _seen_fill_order_ids_fifo=[],
            _last_fill_ts=0.0,
        )

        EppV24Controller._hydrate_seen_fill_order_ids_from_csv(ctrl)

        assert ctrl._seen_fill_order_ids == {"ord-1", "ord-2"}
        assert ctrl._seen_fill_order_ids_fifo == ["ord-1", "ord-2"]
        assert ctrl._last_fill_ts == pytest.approx(
            datetime(2026, 3, 6, 18, 12, 30, tzinfo=UTC).timestamp()
        )

    def test_load_daily_state_restores_last_fill_ts(self):
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        ctrl = SimpleNamespace(
            _state_store=SimpleNamespace(
                load=lambda: {
                    "day_key": today,
                    "equity_open": "1000",
                    "equity_peak": "1005",
                    "traded_notional": "123",
                    "fills_count": 7,
                    "fees_paid": "0.5",
                    "funding_cost": "0",
                    "realized_pnl": "1.2",
                    "last_fill_ts": 1772822127.942416,
                    "position_base": "0.001",
                    "avg_entry_price": "68442.6",
                }
            ),
            _last_fill_ts=0.0,
            _daily_key=None,
            _daily_equity_open=None,
            _daily_equity_peak=None,
            _traded_notional_today=Decimal("0"),
            _fills_count_today=0,
            _fees_paid_today_quote=Decimal("0"),
            _funding_cost_today_quote=Decimal("0"),
            _realized_pnl_today=Decimal("0"),
            _position_base=Decimal("0"),
            _avg_entry_price=Decimal("0"),
        )

        EppV24Controller._load_daily_state(ctrl)

        assert ctrl._last_fill_ts == pytest.approx(1772822127.942416)
        assert ctrl._fills_count_today == 7
        assert ctrl._position_base == Decimal("0.001")

    def test_save_daily_state_persists_last_fill_ts(self):
        save_mock = MagicMock()
        ctrl = SimpleNamespace(
            market_data_provider=SimpleNamespace(time=lambda: 1234.5),
            _state_store=SimpleNamespace(save=save_mock),
            _daily_key="2026-03-06",
            _daily_equity_open=Decimal("1000"),
            _daily_equity_peak=Decimal("1005"),
            _traded_notional_today=Decimal("123"),
            _fills_count_today=7,
            _fees_paid_today_quote=Decimal("0.5"),
            _funding_cost_today_quote=Decimal("0"),
            _realized_pnl_today=Decimal("1.2"),
            _last_fill_ts=1772822127.942416,
            _position_base=Decimal("0.001"),
            _avg_entry_price=Decimal("68442.6"),
        )

        EppV24Controller._save_daily_state(ctrl, force=True)

        saved_data = save_mock.call_args.args[0]
        assert saved_data["last_fill_ts"] == 1772822127.942416


# ===================================================================
# 8. _risk_loss_metrics  (2 tests)
# ===================================================================


class TestRiskLossMetrics:
    def test_daily_loss_pct_calculation(self):
        ctrl = _make_risk_ctrl(
            daily_equity_open=Decimal("1000"),
            daily_equity_peak=Decimal("1000"),
        )
        daily_loss, dd = EppV24Controller._risk_loss_metrics(ctrl, Decimal("970"))
        assert daily_loss == Decimal("0.03")
        assert dd == Decimal("0.03")

    def test_no_loss_returns_zero(self):
        ctrl = _make_risk_ctrl(
            daily_equity_open=Decimal("1000"),
            daily_equity_peak=Decimal("1000"),
        )
        daily_loss, dd = EppV24Controller._risk_loss_metrics(ctrl, Decimal("1000"))
        assert daily_loss == _ZERO
        assert dd == _ZERO


# ===================================================================
# 9. band_pct consistency — _detect_regime returns and propagates band_pct
# ===================================================================


class TestBandPctConsistency:
    def test_detect_regime_returns_band_pct(self):
        """_detect_regime must return a 3-tuple (regime, spec, band_pct)."""
        ctrl = _make_regime_ctrl(
            ema_val=Decimal("50000"),
            band_pct=Decimal("0.003"),
            hold_counter=99,
            pending_regime="neutral_low_vol",
        )
        result = EppV24Controller._detect_regime(ctrl, Decimal("50000"))
        assert len(result) == 3, "_detect_regime must return (regime, spec, band_pct)"
        regime, spec, band_pct = result
        assert isinstance(band_pct, Decimal)
        assert band_pct == Decimal("0.003")

    def test_band_pct_propagated_to_spread_edge(self):
        """When _compute_spread_and_edge is called with band_pct kwarg, it uses that
        value rather than re-reading from price_buffer.  Ensures regime detection
        and spread floor use the same volatility measure."""
        ohlcv_band = Decimal("0.006")    # high-vol OHLCV band
        buffer_band = Decimal("0.001")   # lower price-buffer band

        ctrl = _make_spread_ctrl(band_pct=buffer_band)
        spec = _DEFAULT_SPECS["neutral_low_vol"]

        # When band_pct kwarg not supplied: reads from price_buffer (buffer_band)
        se_no_kwarg = EppV24Controller._compute_spread_and_edge(
            ctrl,
            now_ts=1_700_000_000.0,
            regime_name="neutral_low_vol",
            regime_spec=spec,
            target_base_pct=spec.target_base_pct,
            base_pct=Decimal("0.5"),
            equity_quote=Decimal("1000"),
        )

        # When band_pct kwarg supplied (OHLCV-derived): uses that value
        se_with_kwarg = EppV24Controller._compute_spread_and_edge(
            ctrl,
            now_ts=1_700_000_000.0,
            regime_name="neutral_low_vol",
            regime_spec=spec,
            target_base_pct=spec.target_base_pct,
            base_pct=Decimal("0.5"),
            equity_quote=Decimal("1000"),
            band_pct=ohlcv_band,
        )

        assert se_no_kwarg.band_pct == buffer_band, (
            "Without band_pct kwarg, price-buffer value should be used"
        )
        assert se_with_kwarg.band_pct == ohlcv_band, (
            "With band_pct kwarg, the provided (OHLCV-derived) value should be used"
        )
        # Higher band_pct → higher spread floor → higher spread_pct
        assert se_with_kwarg.spread_pct >= se_no_kwarg.spread_pct, (
            "Higher OHLCV band_pct must produce a higher or equal spread floor"
        )


# ===================================================================
# 10. PnL governor — adaptive min-edge relaxation when behind target
# ===================================================================


class TestPnlGovernor:
    def test_set_external_soft_pause_clears_reason_on_resume(self):
        ctrl = SimpleNamespace(
            _external_soft_pause=False,
            _external_pause_reason="",
        )

        EppV24Controller.set_external_soft_pause(ctrl, True, "risk_guard")
        assert ctrl._external_soft_pause is True
        assert ctrl._external_pause_reason == "risk_guard"

        EppV24Controller.set_external_soft_pause(ctrl, False, "resume")
        assert ctrl._external_soft_pause is False
        assert ctrl._external_pause_reason == ""

    def test_external_override_ttl_expires_stale_intents(self):
        ctrl = SimpleNamespace(
            config=SimpleNamespace(execution_intent_override_ttl_s=60),
            _external_target_base_pct_override=Decimal("0.30"),
            _external_target_base_pct_override_ts=900.0,
            _external_daily_pnl_target_pct_override=Decimal("0.80"),
            _external_daily_pnl_target_pct_override_ts=950.0,
        )

        EppV24Controller._expire_external_intent_overrides(ctrl, 1000.0)

        assert ctrl._external_target_base_pct_override is None
        assert ctrl._external_target_base_pct_override_ts == 0.0
        assert ctrl._external_daily_pnl_target_pct_override == Decimal("0.80")
        assert ctrl._external_daily_pnl_target_pct_override_ts == 950.0

    def test_apply_execution_intent_resume_clears_pause_reason(self):
        ctrl = SimpleNamespace(
            _last_external_model_version="",
            _last_external_intent_reason="",
            _external_soft_pause=True,
            _external_pause_reason="ops_guard",
            market_data_provider=SimpleNamespace(time=lambda: 1_700_000_000.0),
        )
        ctrl.set_external_soft_pause = _types_mod.MethodType(
            EppV24Controller.set_external_soft_pause,
            ctrl,
        )

        ok, msg = EppV24Controller.apply_execution_intent(
            ctrl,
            {"action": "resume", "metadata": {"reason": "manual_resume"}},
        )

        assert ok is True
        assert msg == "ok"
        assert ctrl._external_soft_pause is False
        assert ctrl._external_pause_reason == ""

    def test_apply_execution_intent_sets_external_daily_target_pct(self):
        ctrl = SimpleNamespace(
            _last_external_model_version="",
            _last_external_intent_reason="",
            _external_daily_pnl_target_pct_override=None,
        )
        ok, msg = EppV24Controller.apply_execution_intent(
            ctrl,
            {"action": "set_daily_pnl_target_pct", "metadata": {"daily_pnl_target_pct": "0.6"}},
        )
        assert ok is True
        assert msg == "ok"
        assert ctrl._external_daily_pnl_target_pct_override == Decimal("0.6")

    def test_relaxes_edge_when_behind_target(self):
        ctrl = _make_spread_ctrl(
            equity=Decimal("1000"),
            config_overrides={
                "min_net_edge_bps": 10,
                "pnl_governor_enabled": True,
                "daily_pnl_target_quote": Decimal("100"),
                "pnl_governor_activation_buffer_pct": Decimal("0.0"),
                "pnl_governor_max_edge_bps_cut": Decimal("6"),
            },
        )
        now_ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC).timestamp()
        ctrl._last_fill_ts = now_ts - float(ctrl.config.adaptive_fill_target_age_s)
        ctrl._market_spread_bps_ewma = _ZERO
        ctrl._band_pct_ewma = _ZERO

        effective_min_edge_pct, _floor_pct, _vol_ratio = EppV24Controller._compute_adaptive_spread_knobs(
            ctrl, now_ts, Decimal("1000")
        )

        assert effective_min_edge_pct is not None
        assert effective_min_edge_pct == Decimal("0.0007")  # 10bps - (50% deficit * 6bps)
        assert ctrl._pnl_governor_active is True
        assert ctrl._pnl_governor_edge_relax_bps == Decimal("3")

    def test_stale_fill_relaxation_reduces_edge_floor_without_negative_fill_edge(self):
        ctrl = _make_spread_ctrl(
            equity=Decimal("1000"),
            config_overrides={
                "min_net_edge_bps": 10,
                "pnl_governor_enabled": False,
                "adaptive_fill_target_age_s": 900,
                "adaptive_edge_relax_max_bps": Decimal("8"),
            },
        )
        now_ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC).timestamp()
        ctrl._last_fill_ts = now_ts - 1800.0
        ctrl._market_spread_bps_ewma = _ZERO
        ctrl._band_pct_ewma = _ZERO

        effective_min_edge_pct, _floor_pct, _vol_ratio = EppV24Controller._compute_adaptive_spread_knobs(
            ctrl, now_ts, Decimal("1000")
        )

        assert effective_min_edge_pct is not None
        assert effective_min_edge_pct == Decimal("0.0002")

    def test_stale_fill_relaxation_blocked_when_fill_edge_below_cost_floor(self):
        ctrl = _make_spread_ctrl(
            equity=Decimal("1000"),
            fill_edge_ewma=Decimal("-20"),
            config_overrides={
                "min_net_edge_bps": 10,
                "pnl_governor_enabled": False,
                "adaptive_fill_target_age_s": 900,
                "adaptive_edge_relax_max_bps": Decimal("8"),
                "slippage_est_pct": Decimal("0.0005"),
            },
        )
        now_ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC).timestamp()
        ctrl._last_fill_ts = now_ts - 1800.0
        ctrl._market_spread_bps_ewma = _ZERO
        ctrl._band_pct_ewma = _ZERO

        effective_min_edge_pct, _floor_pct, _vol_ratio = EppV24Controller._compute_adaptive_spread_knobs(
            ctrl, now_ts, Decimal("1000")
        )

        assert effective_min_edge_pct is not None
        assert effective_min_edge_pct == Decimal("0.001")

    def test_does_not_relax_when_ahead_target(self):
        ctrl = _make_spread_ctrl(
            equity=Decimal("1000"),
            config_overrides={
                "min_net_edge_bps": 10,
                "pnl_governor_enabled": True,
                "daily_pnl_target_quote": Decimal("100"),
                "pnl_governor_activation_buffer_pct": Decimal("0.0"),
                "pnl_governor_max_edge_bps_cut": Decimal("6"),
            },
        )
        now_ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC).timestamp()
        ctrl._last_fill_ts = now_ts - float(ctrl.config.adaptive_fill_target_age_s)
        ctrl._market_spread_bps_ewma = _ZERO
        ctrl._band_pct_ewma = _ZERO

        effective_min_edge_pct, _floor_pct, _vol_ratio = EppV24Controller._compute_adaptive_spread_knobs(
            ctrl, now_ts, Decimal("1060")
        )

        assert effective_min_edge_pct is not None
        assert effective_min_edge_pct == Decimal("0.001")
        assert ctrl._pnl_governor_active is False
        assert ctrl._pnl_governor_edge_relax_bps == _ZERO

    def test_does_not_relax_when_fill_edge_below_cost_floor(self):
        ctrl = _make_spread_ctrl(
            equity=Decimal("1000"),
            fill_edge_ewma=Decimal("-20"),
            config_overrides={
                "min_net_edge_bps": 10,
                "pnl_governor_enabled": True,
                "daily_pnl_target_quote": Decimal("100"),
                "pnl_governor_activation_buffer_pct": Decimal("0.0"),
                "pnl_governor_max_edge_bps_cut": Decimal("6"),
                "slippage_est_pct": Decimal("0.0005"),
            },
        )
        now_ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC).timestamp()
        ctrl._last_fill_ts = now_ts - float(ctrl.config.adaptive_fill_target_age_s)
        ctrl._market_spread_bps_ewma = _ZERO
        ctrl._band_pct_ewma = _ZERO

        effective_min_edge_pct, _floor_pct, _vol_ratio = EppV24Controller._compute_adaptive_spread_knobs(
            ctrl, now_ts, Decimal("1000")
        )

        assert effective_min_edge_pct is not None
        assert effective_min_edge_pct == Decimal("0.001")
        assert ctrl._pnl_governor_active is False
        assert ctrl._pnl_governor_edge_relax_bps == _ZERO
        assert ctrl._pnl_governor_activation_reason == "fill_edge_below_cost_floor"

    def test_target_pct_migrates_to_quote_target(self):
        ctrl = _make_spread_ctrl(
            equity=Decimal("1000"),
            config_overrides={
                "min_net_edge_bps": 10,
                "pnl_governor_enabled": True,
                "daily_pnl_target_pct": Decimal("1.5"),
                "daily_pnl_target_quote": Decimal("10"),  # ignored when pct > 0
                "pnl_governor_activation_buffer_pct": Decimal("0.0"),
                "pnl_governor_max_edge_bps_cut": Decimal("6"),
            },
        )
        now_ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC).timestamp()
        ctrl._last_fill_ts = now_ts - float(ctrl.config.adaptive_fill_target_age_s)
        ctrl._market_spread_bps_ewma = _ZERO
        ctrl._band_pct_ewma = _ZERO

        EppV24Controller._compute_adaptive_spread_knobs(ctrl, now_ts, Decimal("1000"))
        assert ctrl._pnl_governor_target_pnl_pct == Decimal("1.5")
        assert ctrl._pnl_governor_target_pnl_quote == Decimal("15")
        assert ctrl._pnl_governor_target_mode == "pct_equity"
        assert ctrl._pnl_governor_target_source == "daily_pnl_target_pct"
        assert ctrl._pnl_governor_target_effective_pct == Decimal("1.5")

    def test_external_daily_target_pct_override_is_applied(self):
        ctrl = _make_spread_ctrl(
            equity=Decimal("1000"),
            config_overrides={
                "min_net_edge_bps": 10,
                "pnl_governor_enabled": True,
                "daily_pnl_target_pct": Decimal("0"),
                "daily_pnl_target_quote": Decimal("0"),
                "pnl_governor_activation_buffer_pct": Decimal("0.0"),
                "pnl_governor_max_edge_bps_cut": Decimal("6"),
            },
        )
        ctrl._external_daily_pnl_target_pct_override = Decimal("0.8")
        now_ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC).timestamp()
        ctrl._last_fill_ts = now_ts - float(ctrl.config.adaptive_fill_target_age_s)
        ctrl._market_spread_bps_ewma = _ZERO
        ctrl._band_pct_ewma = _ZERO

        EppV24Controller._compute_adaptive_spread_knobs(ctrl, now_ts, Decimal("1000"))

        assert ctrl._pnl_governor_target_pnl_pct == Decimal("0.8")
        assert ctrl._pnl_governor_target_pnl_quote == Decimal("8")
        assert ctrl._pnl_governor_target_mode == "pct_equity"
        assert ctrl._pnl_governor_target_source == "execution_intent_daily_pnl_target_pct"
        assert ctrl._pnl_governor_target_effective_pct == Decimal("0.8")

    def test_dynamic_size_boost_respects_clamps(self):
        ctrl = _make_spread_ctrl(
            equity=Decimal("1000"),
            config_overrides={
                "pnl_governor_enabled": True,
                "pnl_governor_max_size_boost_pct": Decimal("0.30"),
                "pnl_governor_size_activation_deficit_pct": Decimal("0.10"),
                "pnl_governor_turnover_soft_cap_x": Decimal("4.0"),
                "pnl_governor_drawdown_soft_cap_pct": Decimal("0.02"),
                "margin_ratio_soft_pause_pct": Decimal("0.20"),
            },
        )
        ctrl._pnl_governor_deficit_ratio = Decimal("0.60")
        ctrl._daily_equity_peak = Decimal("1000")
        ctrl._daily_equity_open = Decimal("1000")
        ctrl._margin_ratio = Decimal("0.40")

        mult = EppV24Controller._compute_pnl_governor_size_mult(
            ctrl, equity_quote=Decimal("1000"), turnover_x=Decimal("1.0")
        )
        assert mult > _ONE
        assert mult <= Decimal("1.30")
        assert ctrl._pnl_governor_size_boost_active is True

        # Turnover clamp disables boost.
        mult_turnover = EppV24Controller._compute_pnl_governor_size_mult(
            ctrl, equity_quote=Decimal("1000"), turnover_x=Decimal("5.0")
        )
        assert mult_turnover == _ONE

    def test_dynamic_size_boost_blocked_when_fill_edge_below_cost_floor(self):
        ctrl = _make_spread_ctrl(
            equity=Decimal("1000"),
            fill_edge_ewma=Decimal("-20"),
            config_overrides={
                "pnl_governor_enabled": True,
                "pnl_governor_max_size_boost_pct": Decimal("0.30"),
                "pnl_governor_size_activation_deficit_pct": Decimal("0.10"),
                "pnl_governor_turnover_soft_cap_x": Decimal("4.0"),
                "pnl_governor_drawdown_soft_cap_pct": Decimal("0.02"),
                "margin_ratio_soft_pause_pct": Decimal("0.20"),
                "slippage_est_pct": Decimal("0.0005"),
            },
        )
        ctrl._pnl_governor_deficit_ratio = Decimal("0.60")
        ctrl._daily_equity_peak = Decimal("1000")
        ctrl._daily_equity_open = Decimal("1000")
        ctrl._margin_ratio = Decimal("0.40")

        mult = EppV24Controller._compute_pnl_governor_size_mult(
            ctrl, equity_quote=Decimal("1000"), turnover_x=Decimal("1.0")
        )
        assert mult == _ONE
        assert ctrl._pnl_governor_size_boost_active is False
        assert ctrl._pnl_governor_size_boost_reason == "fill_edge_below_cost_floor"

    def test_spread_competitiveness_cap(self):
        ctrl = _make_spread_ctrl(config_overrides={"max_quote_to_market_spread_mult": Decimal("1.2")})
        market = _make_market(market_spread_pct=Decimal("0.002"), side_spread_floor=Decimal("0.0002"))
        buy, sell = EppV24Controller._apply_spread_competitiveness_cap(
            ctrl,
            buy_spreads=[Decimal("0.0030"), Decimal("0.0010")],
            sell_spreads=[Decimal("0.0025")],
            market=market,
        )
        # cap_side = max(0.0002, 0.002 * 1.2 / 2) = 0.0012
        assert buy[0] == Decimal("0.0012")
        assert buy[1] == Decimal("0.0010")
        assert sell[0] == Decimal("0.0012")


# ===================================================================
# 11. OHLCV lookahead prevention — _get_ohlcv_ema_and_atr
# ===================================================================

# Lightweight mock DataFrame/Series that satisfies the production code's
# interface without requiring pandas.

class _MockIloc:
    """Supports df.iloc[key] for both row-slicing (MockDF) and index lookup (list)."""

    def __init__(self, target):
        self._target = target

    def __getitem__(self, key):
        if isinstance(self._target, _MockDF):
            return _MockDF(self._target._rows[key])
        # list / sequence → direct subscript
        return self._target[key]


class _MockSeries:
    def __init__(self, data: list):
        self._data = data
        self.values = data

    @property
    def iloc(self):
        return _MockIloc(self._data)


class _MockDF:
    """Minimal DataFrame stub used by _get_ohlcv_ema_and_atr tests."""

    def __init__(self, rows):
        # rows may arrive as a list-slice, re-materialise if needed
        self._rows = list(rows)
        self.columns = list(self._rows[0].keys()) if self._rows else []

    @property
    def empty(self):
        return len(self._rows) == 0

    def __len__(self):
        return len(self._rows)

    def __getitem__(self, col):
        return _MockSeries([r[col] for r in self._rows])

    @property
    def iloc(self):
        return _MockIloc(self)


class TestOhlcvLookaheadPrevention:
    """Verify that _get_ohlcv_ema_and_atr drops the current (forming) candle."""

    def _make_ohlcv_ctrl(self, df, now_s: float):
        ctrl = SimpleNamespace()
        ctrl.config = _make_config(
            ema_period=3,
            atr_period=2,
            candles_connector="binance",
            candles_trading_pair="BTC-USDT",
        )
        ctrl.market_data_provider = SimpleNamespace(
            time=lambda: now_s,
            get_candles_df=lambda connector, pair, interval, limit: df,
        )
        return ctrl

    def _make_candles_df(self, n_closed: int, add_forming: bool, now_s: float):
        """Build a synthetic HB-style candles mock.

        Closed bars have timestamps > 60 s before *now_s*.
        The forming bar (when added) opened 30 s ago — still within the minute.
        """
        base_price = 50000.0
        rows = []
        for i in range(n_closed):
            ts_s = now_s - (n_closed - i) * 60 - 5   # 5 s padding past the minute
            rows.append({
                "timestamp": ts_s * 1000.0,  # HB candles use epoch-ms
                "open": base_price,
                "high": base_price + 10.0,
                "low": base_price - 10.0,
                "close": float(base_price + i),
                "volume": 100.0,
            })
        if add_forming:
            rows.append({
                "timestamp": (now_s - 30.0) * 1000.0,  # opened 30 s ago → still forming
                "open": base_price,
                "high": base_price + 500.0,   # extreme range that would distort ATR
                "low": base_price - 500.0,
                "close": base_price + 5000.0, # extreme close that would distort EMA
                "volume": 200.0,
            })
        return _MockDF(rows)

    def test_closed_candles_return_valid_result(self):
        """Controller returns (ema, band_pct) when only closed candles are present."""
        now_s = 1_700_000_000.0
        df = self._make_candles_df(n_closed=10, add_forming=False, now_s=now_s)
        ctrl = self._make_ohlcv_ctrl(df, now_s)
        ema, band = EppV24Controller._get_ohlcv_ema_and_atr(ctrl)
        assert ema is not None, "Should return EMA from closed candles"
        assert band is not None, "Should return band_pct from closed candles"

    def test_forming_candle_is_dropped(self):
        """When the last candle is still forming it must be excluded from EMA/ATR."""
        now_s = 1_700_000_000.0

        df_closed = self._make_candles_df(n_closed=10, add_forming=False, now_s=now_s)
        ctrl_closed = self._make_ohlcv_ctrl(df_closed, now_s)
        ema_closed, band_closed = EppV24Controller._get_ohlcv_ema_and_atr(ctrl_closed)

        # Add a forming bar with extreme values that would clearly contaminate results.
        df_with_forming = self._make_candles_df(n_closed=10, add_forming=True, now_s=now_s)
        ctrl_with_forming = self._make_ohlcv_ctrl(df_with_forming, now_s)
        ema_forming, band_forming = EppV24Controller._get_ohlcv_ema_and_atr(ctrl_with_forming)

        assert ema_forming is not None, "Should still produce EMA after dropping forming candle"
        assert band_forming is not None, "Should still produce band after dropping forming candle"
        assert abs(float(ema_forming) - float(ema_closed)) < 500.0, (
            "EMA should match closed-only result; forming candle (close=55000) must be excluded"
        )
        assert float(band_forming) < 0.05, (
            "band_pct must not be inflated by the forming candle's 1000-point range"
        )

    def test_returns_none_when_insufficient_closed_bars(self):
        """After dropping the forming bar, if fewer than ema_period bars remain → None."""
        now_s = 1_700_000_000.0
        # Only 2 closed bars; ema_period=3 requires at least 3
        df = self._make_candles_df(n_closed=2, add_forming=True, now_s=now_s)
        ctrl = self._make_ohlcv_ctrl(df, now_s)
        ema, band = EppV24Controller._get_ohlcv_ema_and_atr(ctrl)
        assert ema is None, "Too few closed bars after dropping forming candle → None"


# ===================================================================
# 12. avg_entry_price on position flip  (4 tests)
# ===================================================================


class TestAvgEntryPriceFlip:
    """FC-1 fix: avg_entry_price must only use the opening-side notional
    when a fill crosses through zero (short→long or long→short).
    """

    def _ctrl(self, position_base, avg_entry_price, maker_fee=Decimal("0.0002")):
        ctrl = _make_fill_ctrl(
            mid=Decimal("50000"),
            position_base=position_base,
            avg_entry=avg_entry_price,
            maker_fee=maker_fee,
        )
        return ctrl

    def test_buy_flip_short_to_long_avg_entry(self):
        """Buy 1.5 while short -1 → new long 0.5 at fill_price (not 3× fill_price)."""
        ctrl = self._ctrl(position_base=Decimal("-1"), avg_entry_price=Decimal("49000"))
        fill_px = Decimal("50000")
        ev = _make_fill_event(price=fill_px, amount=Decimal("1.5"), trade_type_name="buy")

        EppV24Controller.did_fill_order(ctrl, ev)

        # New position should be long 0.5
        assert ctrl._position_base == Decimal("-1") + Decimal("1.5")
        # avg_entry for the new long: only 0.5 was opened → should equal fill_price
        assert abs(ctrl._avg_entry_price - fill_px) < Decimal("0.01"), (
            f"Expected avg_entry ≈ {fill_px}, got {ctrl._avg_entry_price}"
        )

    def test_sell_flip_long_to_short_avg_entry(self):
        """Sell 1.5 while long +1 → new short -0.5 at fill_price (not 3× fill_price)."""
        ctrl = self._ctrl(position_base=Decimal("1"), avg_entry_price=Decimal("49000"))
        fill_px = Decimal("50000")
        ev = _make_fill_event(price=fill_px, amount=Decimal("1.5"), trade_type_name="sell")

        EppV24Controller.did_fill_order(ctrl, ev)

        assert ctrl._position_base == Decimal("1") - Decimal("1.5")
        assert abs(ctrl._avg_entry_price - fill_px) < Decimal("0.01"), (
            f"Expected avg_entry ≈ {fill_px}, got {ctrl._avg_entry_price}"
        )

    def test_buy_add_to_existing_long_avg_entry(self):
        """Buy 0.5 while long +1 at 49000 → VWAP of (49000×1 + 50000×0.5) / 1.5."""
        ctrl = self._ctrl(position_base=Decimal("1"), avg_entry_price=Decimal("49000"))
        fill_px = Decimal("50000")
        ev = _make_fill_event(price=fill_px, amount=Decimal("0.5"), trade_type_name="buy")

        EppV24Controller.did_fill_order(ctrl, ev)

        expected = (Decimal("49000") * Decimal("1") + Decimal("50000") * Decimal("0.5")) / Decimal("1.5")
        assert abs(ctrl._avg_entry_price - expected) < Decimal("0.01"), (
            f"Expected VWAP {expected}, got {ctrl._avg_entry_price}"
        )

    def test_sell_add_to_existing_short_avg_entry(self):
        """Sell 0.5 while short -1 at 49000 → VWAP of (49000×1 + 50000×0.5) / 1.5."""
        ctrl = self._ctrl(position_base=Decimal("-1"), avg_entry_price=Decimal("49000"))
        fill_px = Decimal("50000")
        ev = _make_fill_event(price=fill_px, amount=Decimal("0.5"), trade_type_name="sell")

        EppV24Controller.did_fill_order(ctrl, ev)

        expected = (Decimal("49000") * Decimal("1") + Decimal("50000") * Decimal("0.5")) / Decimal("1.5")
        assert abs(ctrl._avg_entry_price - expected) < Decimal("0.01"), (
            f"Expected VWAP {expected}, got {ctrl._avg_entry_price}"
        )


# ===================================================================
# 13. Fee mismatch bi-directional detection  (2 tests)
# ===================================================================


class TestFeeMismatchDetection:
    """FC-3 fix: fee mismatch warning should fire for UNDER-payment too."""

    def _ctrl_with_fees(self, eff_fee_total, notional_total, fills=15):
        ctrl = _make_fill_ctrl(
            mid=Decimal("50000"),
            maker_fee=Decimal("0.001"),  # 10 bps expected
        )
        ctrl.config = _make_config()
        # Simulate already-accumulated state
        ctrl._filled_count_today = fills
        ctrl._fills_count_today = fills
        ctrl._traded_notional_today = notional_total
        ctrl._fees_paid_today_quote = eff_fee_total
        # Override is_paper to True
        ctrl.config.__class__ = type(
            "_PaperConfig",
            (ctrl.config.__class__,),
            {"is_paper": property(lambda self: True)},
        )
        return ctrl

    def test_under_payment_triggers_warning(self, caplog):
        """Effective fee 100× below min(maker,taker) → UNDER warning emitted."""
        import logging

        # notional = 10000, expected_lo = 0.001 (10 bps), fee_paid = 0.001 (0.01 bps) → way under
        ctrl = _make_fill_ctrl(mid=Decimal("50000"), maker_fee=Decimal("0.001"))
        ctrl.config = _make_config(is_paper=True)  # must be paper mode for this check
        ctrl._fills_count_today = 15
        ctrl._traded_notional_today = Decimal("10000")
        ctrl._fees_paid_today_quote = Decimal("0.001")  # 0.01 bps effective
        ctrl._maker_fee_pct = Decimal("0.001")
        ctrl._taker_fee_pct = Decimal("0.001")

        ev = _make_fill_event(
            price=Decimal("49985"), amount=Decimal("0.001"), trade_type_name="buy"
        )
        with caplog.at_level(logging.WARNING, logger="controllers.epp_v2_4"):
            EppV24Controller.did_fill_order(ctrl, ev)

        under_messages = [r.message for r in caplog.records if "UNDER" in r.message]
        assert len(under_messages) >= 1, "Expected UNDER fee-mismatch warning"

    def test_over_payment_still_triggers_warning(self, caplog):
        """Effective fee 3× above max(maker,taker) → OVER warning still fires."""
        import logging

        ctrl = _make_fill_ctrl(mid=Decimal("50000"), maker_fee=Decimal("0.001"))
        ctrl.config = _make_config(is_paper=True)  # must be paper mode
        ctrl._fills_count_today = 15
        ctrl._traded_notional_today = Decimal("10000")
        # 3× taker fee paid → over-pay warning: effective = 30/10000 = 0.003, expected_hi = 0.001
        ctrl._fees_paid_today_quote = Decimal("30")
        ctrl._maker_fee_pct = Decimal("0.001")
        ctrl._taker_fee_pct = Decimal("0.001")

        ev = _make_fill_event(
            price=Decimal("49985"), amount=Decimal("0.001"), trade_type_name="buy"
        )
        with caplog.at_level(logging.WARNING, logger="controllers.epp_v2_4"):
            EppV24Controller.did_fill_order(ctrl, ev)

        over_messages = [r.message for r in caplog.records if "OVER" in r.message]
        assert len(over_messages) >= 1, "Expected OVER fee-mismatch warning"


# ===================================================================
# 14. Margin ratio fallback leverage correction  (2 tests)
# ===================================================================


class TestMarginRatioFallback:
    """FC-5 fix: fallback margin_ratio must account for leverage."""

    def _ctrl_for_margin(self, leverage: int = 1):
        ctrl = SimpleNamespace()
        ctrl.config = _make_config()
        ctrl.config = type("_Cfg", (), {
            "leverage": leverage,
            "trading_pair": "BTC-USDT",
        })()
        ctrl._is_perp = True
        ctrl._margin_ratio = Decimal("1")

        # No live API margin info available → will use fallback
        connector = MagicMock()
        connector.get_margin_info.side_effect = AttributeError("not available")
        ctrl._connector = lambda: connector
        return ctrl

    def test_leverage_1_margin_ratio_is_equity_over_notional(self):
        """At leverage=1, fallback = quote_bal / position_notional (unchanged)."""
        ctrl = self._ctrl_for_margin(leverage=1)
        mid = Decimal("50000")
        base_bal = Decimal("0.1")      # 0.1 BTC position
        quote_bal = Decimal("5000")    # 5000 USDT — fully collateralised
        EppV24Controller._refresh_margin_ratio(ctrl, mid, base_bal, quote_bal)
        # At 1× leverage: 5000 / (0.1 × 50000) = 5000/5000 = 1.0
        assert abs(ctrl._margin_ratio - Decimal("1.0")) < Decimal("0.001")

    def test_leverage_5_margin_ratio_accounts_for_leverage(self):
        """At leverage=5, fallback = (quote_bal × 5) / position_notional."""
        ctrl = self._ctrl_for_margin(leverage=5)
        mid = Decimal("50000")
        base_bal = Decimal("0.5")      # 0.5 BTC position → 25000 USDT notional
        quote_bal = Decimal("5000")    # 5000 USDT margin posted (1/5 of notional = 20%)
        EppV24Controller._refresh_margin_ratio(ctrl, mid, base_bal, quote_bal)
        # leverage=5: (5000 × 5) / 25000 = 25000/25000 = 1.0
        # i.e. margin_ratio=1.0 means fully margined at 5× leverage
        expected = (quote_bal * Decimal("5")) / (base_bal * mid)
        assert abs(ctrl._margin_ratio - expected) < Decimal("0.001")


# ===================================================================
# 15. Portfolio risk guard (real-time global breaker)  (2 tests)
# ===================================================================


class TestPortfolioRiskGuard:
    def _ctrl(self, payload: dict):
        import json
        ctrl = SimpleNamespace()
        ctrl.config = _make_config(
            instance_name="bot1",
            portfolio_risk_guard_enabled=True,
            portfolio_risk_guard_check_s=1,
            portfolio_risk_guard_max_age_s=15,
            portfolio_risk_stream_name="hb.portfolio_risk.v1",
        )
        ctrl._last_portfolio_risk_check_ts = 0.0
        ctrl._portfolio_risk_hard_stop_latched = False
        ctrl._ops_guard = MagicMock()
        mock_redis = MagicMock()
        mock_redis.xrevrange.return_value = [("1-0", {"payload": json.dumps(payload)})]
        ctrl._get_telemetry_redis = lambda: mock_redis
        return ctrl

    def test_global_kill_switch_snapshot_forces_hard_stop(self):
        now = 1_700_000_010.0
        payload = {
            "portfolio_action": "kill_switch",
            "timestamp_ms": int(now * 1000),
            "risk_scope_bots": ["bot1", "bot3"],
        }
        ctrl = self._ctrl(payload)

        EppV24Controller._check_portfolio_risk_guard(ctrl, now)

        ctrl._ops_guard.force_hard_stop.assert_called_once_with("portfolio_risk_global_breach")
        assert ctrl._portfolio_risk_hard_stop_latched is True

    def test_stale_snapshot_is_ignored(self):
        now = 1_700_000_030.0
        payload = {
            "portfolio_action": "kill_switch",
            "timestamp_ms": int((now - 60) * 1000),  # stale (older than max_age_s=15)
            "risk_scope_bots": ["bot1"],
        }
        ctrl = self._ctrl(payload)

        EppV24Controller._check_portfolio_risk_guard(ctrl, now)

        ctrl._ops_guard.force_hard_stop.assert_not_called()
        assert ctrl._portfolio_risk_hard_stop_latched is False


class TestMinuteSnapshotTelemetry:
    def test_zero_quote_levels_project_zero_notional(self):
        ctrl = SimpleNamespace(
            config=SimpleNamespace(
                max_order_notional_quote=Decimal("250"),
                max_total_notional_quote=Decimal("1000"),
            ),
            _min_notional_quote=lambda: Decimal("5"),
            _min_base_amount=lambda _mid: Decimal("0.001"),
        )

        projected = EppV24Controller._project_total_amount_quote(
            ctrl,
            equity_quote=Decimal("1000"),
            mid=Decimal("67000"),
            quote_size_pct=Decimal("0.001"),
            total_levels=0,
            size_mult=Decimal("1"),
        )

        assert projected == Decimal("0")

    def test_publish_bot_minute_snapshot_telemetry_emits_bot_snapshot_event(self):
        mock_redis = MagicMock()
        ctrl = SimpleNamespace(
            config=SimpleNamespace(
                controller_name="epp_v2_4_bot1",
                instance_name="bot1",
                connector_name="bitget_perpetual",
                trading_pair="BTC-USDT",
            ),
            id="ctrl_bot1",
            _get_telemetry_redis=lambda: mock_redis,
            _position_base=Decimal("-0.001"),
            _avg_entry_price=Decimal("67500"),
            _realized_pnl_today=Decimal("1.5"),
        )
        minute_row = {
            "state": "running",
            "regime": "neutral_low_vol",
            "mid": "67000",
            "equity_quote": "1000",
            "base_pct": "0.01",
            "target_base_pct": "0.0",
            "spread_pct": "0.0005",
            "net_edge_pct": "0.0002",
            "turnover_today_x": "0.5",
            "daily_loss_pct": "0.0",
            "drawdown_pct": "0.0",
            "fills_count_today": "3",
            "fees_paid_today_quote": "0.05",
            "fee_source": "manual",
            "maker_fee_pct": "0.0002",
            "taker_fee_pct": "0.0006",
            "risk_reasons": "",
            "bot_mode": "paper",
            "accounting_source": "paper_desk_v2",
            "bot_variant": "a",
            "quote_side_mode": "off",
            "quote_side_reason": "regime",
            "alpha_policy_state": "bot5_strategy_gate",
            "alpha_policy_reason": "no_flow_direction",
            "projected_total_quote": "0",
            "soft_pause_edge": "False",
            "orders_active": "0",
        }

        EppV24Controller._publish_bot_minute_snapshot_telemetry(
            ctrl, "2026-03-08T04:02:00+00:00", minute_row
        )

        mock_redis.xadd.assert_called_once()
        payload = json.loads(mock_redis.xadd.call_args.args[1]["payload"])
        assert payload["event_type"] == "bot_minute_snapshot"
        assert payload["instance_name"] == "bot1"
        assert payload["controller_id"] == "ctrl_bot1"
        position = payload["position"]
        assert position["trading_pair"] == "BTC-USDT"
        assert position["quantity"] == -0.001
        assert position["side"] == "short"
        assert position["realized_pnl_today"] == 1.5
        assert position["avg_entry_price"] == 67500.0
        assert position["unrealized_pnl"] != 0.0

    def test_publish_bot_minute_snapshot_telemetry_falls_back_to_event_store_file(self, tmp_path, monkeypatch):
        import controllers.epp_v2_4 as epp_module

        fake_module_path = tmp_path / "hbot" / "controllers" / "epp_v2_4.py"
        fake_module_path.parent.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(epp_module, "__file__", str(fake_module_path))

        ctrl = SimpleNamespace(
            config=SimpleNamespace(
                controller_name="epp_v2_4_bot1",
                instance_name="bot1",
                connector_name="bitget_perpetual",
                trading_pair="BTC-USDT",
            ),
            id="ctrl_bot1",
            _get_telemetry_redis=lambda: None,
            _position_base=Decimal("-0.002"),
            _avg_entry_price=Decimal("67500"),
            _realized_pnl_today=Decimal("1.5"),
        )
        minute_row = {
            "state": "running",
            "regime": "neutral_low_vol",
            "mid": "67000",
            "equity_quote": "1000",
            "base_pct": "0.01",
            "target_base_pct": "0.0",
            "spread_pct": "0.0005",
            "net_edge_pct": "0.0002",
            "turnover_today_x": "0.5",
            "daily_loss_pct": "0.0",
            "drawdown_pct": "0.0",
            "fills_count_today": "3",
            "fees_paid_today_quote": "0.05",
            "fee_source": "manual",
            "maker_fee_pct": "0.0002",
            "taker_fee_pct": "0.0006",
            "risk_reasons": "",
            "bot_mode": "paper",
            "accounting_source": "paper_desk_v2",
            "bot_variant": "a",
            "quote_side_mode": "off",
            "quote_side_reason": "regime",
            "alpha_policy_state": "bot5_strategy_gate",
            "alpha_policy_reason": "no_flow_direction",
            "projected_total_quote": "0",
            "soft_pause_edge": "False",
            "orders_active": "0",
        }

        EppV24Controller._publish_bot_minute_snapshot_telemetry(
            ctrl, "2026-03-08T04:02:00+00:00", minute_row
        )

        event_files = sorted((tmp_path / "hbot" / "reports" / "event_store").glob("events_*.jsonl"))
        assert event_files
        payload = json.loads(event_files[-1].read_text(encoding="utf-8").strip())
        assert payload["event_type"] == "bot_minute_snapshot"
        assert payload["instance_name"] == "bot1"
        assert payload["payload"]["metadata"]["quote_side_reason"] == "regime"


# ===================================================================
# 16. Paper equity/state reconciliation (2 tests)
# ===================================================================


class TestPaperEquityStateReconciliation:
    def test_paper_reset_state_on_startup_enabled_reads_nested_config(self):
        cfg = _make_config(
            is_paper=True,
            paper_engine=SimpleNamespace(paper_reset_state_on_startup=True),
        )

        assert _paper_reset_state_on_startup_enabled(cfg) is True

    def test_compute_equity_prefers_paper_portfolio_equity_for_perp_risk(self):
        # paper_portfolio_snapshot returns true equity (cash + unrealized PnL);
        # the method must prefer it over the raw cash quote_bal so that risk
        # gates and sizing see the correct mark-to-market value.
        paper_equity = Decimal("195")  # cash 200 minus $5 unrealized loss
        mock_connector = SimpleNamespace(
            paper_portfolio_snapshot=lambda mid: {"equity_quote": paper_equity}
        )
        ctrl = SimpleNamespace()
        ctrl.config = _make_config(
            is_paper=True,
        )
        ctrl._is_perp = True
        ctrl._position_base = Decimal("0.002")
        ctrl._get_balances = lambda: (Decimal("0.002"), Decimal("200"))
        ctrl._refresh_margin_ratio = lambda mid, pos_base, quote_bal: None
        ctrl._connector = lambda: mock_connector

        equity, base_pct_gross, base_pct_net = EppV24Controller._compute_equity_and_base_pcts(
            ctrl, Decimal("60000")
        )

        assert equity == paper_equity
        expected_pct = Decimal("0.002") * Decimal("60000") / paper_equity
        assert abs(base_pct_gross - expected_pct) < Decimal("0.000001")
        assert abs(base_pct_net - expected_pct) < Decimal("0.000001")

    def test_compute_equity_collapses_oneway_perp_gross_to_net_exposure(self):
        ctrl = SimpleNamespace()
        ctrl.config = _make_config(
            is_paper=True,
            position_mode="ONEWAY",
        )
        ctrl._is_perp = True
        ctrl._position_base = Decimal("0.001")
        ctrl._position_gross_base = Decimal("0.015")
        ctrl._get_balances = lambda: (Decimal("0.001"), Decimal("200"))
        ctrl._refresh_margin_ratio = lambda mid, pos_base, quote_bal, gross_base=None: None
        ctrl._connector = lambda: None  # no paper snapshot — falls back to quote_bal

        equity, base_pct_gross, base_pct_net = EppV24Controller._compute_equity_and_base_pcts(
            ctrl, Decimal("60000")
        )

        assert equity == Decimal("200")
        expected_pct = Decimal("0.001") * Decimal("60000") / Decimal("200")
        assert abs(base_pct_gross - expected_pct) < Decimal("0.000001")
        assert abs(base_pct_net - expected_pct) < Decimal("0.000001")

def test_maybe_seed_price_buffer_updates_status_and_buffer() -> None:
    class _FakeProvider:
        def seed_price_buffer(self, buffer, key, bars_needed, now_ms):
            buffer.seed_bars(
                [
                    MinuteBar(ts_minute=60, open=Decimal("100"), high=Decimal("100"), low=Decimal("100"), close=Decimal("100")),
                    MinuteBar(ts_minute=120, open=Decimal("101"), high=Decimal("101"), low=Decimal("101"), close=Decimal("101")),
                ]
            )
            return SimpleNamespace(
                status="fresh",
                degraded_reason="",
                source_used="db_v2",
                bars_returned=2,
                max_gap_s=0,
            )

    ctrl = SimpleNamespace(
        config=SimpleNamespace(connector_name="bitget_perpetual", trading_pair="BTC-USDT", ema_period=20, atr_period=14),
        _price_buffer=PriceBuffer(),
        _history_provider=_FakeProvider(),
        _history_seed_attempted=False,
        _history_seed_status="disabled",
        _history_seed_reason="",
        _history_seed_source="",
        _history_seed_bars=0,
        _history_seed_latency_ms=0.0,
        _history_seed_enabled=lambda: True,
        _get_history_provider=lambda: ctrl._history_provider,
        _required_seed_bars=lambda: 2,
        _history_seed_policy=lambda: EppV24Controller._history_seed_policy(ctrl),
    )

    EppV24Controller._maybe_seed_price_buffer(ctrl, 180.0)

    assert ctrl._history_seed_attempted is True
    assert ctrl._history_seed_status == "fresh"
    assert ctrl._history_seed_source == "db_v2"
    assert ctrl._history_seed_bars == 2
    assert len(ctrl._price_buffer.bars) == 2


def test_maybe_seed_price_buffer_respects_policy_source_fallback(monkeypatch) -> None:
    monkeypatch.setenv("HB_HISTORY_SOURCE_PRIORITY", "quote_mid,exchange_ohlcv")
    monkeypatch.setenv("HB_HISTORY_ALLOW_FALLBACK", "true")
    monkeypatch.setenv("HB_HISTORY_RUNTIME_MIN_STATUS", "degraded")
    monkeypatch.setenv("HB_HISTORY_RUNTIME_MIN_BARS", "2")
    monkeypatch.setenv("HB_HISTORY_MAX_ACCEPTABLE_GAP_S", "300")

    class _FakeProvider:
        def seed_price_buffer(self, buffer, key, bars_needed, now_ms):
            if key.bar_source == "quote_mid":
                buffer.seed_bars(
                    [
                        MinuteBar(ts_minute=60, open=Decimal("100"), high=Decimal("100"), low=Decimal("100"), close=Decimal("100")),
                    ]
                )
                return SimpleNamespace(
                    status="gapped",
                    degraded_reason="gap",
                    source_used="db_v2",
                    bars_returned=1,
                    max_gap_s=600,
                )
            buffer.seed_bars(
                [
                    MinuteBar(ts_minute=60, open=Decimal("100"), high=Decimal("100"), low=Decimal("100"), close=Decimal("100")),
                    MinuteBar(ts_minute=120, open=Decimal("101"), high=Decimal("101"), low=Decimal("101"), close=Decimal("101")),
                ]
            )
            return SimpleNamespace(
                status="fresh",
                degraded_reason="",
                source_used="rest_backfill",
                bars_returned=2,
                max_gap_s=0,
            )

    ctrl = SimpleNamespace(
        config=SimpleNamespace(connector_name="bitget_perpetual", trading_pair="BTC-USDT", ema_period=20, atr_period=14),
        _price_buffer=PriceBuffer(),
        _history_provider=_FakeProvider(),
        _history_seed_attempted=False,
        _history_seed_status="disabled",
        _history_seed_reason="",
        _history_seed_source="",
        _history_seed_bars=0,
        _history_seed_latency_ms=0.0,
        _history_seed_enabled=lambda: True,
        _get_history_provider=lambda: ctrl._history_provider,
        _required_seed_bars=lambda: 2,
        _history_seed_policy=lambda: EppV24Controller._history_seed_policy(ctrl),
    )

    EppV24Controller._maybe_seed_price_buffer(ctrl, 180.0)

    assert ctrl._history_seed_attempted is True
    assert ctrl._history_seed_status == "fresh"
    assert ctrl._history_seed_source == "rest_backfill"
    assert ctrl._history_seed_bars == 2
    assert len(ctrl._price_buffer.bars) == 2


def test_maybe_seed_price_buffer_clears_buffer_when_policy_rejects_all_sources(monkeypatch) -> None:
    monkeypatch.setenv("HB_HISTORY_SOURCE_PRIORITY", "quote_mid,exchange_ohlcv")
    monkeypatch.setenv("HB_HISTORY_ALLOW_FALLBACK", "true")
    monkeypatch.setenv("HB_HISTORY_RUNTIME_MIN_STATUS", "fresh")
    monkeypatch.setenv("HB_HISTORY_RUNTIME_MIN_BARS", "3")
    monkeypatch.setenv("HB_HISTORY_MAX_ACCEPTABLE_GAP_S", "60")

    class _FakeProvider:
        def seed_price_buffer(self, buffer, key, bars_needed, now_ms):
            buffer.seed_bars(
                [
                    MinuteBar(ts_minute=60, open=Decimal("100"), high=Decimal("100"), low=Decimal("100"), close=Decimal("100")),
                    MinuteBar(ts_minute=120, open=Decimal("101"), high=Decimal("101"), low=Decimal("101"), close=Decimal("101")),
                ]
            )
            return SimpleNamespace(
                status="gapped",
                degraded_reason=f"{key.bar_source}_gap",
                source_used=str(key.bar_source),
                bars_returned=2,
                max_gap_s=600,
            )

    ctrl = SimpleNamespace(
        config=SimpleNamespace(connector_name="bitget_perpetual", trading_pair="BTC-USDT", ema_period=20, atr_period=14),
        _price_buffer=PriceBuffer(),
        _history_provider=_FakeProvider(),
        _history_seed_attempted=False,
        _history_seed_status="disabled",
        _history_seed_reason="",
        _history_seed_source="",
        _history_seed_bars=0,
        _history_seed_latency_ms=0.0,
        _history_seed_enabled=lambda: True,
        _get_history_provider=lambda: ctrl._history_provider,
        _required_seed_bars=lambda: 3,
        _history_seed_policy=lambda: EppV24Controller._history_seed_policy(ctrl),
    )

    EppV24Controller._maybe_seed_price_buffer(ctrl, 180.0)

    assert ctrl._history_seed_status == "gapped"
    assert ctrl._history_seed_source == "exchange_ohlcv"
    assert ctrl._history_seed_reason == "exchange_ohlcv_gap"
    assert len(ctrl._price_buffer.bars) == 0


def test_maybe_seed_price_buffer_handles_provider_exception_without_crash() -> None:
    class _BoomProvider:
        def seed_price_buffer(self, buffer, key, bars_needed, now_ms):
            raise RuntimeError("provider_boom")

    ctrl = SimpleNamespace(
        config=SimpleNamespace(connector_name="bitget_perpetual", trading_pair="BTC-USDT", ema_period=20, atr_period=14),
        _price_buffer=PriceBuffer(),
        _history_provider=_BoomProvider(),
        _history_seed_attempted=False,
        _history_seed_status="disabled",
        _history_seed_reason="",
        _history_seed_source="",
        _history_seed_bars=0,
        _history_seed_latency_ms=0.0,
        _history_seed_enabled=lambda: True,
        _get_history_provider=lambda: ctrl._history_provider,
        _required_seed_bars=lambda: 2,
        _history_seed_policy=lambda: EppV24Controller._history_seed_policy(ctrl),
    )

    EppV24Controller._maybe_seed_price_buffer(ctrl, 180.0)

    assert ctrl._history_seed_attempted is True
    assert ctrl._history_seed_status == "degraded"
    assert "provider_boom" in ctrl._history_seed_reason
    assert len(ctrl._price_buffer.bars) == 0
