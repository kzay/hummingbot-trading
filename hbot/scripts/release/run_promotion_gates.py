from __future__ import annotations

import argparse
import hashlib
import json
import os
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


def _metric_insufficient(metric_entry: Dict[str, object]) -> bool:
    """Return True when a parity metric carries insufficient-data semantics."""
    if not isinstance(metric_entry, dict):
        return True
    note = str(metric_entry.get("note", "")).strip().lower()
    if note == "insufficient_data":
        return True
    return metric_entry.get("value") is None and metric_entry.get("delta") is None


def _parity_core_insufficient_active_bots(parity: Dict[str, object]) -> Tuple[List[str], List[str]]:
    """Return (insufficient_active_bots, active_bots).

    Active bot scope is inferred from parity summary activity counters and/or
    non-null equity markers.
    """
    bots = parity.get("bots", [])
    if not isinstance(bots, list):
        return [], []
    active_bots: List[str] = []
    insufficient_bots: List[str] = []
    core_metrics = ("fill_ratio_delta", "slippage_delta_bps", "reject_rate_delta")
    for idx, bot_entry in enumerate(bots):
        if not isinstance(bot_entry, dict):
            continue
        bot_name = str(bot_entry.get("bot", "")).strip() or f"bot_{idx}"
        summary = bot_entry.get("summary", {})
        summary = summary if isinstance(summary, dict) else {}
        active = False
        for key in ("intents_total", "actionable_intents", "fills_total", "order_failed_total", "risk_denied_total"):
            try:
                if float(summary.get(key, 0) or 0) > 0:
                    active = True
                    break
            except Exception:
                continue
        if summary.get("equity_first") is not None or summary.get("equity_last") is not None:
            active = True
        if not active:
            continue
        active_bots.append(bot_name)
        metrics = bot_entry.get("metrics", [])
        metric_map: Dict[str, Dict[str, object]] = {}
        if isinstance(metrics, list):
            for m in metrics:
                if isinstance(m, dict):
                    metric_map[str(m.get("metric", "")).strip()] = m
        core_insufficient = [_metric_insufficient(metric_map.get(metric_name, {})) for metric_name in core_metrics]
        if core_insufficient and all(core_insufficient):
            insufficient_bots.append(bot_name)
    return insufficient_bots, active_bots


def _portfolio_diversification_gate(report: Dict[str, object]) -> Tuple[bool, str]:
    """Return (gate_ok, reason) from diversification report payload."""
    status = str(report.get("status", "")).strip().lower()
    if status == "pass":
        return True, "portfolio diversification check pass (btc/eth correlation within threshold)"
    if status == "insufficient_data":
        return True, "portfolio diversification check inconclusive (insufficient overlap data)"
    if status == "fail":
        return False, "portfolio diversification check fail (btc/eth correlation above threshold)"
    return False, "portfolio diversification report missing or invalid"


def _day2_freshness(day2: Dict[str, object], day2_path: Path, max_report_age_min: float) -> Tuple[bool, float]:
    """Return (is_fresh, age_minutes) for day2 gate artifact."""
    day2_ts = str(day2.get("ts_utc", "")).strip()
    age_min = _minutes_since(day2_ts) if day2_ts else _minutes_since_file_mtime(day2_path)
    return age_min <= max_report_age_min, age_min


def _day2_lag_within_tolerance(
    day2: Dict[str, object], reports_event_store: Path, max_allowed_delta: int
) -> Tuple[bool, Dict[str, object]]:
    """Return (pass, diagnostics) for produced-vs-ingested lag tolerance."""
    source_compare_path_raw = str(day2.get("source_compare_file", "")).strip()
    source_compare_path = Path(source_compare_path_raw) if source_compare_path_raw else None
    if source_compare_path is None or not source_compare_path.exists():
        candidates = sorted(reports_event_store.glob("source_compare_*.json"))
        source_compare_path = candidates[-1] if candidates else None

    source_compare = _read_json(source_compare_path, {}) if source_compare_path else {}
    delta_map_raw = source_compare.get("delta_produced_minus_ingested_since_baseline", {})
    delta_map_raw = delta_map_raw if isinstance(delta_map_raw, dict) else {}

    lag_by_stream: Dict[str, int] = {}
    for stream, value in delta_map_raw.items():
        try:
            lag_by_stream[str(stream)] = abs(int(value))
        except Exception:
            lag_by_stream[str(stream)] = 0

    max_delta_observed = max(lag_by_stream.values()) if lag_by_stream else 0
    worst_stream = ""
    if lag_by_stream:
        worst_stream = max(sorted(lag_by_stream.keys()), key=lambda k: lag_by_stream.get(k, 0))
    offending_streams = {k: v for k, v in lag_by_stream.items() if v > int(max_allowed_delta)}
    diagnostics = {
        "source_compare_path": str(source_compare_path) if source_compare_path else "",
        "lag_by_stream": lag_by_stream,
        "max_delta_observed": int(max_delta_observed),
        "max_allowed_delta": int(max_allowed_delta),
        "worst_stream": worst_stream,
        "offending_streams": offending_streams,
    }
    return int(max_delta_observed) <= int(max_allowed_delta), diagnostics


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


def _build_subprocess_env(root: Path) -> Dict[str, str]:
    env = os.environ.copy()
    root_str = str(root)
    current = env.get("PYTHONPATH", "")
    parts = [p for p in current.split(os.pathsep) if p]
    if root_str not in parts:
        parts.insert(0, root_str)
    env["PYTHONPATH"] = os.pathsep.join(parts)
    return env


def _run_regression(root: Path) -> Tuple[int, str]:
    cmd = [sys.executable, str(root / "scripts" / "release" / "run_backtest_regression.py"), "--min-events", "1000"]
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _refresh_parity_once(root: Path) -> Tuple[int, str]:
    cmd = [sys.executable, str(root / "services" / "shadow_execution" / "main.py"), "--once"]
    try:
        proc = subprocess.run(
            cmd, cwd=str(root), capture_output=True, text=True, check=False, env=_build_subprocess_env(root)
        )
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _refresh_reconciliation_exchange_once(root: Path) -> Tuple[int, str]:
    cmd = [sys.executable, str(root / "services" / "reconciliation_service" / "main.py"), "--once"]
    try:
        env = _build_subprocess_env(root)
        env.setdefault("RECON_EXCHANGE_SOURCE_ENABLED", "true")
        env.setdefault("RECON_EXCHANGE_SNAPSHOT_PATH", str(root / "reports" / "exchange_snapshots" / "latest.json"))
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False, env=env)
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


