from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_incident_note(incidents_path: Path, message: str) -> None:
    incidents_path.parent.mkdir(parents=True, exist_ok=True)
    if not incidents_path.exists():
        incidents_path.write_text("# Incident Playbook\n\n", encoding="utf-8")
    with incidents_path.open("a", encoding="utf-8") as f:
        f.write(f"- {_utc_now()} - {message}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run strict promotion cycle with parity refresh.")
    parser.add_argument("--max-report-age-min", type=int, default=20, help="Max freshness window in minutes.")
    parser.add_argument(
        "--day2-max-delta",
        type=int,
        default=6,
        help="Absolute per-stream lag tolerance for day2 gate.",
    )
    parser.add_argument(
        "--append-incident-on-fail",
        action="store_true",
        help="Append a short incident note to docs/ops/incidents.md when strict gate fails.",
    )
    parser.add_argument(
        "--check-paper-exchange-thresholds",
        action="store_true",
        default=str(os.getenv("STRICT_REQUIRE_PAPER_EXCHANGE_THRESHOLDS", "false")).strip().lower()
        in {"1", "true", "yes", "on"},
        help="Enable quantitative paper-exchange threshold gate in strict cycle.",
    )
    parser.add_argument(
        "--check-paper-exchange-preflight",
        action="store_true",
        default=str(os.getenv("STRICT_REQUIRE_PAPER_EXCHANGE_PREFLIGHT", "false")).strip().lower()
        in {"1", "true", "yes", "on"},
        help="Enable paper-exchange wiring preflight gate in strict cycle.",
    )
    parser.add_argument(
        "--paper-exchange-threshold-max-age-min",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_THRESHOLD_MAX_AGE_MIN", "20")),
        help="Max allowed age (minutes) for paper-exchange threshold input artifact.",
    )
    parser.add_argument(
        "--run-paper-exchange-load-harness",
        action="store_true",
        default=str(os.getenv("STRICT_RUN_PAPER_EXCHANGE_LOAD_HARNESS", "false")).strip().lower()
        in {"1", "true", "yes", "on"},
        help="Inject synthetic paper-exchange load before threshold evaluation in strict cycle.",
    )
    parser.add_argument(
        "--paper-exchange-load-harness-duration-sec",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_DURATION_SEC", "20")),
        help="Duration for strict-cycle paper-exchange load harness.",
    )
    parser.add_argument(
        "--paper-exchange-load-harness-target-cmd-rate",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_TARGET_CMD_RATE", "60")),
        help="Target command rate for strict-cycle paper-exchange load harness.",
    )
    parser.add_argument(
        "--paper-exchange-load-harness-min-commands",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_MIN_COMMANDS", "300")),
        help="Minimum commands for strict-cycle paper-exchange load harness pass criteria.",
    )
    parser.add_argument(
        "--paper-exchange-load-command-stream",
        default=os.getenv("PAPER_EXCHANGE_COMMAND_STREAM", "hb.paper_exchange.command.v1"),
        help="Command stream used by strict-cycle paper-exchange load checks.",
    )
    parser.add_argument(
        "--paper-exchange-load-event-stream",
        default=os.getenv("PAPER_EXCHANGE_EVENT_STREAM", "hb.paper_exchange.event.v1"),
        help="Event stream used by strict-cycle paper-exchange load checks.",
    )
    parser.add_argument(
        "--paper-exchange-load-heartbeat-stream",
        default=os.getenv("PAPER_EXCHANGE_HEARTBEAT_STREAM", "hb.paper_exchange.heartbeat.v1"),
        help="Heartbeat stream used by strict-cycle paper-exchange load checks.",
    )
    parser.add_argument(
        "--paper-exchange-load-consumer-group",
        default=os.getenv("PAPER_EXCHANGE_CONSUMER_GROUP", "hb_group_paper_exchange"),
        help="Consumer group used by strict-cycle paper-exchange load checker.",
    )
    parser.add_argument(
        "--paper-exchange-load-heartbeat-consumer-group",
        default=os.getenv("PAPER_EXCHANGE_CONSUMER_GROUP", ""),
        help="Optional heartbeat metadata consumer_group filter for strict-cycle load checker.",
    )
    parser.add_argument(
        "--paper-exchange-load-heartbeat-consumer-name",
        default=os.getenv("PAPER_EXCHANGE_CONSUMER_NAME", ""),
        help="Optional heartbeat metadata consumer_name filter for strict-cycle load checker.",
    )
    parser.add_argument(
        "--paper-exchange-load-lookback-sec",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_LOAD_LOOKBACK_SEC", "600")),
        help="Load checker lookback window for strict cycle.",
    )
    parser.add_argument(
        "--paper-exchange-load-min-window-sec",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_LOAD_MIN_WINDOW_SEC", "120")),
        help="Minimum command window required by strict-cycle load checker.",
    )
    parser.add_argument(
        "--paper-exchange-load-run-id",
        default=os.getenv("PAPER_EXCHANGE_LOAD_RUN_ID", ""),
        help="Optional run_id filter forwarded to strict-cycle load checker.",
    )
    parser.add_argument(
        "--check-dashboard-readiness",
        action="store_true",
        default=str(os.getenv("STRICT_CHECK_DASHBOARD_READINESS", "true")).strip().lower()
        in {"1", "true", "yes", "on"},
        help="Enforce TradeNote + Grafana dashboard data readiness in strict cycle.",
    )
    parser.add_argument(
        "--no-check-dashboard-readiness",
        action="store_false",
        dest="check_dashboard_readiness",
        help="Disable dashboard readiness gate in strict cycle.",
    )
    args = parser.parse_args()

    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    cmd = [
        sys.executable,
        str(root / "scripts" / "release" / "run_promotion_gates.py"),
        "--ci",
        "--require-day2-go",
        "--require-day2-fresh",
        "--require-day2-lag-within-tolerance",
        "--day2-max-delta",
        str(args.day2_max_delta),
        "--attempt-day2-catchup",
        "--day2-catchup-cycles",
        "2",
        "--require-parity-informative-core",
        "--refresh-parity-once",
        "--check-bot-preflight",
        "--check-recon-exchange-preflight",
        "--collect-go-live-evidence",
        "--check-telegram-validation",
        "--check-portfolio-diversification",
        "--max-report-age-min",
        str(args.max_report_age_min),
    ]
    if args.check_paper_exchange_thresholds:
        cmd.extend(
            [
                "--check-paper-exchange-thresholds",
                "--paper-exchange-threshold-max-age-min",
                str(float(args.paper_exchange_threshold_max_age_min)),
                "--paper-exchange-load-harness-duration-sec",
                str(max(0.1, float(args.paper_exchange_load_harness_duration_sec))),
                "--paper-exchange-load-harness-target-cmd-rate",
                str(max(1.0, float(args.paper_exchange_load_harness_target_cmd_rate))),
                "--paper-exchange-load-harness-min-commands",
                str(max(1, int(args.paper_exchange_load_harness_min_commands))),
                "--paper-exchange-load-command-stream",
                str(args.paper_exchange_load_command_stream),
                "--paper-exchange-load-event-stream",
                str(args.paper_exchange_load_event_stream),
                "--paper-exchange-load-heartbeat-stream",
                str(args.paper_exchange_load_heartbeat_stream),
                "--paper-exchange-load-consumer-group",
                str(args.paper_exchange_load_consumer_group),
                "--paper-exchange-load-heartbeat-consumer-group",
                str(args.paper_exchange_load_heartbeat_consumer_group),
                "--paper-exchange-load-heartbeat-consumer-name",
                str(args.paper_exchange_load_heartbeat_consumer_name),
                "--paper-exchange-load-lookback-sec",
                str(max(1, int(args.paper_exchange_load_lookback_sec))),
                "--paper-exchange-load-min-window-sec",
                str(max(1, int(args.paper_exchange_load_min_window_sec))),
            ]
        )
        if args.run_paper_exchange_load_harness:
            cmd.append("--run-paper-exchange-load-harness")
        if str(args.paper_exchange_load_run_id).strip():
            cmd.extend(["--paper-exchange-load-run-id", str(args.paper_exchange_load_run_id).strip()])
    if args.check_paper_exchange_preflight:
        cmd.append("--check-paper-exchange-preflight")
    if args.check_dashboard_readiness:
        cmd.append("--check-dashboard-readiness")
    proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
    out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")

    reports = root / "reports" / "promotion_gates"
    latest_path = reports / "latest.json"
    latest = {}
    if latest_path.exists():
        try:
            latest = json.loads(latest_path.read_text(encoding="utf-8"))
        except Exception:
            latest = {}

    cycle_summary = {
        "ts_utc": _utc_now(),
        "strict_gate_rc": int(proc.returncode),
        "strict_gate_status": latest.get("status", "UNKNOWN"),
        "critical_failures": latest.get("critical_failures", []),
        "gate_latest_path": str(latest_path),
        "stdout": out[:4000],
    }
    cycle_path = reports / "strict_cycle_latest.json"
    cycle_path.write_text(json.dumps(cycle_summary, indent=2), encoding="utf-8")

    if proc.returncode != 0 and args.append_incident_on_fail:
        failures = latest.get("critical_failures", [])
        msg = f"strict promotion cycle failed; critical_failures={failures}; evidence={latest_path}"
        _append_incident_note(root / "docs" / "ops" / "incidents.md", msg)

    print(f"[strict-cycle] rc={proc.returncode}")
    print(f"[strict-cycle] status={cycle_summary['strict_gate_status']}")
    print(f"[strict-cycle] evidence={cycle_path}")
    return int(proc.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
