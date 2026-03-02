"""Unit tests for EppV24Controller core logic.

Tests cover: _detect_regime, _compute_spread_and_edge, _risk_policy_checks /
_evaluate_all_risk, did_fill_order (fill-edge EWMA, adverse counter), and
_cancel_per_min.

Uses sys.modules patching so the tests run even when hummingbot is not
installed — the controller's hummingbot dependencies are replaced with
lightweight stubs.
"""
from __future__ import annotations

import sys
import types as _types_mod
from datetime import datetime, timezone
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
from controllers.core import MarketConditions, RegimeSpec, SpreadEdgeState  # noqa: E402
from controllers.epp_v2_4 import EppV24Controller, _ZERO, _ONE, _10K  # noqa: E402
from controllers.regime_detector import RegimeDetector  # noqa: E402
from controllers.spread_engine import SpreadEngine  # noqa: E402
from controllers.risk_evaluator import RiskEvaluator  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_SPECS = dict(EppV24Controller.PHASE0_SPECS)


def _make_config(**overrides) -> SimpleNamespace:
    """Minimal config with sane defaults for unit-testing individual methods."""
    defaults = dict(
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
        adverse_fill_spread_multiplier=Decimal("1.3"),
        adverse_fill_count_threshold=20,
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
        startup_position_sync=True,
        is_paper=False,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


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
    ctrl._risk_loss_metrics = _types_mod.MethodType(
        EppV24Controller._risk_loss_metrics, ctrl,
    )
    ctrl._risk_policy_checks = _types_mod.MethodType(
        EppV24Controller._risk_policy_checks, ctrl,
    )
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

def _make_fill_event(price, amount, trade_type_name="buy"):
    ev = MagicMock()
    ev.price = price
    ev.amount = amount
    ev.order_id = "test_order_1"
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
    ctrl.processed_data = {
        "spread_pct": spread_pct,
        "mid": mid,
        "adverse_drift_30s": _ZERO,
    }
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


# ===================================================================
# 2. _compute_spread_and_edge  (6 tests)
# ===================================================================


class TestComputeSpreadAndEdge:
    def test_spread_floor_applied(self):
        """Spread must be at least the fee-based floor."""
        ctrl = _make_spread_ctrl(band_pct=_ZERO)
        se = _compute_se(ctrl)
        assert se.spread_pct >= ctrl._spread_floor_pct

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
        return SimpleNamespace(
            config=SimpleNamespace(
                derisk_force_taker_after_s=60.0,
                derisk_progress_reset_ratio=Decimal("0.05"),
            ),
            _position_base=Decimal("-1"),
            _derisk_cycle_started_ts=0.0,
            _derisk_cycle_start_abs_base=_ZERO,
            _derisk_force_taker=False,
            _recently_issued_levels={"buy_0": 1.0},
            _enqueue_force_derisk_executor_cancels=lambda: None,
        )

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

    def test_force_mode_skips_level_creation(self):
        ctrl = SimpleNamespace(_derisk_force_taker=True)
        assert EppV24Controller.get_levels_to_execute(ctrl) == []

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
        action = EppV24Controller.check_position_rebalance(ctrl)
        assert action is not None
        assert action["amount"] == Decimal("0.003")


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
        now_ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc).timestamp()
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
        now_ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc).timestamp()
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
        now_ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc).timestamp()
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
        now_ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc).timestamp()
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


# ===================================================================
# 16. Paper equity/state reconciliation (2 tests)
# ===================================================================


