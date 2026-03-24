"""State management mixin for SharedRuntimeKernel.

Extracts state-tracking, daily-rollover, equity/balance helpers,
risk metric queries, and daily-state persistence into a reusable mixin.
"""

from __future__ import annotations

import csv
import json
import logging

try:
    import orjson as _orjson
except ImportError:
    _orjson = None

from collections import deque
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from controllers.analytics.performance_metrics import max_drawdown_with_metadata
from controllers.runtime.core import artifact_namespace as _artifact_namespace
from controllers.runtime.kernel.config import (
    _BALANCE_EPSILON,
    _ONE,
    _ZERO,
    _100,
    _config_is_paper,
)
from controllers.risk_evaluator import RiskEvaluator
from platform_lib.contracts.stream_names import PORTFOLIO_RISK_STREAM
from platform_lib.core.utils import to_decimal

logger = logging.getLogger(__name__)


def _lazy_SharedRuntimeKernel():
    from controllers.shared_runtime_v24 import SharedRuntimeKernel
    return SharedRuntimeKernel


class StateMixin:

    # ------------------------------------------------------------------
    # Daily equity tracking
    # ------------------------------------------------------------------

    def _track_daily_equity(self, equity_quote: Decimal) -> None:
        """Initialize and update daily equity open/peak watermarks."""
        if self._daily_equity_open is None and equity_quote > 0:
            self._daily_equity_open = equity_quote
        if self._daily_equity_peak is None:
            self._daily_equity_peak = equity_quote
        if equity_quote > (self._daily_equity_peak or _ZERO):
            self._daily_equity_peak = equity_quote

    # ------------------------------------------------------------------
    # Reference price / mid price
    # ------------------------------------------------------------------

    def _get_reference_price(self) -> Decimal:
        """Return the reference price used for equity valuation and risk checks.

        Delegates to the adapter's order-book mid price, which is the best
        estimate of the current tradeable price.
        """
        return self._runtime_adapter.get_mid_price()

    # Backwards-compatible alias — callsites being migrated.
    _get_mid_price = _get_reference_price

    def _get_price_for_buffer(self) -> Decimal:
        """Return the price that should be fed into the price buffer.

        Respects ``config.price_buffer_source`` ('mid', 'mark', or 'last_trade').
        Falls back to reference price when the adapter lacks the method (test stubs).
        """
        fn = getattr(self._runtime_adapter, "get_price_for_buffer", None)
        if callable(fn):
            return fn(getattr(self.config, "price_buffer_source", "mid"))
        return self._get_reference_price()

    # ------------------------------------------------------------------
    # Balance / connector helpers
    # ------------------------------------------------------------------

    def _get_balances(self) -> tuple[Decimal, Decimal]:
        return self._runtime_adapter.get_balances()

    def _connector(self):
        return self._runtime_adapter.get_connector()

    def _trading_rule(self):
        return self._runtime_adapter.get_trading_rule()

    def _connector_ready(self) -> bool:
        return self._runtime_adapter.ready()

    def _balances_consistent(self) -> bool:
        return self._runtime_adapter.balances_consistent()

    # ------------------------------------------------------------------
    # Equity / base-pct computation
    # ------------------------------------------------------------------

    def _compute_equity_and_base_pcts(self, mid: Decimal) -> tuple[Decimal, Decimal, Decimal]:
        base_bal, quote_bal = self._get_balances()
        if self._is_perp:
            pos_base = self._position_base if abs(self._position_base) > _BALANCE_EPSILON else base_bal
            pos_gross_base = (
                to_decimal(getattr(self, "_position_gross_base", _ZERO))
                if abs(to_decimal(getattr(self, "_position_gross_base", _ZERO))) > _BALANCE_EPSILON
                else abs(pos_base)
            )
            position_mode = str(getattr(self.config, "position_mode", "ONEWAY") or "ONEWAY").upper()
            if position_mode != "HEDGE":
                pos_gross_base = abs(pos_base)
            equity = quote_bal if quote_bal > _ZERO else abs(pos_base) * mid
            # For paper perps, override with true equity (cash + unrealized PnL) so that
            # the daily_loss_pct risk gate, order sizing, and telemetry all see the correct
            # mark-to-market value rather than the stale cash-only balance.
            _conn = self._connector()
            if _conn is not None and hasattr(_conn, "paper_portfolio_snapshot"):
                try:
                    _psnap = _conn.paper_portfolio_snapshot(mid)
                    if _psnap and (_psnap.get("equity_quote") or _ZERO) > _ZERO:
                        equity = Decimal(str(_psnap["equity_quote"]))
                except Exception:
                    pass  # fall back to quote_bal
            gross_value = abs(pos_base) * mid if position_mode != "HEDGE" else pos_gross_base * mid
            net_value = pos_base * mid
            base_pct_gross = gross_value / equity if equity > _ZERO else _ZERO
            base_pct_net = net_value / equity if equity > _ZERO else _ZERO
            try:
                self._refresh_margin_ratio(mid, pos_base, quote_bal, gross_base=pos_gross_base)
            except TypeError:
                self._refresh_margin_ratio(mid, pos_base, quote_bal)
        else:
            equity = quote_bal + base_bal * mid
            base_pct_gross = (base_bal * mid) / equity if equity > _ZERO else _ZERO
            base_pct_net = base_pct_gross
        if equity <= _ZERO:
            return _ZERO, _ZERO, _ZERO
        return equity, base_pct_gross, base_pct_net

    # ------------------------------------------------------------------
    # Margin ratio
    # ------------------------------------------------------------------

    def _refresh_margin_ratio(
        self,
        mid: Decimal,
        base_bal: Decimal,
        quote_bal: Decimal,
        gross_base: Decimal | None = None,
    ) -> None:
        """Update margin ratio for perp connectors."""
        if not self._is_perp:
            return
        connector = self._connector()
        if connector is None:
            return
        try:
            margin_info = getattr(connector, "get_margin_info", None)
            if callable(margin_info):
                info = margin_info(self.config.trading_pair)
                ratio = getattr(info, "margin_ratio", None)
                if ratio is not None:
                    self._margin_ratio = to_decimal(ratio)
                    return
        except Exception:
            logger.debug("Margin info read failed for %s", self.config.trading_pair, exc_info=True)
        position_notional = max(abs(base_bal), to_decimal(gross_base or _ZERO)) * mid
        if position_notional > _ZERO and quote_bal > _ZERO:
            # margin_ratio = available_margin / required_margin.
            # required_margin = position_notional / leverage (initial margin).
            # Without leverage correction this reads optimistically high at leverage > 1.
            leverage_d = Decimal(max(1, int(self.config.leverage)))
            self._margin_ratio = (quote_bal * leverage_d) / position_notional
        else:
            self._margin_ratio = _ONE

    # ------------------------------------------------------------------
    # Total base with locked
    # ------------------------------------------------------------------

    def _compute_total_base_with_locked(self, connector: Any) -> Decimal:
        """Available base + base locked in open sell orders.

        For spot-style connectors ``get_balance()`` returns *available* balance only,
        excluding base locked in open sell orders. This method adds back the locked
        portion so reconciliation and startup sync see the true total position.
        """
        base_asset = self._runtime_adapter._base_asset
        total = to_decimal(connector.get_balance(base_asset))
        try:
            open_orders_fn = getattr(connector, "get_open_orders", None)
            if callable(open_orders_fn):
                for o in (open_orders_fn() or []):
                    if str(getattr(o, "trading_pair", "")) != self.config.trading_pair:
                        continue
                    side_str = str(getattr(o, "trade_type", None) or getattr(o, "side", None)).lower()
                    if "sell" not in side_str:
                        continue
                    amt = getattr(o, "amount", None) or getattr(o, "quantity", None) or getattr(o, "base_asset_amount", None)
                    if amt is None:
                        continue
                    executed = getattr(o, "executed_amount_base", None) or getattr(o, "filled_amount", None) or getattr(o, "executed_amount", None)
                    remaining = to_decimal(amt) - to_decimal(executed or 0)
                    if remaining > _ZERO:
                        total += remaining
        except Exception:
            logger.debug("Locked-base scan failed for %s", self.config.trading_pair, exc_info=True)
        return total

    # ------------------------------------------------------------------
    # Funding rate
    # ------------------------------------------------------------------

    def _refresh_funding_rate(self, now_ts: float) -> None:
        """Fetch funding rate for perpetual connectors."""
        if "_perpetual" not in self.config.connector_name:
            return
        if now_ts - self._last_funding_rate_ts < self.config.funding_rate_refresh_s:
            return
        self._last_funding_rate_ts = now_ts
        connector = self._connector()
        if connector is None:
            return
        try:
            funding_info = getattr(connector, "get_funding_info", None)
            if callable(funding_info):
                info = funding_info(self.config.trading_pair)
                rate = getattr(info, "rate", None) or getattr(info, "funding_rate", None)
                if rate is not None:
                    self._funding_rate = to_decimal(rate)
                    return
            funding_rates = getattr(connector, "funding_rates", None)
            if isinstance(funding_rates, dict):
                rate = funding_rates.get(self.config.trading_pair)
                if rate is not None:
                    self._funding_rate = to_decimal(rate)
                    return
        except Exception:
            logger.debug("Funding rate fetch failed for %s", self.config.trading_pair)

    # ------------------------------------------------------------------
    # Risk helpers
    # ------------------------------------------------------------------

    def _risk_loss_metrics(self, equity_quote: Decimal) -> tuple[Decimal, Decimal]:
        open_equity = self._daily_equity_open or equity_quote
        peak_equity = self._daily_equity_peak or equity_quote
        daily_loss_pct, drawdown_pct = RiskEvaluator.risk_loss_metrics(
            equity_quote, open_equity, peak_equity,
        )
        # Defense: the paper engine may not settle perp PnL into the cash
        # ledger, causing equity_quote to remain stale.  Use the controller's
        # own PnL tracking as a floor so risk hard-stops still fire.
        realized = to_decimal(getattr(self, "_realized_pnl_today", _ZERO))
        fees = to_decimal(getattr(self, "_fees_paid_today_quote", _ZERO))
        funding = to_decimal(getattr(self, "_funding_cost_today_quote", _ZERO))
        net_pnl = realized - fees - funding
        if net_pnl < _ZERO and open_equity > _ZERO:
            daily_loss_pct = max(daily_loss_pct, abs(net_pnl) / open_equity)
        if net_pnl < _ZERO and peak_equity > _ZERO:
            drawdown_pct = max(drawdown_pct, abs(net_pnl) / peak_equity)
        return daily_loss_pct, drawdown_pct

    def _risk_policy_checks(
        self,
        base_pct: Decimal,
        turnover_x: Decimal,
        projected_total_quote: Decimal,
        daily_loss_pct: Decimal,
        drawdown_pct: Decimal,
    ) -> tuple[list[str], bool]:
        return self._risk_evaluator.risk_policy_checks(
            base_pct=base_pct, turnover_x=turnover_x,
            projected_total_quote=projected_total_quote,
            daily_loss_pct=daily_loss_pct, drawdown_pct=drawdown_pct,
        )

    def _edge_gate_update(
        self,
        now_ts: float,
        net_edge: Decimal,
        pause_threshold: Decimal,
        resume_threshold: Decimal,
    ) -> None:
        self._risk_evaluator.edge_gate_update(now_ts, net_edge, pause_threshold, resume_threshold)
        self._edge_gate_blocked = self._risk_evaluator.edge_gate_blocked

    # ------------------------------------------------------------------
    # Day rollover
    # ------------------------------------------------------------------

    def _maybe_roll_day(self, now_ts: float) -> None:
        dt = datetime.fromtimestamp(now_ts, tz=UTC)
        day_key = dt.strftime("%Y-%m-%d")
        if self._daily_key is None:
            self._daily_key = day_key
            return
        if day_key != self._daily_key:
            try:
                mid = self._get_reference_price()
            except Exception:
                logger.warning("Day rollover: reference price unavailable — deferring rollover")
                return
            if mid <= _ZERO:
                logger.warning("Day rollover: reference_price=%s — deferring rollover", mid)
                return
            try:
                equity_now, _, _ = self._compute_equity_and_base_pcts(mid)
            except Exception:
                logger.warning("Day rollover: equity computation failed — deferring rollover", exc_info=True)
                return
            equity_open = self._daily_equity_open or equity_now
            equity_peak = self._daily_equity_peak or equity_now
            pnl = equity_now - equity_open
            pnl_pct = (pnl / equity_open) if equity_open > 0 else Decimal("0")
            drawdown_pct = (equity_peak - equity_now) / equity_peak if equity_peak > 0 else Decimal("0")

            dd_prices = self._equity_samples_today or [equity_open, equity_now]
            dd_ts = self._equity_sample_ts_today if len(self._equity_sample_ts_today) == len(dd_prices) else None
            dd_meta = max_drawdown_with_metadata(dd_prices, method="percent", timestamps=dd_ts)
            event_ts = datetime.fromtimestamp(now_ts, tz=UTC).isoformat()
            self._csv.log_daily(
                {
                    "bot_variant": self.config.variant,
                    "exchange": self.config.connector_name,
                    "trading_pair": self.config.trading_pair,
                    "state": self._ops_guard.state.value,
                    "equity_open_quote": str(equity_open),
                    "equity_peak_quote": str(equity_peak),
                    "equity_now_quote": str(equity_now),
                    "pnl_quote": str(pnl),
                    "pnl_pct": str(pnl_pct),
                    "drawdown_pct": str(drawdown_pct),
                    "max_drawdown_pct": str(dd_meta.max_drawdown),
                    "max_drawdown_peak_ts": str(dd_meta.peak_ts or ""),
                    "max_drawdown_trough_ts": str(dd_meta.trough_ts or ""),
                    "turnover_x": str(self._traded_notional_today / equity_now) if equity_now > 0 else "0",
                    "fills_count": self._fills_count_today,
                    "fees_paid_today_quote": str(self._fees_paid_today_quote),
                    "funding_cost_today_quote": str(self._funding_cost_today_quote),
                    "realized_pnl_today_quote": str(self._realized_pnl_today),
                    "net_realized_pnl_today_quote": str(self._realized_pnl_today - self._funding_cost_today_quote),
                    "ops_events": "|".join(self._ops_guard.reasons),
                },
                ts=event_ts,
            )
            self._daily_key = day_key
            self._daily_equity_open = equity_now
            self._daily_equity_peak = equity_now
            self._equity_samples_today = []
            self._equity_sample_ts_today = []
            self._traded_notional_today = Decimal("0")
            self._fills_count_today = 0
            self._fees_paid_today_quote = Decimal("0")
            self._fee_rate_mismatch_warned_today = False
            self._funding_cost_today_quote = _ZERO
            self._realized_pnl_today = _ZERO
            self._cancel_events_ts = []
            if (
                self.config.close_position_at_rollover
                and mid > _ZERO
                and abs(self._position_base) * mid > self.config.min_close_notional_quote
            ):
                self._pending_eod_close = True
                logger.info(
                    "EOD close triggered: position_base=%s mid=%s notional=%s",
                    self._position_base, mid, abs(self._position_base) * mid,
                )
            self._save_daily_state(force=True)

    # ------------------------------------------------------------------
    # File paths
    # ------------------------------------------------------------------

    def _daily_state_path(self) -> str:
        from pathlib import Path
        connector_tag = str(self.config.connector_name).replace("_paper_trade", "").replace(" ", "_")
        mode_tag = self.config.bot_mode
        return str(
            Path(self.config.log_dir) / _artifact_namespace(self.config)
            / f"{self.config.instance_name}_{self.config.variant}"
            / f"daily_state_{connector_tag}_{mode_tag}.json"
        )

    def _fills_csv_path(self) -> Path:
        """Return canonical fills.csv path for this instance."""
        csv_logger_dir = getattr(self._csv, "log_dir", None)
        if csv_logger_dir is not None:
            try:
                return Path(str(csv_logger_dir)).expanduser().resolve() / "fills.csv"
            except Exception:
                pass  # fall back to config.log_dir path below
        return (
            Path(self.config.log_dir).expanduser().resolve()
            / _artifact_namespace(self.config)
            / f"{self.config.instance_name}_{self.config.variant}"
            / "fills.csv"
        )

    # ------------------------------------------------------------------
    # Fill cache hydration
    # ------------------------------------------------------------------

    def _hydrate_seen_fill_order_ids_from_csv(self) -> None:
        """Warm restart-time fill cache from fills.csv.

        This cache is used for replay-safety diagnostics and live fill-event dedupe.
        It is intentionally best-effort and never blocks startup.
        """
        fills_path = self._fills_csv_path()
        if not fills_path.exists():
            return
        try:
            order_id_cap = int(getattr(self, "_seen_fill_order_ids_cap", 50_000) or 50_000)
            order_id_cap = max(1_000, order_id_cap)
            event_key_cap = int(getattr(self, "_seen_fill_event_keys_cap", 120_000) or 120_000)
            event_key_cap = max(1_000, event_key_cap)
            seen_order_ids = getattr(self, "_seen_fill_order_ids", None)
            if not isinstance(seen_order_ids, set):
                seen_order_ids = set()
                self._seen_fill_order_ids = seen_order_ids
            seen_order_ids_fifo = getattr(self, "_seen_fill_order_ids_fifo", None)
            if not isinstance(seen_order_ids_fifo, (deque, list)):
                seen_order_ids_fifo = deque()
                self._seen_fill_order_ids_fifo = seen_order_ids_fifo
            seen_event_keys = getattr(self, "_seen_fill_event_keys", None)
            if not isinstance(seen_event_keys, set):
                seen_event_keys = set()
                self._seen_fill_event_keys = seen_event_keys
            seen_event_keys_fifo = getattr(self, "_seen_fill_event_keys_fifo", None)
            if not isinstance(seen_event_keys_fifo, (deque, list)):
                seen_event_keys_fifo = deque()
                self._seen_fill_event_keys_fifo = seen_event_keys_fifo
            order_ids: list[str] = []
            fill_event_keys: list[str] = []
            latest_fill_ts = 0.0
            with fills_path.open("r", newline="", encoding="utf-8") as fp:
                reader = csv.DictReader(fp)
                for row in reader:
                    oid = str(row.get("order_id", "") or "").strip()
                    if oid:
                        order_ids.append(oid)
                    fill_event_key = _lazy_SharedRuntimeKernel()._fill_row_dedupe_key(row)
                    if fill_event_key:
                        fill_event_keys.append(fill_event_key)
                    ts_raw = str(row.get("ts", "") or "").strip()
                    if ts_raw:
                        try:
                            parsed_ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00")).timestamp()
                            latest_fill_ts = max(latest_fill_ts, float(parsed_ts))
                        except Exception:
                            pass  # malformed ts in fills CSV row — skip

            if len(order_ids) > order_id_cap:
                order_ids = order_ids[-order_id_cap:]
            if len(fill_event_keys) > event_key_cap:
                fill_event_keys = fill_event_keys[-event_key_cap:]

            seen_order_ids.clear()
            seen_order_ids_fifo.clear()
            for oid in order_ids:
                if oid in seen_order_ids:
                    continue
                seen_order_ids.add(oid)
                seen_order_ids_fifo.append(oid)
            seen_event_keys.clear()
            seen_event_keys_fifo.clear()
            for event_key in fill_event_keys:
                if event_key in seen_event_keys:
                    continue
                seen_event_keys.add(event_key)
                seen_event_keys_fifo.append(event_key)

            if latest_fill_ts > 0:
                self._last_fill_ts = max(float(getattr(self, "_last_fill_ts", 0.0) or 0.0), latest_fill_ts)

            if seen_order_ids or seen_event_keys:
                logger.info(
                    "Hydrated fill cache: %d unique order_ids, %d unique event_keys from %s (last_fill_ts=%s)",
                    len(seen_order_ids),
                    len(seen_event_keys),
                    fills_path,
                    latest_fill_ts if latest_fill_ts > 0 else "n/a",
                )
        except Exception:
            logger.warning("Failed to hydrate fill cache from %s", fills_path, exc_info=True)

    # ------------------------------------------------------------------
    # Daily state persistence
    # ------------------------------------------------------------------

    def _load_daily_state(self) -> None:
        """Restore daily state from Redis or disk.

        Same-day restart: full state restored (counters, position, equity).
        Cross-day restart: only position_base and avg_entry_price are carried
        forward — daily counters reset on the next _maybe_roll_day call.
        This prevents the bot from "forgetting" an open exchange position
        just because the calendar day rolled.
        """
        data = self._state_store.load()
        if data is None:
            return
        try:
            today = datetime.now(UTC).strftime("%Y-%m-%d")
            saved_position = to_decimal(data.get("position_base", "0"))
            saved_avg_entry = to_decimal(data.get("avg_entry_price", "0"))
            saved_position_gross = to_decimal(data.get("position_gross_base", abs(saved_position)))
            saved_position_long = to_decimal(data.get("position_long_base", max(_ZERO, saved_position)))
            saved_position_short = to_decimal(data.get("position_short_base", max(_ZERO, -saved_position)))
            saved_avg_entry_long = to_decimal(
                data.get("avg_entry_price_long", saved_avg_entry if saved_position_long > _ZERO else _ZERO)
            )
            saved_avg_entry_short = to_decimal(
                data.get("avg_entry_price_short", saved_avg_entry if saved_position_short > _ZERO else _ZERO)
            )
            saved_last_fill_ts = float(data.get("last_fill_ts", 0.0) or 0.0)
            if saved_last_fill_ts > 0:
                self._last_fill_ts = saved_last_fill_ts
            if data.get("day_key") == today:
                self._daily_key = data.get("day_key")
                self._daily_equity_open = to_decimal(data["equity_open"]) if data.get("equity_open") else None
                self._daily_equity_peak = to_decimal(data["equity_peak"]) if data.get("equity_peak") else None
                self._traded_notional_today = to_decimal(data.get("traded_notional", "0"))
                self._fills_count_today = int(data.get("fills_count", 0))
                self._fees_paid_today_quote = to_decimal(data.get("fees_paid", "0"))
                self._funding_cost_today_quote = to_decimal(data.get("funding_cost", "0"))
                self._realized_pnl_today = to_decimal(data.get("realized_pnl", "0"))
                self._position_base = saved_position
                self._position_gross_base = saved_position_gross
                self._position_long_base = saved_position_long
                self._position_short_base = saved_position_short
                self._avg_entry_price = saved_avg_entry
                self._avg_entry_price_long = saved_avg_entry_long
                self._avg_entry_price_short = saved_avg_entry_short
                logger.info("Restored daily state for %s (fills=%d, traded=%.2f)", today, self._fills_count_today, self._traded_notional_today)
            else:
                self._position_base = saved_position
                self._position_gross_base = saved_position_gross
                self._position_long_base = saved_position_long
                self._position_short_base = saved_position_short
                self._avg_entry_price = saved_avg_entry
                self._avg_entry_price_long = saved_avg_entry_long
                self._avg_entry_price_short = saved_avg_entry_short
                logger.info(
                    "Cross-day restart: carried forward net=%.8f gross=%.8f avg_entry=%.2f from %s",
                    saved_position, saved_position_gross, saved_avg_entry, data.get("day_key", "?"),
                )
        except Exception:
            logger.warning("Failed to load daily state", exc_info=True)

    def _save_daily_state(self, force: bool = False) -> None:
        """Persist daily state to Redis and disk for restart recovery."""
        now_ts = float(self.market_data_provider.time())
        data = {
            "day_key": self._daily_key,
            "equity_open": str(self._daily_equity_open) if self._daily_equity_open else None,
            "equity_peak": str(self._daily_equity_peak) if self._daily_equity_peak else None,
            "traded_notional": str(self._traded_notional_today),
            "fills_count": self._fills_count_today,
            "fees_paid": str(self._fees_paid_today_quote),
            "funding_cost": str(self._funding_cost_today_quote),
            "realized_pnl": str(self._realized_pnl_today),
            "last_fill_ts": float(getattr(self, "_last_fill_ts", 0.0) or 0.0),
            "position_base": str(getattr(self, "_position_base", _ZERO)),
            "position_gross_base": str(getattr(self, "_position_gross_base", abs(getattr(self, "_position_base", _ZERO)))),
            "position_long_base": str(getattr(self, "_position_long_base", max(_ZERO, getattr(self, "_position_base", _ZERO)))),
            "position_short_base": str(getattr(self, "_position_short_base", max(_ZERO, -getattr(self, "_position_base", _ZERO)))),
            "avg_entry_price": str(getattr(self, "_avg_entry_price", _ZERO)),
            "avg_entry_price_long": str(getattr(self, "_avg_entry_price_long", getattr(self, "_avg_entry_price", _ZERO))),
            "avg_entry_price_short": str(getattr(self, "_avg_entry_price_short", getattr(self, "_avg_entry_price", _ZERO))),
        }
        self._state_store.save(data, now_ts, force=force)

    # ------------------------------------------------------------------
    # Desk reconciliation
    # ------------------------------------------------------------------

    _desk_reconciliation_done: bool = False

    def _maybe_reconcile_desk_state(self, mid: Decimal) -> None:
        """One-time check on first tick: compare controller position vs desk portfolio."""
        if self._desk_reconciliation_done:
            return
        self._desk_reconciliation_done = True
        if not _config_is_paper(self.config):
            return
        try:
            conn = self._connector()
            if conn is None or not hasattr(conn, "paper_portfolio_snapshot"):
                return
            snap = conn.paper_portfolio_snapshot(mid)
            if not snap:
                return
            desk_pos = to_decimal(snap.get("position_base", "0"))
            desk_avg = to_decimal(snap.get("avg_entry_price", "0"))
            desk_rpnl = to_decimal(snap.get("realized_pnl", "0"))
            ctrl_pos = self._position_base
            ctrl_avg = self._avg_entry_price
            ctrl_rpnl = self._realized_pnl_today

            pos_delta = abs(desk_pos - ctrl_pos)
            if pos_delta > Decimal("1e-6"):
                logger.warning(
                    "STATE RECONCILIATION: position mismatch — desk=%.8f controller=%.8f delta=%.8f",
                    desk_pos, ctrl_pos, pos_delta,
                )
            elif abs(desk_avg - ctrl_avg) > Decimal("0.01") and abs(ctrl_pos) > Decimal("1e-8"):
                logger.warning(
                    "STATE RECONCILIATION: avg_entry mismatch — desk=%.2f controller=%.2f",
                    desk_avg, ctrl_avg,
                )
            else:
                logger.info(
                    "STATE RECONCILIATION: desk and controller positions agree (net=%.8f avg_entry=%.2f)",
                    ctrl_pos, ctrl_avg,
                )
            if abs(desk_rpnl - ctrl_rpnl) > Decimal("0.01"):
                logger.warning(
                    "STATE RECONCILIATION: realized_pnl mismatch — desk=%.4f controller=%.4f "
                    "(desk includes fees, controller may differ)",
                    desk_rpnl, ctrl_rpnl,
                )
        except Exception:
            logger.debug("State reconciliation check failed", exc_info=True)
