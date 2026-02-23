from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _root() -> Path:
    return Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]


def _compose_cmd(*args: str) -> List[str]:
    return [
        "docker",
        "compose",
        "--env-file",
        "env/.env",
        "-f",
        "compose/docker-compose.yml",
        *args,
    ]


def _run_cmd(root: Path, cmd: List[str], timeout_sec: int = 60) -> Dict[str, object]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_sec,
        )
        return {
            "cmd": cmd,
            "rc": int(proc.returncode),
            "stdout": (proc.stdout or "")[:4000],
            "stderr": (proc.stderr or "")[:4000],
        }
    except subprocess.TimeoutExpired as exc:
        return {"cmd": cmd, "rc": 124, "stdout": (exc.stdout or "")[:4000], "stderr": "command timeout"}
    except Exception as exc:
        return {"cmd": cmd, "rc": 2, "stdout": "", "stderr": str(exc)}


def _container_state(root: Path, container_name: str) -> str:
    cmd = [
        "docker",
        "inspect",
        "-f",
        "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}",
        container_name,
    ]
    out = _run_cmd(root, cmd, timeout_sec=20)
    if int(out.get("rc", 1)) != 0:
        return "missing"
    return str(out.get("stdout", "")).strip().lower() or "unknown"


def _write_report(root: Path, payload: Dict[str, object]) -> Path:
    out_dir = root / "reports" / "recovery"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = out_dir / f"recover_event_store_strict_{stamp}.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (out_dir / "latest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bring up minimal event-store external stack, wait health, then run strict cycle."
    )
    parser.add_argument("--max-wait-sec", type=int, default=180, help="Max wait for service health.")
    parser.add_argument("--poll-sec", type=int, default=5, help="Poll interval while waiting for health.")
    parser.add_argument("--max-report-age-min", type=int, default=20, help="Strict cycle freshness window.")
    args = parser.parse_args()

    root = _root()
    containers = {
        "redis": "hbot-redis",
        "event_store_service": "hbot-event-store-service",
        "event_store_monitor": "hbot-event-store-monitor",
        "day2_gate_monitor": "hbot-day2-gate-monitor",
    }

    docker_info = _run_cmd(root, ["docker", "info"], timeout_sec=30)
    if int(docker_info.get("rc", 1)) != 0:
        payload = {
            "ts_utc": _utc_now(),
            "status": "blocked",
            "reason": "docker_unavailable",
            "docker_info": docker_info,
            "service_states": {k: "unknown" for k in containers.keys()},
            "strict_cycle": {"rc": None, "stdout": "", "stderr": ""},
        }
        out = _write_report(root, payload)
        print(f"[recover-event-store] status=blocked")
        print(f"[recover-event-store] evidence={out}")
        return 2

    compose_up = _run_cmd(
        root,
        _compose_cmd(
            "--profile",
            "external",
            "up",
            "-d",
            "redis",
            "event-store-service",
            "event-store-monitor",
            "day2-gate-monitor",
        ),
        timeout_sec=120,
    )

    start = time.time()
    service_states: Dict[str, str] = {}
    healthy = False
    while time.time() - start <= max(30, int(args.max_wait_sec)):
        service_states = {name: _container_state(root, cname) for name, cname in containers.items()}
        healthy = all(state == "healthy" for state in service_states.values())
        if healthy:
            break
        time.sleep(max(2, int(args.poll_sec)))

    strict_cycle = _run_cmd(
        root,
        [
            sys.executable,
            "scripts/release/run_strict_promotion_cycle.py",
            "--max-report-age-min",
            str(int(args.max_report_age_min)),
        ],
        timeout_sec=240,
    )

    status = "pass" if healthy and int(strict_cycle.get("rc", 1)) == 0 else "fail"
    payload = {
        "ts_utc": _utc_now(),
        "status": status,
        "compose_up": compose_up,
        "service_states": service_states,
        "strict_cycle": strict_cycle,
    }
    out = _write_report(root, payload)
    print(f"[recover-event-store] status={status}")
    print(f"[recover-event-store] evidence={out}")
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
