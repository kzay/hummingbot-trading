from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path, default: Dict[str, object]) -> Dict[str, object]:
    if not path.exists():
        return default
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else default
    except Exception:
        return default


def _build_subprocess_env(root: Path) -> Dict[str, str]:
    env = os.environ.copy()
    root_str = str(root)
    current = env.get("PYTHONPATH", "")
    parts = [p for p in current.split(os.pathsep) if p]
    if root_str not in parts:
        parts.insert(0, root_str)
    env["PYTHONPATH"] = os.pathsep.join(parts)
    return env


def _run_step(root: Path, label: str, cmd: List[str]) -> Dict[str, object]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
            env=_build_subprocess_env(root),
        )
        out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return {"name": label, "rc": int(proc.returncode), "output": out[:2000]}
    except Exception as exc:
        return {"name": label, "rc": 99, "output": str(exc)}


def _latest_matching(path: Path, pattern: str) -> Path | None:
    files = sorted(path.glob(pattern))
    if not files:
        return None
    return files[-1]


def _count_events_at_least(path: Path, minimum: int) -> int:
    count = 0
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    count += 1
                    if count >= minimum:
                        return count
    except Exception:
        return 0
    return count


def _latest_events_with_min(path: Path, minimum: int) -> Path | None:
    files = sorted(path.glob("events_*.jsonl"), reverse=True)
    for fp in files:
        if _count_events_at_least(fp, minimum) >= minimum:
            return fp
    return files[0] if files else None


def _matching_integrity_for_event(event_file: Path | None, event_store_dir: Path) -> Path | None:
    if not event_file:
        return _latest_matching(event_store_dir, "integrity_*.json")
    suffix = event_file.name.replace("events_", "").replace(".jsonl", "")
    candidate = event_store_dir / f"integrity_{suffix}.json"
    if candidate.exists():
        return candidate
    return _latest_matching(event_store_dir, "integrity_*.json")


def _collect_snapshot(root: Path) -> Dict[str, object]:
    reg = _read_json(root / "reports" / "backtest_regression" / "latest.json", {})
    recon = _read_json(root / "reports" / "reconciliation" / "latest.json", {})
    parity = _read_json(root / "reports" / "parity" / "latest.json", {})
    risk = _read_json(root / "reports" / "portfolio_risk" / "latest.json", {})

    return {
        "regression": {
            "status": str(reg.get("status", "fail")),
            "event_count": int(reg.get("dataset_fingerprint", {}).get("event_count", 0))
            if isinstance(reg.get("dataset_fingerprint"), dict)
            else 0,
            "fingerprint": str(reg.get("dataset_fingerprint", {}).get("sha256", ""))
            if isinstance(reg.get("dataset_fingerprint"), dict)
            else "",
            "path": str(root / "reports" / "backtest_regression" / "latest.json"),
        },
        "reconciliation": {
            "status": str(recon.get("status", "critical")),
            "critical_count": int(recon.get("critical_count", 1)),
            "warning_count": int(recon.get("warning_count", 0)),
            "checked_bots": int(recon.get("checked_bots", 0)),
            "path": str(root / "reports" / "reconciliation" / "latest.json"),
        },
        "parity": {
            "status": str(parity.get("status", "fail")),
            "failed_bots": int(parity.get("failed_bots", 999)),
            "checked_bots": int(parity.get("checked_bots", 0)),
            "path": str(root / "reports" / "parity" / "latest.json"),
        },
        "portfolio_risk": {
            "status": str(risk.get("status", "critical")),
            "critical_count": int(risk.get("critical_count", 1)),
            "warning_count": int(risk.get("warning_count", 0)),
            "portfolio_action": str(risk.get("portfolio_action", "unknown")),
            "path": str(root / "reports" / "portfolio_risk" / "latest.json"),
        },
    }


