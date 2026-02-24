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


def _run(root: Path, name: str, cmd: List[str], dry_run: bool) -> Dict[str, object]:
    if dry_run:
        return {"name": name, "rc": 0, "status": "skipped", "cmd": cmd, "output_tail": "dry_run=true"}
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return {
            "name": name,
            "rc": int(proc.returncode),
            "status": "pass" if proc.returncode == 0 else "fail",
            "cmd": cmd,
            "output_tail": out[-4000:],
        }
    except Exception as exc:
        return {"name": name, "rc": 99, "status": "fail", "cmd": cmd, "output_tail": str(exc)}


def _write_md(path: Path, payload: Dict[str, object]) -> None:
    steps = payload.get("steps", []) if isinstance(payload.get("steps"), list) else []
    lines = [
        "# CI Pipeline Summary",
        "",
        f"- ts_utc: {payload.get('ts_utc', '')}",
        f"- status: {payload.get('status', 'fail')}",
        f"- dry_run: {payload.get('dry_run', False)}",
        "",
        "## Steps",
    ]
    for step in steps:
        if not isinstance(step, dict):
            continue
        lines.append(
            f"- {step.get('name', 'unknown')}: status={step.get('status', 'fail')} rc={step.get('rc', 1)}"
        )
    lines.extend(
        [
            "",
            "## Artifacts",
            "- reports/ci_pipeline/latest.json",
            "- reports/ci_pipeline/latest.md",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Formal CI runner: tests + replay regression + promotion gates."
    )
    parser.add_argument(
        "--tests-runtime",
        choices=["auto", "host", "docker"],
        default="auto",
        help="Runtime passed to run_tests.py and run_promotion_gates.py.",
    )
    parser.add_argument("--cov-fail-under", type=float, default=5.0, help="Coverage threshold for test step.")
    parser.add_argument("--min-events", type=int, default=1000, help="Minimum event rows for replay regression.")
    parser.add_argument("--dry-run", action="store_true", help="Do not execute steps; only emit planned pipeline.")
    args = parser.parse_args()

    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    reports_root = root / "reports" / "ci_pipeline"
    reports_root.mkdir(parents=True, exist_ok=True)

    steps = [
        _run(
            root,
            "ruff_lint",
            [
                sys.executable,
                "-m",
                "ruff",
                "check",
                str(root / "controllers"),
                str(root / "services"),
            ],
            dry_run=bool(args.dry_run),
        ),
        _run(
            root,
            "mypy_typecheck",
            [
                sys.executable,
                "-m",
                "mypy",
                str(root / "controllers"),
                str(root / "services" / "contracts"),
                "--ignore-missing-imports",
            ],
            dry_run=bool(args.dry_run),
        ),
        _run(
            root,
            "tests",
            [
                sys.executable,
                str(root / "scripts" / "release" / "run_tests.py"),
                "--runtime",
                args.tests_runtime,
                "--groups",
                "unit,service,integration",
                "--cov-fail-under",
                str(args.cov_fail_under),
            ],
            dry_run=bool(args.dry_run),
        ),
        _run(
            root,
            "replay_regression_multi_window",
            [
                sys.executable,
                str(root / "scripts" / "release" / "run_replay_regression_multi_window.py"),
                "--windows",
                f"{max(1, int(args.min_events)//2)},{max(1, int(args.min_events))},{max(1, int(args.min_events)*2)}",
                "--repeat",
                "2",
            ],
            dry_run=bool(args.dry_run),
        ),
        _run(
            root,
            "promotion_gates",
            [
                sys.executable,
                str(root / "scripts" / "release" / "run_promotion_gates.py"),
                "--ci",
                "--tests-runtime",
                args.tests_runtime,
                "--skip-replay-cycle",
            ],
            dry_run=bool(args.dry_run),
        ),
    ]

    failed_steps = [str(s.get("name", "unknown")) for s in steps if int(s.get("rc", 1)) != 0]
    status = "pass" if not failed_steps else "fail"
    payload = {
        "ts_utc": _utc_now(),
        "status": status,
        "dry_run": bool(args.dry_run),
        "tests_runtime": args.tests_runtime,
        "cov_fail_under": float(args.cov_fail_under),
        "min_events": int(args.min_events),
        "failed_steps": failed_steps,
        "steps": steps,
        "evidence_paths": {
            "ruff_lint": "inline (see step output)",
            "mypy_typecheck": "inline (see step output)",
            "tests": str(root / "reports" / "tests" / "latest.json"),
            "replay_regression_multi_window": str(root / "reports" / "replay_regression_multi_window" / "latest.json"),
            "promotion_gates": str(root / "reports" / "promotion_gates" / "latest.json"),
        },
    }

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_json = reports_root / f"ci_pipeline_{stamp}.json"
    out_md = reports_root / f"ci_pipeline_{stamp}.md"
    out_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (reports_root / "latest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _write_md(out_md, payload)
    _write_md(reports_root / "latest.md", payload)

    print(f"[ci-pipeline] status={status}")
    print(f"[ci-pipeline] evidence={out_json}")
    return 0 if status == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
