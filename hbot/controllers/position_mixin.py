"""Position management mixin — extracted from SharedRuntimeKernel.

Contains position rebalance, reconciliation, startup sync, and recovery guard logic.
Used as a mixin: class SharedRuntimeKernel(PositionMixin, ...):
"""
from __future__ import annotations

import logging
import time as _time_mod
from decimal import Decimal
from typing import Any

from controllers.ops_guard import GuardState

try:
    from hummingbot.core.data_type.common import TradeType
except ImportError:
    TradeType = None  # type: ignore[assignment,misc]

from platform_lib.core.utils import to_decimal

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")
_ONE = Decimal("1")
_100 = Decimal("100")
_BALANCE_EPSILON = Decimal("1e-12")
_MIN_SPREAD = Decimal("1e-10")
_INVENTORY_DERISK_REASONS = frozenset({"base_pct_above_max", "base_pct_below_min", "eod_close_pending"})


class PositionMixin:
    """Mixin providing position management methods for SharedRuntimeKernel."""

    def _position_rebalance_floor(self, reference_price: Decimal) -> Decimal:
        """Minimum base size required to issue a rebalance order."""
        from controllers.shared_runtime_v24 import _runtime_family_adapter
        return _runtime_family_adapter(self).position_rebalance_floor(reference_price)

    def _recovery_close_action(self) -> Any | None:
        """Build a CreateExecutorAction to flatten an orphaned position.

        Uses the same PositionExecutorConfig + CreateExecutorAction pattern as
        ``create_position_rebalance_order`` but with MARKET order type and
        no SL/TP (just close).

        Uses the *current* ``self._position_base`` (not the guard snapshot) so
        the close side and amount reflect any fills that arrived between guard
        init and trigger.
        """
        guard = self._recovery_guard
        if guard is None or not self._recovery_close_emitted:
            return None

        current_pos = self._position_base
        if abs(current_pos) <= _BALANCE_EPSILON:
            guard.deactivate("position_flat_at_close_time")
            return None

        try:
            from hummingbot.core.data_type.common import OrderType as _HBOrderType
            from hummingbot.core.data_type.common import TradeType as _TradeType
            from hummingbot.strategy_v2.executors.position_executor.data_types import PositionExecutorConfig
            from hummingbot.strategy_v2.models.executor_actions import CreateExecutorAction

            close_side = _TradeType.SELL if current_pos > _ZERO else _TradeType.BUY
            amount = abs(current_pos)
            q_amount = self._quantize_amount(amount)
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
                level_id="recovery_close",
                connector_name=str(getattr(self.config, "connector_name", "")),
                trading_pair=str(self.config.trading_pair),
                entry_price=None,
                amount=q_amount,
                triple_barrier_config=tbc,
                leverage=int(getattr(self.config, "leverage", 1)),
                side=close_side,
            )
            logger.warning(
                "RECOVERY CLOSE ACTION: side=%s amount=%.8f pair=%s (guard_snapshot=%.8f)",
                close_side.name, float(q_amount), self.config.trading_pair,
                float(guard.position_base),
            )
            guard.deactivate("close_action_emitted")
            return CreateExecutorAction(
                controller_id=self.config.id,
                executor_config=executor_config,
            )
        except Exception:
            logger.error("Failed to build recovery close action", exc_info=True)
            return None

    def check_position_rebalance(self) -> Any | None:
        _close_fn = getattr(self, "_recovery_close_action", None)
        if callable(_close_fn):
            recovery_action = _close_fn()
            if recovery_action is not None:
                self._recovery_guard = None
                return recovery_action
        is_perp_connector = "_perpetual" in self.config.connector_name
        ops_guard = getattr(self, "_ops_guard", None)
        guard_reasons = set(getattr(ops_guard, "reasons", []) or [])
        inventory_derisk_active = bool(guard_reasons.intersection(_INVENTORY_DERISK_REASONS))
        guard_state = getattr(ops_guard, "state", None)
        derisk_only_active = (
            guard_state == GuardState.SOFT_PAUSE
            and inventory_derisk_active
        )
        hard_stop_flatten_active = (
            guard_state == GuardState.HARD_STOP
            and abs(self._position_base) > _BALANCE_EPSILON
        )
        if "reference_price" not in self.processed_data or (
            self.config.skip_rebalance
            and not (self._derisk_force_taker or derisk_only_active or hard_stop_flatten_active)
        ):
            return None
        # Perps normally skip rebalance orders, but when derisk_only is active we must
        # actively flatten inventory even before force-taker escalation kicks in.
        if is_perp_connector and not (self._derisk_force_taker or derisk_only_active or hard_stop_flatten_active):
            return None
        active_rebalance = self.filter_executors(
            executors=self.executors_info,
            filter_func=lambda x: x.is_active and x.custom_info.get("level_id") == "position_rebalance",
        )
        if len(active_rebalance) > 0:
            if derisk_only_active:
                trace_derisk = getattr(self, "_trace_derisk", None)
                if callable(trace_derisk):
                    trace_derisk(
                        self.market_data_provider.time(),
                        "rebalance_skipped_active_executor",
                        active_rebalance=len(active_rebalance),
                    )
            return None
        reference_price = to_decimal(self.processed_data["reference_price"])
        if is_perp_connector:
            required_base_amount = self._perp_target_base_amount(reference_price)
        else:
            required_base_amount = self._runtime_required_base_amount(reference_price)
        current_base_amount = self._position_base if is_perp_connector else self.get_current_base_position()
        base_amount_diff = required_base_amount - current_base_amount
        threshold_amount = required_base_amount * self.config.position_rebalance_threshold_pct
        # Guard against zero-threshold churn when target inventory is near flat.
        # Without this floor, tiny residual inventory can trigger repeated
        # min-notional taker rebalances (buy/sell ping-pong).
        min_rebalance_floor = self._position_rebalance_floor(reference_price)
        threshold_amount = max(threshold_amount, min_rebalance_floor)
        if derisk_only_active:
            trace_derisk = getattr(self, "_trace_derisk", None)
            if callable(trace_derisk):
                trace_derisk(
                    self.market_data_provider.time(),
                    "rebalance_eval",
                    required_base_amount=required_base_amount,
                    current_base_amount=current_base_amount,
                    base_amount_diff=base_amount_diff,
                    threshold_amount=threshold_amount,
                    skip_rebalance=self.config.skip_rebalance,
                    force_taker=self._derisk_force_taker,
                )
        if abs(base_amount_diff) > threshold_amount:
            if derisk_only_active:
                trace_derisk = getattr(self, "_trace_derisk", None)
                if callable(trace_derisk):
                    trace_derisk(
                        self.market_data_provider.time(),
                        "rebalance_proposed",
                        required_base_amount=required_base_amount,
                        current_base_amount=current_base_amount,
                        base_amount_diff=base_amount_diff,
                        threshold_amount=threshold_amount,
                    )
            if base_amount_diff > 0:
                return self.create_position_rebalance_order(TradeType.BUY, abs(base_amount_diff))
            return self.create_position_rebalance_order(TradeType.SELL, abs(base_amount_diff))
        if derisk_only_active:
            trace_derisk = getattr(self, "_trace_derisk", None)
            if callable(trace_derisk):
                trace_derisk(
                    self.market_data_provider.time(),
                    "rebalance_skipped_threshold",
                    required_base_amount=required_base_amount,
                    current_base_amount=current_base_amount,
                    base_amount_diff=base_amount_diff,
                    threshold_amount=threshold_amount,
                )
        return None

    def _force_position_reconciliation(self) -> None:
        """Immediately reconcile local position with the exchange, bypassing the
        periodic interval check.  Called after every fill to prevent position
        state from drifting between the bot and the paper exchange desk."""
        provider = getattr(self, "market_data_provider", None)
        now_ts = float(provider.time()) if provider is not None else float(_time_mod.time())
        self._do_position_reconciliation(now_ts)

    def _check_position_reconciliation(self, now_ts: float) -> None:
        """Periodically compare local position with exchange-reported position.

        When drift exceeds the soft-pause threshold, auto-corrects local state
        to match the exchange (source of truth) and saves immediately.
        """
        if now_ts - self._last_position_recon_ts < self.config.position_recon_interval_s:
            return
        self._do_position_reconciliation(now_ts)

    def _do_position_reconciliation(self, now_ts: float) -> None:
        """Core reconciliation logic shared by periodic and forced paths."""
        self._last_position_recon_ts = now_ts
        connector = self._connector()
        if connector is None:
            return
        try:
            if self._is_perp:
                pos_fn = getattr(connector, "get_position", None) or getattr(connector, "account_positions", None)
                if callable(pos_fn):
                    try:
                        pos = pos_fn(self.config.trading_pair)
                    except TypeError:
                        pos = pos_fn()
                    if hasattr(pos, "amount"):
                        exchange_pos = to_decimal(pos.amount)
                    elif isinstance(pos, dict):
                        exchange_pos = to_decimal(pos.get(self.config.trading_pair, {}).get("amount", 0))
                    else:
                        return
                else:
                    return
            else:
                exchange_pos = self._compute_total_base_with_locked(connector)
            local_pos = self._position_base
            if exchange_pos == _ZERO and local_pos == _ZERO:
                self._position_drift_pct = _ZERO
                return
            ref = max(abs(exchange_pos), abs(local_pos), _MIN_SPREAD)
            self._position_drift_pct = abs(exchange_pos - local_pos) / ref
            if self._position_drift_pct > self.config.position_drift_soft_pause_pct:
                logger.warning(
                    "Position drift %.4f%% exceeds threshold — auto-correcting: "
                    "local=%.8f -> exchange=%.8f",
                    float(self._position_drift_pct * _100), float(local_pos), float(exchange_pos),
                )
                self._position_base = exchange_pos
                if self._is_perp and pos is not None:
                    _xchg_entry = _ZERO
                    for _ea in ("entry_price", "avg_entry_price", "average_price"):
                        _ev = getattr(pos, _ea, None)
                        if _ev is not None:
                            try:
                                _xchg_entry = to_decimal(_ev)
                            except (ValueError, TypeError, ArithmeticError):
                                pass
                            if _xchg_entry > _ZERO:
                                break
                    if _xchg_entry > _ZERO:
                        logger.info(
                            "Position drift recon: also adopting exchange avg_entry_price=%.8f (was %.8f)",
                            float(_xchg_entry), float(self._avg_entry_price),
                        )
                        self._avg_entry_price = _xchg_entry
                self._save_daily_state(force=True)
                _cooldown_s = float(getattr(self.config, "drift_escalation_cooldown_s", 900))
                _threshold = int(getattr(self.config, "drift_escalation_count", 5))
                _last_ts = getattr(self, "_last_drift_correction_ts", 0.0)
                if now_ts - _last_ts >= _cooldown_s:
                    self._last_drift_correction_ts = now_ts
                    self._position_drift_correction_count += 1
                    if self._position_drift_correction_count == 1:
                        self._first_drift_correction_ts = now_ts
                    elif self._position_drift_correction_count >= _threshold:
                        if now_ts - self._first_drift_correction_ts < 3600:
                            logger.error(
                                "Position drift corrected %d times in %.0fs — HARD_STOP",
                                self._position_drift_correction_count,
                                now_ts - self._first_drift_correction_ts,
                            )
                            self._ops_guard.force_hard_stop("position_drift_repeated")
            else:
                self._position_drift_correction_count = 0
            self._position_recon_fail_count = 0
            if getattr(self, "_startup_recon_soft_pause", False):
                self._startup_recon_soft_pause = False
                logger.info("Periodic reconciliation succeeded — clearing startup recon SOFT_PAUSE")
        except Exception:
            self._position_recon_fail_count += 1
            if self._position_recon_fail_count <= 3:
                logger.warning("Position reconciliation failed (%d consecutive) for %s",
                               self._position_recon_fail_count, self.config.trading_pair, exc_info=True)
            else:
                logger.error("Position reconciliation failing repeatedly (%d) for %s — position may be out of sync",
                             self._position_recon_fail_count, self.config.trading_pair, exc_info=True)

    _STARTUP_SYNC_MAX_RETRIES: int = 10
    _STARTUP_RECON_MAX_ATTEMPTS: int = 3
    _STARTUP_RECON_BACKOFF_DELAYS: tuple[float, ...] = (2.0, 4.0, 8.0)

    def _run_startup_position_sync(self) -> None:
        """On first tick, query the exchange for actual position and adopt it.

        Covers two critical scenarios:
        1. Cross-day restart where daily_state.json day_key doesn't match
           (position_base was already carried forward, but may be stale).
        2. Crash/kill where daily_state.json was never written or is outdated.

        If exchange reports a position that differs from local state, the
        exchange value wins — because the exchange is the source of truth and
        an untracked position can lead to liquidation.

        Retries up to _STARTUP_SYNC_MAX_RETRIES ticks if the connector is not
        ready yet. Blocks order placement via SOFT_PAUSE until sync succeeds.

        Exchange reconciliation retries with exponential backoff (2s, 4s, 8s).
        If all reconciliation attempts fail, enters SOFT_PAUSE instead of
        HARD_STOP so periodic reconciliation can eventually recover.
        """
        if self._startup_position_sync_done:
            return
        if not bool(getattr(self.config, "startup_position_sync", True)):
            self._startup_position_sync_done = True
            logger.info("Startup position sync disabled by config")
            return
        provider = getattr(self, "market_data_provider", None)
        now_ts = float(provider.time()) if provider is not None else float(_time_mod.time())
        if self._startup_sync_first_ts <= 0:
            self._startup_sync_first_ts = now_ts
        # Respect backoff delay between reconciliation attempts
        next_retry_ts = getattr(self, "_startup_recon_next_retry_ts", 0.0)
        if next_retry_ts > 0 and now_ts < next_retry_ts:
            return
        if now_ts - self._startup_sync_first_ts >= float(getattr(self.config, "startup_sync_timeout_s", 180.0)):
            self._startup_position_sync_done = True
            self._ops_guard.force_hard_stop("startup_sync_timeout")
            logger.error(
                "Startup position sync TIMED OUT after %.0fs (retries=%d). HARD_STOP activated.",
                now_ts - self._startup_sync_first_ts,
                self._startup_sync_retries,
            )
            return
        connector = self._connector()
        if connector is None:
            self._startup_sync_retries += 1
            if self._startup_sync_retries >= self._STARTUP_SYNC_MAX_RETRIES:
                self._startup_position_sync_done = True
                self._startup_recon_soft_pause = True
                logger.error(
                    "Startup position sync FAILED after %d retries: connector never became available. "
                    "SOFT_PAUSE until periodic reconciliation succeeds.",
                    self._startup_sync_retries,
                )
            else:
                logger.warning(
                    "Startup position sync deferred: connector not available (attempt %d/%d)",
                    self._startup_sync_retries, self._STARTUP_SYNC_MAX_RETRIES,
                )
            return
        recon_attempt = int(getattr(self, "_startup_recon_attempt", 0))
        try:
            exchange_pos: Decimal | None = None
            if self._is_perp:
                pos_fn = getattr(connector, "get_position", None) or getattr(connector, "account_positions", None)
                if callable(pos_fn):
                    try:
                        pos = pos_fn(self.config.trading_pair)
                    except TypeError:
                        pos = pos_fn()
                    if hasattr(pos, "amount"):
                        exchange_pos = to_decimal(pos.amount)
                        try:
                            entry_px = getattr(pos, "entry_price", None) or getattr(pos, "avg_entry_price", None)
                            entry_px_d = to_decimal(entry_px) if entry_px is not None else _ZERO
                            if entry_px_d > _ZERO:
                                if self._avg_entry_price <= _ZERO:
                                    self._avg_entry_price = entry_px_d
                                else:
                                    drift = abs(self._avg_entry_price - entry_px_d) / max(entry_px_d, _MIN_SPREAD)
                                    if drift > Decimal("0.001"):
                                        self._avg_entry_price = entry_px_d
                        except Exception:
                            logger.debug("Entry price extraction failed", exc_info=True)
                    elif isinstance(pos, dict):
                        entry = pos.get(self.config.trading_pair, {})
                        exchange_pos = to_decimal(entry.get("amount", 0)) if isinstance(entry, dict) else None
            else:
                exchange_pos = self._compute_total_base_with_locked(connector)
            if exchange_pos is None:
                self._startup_sync_retries += 1
                if self._startup_sync_retries >= self._STARTUP_SYNC_MAX_RETRIES:
                    self._startup_position_sync_done = True
                    self._startup_recon_soft_pause = True
                    logger.error(
                        "Startup position sync FAILED: could not read exchange position after %d attempts. "
                        "SOFT_PAUSE until periodic reconciliation succeeds.",
                        self._startup_sync_retries,
                    )
                else:
                    logger.warning("Startup position sync: could not read exchange position (attempt %d/%d)", self._startup_sync_retries, self._STARTUP_SYNC_MAX_RETRIES)
                return
            self._startup_position_sync_done = True
            local_pos = self._position_base
            if exchange_pos == local_pos:
                logger.info(
                    "Startup position sync OK: local=%.8f matches exchange",
                    float(local_pos),
                )
                return
            if exchange_pos == _ZERO and local_pos == _ZERO:
                return
            ref = max(abs(exchange_pos), abs(local_pos), _MIN_SPREAD)
            drift_pct = abs(exchange_pos - local_pos) / ref
            logger.warning(
                "STARTUP POSITION SYNC: adopting exchange position. "
                "local=%.8f -> exchange=%.8f (drift=%.4f%%)",
                float(local_pos), float(exchange_pos), float(drift_pct * _100),
            )
            if local_pos == _ZERO and exchange_pos != _ZERO:
                logger.warning(
                    "ORPHAN POSITION DETECTED on exchange (%.8f %s). "
                    "Bot had no local record. Adopting to prevent untracked liquidation risk.",
                    float(exchange_pos), self.config.trading_pair,
                )
            self._position_base = exchange_pos
            if self._avg_entry_price == _ZERO and exchange_pos != _ZERO:
                mid = self._get_reference_price()
                if mid > _ZERO:
                    self._avg_entry_price = mid
                    logger.info("Startup sync: avg_entry_price set to current reference price %.2f (no prior entry price)", float(mid))
            self._position_drift_pct = drift_pct
            self._save_daily_state(force=True)
        except Exception:
            self._startup_sync_retries += 1
            self._startup_recon_attempt = recon_attempt + 1
            if recon_attempt + 1 >= self._STARTUP_RECON_MAX_ATTEMPTS:
                self._startup_position_sync_done = True
                self._startup_recon_soft_pause = True
                logger.error(
                    "Startup position reconciliation FAILED after %d attempts with backoff. "
                    "SOFT_PAUSE until periodic reconciliation succeeds.",
                    recon_attempt + 1,
                    exc_info=True,
                )
            else:
                delay_idx = min(recon_attempt, len(self._STARTUP_RECON_BACKOFF_DELAYS) - 1)
                delay = self._STARTUP_RECON_BACKOFF_DELAYS[delay_idx]
                self._startup_recon_next_retry_ts = now_ts + delay
                logger.warning(
                    "Startup position sync failed for %s (attempt %d/%d, retry in %.0fs)",
                    self.config.trading_pair, recon_attempt + 1,
                    self._STARTUP_RECON_MAX_ATTEMPTS, delay,
                    exc_info=True,
                )
        finally:
            if self._startup_position_sync_done and not self._startup_orphan_check_done:
                self._startup_orphan_check_done = True
                canceled = self._cancel_orphan_orders_on_startup()
                if canceled > 0:
                    logger.warning(
                        "Startup orphan order cleanup canceled %d restored order(s) for %s; "
                        "fresh runtime executors will re-quote on the next tick.",
                        canceled,
                        self.config.trading_pair,
                    )
                else:
                    logger.info(
                        "Startup orphan order cleanup found no restored orders for %s",
                        self.config.trading_pair,
                    )
                _init_rg = getattr(self, "_init_recovery_guard", None)
                if callable(_init_rg):
                    _init_rg()

    def _init_recovery_guard(self) -> None:
        """Create a PositionRecoveryGuard if a non-zero position exists with no executor."""
        if not getattr(self.config, "position_recovery_enabled", True):
            return
        if self._recovery_guard is not None:
            return
        if self._recovery_close_emitted:
            return
        if abs(self._position_base) <= _BALANCE_EPSILON:
            return
        try:
            active_executors = self.filter_executors(
                executors=self.executors_info,
                filter_func=lambda x: getattr(x, "is_active", False),
            )
        except Exception:
            active_executors = [
                x for x in list(getattr(self, "executors_info", []) or [])
                if getattr(x, "is_active", False)
            ]
        if active_executors:
            logger.info(
                "Recovery guard skipped: %d active executor(s) already manage %s",
                len(active_executors), self.config.trading_pair,
            )
            return

        tbc = getattr(self.config, "triple_barrier_config", None)
        sl_pct = getattr(tbc, "stop_loss", None) if tbc else None
        tp_pct = getattr(tbc, "take_profit", None) if tbc else None
        time_limit = getattr(tbc, "time_limit", None) if tbc else None
        if sl_pct is not None:
            sl_pct = Decimal(str(sl_pct))
        if tp_pct is not None:
            tp_pct = Decimal(str(tp_pct))
        if time_limit is not None:
            time_limit = int(time_limit)

        has_sl = sl_pct is not None and sl_pct > _ZERO and self._avg_entry_price > _ZERO
        has_tp = tp_pct is not None and tp_pct > _ZERO and self._avg_entry_price > _ZERO
        has_time = time_limit is not None and time_limit > 0
        if not (has_sl or has_tp or has_time):
            logger.error(
                "Recovery guard has NO active barriers (SL=%s TP=%s time_limit=%s entry=%.2f) "
                "— orphaned position %.8f %s is UNPROTECTED. "
                "Configure stop_loss/take_profit/time_limit in triple_barrier_config.",
                sl_pct, tp_pct, time_limit, float(self._avg_entry_price),
                float(self._position_base), self.config.trading_pair,
            )

        from controllers.position_recovery import PositionRecoveryGuard

        now_ts = _time_mod.time()
        persisted_fill_ts = float(getattr(self, "_last_fill_ts", 0.0) or 0.0)
        fill_ts = persisted_fill_ts if persisted_fill_ts > 0 else now_ts

        self._recovery_guard = PositionRecoveryGuard(
            position_base=self._position_base,
            avg_entry_price=self._avg_entry_price,
            stop_loss_pct=sl_pct,
            take_profit_pct=tp_pct,
            time_limit_s=time_limit,
            last_fill_ts=fill_ts,
            connector_name=str(getattr(self.config, "connector_name", "")),
            trading_pair=str(self.config.trading_pair),
            leverage=int(getattr(self.config, "leverage", 1)),
        )
        logger.warning(
            "RECOVERY GUARD ACTIVATED: pair=%s position=%.8f entry=%.2f "
            "SL=%.2f TP=%.2f time_limit=%s last_fill_ts=%.0f (persisted=%s)",
            self.config.trading_pair,
            float(self._position_base),
            float(self._avg_entry_price),
            float(self._recovery_guard.sl_price or 0),
            float(self._recovery_guard.tp_price or 0),
            time_limit,
            self._recovery_guard.last_fill_ts,
            persisted_fill_ts > 0,
        )

