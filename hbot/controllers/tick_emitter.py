"""Tick output construction and minute-level CSV logging for EPP v2.4.

Extracted from ``EppV24Controller`` to isolate output formatting and
persistence from trading logic.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from controllers.core import MarketConditions, SpreadEdgeState
from controllers.ops_guard import GuardState
from controllers.types import ProcessedState

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")
_ONE = Decimal("1")
_10K = Decimal("10000")


class TickEmitter:
    """Builds ``ProcessedState`` dicts and writes minute-level CSV rows."""

    def __init__(self, csv_logger: Any):
        self._csv = csv_logger
        self._last_minute_key: Optional[int] = None
        self._missing_snapshot_keys_warned: set[str] = set()

    def _snapshot_get(self, snapshot: Dict[str, Any], key: str, default: Any) -> Any:
        if key in snapshot:
            return snapshot[key]
        if key not in self._missing_snapshot_keys_warned:
            logger.warning("TickEmitter: snapshot missing key '%s'; using default=%s", key, default)
            self._missing_snapshot_keys_warned.add(key)
        return default

    # ------------------------------------------------------------------
    # ProcessedState construction
    # ------------------------------------------------------------------

    def build_tick_output(
        self,
        mid: Decimal,
        regime_name: str,
        target_base_pct: Decimal,
        base_pct: Decimal,
        state: GuardState,
        spread_state: SpreadEdgeState,
        market: MarketConditions,
        equity_quote: Decimal,
        base_bal: Decimal,
        quote_bal: Decimal,
        risk_hard_stop: bool,
        risk_reasons: List[str],
        daily_loss_pct: Decimal,
        drawdown_pct: Decimal,
        projected_total_quote: Decimal,
        snapshot: Dict[str, Any],
    ) -> ProcessedState:
        """Build the ``ProcessedState`` dict from tick data and a controller snapshot."""
        from controllers.types import PROCESSED_STATE_SCHEMA_VERSION

        adaptive_effective_min_edge_pct = self._snapshot_get(snapshot, "adaptive_effective_min_edge_pct", _ZERO)
        adaptive_fill_age_s = self._snapshot_get(snapshot, "adaptive_fill_age_s", _ZERO)
        adaptive_market_spread_bps_ewma = self._snapshot_get(snapshot, "adaptive_market_spread_bps_ewma", _ZERO)
        adaptive_band_pct_ewma = self._snapshot_get(snapshot, "adaptive_band_pct_ewma", _ZERO)
        adaptive_market_floor_pct = self._snapshot_get(snapshot, "adaptive_market_floor_pct", _ZERO)
        adaptive_vol_ratio = self._snapshot_get(snapshot, "adaptive_vol_ratio", _ZERO)

        return {
            "schema_version": PROCESSED_STATE_SCHEMA_VERSION,
            "reference_price": mid,
            "spread_multiplier": snapshot["spread_multiplier"],
            "regime": regime_name,
            "target_base_pct": target_base_pct,
            "base_pct": base_pct,
            "state": state.value,
            "spread_pct": spread_state.spread_pct,
            "spread_floor_pct": snapshot["spread_floor_pct"],
            "net_edge_pct": spread_state.net_edge,
            "turnover_x": spread_state.turnover_x,
            "adaptive_effective_min_edge_pct": adaptive_effective_min_edge_pct,
            "adaptive_fill_age_s": adaptive_fill_age_s,
            "adaptive_market_spread_bps_ewma": adaptive_market_spread_bps_ewma,
            "adaptive_band_pct_ewma": adaptive_band_pct_ewma,
            "adaptive_market_floor_pct": adaptive_market_floor_pct,
            "adaptive_vol_ratio": adaptive_vol_ratio,
            "skew": spread_state.skew,
            "adverse_drift_30s": spread_state.adverse_drift,
            "adverse_drift_smooth_30s": spread_state.smooth_drift,
            "drift_spread_mult": spread_state.drift_spread_mult,
            "market_spread_pct": market.market_spread_pct,
            "market_spread_bps": market.market_spread_pct * _10K,
            "best_bid_price": market.bid_p,
            "best_ask_price": market.ask_p,
            "best_bid_size": market.best_bid_size,
            "best_ask_size": market.best_ask_size,
            "equity_quote": equity_quote,
            "mid": mid,
            "base_balance": base_bal,
            "quote_balance": quote_bal,
            "soft_pause_edge": snapshot["soft_pause_edge"],
            "edge_gate_blocked": snapshot["edge_gate_blocked"],
            "edge_pause_threshold_pct": spread_state.min_edge_threshold,
            "edge_resume_threshold_pct": spread_state.edge_resume_threshold,
            "risk_hard_stop": risk_hard_stop,
            "risk_reasons": "|".join(risk_reasons),
            "daily_loss_pct": daily_loss_pct,
            "drawdown_pct": drawdown_pct,
            "projected_total_quote": projected_total_quote,
            "fills_count_today": snapshot["fills_count_today"],
            "fees_paid_today_quote": snapshot["fees_paid_today_quote"],
            "paper_fill_count": snapshot["paper_fill_count"],
            "paper_reject_count": snapshot["paper_reject_count"],
            "paper_avg_queue_delay_ms": snapshot["paper_avg_queue_delay_ms"],
            "spread_capture_est_quote": snapshot["traded_notional_today"] * spread_state.spread_pct * spread_state.fill_factor,
            "pnl_quote": equity_quote - (snapshot["daily_equity_open"] or equity_quote),
            "external_soft_pause": snapshot["external_soft_pause"],
            "external_pause_reason": snapshot["external_pause_reason"],
            "external_model_version": snapshot["external_model_version"],
            "external_intent_reason": snapshot["external_intent_reason"],
            "fee_source": snapshot["fee_source"],
            "maker_fee_pct": snapshot["maker_fee_pct"],
            "taker_fee_pct": snapshot["taker_fee_pct"],
            "balance_read_failed": snapshot["balance_read_failed"],
            "funding_rate": snapshot["funding_rate"],
            "funding_cost_today_quote": snapshot["funding_cost_today_quote"],
            "net_realized_pnl_today_quote": snapshot["net_realized_pnl_today"],
            "margin_ratio": snapshot["margin_ratio"],
            "regime_source": snapshot["regime_source"],
            "is_perpetual": snapshot["is_perp"],
            "realized_pnl_today_quote": snapshot["realized_pnl_today"],
            "avg_entry_price": snapshot["avg_entry_price"],
            "position_base": snapshot["position_base"],
            "position_drift_pct": snapshot["position_drift_pct"],
            "fill_edge_ewma_bps": snapshot["fill_edge_ewma"] if snapshot["fill_edge_ewma"] is not None else _ZERO,
            "adverse_fill_active": snapshot["adverse_fill_active"],
            "order_book_stale": market.order_book_stale,
            "ws_reconnect_count": snapshot["ws_reconnect_count"],
            "connector_status": snapshot["connector_status"],
            "ob_imbalance": snapshot["ob_imbalance"],
            "kelly_size_active": snapshot["kelly_size_active"],
            "kelly_order_quote": snapshot["kelly_order_quote"],
            "ml_regime_override": snapshot["ml_regime_override"],
            "adverse_skip_count": snapshot["adverse_skip_count"],
            "_tick_duration_ms": 0.0,
            "_indicator_duration_ms": snapshot["indicator_duration_ms"],
            "_connector_io_duration_ms": snapshot["connector_io_duration_ms"],
        }

    # ------------------------------------------------------------------
    # Minute-level CSV logging
    # ------------------------------------------------------------------

    def log_minute(
        self,
        now_ts: float,
        event_ts: str,
        pd: Dict[str, Any],
        state: GuardState,
        risk_reasons: List[str],
        snapshot: Dict[str, Any],
    ) -> None:
        """Write one row to ``minute.csv`` per calendar minute."""
        minute_key = int(now_ts // 60)
        if self._last_minute_key == minute_key:
            return
        self._last_minute_key = minute_key

        mkt_spread = pd.get("market_spread_pct", _ZERO)
        self._csv.log_minute(
            {
                "bot_variant": snapshot["variant"],
                "bot_mode": snapshot["bot_mode"],
                "accounting_source": "paper_desk_v2" if snapshot["is_paper"] else "live_connector",
                "exchange": snapshot["connector_name"],
                "trading_pair": snapshot["trading_pair"],
                "state": state.value,
                "regime": pd.get("regime", ""),
                "regime_source": pd.get("regime_source", "price_buffer"),
                "mid": str(pd.get("mid", _ZERO)),
                "equity_quote": str(pd.get("equity_quote", _ZERO)),
                "base_pct": str(pd.get("base_pct", _ZERO)),
                "target_base_pct": str(pd.get("target_base_pct", _ZERO)),
                "net_base_pct": str(pd.get("net_base_pct", _ZERO)),
                "target_net_base_pct": str(pd.get("target_net_base_pct", _ZERO)),
                "spread_pct": str(pd.get("spread_pct", _ZERO)),
                "spread_floor_pct": str(pd.get("spread_floor_pct", _ZERO)),
                "net_edge_pct": str(pd.get("net_edge_pct", _ZERO)),
                "net_edge_gate_pct": str(pd.get("net_edge_gate_pct", _ZERO)),
                "net_edge_ewma_pct": str(pd.get("net_edge_ewma_pct", _ZERO)),
                "adaptive_effective_min_edge_pct": str(pd.get("adaptive_effective_min_edge_pct", _ZERO)),
                "adaptive_fill_age_s": str(pd.get("adaptive_fill_age_s", _ZERO)),
                "adaptive_market_spread_bps_ewma": str(pd.get("adaptive_market_spread_bps_ewma", _ZERO)),
                "adaptive_band_pct_ewma": str(pd.get("adaptive_band_pct_ewma", _ZERO)),
                "adaptive_market_floor_pct": str(pd.get("adaptive_market_floor_pct", _ZERO)),
                "adaptive_vol_ratio": str(pd.get("adaptive_vol_ratio", _ZERO)),
                "skew": str(pd.get("skew", _ZERO)),
                "adverse_drift_30s": str(pd.get("adverse_drift_30s", _ZERO)),
                "adverse_drift_smooth_30s": str(pd.get("adverse_drift_smooth_30s", _ZERO)),
                "drift_spread_mult": str(pd.get("drift_spread_mult", _ZERO)),
                "soft_pause_edge": str(pd.get("soft_pause_edge", False)),
                "base_balance": str(pd.get("base_balance", _ZERO)),
                "quote_balance": str(pd.get("quote_balance", _ZERO)),
                "market_spread_pct": str(mkt_spread),
                "market_spread_bps": str(pd.get("market_spread_bps", _ZERO)),
                "best_bid_price": str(pd.get("best_bid_price", _ZERO)),
                "best_ask_price": str(pd.get("best_ask_price", _ZERO)),
                "best_bid_size": str(pd.get("best_bid_size", _ZERO)),
                "best_ask_size": str(pd.get("best_ask_size", _ZERO)),
                "turnover_today_x": str(pd.get("turnover_x", _ZERO)),
                "cancel_per_min": snapshot["cancel_per_min"],
                "orders_active": snapshot["orders_active"],
                "fills_count_today": snapshot["fills_count_today"],
                "fees_paid_today_quote": str(snapshot["fees_paid_today_quote"]),
                "daily_loss_pct": str(pd.get("daily_loss_pct", _ZERO)),
                "drawdown_pct": str(pd.get("drawdown_pct", _ZERO)),
                "risk_reasons": "|".join(risk_reasons),
                "fee_source": snapshot["fee_source"],
                "maker_fee_pct": str(snapshot["maker_fee_pct"]),
                "taker_fee_pct": str(snapshot["taker_fee_pct"]),
                "realized_pnl_today_quote": str(snapshot["realized_pnl_today"]),
                "net_realized_pnl_today_quote": str(snapshot["net_realized_pnl_today"]),
                "position_base": str(snapshot["position_base"]),
                "avg_entry_price": str(snapshot["avg_entry_price"]),
                "fill_edge_ewma_bps": str(snapshot["fill_edge_ewma"] if snapshot["fill_edge_ewma"] is not None else _ZERO),
                "adverse_fill_active": str(snapshot["adverse_fill_active"]),
                "funding_rate": str(snapshot["funding_rate"]),
                "funding_rate_bps": str(snapshot["funding_rate"] * _10K),
                "funding_cost_today_quote": str(snapshot["funding_cost_today_quote"]),
                "margin_ratio": str(snapshot["margin_ratio"]),
                "position_drift_pct": str(snapshot["position_drift_pct"]),
                "ws_reconnect_count": str(snapshot["ws_reconnect_count"]),
                "order_book_stale": str(snapshot["order_book_stale"]),
                "_tick_duration_ms": str(snapshot["tick_duration_ms"]),
                "_indicator_duration_ms": str(snapshot["indicator_duration_ms"]),
                "_connector_io_duration_ms": str(snapshot["connector_io_duration_ms"]),
            },
            ts=event_ts,
        )
