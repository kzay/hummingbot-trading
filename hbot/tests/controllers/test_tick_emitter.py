from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from controllers.core import MarketConditions, QuoteGeometry, SpreadEdgeState
from controllers.ops_guard import GuardState
from controllers.tick_emitter import TickEmitter

try:
    import orjson as _orjson
except ImportError:
    _orjson = None  # type: ignore[assignment]


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
        "order_book_stale": False,
        "connector_status": "ok",
        "ob_imbalance": Decimal("0"),
        "kelly_size_active": False,
        "kelly_order_quote": Decimal("0"),
        "ml_regime_override": "",
        "adverse_skip_count": 0,
        "pnl_governor_active": False,
        "pnl_governor_day_progress": Decimal("0"),
        "pnl_governor_target_pnl_pct": Decimal("0"),
        "pnl_governor_target_pnl_quote": Decimal("0"),
        "pnl_governor_expected_pnl_quote": Decimal("0"),
        "pnl_governor_actual_pnl_quote": Decimal("0"),
        "pnl_governor_deficit_ratio": Decimal("0"),
        "pnl_governor_edge_relax_bps": Decimal("0"),
        "pnl_governor_size_mult": Decimal("1"),
        "pnl_governor_size_boost_active": False,
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
        quote_geometry=QuoteGeometry(
            base_spread_pct=Decimal("0.002"),
            spread_floor_pct=Decimal("0.001"),
            reservation_price_adjustment_pct=Decimal("0"),
            inventory_urgency=Decimal("0"),
            inventory_skew=Decimal("0"),
            alpha_skew=Decimal("0"),
        ),
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
    assert out["pnl_governor_target_mode"] == "disabled"
    assert out["pnl_governor_size_mult_applied"] == Decimal("1")
    assert out["spread_competitiveness_cap_active"] is False


def test_log_minute_returns_row_once_per_minute():
    csv_logger = MagicMock()
    emitter = TickEmitter(csv_logger=csv_logger)
    snapshot = _snapshot_defaults()
    snapshot.update(
        {
            "variant": "a",
            "bot_mode": "paper",
            "is_paper": True,
            "connector_name": "bitget_perpetual",
            "trading_pair": "BTC-USDT",
            "cancel_per_min": 0,
            "orders_active": 0,
            "tick_duration_ms": 0.0,
        }
    )
    pd = {
        "regime": "neutral_low_vol",
        "mid": Decimal("100"),
        "equity_quote": Decimal("1000"),
        "base_pct": Decimal("0"),
        "target_base_pct": Decimal("0"),
        "net_base_pct": Decimal("0"),
        "target_net_base_pct": Decimal("0"),
        "spread_pct": Decimal("0.001"),
        "spread_floor_pct": Decimal("0.001"),
        "base_spread_pct": Decimal("0.001"),
        "net_edge_pct": Decimal("0.0002"),
        "net_edge_gate_pct": Decimal("0.0002"),
        "net_edge_ewma_pct": Decimal("0.0002"),
        "turnover_x": Decimal("0"),
        "daily_loss_pct": Decimal("0"),
        "drawdown_pct": Decimal("0"),
        "edge_pause_threshold_pct": Decimal("0.0001"),
        "edge_resume_threshold_pct": Decimal("0.00015"),
        "projected_total_quote": Decimal("0"),
    }

    row = emitter.log_minute(
        now_ts=120.0,
        event_ts="2026-03-08T04:02:00+00:00",
        pd=pd,
        state=GuardState.RUNNING,
        risk_reasons=[],
        snapshot=snapshot,
    )
    skipped = emitter.log_minute(
        now_ts=121.0,
        event_ts="2026-03-08T04:02:01+00:00",
        pd=pd,
        state=GuardState.RUNNING,
        risk_reasons=[],
        snapshot=snapshot,
    )

    assert row is not None
    assert row["projected_total_quote"] == "0"
    assert row["history_seed_status"] == "disabled"
    assert row["history_seed_bars"] == "0"
    assert skipped is None
    emitter.stop()
    csv_logger.log_minute.assert_called_once()


# ------------------------------------------------------------------
# orjson Decimal serialization round-trip
# ------------------------------------------------------------------

@pytest.mark.skipif(_orjson is None, reason="orjson not installed")
def test_orjson_decimal_roundtrip():
    """Verify that orjson with default=str produces content-identical output for Decimal values."""
    payload = {
        "price": Decimal("50123.45"),
        "qty": Decimal("0.001"),
        "zero": Decimal("0"),
        "negative": Decimal("-12.5"),
        "nested": {"rate": Decimal("0.0003")},
    }
    orjson_result = _orjson.dumps(payload, default=str).decode()
    stdlib_result = json.dumps(payload, default=str)
    assert json.loads(orjson_result) == json.loads(stdlib_result)


@pytest.mark.skipif(_orjson is None, reason="orjson not installed")
def test_orjson_opt_non_str_keys():
    """Ensure OPT_NON_STR_KEYS handles integer dict keys without error."""
    payload = {1: "one", 2: "two", "str_key": Decimal("99.9")}
    result = _orjson.dumps(payload, default=str, option=_orjson.OPT_NON_STR_KEYS).decode()
    parsed = json.loads(result)
    assert parsed["1"] == "one"
    assert parsed["str_key"] == "99.9"
