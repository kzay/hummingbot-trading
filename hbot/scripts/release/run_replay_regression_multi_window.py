from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _run_window(root: Path, min_events: int, repeat: int) -> Dict[str, object]:
    cmd = [
        sys.executable,
        str(root / "scripts" / "release" / "run_replay_regression_cycle.py"),
        "--repeat",
        str(max(1, int(repeat))),
        "--min-events",
        str(max(1, int(min_events))),
    ]
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        payload = _read_json(root / "reports" / "replay_regression" / "latest.json")
        return {
            "min_events": int(min_events),
            "rc": int(proc.returncode),
            "status": str(payload.get("status", "fail")),
            "deterministic_repeat_pass": bool(payload.get("deterministic_repeat_pass", False)),
            "blockers": payload.get("blockers", []) if isinstance(payload.get("blockers"), list) else [],
            "signature_baseline": payload.get("signature_baseline", {})
            if isinstance(payload.get("signature_baseline"), dict)
            else {},
            "report_path": str(root / "reports" / "replay_regression" / "latest.json"),
            "runner_output_tail": ((proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else ""))[-2000:],
        }
    except Exception as exc:
        return {
            "min_events": int(min_events),
            "rc": 99,
            "status": "fail",
            "deterministic_repeat_pass": False,
            "blockers": [str(exc)],
            "signature_baseline": {},
            "report_path": str(root / "reports" / "replay_regression" / "latest.json"),
            "runner_output_tail": str(exc),
        }


def _write_md(path: Path, payload: Dict[str, object]) -> None:
    windows = payload.get("windows", []) if isinstance(payload.get("windows"), list) else []
    lines = [
        "# Replay Regression Multi-Window Summary",
        "",
        f"- ts_utc: {payload.get('ts_utc', '')}",
        f"- status: {payload.get('status', 'fail')}",
        f"- repeat: {payload.get('repeat', 0)}",
        f"- windows_total: {len(windows)}",
        "",
        "## Windows",
    ]
    for w in windows:
        if not isinstance(w, dict):
            continue
        lines.append(
            f"- min_events={w.get('min_events', 0)} status={w.get('status', 'fail')} rc={w.get('rc', 1)} deterministic_repeat_pass={w.get('deterministic_repeat_pass', False)}"
        )
    lines.extend(["", "## Artifacts", "- reports/replay_regression_multi_window/latest.json", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run replay regression cycle across multiple event-count windows.")
    parser.add_argument(
        "--windows",
        default="500,1000,2000",
        help="Comma-separated min-event windows for replay regression coverage.",
    )
    parser.add_argument("--repeat", type=int, default=2, help="Repeat count passed to replay cycle.")
    args = parser.parse_args()

    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    out_root = root / "reports" / "replay_regression_multi_window"
    out_root.mkdir(parents=True, exist_ok=True)

    parsed_windows: List[int] = []
    for raw in str(args.windows).split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            parsed_windows.append(max(1, int(raw)))
        except Exception:
            continue
    if not parsed_windows:
        parsed_windows = [1000]

    windows = [_run_window(root=root, min_events=w, repeat=int(args.repeat)) for w in parsed_windows]
    failed = [
        f"window_{w.get('min_events', 0)}"
        for w in windows
        if int(w.get("rc", 1)) != 0
        or str(w.get("status", "fail")) != "pass"
        or bool(w.get("deterministic_repeat_pass", False)) is not True
    ]
    status = "pass" if not failed else "fail"

    payload = {
        "ts_utc": _utc_now(),
        "status": status,
        "repeat": int(args.repeat),
        "windows_requested": parsed_windows,
        "failed_windows": failed,
        "windows": windows,
    }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_json = out_root / f"replay_regression_multi_window_{stamp}.json"
    out_md = out_root / f"replay_regression_multi_window_{stamp}.md"
    out_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (out_root / "latest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _write_md(out_md, payload)
    _write_md(out_root / "latest.md", payload)

    print(f"[replay-regression-multi-window] status={status}")
    print(f"[replay-regression-multi-window] evidence={out_json}")
    return 0 if status == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
