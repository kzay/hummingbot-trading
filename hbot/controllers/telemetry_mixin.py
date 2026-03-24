"""Telemetry emission mixin — extracted from SharedRuntimeKernel.

Contains snapshot building, Redis telemetry publishing, and display formatting.
Used as a mixin: class SharedRuntimeKernel(TelemetryMixin, ...):
"""
from __future__ import annotations

import json
import logging
import math
import os
import time as _time_mod
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from controllers.ops_guard import GuardState
from controllers.runtime.data_context import RuntimeDataContext
from controllers.runtime.execution_context import RuntimeExecutionPlan
from controllers.runtime.risk_context import RuntimeRiskDecision

if TYPE_CHECKING:
    from controllers.runtime.runtime_types import (
        MarketConditions,
        SpreadEdgeState,
    )

from controllers.tick_types import TickSnapshot

try:
    import orjson as _orjson
except ImportError:
    _orjson = None  # type: ignore[assignment]

from datetime import UTC, datetime

from controllers.runtime.core import resolve_runtime_compatibility, runtime_metadata
from platform_lib.core.utils import to_decimal
from platform_lib.contracts.event_identity import validate_event_identity as _validate_event_identity
from platform_lib.contracts.stream_names import BOT_TELEMETRY_STREAM

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")
_ONE = Decimal("1")
_10K = Decimal("10000")
_BALANCE_EPSILON = Decimal("1e-12")
_INVENTORY_DERISK_REASONS = frozenset({"base_pct_above_max", "base_pct_below_min", "eod_close_pending"})


def _config_is_paper_check(config: Any) -> bool:
    explicit = getattr(config, "is_paper", None)
    if explicit is not None:
        return bool(explicit)
    return str(getattr(config, "bot_mode", "")).strip().lower() == "paper"


_SUB_MINUTE_INTERVAL_S = float(os.environ.get("TELEMETRY_SUB_MINUTE_INTERVAL_S", "10"))


def _sanitize_floats(obj: Any, _key: str = "") -> Any:
    """Recursively replace NaN/Inf floats with 0.0 to prevent invalid JSON."""
    if isinstance(obj, float):
        if not math.isfinite(obj):
            logger.warning("Non-finite gauge value substituted with 0.0 (key=%s, value=%s)", _key, obj)
            return 0.0
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize_floats(v, _key=k) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_floats(v, _key=_key) for v in obj]
    return obj