def _run_event_store_once(root: Path) -> Tuple[int, str]:
    cmd = [sys.executable, str(root / "services" / "event_store" / "main.py"), "--once"]
    try:
        proc = subprocess.run(
            cmd, cwd=str(root), capture_output=True, text=True, check=False, env=_build_subprocess_env(root)
        )
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_event_store_count_check_once(root: Path) -> Tuple[int, str]:
    cmd = [sys.executable, str(root / "scripts" / "utils" / "event_store_count_check.py")]
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _refresh_day2_gate_once(
    root: Path,
    day2_min_hours_override: float = -1.0,
    day2_max_delta_override: int = -1,
) -> Tuple[int, str]:
    cmd = [sys.executable, str(root / "scripts" / "utils" / "day2_gate_evaluator.py")]
    try:
        env = _build_subprocess_env(root)
        if day2_min_hours_override >= 0:
            env["DAY2_GATE_MIN_HOURS"] = str(day2_min_hours_override)
        if day2_max_delta_override >= 0:
            env["DAY2_GATE_MAX_DELTA"] = str(day2_max_delta_override)
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False, env=env)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_fill_event_backfill_once(root: Path, day_utc: str) -> Tuple[int, str]:
    cmd = [
        sys.executable,
        str(root / "scripts" / "utils" / "backfill_order_filled_events_from_fills_csv.py"),
        "--day",
        day_utc.replace("-", ""),
    ]
    try:
        proc = subprocess.run(
            cmd, cwd=str(root), capture_output=True, text=True, check=False, env=_build_subprocess_env(root)
        )
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _attempt_day2_catchup(
    root: Path,
    cycles: int,
    day2_min_hours_override: float = -1.0,
    day2_max_delta_override: int = -1,
) -> Tuple[int, str]:
    logs: List[str] = []
    worst_rc = 0
    for i in range(max(1, int(cycles))):
        rc_ingest, msg_ingest = _run_event_store_once(root)
        rc_count, msg_count = _run_event_store_count_check_once(root)
        logs.append(f"cycle={i + 1} event_store_once_rc={rc_ingest} count_check_rc={rc_count}")
        if msg_ingest:
            logs.append(f"cycle={i + 1} event_store_once_out={msg_ingest[:400]}")
        if msg_count:
            logs.append(f"cycle={i + 1} count_check_out={msg_count[:400]}")
        worst_rc = max(worst_rc, rc_ingest, rc_count)
    rc_day2, msg_day2 = _refresh_day2_gate_once(
        root,
        day2_min_hours_override=day2_min_hours_override,
        day2_max_delta_override=day2_max_delta_override,
    )
    logs.append(f"refresh_day2_gate_rc={rc_day2}")
    if msg_day2:
        logs.append(f"refresh_day2_gate_out={msg_day2[:400]}")
    worst_rc = max(worst_rc, rc_day2)
    return worst_rc, " | ".join(logs)


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


