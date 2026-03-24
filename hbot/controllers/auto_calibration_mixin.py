"""Auto-calibration mixin — extracted from SharedRuntimeKernel.

Performs periodic self-tuning of min_edge and spread_floor parameters based on
rolling fill statistics and P&L metrics.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from controllers.core import clip as _clip
from controllers.ops_guard import GuardState

try:
    import orjson as _orjson
except ImportError:
    _orjson = None  # type: ignore[assignment]

import json

from platform_lib.core.utils import to_decimal

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")
_ONE = Decimal("1")
_10K = Decimal("10000")


class AutoCalibrationMixin:
    """Mixin providing auto-calibration diagnostic methods."""

    @staticmethod
    def _auto_calibration_p95(values: list[Decimal]) -> Decimal:
        if not values:
            return _ZERO
        n = len(values)
        # O(n) selection via heapq.nlargest — avoids O(n log n) full sort.
        k = max(1, n - int((n - 1) * 0.95))
        import heapq
        return heapq.nlargest(k, values)[-1]

    def _auto_calibration_report_path(self) -> Path:
        return Path(__file__).resolve().parents[1] / "reports" / "strategy" / "auto_tune_latest.json"

    def _auto_calibration_report_paths(self) -> list[Path]:
        paths = [self._auto_calibration_report_path()]
        try:
            paths.append(Path(self.config.log_dir) / "auto_tune_latest.json")
        except Exception:
            pass
        try:
            paths.append(Path(self._daily_state_path()).parent / "auto_tune_latest.json")
        except Exception:
            pass
        dedup: list[Path] = []
        seen: set[str] = set()
        for p in paths:
            key = str(p)
            if key in seen:
                continue
            seen.add(key)
            dedup.append(p)
        return dedup

    def _auto_calibration_write_report(self, payload: dict[str, Any]) -> None:
        try:
            blob = (
                _orjson.dumps(payload, default=str, option=_orjson.OPT_INDENT_2).decode()
                if _orjson is not None
                else json.dumps(payload, indent=2, default=str)
            )
            for path in self._auto_calibration_report_paths():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(blob, encoding="utf-8")
            self._auto_calibration_last_report_ts = float(self.market_data_provider.time())
        except Exception:
            logger.debug("auto_calibration report write failed", exc_info=True)

    def _auto_calibration_record_minute(
        self,
        now_ts: float,
        state: GuardState,
        risk_reasons: list[str],
        snapshot: dict[str, Any],
        daily_loss_pct: Decimal,
        drawdown_pct: Decimal,
    ) -> None:
        self._auto_calibration_minute_history.append(
            {
                "ts": now_ts,
                "state": str(getattr(state, "value", state)),
                "risk_reasons": list(risk_reasons),
                "edge_gate_blocked": bool(snapshot.get("edge_gate_blocked", False)),
                "orders_active": int(to_decimal(snapshot.get("orders_active", _ZERO))),
                "order_book_stale": bool(snapshot.get("order_book_stale", False)),
                "net_edge_pct": to_decimal(self.processed_data.get("net_edge_pct", _ZERO)),
                "net_edge_gate_pct": to_decimal(self.processed_data.get("net_edge_gate_pct", _ZERO)),
                "daily_loss_pct": to_decimal(daily_loss_pct),
                "drawdown_pct": to_decimal(drawdown_pct),
            }
        )

    def _auto_calibration_record_fill(
        self,
        now_ts: float,
        notional_quote: Decimal,
        fee_quote: Decimal,
        realized_pnl_quote: Decimal,
        slippage_bps: Decimal,
        is_maker: bool,
        fill_edge_bps: Decimal = _ZERO,
    ) -> None:
        net_pnl_quote = realized_pnl_quote - fee_quote
        self._auto_calibration_fill_history.append(
            {
                "ts": now_ts,
                "notional_quote": max(_ZERO, to_decimal(notional_quote)),
                "fee_quote": max(_ZERO, to_decimal(fee_quote)),
                "realized_pnl_quote": to_decimal(realized_pnl_quote),
                "net_pnl_quote": to_decimal(net_pnl_quote),
                "slippage_bps": to_decimal(slippage_bps),
                "fill_edge_bps": to_decimal(fill_edge_bps),
                "is_maker": bool(is_maker),
            }
        )

    def _auto_calibration_maybe_run(
        self,
        now_ts: float,
        state: GuardState,
        risk_reasons: list[str],
        daily_loss_pct: Decimal,
        drawdown_pct: Decimal,
    ) -> None:
        if not self.config.auto_calibration_enabled:
            return
        interval_s = float(max(60, int(self.config.auto_calibration_update_interval_s)))
        if (now_ts - self._auto_calibration_last_eval_ts) < interval_s:
            return
        self._auto_calibration_last_eval_ts = now_ts

        lookback_s = float(max(300, int(self.config.auto_calibration_lookback_s)))
        window_start = now_ts - lookback_s
        minutes = [m for m in self._auto_calibration_minute_history if float(m.get("ts", 0.0)) >= window_start]
        fills = [f for f in self._auto_calibration_fill_history if float(f.get("ts", 0.0)) >= window_start]
        rows = max(1, len(minutes))

        edge_gate_blocked_ratio = Decimal(sum(1 for m in minutes if bool(m.get("edge_gate_blocked", False)))) / Decimal(rows)
        orders_active_ratio = Decimal(sum(1 for m in minutes if int(m.get("orders_active", 0)) > 0)) / Decimal(rows)
        stale_ratio = Decimal(sum(1 for m in minutes if bool(m.get("order_book_stale", False)))) / Decimal(rows)
        fills_count = len(fills)
        taker_ratio = (
            Decimal(sum(1 for f in fills if not bool(f.get("is_maker", False)))) / Decimal(fills_count)
            if fills_count > 0 else _ZERO
        )
        notional_total = sum((to_decimal(f.get("notional_quote", _ZERO)) for f in fills), _ZERO)
        net_pnl_total = sum((to_decimal(f.get("net_pnl_quote", _ZERO)) for f in fills), _ZERO)
        net_pnl_bps = (net_pnl_total / notional_total * _10K) if notional_total > _ZERO else _ZERO
        slippage_p95_bps = self._auto_calibration_p95([to_decimal(f.get("slippage_bps", _ZERO)) for f in fills])

        freeze_reasons: list[str] = []
        if to_decimal(drawdown_pct) >= to_decimal(self.config.auto_calibration_freeze_drawdown_pct):
            freeze_reasons.append("drawdown_cap")
        if to_decimal(daily_loss_pct) >= to_decimal(self.config.auto_calibration_freeze_daily_loss_pct):
            freeze_reasons.append("daily_loss_cap")
        if stale_ratio > to_decimal(self.config.auto_calibration_freeze_order_book_stale_ratio_gt):
            freeze_reasons.append("order_book_stale_ratio")
        if self._external_soft_pause:
            freeze_reasons.append("external_guard")
        if state == GuardState.HARD_STOP:
            freeze_reasons.append("hard_stop")

        relax_signal = (
            fills_count < int(self.config.auto_calibration_relax_fills_lt)
            and edge_gate_blocked_ratio > to_decimal(self.config.auto_calibration_relax_edge_gate_blocked_ratio_gt)
            and orders_active_ratio < to_decimal(self.config.auto_calibration_relax_orders_active_ratio_lt)
            and stale_ratio < to_decimal(self.config.auto_calibration_relax_order_book_stale_ratio_lt)
        )
        tighten_signal = (
            (fills_count > 0 and slippage_p95_bps > to_decimal(self.config.auto_calibration_tighten_slippage_p95_bps_gt))
            or (fills_count > 0 and net_pnl_bps < to_decimal(self.config.auto_calibration_tighten_net_pnl_bps_lt))
            or (
                fills_count > 0
                and taker_ratio > to_decimal(self.config.auto_calibration_tighten_taker_ratio_gt)
                and net_pnl_bps < _ZERO
            )
        )

        if fills_count > 0 and net_pnl_bps < _ZERO:
            self._auto_calibration_negative_window_streak += 1
        elif fills_count > 0:
            self._auto_calibration_negative_window_streak = 0

        if relax_signal:
            self._auto_calibration_relax_signal_streak += 1
        else:
            self._auto_calibration_relax_signal_streak = 0

        decision = "hold"
        direction = _ZERO
        if freeze_reasons:
            decision = "freeze"
        elif tighten_signal:
            decision = "tighten"
            direction = _ONE
            self._auto_calibration_relax_signal_streak = 0
        elif relax_signal and self._auto_calibration_relax_signal_streak >= int(self.config.auto_calibration_required_consecutive_relax_cycles):
            decision = "relax"
            direction = Decimal("-1")

        max_hourly = max(_ZERO, to_decimal(self.config.auto_calibration_max_total_change_per_hour_bps))
        while self._auto_calibration_change_events and (now_ts - float(self._auto_calibration_change_events[0][0])) > 3600:
            self._auto_calibration_change_events.popleft()
        used_hourly = sum((to_decimal(v[1]) for v in self._auto_calibration_change_events), _ZERO)
        remaining_hourly = max(_ZERO, max_hourly - used_hourly)
        step_bps = max(_ZERO, to_decimal(self.config.auto_calibration_max_step_bps))
        step_bps = min(step_bps, remaining_hourly / Decimal("3") if remaining_hourly > _ZERO else _ZERO)

        old_min_edge = to_decimal(self.config.min_net_edge_bps)
        old_resume = to_decimal(self.config.edge_resume_bps)
        old_side_floor = to_decimal(self.config.min_side_spread_bps)
        new_min_edge = old_min_edge
        new_resume = old_resume
        new_side_floor = old_side_floor

        if decision in {"relax", "tighten"} and step_bps > _ZERO:
            new_min_edge = _clip(
                old_min_edge + (direction * step_bps),
                to_decimal(self.config.auto_calibration_min_net_edge_bps_min),
                to_decimal(self.config.auto_calibration_min_net_edge_bps_max),
            )
            new_resume = _clip(
                old_resume + (direction * step_bps),
                to_decimal(self.config.auto_calibration_edge_resume_bps_min),
                to_decimal(self.config.auto_calibration_edge_resume_bps_max),
            )
            new_side_floor = _clip(
                old_side_floor + (direction * step_bps),
                to_decimal(self.config.auto_calibration_min_side_spread_bps_min),
                to_decimal(self.config.auto_calibration_min_side_spread_bps_max),
            )

        change_abs = abs(new_min_edge - old_min_edge) + abs(new_resume - old_resume) + abs(new_side_floor - old_side_floor)
        applied = False
        shadow = bool(self.config.auto_calibration_shadow_mode)
        rollback_applied = False

        if decision in {"relax", "tighten"} and change_abs <= _ZERO:
            decision = "hold_no_budget_or_bound"
        elif decision in {"relax", "tighten"}:
            if shadow:
                decision = f"{decision}_shadow"
            else:
                self.config.min_net_edge_bps = new_min_edge
                self.config.edge_resume_bps = new_resume
                self.config.min_side_spread_bps = new_side_floor
                self._spread_engine._min_net_edge_bps = new_min_edge
                self._spread_engine._edge_resume_bps = new_resume
                self._auto_calibration_change_events.append((now_ts, change_abs))
                self._auto_calibration_applied_changes.append(
                    {
                        "ts": now_ts,
                        "prev": {
                            "min_net_edge_bps": str(old_min_edge),
                            "edge_resume_bps": str(old_resume),
                            "min_side_spread_bps": str(old_side_floor),
                        },
                        "new": {
                            "min_net_edge_bps": str(new_min_edge),
                            "edge_resume_bps": str(new_resume),
                            "min_side_spread_bps": str(new_side_floor),
                        },
                    }
                )
                applied = True
                logger.warning(
                    "AUTO_TUNE applied decision=%s min_net_edge_bps=%s edge_resume_bps=%s min_side_spread_bps=%s",
                    decision, str(new_min_edge), str(new_resume), str(new_side_floor),
                )

        if (
            self.config.auto_calibration_rollback_enabled
            and not shadow
            and self._auto_calibration_negative_window_streak >= int(self.config.auto_calibration_rollback_negative_windows)
            and len(self._auto_calibration_applied_changes) > 0
        ):
            last = self._auto_calibration_applied_changes.pop()
            prev = last.get("prev", {})
            rb_min_edge = to_decimal(prev.get("min_net_edge_bps", self.config.min_net_edge_bps))
            rb_resume = to_decimal(prev.get("edge_resume_bps", self.config.edge_resume_bps))
            rb_side_floor = to_decimal(prev.get("min_side_spread_bps", self.config.min_side_spread_bps))
            rb_change = (
                abs(to_decimal(self.config.min_net_edge_bps) - rb_min_edge)
                + abs(to_decimal(self.config.edge_resume_bps) - rb_resume)
                + abs(to_decimal(self.config.min_side_spread_bps) - rb_side_floor)
            )
            self.config.min_net_edge_bps = rb_min_edge
            self.config.edge_resume_bps = rb_resume
            self.config.min_side_spread_bps = rb_side_floor
            self._spread_engine._min_net_edge_bps = rb_min_edge
            self._spread_engine._edge_resume_bps = rb_resume
            self._auto_calibration_change_events.append((now_ts, rb_change))
            self._auto_calibration_negative_window_streak = 0
            rollback_applied = True
            decision = "rollback"
            logger.warning(
                "AUTO_TUNE rollback applied min_net_edge_bps=%s edge_resume_bps=%s min_side_spread_bps=%s",
                str(rb_min_edge), str(rb_resume), str(rb_side_floor),
            )

        self._auto_calibration_last_decision = decision
        report = {
            "ts_utc": datetime.fromtimestamp(now_ts, tz=UTC).isoformat(),
            "enabled": bool(self.config.auto_calibration_enabled),
            "shadow_mode": shadow,
            "decision": decision,
            "applied": applied,
            "rollback_applied": rollback_applied,
            "freeze_reasons": freeze_reasons,
            "metrics": {
                "lookback_s": int(lookback_s),
                "minute_rows": len(minutes),
                "fills": fills_count,
                "edge_gate_blocked_ratio": float(edge_gate_blocked_ratio),
                "orders_active_ratio": float(orders_active_ratio),
                "order_book_stale_ratio": float(stale_ratio),
                "taker_ratio": float(taker_ratio),
                "slippage_p95_bps": float(slippage_p95_bps),
                "net_pnl_bps": float(net_pnl_bps),
                "net_pnl_quote": float(net_pnl_total),
                "negative_window_streak": self._auto_calibration_negative_window_streak,
                "relax_signal_streak": self._auto_calibration_relax_signal_streak,
            },
            "knobs_before": {
                "min_net_edge_bps": str(old_min_edge),
                "edge_resume_bps": str(old_resume),
                "min_side_spread_bps": str(old_side_floor),
            },
            "knobs_after": {
                "min_net_edge_bps": str(to_decimal(self.config.min_net_edge_bps)),
                "edge_resume_bps": str(to_decimal(self.config.edge_resume_bps)),
                "min_side_spread_bps": str(to_decimal(self.config.min_side_spread_bps)),
            },
            "limits": {
                "max_step_bps": str(to_decimal(self.config.auto_calibration_max_step_bps)),
                "remaining_hourly_budget_bps": str(max(_ZERO, remaining_hourly)),
            },
        }
        self._auto_calibration_write_report(report)

