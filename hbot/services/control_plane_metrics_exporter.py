from __future__ import annotations

import csv
import logging
import os
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from platform_lib.logging.log_namespace import iter_bot_log_files
from platform_lib.core.utils import (
    env_int as _env_int,
)
from platform_lib.core.utils import (
    parse_iso_ts as _safe_parse_iso_ts,
)
from platform_lib.core.utils import (
    read_json as _read_json,
)
from platform_lib.core.utils import (
    safe_float as _safe_float,
)
from services.hb_bridge.redis_client import RedisStreamClient


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _fmt_labels(labels: dict[str, str]) -> str:
    if not labels:
        return ""
    pairs = [f'{k}="{_escape_label(v)}"' for k, v in labels.items()]
    return "{" + ",".join(pairs) + "}"


def _status_to_bool(status: str, good_values: tuple[str, ...]) -> float:
    return 1.0 if str(status).strip().lower() in good_values else 0.0


def _safe_int(value: object, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def _percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    idx = int(max(0, min(len(sorted_values) - 1, (len(sorted_values) - 1) * p)))
    return float(sorted_values[idx])


class ControlPlaneMetricsExporter:
    def __init__(
        self,
        reports_root: Path,
        data_root: Path,
        freshness_max_sec: int = 1800,
        *,
        redis_host: str = "redis",
        redis_port: int = 6379,
        redis_db: int = 0,
        redis_password: str = "",
        redis_enabled: bool = True,
        paper_exchange_heartbeat_stream: str = "hb.paper_exchange.heartbeat.v1",
        paper_exchange_heartbeat_max_age_sec: int = 30,
        paper_exchange_load_report_path: str = "verification/paper_exchange_load_latest.json",
        paper_exchange_threshold_inputs_path: str = "verification/paper_exchange_threshold_inputs_latest.json",
        paper_exchange_command_journal_path: str = "verification/paper_exchange_command_journal_latest.json",
        paper_exchange_state_snapshot_path: str = "verification/paper_exchange_state_snapshot_latest.json",
        paper_exchange_pair_snapshot_path: str = "verification/paper_exchange_pair_snapshot_latest.json",
        paper_exchange_market_fill_journal_path: str = "verification/paper_exchange_market_fill_journal_latest.json",
    ):
        self._reports_root = reports_root
        self._data_root = data_root
        self._freshness_max_sec = freshness_max_sec
        self._paper_exchange_heartbeat_stream = str(paper_exchange_heartbeat_stream or "").strip() or "hb.paper_exchange.heartbeat.v1"
        self._paper_exchange_heartbeat_max_age_sec = max(1, int(paper_exchange_heartbeat_max_age_sec))
        self._paper_exchange_load_report_path = self._resolve_reports_path(paper_exchange_load_report_path)
        self._paper_exchange_threshold_inputs_path = self._resolve_reports_path(paper_exchange_threshold_inputs_path)
        self._paper_exchange_command_journal_path = self._resolve_reports_path(paper_exchange_command_journal_path)
        self._paper_exchange_state_snapshot_path = self._resolve_reports_path(paper_exchange_state_snapshot_path)
        self._paper_exchange_pair_snapshot_path = self._resolve_reports_path(paper_exchange_pair_snapshot_path)
        self._paper_exchange_market_fill_journal_path = self._resolve_reports_path(paper_exchange_market_fill_journal_path)
        self._redis_client = RedisStreamClient(
            host=str(redis_host),
            port=int(redis_port),
            db=int(redis_db),
            password=str(redis_password or "") or None,
            enabled=bool(redis_enabled),
        )

    def _resolve_reports_path(self, path_value: str) -> Path:
        path = Path(str(path_value or "").strip())
        if not path.is_absolute():
            parts = list(path.parts)
            if parts and str(parts[0]).strip().lower() == "reports":
                path = Path(*parts[1:]) if len(parts) > 1 else Path(".")
            path = self._reports_root / path
        return path

    def _latest_integrity_file(self) -> Path:
        event_store_root = self._reports_root / "event_store"
        candidates = sorted(event_store_root.glob("integrity_*.json"))
        if candidates:
            return candidates[-1]
        return event_store_root / "integrity_20260221.json"

    def _report_targets(self) -> dict[str, Path]:
        return {
            "reconciliation": self._reports_root / "reconciliation" / "latest.json",
            "parity": self._reports_root / "parity" / "latest.json",
            "portfolio_risk": self._reports_root / "portfolio_risk" / "latest.json",
            "market_data": self._reports_root / "market_data" / "latest.json",
            "ops_db_writer": self._reports_root / "ops_db_writer" / "latest.json",
            "coordination": self._reports_root / "coordination" / "latest.json",
            "coordination_policy": self._reports_root / "policy" / "coordination_policy_latest.json",
            "portfolio_allocator": self._reports_root / "policy" / "portfolio_allocator_latest.json",
            "reliability_slo": self._reports_root / "ops" / "reliability_slo_latest.json",
            "promotion_gate": self._reports_root / "promotion_gates" / "latest.json",
            "strict_cycle": self._reports_root / "promotion_gates" / "strict_cycle_latest.json",
            "soak": self._reports_root / "soak" / "latest.json",
            "day2_gate": self._reports_root / "event_store" / "day2_gate_eval_latest.json",
            "event_store_integrity": self._latest_integrity_file(),
            "readiness": self._reports_root / "readiness" / "final_decision_latest.json",
        }

    def _read_last_csv_row(self, path: Path) -> dict[str, str]:
        if not path.exists():
            return {}
        try:
            with path.open("r", encoding="utf-8", errors="ignore", newline="") as fp:
                reader = csv.DictReader(fp)
                last: dict[str, str] | None = None
                for row in reader:
                    last = {str(k): str(v) for k, v in row.items()}
                return last or {}
        except Exception:
            return {}

    def _bot_blotter_metrics(self, expected_bots: list[str] | None = None) -> list[dict[str, object]]:
        out: list[dict[str, object]] = []
        seen_bots = set()
        for fills_file in iter_bot_log_files(self._data_root, "fills.csv"):
            try:
                bot = fills_file.parts[-5]
                variant = fills_file.parts[-2]
            except Exception:
                continue
            seen_bots.add(bot)
            latest_row = self._read_last_csv_row(fills_file)
            ts_value = (
                latest_row.get("ts")
                or latest_row.get("timestamp")
                or latest_row.get("fill_ts")
                or latest_row.get("time")
                or ""
            )
            ts_epoch = 0.0
            parsed = _safe_parse_iso_ts(ts_value)
            if parsed:
                ts_epoch = parsed.timestamp()
            row_count = 0
            try:
                row_count = max(0, len(fills_file.read_text(encoding="utf-8", errors="ignore").splitlines()) - 1)
            except Exception:
                row_count = 0
            out.append(
                {
                    "bot": bot,
                    "variant": variant,
                    "fills_total": float(row_count),
                    "last_fill_ts_epoch": float(ts_epoch),
                }
            )
        for bot in expected_bots or []:
            if bot in seen_bots:
                continue
            out.append(
                {
                    "bot": str(bot),
                    "variant": "no_fills",
                    "fills_total": 0.0,
                    "last_fill_ts_epoch": 0.0,
                }
            )
        return out

    @staticmethod
    def _stream_entry_ts_ms(entry_id: str) -> int:
        text = str(entry_id or "").strip()
        if "-" not in text:
            return 0
        try:
            return max(0, int(text.split("-", 1)[0]))
        except Exception:
            return 0

    def _paper_exchange_service_metrics(self, now: datetime) -> list[str]:
        labels = {"stream": self._paper_exchange_heartbeat_stream}
        redis_up = 1.0 if self._redis_client.ping() else 0.0
        latest = self._redis_client.read_latest(self._paper_exchange_heartbeat_stream) if redis_up > 0 else None

        present = 1.0 if latest else 0.0
        heartbeat_age_sec = 1e9
        heartbeat_status = "missing"
        instance_name = ""
        service_name = "paper_exchange_service"
        market_pairs_total = 0
        stale_pairs = 0
        newest_snapshot_age_ms = 0
        oldest_snapshot_age_ms = 0
        metadata: dict[str, Any] = {}

        if latest is not None:
            entry_id, payload = latest
            payload = payload if isinstance(payload, dict) else {}
            instance_name = str(payload.get("instance_name", "")).strip()
            service_name = str(payload.get("service_name", service_name)).strip() or service_name
            heartbeat_status = str(payload.get("status", "unknown")).strip().lower() or "unknown"
            market_pairs_total = _safe_int(payload.get("market_pairs_total"), 0)
            stale_pairs = _safe_int(payload.get("stale_pairs"), 0)
            newest_snapshot_age_ms = _safe_int(payload.get("newest_snapshot_age_ms"), 0)
            oldest_snapshot_age_ms = _safe_int(payload.get("oldest_snapshot_age_ms"), 0)
            metadata = payload.get("metadata", {}) if isinstance(payload.get("metadata", {}), dict) else {}
            ts_ms = 0
            try:
                ts_ms = int(payload.get("timestamp_ms", 0) or 0)
            except Exception:
                ts_ms = 0
            if ts_ms <= 0:
                ts_ms = self._stream_entry_ts_ms(entry_id)
            if ts_ms > 0:
                heartbeat_age_sec = max(0.0, now.timestamp() - (float(ts_ms) / 1000.0))

        heartbeat_fresh = 1.0 if (present > 0 and heartbeat_age_sec <= float(self._paper_exchange_heartbeat_max_age_sec)) else 0.0
        service_up = 1.0 if (redis_up > 0 and heartbeat_fresh > 0) else 0.0

        out = [
            f"hbot_paper_exchange_redis_up{_fmt_labels(labels)} {redis_up}",
            f"hbot_paper_exchange_heartbeat_present{_fmt_labels(labels)} {present}",
            f"hbot_paper_exchange_heartbeat_age_seconds{_fmt_labels(labels)} {heartbeat_age_sec}",
            f"hbot_paper_exchange_heartbeat_fresh{_fmt_labels(labels)} {heartbeat_fresh}",
            f"hbot_paper_exchange_service_up{_fmt_labels(labels)} {service_up}",
            f"hbot_paper_exchange_market_pairs_total{_fmt_labels(labels)} {float(market_pairs_total)}",
            f"hbot_paper_exchange_stale_pairs_total{_fmt_labels(labels)} {float(stale_pairs)}",
            f"hbot_paper_exchange_newest_snapshot_age_ms{_fmt_labels(labels)} {float(newest_snapshot_age_ms)}",
            f"hbot_paper_exchange_oldest_snapshot_age_ms{_fmt_labels(labels)} {float(oldest_snapshot_age_ms)}",
        ]
        metadata_int_fields = [
            "processed_commands",
            "rejected_commands",
            "orders_active",
            "orders_total",
            "command_latency_samples",
            "command_latency_avg_ms",
            "command_latency_max_ms",
            "generated_fill_events",
            "generated_partial_fill_events",
            "market_rows_not_acked",
            "command_publish_failures",
        ]
        for field_name in metadata_int_fields:
            value = float(_safe_int(metadata.get(field_name), 0))
            out.append(f"hbot_paper_exchange_{field_name}{_fmt_labels(labels)} {value}")
        status_labels = {
            "stream": self._paper_exchange_heartbeat_stream,
            "status": heartbeat_status,
            "instance_name": instance_name,
            "service_name": service_name,
        }
        out.append(f"hbot_paper_exchange_heartbeat_status_info{_fmt_labels(status_labels)} 1")
        return out

    def _paper_exchange_load_report_metrics(self, now: datetime) -> list[str]:
        payload = _read_json(self._paper_exchange_load_report_path)
        present = 1.0 if self._paper_exchange_load_report_path.exists() else 0.0
        ts = _safe_parse_iso_ts(payload.get("ts_utc")) if payload else None
        age_sec = (now - ts).total_seconds() if ts else 1e9
        if age_sec < 0:
            age_sec = 0.0
        labels = {"artifact": "paper_exchange_load_latest"}
        lines = [
            f"hbot_paper_exchange_load_report_present{_fmt_labels(labels)} {present}",
            f"hbot_paper_exchange_load_report_age_seconds{_fmt_labels(labels)} {age_sec}",
        ]
        metrics = payload.get("metrics", {}) if isinstance(payload.get("metrics", {}), dict) else {}
        key_map = {
            "p1_19_sustained_command_throughput_cmds_per_sec": "hbot_paper_exchange_load_throughput_cmds_per_sec",
            "p1_19_command_latency_under_load_p95_ms": "hbot_paper_exchange_load_command_latency_p95_ms",
            "p1_19_command_latency_under_load_p99_ms": "hbot_paper_exchange_load_command_latency_p99_ms",
            "p1_19_stream_backlog_growth_rate_pct_per_10min": "hbot_paper_exchange_load_backlog_growth_pct_per_10m",
        }
        for src_key, metric_name in key_map.items():
            lines.append(f"{metric_name}{_fmt_labels(labels)} {_safe_float(metrics.get(src_key), 0.0)}")
        return lines

    def _paper_exchange_threshold_metrics(self, now: datetime) -> list[str]:
        payload = _read_json(self._paper_exchange_threshold_inputs_path)
        present = 1.0 if self._paper_exchange_threshold_inputs_path.exists() else 0.0
        ts = _safe_parse_iso_ts(payload.get("ts_utc")) if payload else None
        age_sec = (now - ts).total_seconds() if ts else 1e9
        if age_sec < 0:
            age_sec = 0.0
        labels = {"artifact": "paper_exchange_threshold_inputs_latest"}
        lines = [
            f"hbot_paper_exchange_threshold_inputs_present{_fmt_labels(labels)} {present}",
            f"hbot_paper_exchange_threshold_inputs_age_seconds{_fmt_labels(labels)} {age_sec}",
        ]
        diagnostics = payload.get("diagnostics", {}) if isinstance(payload.get("diagnostics", {}), dict) else {}
        lines.append(
            f"hbot_paper_exchange_threshold_unresolved_metrics_total{_fmt_labels(labels)} {float(_safe_int(diagnostics.get('unresolved_metric_count'), 0))}"
        )
        metrics = payload.get("metrics", {}) if isinstance(payload.get("metrics", {}), dict) else {}
        for metric_name, value in metrics.items():
            mlabels = {"metric": str(metric_name)}
            lines.append(f"hbot_paper_exchange_threshold_metric{_fmt_labels(mlabels)} {_safe_float(value, 0.0)}")
        return lines

    def _paper_exchange_command_journal_metrics(self, now: datetime) -> list[str]:
        payload = _read_json(self._paper_exchange_command_journal_path)
        present = 1.0 if self._paper_exchange_command_journal_path.exists() else 0.0
        ts = _safe_parse_iso_ts(payload.get("ts_utc")) if payload else None
        age_sec = (now - ts).total_seconds() if ts else 1e9
        if age_sec < 0:
            age_sec = 0.0
        lines = [
            f"hbot_paper_exchange_command_journal_present {present}",
            f"hbot_paper_exchange_command_journal_age_seconds {age_sec}",
        ]
        commands = payload.get("commands", {}) if isinstance(payload.get("commands", {}), dict) else {}
        lines.append(f"hbot_paper_exchange_command_journal_entries_total {float(len(commands))}")
        command_status_counts: dict[tuple[str, str], int] = {}
        reject_reason_counts: dict[str, int] = {}
        for _event_id, row in commands.items():
            if not isinstance(row, dict):
                continue
            command_name = str(row.get("command", "unknown")).strip().lower() or "unknown"
            status = str(row.get("status", "unknown")).strip().lower() or "unknown"
            reason = str(row.get("reason", "unknown")).strip().lower() or "unknown"
            key = (command_name, status)
            command_status_counts[key] = command_status_counts.get(key, 0) + 1
            if status == "rejected":
                reject_reason_counts[reason] = reject_reason_counts.get(reason, 0) + 1
        for (command_name, status), count in sorted(command_status_counts.items()):
            labels = {"command": command_name, "status": status}
            lines.append(f"hbot_paper_exchange_command_total{_fmt_labels(labels)} {float(count)}")
        for reason, count in sorted(reject_reason_counts.items()):
            labels = {"reason": reason}
            lines.append(f"hbot_paper_exchange_command_reject_reason_total{_fmt_labels(labels)} {float(count)}")

        state_snapshot = _read_json(self._paper_exchange_state_snapshot_path)
        orders = state_snapshot.get("orders", {}) if isinstance(state_snapshot.get("orders", {}), dict) else {}
        state_counts: dict[str, int] = {}
        submit_to_first_fill_latencies_ms: list[float] = []
        for _order_id, row in orders.items():
            if not isinstance(row, dict):
                continue
            state = str(row.get("state", "unknown")).strip().lower() or "unknown"
            state_counts[state] = state_counts.get(state, 0) + 1
            created_ts_ms = _safe_int(row.get("created_ts_ms"), 0)
            first_fill_ts_ms = _safe_int(row.get("first_fill_ts_ms"), 0)
            if created_ts_ms > 0 and first_fill_ts_ms > 0:
                submit_to_first_fill_latencies_ms.append(float(max(0, first_fill_ts_ms - created_ts_ms)))
        lines.append(f"hbot_paper_exchange_order_snapshot_total {float(len(orders))}")
        for state, count in sorted(state_counts.items()):
            labels = {"state": state}
            lines.append(f"hbot_paper_exchange_order_state_total{_fmt_labels(labels)} {float(count)}")
        sorted_latencies = sorted(submit_to_first_fill_latencies_ms)
        lines.append(f"hbot_paper_exchange_submit_to_first_fill_latency_samples {float(len(sorted_latencies))}")
        lines.append(f"hbot_paper_exchange_submit_to_first_fill_latency_p95_ms {_percentile(sorted_latencies, 0.95)}")
        lines.append(f"hbot_paper_exchange_submit_to_first_fill_latency_p99_ms {_percentile(sorted_latencies, 0.99)}")

        fill_journal = _read_json(self._paper_exchange_market_fill_journal_path)
        fill_present = 1.0 if self._paper_exchange_market_fill_journal_path.exists() else 0.0
        fill_ts = _safe_parse_iso_ts(fill_journal.get("ts_utc")) if fill_journal else None
        fill_age_sec = (now - fill_ts).total_seconds() if fill_ts else 1e9
        if fill_age_sec < 0:
            fill_age_sec = 0.0
        lines.append(f"hbot_paper_exchange_market_fill_journal_present {fill_present}")
        lines.append(f"hbot_paper_exchange_market_fill_journal_age_seconds {fill_age_sec}")
        lines.append(
            f"hbot_paper_exchange_market_fill_events_total {float(_safe_int(fill_journal.get('event_count'), 0))}"
        )
        return lines

    def _paper_exchange_pair_snapshot_metrics(self, now: datetime) -> list[str]:
        payload = _read_json(self._paper_exchange_pair_snapshot_path)
        present = 1.0 if self._paper_exchange_pair_snapshot_path.exists() else 0.0
        ts = _safe_parse_iso_ts(payload.get("ts_utc")) if payload else None
        age_sec = (now - ts).total_seconds() if ts else 1e9
        if age_sec < 0:
            age_sec = 0.0
        lines = [
            f"hbot_paper_exchange_pair_snapshot_present {present}",
            f"hbot_paper_exchange_pair_snapshot_artifact_age_seconds {age_sec}",
        ]
        pairs = payload.get("pairs", {}) if isinstance(payload.get("pairs", {}), dict) else {}
        lines.append(f"hbot_paper_exchange_pair_snapshot_total {float(len(pairs))}")
        now_ts_ms = int(now.timestamp() * 1000)
        stale_after_ms = int(self._paper_exchange_heartbeat_max_age_sec * 1000)
        for _pair_key, row in pairs.items():
            if not isinstance(row, dict):
                continue
            labels = {
                "connector": str(row.get("connector_name", "")).strip() or "unknown",
                "pair": str(row.get("trading_pair", "")).strip() or "unknown",
                "instance_name": str(row.get("instance_name", "")).strip() or "unknown",
            }
            snapshot_ts_ms = _safe_int(row.get("timestamp_ms"), 0)
            reference_ts_ms = _safe_int(row.get("reference_ts_ms"), 0)
            snapshot_age_seconds = (
                float(max(0, now_ts_ms - snapshot_ts_ms)) / 1000.0 if snapshot_ts_ms > 0 else 1e9
            )
            reference_age_seconds = (
                float(max(0, now_ts_ms - reference_ts_ms)) / 1000.0 if reference_ts_ms > 0 else 1e9
            )
            is_stale = 1.0 if (snapshot_ts_ms <= 0 or (now_ts_ms - snapshot_ts_ms) > stale_after_ms) else 0.0
            lines.append(f"hbot_paper_exchange_pair_snapshot_age_seconds{_fmt_labels(labels)} {snapshot_age_seconds}")
            lines.append(f"hbot_paper_exchange_pair_reference_age_seconds{_fmt_labels(labels)} {reference_age_seconds}")
            lines.append(f"hbot_paper_exchange_pair_stale{_fmt_labels(labels)} {is_stale}")
        return lines

    def render_prometheus(self) -> str:
        now = datetime.now(UTC)
        lines: list[str] = [
            "# HELP hbot_control_plane_report_age_seconds Age in seconds for control-plane report artifacts.",
            "# TYPE hbot_control_plane_report_age_seconds gauge",
            "# HELP hbot_control_plane_report_fresh Whether control-plane report age is within freshness threshold.",
            "# TYPE hbot_control_plane_report_fresh gauge",
            "# HELP hbot_control_plane_report_present Whether control-plane report artifact is present.",
            "# TYPE hbot_control_plane_report_present gauge",
            "# HELP hbot_control_plane_gate_status Normalized gate/status pass signal (1 good, 0 bad).",
            "# TYPE hbot_control_plane_gate_status gauge",
            "# HELP hbot_control_plane_finding_count Count of warning/critical findings for control-plane outputs.",
            "# TYPE hbot_control_plane_finding_count gauge",
            "# HELP hbot_exchange_snapshot_equity_quote Exchange snapshot equity_quote per bot.",
            "# TYPE hbot_exchange_snapshot_equity_quote gauge",
            "# HELP hbot_exchange_snapshot_base_pct Exchange snapshot base_pct per bot.",
            "# TYPE hbot_exchange_snapshot_base_pct gauge",
            "# HELP hbot_exchange_snapshot_probe_status Probe status one-hot signal from exchange snapshots.",
            "# TYPE hbot_exchange_snapshot_probe_status gauge",
            "# HELP hbot_bot_blotter_fills_total Total observed fills rows per bot variant.",
            "# TYPE hbot_bot_blotter_fills_total gauge",
            "# HELP hbot_bot_blotter_last_fill_timestamp_seconds Last fill timestamp in epoch seconds.",
            "# TYPE hbot_bot_blotter_last_fill_timestamp_seconds gauge",
            "# HELP hbot_bot_blotter_last_fill_age_seconds Age of latest fill in seconds.",
            "# TYPE hbot_bot_blotter_last_fill_age_seconds gauge",
            "# HELP hbot_coordination_runtime_state Coordination runtime state one-hot by state label.",
            "# TYPE hbot_coordination_runtime_state gauge",
            "# HELP hbot_coordination_decisions_seen Coordination decisions processed (latest observed counter).",
            "# TYPE hbot_coordination_decisions_seen gauge",
            "# HELP hbot_coordination_intents_emitted Coordination intents emitted (latest observed counter).",
            "# TYPE hbot_coordination_intents_emitted gauge",
            "# HELP hbot_coordination_allowed_instance_info Coordination policy allowed instances info.",
            "# TYPE hbot_coordination_allowed_instance_info gauge",
            "# HELP hbot_portfolio_allocator_allocation_pct Allocation percentage by bot from portfolio allocator report.",
            "# TYPE hbot_portfolio_allocator_allocation_pct gauge",
            "# HELP hbot_portfolio_allocator_target_notional_quote Target notional quote by bot from portfolio allocator report.",
            "# TYPE hbot_portfolio_allocator_target_notional_quote gauge",
            "# HELP hbot_portfolio_allocator_daily_goal_bot_target_pct Daily PnL target percent by bot from allocator daily_goal rows.",
            "# TYPE hbot_portfolio_allocator_daily_goal_bot_target_pct gauge",
            "# HELP hbot_portfolio_allocator_daily_goal_bot_target_quote Daily PnL target quote by bot from allocator daily_goal rows.",
            "# TYPE hbot_portfolio_allocator_daily_goal_bot_target_quote gauge",
            "# HELP hbot_portfolio_allocator_daily_goal_enabled Whether allocator daily_goal mode is enabled (1/0).",
            "# TYPE hbot_portfolio_allocator_daily_goal_enabled gauge",
            "# HELP hbot_portfolio_allocator_daily_goal_ok Whether allocator daily_goal status is pass (1/0).",
            "# TYPE hbot_portfolio_allocator_daily_goal_ok gauge",
            "# HELP hbot_portfolio_allocator_daily_goal_target_pct_total_equity Desk daily goal percent of equity from allocator report.",
            "# TYPE hbot_portfolio_allocator_daily_goal_target_pct_total_equity gauge",
            "# HELP hbot_portfolio_allocator_daily_goal_target_quote_total_equity Desk daily goal quote target from allocator report.",
            "# TYPE hbot_portfolio_allocator_daily_goal_target_quote_total_equity gauge",
            "# HELP hbot_portfolio_allocator_daily_goal_scope_equity_quote Equity scope used for daily goal computation.",
            "# TYPE hbot_portfolio_allocator_daily_goal_scope_equity_quote gauge",
            "# HELP hbot_portfolio_allocator_daily_goal_target_quote_distributed Total quote target distributed across bots.",
            "# TYPE hbot_portfolio_allocator_daily_goal_target_quote_distributed gauge",
            "# HELP hbot_portfolio_allocator_daily_goal_info Allocator daily goal metadata labels.",
            "# TYPE hbot_portfolio_allocator_daily_goal_info gauge",
            "# HELP hbot_paper_exchange_redis_up Redis availability for paper exchange heartbeat stream.",
            "# TYPE hbot_paper_exchange_redis_up gauge",
            "# HELP hbot_paper_exchange_heartbeat_present Whether a heartbeat entry is available.",
            "# TYPE hbot_paper_exchange_heartbeat_present gauge",
            "# HELP hbot_paper_exchange_heartbeat_age_seconds Age of latest paper exchange heartbeat.",
            "# TYPE hbot_paper_exchange_heartbeat_age_seconds gauge",
            "# HELP hbot_paper_exchange_heartbeat_fresh Whether heartbeat age is within threshold.",
            "# TYPE hbot_paper_exchange_heartbeat_fresh gauge",
            "# HELP hbot_paper_exchange_service_up Service liveness from redis + heartbeat freshness.",
            "# TYPE hbot_paper_exchange_service_up gauge",
            "# HELP hbot_paper_exchange_market_pairs_total Count of pairs tracked by paper exchange service.",
            "# TYPE hbot_paper_exchange_market_pairs_total gauge",
            "# HELP hbot_paper_exchange_stale_pairs_total Count of stale pairs in latest heartbeat.",
            "# TYPE hbot_paper_exchange_stale_pairs_total gauge",
            "# HELP hbot_paper_exchange_newest_snapshot_age_ms Newest market snapshot age in ms from heartbeat.",
            "# TYPE hbot_paper_exchange_newest_snapshot_age_ms gauge",
            "# HELP hbot_paper_exchange_oldest_snapshot_age_ms Oldest market snapshot age in ms from heartbeat.",
            "# TYPE hbot_paper_exchange_oldest_snapshot_age_ms gauge",
            "# HELP hbot_paper_exchange_processed_commands Commands processed by service.",
            "# TYPE hbot_paper_exchange_processed_commands gauge",
            "# HELP hbot_paper_exchange_rejected_commands Commands rejected by service.",
            "# TYPE hbot_paper_exchange_rejected_commands gauge",
            "# HELP hbot_paper_exchange_orders_active Active tracked order count in service.",
            "# TYPE hbot_paper_exchange_orders_active gauge",
            "# HELP hbot_paper_exchange_orders_total Total tracked orders in service.",
            "# TYPE hbot_paper_exchange_orders_total gauge",
            "# HELP hbot_paper_exchange_command_latency_samples Latency samples count in heartbeat metadata.",
            "# TYPE hbot_paper_exchange_command_latency_samples gauge",
            "# HELP hbot_paper_exchange_command_latency_avg_ms Mean command handling latency in ms.",
            "# TYPE hbot_paper_exchange_command_latency_avg_ms gauge",
            "# HELP hbot_paper_exchange_command_latency_max_ms Max command handling latency in ms.",
            "# TYPE hbot_paper_exchange_command_latency_max_ms gauge",
            "# HELP hbot_paper_exchange_generated_fill_events Generated fill events total.",
            "# TYPE hbot_paper_exchange_generated_fill_events gauge",
            "# HELP hbot_paper_exchange_generated_partial_fill_events Generated partial fill events total.",
            "# TYPE hbot_paper_exchange_generated_partial_fill_events gauge",
            "# HELP hbot_paper_exchange_market_rows_not_acked Market rows not acknowledged counter.",
            "# TYPE hbot_paper_exchange_market_rows_not_acked gauge",
            "# HELP hbot_paper_exchange_command_publish_failures Command publish failure counter.",
            "# TYPE hbot_paper_exchange_command_publish_failures gauge",
            "# HELP hbot_paper_exchange_heartbeat_status_info Last heartbeat status labels.",
            "# TYPE hbot_paper_exchange_heartbeat_status_info gauge",
            "# HELP hbot_paper_exchange_load_report_present Whether load report artifact exists.",
            "# TYPE hbot_paper_exchange_load_report_present gauge",
            "# HELP hbot_paper_exchange_load_report_age_seconds Age of load report artifact in seconds.",
            "# TYPE hbot_paper_exchange_load_report_age_seconds gauge",
            "# HELP hbot_paper_exchange_load_throughput_cmds_per_sec Sustained command throughput from load report.",
            "# TYPE hbot_paper_exchange_load_throughput_cmds_per_sec gauge",
            "# HELP hbot_paper_exchange_load_command_latency_p95_ms P95 command latency under load.",
            "# TYPE hbot_paper_exchange_load_command_latency_p95_ms gauge",
            "# HELP hbot_paper_exchange_load_command_latency_p99_ms P99 command latency under load.",
            "# TYPE hbot_paper_exchange_load_command_latency_p99_ms gauge",
            "# HELP hbot_paper_exchange_load_backlog_growth_pct_per_10m Stream backlog growth trend from load report.",
            "# TYPE hbot_paper_exchange_load_backlog_growth_pct_per_10m gauge",
            "# HELP hbot_paper_exchange_threshold_inputs_present Whether threshold artifact exists.",
            "# TYPE hbot_paper_exchange_threshold_inputs_present gauge",
            "# HELP hbot_paper_exchange_threshold_inputs_age_seconds Age of threshold artifact in seconds.",
            "# TYPE hbot_paper_exchange_threshold_inputs_age_seconds gauge",
            "# HELP hbot_paper_exchange_threshold_unresolved_metrics_total Unresolved threshold metrics count.",
            "# TYPE hbot_paper_exchange_threshold_unresolved_metrics_total gauge",
            "# HELP hbot_paper_exchange_threshold_metric Threshold metric value keyed by metric label.",
            "# TYPE hbot_paper_exchange_threshold_metric gauge",
            "# HELP hbot_paper_exchange_command_journal_present Whether command journal artifact exists.",
            "# TYPE hbot_paper_exchange_command_journal_present gauge",
            "# HELP hbot_paper_exchange_command_journal_age_seconds Age of command journal artifact in seconds.",
            "# TYPE hbot_paper_exchange_command_journal_age_seconds gauge",
            "# HELP hbot_paper_exchange_command_journal_entries_total Number of command entries in journal artifact.",
            "# TYPE hbot_paper_exchange_command_journal_entries_total gauge",
            "# HELP hbot_paper_exchange_command_total Command totals by command and status.",
            "# TYPE hbot_paper_exchange_command_total gauge",
            "# HELP hbot_paper_exchange_command_reject_reason_total Rejected commands grouped by reason.",
            "# TYPE hbot_paper_exchange_command_reject_reason_total gauge",
            "# HELP hbot_paper_exchange_order_snapshot_total Number of orders in service state snapshot.",
            "# TYPE hbot_paper_exchange_order_snapshot_total gauge",
            "# HELP hbot_paper_exchange_order_state_total Count of orders by state.",
            "# TYPE hbot_paper_exchange_order_state_total gauge",
            "# HELP hbot_paper_exchange_submit_to_first_fill_latency_samples Samples count for submit-to-first-fill latency.",
            "# TYPE hbot_paper_exchange_submit_to_first_fill_latency_samples gauge",
            "# HELP hbot_paper_exchange_submit_to_first_fill_latency_p95_ms P95 submit-to-first-fill latency in ms.",
            "# TYPE hbot_paper_exchange_submit_to_first_fill_latency_p95_ms gauge",
            "# HELP hbot_paper_exchange_submit_to_first_fill_latency_p99_ms P99 submit-to-first-fill latency in ms.",
            "# TYPE hbot_paper_exchange_submit_to_first_fill_latency_p99_ms gauge",
            "# HELP hbot_paper_exchange_market_fill_journal_present Whether market fill journal artifact exists.",
            "# TYPE hbot_paper_exchange_market_fill_journal_present gauge",
            "# HELP hbot_paper_exchange_market_fill_journal_age_seconds Age of market fill journal artifact in seconds.",
            "# TYPE hbot_paper_exchange_market_fill_journal_age_seconds gauge",
            "# HELP hbot_paper_exchange_market_fill_events_total Total market fill events in artifact.",
            "# TYPE hbot_paper_exchange_market_fill_events_total gauge",
            "# HELP hbot_paper_exchange_pair_snapshot_present Whether pair snapshot artifact exists.",
            "# TYPE hbot_paper_exchange_pair_snapshot_present gauge",
            "# HELP hbot_paper_exchange_pair_snapshot_artifact_age_seconds Age of pair snapshot artifact.",
            "# TYPE hbot_paper_exchange_pair_snapshot_artifact_age_seconds gauge",
            "# HELP hbot_paper_exchange_pair_snapshot_total Number of pair snapshots in artifact.",
            "# TYPE hbot_paper_exchange_pair_snapshot_total gauge",
            "# HELP hbot_paper_exchange_pair_snapshot_age_seconds Snapshot age per connector/pair/instance.",
            "# TYPE hbot_paper_exchange_pair_snapshot_age_seconds gauge",
            "# HELP hbot_paper_exchange_pair_reference_age_seconds Reference timestamp age per connector/pair/instance.",
            "# TYPE hbot_paper_exchange_pair_reference_age_seconds gauge",
            "# HELP hbot_paper_exchange_pair_stale Stale flag per connector/pair/instance.",
            "# TYPE hbot_paper_exchange_pair_stale gauge",
        ]

        report_targets = self._report_targets()
        for report_name, path in report_targets.items():
            payload = _read_json(path)
            present = 1.0 if path.exists() else 0.0
            ts = _safe_parse_iso_ts(payload.get("ts_utc")) if payload else None
            age_sec = (now - ts).total_seconds() if ts else 1e9
            if age_sec < 0:
                age_sec = 0.0
            fresh = 1.0 if age_sec <= float(self._freshness_max_sec) else 0.0

            labels = {"report": report_name}
            lines.append(f"hbot_control_plane_report_present{_fmt_labels(labels)} {present}")
            lines.append(f"hbot_control_plane_report_age_seconds{_fmt_labels(labels)} {age_sec}")
            lines.append(f"hbot_control_plane_report_fresh{_fmt_labels(labels)} {fresh}")

            if report_name == "promotion_gate":
                status = str(payload.get("status", "")).strip().lower()
                lines.append(
                    f'hbot_control_plane_gate_status{{gate="promotion_latest"}} {_status_to_bool(status, ("pass",))}'
                )
                lines.append(
                    f'hbot_control_plane_finding_count{{report="promotion_gate_critical_failures"}} {float(len(payload.get("critical_failures", [])))}'
                )
                checks = payload.get("checks", [])
                if isinstance(checks, list):
                    for check in checks:
                        if not isinstance(check, dict):
                            continue
                        check_name = str(check.get("name", "")).strip()
                        if not check_name:
                            continue
                        check_pass = 1.0 if bool(check.get("pass", False)) else 0.0
                        labels_gate = {
                            "gate": check_name,
                            "severity": str(check.get("severity", "")),
                            "source": "promotion_latest",
                        }
                        lines.append(f"hbot_control_plane_gate_status{_fmt_labels(labels_gate)} {check_pass}")
            elif report_name == "strict_cycle":
                status = str(payload.get("strict_gate_status", payload.get("status", ""))).strip().lower()
                lines.append(
                    f'hbot_control_plane_gate_status{{gate="strict_cycle"}} {_status_to_bool(status, ("pass",))}'
                )
                lines.append(
                    f'hbot_control_plane_finding_count{{report="strict_cycle_critical_failures"}} {float(len(payload.get("critical_failures", [])))}'
                )
            elif report_name == "day2_gate":
                day2_go = bool(payload.get("go", False))
                lines.append(f'hbot_control_plane_gate_status{{gate="day2_go"}} {1.0 if day2_go else 0.0}')
                checks = payload.get("checks", [])
                failed_checks = 0
                if isinstance(checks, list):
                    failed_checks = len([c for c in checks if isinstance(c, dict) and not bool(c.get("pass", False))])
                lines.append(f'hbot_control_plane_finding_count{{report="day2_gate_failed_checks"}} {float(failed_checks)}')
            elif report_name == "reconciliation":
                lines.append(
                    f'hbot_control_plane_gate_status{{gate="reconciliation_ok"}} {_status_to_bool(str(payload.get("status", "")), ("ok", "warning"))}'
                )
                lines.append(
                    f'hbot_control_plane_finding_count{{report="reconciliation_critical_count"}} {float(payload.get("critical_count", 0) or 0)}'
                )
            elif report_name == "parity":
                lines.append(
                    f'hbot_control_plane_gate_status{{gate="parity_pass"}} {_status_to_bool(str(payload.get("status", "")), ("pass",))}'
                )
                lines.append(
                    f'hbot_control_plane_finding_count{{report="parity_failed_bots"}} {float(payload.get("failed_bots", 0) or 0)}'
                )
            elif report_name == "portfolio_risk":
                lines.append(
                    f'hbot_control_plane_gate_status{{gate="portfolio_risk_ok"}} {_status_to_bool(str(payload.get("status", "")), ("ok", "warning"))}'
                )
                lines.append(
                    f'hbot_control_plane_finding_count{{report="portfolio_risk_critical_count"}} {float(payload.get("critical_count", 0) or 0)}'
                )
            elif report_name == "market_data":
                lines.append(
                    f'hbot_control_plane_gate_status{{gate="market_data_fresh"}} {_status_to_bool(str(payload.get("status", "")), ("pass", "ok"))}'
                )
                lines.append(
                    f'hbot_control_plane_finding_count{{report="market_data_event_rows"}} {float(payload.get("market_data_event_rows", 0) or 0)}'
                )
            elif report_name == "ops_db_writer":
                lines.append(
                    f'hbot_control_plane_gate_status{{gate="ops_db_writer_ok"}} {_status_to_bool(str(payload.get("status", "")), ("pass", "ok"))}'
                )
                counts = payload.get("counts", {})
                if isinstance(counts, dict):
                    for table_name, value in counts.items():
                        if isinstance(value, dict):
                            for metric_name, metric_value in value.items():
                                if isinstance(metric_value, dict):
                                    continue
                                lines.append(
                                    f'hbot_control_plane_finding_count{{report="ops_db_writer_count",table="{_escape_label(str(table_name))}",metric="{_escape_label(str(metric_name))}"}} {_safe_float(metric_value, 0.0)}'
                                )
                            continue
                        lines.append(
                            f'hbot_control_plane_finding_count{{report="ops_db_writer_count",table="{_escape_label(str(table_name))}"}} {_safe_float(value, 0.0)}'
                        )
            elif report_name == "coordination":
                lines.append(
                    f'hbot_control_plane_gate_status{{gate="coordination_runtime_ok"}} {_status_to_bool(str(payload.get("status", "")), ("ok", "warning"))}'
                )
                state = str(payload.get("state", "unknown")).strip() or "unknown"
                lines.append(f'hbot_control_plane_gate_status{{gate="coordination_runtime_active"}} {1.0 if state == "active" else 0.0}')
                lines.append(
                    f"hbot_control_plane_finding_count{{report=\"coordination_decisions_seen\"}} {float(payload.get('decisions_seen', 0) or 0)}"
                )
                lines.append(
                    f"hbot_control_plane_finding_count{{report=\"coordination_intents_emitted\"}} {float(payload.get('intents_emitted', 0) or 0)}"
                )
                lines.append(f'hbot_coordination_runtime_state{{state="{_escape_label(state)}"}} 1')
                lines.append(f"hbot_coordination_decisions_seen {float(payload.get('decisions_seen', 0) or 0)}")
                lines.append(f"hbot_coordination_intents_emitted {float(payload.get('intents_emitted', 0) or 0)}")
                allowed_instances = payload.get("allowed_instances", [])
                if isinstance(allowed_instances, list):
                    for instance in allowed_instances:
                        lines.append(
                            f'hbot_coordination_allowed_instance_info{{instance="{_escape_label(str(instance))}"}} 1'
                        )
            elif report_name == "coordination_policy":
                lines.append(
                    f'hbot_control_plane_gate_status{{gate="coordination_policy_ok"}} {_status_to_bool(str(payload.get("status", "")), ("pass",))}'
                )
                errors = payload.get("errors", [])
                lines.append(
                    f'hbot_control_plane_finding_count{{report="coordination_policy_error_count"}} {float(len(errors) if isinstance(errors, list) else 0)}'
                )
            elif report_name == "portfolio_allocator":
                alloc_status = str(payload.get("status", "")).strip().lower()
                lines.append(
                    f'hbot_control_plane_gate_status{{gate="portfolio_allocator_ok"}} {_status_to_bool(alloc_status, ("pass",))}'
                )
                lines.append(
                    f'hbot_control_plane_finding_count{{report="portfolio_allocator_reason_count"}} {float(len(payload.get("reasons", [])) if isinstance(payload.get("reasons"), list) else 0)}'
                )

                proposals = payload.get("proposals", [])
                if isinstance(proposals, list):
                    for row in proposals:
                        if not isinstance(row, dict):
                            continue
                        bot = str(row.get("bot", "")).strip()
                        if not bot:
                            continue
                        bot_labels = {"bot": bot}
                        lines.append(
                            f"hbot_portfolio_allocator_allocation_pct{_fmt_labels(bot_labels)} {_safe_float(row.get('allocation_pct'), 0.0)}"
                        )
                        lines.append(
                            f"hbot_portfolio_allocator_target_notional_quote{_fmt_labels(bot_labels)} {_safe_float(row.get('target_notional_quote'), 0.0)}"
                        )
                        lines.append(
                            f"hbot_portfolio_allocator_daily_goal_bot_target_pct{_fmt_labels(bot_labels)} {_safe_float(row.get('daily_pnl_target_pct'), 0.0)}"
                        )
                        lines.append(
                            f"hbot_portfolio_allocator_daily_goal_bot_target_quote{_fmt_labels(bot_labels)} {_safe_float(row.get('daily_pnl_target_quote'), 0.0)}"
                        )

                daily_goal = payload.get("daily_goal", {})
                daily_goal = daily_goal if isinstance(daily_goal, dict) else {}
                daily_goal_enabled = bool(daily_goal.get("enabled", False))
                daily_goal_status = str(daily_goal.get("status", "unknown")).strip().lower() or "unknown"
                distribution = str(daily_goal.get("distribution", "unknown")).strip().lower() or "unknown"
                distribution_effective = (
                    str(daily_goal.get("distribution_effective", distribution)).strip().lower() or distribution
                )
                lines.append(f"hbot_portfolio_allocator_daily_goal_enabled {1.0 if daily_goal_enabled else 0.0}")
                lines.append(
                    f"hbot_portfolio_allocator_daily_goal_ok {_status_to_bool(daily_goal_status, ('pass',))}"
                )
                lines.append(
                    f"hbot_portfolio_allocator_daily_goal_target_pct_total_equity {_safe_float(daily_goal.get('target_pct_total_equity'), 0.0)}"
                )
                lines.append(
                    f"hbot_portfolio_allocator_daily_goal_target_quote_total_equity {_safe_float(daily_goal.get('target_quote_total_equity'), 0.0)}"
                )
                lines.append(
                    f"hbot_portfolio_allocator_daily_goal_scope_equity_quote {_safe_float(daily_goal.get('goal_scope_equity_quote'), 0.0)}"
                )
                lines.append(
                    f"hbot_portfolio_allocator_daily_goal_target_quote_distributed {_safe_float(daily_goal.get('target_quote_distributed'), 0.0)}"
                )
                goal_info_labels = {
                    "status": daily_goal_status,
                    "distribution": distribution,
                    "distribution_effective": distribution_effective,
                }
                lines.append(f"hbot_portfolio_allocator_daily_goal_info{_fmt_labels(goal_info_labels)} 1")
            elif report_name == "reliability_slo":
                rel_status = str(payload.get("status", "")).strip().lower()
                lines.append(
                    f'hbot_control_plane_gate_status{{gate="reliability_slo_pass"}} {_status_to_bool(rel_status, ("pass",))}'
                )
                failed_checks = payload.get("failed_checks", [])
                lines.append(
                    f'hbot_control_plane_finding_count{{report="reliability_slo_failed_checks"}} {float(len(failed_checks) if isinstance(failed_checks, list) else 0)}'
                )
                details = payload.get("details", {})
                if isinstance(details, dict):
                    dead = details.get("dead_letter", {})
                    if isinstance(dead, dict):
                        lines.append(
                            f'hbot_control_plane_finding_count{{report="reliability_slo_dead_letter_critical"}} {float(dead.get("critical_count", 0) or 0)}'
                        )
                    redis_diag = details.get("redis", {})
                    if isinstance(redis_diag, dict):
                        groups = redis_diag.get("group_stats", {})
                        if isinstance(groups, dict):
                            for group_name, group_stats in groups.items():
                                if not isinstance(group_stats, dict):
                                    continue
                                labels = {"report": "reliability_slo_group_lag", "group": str(group_name)}
                                lines.append(
                                    f"hbot_control_plane_finding_count{_fmt_labels(labels)} {float(group_stats.get('lag', 0) or 0)}"
                                )
                                labels_pending = {"report": "reliability_slo_group_pending", "group": str(group_name)}
                                lines.append(
                                    f"hbot_control_plane_finding_count{_fmt_labels(labels_pending)} {float(group_stats.get('pending', 0) or 0)}"
                                )
            elif report_name == "soak":
                lines.append(
                    f'hbot_control_plane_gate_status{{gate="soak_ready"}} {_status_to_bool(str(payload.get("status", "")), ("ready", "pass"))}'
                )
                blockers = payload.get("blockers", [])
                lines.append(
                    f'hbot_control_plane_finding_count{{report="soak_blocker_count"}} {float(len(blockers) if isinstance(blockers, list) else 0)}'
                )
            elif report_name == "event_store_integrity":
                missing = float(payload.get("missing_correlation_count", 0) or 0)
                lines.append(
                    f'hbot_control_plane_gate_status{{gate="event_store_integrity_ok"}} {1.0 if missing == 0 else 0.0}'
                )
                lines.append(f'hbot_control_plane_finding_count{{report="event_store_missing_correlation"}} {missing}')
            elif report_name == "readiness":
                lines.append(
                    f'hbot_control_plane_gate_status{{gate="readiness_go"}} {_status_to_bool(str(payload.get("status", "")), ("go",))}'
                )
                blockers = payload.get("blockers", [])
                lines.append(
                    f'hbot_control_plane_finding_count{{report="readiness_blocker_count"}} {float(len(blockers) if isinstance(blockers, list) else 0)}'
                )

        exchange_snapshot = _read_json(self._reports_root / "exchange_snapshots" / "latest.json")
        bots = exchange_snapshot.get("bots", {})
        if isinstance(bots, dict):
            for bot, bot_payload in bots.items():
                if not isinstance(bot_payload, dict):
                    continue
                labels = {
                    "bot": str(bot),
                    "exchange": str(bot_payload.get("exchange", "")),
                    "pair": str(bot_payload.get("trading_pair", "")),
                    "source": str(bot_payload.get("source", "")),
                }
                lines.append(
                    f"hbot_exchange_snapshot_equity_quote{_fmt_labels(labels)} {_safe_float(bot_payload.get('equity_quote'), 0.0)}"
                )
                lines.append(
                    f"hbot_exchange_snapshot_base_pct{_fmt_labels(labels)} {_safe_float(bot_payload.get('base_pct'), 0.0)}"
                )
                status = str(bot_payload.get("account_probe_status", "unknown"))
                probe_labels = dict(labels)
                probe_labels["status"] = status
                lines.append(f"hbot_exchange_snapshot_probe_status{_fmt_labels(probe_labels)} 1")

        expected_bots = [str(b) for b in bots] if isinstance(bots, dict) else []
        for blotter in self._bot_blotter_metrics(expected_bots=expected_bots):
            bot_labels = {"bot": str(blotter.get("bot", "")), "variant": str(blotter.get("variant", ""))}
            last_fill_ts = float(blotter.get("last_fill_ts_epoch", 0.0) or 0.0)
            age_sec = max(0.0, now.timestamp() - last_fill_ts) if last_fill_ts > 0 else 1e9
            lines.append(f"hbot_bot_blotter_fills_total{_fmt_labels(bot_labels)} {float(blotter.get('fills_total', 0.0))}")
            lines.append(f"hbot_bot_blotter_last_fill_timestamp_seconds{_fmt_labels(bot_labels)} {last_fill_ts}")
            lines.append(f"hbot_bot_blotter_last_fill_age_seconds{_fmt_labels(bot_labels)} {age_sec}")

        lines.extend(self._paper_exchange_service_metrics(now))
        lines.extend(self._paper_exchange_load_report_metrics(now))
        lines.extend(self._paper_exchange_threshold_metrics(now))
        lines.extend(self._paper_exchange_command_journal_metrics(now))
        lines.extend(self._paper_exchange_pair_snapshot_metrics(now))
        lines.extend(self._kill_switch_metrics(now))

        return "\n".join(lines) + "\n"

    def _kill_switch_metrics(self, now: datetime) -> list[str]:
        """Emit hbot_bot_kill_switch_count from reports/kill_switch/latest.json."""
        lines: list[str] = [
            "# HELP hbot_bot_kill_switch_count Kill switch trigger count per bot.",
            "# TYPE hbot_bot_kill_switch_count gauge",
        ]
        ks_path = self._reports_root / "kill_switch" / "latest.json"
        payload = _read_json(ks_path)
        if not payload:
            return lines
        bots = payload.get("bots", {})
        if isinstance(bots, dict):
            for bot, bot_data in bots.items():
                if not isinstance(bot_data, dict):
                    continue
                count = float(_safe_int(bot_data.get("trigger_count", bot_data.get("count", 0)), 0))
                labels = {"bot": str(bot)}
                lines.append(f"hbot_bot_kill_switch_count{_fmt_labels(labels)} {count}")
        elif isinstance(payload.get("trigger_count"), (int, float)):
            lines.append(f"hbot_bot_kill_switch_count {float(payload['trigger_count'])}")
        elif isinstance(payload.get("count"), (int, float)):
            lines.append(f"hbot_bot_kill_switch_count {float(payload['count'])}")
        return lines


class MetricsHandler(BaseHTTPRequestHandler):
    exporter: ControlPlaneMetricsExporter
    metrics_path: str = "/metrics"

    def do_GET(self) -> None:
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
            return
        if self.path != self.metrics_path:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"not found")
            return
        body = self.exporter.render_prometheus().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        return


