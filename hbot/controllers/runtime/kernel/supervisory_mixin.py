"""Supervisory / maintenance mixin for SharedRuntimeKernel.

Houses periodic governance helpers: blocked-order sweeps, ghost-position
guards, stale-order cancellation, external execution-intent handling,
portfolio risk checks, and recovery-executor cleanup.
"""
from __future__ import annotations

import json
import logging
import time as _time_mod
from decimal import Decimal
from typing import Any

try:
    import orjson as _orjson
except ImportError:
    _orjson = None

from controllers.runtime.kernel.config import _ZERO, _BALANCE_EPSILON
from controllers.ops_guard import GuardState
from platform_lib.core.utils import to_decimal
from platform_lib.contracts.stream_names import PORTFOLIO_RISK_STREAM

logger = logging.getLogger(__name__)

_ONE = Decimal("1")
_clip: Any = None
try:
    from controllers.runtime.runtime_types import clip as _clip
except Exception:
    def _clip(v, lo, hi):  # type: ignore[misc]
        return max(lo, min(v, hi))


class SupervisoryMixin:

    # ------------------------------------------------------------------
    # Recovery zombie cleanup
    # ------------------------------------------------------------------

    def _cleanup_recovery_zombie_executors(self) -> None:
        """Stop recovery_close executors that have filled and are now zombies.

        A PositionExecutor created for recovery close has no SL/TP/time_limit,
        so it never reaches a terminal state on its own.  Once it has filled
        (is_trading), it no longer serves a purpose and should be stopped to
        free up executor slots.
        """
        if self._recovery_zombie_cleaned or not self._recovery_close_emitted:
            return
        if self._recovery_guard is not None:
            return
        try:
            zombie_executors = self.filter_executors(
                executors=self.executors_info,
                filter_func=lambda x: (
                    getattr(x, "is_active", False)
                    and getattr(x, "is_trading", False)
                    and (getattr(x, "custom_info", None) or {}).get("level_id") == "recovery_close"
                ),
            )
        except Exception:
            return  # executor query unavailable — skip zombie cleanup
        if not zombie_executors:
            return
        try:
            from hummingbot.strategy_v2.models.executor_actions import StopExecutorAction
        except Exception:
            logger.warning("Unable to import StopExecutorAction — zombie recovery cleanup disabled")
            self._recovery_zombie_cleaned = True
            return
        for ex in zombie_executors:
            ex_id = str(getattr(ex, "id", "") or "")
            if not ex_id:
                continue
            self._pending_stale_cancel_actions.append(
                StopExecutorAction(controller_id=self.config.id, executor_id=ex_id)
            )
            logger.info("Stopping zombie recovery_close executor %s", ex_id)
        self._recovery_zombie_cleaned = True

    # ------------------------------------------------------------------
    # Blocked-order sweep
    # ------------------------------------------------------------------

    _BLOCKED_SWEEP_COOLDOWN_S: float = 3.0

    def _enforce_blocked_order_sweep(self, now: float) -> None:
        """Cancel all resting orders and stop executors every tick while blocked.

        Unlike the transition-only cancel, this runs continuously with a
        cooldown so that orders which survived a single cancel attempt are
        retried on the next pass.  Safe to call when RUNNING — it no-ops.
        """
        state = getattr(self, "_ops_guard", None)
        guard_state = getattr(state, "state", None) if state is not None else None
        if guard_state is None or guard_state == GuardState.RUNNING:
            self._blocked_sweep_ticks = 0
            return

        derisk_only = bool(getattr(self, "_derisk_only_mode", False))
        if derisk_only:
            return

        self._blocked_sweep_ticks = getattr(self, "_blocked_sweep_ticks", 0) + 1

        last_ts = float(getattr(self, "_blocked_sweep_last_ts", 0.0) or 0.0)
        if (now - last_ts) < self._BLOCKED_SWEEP_COOLDOWN_S:
            return
        self._blocked_sweep_last_ts = now

        stopped = 0
        try:
            from hummingbot.strategy_v2.models.executor_actions import StopExecutorAction
            for executor in self.executors_info:
                if not bool(getattr(executor, "is_active", False)):
                    continue
                ex_id = str(getattr(executor, "id", "") or "")
                if not ex_id:
                    continue
                self._pending_stale_cancel_actions.append(
                    StopExecutorAction(controller_id=self.config.id, executor_id=ex_id)
                )
                stopped += 1
        except Exception:
            logger.debug("blocked_sweep: StopExecutorAction import failed", exc_info=True)

        cancelled = 0
        try:
            cancelled = self._cancel_active_runtime_orders()
        except Exception:
            logger.debug("blocked_sweep: _cancel_active_runtime_orders failed", exc_info=True)

        try:
            cancelled += self._cancel_stale_orders(stale_age_s=0.0, now_ts=now)
        except Exception:
            logger.debug("blocked_sweep: _cancel_stale_orders failed", exc_info=True)

        if stopped or cancelled:
            logger.info(
                "BLOCKED_SWEEP: state=%s tick=%d, stopped %d executors, cancelled %d orders",
                guard_state.value if hasattr(guard_state, "value") else str(guard_state),
                self._blocked_sweep_ticks, stopped, cancelled,
            )

    # ------------------------------------------------------------------
    # Unintended (ghost) position guard
    # ------------------------------------------------------------------

    _UNINTENDED_POSITION_TICKS_THRESHOLD: int = 10
    _UNINTENDED_POSITION_MIN_NOTIONAL: Decimal = Decimal("5")

    def _guard_unintended_position(self, now: float) -> None:
        """Force-close positions that accumulated while all gates were blocking.

        After N consecutive blocked ticks with a non-trivial position,
        emit a MARKET close.  Opt-in via config ``ghost_position_guard_enabled``.
        """
        if not bool(getattr(self.config, "ghost_position_guard_enabled", False)):
            return

        blocked_ticks = getattr(self, "_blocked_sweep_ticks", 0)
        if blocked_ticks < self._UNINTENDED_POSITION_TICKS_THRESHOLD:
            return

        pos = self._position_base
        if abs(pos) < Decimal("0.00001"):
            return

        mid = to_decimal(self.processed_data.get("reference_price") or self.processed_data.get("mid") or Decimal("1"))
        notional = abs(pos) * mid
        if notional < self._UNINTENDED_POSITION_MIN_NOTIONAL:
            return

        guard_ts = getattr(self, "_ghost_guard_last_close_ts", 0.0)
        if (now - guard_ts) < 30.0:
            return
        self._ghost_guard_last_close_ts = now

        try:
            from hummingbot.core.data_type.common import OrderType as _HBOrderType
            from hummingbot.core.data_type.common import TradeType as _TradeType
            from hummingbot.strategy_v2.executors.position_executor.data_types import PositionExecutorConfig
            from hummingbot.strategy_v2.models.executor_actions import CreateExecutorAction

            close_side = _TradeType.SELL if pos > _ZERO else _TradeType.BUY
            amount = abs(pos)
            q_amount = self._quantize_amount(amount) if hasattr(self, "_quantize_amount") else amount
            if q_amount <= _ZERO:
                q_amount = amount

            tbc = self.config.triple_barrier_config.model_copy(
                update={
                    "open_order_type": _HBOrderType.MARKET,
                    "stop_loss": None,
                    "take_profit": None,
                    "time_limit": None,
                },
            )
            executor_config = PositionExecutorConfig(
                timestamp=self.market_data_provider.time(),
                level_id="ghost_position_close",
                connector_name=str(getattr(self.config, "connector_name", "")),
                trading_pair=str(self.config.trading_pair),
                entry_price=None,
                amount=q_amount,
                triple_barrier_config=tbc,
                leverage=int(getattr(self.config, "leverage", 1)),
                side=close_side,
            )
            logger.critical(
                "GHOST_POSITION_GUARD: blocked_ticks=%d position=%s notional=%.2f — force-closing",
                blocked_ticks, pos, float(notional),  # float: log-formatting
            )
            self._pending_stale_cancel_actions.append(
                CreateExecutorAction(controller_id=self.config.id, executor_config=executor_config)
            )
        except Exception:
            logger.error("GHOST_POSITION_GUARD: failed to emit close action", exc_info=True)

    # ------------------------------------------------------------------
    # Supervisory dispatcher
    # ------------------------------------------------------------------

    def _run_supervisory_maintenance(self, now: float) -> None:
        """Move slower governance/telemetry checks after the order decision path."""
        self._enforce_blocked_order_sweep(now)
        self._guard_unintended_position(now)
        self._ensure_fee_config(now)
        self._refresh_funding_rate(now)
        self._check_portfolio_risk_guard(now)
        self._check_position_reconciliation(now)
        self._cleanup_recovery_zombie_executors()

    # ------------------------------------------------------------------
    # Stale-side executor cancellation
    # ------------------------------------------------------------------

    def _cancel_stale_side_executors(self, old_one_sided: str, new_one_sided: str) -> list[Any]:
        """Return StopExecutorActions for active executors on a side the new regime disabled."""
        from hummingbot.strategy_v2.models.executor_actions import StopExecutorAction

        cancel_buy = (
            (new_one_sided == "sell_only" and old_one_sided != "sell_only")
            or (new_one_sided == "off" and old_one_sided != "off")
        )
        cancel_sell = (
            (new_one_sided == "buy_only" and old_one_sided != "buy_only")
            or (new_one_sided == "off" and old_one_sided != "off")
        )
        if not cancel_buy and not cancel_sell:
            return []
        actions: list[Any] = []
        for executor in self.executors_info:
            if not executor.is_active:
                continue
            custom = getattr(executor, "custom_info", None) or {}
            level_id = custom.get("level_id", "") if isinstance(custom, dict) else ""
            if (cancel_buy and level_id.startswith("buy")) or (cancel_sell and level_id.startswith("sell")):
                actions.append(StopExecutorAction(controller_id=self.config.id, executor_id=executor.id))
        if actions:
            logger.info("Regime transition %s→%s: canceling %d stale-side executors", old_one_sided, new_one_sided, len(actions))
        return actions

    # ------------------------------------------------------------------
    # Active quote executor cancellation (alpha no-trade)
    # ------------------------------------------------------------------

    def _cancel_active_quote_executors(self) -> list[Any]:
        """Return StopExecutorActions for all active quote executors.

        Used by alpha no-trade fail-closed behavior so outstanding buy/sell quote
        executors do not keep resting and filling after the policy disabled quoting.
        """
        try:
            from hummingbot.strategy_v2.models.executor_actions import StopExecutorAction
        except Exception:
            logger.debug("Unable to import StopExecutorAction for alpha no-trade cancel", exc_info=True)
            return []

        requested_ids = getattr(self, "_alpha_no_trade_cancel_requested_ids", None)
        if not isinstance(requested_ids, set):
            requested_ids = set()
            self._alpha_no_trade_cancel_requested_ids = requested_ids
        if len(requested_ids) > 10_000:
            requested_ids.clear()

        existing_pending = {
            str(getattr(a, "executor_id", ""))
            for a in self._pending_stale_cancel_actions
            if getattr(a, "executor_id", None) is not None
        }

        actions: list[Any] = []
        for executor in self.executors_info:
            if not bool(getattr(executor, "is_active", False)):
                continue
            custom = getattr(executor, "custom_info", None) or {}
            level_id = str(custom.get("level_id", "") if isinstance(custom, dict) else "")
            if not (level_id.startswith("buy") or level_id.startswith("sell")):
                continue
            ex_id = str(getattr(executor, "id", "") or "")
            if not ex_id or ex_id in existing_pending or ex_id in requested_ids:
                continue
            actions.append(StopExecutorAction(controller_id=self.config.id, executor_id=ex_id))
            requested_ids.add(ex_id)

        if actions:
            logger.info("Alpha no-trade: canceling %d active quote executors", len(actions))
        return actions

    # ------------------------------------------------------------------
    # Alpha no-trade order cancellation
    # ------------------------------------------------------------------

    def _cancel_alpha_no_trade_orders(self) -> int:
        """Cancel lingering orders while alpha policy is in no-trade.

        Works uniformly for both paper (bridged) and live connectors.
        """
        provider = getattr(self, "market_data_provider", None)
        time_fn = getattr(provider, "time", None) if provider is not None else None
        now_ts = float(time_fn()) if callable(time_fn) else float(_time_mod.time())
        cooldown_s = 5.0
        last_ts = float(getattr(self, "_alpha_no_trade_last_paper_cancel_ts", 0.0) or 0.0)
        if (now_ts - last_ts) < cooldown_s:
            return 0
        self._alpha_no_trade_last_paper_cancel_ts = now_ts

        try:
            canceled = self._cancel_stale_orders(
                stale_age_s=0.25,
                now_ts=now_ts,
            )
        except Exception:
            logger.debug("Alpha no-trade order cleanup skipped", exc_info=True)
            canceled = 0

        try:
            canceled += self._cancel_active_runtime_orders()
        except Exception:
            logger.debug("Alpha no-trade runtime-order cleanup skipped", exc_info=True)

        if canceled > 0:
            logger.info("Alpha no-trade: canceled %d lingering order(s)", canceled)
        return canceled

    # ------------------------------------------------------------------
    # Active runtime order cancellation
    # ------------------------------------------------------------------

    def _cancel_active_runtime_orders(self) -> int:
        """Cancel active runtime orders from the Paper Exchange Service.

        These orders live in ``_paper_exchange_runtime_orders`` — a separate
        store from PaperDesk engine orders (which are exposed via
        ``connector.get_open_orders()``).  In live mode this is a no-op
        because the store is empty.
        """
        strategy = getattr(self, "strategy", None) or getattr(self, "_strategy", None)
        if strategy is None:
            return 0
        cancel_order = getattr(strategy, "cancel", None)
        if not callable(cancel_order):
            return 0

        runtime_store = getattr(strategy, "_paper_exchange_runtime_orders", {}) or {}
        if not isinstance(runtime_store, dict):
            return 0
        connector_name = str(getattr(self.config, "connector_name", "") or "")
        trading_pair = str(getattr(self.config, "trading_pair", "") or "")
        bucket = runtime_store.get(connector_name)
        if not isinstance(bucket, dict):
            return 0

        canceled = 0
        for raw_order in list(bucket.values()):
            if raw_order is None:
                continue
            order_id = str(getattr(raw_order, "client_order_id", "") or getattr(raw_order, "order_id", "") or "")
            if not order_id:
                continue
            order_pair = str(getattr(raw_order, "trading_pair", "") or trading_pair)
            if trading_pair and order_pair and order_pair != trading_pair:
                continue
            state = str(getattr(raw_order, "current_state", "") or "").strip().lower()
            is_open = bool(getattr(raw_order, "is_open", False))
            if state in {"pending_cancel", "canceled", "cancelled", "filled", "failed", "rejected", "expired"}:
                continue
            if not is_open and state not in {"working", "pending_create", "partially_filled", "open", "partial"}:
                continue
            try:
                cancel_order(connector_name, order_pair or trading_pair, order_id)
            except Exception:
                logger.debug("Runtime active-order cleanup skipped order_id=%s", order_id, exc_info=True)
                continue
            canceled += 1

        if canceled > 0:
            logger.info("Alpha no-trade: requested cancel for %d active runtime order(s)", canceled)
        return canceled

    # ------------------------------------------------------------------
    # Stale order cancellation
    # ------------------------------------------------------------------

    def _cancel_stale_orders(self, stale_age_s: float, now_ts: float | None = None) -> int:
        """Cancel orders that outlive the refresh window.

        Works uniformly for both paper (bridged) and live connectors.
        """
        stale_age_s = max(0.0, float(stale_age_s or 0.0))
        if stale_age_s <= 0.0:
            return 0

        try:
            connector = self._connector()
            open_orders_fn = getattr(connector, "get_open_orders", None)
            if not callable(open_orders_fn):
                return 0
            strategy = getattr(self, "strategy", None) or getattr(self, "_strategy", None)
            cancel_fn = getattr(strategy, "cancel", None) if strategy is not None else None
            if not callable(cancel_fn):
                return 0

            now_epoch = float(now_ts if now_ts is not None else self.market_data_provider.time())
            connector_name = str(getattr(self.config, "connector_name", "") or "")
            trading_pair = str(self.config.trading_pair)
            cancel_ids: list[str] = []
            for order in list(open_orders_fn() or []):
                if str(getattr(order, "trading_pair", "")) != trading_pair:
                    continue
                source_bot = str(getattr(order, "source_bot", "") or "")
                if connector_name and source_bot and source_bot != connector_name:
                    continue
                order_id = str(getattr(order, "client_order_id", "") or getattr(order, "order_id", "") or "")
                if not order_id:
                    continue
                created_ts = float(
                    getattr(order, "creation_timestamp", 0)
                    or getattr(order, "created_at_ns", 0) / 1e9
                    or 0
                )
                if created_ts <= 0:
                    continue
                if (now_epoch - created_ts) >= stale_age_s:
                    cancel_ids.append(order_id)

            canceled = 0
            for order_id in cancel_ids:
                try:
                    cancel_fn(connector_name, trading_pair, order_id)
                    canceled += 1
                except Exception:
                    logger.debug("Stale cancel skipped order_id=%s", order_id, exc_info=True)
            if canceled > 0:
                self._recently_issued_levels = {}
            return canceled
        except Exception:
            logger.debug("Stale order cleanup failed for %s", self.config.trading_pair, exc_info=True)
            return 0

    # ------------------------------------------------------------------
    # Cancel-per-minute tracker
    # ------------------------------------------------------------------

    def _cancel_per_min(self, now: float) -> int:
        recent = [ts for ts in self._cancel_events_ts if now - ts <= 60.0]
        self._cancel_events_ts = recent
        return len(recent)

    # ------------------------------------------------------------------
    # External intent override expiration
    # ------------------------------------------------------------------

    def _expire_external_intent_overrides(self, now_ts: float) -> None:
        """Expire stale external execution-intent overrides to prevent sticky state."""
        ttl_s = int(max(0, int(self.config.execution_intent_override_ttl_s)))
        ttl = float(ttl_s)

        base_override = getattr(self, "_external_target_base_pct_override", None)
        base_override_ts = float(getattr(self, "_external_target_base_pct_override_ts", 0.0) or 0.0)
        base_override_expires_ts = float(
            getattr(self, "_external_target_base_pct_override_expires_ts", 0.0) or 0.0
        )
        base_expired = False
        if base_override is not None:
            if base_override_expires_ts > 0.0:
                base_expired = now_ts >= base_override_expires_ts
            elif ttl_s > 0:
                base_expired = base_override_ts <= 0.0 or (now_ts - base_override_ts) > ttl
        if base_override is not None and base_expired:
            self._external_target_base_pct_override = None
            self._external_target_base_pct_override_ts = 0.0
            self._external_target_base_pct_override_expires_ts = 0.0
            logger.info("Expired stale external target_base_pct override (ttl=%ss)", ttl_s)

        daily_target_override = getattr(self, "_external_daily_pnl_target_pct_override", None)
        daily_target_override_ts = float(
            getattr(self, "_external_daily_pnl_target_pct_override_ts", 0.0) or 0.0
        )
        daily_target_override_expires_ts = float(
            getattr(self, "_external_daily_pnl_target_pct_override_expires_ts", 0.0) or 0.0
        )
        daily_expired = False
        if daily_target_override is not None:
            if daily_target_override_expires_ts > 0.0:
                daily_expired = now_ts >= daily_target_override_expires_ts
            elif ttl_s > 0:
                daily_expired = daily_target_override_ts <= 0.0 or (now_ts - daily_target_override_ts) > ttl
        if daily_target_override is not None and daily_expired:
            self._external_daily_pnl_target_pct_override = None
            self._external_daily_pnl_target_pct_override_ts = 0.0
            self._external_daily_pnl_target_pct_override_expires_ts = 0.0
            logger.info("Expired stale external daily_pnl_target_pct override (ttl=%ss)", ttl_s)

    @staticmethod
    def _intent_expires_ts(intent: dict[str, object], now_ts: float) -> float:
        expires_at_ms = intent.get("expires_at_ms")
        try:
            if expires_at_ms is None:
                return 0.0
            expires_ts = float(expires_at_ms) / 1000.0
            if expires_ts <= now_ts:
                return 0.0
            return expires_ts
        except Exception:
            return 0.0

    # ------------------------------------------------------------------
    # External soft-pause
    # ------------------------------------------------------------------

    def set_external_soft_pause(self, active: bool, reason: str) -> None:
        self._external_soft_pause = bool(active)
        if self._external_soft_pause:
            resolved_reason = str(reason or "").strip()
            self._external_pause_reason = resolved_reason or "external_intent"
        else:
            self._external_pause_reason = ""

    # ------------------------------------------------------------------
    # Execution intent application
    # ------------------------------------------------------------------

    def apply_execution_intent(self, intent: dict[str, object]) -> tuple[bool, str]:
        action = str(intent.get("action", "")).strip()
        metadata = intent.get("metadata", {})
        metadata = metadata if isinstance(metadata, dict) else {}
        provider = getattr(self, "market_data_provider", None)
        now_ts = float(provider.time()) if provider is not None else float(_time_mod.time())
        self._last_external_intent_ts = now_ts
        self._last_external_model_version = str(metadata.get("model_version", ""))
        self._last_external_intent_reason = str(metadata.get("reason", ""))
        if action == "soft_pause":
            reason = str(metadata.get("reason", "external_intent"))
            self.set_external_soft_pause(True, reason)
            return True, "ok"
        if action == "resume":
            self.set_external_soft_pause(False, "")
            return True, "ok"
        if action == "kill_switch":
            self._ops_guard.force_hard_stop("external_kill_switch")
            return True, "ok"
        if action == "set_target_base_pct":
            value = intent.get("target_base_pct")
            if value is None:
                return False, "missing_target_base_pct"
            try:
                candidate = to_decimal(value)
                if candidate < Decimal("0") or candidate > Decimal("1"):
                    return False, "target_base_pct_out_of_range"
                self._external_target_base_pct_override = _clip(candidate, Decimal("0"), Decimal("1"))
                self._external_target_base_pct_override_ts = now_ts
                self._external_target_base_pct_override_expires_ts = SupervisoryMixin._intent_expires_ts(
                    intent, now_ts
                )
                return True, "ok"
            except Exception:
                return False, "invalid_target_base_pct"
        if action == "set_daily_pnl_target_pct":
            value = intent.get("daily_pnl_target_pct")
            if value is None:
                value = metadata.get("daily_pnl_target_pct")
            if value is None:
                return False, "missing_daily_pnl_target_pct"
            try:
                candidate = to_decimal(value)
                if candidate < Decimal("0") or candidate > Decimal("100"):
                    return False, "daily_pnl_target_pct_out_of_range"
                self._external_daily_pnl_target_pct_override = _clip(candidate, Decimal("0"), Decimal("100"))
                self._external_daily_pnl_target_pct_override_ts = now_ts
                self._external_daily_pnl_target_pct_override_expires_ts = SupervisoryMixin._intent_expires_ts(
                    intent, now_ts
                )
                return True, "ok"
            except Exception:
                return False, "invalid_daily_pnl_target_pct"
        if action == "adverse_skip_tick":
            if not self.config.adverse_classifier_enabled:
                return False, "adverse_classifier_not_enabled"
            p_adverse = float(metadata.get("p_adverse", 0))
            self._runtime_levels.buy_spreads = []
            self._runtime_levels.sell_spreads = []
            self._runtime_levels.buy_amounts_pct = []
            self._runtime_levels.sell_amounts_pct = []
            logger.debug("Adverse skip: cleared spreads (p_adverse=%.3f skip_count=%d)", p_adverse, self._adverse_skip_count)
            return True, "ok"
        if action == "adverse_widen_spreads":
            if not self.config.adverse_classifier_enabled:
                return False, "adverse_classifier_not_enabled"
            p_adverse_d = to_decimal(metadata.get("p_adverse", 0))
            widen_mult = _ONE + p_adverse_d * Decimal("0.5")
            for i in range(len(self._runtime_levels.buy_spreads)):
                self._runtime_levels.buy_spreads[i] = self._runtime_levels.buy_spreads[i] * widen_mult
            for i in range(len(self._runtime_levels.sell_spreads)):
                self._runtime_levels.sell_spreads[i] = self._runtime_levels.sell_spreads[i] * widen_mult
            logger.debug("Adverse widen: spread × %.3f (p_adverse=%.3f)", float(widen_mult), float(p_adverse_d))
            return True, "ok"
        if action == "set_regime_override":
            if not self.config.ml_regime_enabled:
                return False, "ml_regime_not_enabled"
            regime = str(intent.get("regime", metadata.get("regime", ""))).strip()
            if not regime or regime not in self._resolved_specs:
                return False, f"unknown_regime:{regime}"
            now = float(self.market_data_provider.time())
            self._external_regime_override = regime
            self._external_regime_override_expiry = now + self.config.ml_regime_override_ttl_s
            logger.debug("ML regime override set: %s (expires in %.0fs)", regime, self.config.ml_regime_override_ttl_s)
            return True, "ok"
        if action == "set_ml_regime":
            if not getattr(self.config, "ml_regime_override_enabled", False):
                return False, "ml_regime_override_not_enabled"
            regime = str(intent.get("regime", metadata.get("regime", ""))).strip()
            confidence = float(intent.get("confidence", metadata.get("confidence", 0)))
            threshold = float(getattr(self.config, "ml_confidence_threshold", 0.5))
            if confidence < threshold:
                return False, f"low_confidence:{confidence:.3f}<{threshold:.3f}"
            if not regime or regime not in self._resolved_specs:
                return False, f"unknown_regime:{regime}"
            now = float(self.market_data_provider.time())
            self._external_regime_override = regime
            self._external_regime_override_expiry = now + self.config.ml_regime_override_ttl_s
            logger.debug("ML feature regime: %s (confidence=%.3f)", regime, confidence)
            return True, "ok"
        if action == "set_ml_direction_hint":
            if not getattr(self.config, "ml_direction_hint_enabled", False):
                return False, "ml_direction_hint_not_enabled"
            direction = str(intent.get("direction", metadata.get("direction", ""))).strip()
            confidence = float(intent.get("confidence", metadata.get("confidence", 0)))
            threshold = float(getattr(self.config, "ml_confidence_threshold", 0.5))
            if confidence < threshold:
                return False, f"low_confidence:{confidence:.3f}<{threshold:.3f}"
            self._ml_direction_hint = direction
            self._ml_direction_hint_confidence = confidence
            logger.debug("ML direction hint: %s (confidence=%.3f)", direction, confidence)
            return True, "ok"
        if action == "set_ml_sizing_hint":
            if not getattr(self.config, "ml_sizing_hint_enabled", False):
                return False, "ml_sizing_hint_not_enabled"
            multiplier = float(intent.get("multiplier", metadata.get("multiplier", 1.0)))
            confidence = float(intent.get("confidence", metadata.get("confidence", 0)))
            self._ml_sizing_multiplier = max(0.0, min(multiplier, 3.0))
            logger.debug("ML sizing hint: %.3f (confidence=%.3f)", multiplier, confidence)
            return True, "ok"
        return False, "unsupported_action"

    # ------------------------------------------------------------------
    # Portfolio risk guard
    # ------------------------------------------------------------------

    def _check_portfolio_risk_guard(self, now_ts: float) -> None:
        """Fail-closed when portfolio_risk_service broadcasts global kill_switch."""
        if not self.config.portfolio_risk_guard_enabled:
            return
        if now_ts - self._last_portfolio_risk_check_ts < float(self.config.portfolio_risk_guard_check_s):
            return
        self._last_portfolio_risk_check_ts = now_ts
        if self._portfolio_risk_hard_stop_latched:
            return
        stream_name = str(self.config.portfolio_risk_stream_name or PORTFOLIO_RISK_STREAM)
        max_age_s = int(self.config.portfolio_risk_guard_max_age_s)
        r = self._get_telemetry_redis()
        if r is None:
            return
        try:
            rows = r.xrevrange(stream_name, "+", "-", count=1)
            if not rows:
                return
            _entry_id, data = rows[0]
            payload_raw = data.get("payload") if isinstance(data, dict) else None
            if not isinstance(payload_raw, str) or not payload_raw:
                return
            payload = _orjson.loads(payload_raw) if _orjson is not None else json.loads(payload_raw)
            if not isinstance(payload, dict):
                return
            if str(payload.get("portfolio_action", "allow")) != "kill_switch":
                return
            ts_ms = float(payload.get("timestamp_ms") or 0)
            if ts_ms > 0:
                age_s = max(0.0, now_ts - ts_ms / 1000.0)
                if age_s > float(max_age_s):
                    return
            scope = payload.get("risk_scope_bots", [])
            if isinstance(scope, list) and scope:
                scope_s = {str(x) for x in scope}
                if self.config.instance_name not in scope_s:
                    return
            self._portfolio_risk_hard_stop_latched = True
            self._ops_guard.force_hard_stop("portfolio_risk_global_breach")
            logger.error(
                "Portfolio risk guard triggered HARD_STOP for %s (stream=%s).",
                self.config.instance_name, stream_name,
            )
        except Exception:
            logger.debug("Portfolio risk guard check failed", exc_info=True)
