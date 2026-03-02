#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

from services.contracts import stream_names


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_env_map(path: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _check(name: str, ok: bool, reason: str, evidence_paths: List[str]) -> Dict[str, object]:
    return {
        "name": name,
        "pass": bool(ok),
        "reason": reason,
        "evidence_paths": evidence_paths,
    }


def build_report(root: Path) -> Dict[str, object]:
    checks: List[Dict[str, object]] = []

    service_script = root / "services" / "paper_exchange_service" / "main.py"
    checks.append(
        _check(
            "paper_exchange_service_script_exists",
            service_script.exists(),
            "service script exists" if service_script.exists() else "service script missing",
            [str(service_script)],
        )
    )

    compose_path = root / "compose" / "docker-compose.yml"
    compose_text = compose_path.read_text(encoding="utf-8") if compose_path.exists() else ""
    compose_has_service = "paper-exchange-service:" in compose_text
    compose_has_command = "services/paper_exchange_service/main.py" in compose_text
    checks.append(
        _check(
            "paper_exchange_compose_service_wired",
            compose_has_service and compose_has_command,
            "compose service block + command wiring present"
            if (compose_has_service and compose_has_command)
            else "compose paper-exchange service block/command wiring missing",
            [str(compose_path)],
        )
    )

    required_streams = [
        ("PAPER_EXCHANGE_COMMAND_STREAM", stream_names.PAPER_EXCHANGE_COMMAND_STREAM),
        ("PAPER_EXCHANGE_EVENT_STREAM", stream_names.PAPER_EXCHANGE_EVENT_STREAM),
        ("PAPER_EXCHANGE_HEARTBEAT_STREAM", stream_names.PAPER_EXCHANGE_HEARTBEAT_STREAM),
    ]
    streams_present = all(bool(value) for _name, value in required_streams)
    retention_ok = all(
        value in stream_names.STREAM_RETENTION_MAXLEN
        for _name, value in required_streams
    )
    checks.append(
        _check(
            "paper_exchange_stream_contracts",
            streams_present and retention_ok,
            "stream names + retention entries present"
            if (streams_present and retention_ok)
            else "stream names and/or retention entries missing",
            [str(root / "services" / "contracts" / "stream_names.py")],
        )
    )

    env_path = root / "env" / ".env"
    env_map = _read_env_map(env_path)
    allowed_raw = str(env_map.get("PAPER_EXCHANGE_ALLOWED_CONNECTORS", "")).strip()
    allowed = [x.strip() for x in allowed_raw.split(",") if x.strip()]
    checks.append(
        _check(
            "paper_exchange_allowed_connectors_non_empty",
            len(allowed) > 0,
            f"allowed connectors: {','.join(allowed)}" if allowed else "PAPER_EXCHANGE_ALLOWED_CONNECTORS missing/empty",
            [str(env_path)],
        )
    )

    env_template_path = root / "env" / ".env.template"
    env_template_map = _read_env_map(env_template_path)
    required_template_keys = [
        "PAPER_EXCHANGE_MODE_BOT1",
        "PAPER_EXCHANGE_MODE_BOT3",
        "PAPER_EXCHANGE_MODE_BOT4",
        "PAPER_EXCHANGE_SYNC_TIMEOUT_MS",
    ]
    missing_template_keys = [key for key in required_template_keys if key not in env_template_map]
    checks.append(
        _check(
            "paper_exchange_mode_toggle_template_keys_present",
            len(missing_template_keys) == 0,
            "paper-exchange rollout mode keys present in env template"
            if len(missing_template_keys) == 0
            else f"missing env template keys: {','.join(missing_template_keys)}",
            [str(env_template_path)],
        )
    )

    runbook_path = root / "docs" / "ops" / "runbooks.md"
    runbook_text = runbook_path.read_text(encoding="utf-8") if runbook_path.exists() else ""
    rollout_section_present = "Paper Exchange Service Rollout" in runbook_text
    rollback_section_present = "Paper Exchange Rollback" in runbook_text
    checks.append(
        _check(
            "paper_exchange_rollout_runbook_present",
            rollout_section_present and rollback_section_present,
            "rollout + rollback runbook sections present"
            if (rollout_section_present and rollback_section_present)
            else "paper-exchange rollout/rollback runbook sections missing",
            [str(runbook_path)],
        )
    )

    evaluator_script = root / "scripts" / "release" / "check_paper_exchange_thresholds.py"
    checks.append(
        _check(
            "paper_exchange_threshold_evaluator_exists",
            evaluator_script.exists(),
            "threshold evaluator script exists" if evaluator_script.exists() else "threshold evaluator script missing",
            [str(evaluator_script)],
        )
    )

    builder_script = root / "scripts" / "release" / "build_paper_exchange_threshold_inputs.py"
    checks.append(
        _check(
            "paper_exchange_threshold_inputs_builder_exists",
            builder_script.exists(),
            "threshold input builder script exists" if builder_script.exists() else "threshold input builder script missing",
            [str(builder_script)],
        )
    )

    load_check_script = root / "scripts" / "release" / "check_paper_exchange_load.py"
    checks.append(
        _check(
            "paper_exchange_load_check_exists",
            load_check_script.exists(),
            "load/backpressure check script exists" if load_check_script.exists() else "load/backpressure check script missing",
            [str(load_check_script)],
        )
    )

    load_harness_script = root / "scripts" / "release" / "run_paper_exchange_load_harness.py"
    checks.append(
        _check(
            "paper_exchange_load_harness_exists",
            load_harness_script.exists(),
            "load harness script exists" if load_harness_script.exists() else "load harness script missing",
            [str(load_harness_script)],
        )
    )

    canary_script = root / "scripts" / "ops" / "run_paper_exchange_canary.py"
    checks.append(
        _check(
            "paper_exchange_canary_launcher_exists",
            canary_script.exists(),
            "canary launcher script exists" if canary_script.exists() else "canary launcher script missing",
            [str(canary_script)],
        )
    )

    failed_checks = [str(c["name"]) for c in checks if not bool(c.get("pass", False))]
    status = "pass" if not failed_checks else "fail"
    return {
        "ts_utc": _utc_now(),
        "status": status,
        "failed_checks": failed_checks,
        "checks": checks,
    }


def run_check(*, strict: bool) -> int:
    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    report = build_report(root)
    out_dir = root / "reports" / "ops"
    out_dir.mkdir(parents=True, exist_ok=True)
    latest_path = out_dir / "preflight_paper_exchange_latest.json"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    ts_path = out_dir / f"preflight_paper_exchange_{stamp}.json"
    payload = json.dumps(report, indent=2)
    latest_path.write_text(payload, encoding="utf-8")
    ts_path.write_text(payload, encoding="utf-8")

    print(f"[paper-exchange-preflight] status={report.get('status')}")
    print(f"[paper-exchange-preflight] evidence={latest_path}")
    if strict and str(report.get("status", "fail")).lower() != "pass":
        return 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Preflight checks for paper-exchange service wiring.")
    parser.add_argument("--strict", action="store_true", help="Return non-zero on preflight failures.")
    args = parser.parse_args()
    return run_check(strict=bool(args.strict))


if __name__ == "__main__":
    raise SystemExit(main())

