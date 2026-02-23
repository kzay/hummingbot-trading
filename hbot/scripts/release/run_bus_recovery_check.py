from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _root() -> Path:
    return Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]


def _read_json(path: Path, default: Dict[str, object]) -> Dict[str, object]:
    if not path.exists():
        return default
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else default
    except Exception:
        return default


def _latest_matching(path: Path, pattern: str) -> Path | None:
    files = sorted(path.glob(pattern))
    return files[-1] if files else None


def _latest_matching_excluding(path: Path, pattern: str, exclude_name: str) -> Path | None:
    files = sorted([p for p in path.glob(pattern) if p.name != exclude_name])
    return files[-1] if files else None


def _run(root: Path, cmd: List[str]) -> Tuple[int, str]:
    proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
    out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    return int(proc.returncode), out.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture bus recovery health evidence.")
    parser.add_argument("--label", default="checkpoint", help="Evidence label (e.g. pre_restart/post_restart).")
    parser.add_argument("--max-delta", type=int, default=5, help="Max allowed produced/ingested delta.")
    parser.add_argument(
        "--max-delta-regression",
        type=int,
        default=50,
        help="Allowed increase in max delta from pre->post restart comparison.",
    )
    parser.add_argument(
        "--enforce-absolute-delta",
        action="store_true",
        help="Fail when absolute delta exceeds max-delta (legacy strict mode).",
    )
    args = parser.parse_args()

    root = _root()
    reports = root / "reports" / "event_store"

    rc_count, out_count = _run(root, [sys.executable, str(root / "scripts" / "utils" / "event_store_count_check.py")])
    rc_day2, out_day2 = _run(root, [sys.executable, str(root / "scripts" / "utils" / "day2_gate_evaluator.py")])

    source_compare = _latest_matching(reports, "source_compare_*.json")
    integrity = _latest_matching(reports, "integrity_*.json")
    day2_latest = reports / "day2_gate_eval_latest.json"

    source_data = _read_json(source_compare, {}) if source_compare else {}
    integrity_data = _read_json(integrity, {}) if integrity else {}
    day2_data = _read_json(day2_latest, {})

    delta_map = (
        source_data.get("delta_produced_minus_ingested_since_baseline", {})
        if isinstance(source_data.get("delta_produced_minus_ingested_since_baseline"), dict)
        else {}
    )
    max_delta_observed = 0
    if delta_map:
        max_delta_observed = max(abs(int(v)) for v in delta_map.values())

    critical_stream_deltas = {
        k: abs(int(v))
        for k, v in delta_map.items()
        if k in {"hb.execution_intent.v1", "hb.audit.v1", "hb.risk_decision.v1"}
    }
    critical_streams_present = len(critical_stream_deltas) > 0

    # Compare against previous checkpoint to detect restart-induced regressions.
    previous_path = _latest_matching_excluding(out_dir := (root / "reports" / "bus_recovery"), "bus_recovery_*.json", "")
    # If no previous file, comparison is N/A and treated as pass.
    previous = _read_json(previous_path, {}) if previous_path else {}
    previous_max_delta = int(previous.get("max_delta_observed", max_delta_observed)) if previous else max_delta_observed
    delta_regression = max_delta_observed - previous_max_delta

    checks = {
        "count_check_exit_ok": rc_count == 0,
        "day2_eval_exit_ok": rc_day2 in {0, 2},  # gate can be NO-GO because of elapsed window
        "missing_correlation_zero": int(integrity_data.get("missing_correlation_count", 1)) == 0,
        "critical_stream_deltas_present": critical_streams_present,
        "delta_not_worse_than_previous": delta_regression <= int(args.max_delta_regression),
    }
    if args.enforce_absolute_delta:
        checks["delta_since_baseline_within_tolerance"] = max_delta_observed <= int(args.max_delta)

    status = "pass" if all(checks.values()) else "fail"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_file = out_dir / f"bus_recovery_{args.label}_{stamp}.json"
    payload = {
        "ts_utc": _utc_now(),
        "label": args.label,
        "status": status,
        "checks": checks,
        "max_delta_observed": max_delta_observed,
        "delta_regression_vs_previous": delta_regression,
        "previous_checkpoint_path": str(previous_path) if previous_path else "",
        "critical_stream_deltas": critical_stream_deltas,
        "paths": {
            "integrity": str(integrity) if integrity else "",
            "source_compare": str(source_compare) if source_compare else "",
            "day2_latest": str(day2_latest),
        },
        "commands": {
            "event_store_count_check": {"rc": rc_count, "output": out_count[:1500]},
            "day2_gate_evaluator": {"rc": rc_day2, "output": out_day2[:1500]},
        },
    }
    out_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (out_dir / "latest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"[bus-recovery] status={status}")
    print(f"[bus-recovery] evidence={out_file}")
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
