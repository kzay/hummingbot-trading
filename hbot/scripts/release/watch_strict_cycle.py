from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path, default: Dict[str, object]) -> Dict[str, object]:
    if not path.exists():
        return default
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else default
    except Exception:
        return default


def _append_jsonl(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")


def _append_incident_note(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("# Incident Playbook\n\n", encoding="utf-8")
    with path.open("a", encoding="utf-8") as f:
        f.write(f"- {_utc_now()} - {message}\n")


def _run_strict_cycle(root: Path, max_report_age_min: int) -> int:
    cmd = [
        sys.executable,
        str(root / "scripts" / "release" / "run_strict_promotion_cycle.py"),
        "--max-report-age-min",
        str(max_report_age_min),
    ]
    proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
    return int(proc.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description="Watch strict promotion cycle and log state transitions.")
    parser.add_argument("--interval-sec", type=int, default=300, help="Seconds between strict cycle runs.")
    parser.add_argument("--max-runs", type=int, default=0, help="Stop after N runs (0 means infinite).")
    parser.add_argument("--max-report-age-min", type=int, default=20, help="Freshness window for strict cycle.")
    parser.add_argument(
        "--append-incident-on-transition",
        action="store_true",
        help="Append incident note only when status transitions to FAIL.",
    )
    args = parser.parse_args()

    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    reports = root / "reports" / "promotion_gates"
    state_path = reports / "strict_watch_state.json"
    transition_path = reports / "strict_watch_transitions.jsonl"
    incident_path = root / "docs" / "ops" / "incidents.md"

    run_count = 0
    while True:
        run_count += 1
        rc = _run_strict_cycle(root=root, max_report_age_min=args.max_report_age_min)
        latest = _load_json(reports / "strict_cycle_latest.json", {})
        current_status = str(latest.get("strict_gate_status", "UNKNOWN"))
        current_failures = latest.get("critical_failures", [])
        current_failures = current_failures if isinstance(current_failures, list) else []

        prev = _load_json(state_path, {})
        prev_status = str(prev.get("last_status", "UNKNOWN"))
        transitioned = current_status != prev_status

        state = {
            "ts_utc": _utc_now(),
            "run_count": run_count,
            "last_status": current_status,
            "last_rc": rc,
            "last_failures": current_failures,
            "strict_cycle_latest_path": str(reports / "strict_cycle_latest.json"),
        }
        state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

        if transitioned:
            event = {
                "ts_utc": _utc_now(),
                "from_status": prev_status,
                "to_status": current_status,
                "critical_failures": current_failures,
                "strict_cycle_latest_path": str(reports / "strict_cycle_latest.json"),
            }
            _append_jsonl(transition_path, event)
            if args.append_incident_on_transition and current_status == "FAIL":
                _append_incident_note(
                    incident_path,
                    f"strict gate status transition to FAIL; critical_failures={current_failures}; evidence={reports / 'strict_cycle_latest.json'}",
                )

        print(f"[strict-watch] run={run_count} status={current_status} rc={rc} transitioned={transitioned}")

        if args.max_runs > 0 and run_count >= args.max_runs:
            break
        time.sleep(max(30, args.interval_sec))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
