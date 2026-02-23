from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


TEST_GROUPS: Dict[str, List[str]] = {
    "unit": [
        "tests/controllers/test_paper_engine.py",
        "tests/services/test_event_schemas.py",
        "tests/services/test_intent_idempotency.py",
    ],
    "service": [
        "tests/services/test_ml_risk_gates.py",
        "tests/services/test_ml_feature_builder.py",
        "tests/services/test_ml_model_loader.py",
    ],
    "integration": [
        "tests/integration/test_signal_risk_flow.py",
        "tests/integration/test_ml_signal_to_intent_flow.py",
    ],
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_pytest(root: Path, targets: List[str], cov_fail_under: float) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--disable-warnings",
        "--maxfail=1",
        "--cov=controllers",
        "--cov=services",
        "--cov-report=term-missing",
        "--cov-report=xml:reports/tests/coverage.xml",
        "--cov-report=json:reports/tests/coverage.json",
        f"--cov-fail-under={cov_fail_under:.2f}",
    ] + targets
    return subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)


def _run_pytest_docker(root: Path, targets: List[str], cov_fail_under: float) -> subprocess.CompletedProcess[str]:
    compose_file = root / "compose" / "docker-compose.yml"
    env_file = root / "env" / ".env"
    inner_cmd = [
        "python",
        "-m",
        "pytest",
        "-q",
        "--disable-warnings",
        "--maxfail=1",
        "--cov=controllers",
        "--cov=services",
        "--cov-report=term-missing",
        "--cov-report=xml:reports/tests/coverage.xml",
        "--cov-report=json:reports/tests/coverage.json",
        f"--cov-fail-under={cov_fail_under:.2f}",
    ] + targets
    cmd = [
        "docker",
        "compose",
        "--env-file",
        str(env_file),
        "--profile",
        "external",
        "-f",
        str(compose_file),
        "run",
        "--rm",
        "--no-deps",
        "event-store-service",
    ] + inner_cmd
    return subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)


def _docker_available() -> bool:
    try:
        probe = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            check=False,
        )
        return probe.returncode == 0 and bool((probe.stdout or "").strip())
    except Exception:
        return False


def _should_fallback_to_host(proc: subprocess.CompletedProcess[str]) -> bool:
    out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).lower()
    return (
        "no module named pytest" in out
        or "module not found" in out and "pytest" in out
        or "can't open file" in out and "pytest" in out
    )


def _write_md(path: Path, payload: Dict[str, object]) -> None:
    groups = payload.get("groups", {}) if isinstance(payload.get("groups"), dict) else {}
    lines = [
        "# Test Runner Summary",
        "",
        f"- ts_utc: {payload.get('ts_utc', '')}",
        f"- status: {payload.get('status', 'fail')}",
        f"- rc: {payload.get('rc', 1)}",
        f"- cov_fail_under: {payload.get('cov_fail_under', 0)}",
        "",
        "## Group Coverage",
    ]
    for name in ("unit", "service", "integration"):
        info = groups.get(name, {})
        lines.append(f"- {name}: selected={info.get('selected', 0)}")
    lines.extend(
        [
            "",
            "## Artifacts",
            "- reports/tests/latest.json",
            "- reports/tests/latest.md",
            "- reports/tests/coverage.xml",
            "- reports/tests/coverage.json",
            "",
            "## Output (tail)",
            "```text",
            str(payload.get("output_tail", "")),
            "```",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic test groups with coverage artifacts.")
    parser.add_argument(
        "--groups",
        default="unit,service,integration",
        help="Comma-separated test groups from: unit,service,integration",
    )
    parser.add_argument(
        "--cov-fail-under",
        type=float,
        default=5.0,
        help="Minimum combined coverage percentage required for PASS.",
    )
    parser.add_argument(
        "--runtime",
        choices=["auto", "host", "docker"],
        default="auto",
        help="Test execution runtime. auto prefers docker when not already in container.",
    )
    args = parser.parse_args()

    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    selected_groups = [g.strip() for g in args.groups.split(",") if g.strip()]
    unknown = [g for g in selected_groups if g not in TEST_GROUPS]
    if unknown:
        print(f"[run-tests] unknown groups: {unknown}")
        return 2

    selected_targets: List[str] = []
    groups_payload: Dict[str, object] = {}
    for group in ("unit", "service", "integration"):
        targets = TEST_GROUPS[group] if group in selected_groups else []
        groups_payload[group] = {"selected": len(targets)}
        selected_targets.extend(targets)

    reports_root = root / "reports" / "tests"
    reports_root.mkdir(parents=True, exist_ok=True)

    runtime_used = "host"
    fallback_reason = ""
    if args.runtime == "docker":
        runtime_used = "docker"
        proc = _run_pytest_docker(root=root, targets=selected_targets, cov_fail_under=args.cov_fail_under)
    elif args.runtime == "host":
        proc = _run_pytest(root=root, targets=selected_targets, cov_fail_under=args.cov_fail_under)
    else:
        # Auto: in container use host runtime; on developer host prefer dockerized runtime for dependency consistency.
        if Path("/.dockerenv").exists() or os.name == "posix":
            proc = _run_pytest(root=root, targets=selected_targets, cov_fail_under=args.cov_fail_under)
        else:
            if _docker_available():
                runtime_used = "docker"
                proc = _run_pytest_docker(root=root, targets=selected_targets, cov_fail_under=args.cov_fail_under)
            else:
                proc = _run_pytest(root=root, targets=selected_targets, cov_fail_under=args.cov_fail_under)
    if args.runtime == "auto" and runtime_used == "docker" and proc.returncode != 0 and _should_fallback_to_host(proc):
        fallback_reason = "docker_runtime_missing_pytest"
        runtime_used = "host"
        proc = _run_pytest(root=root, targets=selected_targets, cov_fail_under=args.cov_fail_under)

    out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    status = "pass" if proc.returncode == 0 else "fail"
    payload = {
        "ts_utc": _utc_now(),
        "status": status,
        "rc": int(proc.returncode),
        "groups": groups_payload,
        "selected_tests": selected_targets,
        "cov_fail_under": args.cov_fail_under,
        "runtime_used": runtime_used,
        "fallback_reason": fallback_reason,
        "output_tail": out[-4000:],
    }

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_json = reports_root / f"test_run_{stamp}.json"
    out_md = reports_root / f"test_run_{stamp}.md"
    out_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (reports_root / "latest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _write_md(out_md, payload)
    _write_md(reports_root / "latest.md", payload)

    print(f"[run-tests] status={status}")
    print(f"[run-tests] rc={proc.returncode}")
    print(f"[run-tests] evidence={out_json}")
    return 0 if status == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
