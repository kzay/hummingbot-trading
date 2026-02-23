from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Optional, Tuple


from services.common.utils import (
    env_int as _env_int,
    parse_iso_ts as _safe_parse_iso_ts,
    read_json as _read_json,
    safe_float as _safe_float,
)


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _fmt_labels(labels: Dict[str, str]) -> str:
    if not labels:
        return ""
    pairs = [f'{k}="{_escape_label(v)}"' for k, v in labels.items()]
    return "{" + ",".join(pairs) + "}"


def _status_to_bool(status: str, good_values: Tuple[str, ...]) -> float:
    return 1.0 if str(status).strip().lower() in good_values else 0.0


class ControlPlaneMetricsExporter:
    def __init__(self, reports_root: Path, data_root: Path, freshness_max_sec: int = 1800):
        self._reports_root = reports_root
        self._data_root = data_root
        self._freshness_max_sec = freshness_max_sec

    def _latest_integrity_file(self) -> Path:
        event_store_root = self._reports_root / "event_store"
        candidates = sorted(event_store_root.glob("integrity_*.json"))
        if candidates:
            return candidates[-1]
        return event_store_root / "integrity_20260221.json"

    def _report_targets(self) -> Dict[str, Path]:
        return {
            "reconciliation": self._reports_root / "reconciliation" / "latest.json",
            "parity": self._reports_root / "parity" / "latest.json",
            "portfolio_risk": self._reports_root / "portfolio_risk" / "latest.json",
            "coordination": self._reports_root / "coordination" / "latest.json",
            "coordination_policy": self._reports_root / "policy" / "coordination_policy_latest.json",
            "promotion_gate": self._reports_root / "promotion_gates" / "latest.json",
            "strict_cycle": self._reports_root / "promotion_gates" / "strict_cycle_latest.json",
            "soak": self._reports_root / "soak" / "latest.json",
            "day2_gate": self._reports_root / "event_store" / "day2_gate_eval_latest.json",
            "event_store_integrity": self._latest_integrity_file(),
            "readiness": self._reports_root / "readiness" / "final_decision_latest.json",
        }

    def _read_last_csv_row(self, path: Path) -> Dict[str, str]:
        if not path.exists():
            return {}
        try:
            with path.open("r", encoding="utf-8", errors="ignore", newline="") as fp:
                reader = csv.DictReader(fp)
                last: Optional[Dict[str, str]] = None
                for row in reader:
                    last = {str(k): str(v) for k, v in row.items()}
                return last or {}
        except Exception:
            return {}

    def _bot_blotter_metrics(self, expected_bots: Optional[List[str]] = None) -> List[Dict[str, object]]:
        out: List[Dict[str, object]] = []
        seen_bots = set()
        for fills_file in self._data_root.glob("*/logs/epp_v24/*/fills.csv"):
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

    def render_prometheus(self) -> str:
        now = datetime.now(timezone.utc)
        lines: List[str] = [
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

        expected_bots = [str(b) for b in bots.keys()] if isinstance(bots, dict) else []
        for blotter in self._bot_blotter_metrics(expected_bots=expected_bots):
            bot_labels = {"bot": str(blotter.get("bot", "")), "variant": str(blotter.get("variant", ""))}
            last_fill_ts = float(blotter.get("last_fill_ts_epoch", 0.0) or 0.0)
            age_sec = max(0.0, now.timestamp() - last_fill_ts) if last_fill_ts > 0 else 1e9
            lines.append(f"hbot_bot_blotter_fills_total{_fmt_labels(bot_labels)} {float(blotter.get('fills_total', 0.0))}")
            lines.append(f"hbot_bot_blotter_last_fill_timestamp_seconds{_fmt_labels(bot_labels)} {last_fill_ts}")
            lines.append(f"hbot_bot_blotter_last_fill_age_seconds{_fmt_labels(bot_labels)} {age_sec}")

        return "\n".join(lines) + "\n"


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

    exporter = ControlPlaneMetricsExporter(reports_root=reports_root, data_root=data_root, freshness_max_sec=freshness_max_sec)
    MetricsHandler.exporter = exporter
    MetricsHandler.metrics_path = metrics_path

    server = ThreadingHTTPServer(("0.0.0.0", port), MetricsHandler)
    print(
        f"control_plane_metrics_exporter listening on :{port}{metrics_path}, "
        f"reports_root={reports_root}, data_root={data_root}, freshness_max_sec={freshness_max_sec}"
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
