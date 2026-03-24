"""Startup / initialisation mixin for SharedRuntimeKernel.

Extracts pre-flight, recovery-guard, history-seed, fee-resolution and
orphan-order-cleanup logic that runs once (or early) during controller
boot so that the main kernel file stays focused on tick-level execution.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time as _time_mod
from decimal import Decimal
from typing import Any

from controllers.runtime.kernel.config import _ZERO, _BALANCE_EPSILON, _canonical_connector_name
from platform_lib.execution.fee_provider import FeeResolver
from platform_lib.market_data.market_history_policy import runtime_seed_policy, status_meets_policy
from platform_lib.market_data.market_history_provider_impl import MarketHistoryProviderImpl
from platform_lib.market_data.market_history_types import MarketBarKey
from platform_lib.core.utils import to_decimal

logger = logging.getLogger(__name__)


class StartupMixin:

    # ------------------------------------------------------------------
    # Pre-flight / hot-path
    # ------------------------------------------------------------------

    def _preflight_hot_path(self, now: float) -> None:
        """Only keep cheap or hard-veto work on the execution-critical path."""
        self._expire_external_intent_overrides(now)
        self._runtime_adapter.refresh_connector_cache()
        if not self._startup_position_sync_done:
            self._run_startup_position_sync()
        # Fee resolution can be a hard veto; ensure we bootstrap it before quoting.
        if not self._fee_resolved or self._fee_resolution_error:
            self._ensure_fee_config(now)
        if self._protective_stop is not None:
            self._protective_stop.update(self._position_base, self._avg_entry_price)
            if self._protective_stop.placement_failure_escalation and abs(self._position_base) > _ZERO:
                logger.error(
                    "PROTECTIVE_STOP_ESCALATION: stop placement failed %d+ times "
                    "with open position — adding soft_pause reason",
                    self._protective_stop._consecutive_placement_failures,
                )
                self._ops_guard.force_hard_stop("protective_stop_unprotected")
        if self._recovery_guard is not None:
            self._check_recovery_guard(now)

    # ------------------------------------------------------------------
    # Recovery guard
    # ------------------------------------------------------------------

    def _check_recovery_guard(self, now: float) -> None:
        """Tick-level evaluation of the position recovery guard."""
        guard = self._recovery_guard
        if guard is None or not guard.active:
            return

        if abs(self._position_base) <= _BALANCE_EPSILON:
            guard.deactivate("position_flat")
            self._recovery_guard = None
            return

        try:
            active_executors = self.filter_executors(
                executors=self.executors_info,
                filter_func=lambda x: getattr(x, "is_active", False),
            )
        except Exception:
            active_executors = []
        if active_executors:
            guard.deactivate("executor_took_over")
            self._recovery_guard = None
            return

        if self._recovery_close_emitted:
            return

        mid = self._get_reference_price()
        if mid <= _ZERO:
            return

        trigger = guard.check(mid, now)
        if trigger is None:
            return

        unrealized_pnl = (mid - guard.avg_entry_price) * guard.position_base
        logger.warning(
            "RECOVERY GUARD TRIGGERED: reason=%s pair=%s mid=%.2f entry=%.2f "
            "position=%.8f unrealized_pnl=%.4f",
            trigger, guard.trading_pair, float(mid),  # float: log-formatting
            float(guard.avg_entry_price), float(guard.position_base),  # float: log-formatting
            float(unrealized_pnl),  # float: log-formatting
        )
        guard.mark_close_triggered()
        self._recovery_close_emitted = True

    # ------------------------------------------------------------------
    # History provider / seed helpers
    # ------------------------------------------------------------------

    def _history_provider_enabled(self) -> bool:
        return str(os.getenv("HB_HISTORY_PROVIDER_ENABLED", "false")).strip().lower() in {"1", "true", "yes", "on"}

    def _history_seed_enabled(self) -> bool:
        return str(os.getenv("HB_HISTORY_SEED_ENABLED", "false")).strip().lower() in {"1", "true", "yes", "on"}

    def _get_history_provider(self):
        if self._history_provider is None and (self._history_provider_enabled() or self._history_seed_enabled()):
            self._history_provider = MarketHistoryProviderImpl()
        return self._history_provider

    def _required_seed_bars(self) -> int:
        bot_periods = [
            int(getattr(self.config, "ema_period", 0) or 0),
            int(getattr(self.config, "atr_period", 0) or 0) + 1,
            int(getattr(self.config, "bot7_bb_period", 0) or 0),
            int(getattr(self.config, "bot7_rsi_period", 0) or 0),
            int(getattr(self.config, "bot7_adx_period", 0) or 0) * 2,
        ]
        required = max([period for period in bot_periods if period > 0] or [30])
        return max(5, required + 5)

    def _history_seed_policy(self):
        return runtime_seed_policy(default_min_bars=self._required_seed_bars())

    def _ensure_price_sampler_started(self) -> None:
        """Start (or restart) the background price-sampling coroutine.

        The coroutine polls every second and records a sample into
        ``_price_buffer`` whenever the price changes, giving effectively
        live (tick-resolution) OHLC bar updates without flooding the buffer
        with duplicate values.
        """
        task = self._price_sampler_task
        if task is not None and not task.done():
            return
        try:
            loop = asyncio.get_event_loop()
            self._price_sampler_task = loop.create_task(self._run_price_sample_loop())
        except RuntimeError:
            pass

    async def _run_price_sample_loop(self) -> None:
        """Background loop: capture every price change into the price buffer.

        Polls every 1 second (matching the HB asyncio clock cadence).  A new
        sample is only recorded when the price differs from the last recorded
        value, so the buffer receives one entry per distinct price tick rather
        than one per fixed interval.  This gives accurate intra-minute OHLC
        highs and lows while respecting the configured ``price_buffer_source``
        ('mid', 'mark', or 'last_trade').
        """
        _last_price: Decimal = _ZERO
        while True:
            await asyncio.sleep(1)
            try:
                price = self._get_price_for_buffer()
                if price > _ZERO and price != _last_price:
                    now = float(self.market_data_provider.time())
                    self._price_buffer.add_sample(now, price)
                    _last_price = price
            except Exception:
                pass  # tick-level price sampling — non-critical

    def _maybe_seed_price_buffer(self, now: float) -> None:
        if self._history_seed_attempted or not self._history_seed_enabled():
            return
        self._history_seed_attempted = True
        provider = self._get_history_provider()
        if provider is None:
            self._history_seed_status = "disabled"
            self._history_seed_reason = "provider_unavailable"
            return
        connector_name = _canonical_connector_name(str(getattr(self.config, "connector_name", "") or "").strip())
        if not connector_name:
            self._history_seed_status = "empty"
            self._history_seed_reason = "connector_name_missing"
            return
        trading_pair = str(getattr(self.config, "trading_pair", "") or "").strip()
        policy = self._history_seed_policy()
        source_order = list(policy.preferred_sources or ["quote_mid"])
        if not bool(policy.allow_fallback):
            source_order = source_order[:1]
        started = _time_mod.perf_counter()
        try:
            status = None
            for source in source_order:
                self._price_buffer.seed_bars([], reset=True)
                attempt_status = provider.seed_price_buffer(
                    self._price_buffer,
                    MarketBarKey(
                        connector_name=connector_name,
                        trading_pair=trading_pair,
                        bar_source=source,
                    ),
                    bars_needed=int(policy.min_bars_before_trading),
                    now_ms=int(now * 1000.0),
                )
                status = attempt_status
                if status_meets_policy(attempt_status, policy):
                    break
            if status is None:
                self._history_seed_status = "empty"
                self._history_seed_reason = "no_history_sources_attempted"
                return
            if not status_meets_policy(status, policy):
                self._price_buffer.seed_bars([], reset=True)
            self._history_seed_latency_ms = (_time_mod.perf_counter() - started) * 1000.0
            self._history_seed_status = str(status.status)
            self._history_seed_reason = str(status.degraded_reason or "")
            self._history_seed_source = str(status.source_used or "")
            self._history_seed_bars = int(status.bars_returned or 0)
            logger.info(
                "History seed result status=%s bars=%s source=%s latency_ms=%.1f reason=%s pair=%s",
                self._history_seed_status,
                self._history_seed_bars,
                self._history_seed_source or "none",
                self._history_seed_latency_ms,
                self._history_seed_reason or "none",
                self.config.trading_pair,
            )
        except Exception as exc:
            self._history_seed_latency_ms = (_time_mod.perf_counter() - started) * 1000.0
            self._history_seed_status = "degraded"
            self._history_seed_reason = str(exc)
            logger.warning(
                "History seed failed for %s; continuing with live warmup.",
                self.config.trading_pair,
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # Orphan order cleanup
    # ------------------------------------------------------------------

    def _cancel_orphan_orders_on_startup(self) -> int:
        """Cancel open orders that have no owning executor after restart.

        Works uniformly for both paper (bridged) and live connectors.
        When active executors exist, only cleans up orders older than
        2x the executor refresh time to avoid cancelling managed orders.
        """
        try:
            active_executors = self.filter_executors(
                executors=self.executors_info,
                filter_func=lambda x: getattr(x, "is_active", False),
            )
        except Exception:
            active_executors = [x for x in list(getattr(self, "executors_info", []) or []) if getattr(x, "is_active", False)]

        has_active = bool(active_executors)
        executor_order_ids: set[str] = set()
        if has_active:
            for executor in active_executors:
                for attr in ("order_id", "close_order_id"):
                    oid = str(getattr(executor, attr, "") or "")
                    if oid:
                        executor_order_ids.add(oid)
                for ao in getattr(executor, "active_orders", []) or []:
                    oid = str(getattr(ao, "client_order_id", "") or getattr(ao, "order_id", "") or "")
                    if oid:
                        executor_order_ids.add(oid)

        try:
            connector = self._connector()
            open_orders_fn = getattr(connector, "get_open_orders", None)
            if not callable(open_orders_fn):
                return 0
            connector_name = str(getattr(self.config, "connector_name", "") or "")
            trading_pair = str(self.config.trading_pair)
            strategy = getattr(self, "strategy", None) or getattr(self, "_strategy", None)
            cancel_fn = getattr(strategy, "cancel", None) if strategy is not None else None
            if not callable(cancel_fn):
                return 0

            _levels = getattr(self, "_runtime_levels", None)
            max_age_s = float(getattr(_levels, "executor_refresh_time", 60) or 60) * 2.0
            now_epoch = float(self.market_data_provider.time()) if hasattr(self, "market_data_provider") else 0.0

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
                if order_id in executor_order_ids:
                    continue
                if has_active and now_epoch > 0:
                    created_ts = float(
                        getattr(order, "creation_timestamp", 0)
                        or getattr(order, "created_at_ns", 0) / 1e9
                        or 0
                    )
                    if created_ts > 0 and (now_epoch - created_ts) < max_age_s:
                        continue
                cancel_ids.append(order_id)
            canceled = 0
            for order_id in cancel_ids:
                try:
                    cancel_fn(connector_name, trading_pair, order_id)
                    canceled += 1
                except Exception:
                    logger.debug("Orphan cancel skipped order_id=%s", order_id, exc_info=True)
            if canceled > 0:
                self._recently_issued_levels = {}
            return canceled
        except Exception:
            logger.debug("Startup orphan order cleanup failed for %s", self.config.trading_pair, exc_info=True)
            return 0

    # ------------------------------------------------------------------
    # Fee resolution
    # ------------------------------------------------------------------

    def _ensure_fee_config(self, now_ts: float) -> None:
        mode = self.config.fee_mode
        connector = self._connector()
        canonical_name = _canonical_connector_name(self.config.connector_name)

        # Manual/project modes are static after first successful resolution.
        if mode in {"manual", "project"} and self._fee_resolved:
            return
        # In auto mode, allow periodic refresh attempts until API source is obtained.
        if mode == "auto" and self._fee_resolved and self._fee_source.startswith("api:"):
            return
        if self._last_fee_resolve_ts > 0 and (now_ts - self._last_fee_resolve_ts) < self.config.fee_refresh_s:
            return
        self._last_fee_resolve_ts = now_ts

        if mode == "manual":
            self._fee_source = "manual:spot_fee_pct"
            self._maker_fee_pct = to_decimal(self.config.spot_fee_pct)
            self._taker_fee_pct = to_decimal(self.config.spot_fee_pct)
            self._fee_resolved = self._maker_fee_pct > 0
            if not self._fee_resolved:
                self._fee_resolution_error = "manual_fee_non_positive"
            else:
                self._fee_resolution_error = ""
            return

        if mode == "auto":
            live_api = FeeResolver.from_exchange_api(connector, self.config.connector_name, self.config.trading_pair)
            # For framework paper connectors, credentials may only exist on the base connector.
            if live_api is None and self.config.connector_name.endswith("_paper_trade"):
                try:
                    base_connector = self.market_data_provider.get_connector(canonical_name)
                except Exception:
                    base_connector = None
                live_api = FeeResolver.from_exchange_api(base_connector, canonical_name, self.config.trading_pair)
            if live_api is not None:
                self._maker_fee_pct = live_api.maker
                self._taker_fee_pct = live_api.taker
                self._fee_source = live_api.source
                self._fee_resolved = True
                self._fee_resolution_error = ""
                return
            runtime = FeeResolver.from_connector_runtime(connector, self.config.trading_pair)
            if runtime is not None:
                self._maker_fee_pct = runtime.maker
                self._taker_fee_pct = runtime.taker
                self._fee_source = runtime.source
                self._fee_resolved = True
                self._fee_resolution_error = ""
                return

        profile = FeeResolver.from_project_profile(self.config.connector_name, self.config.fee_profile)
        if profile is not None:
            self._maker_fee_pct = profile.maker
            self._taker_fee_pct = profile.taker
            self._fee_source = profile.source
            self._fee_resolved = True
            self._fee_resolution_error = ""
            return

        if self._maker_fee_pct > 0:
            self._fee_source = "manual_fallback:spot_fee_pct"
            self._taker_fee_pct = self._maker_fee_pct
            self._fee_resolved = not self.config.require_fee_resolution
            if self.config.require_fee_resolution:
                self._fee_resolution_error = "resolver_failed_with_require_true"
            else:
                self._fee_resolution_error = ""
        else:
            self._fee_resolution_error = "no_fee_available"
            logger.warning(
                "Fee resolution exhausted all sources — maker_fee_pct=0 for %s %s. "
                "Edge gating will use zero fee cost floor.",
                self.config.connector_name, self.config.trading_pair,
            )
        return
