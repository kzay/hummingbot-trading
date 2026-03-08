"""Tick output construction and minute-level CSV logging for EPP v2.4.

Extracted from ``EppV24Controller`` to isolate output formatting and
persistence from trading logic.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from controllers.runtime.market_making_types import MarketConditions, SpreadEdgeState
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
            "base_spread_pct": self._snapshot_get(snapshot, "base_spread_pct", _ZERO),
            "net_edge_pct": spread_state.net_edge,
            "turnover_x": spread_state.turnover_x,
            "adaptive_effective_min_edge_pct": adaptive_effective_min_edge_pct,
            "adaptive_fill_age_s": adaptive_fill_age_s,
            "adaptive_market_spread_bps_ewma": adaptive_market_spread_bps_ewma,
            "adaptive_band_pct_ewma": adaptive_band_pct_ewma,
            "adaptive_market_floor_pct": adaptive_market_floor_pct,
            "adaptive_vol_ratio": adaptive_vol_ratio,
            "pnl_governor_active": snapshot["pnl_governor_active"],
            "pnl_governor_day_progress": snapshot["pnl_governor_day_progress"],
            "pnl_governor_target_pnl_pct": self._snapshot_get(snapshot, "pnl_governor_target_pnl_pct", _ZERO),
            "pnl_governor_target_pnl_quote": snapshot["pnl_governor_target_pnl_quote"],
            "pnl_governor_expected_pnl_quote": snapshot["pnl_governor_expected_pnl_quote"],
            "pnl_governor_actual_pnl_quote": snapshot["pnl_governor_actual_pnl_quote"],
            "pnl_governor_deficit_ratio": snapshot["pnl_governor_deficit_ratio"],
            "pnl_governor_edge_relax_bps": snapshot["pnl_governor_edge_relax_bps"],
            "pnl_governor_size_mult": self._snapshot_get(snapshot, "pnl_governor_size_mult", _ONE),
            "pnl_governor_size_boost_active": self._snapshot_get(snapshot, "pnl_governor_size_boost_active", False),
            "pnl_governor_target_mode": self._snapshot_get(snapshot, "pnl_governor_target_mode", "disabled"),
            "pnl_governor_target_source": self._snapshot_get(snapshot, "pnl_governor_target_source", "none"),
            "pnl_governor_target_equity_open_quote": self._snapshot_get(snapshot, "pnl_governor_target_equity_open_quote", _ZERO),
            "pnl_governor_target_effective_pct": self._snapshot_get(snapshot, "pnl_governor_target_effective_pct", _ZERO),
            "pnl_governor_size_mult_applied": self._snapshot_get(snapshot, "pnl_governor_size_mult_applied", _ONE),
            "pnl_governor_activation_reason": self._snapshot_get(snapshot, "pnl_governor_activation_reason", "unknown"),
            "pnl_governor_size_boost_reason": self._snapshot_get(snapshot, "pnl_governor_size_boost_reason", "unknown"),
            "pnl_governor_activation_reason_counts": self._snapshot_get(
                snapshot, "pnl_governor_activation_reason_counts", "{}"
            ),
            "pnl_governor_size_boost_reason_counts": self._snapshot_get(
                snapshot, "pnl_governor_size_boost_reason_counts", "{}"
            ),
            "skew": spread_state.skew,
            "reservation_price_adjustment_pct": self._snapshot_get(
                snapshot, "reservation_price_adjustment_pct", _ZERO
            ),
            "inventory_urgency_pct": self._snapshot_get(snapshot, "inventory_urgency_pct", _ZERO),
            "inventory_skew_pct": self._snapshot_get(snapshot, "inventory_skew_pct", _ZERO),
            "alpha_skew_pct": self._snapshot_get(snapshot, "alpha_skew_pct", _ZERO),
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
            "selective_quote_state": self._snapshot_get(snapshot, "selective_quote_state", "inactive"),
            "selective_quote_score": self._snapshot_get(snapshot, "selective_quote_score", _ZERO),
            "selective_quote_reason": self._snapshot_get(snapshot, "selective_quote_reason", "disabled"),
            "selective_quote_adverse_ratio": self._snapshot_get(snapshot, "selective_quote_adverse_ratio", _ZERO),
            "selective_quote_slippage_p95_bps": self._snapshot_get(snapshot, "selective_quote_slippage_p95_bps", _ZERO),
            "alpha_policy_state": self._snapshot_get(snapshot, "alpha_policy_state", "maker_two_sided"),
            "alpha_policy_reason": self._snapshot_get(snapshot, "alpha_policy_reason", "unknown"),
            "alpha_maker_score": self._snapshot_get(snapshot, "alpha_maker_score", _ZERO),
            "alpha_aggressive_score": self._snapshot_get(snapshot, "alpha_aggressive_score", _ZERO),
            "alpha_cross_allowed": self._snapshot_get(snapshot, "alpha_cross_allowed", False),
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
            "avg_entry_price_long": self._snapshot_get(snapshot, "avg_entry_price_long", _ZERO),
            "avg_entry_price_short": self._snapshot_get(snapshot, "avg_entry_price_short", _ZERO),
            "position_base": snapshot["position_base"],
            "position_gross_base": self._snapshot_get(snapshot, "position_gross_base", abs(snapshot["position_base"])),
            "position_long_base": self._snapshot_get(snapshot, "position_long_base", max(_ZERO, snapshot["position_base"])),
            "position_short_base": self._snapshot_get(snapshot, "position_short_base", max(_ZERO, -snapshot["position_base"])),
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
            "spread_competitiveness_cap_active": self._snapshot_get(snapshot, "spread_competitiveness_cap_active", False),
            "spread_competitiveness_cap_side_pct": self._snapshot_get(snapshot, "spread_competitiveness_cap_side_pct", _ZERO),
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
                "base_spread_pct": str(pd.get("base_spread_pct", _ZERO)),
                "net_edge_pct": str(pd.get("net_edge_pct", _ZERO)),
                "net_edge_gate_pct": str(pd.get("net_edge_gate_pct", _ZERO)),
                "net_edge_ewma_pct": str(pd.get("net_edge_ewma_pct", _ZERO)),
                "adaptive_effective_min_edge_pct": str(pd.get("adaptive_effective_min_edge_pct", _ZERO)),
                "adaptive_fill_age_s": str(pd.get("adaptive_fill_age_s", _ZERO)),
                "adaptive_market_spread_bps_ewma": str(pd.get("adaptive_market_spread_bps_ewma", _ZERO)),
                "adaptive_band_pct_ewma": str(pd.get("adaptive_band_pct_ewma", _ZERO)),
                "adaptive_market_floor_pct": str(pd.get("adaptive_market_floor_pct", _ZERO)),
                "adaptive_vol_ratio": str(pd.get("adaptive_vol_ratio", _ZERO)),
                "pnl_governor_active": str(pd.get("pnl_governor_active", False)),
                "pnl_governor_day_progress": str(pd.get("pnl_governor_day_progress", _ZERO)),
                "pnl_governor_target_pnl_pct": str(pd.get("pnl_governor_target_pnl_pct", _ZERO)),
                "pnl_governor_target_pnl_quote": str(pd.get("pnl_governor_target_pnl_quote", _ZERO)),
                "pnl_governor_expected_pnl_quote": str(pd.get("pnl_governor_expected_pnl_quote", _ZERO)),
                "pnl_governor_actual_pnl_quote": str(pd.get("pnl_governor_actual_pnl_quote", _ZERO)),
                "pnl_governor_deficit_ratio": str(pd.get("pnl_governor_deficit_ratio", _ZERO)),
                "pnl_governor_edge_relax_bps": str(pd.get("pnl_governor_edge_relax_bps", _ZERO)),
                "pnl_governor_size_mult": str(pd.get("pnl_governor_size_mult", _ONE)),
                "pnl_governor_size_boost_active": str(pd.get("pnl_governor_size_boost_active", False)),
                "pnl_governor_target_mode": str(pd.get("pnl_governor_target_mode", "disabled")),
                "pnl_governor_target_source": str(pd.get("pnl_governor_target_source", "none")),
                "pnl_governor_target_equity_open_quote": str(pd.get("pnl_governor_target_equity_open_quote", _ZERO)),
                "pnl_governor_target_effective_pct": str(pd.get("pnl_governor_target_effective_pct", _ZERO)),
                "pnl_governor_size_mult_applied": str(pd.get("pnl_governor_size_mult_applied", _ONE)),
                "pnl_governor_activation_reason": str(pd.get("pnl_governor_activation_reason", "unknown")),
                "pnl_governor_size_boost_reason": str(pd.get("pnl_governor_size_boost_reason", "unknown")),
                "pnl_governor_activation_reason_counts": str(pd.get("pnl_governor_activation_reason_counts", "{}")),
                "pnl_governor_size_boost_reason_counts": str(pd.get("pnl_governor_size_boost_reason_counts", "{}")),
                "skew": str(pd.get("skew", _ZERO)),
                "reservation_price_adjustment_pct": str(pd.get("reservation_price_adjustment_pct", _ZERO)),
                "inventory_urgency_pct": str(pd.get("inventory_urgency_pct", _ZERO)),
                "inventory_skew_pct": str(pd.get("inventory_skew_pct", _ZERO)),
                "alpha_skew_pct": str(pd.get("alpha_skew_pct", _ZERO)),
                "adverse_drift_30s": str(pd.get("adverse_drift_30s", _ZERO)),
                "adverse_drift_smooth_30s": str(pd.get("adverse_drift_smooth_30s", _ZERO)),
                "drift_spread_mult": str(pd.get("drift_spread_mult", _ZERO)),
                "soft_pause_edge": str(pd.get("soft_pause_edge", False)),
                "selective_quote_state": str(pd.get("selective_quote_state", "inactive")),
                "selective_quote_score": str(pd.get("selective_quote_score", _ZERO)),
                "selective_quote_reason": str(pd.get("selective_quote_reason", "disabled")),
                "selective_quote_adverse_ratio": str(pd.get("selective_quote_adverse_ratio", _ZERO)),
                "selective_quote_slippage_p95_bps": str(pd.get("selective_quote_slippage_p95_bps", _ZERO)),
                "alpha_policy_state": str(pd.get("alpha_policy_state", "maker_two_sided")),
                "alpha_policy_reason": str(pd.get("alpha_policy_reason", "unknown")),
                "alpha_maker_score": str(pd.get("alpha_maker_score", _ZERO)),
                "alpha_aggressive_score": str(pd.get("alpha_aggressive_score", _ZERO)),
                "alpha_cross_allowed": str(pd.get("alpha_cross_allowed", False)),
                "quote_side_mode": str(pd.get("quote_side_mode", "off")),
                "quote_side_reason": str(pd.get("quote_side_reason", "regime")),
                "base_balance": str(pd.get("base_balance", _ZERO)),
                "quote_balance": str(pd.get("quote_balance", _ZERO)),
                "market_spread_pct": str(mkt_spread),
                "market_spread_bps": str(pd.get("market_spread_bps", _ZERO)),
                "best_bid_price": str(pd.get("best_bid_price", _ZERO)),
                "best_ask_price": str(pd.get("best_ask_price", _ZERO)),
                "best_bid_size": str(pd.get("best_bid_size", _ZERO)),
                "best_ask_size": str(pd.get("best_ask_size", _ZERO)),
                "turnover_today_x": str(pd.get("turnover_x", _ZERO)),
                "projected_total_quote": str(pd.get("projected_total_quote", _ZERO)),
                "cancel_per_min": snapshot["cancel_per_min"],
                "orders_active": snapshot["orders_active"],
                "fills_count_today": snapshot["fills_count_today"],
                "fees_paid_today_quote": str(snapshot["fees_paid_today_quote"]),
                "daily_loss_pct": str(pd.get("daily_loss_pct", _ZERO)),
                "drawdown_pct": str(pd.get("drawdown_pct", _ZERO)),
                "edge_pause_threshold_pct": str(pd.get("edge_pause_threshold_pct", _ZERO)),
                "edge_resume_threshold_pct": str(pd.get("edge_resume_threshold_pct", _ZERO)),
                "risk_reasons": "|".join(risk_reasons),
                "min_base_pct": str(snapshot.get("min_base_pct", _ZERO)),
                "max_base_pct": str(snapshot.get("max_base_pct", _ZERO)),
                "max_total_notional_quote": str(snapshot.get("max_total_notional_quote", _ZERO)),
                "max_daily_turnover_x_hard": str(snapshot.get("max_daily_turnover_x_hard", _ZERO)),
                "max_daily_loss_pct_hard": str(snapshot.get("max_daily_loss_pct_hard", _ZERO)),
                "max_drawdown_pct_hard": str(snapshot.get("max_drawdown_pct_hard", _ZERO)),
                "margin_ratio_soft_pause_pct": str(snapshot.get("margin_ratio_soft_pause_pct", _ZERO)),
                "margin_ratio_hard_stop_pct": str(snapshot.get("margin_ratio_hard_stop_pct", _ZERO)),
                "position_drift_soft_pause_pct": str(snapshot.get("position_drift_soft_pause_pct", _ZERO)),
                "fee_source": snapshot["fee_source"],
                "maker_fee_pct": str(snapshot["maker_fee_pct"]),
                "taker_fee_pct": str(snapshot["taker_fee_pct"]),
                "realized_pnl_today_quote": str(snapshot["realized_pnl_today"]),
                "net_realized_pnl_today_quote": str(snapshot["net_realized_pnl_today"]),
                "position_base": str(snapshot["position_base"]),
                "position_gross_base": str(snapshot.get("position_gross_base", abs(snapshot["position_base"]))),
                "position_long_base": str(snapshot.get("position_long_base", max(_ZERO, snapshot["position_base"]))),
                "position_short_base": str(snapshot.get("position_short_base", max(_ZERO, -snapshot["position_base"]))),
                "avg_entry_price": str(snapshot["avg_entry_price"]),
                "avg_entry_price_long": str(snapshot.get("avg_entry_price_long", _ZERO)),
                "avg_entry_price_short": str(snapshot.get("avg_entry_price_short", _ZERO)),
                "fill_edge_ewma_bps": str(snapshot["fill_edge_ewma"] if snapshot["fill_edge_ewma"] is not None else _ZERO),
                "adverse_fill_active": str(snapshot["adverse_fill_active"]),
                "funding_rate": str(snapshot["funding_rate"]),
                "funding_rate_bps": str(snapshot["funding_rate"] * _10K),
                "funding_cost_today_quote": str(snapshot["funding_cost_today_quote"]),
                "margin_ratio": str(snapshot["margin_ratio"]),
                "position_drift_pct": str(snapshot["position_drift_pct"]),
                "bot6_signal_side": str(pd.get("bot6_signal_side", "off")),
                "bot6_signal_reason": str(pd.get("bot6_signal_reason", "inactive")),
                "bot6_signal_score_long": str(pd.get("bot6_signal_score_long", 0)),
                "bot6_signal_score_short": str(pd.get("bot6_signal_score_short", 0)),
                "bot6_signal_score_active": str(pd.get("bot6_signal_score_active", 0)),
                "bot6_sma_fast": str(pd.get("bot6_sma_fast", _ZERO)),
                "bot6_sma_slow": str(pd.get("bot6_sma_slow", _ZERO)),
                "bot6_adx": str(pd.get("bot6_adx", _ZERO)),
                "bot6_funding_bias": str(pd.get("bot6_funding_bias", "neutral")),
                "bot6_futures_cvd": str(pd.get("bot6_futures_cvd", _ZERO)),
                "bot6_spot_cvd": str(pd.get("bot6_spot_cvd", _ZERO)),
                "bot6_cvd_divergence_ratio": str(pd.get("bot6_cvd_divergence_ratio", _ZERO)),
                "bot6_stacked_buy_count": str(pd.get("bot6_stacked_buy_count", 0)),
                "bot6_stacked_sell_count": str(pd.get("bot6_stacked_sell_count", 0)),
                "bot6_delta_spike_ratio": str(pd.get("bot6_delta_spike_ratio", _ZERO)),
                "bot6_hedge_state": str(pd.get("bot6_hedge_state", "inactive")),
                "bot6_partial_exit_ratio": str(pd.get("bot6_partial_exit_ratio", _ZERO)),
                "ws_reconnect_count": str(snapshot["ws_reconnect_count"]),
                "order_book_stale": str(snapshot["order_book_stale"]),
                "derisk_runtime_recovered": str(pd.get("derisk_runtime_recovered", False)),
                "derisk_runtime_recovery_count": str(pd.get("derisk_runtime_recovery_count", 0)),
                "spread_competitiveness_cap_active": str(pd.get("spread_competitiveness_cap_active", False)),
                "spread_competitiveness_cap_side_pct": str(pd.get("spread_competitiveness_cap_side_pct", _ZERO)),
                "_tick_duration_ms": str(snapshot["tick_duration_ms"]),
                "_indicator_duration_ms": str(snapshot["indicator_duration_ms"]),
                "_connector_io_duration_ms": str(snapshot["connector_io_duration_ms"]),
            },
            ts=event_ts,
        )