class TestPaperEquityStateReconciliation:
    def test_compute_equity_prefers_paper_portfolio_equity_for_perp_risk(self):
        ctrl = SimpleNamespace()
        ctrl.config = _make_config(
            is_paper=True,
            paper_use_portfolio_equity_for_risk=True,
        )
        ctrl._is_perp = True
        ctrl._position_base = Decimal("0.002")
        ctrl._get_balances = lambda: (Decimal("0.002"), Decimal("200"))
        ctrl._paper_portfolio_snapshot = lambda mid: {
            "position_base": Decimal("0.002"),
            "equity_quote": Decimal("500"),
        }
        ctrl._refresh_margin_ratio = lambda mid, pos_base, quote_bal: None

        equity, base_pct_gross, base_pct_net = EppV24Controller._compute_equity_and_base_pcts(
            ctrl, Decimal("60000")
        )

        assert equity == Decimal("500")
        assert abs(base_pct_gross - Decimal("0.24")) < Decimal("0.000001")
        assert abs(base_pct_net - Decimal("0.24")) < Decimal("0.000001")

    def test_sync_from_paper_desk_reconciles_realized_state_and_persists(self):
        ctrl = SimpleNamespace()
        ctrl.config = _make_config(
            is_paper=True,
            paper_state_reconcile_enabled=True,
            paper_state_reconcile_realized_pnl_diff_quote=Decimal("5"),
        )
        ctrl.market_data_provider = SimpleNamespace(time=lambda: 1_700_000_000.0)
        ctrl._paper_state_reconcile_last_ts = 0.0
        ctrl._paper_state_reconcile_log_cooldown_s = 1.0
        ctrl._controller_start_ts = 0.0
        ctrl._paper_daily_baseline_reset_done = True
        ctrl._daily_equity_open = Decimal("500")
        ctrl._daily_equity_peak = None
        ctrl._realized_pnl_today = Decimal("-250")
        ctrl._position_base = _ZERO
        ctrl._avg_entry_price = _ZERO
        ctrl._save_daily_state = MagicMock()

        pos = SimpleNamespace(
            quantity=Decimal("0.001"),
            avg_entry_price=Decimal("65000"),
            unrealized_pnl=Decimal("1"),
            realized_pnl=Decimal("8"),
        )
        portfolio = SimpleNamespace(
            daily_open_equity=Decimal("500"),
            get_position=lambda _iid: pos,
            equity_quote=lambda _marks, quote_asset="USDT": Decimal("510"),
        )
        connector = SimpleNamespace(
            _paper_desk_v2=SimpleNamespace(portfolio=portfolio),
            _paper_desk_v2_instrument_id=SimpleNamespace(
                key="bitget:BTC-USDT:perp",
                quote_asset="USDT",
            ),
        )
        ctrl._connector = lambda: connector
        ctrl._paper_portfolio_snapshot = _types_mod.MethodType(
            EppV24Controller._paper_portfolio_snapshot, ctrl
        )

        EppV24Controller._sync_from_paper_desk_v2(ctrl, mid=Decimal("65000"), equity_quote=Decimal("200"))

        # realized = (equity - open_equity) - unrealized = (510 - 500) - 1 = 9
        assert ctrl._realized_pnl_today == Decimal("9")
        assert ctrl._position_base == Decimal("0.001")
        assert ctrl._avg_entry_price == Decimal("65000")
        ctrl._save_daily_state.assert_called_once_with(force=True)

    def test_sync_from_paper_desk_can_reset_startup_daily_baseline_when_inherited_loss_is_large(self):
        now_ts = 1_700_000_000.0
        ctrl = SimpleNamespace()
        ctrl.config = _make_config(
            is_paper=True,
            paper_state_reconcile_enabled=True,
            paper_state_reconcile_realized_pnl_diff_quote=Decimal("5"),
            paper_daily_baseline_auto_reset_on_startup=True,
            paper_daily_baseline_reset_loss_pct_threshold=Decimal("0.25"),
            paper_daily_baseline_reset_startup_window_s=300,
        )
        ctrl.market_data_provider = SimpleNamespace(time=lambda: now_ts)
        ctrl._controller_start_ts = now_ts - 5.0
        ctrl._paper_daily_baseline_reset_done = False
        ctrl._paper_state_reconcile_last_ts = 0.0
        ctrl._paper_state_reconcile_log_cooldown_s = 1.0
        ctrl._daily_equity_open = Decimal("500")
        ctrl._daily_equity_peak = Decimal("520")
        ctrl._realized_pnl_today = Decimal("-120")
        ctrl._position_base = _ZERO
        ctrl._avg_entry_price = _ZERO
        ctrl._traded_notional_today = Decimal("200")
        ctrl._fills_count_today = 9
        ctrl._fees_paid_today_quote = Decimal("3")
        ctrl._funding_cost_today_quote = Decimal("1")
        ctrl._save_daily_state = MagicMock()

        pos = SimpleNamespace(
            quantity=Decimal("-0.002"),
            avg_entry_price=Decimal("65000"),
            unrealized_pnl=Decimal("0"),
            realized_pnl=Decimal("12"),
        )
        portfolio = SimpleNamespace(
            daily_open_equity=Decimal("500"),
            get_position=lambda _iid: pos,
            equity_quote=lambda _marks, quote_asset="USDT": Decimal("200"),
        )
        connector = SimpleNamespace(
            _paper_desk_v2=SimpleNamespace(portfolio=portfolio),
            _paper_desk_v2_instrument_id=SimpleNamespace(
                key="bitget:BTC-USDT:perp",
                quote_asset="USDT",
            ),
        )
        ctrl._connector = lambda: connector
        ctrl._paper_portfolio_snapshot = _types_mod.MethodType(
            EppV24Controller._paper_portfolio_snapshot, ctrl
        )

        EppV24Controller._sync_from_paper_desk_v2(ctrl, mid=Decimal("65000"), equity_quote=Decimal("200"))

        assert ctrl._paper_daily_baseline_reset_done is True
        assert ctrl._daily_equity_open == Decimal("200")
        assert ctrl._traded_notional_today == Decimal("0")
        assert ctrl._fills_count_today == 0
        assert ctrl._fees_paid_today_quote == Decimal("0")
        assert ctrl._funding_cost_today_quote == Decimal("0")
        assert ctrl._save_daily_state.call_count >= 1
