"""Risk evaluation mixin — extracted from SharedRuntimeKernel.

Contains soft-pause checks, PnL governor sizing, derisk-force management,
and the unified risk / guard-state evaluation entry points.
Used as a mixin: class SharedRuntimeKernel(RiskMixin, ...):
"""
from __future__ import annotations

import heapq
import logging
import math
from decimal import Decimal
from typing import Any

from controllers.ops_guard import GuardState, OpsSnapshot
from controllers.runtime.runtime_types import (
    MarketConditions,
    SpreadEdgeState,
    clip,
)
from platform_lib.core.utils import safe_decimal, to_decimal

logger = logging.getLogger(__name__)

_clip = clip

_ZERO = Decimal("0")
_ONE = Decimal("1")
_100 = Decimal("100")
_10K = Decimal("10000")
_BALANCE_EPSILON = Decimal("1e-12")
_INVENTORY_DERISK_REASONS = frozenset({"base_pct_above_max", "base_pct_below_min", "eod_close_pending"})


class RiskMixin:
    """Mixin providing risk evaluation, soft-pause, and derisk methods."""

    @staticmethod
    def _auto_calibration_p95(values: list[Decimal]) -> Decimal:
        if not values:
            return _ZERO
        n = len(values)
        k = n - int((n - 1) * 0.95)  # number of largest elements needed
        if k <= 0:
            k = 1
        largest = heapq.nlargest(k, values)
        return largest[-1]

    # ------------------------------------------------------------------
    # Soft-pause quality checks
    # ------------------------------------------------------------------

    _fee_fallback_warned: bool = False

    def _fill_edge_below_cost_floor(self) -> bool:
        """Return True when realized fill edge is worse than estimated maker cost floor."""
        fill_edge_ewma = getattr(self, "_fill_edge_ewma", None)
        if fill_edge_ewma is None:
            return False
        maker_fee = to_decimal(getattr(self, "_maker_fee_pct", _ZERO))
        if maker_fee <= _ZERO and not self._fee_fallback_warned:
            self._fee_fallback_warned = True
            logger.warning("Fee extraction fell back to zero — cost floor calculations may be inaccurate")
        cost_floor_bps = (
            max(_ZERO, maker_fee)
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
            return self._fill_edge_below_cost_floor()
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
        safe_var = max(_ZERO, safe_decimal(edge_var_bps2))
        if safe_var <= _ZERO:
            return False

        z_score = max(_ZERO, safe_decimal(getattr(self.config, "edge_confidence_soft_pause_z_score", Decimal("1.96"))))
        fvar = float(safe_var)
        fn = float(n_fills)
        if math.isnan(fvar) or math.isinf(fvar) or fvar < 0:
            return True  # fail-closed: treat as paused when data is corrupted
        std_err = Decimal(str(math.sqrt(fvar) / max(1.0, math.sqrt(max(1.0, fn)))))
        upper_edge_bps = safe_decimal(edge_mean_bps) + (z_score * std_err)

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
        p95_slippage_bps = RiskMixin._auto_calibration_p95(positive_slippage_bps)
        trigger_bps = max(_ZERO, to_decimal(getattr(self.config, "slippage_soft_pause_p95_bps", Decimal("25"))))
        return p95_slippage_bps >= trigger_bps

    def _recent_positive_slippage_p95_bps(
        self,
        *,
        window_fills: int | None = None,
        min_fills: int | None = None,
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
        return RiskMixin._auto_calibration_p95(positive_slippage_bps)

    # ------------------------------------------------------------------
    # PnL governor sizing
    # ------------------------------------------------------------------

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
            self._increment_governor_reason_count("_pnl_governor_size_boost_reason_counts", reason)
            return _ONE
        max_boost_pct = max(_ZERO, to_decimal(self.config.pnl_governor_max_size_boost_pct))
        if max_boost_pct <= _ZERO:
            reason = "max_boost_zero"
            self._pnl_governor_size_boost_reason = reason
            self._increment_governor_reason_count("_pnl_governor_size_boost_reason_counts", reason)
            return _ONE
        deficit_ratio = _clip(self._pnl_governor_deficit_ratio, _ZERO, _ONE)
        activation = _clip(to_decimal(self.config.pnl_governor_size_activation_deficit_pct), _ZERO, _ONE)
        if deficit_ratio <= activation:
            reason = "deficit_below_activation"
            self._pnl_governor_size_boost_reason = reason
            self._increment_governor_reason_count("_pnl_governor_size_boost_reason_counts", reason)
            return _ONE
        turnover_soft_cap = max(_ZERO, to_decimal(self.config.pnl_governor_turnover_soft_cap_x))
        if turnover_soft_cap > _ZERO and turnover_x >= turnover_soft_cap:
            reason = "turnover_soft_cap"
            self._pnl_governor_size_boost_reason = reason
            self._increment_governor_reason_count("_pnl_governor_size_boost_reason_counts", reason)
            return _ONE
        _, drawdown_pct = self._risk_loss_metrics(equity_quote)
        drawdown_soft_cap = max(_ZERO, to_decimal(self.config.pnl_governor_drawdown_soft_cap_pct))
        if drawdown_soft_cap > _ZERO and drawdown_pct >= drawdown_soft_cap:
            reason = "drawdown_soft_cap"
            self._pnl_governor_size_boost_reason = reason
            self._increment_governor_reason_count("_pnl_governor_size_boost_reason_counts", reason)
            return _ONE
        margin_soft_floor = max(_ZERO, to_decimal(self.config.margin_ratio_soft_pause_pct))
        if margin_soft_floor > _ZERO and self._margin_ratio <= margin_soft_floor:
            reason = "margin_soft_floor"
            self._pnl_governor_size_boost_reason = reason
            self._increment_governor_reason_count("_pnl_governor_size_boost_reason_counts", reason)
            return _ONE
        if self._fill_edge_below_cost_floor():
            reason = "fill_edge_below_cost_floor"
            self._pnl_governor_size_boost_reason = reason
            self._increment_governor_reason_count(
                "_pnl_governor_size_boost_reason_counts", reason
            )
            return _ONE
        normalized = _clip((deficit_ratio - activation) / max(Decimal("0.0001"), (_ONE - activation)), _ZERO, _ONE)
        size_mult = _ONE + (normalized * max_boost_pct)
        size_mult = _clip(size_mult, _ONE, _ONE + max_boost_pct)
        self._pnl_governor_size_mult = size_mult
        self._pnl_governor_size_boost_active = size_mult > _ONE
        reason = "active" if self._pnl_governor_size_boost_active else "inactive"
        self._pnl_governor_size_boost_reason = reason
        self._increment_governor_reason_count("_pnl_governor_size_boost_reason_counts", reason)
        return size_mult

    # ------------------------------------------------------------------
    # Derisk force-taker management
    # ------------------------------------------------------------------

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
            min_exchange_base = max(_ZERO, safe_decimal(min_base_amount_fn(reference_price)))
        except Exception:
            logger.warning("derisk force min-base resolution failed — fail-closed (blocking force-taker)", exc_info=True)
            return Decimal("999999")
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
        min_force_base = self._derisk_force_min_base_amount()
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
            if not self._derisk_force_expectancy_allows(abs_position_base, min_force_base):
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
            logger.warning("Unable to import StopExecutorAction — force-derisk executor cancels disabled")
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

    # ------------------------------------------------------------------
    # Unified risk evaluation
    # ------------------------------------------------------------------

    def _evaluate_all_risk(
        self, spread_state: SpreadEdgeState, base_pct_gross: Decimal,
        equity_quote: Decimal, projected_total_quote: Decimal, market: MarketConditions,
    ) -> tuple[list[str], bool, Decimal, Decimal]:
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
        if self._adverse_fill_soft_pause_active():
            if "adverse_fill_soft_pause" not in risk_reasons:
                risk_reasons.append("adverse_fill_soft_pause")
        if self._edge_confidence_soft_pause_active():
            if "edge_confidence_soft_pause" not in risk_reasons:
                risk_reasons.append("edge_confidence_soft_pause")
        if self._slippage_soft_pause_active():
            if "slippage_soft_pause" not in risk_reasons:
                risk_reasons.append("slippage_soft_pause")
        if str(getattr(self, "_selective_quote_state", "inactive")) == "blocked":
            if "selective_quote_soft_pause" not in risk_reasons:
                risk_reasons.append("selective_quote_soft_pause")
        if bool(getattr(self, "_startup_recon_soft_pause", False)):
            if "startup_recon_failed" not in risk_reasons:
                risk_reasons.append("startup_recon_failed")
        return risk_reasons, risk_hard_stop, daily_loss_pct, drawdown_pct

    def _resolve_guard_state(
        self, now: float, market: MarketConditions,
        risk_reasons: list[str], risk_hard_stop: bool,
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
