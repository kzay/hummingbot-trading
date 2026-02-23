from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _minutes_since(ts: str) -> float:
    try:
        dt = _parse_ts(ts)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 60.0
    except Exception:
        return 1e9


def _minutes_since_file_mtime(path: Path) -> float:
    try:
        dt = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 60.0
    except Exception:
        return 1e9


def _read_json(path: Path, default: Dict[str, object]) -> Dict[str, object]:
    if not path.exists():
        return default
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else default
    except Exception:
        return default


def _check(cond: bool, name: str, severity: str, reason: str, evidence: List[str]) -> Dict[str, object]:
    return {
        "name": name,
        "severity": severity,
        "pass": bool(cond),
        "reason": reason,
        "evidence_paths": evidence,
    }


def _sha256_file(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
    except Exception:
        return ""
    return h.hexdigest()


def _file_ref(path: Path) -> Dict[str, object]:
    exists = path.exists() and path.is_file()
    ref = {
        "path": str(path),
        "exists": bool(exists),
        "sha256": "",
        "size_bytes": 0,
    }
    if exists:
        try:
            ref["sha256"] = _sha256_file(path)
            ref["size_bytes"] = int(path.stat().st_size)
        except Exception:
            pass
    return ref


def _write_markdown_summary(path: Path, summary: Dict[str, object]) -> None:
    checks = summary.get("checks", []) if isinstance(summary.get("checks"), list) else []
    critical_failures = summary.get("critical_failures", []) if isinstance(summary.get("critical_failures"), list) else []
    bundle = summary.get("evidence_bundle", {}) if isinstance(summary.get("evidence_bundle"), dict) else {}
    lines = [
        "# Promotion Gates Summary",
        "",
        f"- ts_utc: {summary.get('ts_utc', '')}",
        f"- status: {summary.get('status', 'FAIL')}",
        f"- critical_failures_count: {len(critical_failures)}",
        f"- evidence_bundle_id: {bundle.get('evidence_bundle_id', '')}",
        "",
        "## Critical Failures",
    ]
    if critical_failures:
        lines.extend([f"- {name}" for name in critical_failures])
    else:
        lines.append("- none")
    lines.extend(["", "## Checks"])
    for c in checks:
        name = str(c.get("name", "unknown"))
        ok = bool(c.get("pass"))
        reason = str(c.get("reason", ""))
        lines.append(f"- [{'PASS' if ok else 'FAIL'}] {name}: {reason}")
    lines.extend(["", "## Evidence Artifacts"])
    for ref in bundle.get("artifacts", []) if isinstance(bundle.get("artifacts"), list) else []:
        if isinstance(ref, dict):
            lines.append(f"- {ref.get('path', '')} (sha256={ref.get('sha256', '')})")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run_regression(root: Path) -> Tuple[int, str]:
    cmd = [sys.executable, str(root / "scripts" / "release" / "run_backtest_regression.py"), "--min-events", "1000"]
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_replay_regression_cycle(root: Path) -> Tuple[int, str]:
    cmd = [
        sys.executable,
        str(root / "scripts" / "release" / "run_replay_regression_cycle.py"),
        "--repeat",
        "2",
        "--min-events",
        "1000",
    ]
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _refresh_parity_once(root: Path) -> Tuple[int, str]:
    cmd = [sys.executable, str(root / "services" / "shadow_execution" / "main.py"), "--once"]
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _refresh_event_store_integrity_once(root: Path) -> Tuple[int, str]:
    """Recompute integrity stats from the local JSONL file (no Redis required)."""
    cmd = [sys.executable, str(root / "scripts" / "utils" / "refresh_event_store_integrity_local.py")]
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_multi_bot_policy_check(root: Path) -> Tuple[int, str]:
    cmd = [sys.executable, str(root / "scripts" / "release" / "check_multi_bot_policy.py")]
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_secrets_hygiene_check(root: Path) -> Tuple[int, str]:
    cmd = [
        sys.executable,
        str(root / "scripts" / "release" / "run_secrets_hygiene_check.py"),
        "--include-logs",
    ]
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_strategy_catalog_check(root: Path) -> Tuple[int, str]:
    cmd = [sys.executable, str(root / "scripts" / "release" / "check_strategy_catalog_consistency.py")]
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_replay_regression_multi_window(root: Path) -> Tuple[int, str]:
    cmd = [
        sys.executable,
        str(root / "scripts" / "release" / "run_replay_regression_multi_window.py"),
        "--windows",
        "500,1000,2000",
        "--repeat",
        "2",
    ]
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_tests(root: Path, runtime: str = "auto") -> Tuple[int, str]:
    cmd = [sys.executable, str(root / "scripts" / "release" / "run_tests.py"), "--runtime", runtime]
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_coordination_policy_check(root: Path) -> Tuple[int, str]:
    cmd = [sys.executable, str(root / "scripts" / "release" / "check_coordination_policy.py")]
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_market_data_freshness_check(root: Path, max_age_min: float) -> Tuple[int, str]:
    cmd = [
        sys.executable,
        str(root / "scripts" / "release" / "check_market_data_freshness.py"),
        "--max-age-min",
        str(max_age_min),
    ]
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_accounting_integrity_check(root: Path, max_age_min: float) -> Tuple[int, str]:
    cmd = [
        sys.executable,
        str(root / "scripts" / "release" / "check_accounting_integrity_v2.py"),
        "--max-age-min",
        str(max_age_min),
    ]
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_ml_governance_check(root: Path) -> Tuple[int, str]:
    cmd = [sys.executable, str(root / "scripts" / "release" / "check_ml_signal_governance.py")]
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run promotion gate contract checks.")
    parser.add_argument("--max-report-age-min", type=int, default=20, help="Max allowed age for fresh reports.")
    parser.add_argument("--require-day2-go", action="store_true", help="Require Day2 gate GO before promotion PASS.")
    parser.add_argument(
        "--refresh-parity-once",
        action="store_true",
        help="Run one parity cycle before evaluating parity freshness gate.",
    )
    parser.add_argument(
        "--skip-replay-cycle",
        action="store_true",
        help="Skip replay regression cycle execution/check (not recommended).",
    )
    parser.add_argument(
        "--refresh-event-integrity-once",
        action="store_true",
        help="Recompute event store integrity from local JSONL before freshness check (no Redis required).",
    )
    parser.add_argument(
        "--tests-runtime",
        choices=["auto", "host", "docker"],
        default="auto",
        help="Runtime passed to run_tests.py. Use 'host' when Docker image is stale (default: auto).",
    )
    parser.add_argument(
        "--ci",
        action="store_true",
        help="CI-like non-interactive mode: parity + integrity refresh, markdown summary, strict freshness defaults.",
    )
    args = parser.parse_args()

    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    reports = root / "reports"

    checks: List[Dict[str, object]] = []
    critical_failures: List[str] = []
    parity_refresh_rc = 0
    parity_refresh_msg = ""
    integrity_refresh_rc = 0
    integrity_refresh_msg = ""

    max_report_age_min = float(args.max_report_age_min)
    refresh_parity_once = bool(args.refresh_parity_once or args.ci)
    refresh_event_integrity_once = bool(args.refresh_event_integrity_once or args.ci)
    if args.ci and args.max_report_age_min == 20:
        max_report_age_min = 15.0

    if refresh_parity_once:
        parity_refresh_rc, parity_refresh_msg = _refresh_parity_once(root)

    if refresh_event_integrity_once:
        integrity_refresh_rc, integrity_refresh_msg = _refresh_event_store_integrity_once(root)

    # 1) Preflight checks
    required_files = [
        root / "config" / "reconciliation_thresholds.json",
        root / "config" / "parity_thresholds.json",
        root / "config" / "portfolio_limits_v1.json",
        root / "config" / "multi_bot_policy_v1.json",
        root / "scripts" / "release" / "run_backtest_regression.py",
        root / "scripts" / "release" / "run_replay_regression_cycle.py",
        root / "scripts" / "release" / "run_replay_regression_multi_window.py",
        root / "scripts" / "release" / "check_multi_bot_policy.py",
        root / "scripts" / "release" / "check_strategy_catalog_consistency.py",
        root / "scripts" / "release" / "check_coordination_policy.py",
        root / "scripts" / "release" / "run_tests.py",
        root / "scripts" / "release" / "run_secrets_hygiene_check.py",
        root / "scripts" / "release" / "check_ml_signal_governance.py",
        root / "scripts" / "release" / "check_accounting_integrity_v2.py",
        root / "scripts" / "release" / "check_market_data_freshness.py",
        root / "scripts" / "utils" / "refresh_event_store_integrity_local.py",
        root / "config" / "coordination_policy_v1.json",
        root / "config" / "ml_governance_policy_v1.json",
        root / "docs" / "validation" / "backtest_regression_spec.md",
    ]
    preflight_ok = all(p.exists() for p in required_files)
    checks.append(
        _check(
            preflight_ok,
            "preflight_checks",
            "critical",
            "required files present" if preflight_ok else "missing required config/spec/script files",
            [str(p) for p in required_files],
        )
    )

    # 2) Multi-bot policy consistency check
    policy_check_path = reports / "policy" / "latest.json"
    policy_rc, policy_msg = _run_multi_bot_policy_check(root)
    policy_report = _read_json(policy_check_path, {})
    policy_ok = policy_rc == 0 and str(policy_report.get("status", "fail")) == "pass"
    checks.append(
        _check(
            policy_ok,
            "multi_bot_policy_scope",
            "critical",
            "multi-bot policy scope is consistent across risk/reconciliation/account-map"
            if policy_ok
            else f"multi-bot policy consistency failed (rc={policy_rc})",
            [str(policy_check_path), str(root / "config" / "multi_bot_policy_v1.json")],
        )
    )

    # 3) Strategy catalog consistency check
    strategy_catalog_path = reports / "strategy_catalog" / "latest.json"
    strategy_rc, strategy_msg = _run_strategy_catalog_check(root)
    strategy_report = _read_json(strategy_catalog_path, {})
    strategy_ok = strategy_rc == 0 and str(strategy_report.get("status", "fail")) == "pass"
    checks.append(
        _check(
            strategy_ok,
            "strategy_catalog_consistency",
            "critical",
            "strategy catalog configs resolve to shared code and declared bundles"
            if strategy_ok
            else f"strategy catalog consistency failed (rc={strategy_rc})",
            [str(strategy_catalog_path), str(root / "config" / "strategy_catalog" / "catalog_v1.json")],
        )
    )

    # 4) Coordination policy scope check
    coord_policy_path = reports / "policy" / "coordination_policy_latest.json"
    coord_rc, coord_msg = _run_coordination_policy_check(root)
    coord_report = _read_json(coord_policy_path, {})
    coord_ok = coord_rc == 0 and str(coord_report.get("status", "fail")) == "pass"
    checks.append(
        _check(
            coord_ok,
            "coordination_policy_scope",
            "critical",
            "coordination service runs only in policy-permitted scope/mode"
            if coord_ok
            else f"coordination policy check failed (rc={coord_rc})",
            [str(coord_policy_path), str(root / "config" / "coordination_policy_v1.json")],
        )
    )

    # 5) Deterministic tests + coverage
    tests_path = reports / "tests" / "latest.json"
    tests_rc, tests_msg = _run_tests(root, runtime=args.tests_runtime)
    tests_report = _read_json(tests_path, {})
    tests_ok = tests_rc == 0 and str(tests_report.get("status", "fail")) == "pass"
    checks.append(
        _check(
            tests_ok,
            "unit_service_integration_tests",
            "critical",
            "deterministic test suite + coverage threshold passed"
            if tests_ok
            else f"deterministic tests failed (rc={tests_rc})",
            [str(tests_path), str(root / "reports" / "tests" / "latest.md")],
        )
    )

    # 6) Secrets hygiene check
    secrets_check_path = reports / "security" / "latest.json"
    secrets_rc, secrets_msg = _run_secrets_hygiene_check(root)
    secrets_report = _read_json(secrets_check_path, {})
    secrets_ok = secrets_rc == 0 and str(secrets_report.get("status", "fail")) == "pass"
    checks.append(
        _check(
            secrets_ok,
            "secrets_hygiene",
            "critical",
            "no secret leakage markers in docs/reports/log artifacts"
            if secrets_ok
            else f"secrets hygiene check failed (rc={secrets_rc})",
            [str(secrets_check_path), str(root / "scripts" / "release" / "run_secrets_hygiene_check.py")],
        )
    )

    # 7) Smoke checks (activity evidence)
    smoke_paths = list((root / "data" / "bot4" / "logs").glob("epp_v24/*/minute.csv"))
    smoke_ok = len(smoke_paths) > 0
    checks.append(
        _check(
            smoke_ok,
            "smoke_checks",
            "critical",
            "bot4 smoke activity artifacts found" if smoke_ok else "bot4 smoke artifacts missing",
            [str(p) for p in smoke_paths] if smoke_ok else [str(root / "data" / "bot4" / "logs")],
        )
    )

    # 8) Paper smoke matrix (required)
    snapshot_path = reports / "exchange_snapshots" / "latest.json"
    snapshot = _read_json(snapshot_path, {})
    bot3 = snapshot.get("bots", {}).get("bot3", {}) if isinstance(snapshot.get("bots"), dict) else {}
    paper_ok_direct = (
        isinstance(bot3, dict)
        and str(bot3.get("account_mode", "")) == "paper_only"
        and str(bot3.get("account_probe_status", "")) == "paper_only"
    )
    paper_ok_proxy = (
        isinstance(bot3, dict)
        and str(bot3.get("exchange", "")).lower() == "bitget_paper_trade"
        and str(bot3.get("source", "")) == "local_minute_proxy"
    )
    paper_ok = paper_ok_direct or paper_ok_proxy
    checks.append(
        _check(
            paper_ok,
            "paper_smoke_matrix",
            "critical",
            "bot3 paper-mode intent verified"
            if paper_ok
            else "bot3 paper-mode evidence missing/invalid (expected direct paper_only or proxy-local paper markers)",
            [str(snapshot_path)],
        )
    )

    # 9) Replay regression cycle (required unless explicitly skipped)
    replay_cycle_rc = 0
    replay_cycle_msg = ""
    replay_cycle_path = reports / "replay_regression_multi_window" / "latest.json"
    replay_cycle = {}
    if not args.skip_replay_cycle:
        replay_cycle_rc, replay_cycle_msg = _run_replay_regression_multi_window(root)
        replay_cycle = _read_json(replay_cycle_path, {})
    replay_cycle_ok = True if args.skip_replay_cycle else (replay_cycle_rc == 0 and str(replay_cycle.get("status", "fail")) == "pass")
    checks.append(
        _check(
            replay_cycle_ok,
            "replay_regression_first_class",
            "critical",
            "replay regression multi-window PASS"
            if replay_cycle_ok
            else f"replay regression multi-window failed (rc={replay_cycle_rc})",
            [str(replay_cycle_path), str(root / "scripts" / "release" / "run_replay_regression_multi_window.py")],
        )
    )

    # 10) ML governance policy + retirement/drift checks
    ml_governance_path = reports / "policy" / "ml_governance_latest.json"
    ml_rc, ml_msg = _run_ml_governance_check(root)
    ml_report = _read_json(ml_governance_path, {})
    ml_ok = ml_rc == 0 and str(ml_report.get("status", "fail")) == "pass"
    checks.append(
        _check(
            ml_ok,
            "ml_signal_governance",
            "critical",
            "ML governance policy checks passed"
            if ml_ok
            else f"ML governance policy check failed (rc={ml_rc})",
            [str(ml_governance_path), str(root / "config" / "ml_governance_policy_v1.json")],
        )
    )

    # 11) Regression backtest harness (required)
    rc, reg_msg = _run_regression(root)
    reg_report = reports / "backtest_regression" / "latest.json"
    regression_ok = rc == 0 and reg_report.exists()
    checks.append(
        _check(
            regression_ok,
            "regression_backtest_harness",
            "critical",
            "regression harness PASS" if regression_ok else f"regression harness failed (rc={rc})",
            [str(reg_report), str(root / "scripts" / "release" / "run_backtest_regression.py")],
        )
    )

    # 12) Reconciliation status
    recon_path = reports / "reconciliation" / "latest.json"
    recon = _read_json(recon_path, {})
    recon_ok = str(recon.get("status", "critical")) in {"ok", "warning"} and int(recon.get("critical_count", 1)) == 0
    recon_fresh = _minutes_since(str(recon.get("ts_utc", ""))) <= max_report_age_min
    checks.append(
        _check(
            recon_ok and recon_fresh,
            "reconciliation_status",
            "critical",
            "reconciliation healthy and fresh"
            if (recon_ok and recon_fresh)
            else "reconciliation critical or stale",
            [str(recon_path)],
        )
    )

    # 13) Parity thresholds
    parity_path = reports / "parity" / "latest.json"
    parity = _read_json(parity_path, {})
    parity_ok = str(parity.get("status", "fail")) == "pass"
    parity_fresh = _minutes_since(str(parity.get("ts_utc", ""))) <= max_report_age_min
    checks.append(
        _check(
            parity_ok and parity_fresh,
            "parity_thresholds",
            "critical",
            "parity pass and fresh" if (parity_ok and parity_fresh) else "parity fail or stale",
            [str(parity_path)],
        )
    )

    # 14) Portfolio risk status + freshness
    risk_path = reports / "portfolio_risk" / "latest.json"
    risk = _read_json(risk_path, {})
    risk_ok = str(risk.get("status", "critical")) in {"ok", "warning"} and int(risk.get("critical_count", 1)) == 0
    risk_fresh = _minutes_since(str(risk.get("ts_utc", ""))) <= max_report_age_min
    checks.append(
        _check(
            risk_ok and risk_fresh,
            "portfolio_risk_status",
            "critical",
            "portfolio risk healthy and fresh"
            if (risk_ok and risk_fresh)
            else "portfolio risk critical or stale",
            [str(risk_path)],
        )
    )

    # 15) Accounting integrity
    accounting_path = reports / "accounting" / "latest.json"
    accounting_rc, accounting_msg = _run_accounting_integrity_check(root, max_report_age_min)
    accounting_report = _read_json(accounting_path, {})
    accounting_ok = accounting_rc == 0 and str(accounting_report.get("status", "fail")) == "pass"
    checks.append(
        _check(
            accounting_ok,
            "accounting_integrity_v2",
            "critical",
            "accounting integrity checks passed with fresh snapshots"
            if accounting_ok
            else f"accounting integrity check failed (rc={accounting_rc})",
            [str(accounting_path), str(reports / "reconciliation" / "latest.json")],
        )
    )

    # 16) Alerting health
    alert_path = reports / "reconciliation" / "last_webhook_sent.json"
    alert = _read_json(alert_path, {})
    alert_ok = alert_path.exists() and _minutes_since(str(alert.get("ts_utc", ""))) <= 24 * 60
    checks.append(
        _check(
            alert_ok,
            "alerting_health",
            "critical",
            "alert webhook evidence is present/recent"
            if alert_ok
            else "alert webhook evidence missing or stale",
            [str(alert_path)],
        )
    )

    # 17) Event store integrity freshness
    integrity_path = reports / "event_store" / "integrity_20260221.json"
    # Prefer latest integrity artifact if present.
    integrity_candidates = sorted((reports / "event_store").glob("integrity_*.json"))
    if integrity_candidates:
        integrity_path = integrity_candidates[-1]
    integrity = _read_json(integrity_path, {})
    # event_store/main.py writes "last_update_utc"; ts_utc is a forward-compat fallback.
    integrity_ts = str(integrity.get("ts_utc", "")).strip() or str(integrity.get("last_update_utc", "")).strip()
    integrity_age_min = (
        _minutes_since(integrity_ts)
        if integrity_ts
        else _minutes_since_file_mtime(integrity_path)
    )
    integrity_ok = (
        bool(integrity_path.exists())
        and int(integrity.get("missing_correlation_count", 1)) == 0
        and integrity_age_min <= max_report_age_min
    )
    checks.append(
        _check(
            integrity_ok,
            "event_store_integrity_freshness",
            "critical",
            "event store integrity fresh with zero missing correlations"
            if integrity_ok
            else "event store integrity missing/stale or missing correlations detected",
            [str(integrity_path)],
        )
    )

    # 18) Market data freshness
    md_path = reports / "market_data" / "latest.json"
    md_rc, md_msg = _run_market_data_freshness_check(root, max_report_age_min)
    md_report = _read_json(md_path, {})
    md_ok = md_rc == 0 and str(md_report.get("status", "fail")) == "pass"
    checks.append(
        _check(
            md_ok,
            "market_data_freshness",
            "warning",
            "market data artifacts are fresh with hb.market_data.v1 rows"
            if md_ok
            else f"market data freshness check failed (rc={md_rc})",
            [str(md_path), str(root / "reports" / "event_store")],
        )
    )

    # 19) Optional strict day2 gate dependency
    day2_path = reports / "event_store" / "day2_gate_eval_latest.json"
    day2 = _read_json(day2_path, {})
    day2_go = bool(day2.get("go", False))
    checks.append(
        _check(
            (day2_go if args.require_day2_go else True),
            "day2_event_store_gate",
            "critical",
            "day2 gate GO" if day2_go else "day2 gate not yet GO",
            [str(day2_path)],
        )
    )

    # 20) Validation ladder: paper soak (Level 3) required for live promotion
    paper_soak_path = reports / "paper_soak" / "latest.json"
    paper_soak = _read_json(paper_soak_path, {})
    paper_soak_pass = str(paper_soak.get("status", "")).upper() == "PASS"
    paper_soak_age = _minutes_since(str(paper_soak.get("ts_utc", "")))
    checks.append(
        _check(
            paper_soak_pass and paper_soak_age <= 24 * 60,
            "validation_ladder_paper_soak",
            "warning",
            f"paper soak PASS (age={paper_soak_age:.0f}m)"
            if paper_soak_pass
            else "paper soak not PASS or missing — Level 3 validation incomplete",
            [str(paper_soak_path)],
        )
    )

    # 21) Validation ladder: post-trade validation (Level 6) — informational
    ptv_path = reports / "analysis" / "post_trade_validation.json"
    ptv = _read_json(ptv_path, {})
    ptv_status = str(ptv.get("status", "")).upper()
    ptv_ok = ptv_status in {"PASS", "WARNING"}
    ptv_critical = ptv_status == "CRITICAL"
    checks.append(
        _check(
            not ptv_critical,
            "validation_ladder_post_trade",
            "warning",
            f"post-trade validation {ptv_status}"
            if ptv_status
            else "post-trade validation not yet run",
            [str(ptv_path)],
        )
    )

    # Compute validation level achieved
    validation_level = 0
    if any(c["pass"] for c in checks if c["name"] == "unit_service_integration_tests"):
        validation_level = 1
    if any(c["pass"] for c in checks if c["name"] == "replay_regression_cycle"):
        validation_level = max(validation_level, 2)
    if paper_soak_pass:
        validation_level = max(validation_level, 3)
    if ptv_ok and ptv_status:
        validation_level = max(validation_level, 6)

    for c in checks:
        if c["severity"] == "critical" and not c["pass"]:
            critical_failures.append(str(c["name"]))

    status = "PASS" if not critical_failures else "FAIL"
    manifest_path = root / "docs" / "ops" / "release_manifest_20260221.md"
    all_evidence_paths = sorted({p for c in checks for p in c.get("evidence_paths", []) if isinstance(p, str)})
    all_evidence_refs = []
    for p in all_evidence_paths:
        all_evidence_refs.append(_file_ref(Path(p)))
    evidence_bundle_raw = json.dumps(
        {
            "status": status,
            "critical_failures": critical_failures,
            "evidence_paths": all_evidence_paths,
            "manifest_sha256": _sha256_file(manifest_path),
        },
        sort_keys=True,
    )
    evidence_bundle_id = hashlib.sha256(evidence_bundle_raw.encode("utf-8")).hexdigest()

    summary = {
        "ts_utc": _utc_now(),
        "status": status,
        "validation_level": validation_level,
        "critical_failures": critical_failures,
        "checks": checks,
        "release_manifest_ref": _file_ref(manifest_path),
        "evidence_bundle": {
            "evidence_bundle_id": evidence_bundle_id,
            "artifact_count": len(all_evidence_refs),
            "artifacts": all_evidence_refs,
        },
        "notes": {
            "regression_runner_output": reg_msg[:2000],
            "replay_cycle_runner_output": replay_cycle_msg[:2000],
            "ml_governance_runner_output": ml_msg[:2000],
            "multi_bot_policy_runner_output": policy_msg[:2000],
            "strategy_catalog_runner_output": strategy_msg[:2000],
            "coordination_policy_runner_output": coord_msg[:2000],
            "tests_runner_output": tests_msg[:2000],
            "secrets_hygiene_runner_output": secrets_msg[:2000],
            "require_day2_go": bool(args.require_day2_go),
            "refresh_parity_once": bool(refresh_parity_once),
            "refresh_event_integrity_once": bool(refresh_event_integrity_once),
            "skip_replay_cycle": bool(args.skip_replay_cycle),
            "ci_mode": bool(args.ci),
            "max_report_age_min": max_report_age_min,
            "parity_refresh_rc": parity_refresh_rc,
            "parity_refresh_output": parity_refresh_msg[:2000],
            "integrity_refresh_rc": integrity_refresh_rc,
            "integrity_refresh_output": integrity_refresh_msg[:2000],
            "accounting_integrity_runner_output": accounting_msg[:2000],
            "market_data_freshness_runner_output": md_msg[:2000],
        },
    }

    out_root = reports / "promotion_gates"
    out_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_file = out_root / f"promotion_gates_{stamp}.json"
    out_md = out_root / f"promotion_gates_{stamp}.md"
    out_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out_root / "latest.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    _write_markdown_summary(out_md, summary)
    _write_markdown_summary(out_root / "latest.md", summary)

    print(f"[promotion-gates] status={status} validation_level={validation_level}")
    if critical_failures:
        print("[promotion-gates] critical_failures=" + ",".join(critical_failures))
    print(f"[promotion-gates] evidence={out_file}")
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