def _run_alerting_health_check(root: Path) -> Tuple[int, str]:
    cmd = [sys.executable, str(root / "scripts" / "release" / "check_alerting_health.py")]
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_bot_preflight_check(root: Path, require_container: bool = False) -> Tuple[int, str]:
    """Run preflight_startup.py to verify env file and CONFIG_PASSWORD in bot container."""
    cmd = [sys.executable, str(root / "scripts" / "ops" / "preflight_startup.py")]
    if require_container:
        cmd.append("--require-bot-container")
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_recon_exchange_preflight_check(root: Path) -> Tuple[int, str]:
    cmd = [
        sys.executable,
        str(root / "scripts" / "ops" / "preflight_startup.py"),
        "--require-recon-exchange",
    ]
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_paper_exchange_preflight_check(root: Path, strict: bool = False) -> Tuple[int, str]:
    cmd = [sys.executable, str(root / "scripts" / "ops" / "preflight_paper_exchange.py")]
    if strict:
        cmd.append("--strict")
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_checklist_evidence_collector(root: Path) -> Tuple[int, str]:
    cmd = [sys.executable, str(root / "scripts" / "ops" / "checklist_evidence_collector.py")]
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_telegram_validation(root: Path, strict: bool = False) -> Tuple[int, str]:
    cmd = [sys.executable, str(root / "scripts" / "ops" / "validate_telegram_alerting.py")]
    if strict:
        cmd.append("--strict")
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_data_plane_consistency_check(root: Path) -> Tuple[int, str]:
    cmd = [
        sys.executable,
        str(root / "scripts" / "release" / "validate_data_plane_consistency.py"),
        "--data", str(root / "data"),
        "--reports", str(root / "reports"),
        "--skip-inactive-h", "6",
    ]
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False, timeout=30)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_paper_exchange_load_harness(
    root: Path,
    *,
    strict: bool = False,
    duration_sec: float = 20.0,
    target_cmd_rate: float = 60.0,
    min_commands: int = 300,
    command_stream: str = "hb.paper_exchange.command.v1",
    event_stream: str = "hb.paper_exchange.event.v1",
    heartbeat_stream: str = "hb.paper_exchange.heartbeat.v1",
    producer: str = "hb_bridge_active_adapter",
    instance_name: str = "bot1",
    connector_name: str = "bitget_perpetual",
    trading_pair: str = "BTC-USDT",
    result_timeout_sec: float = 30.0,
    poll_interval_ms: int = 300,
    scan_count: int = 20_000,
) -> Tuple[int, str]:
    cmd = [
        sys.executable,
        str(root / "scripts" / "release" / "run_paper_exchange_load_harness.py"),
        "--duration-sec",
        str(max(0.1, float(duration_sec))),
        "--target-cmd-rate",
        str(max(1.0, float(target_cmd_rate))),
        "--min-commands",
        str(max(1, int(min_commands))),
        "--command-stream",
        str(command_stream),
        "--event-stream",
        str(event_stream),
        "--heartbeat-stream",
        str(heartbeat_stream),
        "--producer",
        str(producer),
        "--instance-name",
        str(instance_name),
        "--connector-name",
        str(connector_name),
        "--trading-pair",
        str(trading_pair),
        "--result-timeout-sec",
        str(max(0.0, float(result_timeout_sec))),
        "--poll-interval-ms",
        str(max(10, int(poll_interval_ms))),
        "--scan-count",
        str(max(100, int(scan_count))),
    ]
    if strict:
        cmd.append("--strict")
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
            env=_build_subprocess_env(root),
        )
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_paper_exchange_load_check(
    root: Path,
    *,
    strict: bool = False,
    lookback_sec: int = 600,
    sample_count: int = 8000,
    min_latency_samples: int = 200,
    min_window_sec: int = 120,
    command_stream: str = "hb.paper_exchange.command.v1",
    event_stream: str = "hb.paper_exchange.event.v1",
    heartbeat_stream: str = "hb.paper_exchange.heartbeat.v1",
    consumer_group: str = "hb_group_paper_exchange",
    heartbeat_consumer_group: str = "",
    heartbeat_consumer_name: str = "",
    load_run_id: str = "",
) -> Tuple[int, str]:
    cmd = [
        sys.executable,
        str(root / "scripts" / "release" / "check_paper_exchange_load.py"),
        "--lookback-sec",
        str(max(1, int(lookback_sec))),
        "--sample-count",
        str(max(1, int(sample_count))),
        "--min-latency-samples",
        str(max(1, int(min_latency_samples))),
        "--min-window-sec",
        str(max(1, int(min_window_sec))),
        "--command-stream",
        str(command_stream),
        "--event-stream",
        str(event_stream),
        "--heartbeat-stream",
        str(heartbeat_stream),
        "--consumer-group",
        str(consumer_group),
    ]
    if str(heartbeat_consumer_group or "").strip():
        cmd.extend(["--heartbeat-consumer-group", str(heartbeat_consumer_group).strip()])
    if str(heartbeat_consumer_name or "").strip():
        cmd.extend(["--heartbeat-consumer-name", str(heartbeat_consumer_name).strip()])
    if str(load_run_id or "").strip():
        cmd.extend(["--load-run-id", str(load_run_id).strip()])
    if strict:
        cmd.append("--strict")
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
            env=_build_subprocess_env(root),
        )
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_paper_exchange_threshold_inputs_builder(
    root: Path,
    *,
    max_source_age_min: float = 20.0,
) -> Tuple[int, str]:
    cmd = [
        sys.executable,
        str(root / "scripts" / "release" / "build_paper_exchange_threshold_inputs.py"),
        "--max-source-age-min",
        str(float(max_source_age_min)),
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
            env=_build_subprocess_env(root),
        )
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_paper_exchange_thresholds_check(
    root: Path,
    *,
    strict: bool = False,
    max_input_age_min: float = 20.0,
) -> Tuple[int, str]:
    cmd = [
        sys.executable,
        str(root / "scripts" / "release" / "check_paper_exchange_thresholds.py"),
        "--max-input-age-min",
        str(float(max_input_age_min)),
    ]
    if strict:
        cmd.append("--strict")
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_testnet_readiness_gate(root: Path, strict: bool = False) -> Tuple[int, str]:
    cmd = [sys.executable, str(root / "scripts" / "release" / "testnet_readiness_gate.py")]
    if strict:
        cmd.append("--strict")
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_testnet_daily_scorecard(root: Path, day_utc: str) -> Tuple[int, str]:
    cmd = [
        sys.executable,
        str(root / "scripts" / "analysis" / "testnet_daily_scorecard.py"),
        "--day",
        day_utc,
    ]
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_portfolio_diversification_check(root: Path) -> Tuple[int, str]:
    cmd = [
        sys.executable,
        str(root / "scripts" / "analysis" / "portfolio_diversification_check.py"),
    ]
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
        "--require-day2-fresh",
        action="store_true",
        help="Require Day2 gate artifact freshness within --max-report-age-min.",
    )
    parser.add_argument(
        "--require-parity-informative-core",
        action="store_true",
        help="Require parity core metrics (fill/slippage/reject deltas) to be informative for active bots.",
    )
    parser.add_argument(
        "--require-day2-lag-within-tolerance",
        action="store_true",
        help="Require day2 produced-vs-ingested lag to remain within --day2-max-delta.",
    )
    parser.add_argument(
        "--day2-max-delta",
        type=int,
        default=int(os.getenv("DAY2_GATE_MAX_DELTA", "5")),
        help="Max allowed produced-vs-ingested delta for day2 lag checks.",
    )
    parser.add_argument(
        "--attempt-day2-catchup",
        action="store_true",
        help="Run deterministic event-store catch-up steps before evaluating day2 lag gate.",
    )
    parser.add_argument(
        "--attempt-fill-event-backfill",
        action="store_true",
        help="Backfill order_filled events from fills.csv for the current UTC day before replay/parity checks.",
    )
    parser.add_argument(
        "--day2-catchup-cycles",
        type=int,
        default=2,
        help="Number of event-store catch-up cycles when --attempt-day2-catchup is enabled.",
    )
    parser.add_argument(
        "--day2-min-hours",
        type=float,
        default=-1.0,
        help="Optional override for DAY2_GATE_MIN_HOURS when refreshing day2 gate (-1 keeps environment/default).",
    )
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
    parser.add_argument(
        "--check-alerting-health",
        action="store_true",
        default=True,
        dest="check_alerting_health",
        help="Run alerting health probe before evaluating alerting_health gate (default: True).",
    )
    parser.add_argument(
        "--no-check-alerting-health",
        action="store_false",
        dest="check_alerting_health",
        help="Skip alerting health probe (use existing last_webhook_sent.json).",
    )
    parser.add_argument(
        "--check-bot-preflight",
        action="store_true",
        help="Run bot startup preflight (env file + CONFIG_PASSWORD in container).",
    )
    parser.add_argument(
        "--check-recon-exchange-preflight",
        action="store_true",
        help="Run reconciliation exchange-source readiness preflight.",
    )
    parser.add_argument(
        "--check-paper-exchange-preflight",
        action="store_true",
        default=str(os.getenv("PROMOTION_CHECK_PAPER_EXCHANGE_PREFLIGHT", "false")).strip().lower()
        in {"1", "true", "yes", "on"},
        help="Run paper-exchange service wiring preflight gate.",
    )
    parser.add_argument(
        "--collect-go-live-evidence",
        action="store_true",
        help="Run go-live checklist evidence collector and enforce artifact gate.",
    )
    parser.add_argument(
        "--check-telegram-validation",
        action="store_true",
        help="Run Telegram alerting validator and enforce diagnosis gate.",
    )
    parser.add_argument(
        "--check-testnet-readiness",
        action="store_true",
        help="Run ROAD-5 testnet readiness gate.",
    )
    parser.add_argument(
        "--check-testnet-daily-scorecard",
        action="store_true",
        help="Run ROAD-5 daily scorecard for UTC today.",
    )
    parser.add_argument(
        "--check-portfolio-diversification",
        action="store_true",
        help="Run ROAD-9 BTC/ETH diversification evidence check (warning gate).",
    )
    parser.add_argument(
        "--check-data-plane-consistency",
        action="store_true",
        help="Run INFRA-5 data-plane consistency gate (requires desk_snapshot_service running).",
    )
    parser.add_argument(
        "--check-paper-exchange-thresholds",
        action="store_true",
        default=str(os.getenv("PROMOTION_CHECK_PAPER_EXCHANGE_THRESHOLDS", "false")).strip().lower()
        in {"1", "true", "yes", "on"},
        help=(
            "Run quantitative paper-exchange threshold evaluator "
            "(reports/verification/paper_exchange_thresholds_latest.json)."
        ),
    )
    parser.add_argument(
        "--paper-exchange-threshold-max-age-min",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_THRESHOLD_MAX_AGE_MIN", "20")),
        help="Max allowed age (minutes) for paper-exchange threshold input artifact.",
    )
    parser.add_argument(
        "--build-paper-exchange-threshold-inputs",
        action="store_true",
        default=True,
        help="Build threshold input artifact before paper-exchange threshold evaluation.",
    )
    parser.add_argument(
        "--no-build-paper-exchange-threshold-inputs",
        action="store_false",
        dest="build_paper_exchange_threshold_inputs",
        help="Skip threshold input artifact builder (use existing input artifact).",
    )
    parser.add_argument(
        "--paper-exchange-threshold-source-max-age-min",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_THRESHOLD_SOURCE_MAX_AGE_MIN", "20")),
        help="Max source artifact age (minutes) used by threshold input builder.",
    )
    parser.add_argument(
        "--check-paper-exchange-load",
        action="store_true",
        default=True,
        help="Build paper-exchange load/backpressure evidence before threshold input build.",
    )
    parser.add_argument(
        "--no-check-paper-exchange-load",
        action="store_false",
        dest="check_paper_exchange_load",
        help="Skip paper-exchange load/backpressure evidence generation.",
    )
    parser.add_argument(
        "--run-paper-exchange-load-harness",
        action="store_true",
        default=str(os.getenv("PROMOTION_RUN_PAPER_EXCHANGE_LOAD_HARNESS", "false")).strip().lower()
        in {"1", "true", "yes", "on"},
        help="Inject synthetic sync_state command load before paper-exchange load checker.",
    )
    parser.add_argument(
        "--paper-exchange-load-harness-duration-sec",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_DURATION_SEC", "20")),
        help="Duration of synthetic paper-exchange load harness run.",
    )
    parser.add_argument(
        "--paper-exchange-load-harness-target-cmd-rate",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_TARGET_CMD_RATE", "60")),
        help="Target sync_state command publish rate for load harness.",
    )
    parser.add_argument(
        "--paper-exchange-load-harness-min-commands",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_MIN_COMMANDS", "300")),
        help="Minimum commands the harness must publish for pass-grade evidence.",
    )
    parser.add_argument(
        "--paper-exchange-load-command-stream",
        default=os.getenv("PAPER_EXCHANGE_COMMAND_STREAM", "hb.paper_exchange.command.v1"),
        help="Command stream used by paper-exchange load harness/check.",
    )
    parser.add_argument(
        "--paper-exchange-load-event-stream",
        default=os.getenv("PAPER_EXCHANGE_EVENT_STREAM", "hb.paper_exchange.event.v1"),
        help="Event stream used by paper-exchange load harness/check.",
    )
    parser.add_argument(
        "--paper-exchange-load-heartbeat-stream",
        default=os.getenv("PAPER_EXCHANGE_HEARTBEAT_STREAM", "hb.paper_exchange.heartbeat.v1"),
        help="Heartbeat stream used by paper-exchange load harness/check.",
    )
    parser.add_argument(
        "--paper-exchange-load-consumer-group",
        default=os.getenv("PAPER_EXCHANGE_CONSUMER_GROUP", "hb_group_paper_exchange"),
        help="Consumer group used by load checker lag/pending diagnostics.",
    )
    parser.add_argument(
        "--paper-exchange-load-heartbeat-consumer-group",
        default=os.getenv("PAPER_EXCHANGE_CONSUMER_GROUP", ""),
        help="Optional heartbeat metadata consumer_group filter for load checker restart diagnostics.",
    )
    parser.add_argument(
        "--paper-exchange-load-heartbeat-consumer-name",
        default=os.getenv("PAPER_EXCHANGE_CONSUMER_NAME", ""),
        help="Optional heartbeat metadata consumer_name filter for load checker restart diagnostics.",
    )
    parser.add_argument(
        "--paper-exchange-load-harness-producer",
        default=os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_PRODUCER", "hb_bridge_active_adapter"),
        help="Producer name emitted by the synthetic load harness.",
    )
    parser.add_argument(
        "--paper-exchange-load-harness-instance-name",
        default=os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_INSTANCE_NAME", "bot1"),
        help="Instance name used in harness commands.",
    )
    parser.add_argument(
        "--paper-exchange-load-harness-connector-name",
        default=os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_CONNECTOR_NAME", "bitget_perpetual"),
        help="Connector used in harness commands.",
    )
    parser.add_argument(
        "--paper-exchange-load-harness-trading-pair",
        default=os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_TRADING_PAIR", "BTC-USDT"),
        help="Trading pair used in harness commands.",
    )
    parser.add_argument(
        "--paper-exchange-load-harness-result-timeout-sec",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_RESULT_TIMEOUT_SEC", "30")),
        help="Timeout waiting for command results during harness execution.",
    )
    parser.add_argument(
        "--paper-exchange-load-harness-poll-interval-ms",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_POLL_INTERVAL_MS", "300")),
        help="Polling interval for harness result collection.",
    )
    parser.add_argument(
        "--paper-exchange-load-harness-scan-count",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_SCAN_COUNT", "20000")),
        help="Rows scanned by harness when matching command results.",
    )
    parser.add_argument(
        "--paper-exchange-load-lookback-sec",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_LOAD_LOOKBACK_SEC", "600")),
        help="Load-evidence window in seconds for paper-exchange load checker.",
    )
    parser.add_argument(
        "--paper-exchange-load-sample-count",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_LOAD_SAMPLE_COUNT", "8000")),
        help="Max stream rows sampled by paper-exchange load checker.",
    )
    parser.add_argument(
        "--paper-exchange-load-min-latency-samples",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_LOAD_MIN_LATENCY_SAMPLES", "200")),
        help="Minimum matched command/result samples for pass-grade load evidence.",
    )
    parser.add_argument(
        "--paper-exchange-load-min-window-sec",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_LOAD_MIN_WINDOW_SEC", "120")),
        help="Minimum command observation window (seconds) for pass-grade load evidence.",
    )
    parser.add_argument(
        "--paper-exchange-load-run-id",
        default=os.getenv("PAPER_EXCHANGE_LOAD_RUN_ID", ""),
        help="Optional run_id filter for load checker (defaults to latest harness run_id when harness is executed).",
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
    alerting_health_rc = 0
    alerting_health_msg = ""
    recon_preflight_rc = 0
    recon_preflight_msg = ""
    paper_exchange_preflight_rc = 0
    paper_exchange_preflight_msg = ""
    checklist_evidence_rc = 0
    checklist_evidence_msg = ""
    telegram_validation_rc = 0
    telegram_validation_msg = ""
    testnet_readiness_rc = 0
    testnet_readiness_msg = ""
    testnet_scorecard_rc = 0
    testnet_scorecard_msg = ""
    diversification_rc = 0
    diversification_msg = ""
    paper_exchange_load_harness_rc = 0
    paper_exchange_load_harness_msg = ""
    paper_exchange_load_rc = 0
    paper_exchange_load_msg = ""
    paper_exchange_load_run_id = ""
    paper_exchange_threshold_inputs_rc = 0
    paper_exchange_threshold_inputs_msg = ""
    paper_exchange_thresholds_rc = 0
    paper_exchange_thresholds_msg = ""
    day2_catchup_rc = 0
    day2_catchup_msg = ""
    fill_backfill_rc = 0
    fill_backfill_msg = ""
    recon_refresh_rc = 0
    recon_refresh_msg = ""

    max_report_age_min = float(args.max_report_age_min)
    refresh_parity_once = bool(args.refresh_parity_once or args.ci)
    refresh_event_integrity_once = bool(args.refresh_event_integrity_once or args.ci)
    if args.ci and args.max_report_age_min == 20:
        max_report_age_min = 15.0

    if refresh_parity_once:
        parity_refresh_rc, parity_refresh_msg = _refresh_parity_once(root)

    if refresh_event_integrity_once:
        integrity_refresh_rc, integrity_refresh_msg = _refresh_event_store_integrity_once(root)

    attempt_fill_event_backfill = bool(args.attempt_fill_event_backfill or args.ci)
    if attempt_fill_event_backfill:
        fill_backfill_rc, fill_backfill_msg = _run_fill_event_backfill_once(
            root, day_utc=datetime.now(timezone.utc).date().isoformat()
        )

    day2_min_hours_override = float(args.day2_min_hours)
    if day2_min_hours_override < 0 and args.ci:
        day2_min_hours_override = 0.0

    if args.attempt_day2_catchup:
        day2_catchup_rc, day2_catchup_msg = _attempt_day2_catchup(
            root,
            cycles=int(args.day2_catchup_cycles),
            day2_min_hours_override=day2_min_hours_override,
            day2_max_delta_override=int(args.day2_max_delta),
        )

    if args.check_recon_exchange_preflight:
        recon_refresh_rc, recon_refresh_msg = _refresh_reconciliation_exchange_once(root)

    if args.check_alerting_health:
        alerting_health_rc, alerting_health_msg = _run_alerting_health_check(root)

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
        root / "scripts" / "release" / "check_alerting_health.py",
        root / "scripts" / "release" / "run_paper_exchange_load_harness.py",
        root / "scripts" / "release" / "check_paper_exchange_load.py",
        root / "scripts" / "release" / "build_paper_exchange_threshold_inputs.py",
        root / "scripts" / "release" / "check_paper_exchange_thresholds.py",
        root / "scripts" / "ops" / "preflight_startup.py",
        root / "scripts" / "ops" / "preflight_paper_exchange.py",
        root / "scripts" / "ops" / "checklist_evidence_collector.py",
        root / "scripts" / "ops" / "validate_telegram_alerting.py",
        root / "scripts" / "release" / "testnet_readiness_gate.py",
        root / "scripts" / "analysis" / "testnet_daily_scorecard.py",
        root / "scripts" / "analysis" / "portfolio_diversification_check.py",
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

    # 1b) Bot startup preflight (env + CONFIG_PASSWORD) — when --check-bot-preflight
    if args.check_bot_preflight:
        preflight_rc, preflight_msg = _run_bot_preflight_check(root, require_container=args.ci)
        preflight_ok = preflight_rc == 0
        checks.append(
            _check(
                preflight_ok,
                "bot_startup_preflight",
                "critical",
                "env file + CONFIG_PASSWORD in bot container OK" if preflight_ok else f"preflight failed: {preflight_msg[:200]}",
                [str(root / "scripts" / "ops" / "preflight_startup.py")],
            )
        )
        if not preflight_ok:
            critical_failures.append("bot_startup_preflight")

    # 1c) Reconciliation exchange-source readiness
    if args.check_recon_exchange_preflight:
        recon_preflight_rc, recon_preflight_msg = _run_recon_exchange_preflight_check(root)
        recon_preflight_ok = recon_preflight_rc == 0
        checks.append(
            _check(
                recon_preflight_ok,
                "recon_exchange_live_gate",
                "critical",
                "reconciliation exchange-source readiness PASS"
                if recon_preflight_ok
                else f"reconciliation exchange-source preflight failed (rc={recon_preflight_rc})",
                [str(root / "reports" / "ops" / "preflight_recon_latest.json")],
            )
        )
        if not recon_preflight_ok:
            critical_failures.append("recon_exchange_live_gate")

    # 1d) Paper exchange preflight
    if args.check_paper_exchange_preflight:
        paper_exchange_preflight_rc, paper_exchange_preflight_msg = _run_paper_exchange_preflight_check(
            root, strict=bool(args.ci)
        )
        pe_preflight_path = root / "reports" / "ops" / "preflight_paper_exchange_latest.json"
        pe_preflight_report = _read_json(pe_preflight_path, {})
        pe_preflight_ok = (
            paper_exchange_preflight_rc == 0
            and str(pe_preflight_report.get("status", "fail")).strip().lower() == "pass"
        )
        checks.append(
            _check(
                pe_preflight_ok,
                "paper_exchange_preflight",
                "critical",
                "paper-exchange preflight PASS"
                if pe_preflight_ok
                else f"paper-exchange preflight failed (rc={paper_exchange_preflight_rc})",
                [str(pe_preflight_path)],
            )
        )
        if not pe_preflight_ok:
            critical_failures.append("paper_exchange_preflight")

    # 1e) Go-live checklist evidence collector
    if args.collect_go_live_evidence:
        checklist_evidence_rc, checklist_evidence_msg = _run_checklist_evidence_collector(root)
        evidence_path = root / "reports" / "ops" / "go_live_checklist_evidence_latest.json"
        evidence_report = _read_json(evidence_path, {})
        evidence_status = str(evidence_report.get("overall_status", "fail"))
        evidence_ok = checklist_evidence_rc == 0 and evidence_status in {"pass", "in_progress"}
        checks.append(
            _check(
                evidence_ok,
                "go_live_checklist_evidence_gate",
                "critical",
                f"go-live checklist evidence collected (status={evidence_status})"
                if evidence_ok
                else f"go-live checklist evidence failed (rc={checklist_evidence_rc}, status={evidence_status})",
                [str(evidence_path), str(root / "docs" / "ops" / "go_live_hardening_checklist.md")],
            )
        )
        if not evidence_ok:
            critical_failures.append("go_live_checklist_evidence_gate")

    # 1f) Telegram validation evidence
    if args.check_telegram_validation:
        telegram_validation_rc, telegram_validation_msg = _run_telegram_validation(root, strict=bool(args.ci))
        telegram_path = root / "reports" / "ops" / "telegram_validation_latest.json"
        telegram_report = _read_json(telegram_path, {})
        telegram_ok = telegram_validation_rc == 0 and str(telegram_report.get("status", "error")) == "ok"
        checks.append(
            _check(
                telegram_ok,
                "telegram_alerting_gate",
                "critical",
                "telegram alerting validation PASS"
                if telegram_ok
                else f"telegram alerting validation failed (rc={telegram_validation_rc}, diagnosis={telegram_report.get('diagnosis', 'unknown')})",
                [str(telegram_path)],
            )
        )
        if not telegram_ok:
            critical_failures.append("telegram_alerting_gate")

    # 1g) ROAD-5 testnet readiness gate
    if args.check_testnet_readiness:
        testnet_readiness_rc, testnet_readiness_msg = _run_testnet_readiness_gate(root, strict=bool(args.ci))
        testnet_ready_path = root / "reports" / "ops" / "testnet_readiness_latest.json"
        testnet_ready = _read_json(testnet_ready_path, {})
        testnet_ready_ok = testnet_readiness_rc == 0 and str(testnet_ready.get("status", "fail")) == "pass"
        checks.append(
            _check(
                testnet_ready_ok,
                "testnet_readiness_gate",
                "warning",
                "testnet readiness PASS" if testnet_ready_ok else "testnet readiness not yet pass",
                [str(testnet_ready_path)],
            )
        )

    # 1h) ROAD-5 daily scorecard
    if args.check_testnet_daily_scorecard:
        day_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        testnet_scorecard_rc, testnet_scorecard_msg = _run_testnet_daily_scorecard(root, day_utc=day_utc)
        testnet_score_path = root / "reports" / "strategy" / "testnet_daily_scorecard_latest.json"
        testnet_score = _read_json(testnet_score_path, {})
        testnet_score_ok = testnet_scorecard_rc == 0 and str(testnet_score.get("status", "fail")) == "pass"
        checks.append(
            _check(
                testnet_score_ok,
                "testnet_daily_scorecard",
                "warning",
                f"testnet daily scorecard PASS ({day_utc})"
                if testnet_score_ok
                else f"testnet daily scorecard not pass ({day_utc})",
                [str(testnet_score_path)],
            )
        )

    # 1i) ROAD-9 diversification evidence (BTC vs ETH correlation + inverse-variance weights)
    if args.check_portfolio_diversification:
        diversification_rc, diversification_msg = _run_portfolio_diversification_check(root)
        diversification_path = reports / "policy" / "portfolio_diversification_latest.json"
        diversification_report = _read_json(diversification_path, {})
        div_gate_ok, div_reason = _portfolio_diversification_gate(diversification_report)
        if diversification_rc != 0 and str(diversification_report.get("status", "")).lower() != "fail":
            div_gate_ok = False
            div_reason = f"portfolio diversification check execution failed (rc={diversification_rc})"
        checks.append(
            _check(
                div_gate_ok,
                "portfolio_diversification",
                "warning",
                div_reason,
                [str(diversification_path)],
            )
        )

    # 1j) INFRA-5 data-plane consistency gate
    if args.check_data_plane_consistency:
        dp_rc, dp_msg = _run_data_plane_consistency_check(root)
        dp_path = reports / "data_plane_consistency" / "latest.json"
        dp_report = _read_json(dp_path, {})
        dp_ok = dp_rc == 0 and str(dp_report.get("status", "FAIL")) == "PASS"
        checks.append(
            _check(
                dp_ok,
                "data_plane_consistency",
                "warning",
                "data-plane consistency PASS (snapshot fresh + complete for all bots)"
                if dp_ok
                else f"data-plane consistency check failed (rc={dp_rc}): {dp_msg[:200]}",
                [str(dp_path)],
            )
        )

    # 1k) Quantitative paper-exchange threshold gate
    if args.check_paper_exchange_thresholds:
        if args.check_paper_exchange_load and args.run_paper_exchange_load_harness:
            paper_exchange_load_harness_rc, paper_exchange_load_harness_msg = _run_paper_exchange_load_harness(
                root,
                strict=False,
                duration_sec=float(args.paper_exchange_load_harness_duration_sec),
                target_cmd_rate=float(args.paper_exchange_load_harness_target_cmd_rate),
                min_commands=int(args.paper_exchange_load_harness_min_commands),
                command_stream=str(args.paper_exchange_load_command_stream),
                event_stream=str(args.paper_exchange_load_event_stream),
                heartbeat_stream=str(args.paper_exchange_load_heartbeat_stream),
                producer=str(args.paper_exchange_load_harness_producer),
                instance_name=str(args.paper_exchange_load_harness_instance_name),
                connector_name=str(args.paper_exchange_load_harness_connector_name),
                trading_pair=str(args.paper_exchange_load_harness_trading_pair),
                result_timeout_sec=float(args.paper_exchange_load_harness_result_timeout_sec),
                poll_interval_ms=int(args.paper_exchange_load_harness_poll_interval_ms),
                scan_count=int(args.paper_exchange_load_harness_scan_count),
            )
            pe_harness_path = reports / "verification" / "paper_exchange_load_harness_latest.json"
            pe_harness_report = _read_json(pe_harness_path, {})
            pe_harness_diag = pe_harness_report.get("diagnostics", {})
            pe_harness_diag = pe_harness_diag if isinstance(pe_harness_diag, dict) else {}
            paper_exchange_load_run_id = str(pe_harness_diag.get("run_id", "")).strip()
            pe_harness_ok = (
                paper_exchange_load_harness_rc == 0
                and str(pe_harness_report.get("status", "fail")).strip().lower() == "pass"
            )
            checks.append(
                _check(
                    pe_harness_ok,
                    "paper_exchange_load_harness",
                    "warning",
                    "paper-exchange load harness PASS"
                    if pe_harness_ok
                    else f"paper-exchange load harness failed (rc={paper_exchange_load_harness_rc})",
                    [str(pe_harness_path)],
                )
            )
        if args.check_paper_exchange_load:
            paper_exchange_load_rc, paper_exchange_load_msg = _run_paper_exchange_load_check(
                root,
                strict=False,
                lookback_sec=int(args.paper_exchange_load_lookback_sec),
                sample_count=int(args.paper_exchange_load_sample_count),
                min_latency_samples=int(args.paper_exchange_load_min_latency_samples),
                min_window_sec=int(args.paper_exchange_load_min_window_sec),
                command_stream=str(args.paper_exchange_load_command_stream),
                event_stream=str(args.paper_exchange_load_event_stream),
                heartbeat_stream=str(args.paper_exchange_load_heartbeat_stream),
                consumer_group=str(args.paper_exchange_load_consumer_group),
                heartbeat_consumer_group=str(args.paper_exchange_load_heartbeat_consumer_group),
                heartbeat_consumer_name=str(args.paper_exchange_load_heartbeat_consumer_name),
                load_run_id=(paper_exchange_load_run_id or str(args.paper_exchange_load_run_id)),
            )
            pe_load_path = reports / "verification" / "paper_exchange_load_latest.json"
            pe_load_report = _read_json(pe_load_path, {})
            pe_load_status = str(pe_load_report.get("status", "")).strip().lower()
            pe_load_ok = paper_exchange_load_rc == 0 and pe_load_status in {"pass", "warning"}
            checks.append(
                _check(
                    pe_load_ok,
                    "paper_exchange_load_validation",
                    "warning",
                    "paper-exchange load/backpressure evidence generated"
                    if pe_load_ok
                    else f"paper-exchange load/backpressure evidence failed (rc={paper_exchange_load_rc})",
                    [str(pe_load_path)],
                )
            )
        if args.build_paper_exchange_threshold_inputs:
            paper_exchange_threshold_inputs_rc, paper_exchange_threshold_inputs_msg = (
                _run_paper_exchange_threshold_inputs_builder(
                    root,
                    max_source_age_min=float(args.paper_exchange_threshold_source_max_age_min),
                )
            )
        paper_exchange_thresholds_rc, paper_exchange_thresholds_msg = _run_paper_exchange_thresholds_check(
            root,
            strict=bool(args.ci),
            max_input_age_min=float(args.paper_exchange_threshold_max_age_min),
        )
        pe_threshold_path = reports / "verification" / "paper_exchange_thresholds_latest.json"
        pe_threshold_report = _read_json(pe_threshold_path, {})
        pe_threshold_ok = (
            paper_exchange_thresholds_rc == 0
            and str(pe_threshold_report.get("status", "fail")).strip().lower() == "pass"
        )
        checks.append(
            _check(
                pe_threshold_ok,
                "paper_exchange_thresholds",
                "critical",
                "paper-exchange quantitative thresholds PASS"
                if pe_threshold_ok
                else (
                    "paper-exchange quantitative thresholds failed "
                    f"(rc={paper_exchange_thresholds_rc})"
                ),
                [str(pe_threshold_path)],
            )
        )
        if not pe_threshold_ok:
            critical_failures.append("paper_exchange_thresholds")

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
    parity_insufficient_bots, parity_active_bots = _parity_core_insufficient_active_bots(parity)
    parity_informative_ok = (not args.require_parity_informative_core) or (len(parity_insufficient_bots) == 0)
    if parity_ok and parity_fresh and parity_informative_ok:
        parity_reason = "parity pass, fresh, and informative"
    elif parity_ok and parity_fresh and not parity_informative_ok:
        parity_reason = (
            "parity core metrics insufficient_data for active bots: "
            + ",".join(parity_insufficient_bots)
        )
    else:
        parity_reason = "parity fail or stale"
    checks.append(
        _check(
            parity_ok and parity_fresh and parity_informative_ok,
            "parity_thresholds",
            "critical",
            parity_reason,
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

    # 18) Event stream coverage (desk-grade tracking requirement)
    required_streams = [
        "hb.market_data.v1",
        "hb.signal.v1",
        "hb.risk_decision.v1",
        "hb.execution_intent.v1",
        "hb.audit.v1",
        "hb.bot_telemetry.v1",
    ]
    events_by_stream = integrity.get("events_by_stream", {})
    stream_coverage_ok = isinstance(events_by_stream, dict) and all(
        float(events_by_stream.get(stream, 0) or 0) > 0 for stream in required_streams
    )
    checks.append(
        _check(
            stream_coverage_ok,
            "event_stream_coverage",
            "critical",
            "all required streams present in event_store integrity artifact"
            if stream_coverage_ok
            else "one or more required streams missing/zero in event_store integrity artifact",
            [str(integrity_path)],
        )
    )

    # 19) Ops DB writer freshness + non-empty ingestion
    ops_db_writer_path = reports / "ops_db_writer" / "latest.json"
    ops_db_writer = _read_json(ops_db_writer_path, {})
    ops_db_writer_fresh = (
        ops_db_writer_path.exists()
        and _minutes_since(str(ops_db_writer.get("ts_utc", ""))) <= max_report_age_min
    )
    ops_counts = ops_db_writer.get("counts", {})
    ops_non_empty = isinstance(ops_counts, dict) and (
        float(ops_counts.get("bot_snapshot_minute", 0) or 0) > 0
        and float(ops_counts.get("exchange_snapshot", 0) or 0) > 0
    )
    ops_db_writer_ok = (
        str(ops_db_writer.get("status", "fail")).lower() == "pass"
        and ops_db_writer_fresh
        and ops_non_empty
    )
    checks.append(
        _check(
            ops_db_writer_ok,
            "ops_db_writer_freshness",
            "critical",
            "ops_db_writer latest.json is pass/fresh with non-empty counts"
            if ops_db_writer_ok
            else "ops_db_writer missing/stale/failing or ingestion counts are empty",
            [str(ops_db_writer_path)],
        )
    )

    # 20) Market data freshness
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

    # 21) Optional strict day2 gate dependency
    day2_path = reports / "event_store" / "day2_gate_eval_latest.json"
    day2 = _read_json(day2_path, {})
    day2_go = bool(day2.get("go", False))
    day2_fresh, day2_age_min = _day2_freshness(day2, day2_path, max_report_age_min)
    day2_lag_ok, day2_lag_diag = _day2_lag_within_tolerance(
        day2=day2,
        reports_event_store=reports / "event_store",
        max_allowed_delta=int(args.day2_max_delta),
    )
    day2_go_ok = day2_go if args.require_day2_go else True
    day2_fresh_ok = day2_fresh if args.require_day2_fresh else True
    day2_lag_gate_ok = day2_lag_ok if args.require_day2_lag_within_tolerance else True
    day2_ok = day2_go_ok and day2_fresh_ok and day2_lag_gate_ok
    if day2_ok:
        day2_reason = (
            "day2 gate GO/fresh with lag in tolerance "
            f"(age_min={day2_age_min:.1f} max_delta={int(day2_lag_diag.get('max_delta_observed', 0))})"
        )
    else:
        day2_reason = (
            f"day2 gate status: go={day2_go} age_min={day2_age_min:.1f} "
            f"max_delta={int(day2_lag_diag.get('max_delta_observed', 0))}/"
            f"{int(day2_lag_diag.get('max_allowed_delta', int(args.day2_max_delta)))} "
            f"worst_stream={str(day2_lag_diag.get('worst_stream', ''))} "
            f"(require_go={bool(args.require_day2_go)} "
            f"require_fresh={bool(args.require_day2_fresh)} "
            f"require_lag_tolerance={bool(args.require_day2_lag_within_tolerance)}). "
            "Remediation: run scripts/release/run_bus_recovery_check.py with --enforce-absolute-delta "
            "and ensure event_store consumer catches up before strict cycle."
        )
    day2_evidence = [str(day2_path)]
    source_compare_path = str(day2_lag_diag.get("source_compare_path", "")).strip()
    if source_compare_path:
        day2_evidence.append(source_compare_path)
    checks.append(
        _check(
            day2_ok,
            "day2_event_store_gate",
            "critical",
            day2_reason,
            day2_evidence,
        )
    )

    # 22) Validation ladder: paper soak (Level 3) required for live promotion
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

    # 23) Validation ladder: post-trade validation (Level 6) — informational
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

    # Preserve order while removing duplicates from mixed direct/check-derived appends.
    critical_failures = list(dict.fromkeys(critical_failures))

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
            "require_day2_fresh": bool(args.require_day2_fresh),
            "require_day2_lag_within_tolerance": bool(args.require_day2_lag_within_tolerance),
            "day2_max_delta": int(args.day2_max_delta),
            "require_parity_informative_core": bool(args.require_parity_informative_core),
            "parity_active_bots": parity_active_bots,
            "parity_insufficient_active_bots": parity_insufficient_bots,
            "day2_lag_ok": bool(day2_lag_ok),
            "day2_lag_diagnostics": day2_lag_diag,
            "day2_catchup_attempted": bool(args.attempt_day2_catchup),
            "day2_catchup_cycles": int(args.day2_catchup_cycles),
            "day2_min_hours_override": day2_min_hours_override,
            "day2_catchup_rc": int(day2_catchup_rc),
            "day2_catchup_output": day2_catchup_msg[:2000],
            "fill_event_backfill_attempted": bool(attempt_fill_event_backfill),
            "fill_event_backfill_rc": int(fill_backfill_rc),
            "fill_event_backfill_output": fill_backfill_msg[:2000],
            "reconciliation_refresh_rc": int(recon_refresh_rc),
            "reconciliation_refresh_output": recon_refresh_msg[:2000],
            "integrity_refresh_rc": integrity_refresh_rc,
            "integrity_refresh_output": integrity_refresh_msg[:2000],
            "accounting_integrity_runner_output": accounting_msg[:2000],
            "market_data_freshness_runner_output": md_msg[:2000],
            "alerting_health_runner_output": alerting_health_msg[:2000],
            "alerting_health_rc": alerting_health_rc,
            "recon_exchange_preflight_output": recon_preflight_msg[:2000],
            "recon_exchange_preflight_rc": recon_preflight_rc,
            "paper_exchange_preflight_output": paper_exchange_preflight_msg[:2000],
            "paper_exchange_preflight_rc": paper_exchange_preflight_rc,
            "check_paper_exchange_preflight": bool(args.check_paper_exchange_preflight),
            "go_live_checklist_evidence_output": checklist_evidence_msg[:2000],
            "go_live_checklist_evidence_rc": checklist_evidence_rc,
            "telegram_validation_output": telegram_validation_msg[:2000],
            "telegram_validation_rc": telegram_validation_rc,
            "testnet_readiness_output": testnet_readiness_msg[:2000],
            "testnet_readiness_rc": testnet_readiness_rc,
            "testnet_scorecard_output": testnet_scorecard_msg[:2000],
            "testnet_scorecard_rc": testnet_scorecard_rc,
            "portfolio_diversification_output": diversification_msg[:2000],
            "portfolio_diversification_rc": diversification_rc,
            "check_paper_exchange_thresholds": bool(args.check_paper_exchange_thresholds),
            "check_paper_exchange_load": bool(args.check_paper_exchange_load),
            "run_paper_exchange_load_harness": bool(args.run_paper_exchange_load_harness),
            "paper_exchange_load_harness_duration_sec": float(args.paper_exchange_load_harness_duration_sec),
            "paper_exchange_load_harness_target_cmd_rate": float(args.paper_exchange_load_harness_target_cmd_rate),
            "paper_exchange_load_harness_min_commands": int(args.paper_exchange_load_harness_min_commands),
            "paper_exchange_load_harness_producer": str(args.paper_exchange_load_harness_producer),
            "paper_exchange_load_harness_instance_name": str(args.paper_exchange_load_harness_instance_name),
            "paper_exchange_load_harness_connector_name": str(args.paper_exchange_load_harness_connector_name),
            "paper_exchange_load_harness_trading_pair": str(args.paper_exchange_load_harness_trading_pair),
            "paper_exchange_load_harness_result_timeout_sec": float(args.paper_exchange_load_harness_result_timeout_sec),
            "paper_exchange_load_harness_poll_interval_ms": int(args.paper_exchange_load_harness_poll_interval_ms),
            "paper_exchange_load_harness_scan_count": int(args.paper_exchange_load_harness_scan_count),
            "paper_exchange_load_harness_output": paper_exchange_load_harness_msg[:2000],
            "paper_exchange_load_harness_rc": int(paper_exchange_load_harness_rc),
            "paper_exchange_load_run_id": paper_exchange_load_run_id,
            "paper_exchange_load_command_stream": str(args.paper_exchange_load_command_stream),
            "paper_exchange_load_event_stream": str(args.paper_exchange_load_event_stream),
            "paper_exchange_load_heartbeat_stream": str(args.paper_exchange_load_heartbeat_stream),
            "paper_exchange_load_consumer_group": str(args.paper_exchange_load_consumer_group),
            "paper_exchange_load_heartbeat_consumer_group": str(args.paper_exchange_load_heartbeat_consumer_group),
            "paper_exchange_load_heartbeat_consumer_name": str(args.paper_exchange_load_heartbeat_consumer_name),
            "paper_exchange_load_run_id_override": str(args.paper_exchange_load_run_id),
            "paper_exchange_load_lookback_sec": int(args.paper_exchange_load_lookback_sec),
            "paper_exchange_load_sample_count": int(args.paper_exchange_load_sample_count),
            "paper_exchange_load_min_latency_samples": int(args.paper_exchange_load_min_latency_samples),
            "paper_exchange_load_min_window_sec": int(args.paper_exchange_load_min_window_sec),
            "paper_exchange_load_output": paper_exchange_load_msg[:2000],
            "paper_exchange_load_rc": int(paper_exchange_load_rc),
            "build_paper_exchange_threshold_inputs": bool(args.build_paper_exchange_threshold_inputs),
            "paper_exchange_threshold_source_max_age_min": float(args.paper_exchange_threshold_source_max_age_min),
            "paper_exchange_threshold_inputs_output": paper_exchange_threshold_inputs_msg[:2000],
            "paper_exchange_threshold_inputs_rc": paper_exchange_threshold_inputs_rc,
            "paper_exchange_threshold_max_age_min": float(args.paper_exchange_threshold_max_age_min),
            "paper_exchange_thresholds_output": paper_exchange_thresholds_msg[:2000],
            "paper_exchange_thresholds_rc": paper_exchange_thresholds_rc,
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