def main() -> None:
    reports_root = Path(os.getenv("HB_REPORTS_ROOT", "/workspace/hbot/reports")).resolve()
    data_root = Path(os.getenv("HB_DATA_ROOT", "/workspace/hbot/data")).resolve()
    port = _env_int("CONTROL_PLANE_METRICS_PORT", 9401)
    metrics_path = os.getenv("CONTROL_PLANE_METRICS_PATH", "/metrics")
    freshness_max_sec = _env_int("CONTROL_PLANE_FRESHNESS_MAX_SEC", 1800)
    redis_host = os.getenv("REDIS_HOST", "redis")
    redis_port = _env_int("REDIS_PORT", 6379)
    redis_db = _env_int("REDIS_DB", 0)
    redis_password = os.getenv("REDIS_PASSWORD", "")
    redis_enabled = str(os.getenv("REDIS_ENABLED", "true")).strip().lower() not in {"0", "false", "no"}
    paper_exchange_heartbeat_stream = os.getenv(
        "PAPER_EXCHANGE_HEARTBEAT_STREAM", "hb.paper_exchange.heartbeat.v1"
    )
    paper_exchange_heartbeat_max_age_sec = _env_int("PAPER_EXCHANGE_HEARTBEAT_MAX_AGE_SEC", 30)
    paper_exchange_load_report_path = os.getenv(
        "PAPER_EXCHANGE_LOAD_REPORT_PATH", "verification/paper_exchange_load_latest.json"
    )
    paper_exchange_threshold_inputs_path = os.getenv(
        "PAPER_EXCHANGE_THRESHOLD_INPUTS_PATH", "verification/paper_exchange_threshold_inputs_latest.json"
    )
    paper_exchange_command_journal_path = os.getenv(
        "PAPER_EXCHANGE_COMMAND_JOURNAL_PATH", "verification/paper_exchange_command_journal_latest.json"
    )
    paper_exchange_state_snapshot_path = os.getenv(
        "PAPER_EXCHANGE_STATE_SNAPSHOT_PATH", "verification/paper_exchange_state_snapshot_latest.json"
    )
    paper_exchange_pair_snapshot_path = os.getenv(
        "PAPER_EXCHANGE_PAIR_SNAPSHOT_PATH", "verification/paper_exchange_pair_snapshot_latest.json"
    )
    paper_exchange_market_fill_journal_path = os.getenv(
        "PAPER_EXCHANGE_MARKET_FILL_JOURNAL_PATH", "verification/paper_exchange_market_fill_journal_latest.json"
    )

    exporter = ControlPlaneMetricsExporter(
        reports_root=reports_root,
        data_root=data_root,
        freshness_max_sec=freshness_max_sec,
        redis_host=redis_host,
        redis_port=redis_port,
        redis_db=redis_db,
        redis_password=redis_password,
        redis_enabled=redis_enabled,
        paper_exchange_heartbeat_stream=paper_exchange_heartbeat_stream,
        paper_exchange_heartbeat_max_age_sec=paper_exchange_heartbeat_max_age_sec,
        paper_exchange_load_report_path=paper_exchange_load_report_path,
        paper_exchange_threshold_inputs_path=paper_exchange_threshold_inputs_path,
        paper_exchange_command_journal_path=paper_exchange_command_journal_path,
        paper_exchange_state_snapshot_path=paper_exchange_state_snapshot_path,
        paper_exchange_pair_snapshot_path=paper_exchange_pair_snapshot_path,
        paper_exchange_market_fill_journal_path=paper_exchange_market_fill_journal_path,
    )
    MetricsHandler.exporter = exporter
    MetricsHandler.metrics_path = metrics_path

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logger = logging.getLogger("control_plane_metrics_exporter")

    server = ThreadingHTTPServer(("0.0.0.0", port), MetricsHandler)
    logger.info(
        "listening on :%d%s, reports_root=%s, data_root=%s, freshness_max_sec=%d, "
        "redis_host=%s, redis_port=%d, stream=%s, heartbeat_max_age_sec=%d",
        port, metrics_path, reports_root, data_root, freshness_max_sec,
        redis_host, redis_port, paper_exchange_heartbeat_stream, paper_exchange_heartbeat_max_age_sec
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
