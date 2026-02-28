from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

from controllers.core import MarketConditions, SpreadEdgeState
from controllers.ops_guard import GuardState
from controllers.tick_emitter import TickEmitter


def _snapshot_defaults() -> dict:
    return {
        "spread_multiplier": Decimal("1"),
        "spread_floor_pct": Decimal("0.001"),
        "soft_pause_edge": False,
        "edge_gate_blocked": False,
        "fills_count_today": 0,
        "fees_paid_today_quote": Decimal("0"),
        "paper_fill_count": 0,
        "paper_reject_count": 0,
        "paper_avg_queue_delay_ms": Decimal("0"),
        "traded_notional_today": Decimal("0"),
        "daily_equity_open": Decimal("1000"),
        "external_soft_pause": False,
        "external_pause_reason": "",
        "external_model_version": "",
        "external_intent_reason": "",
        "fee_source": "manual",
        "maker_fee_pct": Decimal("0.001"),
        "taker_fee_pct": Decimal("0.001"),
        "balance_read_failed": False,
        "funding_rate": Decimal("0"),
        "funding_cost_today_quote": Decimal("0"),
        "net_realized_pnl_today": Decimal("0"),
        "margin_ratio": Decimal("1"),
        "regime_source": "price_buffer",
        "is_perp": False,
        "realized_pnl_today": Decimal("0"),
        "avg_entry_price": Decimal("0"),
        "position_base": Decimal("0"),
        "position_drift_pct": Decimal("0"),
        "fill_edge_ewma": None,
        "adverse_fill_active": False,
        "ws_reconnect_count": 0,
        "connector_status": "ok",
        "ob_imbalance": Decimal("0"),
        "kelly_size_active": False,
        "kelly_order_quote": Decimal("0"),
        "ml_regime_override": "",
        "adverse_skip_count": 0,
        "indicator_duration_ms": 0.0,
        "connector_io_duration_ms": 0.0,
    }


def test_build_tick_output_defaults_missing_adaptive_keys():
    emitter = TickEmitter(csv_logger=MagicMock())
    snapshot = _snapshot_defaults()
    spread_state = SpreadEdgeState(
        band_pct=Decimal("0.001"),
        spread_pct=Decimal("0.002"),
        net_edge=Decimal("0.0005"),
        skew=Decimal("0"),
        adverse_drift=Decimal("0"),
        smooth_drift=Decimal("0"),
        drift_spread_mult=Decimal("1"),
        turnover_x=Decimal("0"),
        min_edge_threshold=Decimal("0.0001"),
        edge_resume_threshold=Decimal("0.0002"),
        fill_factor=Decimal("0.4"),
    )
    market = MarketConditions(
        is_high_vol=False,
        bid_p=Decimal("100"),
        ask_p=Decimal("101"),
        market_spread_pct=Decimal("0.01"),
        best_bid_size=Decimal("1"),
        best_ask_size=Decimal("1"),
        connector_ready=True,
        order_book_stale=False,
        market_spread_too_small=False,
        side_spread_floor=Decimal("0"),
    )

    out = emitter.build_tick_output(
        mid=Decimal("100.5"),
        regime_name="neutral_low_vol",
        target_base_pct=Decimal("0.5"),
        base_pct=Decimal("0.5"),
        state=GuardState.RUNNING,
        spread_state=spread_state,
        market=market,
        equity_quote=Decimal("1000"),
        base_bal=Decimal("0"),
        quote_bal=Decimal("1000"),
        risk_hard_stop=False,
        risk_reasons=[],
        daily_loss_pct=Decimal("0"),
        drawdown_pct=Decimal("0"),
        projected_total_quote=Decimal("1000"),
        snapshot=snapshot,
    )
    assert out["adaptive_effective_min_edge_pct"] == Decimal("0")
    assert out["adaptive_fill_age_s"] == Decimal("0")
    assert out["adaptive_market_floor_pct"] == Decimal("0")