def _evaluate_snapshot(snapshot: Dict[str, object]) -> Tuple[bool, List[str]]:
    failures: List[str] = []
    reg = snapshot.get("regression", {}) if isinstance(snapshot.get("regression"), dict) else {}
    recon = snapshot.get("reconciliation", {}) if isinstance(snapshot.get("reconciliation"), dict) else {}
    parity = snapshot.get("parity", {}) if isinstance(snapshot.get("parity"), dict) else {}
    risk = snapshot.get("portfolio_risk", {}) if isinstance(snapshot.get("portfolio_risk"), dict) else {}

    if str(reg.get("status", "fail")) != "pass":
        failures.append("regression_not_pass")
    if not str(reg.get("fingerprint", "")):
        failures.append("regression_fingerprint_missing")
    if str(recon.get("status", "critical")) not in {"ok", "warning"} or int(recon.get("critical_count", 1)) > 0:
        failures.append("reconciliation_not_healthy")
    if str(parity.get("status", "fail")) != "pass":
        failures.append("parity_not_pass")
    if str(risk.get("status", "critical")) not in {"ok", "warning"} or int(risk.get("critical_count", 1)) > 0:
        failures.append("portfolio_risk_not_healthy")
    return (len(failures) == 0), failures


def _snapshot_signature(snapshot: Dict[str, object]) -> Dict[str, object]:
    reg = snapshot.get("regression", {}) if isinstance(snapshot.get("regression"), dict) else {}
    recon = snapshot.get("reconciliation", {}) if isinstance(snapshot.get("reconciliation"), dict) else {}
    parity = snapshot.get("parity", {}) if isinstance(snapshot.get("parity"), dict) else {}
    risk = snapshot.get("portfolio_risk", {}) if isinstance(snapshot.get("portfolio_risk"), dict) else {}
    return {
        "regression_status": str(reg.get("status", "")),
        "regression_fingerprint": str(reg.get("fingerprint", "")),
        "regression_event_count": int(reg.get("event_count", 0)),
        "reconciliation_status": str(recon.get("status", "")),
        "reconciliation_critical_count": int(recon.get("critical_count", 0)),
        "reconciliation_warning_count": int(recon.get("warning_count", 0)),
        "parity_status": str(parity.get("status", "")),
        "parity_failed_bots": int(parity.get("failed_bots", 0)),
        "portfolio_status": str(risk.get("status", "")),
        "portfolio_critical_count": int(risk.get("critical_count", 0)),
        "portfolio_action": str(risk.get("portfolio_action", "")),
    }


def _freeze_inputs(
    out_root: Path, event_file: Path | None, integrity_file: Path | None
) -> Tuple[Path | None, Path | None, Path | None]:
    if not event_file and not integrity_file:
        return None, None, None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snap_dir = out_root / "pinned_inputs" / stamp
    snap_dir.mkdir(parents=True, exist_ok=True)

    frozen_event: Path | None = None
    frozen_integrity: Path | None = None
    if event_file and event_file.exists():
        frozen_event = snap_dir / event_file.name
        shutil.copy2(event_file, frozen_event)
    if integrity_file and integrity_file.exists():
        frozen_integrity = snap_dir / integrity_file.name
        shutil.copy2(integrity_file, frozen_integrity)
    return frozen_event, frozen_integrity, snap_dir