class TelemetryMixin:
    """Mixin providing telemetry emission methods for SharedRuntimeKernel."""

    _last_minute_row: dict[str, Any] | None = None
    _last_sub_minute_publish_ts: float = 0.0

    def _get_telemetry_redis(self) -> Any | None:
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

    def _publish_bot_minute_snapshot_telemetry(self, event_ts: str, minute_row: dict[str, Any] | None) -> None:
        """Publish a compact per-minute runtime snapshot to the shared telemetry stream."""
        if not isinstance(minute_row, dict) or not minute_row:
            self._maybe_publish_sub_minute_snapshot(event_ts)
            return
        self._last_minute_row = dict(minute_row)
        self._last_sub_minute_publish_ts = _time_mod.time()
        try:
            import json as _json_tel
            import uuid as _uuid_mod
            from datetime import datetime as _dt
            from pathlib import Path as _Path

            surface = getattr(self, "_runtime_compat", None)
            if surface is None:
                config = getattr(self, "config", None)
                runtime_impl = type(self).__name__.replace("Controller", "") or "shared_runtime_v24"
                surface = resolve_runtime_compatibility(
                    config,
                    runtime_impl=runtime_impl,
                )
                self._runtime_compat = surface
            runtime_compat = surface

            payload = {
                "event_type": "bot_minute_snapshot",
                "event_version": "v1",
                "schema_version": "1.0",
                "ts_utc": event_ts,
                "producer": f"{runtime_compat.telemetry_producer_prefix}.{self.config.instance_name}",
                "instance_name": self.config.instance_name,
                "controller_id": str(getattr(self, "id", "") or getattr(self.config, "id", "") or self.config.instance_name or ""),
                "connector_name": self.config.connector_name,
                "trading_pair": self.config.trading_pair,
                "strategy_type": getattr(self.config, "strategy_type", "mm"),
                "state": str(minute_row.get("state", "")),
                "regime": str(minute_row.get("regime", "")),
                "mid_price": float(to_decimal(minute_row.get("mid", _ZERO))),
                "equity_quote": float(to_decimal(minute_row.get("equity_quote", _ZERO))),
                "quote_balance": float(to_decimal(minute_row.get("quote_balance", _ZERO))),
                "equity_open": float(getattr(self, "_daily_equity_open", None) or 0),
                "equity_peak": float(getattr(self, "_daily_equity_peak", None) or 0),
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
                "position": {
                    "trading_pair": self.config.trading_pair,
                    "quantity": float(self._position_base),
                    "avg_entry_price": float(self._avg_entry_price),
                    "unrealized_pnl": float(
                        (to_decimal(minute_row.get("mid", _ZERO)) - self._avg_entry_price) * self._position_base
                    ) if self._avg_entry_price > _ZERO and abs(self._position_base) > _BALANCE_EPSILON else 0.0,
                    "side": "long" if self._position_base > _BALANCE_EPSILON else (
                        "short" if self._position_base < -_BALANCE_EPSILON else "flat"
                    ),
                    "realized_pnl_today": float(self._realized_pnl_today),
                    "source_ts_ms": int(_time_mod.time() * 1000),
                },
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

            # ── Bot-specific gate metrics ──────────────────────────────
            bot_gates: dict[str, Any] = {}
            pd = getattr(self, "processed_data", {}) or {}
            for prefix in ("bot1", "bot5", "bot6", "bot7"):
                gate_method = getattr(self, f"_{prefix}_gate_metrics", None)
                if gate_method is not None:
                    try:
                        gate_data = dict(gate_method())
                    except Exception:
                        gate_data = {}
                    _indicator_keys: dict[str, tuple[str, ...]] = {
                        "bot6": ("cvd_divergence_ratio", "adx", "hedge_state", "sma_fast", "sma_slow"),
                        "bot7": ("adx", "rsi", "price_buffer_bars"),
                    }
                    for ind_key in _indicator_keys.get(prefix, ()):
                        val = pd.get(f"{prefix}_{ind_key}")
                        if val is not None:
                            gate_data[ind_key] = str(val)
                    bot_gates[prefix] = gate_data
            payload["bot_gates"] = bot_gates

            payload = _sanitize_floats(payload)
            identity_ok, identity_reason = _validate_event_identity(payload)
            if not identity_ok:
                logger.warning("Minute snapshot telemetry dropped due to identity contract: %s", identity_reason)
                return
            redis_published = False
            try:
                _r = self._get_telemetry_redis()
                if _r is not None:
                    _payload_s = _orjson.dumps(payload).decode() if _orjson is not None else _json_tel.dumps(payload)
                    _r.xadd(BOT_TELEMETRY_STREAM, {"payload": _payload_s}, maxlen=100_000, approximate=True)
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
                out_path = out_dir / f"events_{_dt.now(UTC).strftime('%Y%m%d')}.jsonl"
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
                    "ingest_ts_utc": _dt.now(UTC).isoformat(),
                    "schema_validation_status": "ok",
                }
                with out_path.open("a", encoding="utf-8") as handle:
                    _line = _orjson.dumps(envelope).decode() if _orjson is not None else _json_tel.dumps(envelope, ensure_ascii=True)
                    handle.write(_line + "\n")
        except Exception:
            logger.debug("Minute snapshot telemetry publish failed", exc_info=True)

    def _maybe_publish_sub_minute_snapshot(self, event_ts: str) -> None:
        """Re-publish using cached minute_row at sub-minute intervals for dashboard freshness.

        Overlays live equity/position/PnL from controller state onto the cached
        minute_row so the dashboard sees fresh account data between minute ticks.
        """
        if _SUB_MINUTE_INTERVAL_S <= 0:
            return
        now = _time_mod.time()
        if (now - self._last_sub_minute_publish_ts) < _SUB_MINUTE_INTERVAL_S:
            return
        cached = self._last_minute_row
        if not cached:
            return
        self._last_sub_minute_publish_ts = now
        refreshed = dict(cached)
        refreshed["equity_quote"] = getattr(self, "_last_equity_quote", cached.get("equity_quote", _ZERO))
        refreshed["quote_balance"] = getattr(self, "_last_quote_balance", cached.get("quote_balance", _ZERO))
        refreshed["realized_pnl_today"] = float(getattr(self, "_realized_pnl_today", _ZERO))
        refreshed["fills_count_today"] = int(getattr(self, "_fills_count_today", 0))
        refreshed["fees_paid_today_quote"] = float(getattr(self, "_fees_paid_today_quote", _ZERO))
        self._publish_bot_minute_snapshot_telemetry(event_ts, refreshed)

    def _build_tick_snapshot(self, equity_quote: Decimal) -> TickSnapshot:
        """Gather controller-level state into a snapshot dict for TickEmitter."""
        adapter_stats: dict[str, Any] = {}
        connector = self._connector()
        if connector is not None and hasattr(connector, "paper_stats"):
            try:
                adapter_stats = dict(connector.paper_stats)
            except Exception:
                adapter_stats = {}
        self._paper_fill_count = int(adapter_stats.get("paper_fill_count", Decimal("0")))
        self._paper_reject_count = int(adapter_stats.get("paper_reject_count", Decimal("0")))
        self._paper_avg_queue_delay_ms = to_decimal(adapter_stats.get("paper_avg_queue_delay_ms", Decimal("0")))

        adapter = self._family_adapter
        runtime_family = getattr(adapter, "__class__", type(adapter)).__name__
        if "Directional" in runtime_family:
            runtime_family = "directional"
        elif "MarketMaking" in runtime_family:
            runtime_family = "market_making"
        else:
            runtime_family = "unknown"

        return {
            "runtime_family": runtime_family,
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
            "pnl_governor_activation_reason_counts": (
                _orjson.dumps(self._pnl_governor_activation_reason_counts, option=_orjson.OPT_SORT_KEYS).decode()
                if _orjson is not None
                else json.dumps(self._pnl_governor_activation_reason_counts, sort_keys=True)
            ),
            "pnl_governor_size_boost_reason_counts": (
                _orjson.dumps(self._pnl_governor_size_boost_reason_counts, option=_orjson.OPT_SORT_KEYS).decode()
                if _orjson is not None
                else json.dumps(self._pnl_governor_size_boost_reason_counts, sort_keys=True)
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
            "adverse_fill_soft_pause_active": self._adverse_fill_soft_pause_active(),
            "edge_confidence_soft_pause_active": self._edge_confidence_soft_pause_active(),
            "slippage_soft_pause_active": self._slippage_soft_pause_active(),
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
            "derisk_force_taker_min_base": self._derisk_force_min_base_amount(),
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
            "min_base_pct": self.config.min_base_pct,
            "max_base_pct": self.config.max_base_pct,
            "max_total_notional_quote": self.config.max_total_notional_quote,
            "max_daily_turnover_x_hard": self.config.max_daily_turnover_x_hard,
            "max_daily_loss_pct_hard": self.config.max_daily_loss_pct_hard,
            "max_drawdown_pct_hard": self.config.max_drawdown_pct_hard,
            "margin_ratio_soft_pause_pct": self.config.margin_ratio_soft_pause_pct,
            "margin_ratio_hard_stop_pct": self.config.margin_ratio_hard_stop_pct,
            "position_drift_soft_pause_pct": self.config.position_drift_soft_pause_pct,
            "variant": self.config.variant,
            "bot_mode": self.config.bot_mode,
            "is_paper": _config_is_paper_check(self.config),
            "connector_name": self.config.connector_name,
            "trading_pair": self.config.trading_pair,
        }

    def _emit_tick_output(
        self, _t0: float, now: float, mid: Decimal,
        regime_name: str, target_base_pct: Decimal, target_net_base_pct: Decimal,
        base_pct_gross: Decimal, base_pct_net: Decimal,
        equity_quote: Decimal, spread_state: SpreadEdgeState, market: MarketConditions,
        risk_hard_stop: bool, risk_reasons: list[str],
        daily_loss_pct: Decimal, drawdown_pct: Decimal,
        projected_total_quote: Decimal, state: GuardState,
        runtime_data_context: RuntimeDataContext | None = None,
        runtime_execution_plan: RuntimeExecutionPlan | None = None,
        runtime_risk_decision: RuntimeRiskDecision | None = None,
    ) -> None:
        """Build ProcessedState, blank levels on pause, and log the minute row."""
        risk_reasons_for_log = list(risk_reasons)
        derisk_only = False
        derisk_runtime_recovered = False
        rr = set(risk_reasons)
        inventory_derisk_reasons = rr.intersection(_INVENTORY_DERISK_REASONS)
        hard_stop_flatten_floor = self._position_rebalance_floor(mid)
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
        self._last_equity_quote = equity_quote
        self._last_quote_balance = quote_bal
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
        self.processed_data["_preflight_hot_path_duration_ms"] = self._preflight_hot_path_duration_ms
        self.processed_data["_execution_plan_duration_ms"] = self._execution_plan_duration_ms
        self.processed_data["_risk_duration_ms"] = self._risk_duration_ms
        self.processed_data["_emit_tick_duration_ms"] = self._emit_tick_duration_ms
        self.processed_data["_governance_duration_ms"] = self._governance_duration_ms

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

        event_ts = datetime.fromtimestamp(now, tz=UTC).isoformat()
        snapshot["tick_duration_ms"] = self._tick_duration_ms
        snapshot["order_book_stale"] = self._is_order_book_stale(now)
        snapshot["cancel_per_min"] = self._cancel_per_min(now)
        runtime_orders_active = sum(1 for ex in self.executors_info if getattr(ex, "is_active", False))
        snapshot["orders_active"] = max(runtime_orders_active, self._open_order_count())
        _st_fields = getattr(self, "telemetry_fields", None)
        _strategy_telem = _st_fields() if callable(_st_fields) else ()
        minute_row = self._tick_emitter.log_minute(
            now, event_ts, self.processed_data, state, risk_reasons_for_log, snapshot,
            strategy_telemetry=_strategy_telem,
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


    def to_format_status(self) -> list[str]:
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
            recovery_info = ""
            guard = getattr(self, "_recovery_guard", None)
            if guard is not None and guard.active:
                recovery_info = (
                    f" | RECOVERY GUARD SL={float(guard.sl_price or 0):.2f} "
                    f"TP={float(guard.tp_price or 0):.2f}"
                )
            lines.append(
                f"** OPEN POSITION: {float(self._position_base):.8f} {self.config.trading_pair} "
                f"(entry={float(self._avg_entry_price):.2f}) — {stop_info}{recovery_info} **"
            )
        return lines

    def get_custom_info(self) -> dict[str, Any]:
        return dict(self.processed_data)
