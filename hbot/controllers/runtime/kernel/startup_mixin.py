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
from platform_lib.market_data.ccxt_ohlcv_bar_reader import ccxt_rest_bar_reader, _pair_to_ccxt_symbol
from controllers.backtesting.data_store import resolve_data_path
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
            self._history_provider = MarketHistoryProviderImpl(rest_reader=ccxt_rest_bar_reader)
        return self._history_provider

    def _required_seed_bars(self) -> int:
        bot_periods = [
            int(getattr(self.config, "ema_period", 0) or 0),
            int(getattr(self.config, "atr_period", 0) or 0) + 1,
            int(getattr(self.config, "bot7_bb_period", 0) or 0),
            int(getattr(self.config, "bot7_rsi_period", 0) or 0),
            int(getattr(self.config, "bot7_adx_period", 0) or 0) * 2,
            int(getattr(self.config, "pb_bb_period", 0) or 0),
            int(getattr(self.config, "pb_rsi_period", 0) or 0),
            int(getattr(self.config, "pb_adx_period", 0) or 0) * 2,
            int(getattr(self.config, "pb_trend_sma_period", 0) or 0),
        ]
        required = max([period for period in bot_periods if period > 0] or [30])
        resolution = getattr(self, "_resolution_minutes", 1)
        return max(5, (required + 5) * resolution)

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
        if self._history_seed_attempted:
            return
        self._history_seed_attempted = True
        started = _time_mod.perf_counter()

        # --- Phase 1: parquet + API bridge (always attempted) -------------
        parquet_seeded = self._try_seed_from_parquet(now)
        if parquet_seeded:
            self._history_seed_latency_ms = (_time_mod.perf_counter() - started) * 1000.0
            return

        # --- Phase 2: full REST fetch (fallback) --------------------------
        rest_seeded = self._try_seed_from_rest(now)
        if rest_seeded:
            self._history_seed_latency_ms = (_time_mod.perf_counter() - started) * 1000.0
            return

        # --- Both paths failed — bot must NOT trade on empty indicators ---
        self._history_seed_latency_ms = (_time_mod.perf_counter() - started) * 1000.0
        if self._history_seed_status not in ("rejected",):
            self._history_seed_status = "failed"
        logger.error(
            "SEED FAILED for %s — no gapless history available. "
            "Bot will not trade until buffer warms up from live ticks. "
            "status=%s reason=%s pair=%s",
            getattr(self.config, "connector_name", "?"),
            self._history_seed_status,
            self._history_seed_reason,
            getattr(self.config, "trading_pair", "?"),
        )

    def seed_ok(self) -> bool:
        """Return True only if the price buffer was seeded with gapless data."""
        return self._history_seed_status == "ok"

    def _try_seed_from_rest(self, now: float) -> bool:
        """Fetch full history from exchange REST API and validate for gaps."""
        if not self._history_seed_enabled():
            self._history_seed_reason = "rest_seed_disabled"
            return False
        connector_name = _canonical_connector_name(str(getattr(self.config, "connector_name", "") or "").strip())
        trading_pair = str(getattr(self.config, "trading_pair", "") or "").strip()
        if not connector_name or not trading_pair:
            self._history_seed_reason = "connector_or_pair_missing"
            return False

        bars_needed = self._required_seed_bars()
        now_ms = int(now * 1000.0)
        try:
            df = self._fetch_bridge_bars(
                connector_name, trading_pair,
                since_ms=now_ms - bars_needed * 60_000,
                until_ms=now_ms,
            )
        except Exception as exc:
            self._history_seed_reason = f"rest_fetch_error: {exc}"
            logger.warning("REST seed fetch failed for %s: %s", trading_pair, exc)
            return False

        if df is None or df.empty:
            self._history_seed_reason = "rest_returned_empty"
            return False

        df = df.tail(bars_needed).reset_index(drop=True)
        return self._validate_and_seed(df, now_ms, source_label="rest_api")

    # ------------------------------------------------------------------
    # Shared validation + seeding
    # ------------------------------------------------------------------

    def _validate_and_seed(self, df, now_ms: int, source_label: str) -> bool:
        """Validate DataFrame has zero internal gaps and seed PriceBuffer.

        Checks:
        1. Every consecutive bar is exactly 60_000 ms apart (no holes).
        2. Last bar is within 2 minutes of *now_ms* (trailing freshness).
        3. All OHLC values are finite and positive.

        Returns True if seeding succeeded.
        """
        import pandas as pd
        trading_pair = str(getattr(self.config, "trading_pair", "") or "")

        df = df.sort_values("timestamp_ms").drop_duplicates(subset=["timestamp_ms"]).reset_index(drop=True)
        ts = df["timestamp_ms"].values
        if len(ts) < 2:
            self._history_seed_status = "rejected"
            self._history_seed_reason = f"{source_label}_too_few_bars"
            return False

        # Zero-gap check: every consecutive pair must be exactly 60s apart
        deltas_ms = ts[1:] - ts[:-1]
        max_delta_ms = int(deltas_ms.max())
        if max_delta_ms > 60_000:
            gap_min = max_delta_ms // 60_000
            logger.warning(
                "Seed REJECTED (%s) for %s: internal gap of %d min",
                source_label, trading_pair, gap_min,
            )
            self._history_seed_status = "rejected"
            self._history_seed_reason = f"{source_label}_gap_{gap_min}m"
            return False

        # Trailing freshness: last bar within 2 min of now
        trailing_min = (now_ms - int(ts[-1])) // 60_000
        if trailing_min > 2:
            logger.warning(
                "Seed REJECTED (%s) for %s: trailing gap %d min",
                source_label, trading_pair, trailing_min,
            )
            self._history_seed_status = "rejected"
            self._history_seed_reason = f"{source_label}_trailing_{trailing_min}m"
            return False

        # Convert to MinuteBar and seed
        from controllers.price_buffer import MinuteBar
        bars = []
        for row in df.itertuples(index=False):
            bars.append(MinuteBar(
                ts_minute=int(row.timestamp_ms) // 1000,
                open=Decimal(str(row.open)),
                high=Decimal(str(row.high)),
                low=Decimal(str(row.low)),
                close=Decimal(str(row.close)),
            ))

        if not bars:
            return False

        seeded = self._price_buffer.seed_bars(bars, reset=True)
        self._history_seed_status = "ok"
        self._history_seed_source = source_label
        self._history_seed_bars = seeded
        self._history_seed_reason = ""
        logger.info(
            "Seed OK (%s) for %s: %d gapless bars",
            source_label, trading_pair, seeded,
        )
        return True

    def _try_seed_from_parquet(self, now: float) -> bool:
        """Seed PriceBuffer from local parquet + API bridge for the gap.

        Mirrors the ML feature service pattern: load bulk history from
        parquet (instant), then fetch only the small gap since the last
        parquet row from the exchange API.  Returns True if seeding
        succeeded with zero internal gaps.
        """
        base_dir = os.getenv("HISTORICAL_DATA_DIR", "data/historical")
        connector_name = _canonical_connector_name(
            str(getattr(self.config, "connector_name", "") or "").strip()
        )
        trading_pair = str(getattr(self.config, "trading_pair", "") or "").strip()
        if not connector_name or not trading_pair:
            return False

        parquet_path = resolve_data_path(connector_name, trading_pair, "1m", base_dir)
        if not parquet_path.exists():
            logger.debug("No parquet at %s for %s — skipping parquet seed", parquet_path, trading_pair)
            return False

        try:
            import pandas as pd
            df = pd.read_parquet(parquet_path)
            if df.empty:
                return False
        except Exception as exc:
            logger.debug("Parquet read failed for %s: %s", trading_pair, exc)
            return False

        bars_needed = self._required_seed_bars()
        df = df.sort_values("timestamp_ms").tail(bars_needed).reset_index(drop=True)
        last_parquet_ts = int(df["timestamp_ms"].max())
        now_ms = int(now * 1000.0)
        gap_minutes = max(0, (now_ms - last_parquet_ts) // 60_000)

        # Bridge the gap from exchange API if parquet is stale
        source_label = "parquet"
        if gap_minutes > 1:
            try:
                bridge_since_ms = last_parquet_ts - 5 * 60_000  # 5-min overlap for dedup
                bridge_df = self._fetch_bridge_bars(connector_name, trading_pair, bridge_since_ms, now_ms)
                if bridge_df is not None and not bridge_df.empty:
                    parquet_rows = len(df)
                    combined = pd.concat([df, bridge_df], ignore_index=True)
                    combined = combined.drop_duplicates(subset=["timestamp_ms"]).sort_values("timestamp_ms")
                    df = combined.tail(bars_needed).reset_index(drop=True)
                    source_label = "parquet_bridge"
                    logger.info(
                        "Parquet+bridge for %s: %d parquet + %d bridge bars, gap was %d min",
                        trading_pair, parquet_rows, len(bridge_df), gap_minutes,
                    )
                else:
                    logger.warning("Bridge returned empty for %s — gap of %d min remains", trading_pair, gap_minutes)
                    self._history_seed_status = "rejected"
                    self._history_seed_reason = f"bridge_empty_gap_{gap_minutes}m"
                    return False
            except Exception as exc:
                logger.warning("Bridge fetch failed for %s: %s", trading_pair, exc)
                self._history_seed_status = "rejected"
                self._history_seed_reason = f"bridge_error_gap_{gap_minutes}m"
                return False

        return self._validate_and_seed(df, now_ms, source_label=source_label)

    def _fetch_bridge_bars(
        self, exchange_id: str, trading_pair: str, since_ms: int, until_ms: int,
    ):
        """Fetch 1m candles from exchange API to bridge the parquet gap."""
        import pandas as pd
        try:
            import ccxt
        except ImportError:
            return None
        exchange_cls = getattr(ccxt, exchange_id, None)
        if exchange_cls is None:
            return None
        ex = exchange_cls({"enableRateLimit": True, "options": {"defaultType": "swap"}})
        symbol = _pair_to_ccxt_symbol(trading_pair, swap=True)

        all_bars: list[list] = []
        cursor_ms = since_ms
        while cursor_ms < until_ms:
            batch = ex.fetch_ohlcv(symbol, "1m", since=cursor_ms, limit=200)
            if not batch:
                break
            all_bars.extend(batch)
            cursor_ms = batch[-1][0] + 60_000
            if len(batch) < 200:
                break
            _time_mod.sleep(0.3)

        if not all_bars:
            return None
        return pd.DataFrame(all_bars, columns=["timestamp_ms", "open", "high", "low", "close", "volume"])

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