def _write_markdown(path: Path, payload: Dict[str, object]) -> None:
    runs = payload.get("runs", []) if isinstance(payload.get("runs"), list) else []
    blockers = payload.get("blockers", []) if isinstance(payload.get("blockers"), list) else []
    evidence_paths = payload.get("evidence_paths", {}) if isinstance(payload.get("evidence_paths"), dict) else {}
    lines = [
        "# Replay Regression Summary",
        "",
        f"- ts_utc: {payload.get('ts_utc', '')}",
        f"- status: {payload.get('status', 'fail')}",
        f"- deterministic_repeat_pass: {payload.get('deterministic_repeat_pass', False)}",
        f"- repeat_runs: {payload.get('repeat_runs', 0)}",
        "",
        "## Blockers",
    ]
    if blockers:
        lines.extend([f"- {b}" for b in blockers])
    else:
        lines.append("- none")
    lines.extend(["", "## Evidence Paths"])
    for key, value in evidence_paths.items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Run Snapshots"])
    for idx, run in enumerate(runs, start=1):
        sig = run.get("signature", {}) if isinstance(run, dict) else {}
        lines.append(f"- run_{idx}: {json.dumps(sig, sort_keys=True)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic replay->reconcile->parity->risk regression cycle.")
    parser.add_argument("--repeat", type=int, default=2, help="How many consecutive cycles to run for stability check.")
    parser.add_argument("--min-events", type=int, default=1000, help="Minimum events for backtest regression step.")
    args = parser.parse_args()

    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    out_root = root / "reports" / "replay_regression"
    out_root.mkdir(parents=True, exist_ok=True)
    event_store_dir = root / "reports" / "event_store"
    pinned_event_file = _latest_events_with_min(event_store_dir, minimum=max(1, int(args.min_events)))
    pinned_integrity_file = _matching_integrity_for_event(pinned_event_file, event_store_dir)
    frozen_event_file, frozen_integrity_file, frozen_inputs_dir = _freeze_inputs(
        out_root=out_root,
        event_file=pinned_event_file,
        integrity_file=pinned_integrity_file,
    )

    all_runs: List[Dict[str, object]] = []
    blockers: List[str] = []
    repeat = max(1, int(args.repeat))

    for _ in range(repeat):
        regression_cmd = [
            sys.executable,
            str(root / "scripts" / "release" / "run_backtest_regression.py"),
            "--min-events",
            str(args.min_events),
        ]
        if frozen_event_file:
            regression_cmd.extend(["--event-file", str(frozen_event_file)])
        if frozen_integrity_file:
            regression_cmd.extend(["--integrity-file", str(frozen_integrity_file)])

        steps = [
            _run_step(root, "backtest_regression", regression_cmd),
            _run_step(
                root,
                "reconciliation_once",
                [sys.executable, str(root / "services" / "reconciliation_service" / "main.py"), "--once"],
            ),
            _run_step(
                root,
                "parity_once",
                [sys.executable, str(root / "services" / "shadow_execution" / "main.py"), "--once"],
            ),
            _run_step(
                root,
                "portfolio_risk_once",
                [sys.executable, str(root / "services" / "portfolio_risk_service" / "main.py"), "--once"],
            ),
        ]
        step_failures = [str(s.get("name")) for s in steps if int(s.get("rc", 1)) != 0]
        snapshot = _collect_snapshot(root)
        snapshot_ok, snapshot_failures = _evaluate_snapshot(snapshot)
        all_runs.append(
            {
                "steps": steps,
                "step_failures": step_failures,
                "snapshot": snapshot,
                "snapshot_ok": snapshot_ok,
                "snapshot_failures": snapshot_failures,
                "signature": _snapshot_signature(snapshot),
            }
        )

    if all_runs:
        baseline_sig = all_runs[0].get("signature", {})
        deterministic_repeat_pass = all(
            isinstance(r.get("signature"), dict) and r.get("signature") == baseline_sig for r in all_runs[1:]
        )
    else:
        deterministic_repeat_pass = False
        baseline_sig = {}

    for idx, run in enumerate(all_runs, start=1):
        if run.get("step_failures"):
            blockers.append(f"run_{idx}_step_failures:{','.join(run['step_failures'])}")
        if run.get("snapshot_failures"):
            blockers.append(f"run_{idx}_snapshot_failures:{','.join(run['snapshot_failures'])}")
    if not deterministic_repeat_pass and repeat > 1:
        blockers.append("deterministic_repeat_check_failed")

    status = "pass" if not blockers else "fail"
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = out_root / f"replay_regression_{ts}.json"
    md_path = out_root / f"replay_regression_{ts}.md"

    payload = {
        "ts_utc": _utc_now(),
        "status": status,
        "repeat_runs": repeat,
        "deterministic_repeat_pass": deterministic_repeat_pass,
        "signature_baseline": baseline_sig,
        "blockers": blockers,
        "runs": all_runs,
        "evidence_paths": {
            "source_event_file": str(pinned_event_file) if pinned_event_file else "",
            "source_integrity_file": str(pinned_integrity_file) if pinned_integrity_file else "",
            "frozen_event_file": str(frozen_event_file) if frozen_event_file else "",
            "frozen_integrity_file": str(frozen_integrity_file) if frozen_integrity_file else "",
            "frozen_inputs_dir": str(frozen_inputs_dir) if frozen_inputs_dir else "",
            "backtest_regression_latest": str(root / "reports" / "backtest_regression" / "latest.json"),
            "reconciliation_latest": str(root / "reports" / "reconciliation" / "latest.json"),
            "parity_latest": str(root / "reports" / "parity" / "latest.json"),
            "portfolio_risk_latest": str(root / "reports" / "portfolio_risk" / "latest.json"),
            "json_report": str(json_path),
            "markdown_report": str(md_path),
        },
    }

    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (out_root / "latest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _write_markdown(md_path, payload)
    _write_markdown(out_root / "latest.md", payload)

    print(f"[replay-regression] status={status}")
    print(f"[replay-regression] evidence={json_path}")
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
