from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

CRITICAL_PATH_PREFIXES = [
    "scripts/shared/v2_with_controllers.py",
    "controllers/paper_engine_v2/",
    "controllers/tick_emitter.py",
    "services/event_store/main.py",
    "services/reconciliation_service/main.py",
    "services/bot_metrics_exporter.py",
    "services/hb_bridge/redis_client.py",
]


TEST_GROUPS: dict[str, list[str]] = {
    "unit": [
        "tests/scripts/test_v2_with_controllers_hot_reload.py",
        "tests/controllers/test_hb_bridge_event_isolation.py::test_sync_state_processed_hydrates_runtime_orders_from_service_snapshot",
        "tests/controllers/test_hb_bridge_event_isolation.py::test_hydrate_runtime_orders_logs_snapshot_read_failure",
        "tests/controllers/test_paper_engine_v2/",
        "tests/controllers/test_epp_v2_4_state.py",
        "tests/services/test_event_schemas.py",
        "tests/services/test_intent_idempotency.py",
    ],
    "service": [
        "tests/services/test_bot_metrics_exporter.py",
        "tests/services/test_ml_risk_gates.py",
        "tests/services/test_ml_feature_builder.py",
        "tests/services/test_ml_model_loader.py",
    ],
    "backtest": [
        "tests/controllers/test_backtesting/test_backtest_smoke.py",
    ],
    "integration": [
        "tests/integration/test_signal_risk_flow.py",
        "tests/integration/test_ml_signal_to_intent_flow.py",
    ],
}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _run_pytest(root: Path, targets: list[str], cov_fail_under: float) -> subprocess.CompletedProcess[str]:
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


def _run_pytest_docker(root: Path, targets: list[str], cov_fail_under: float) -> subprocess.CompletedProcess[str]:
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
        or ("module not found" in out and "pytest" in out)
        or ("can't open file" in out and "pytest" in out)
    )


def _write_md(path: Path, payload: dict[str, object]) -> None:
    groups = payload.get("groups", {}) if isinstance(payload.get("groups"), dict) else {}
    critical = payload.get("critical_path_coverage", {}) if isinstance(payload.get("critical_path_coverage"), dict) else {}
    lines = [
        "# Test Runner Summary",
        "",
        f"- ts_utc: {payload.get('ts_utc', '')}",
        f"- status: {payload.get('status', 'fail')}",
        f"- rc: {payload.get('rc', 1)}",
        f"- cov_fail_under: {payload.get('cov_fail_under', 0)}",
        f"- critical_path_cov_fail_under: {payload.get('critical_path_cov_fail_under', 0)}",
        "",
        "## Group Coverage",
    ]
    for name in ("unit", "service", "integration"):
        info = groups.get(name, {})
        lines.append(f"- {name}: selected={info.get('selected', 0)}")
    lines.extend(
        [
            "",
            "## Critical Path Coverage",
            f"- selected_files: {critical.get('selected_files', 0)}",
            f"- covered_lines: {critical.get('covered_lines', 0)}",
            f"- num_statements: {critical.get('num_statements', 0)}",
            f"- percent_covered: {critical.get('percent_covered', 0)}",
            f"- threshold_pass: {critical.get('pass', False)}",
        ]
    )
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


def _compute_critical_path_coverage(coverage_path: Path) -> dict[str, object]:
    if not coverage_path.exists():
        return {
            "selected_files": 0,
            "covered_lines": 0,
            "num_statements": 0,
            "percent_covered": 0.0,
            "files": [],
        }
    try:
        payload = json.loads(coverage_path.read_text(encoding="utf-8"))
    except Exception:
        return {
            "selected_files": 0,
            "covered_lines": 0,
            "num_statements": 0,
            "percent_covered": 0.0,
            "files": [],
        }
    files = payload.get("files", {}) if isinstance(payload, dict) else {}
    selected: list[dict[str, object]] = []
    total_covered = 0
    total_statements = 0
    for raw_path, info in files.items() if isinstance(files, dict) else []:
        path_text = str(raw_path).replace("\\", "/")
        if not any(
            path_text == prefix or path_text.startswith(prefix) or path_text.endswith(prefix) or f"/{prefix}" in path_text
            for prefix in CRITICAL_PATH_PREFIXES
        ):
            continue
        summary = info.get("summary", {}) if isinstance(info, dict) else {}
        covered_lines = int(summary.get("covered_lines", 0) or 0)
        num_statements = int(summary.get("num_statements", 0) or 0)
        percent_covered = float(summary.get("percent_covered", 0.0) or 0.0)
        total_covered += covered_lines
        total_statements += num_statements
        selected.append(
            {
                "path": path_text,
                "covered_lines": covered_lines,
                "num_statements": num_statements,
                "percent_covered": percent_covered,
            }
        )
    percent = (100.0 * total_covered / total_statements) if total_statements > 0 else 0.0
    return {
        "selected_files": len(selected),
        "covered_lines": total_covered,
        "num_statements": total_statements,
        "percent_covered": round(percent, 2),
        "files": selected,
    }


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
        default=30.0,
        help="Minimum combined coverage percentage required for PASS.",
    )
    parser.add_argument(
        "--runtime",
        choices=["auto", "host", "docker"],
        default="auto",
        help="Test execution runtime. auto prefers docker when not already in container.",
    )
    parser.add_argument(
        "--critical-path-cov-fail-under",
        type=float,
        default=float(os.getenv("CRITICAL_PATH_COV_FAIL_UNDER", "15.0")),
        help="Minimum critical-path coverage percentage required for PASS.",
    )
    args = parser.parse_args()

    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    selected_groups = [g.strip() for g in args.groups.split(",") if g.strip()]
    unknown = [g for g in selected_groups if g not in TEST_GROUPS]
    if unknown:
        print(f"[run-tests] unknown groups: {unknown}")
        return 2

    selected_targets: list[str] = []
    groups_payload: dict[str, object] = {}
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
    critical_path_coverage = _compute_critical_path_coverage(reports_root / "coverage.json")
    critical_path_pass = float(critical_path_coverage.get("percent_covered", 0.0) or 0.0) >= float(args.critical_path_cov_fail_under)
    status = "pass" if proc.returncode == 0 and critical_path_pass else "fail"
    payload = {
        "ts_utc": _utc_now(),
        "status": status,
        "rc": int(proc.returncode),
        "groups": groups_payload,
        "selected_tests": selected_targets,
        "cov_fail_under": args.cov_fail_under,
        "critical_path_cov_fail_under": float(args.critical_path_cov_fail_under),
        "critical_path_coverage": {
            **critical_path_coverage,
            "pass": bool(critical_path_pass),
        },
        "runtime_used": runtime_used,
        "fallback_reason": fallback_reason,
        "output_tail": out[-4000:],
    }

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
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
