#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mode_env_key(bot: str) -> str:
    suffix = str(bot or "").strip().upper()
    if not suffix.startswith("BOT"):
        raise ValueError(f"unsupported bot name: {bot}")
    return f"PAPER_EXCHANGE_MODE_{suffix}"


def _upsert_env_text(text: str, updates: Dict[str, str]) -> str:
    lines = text.splitlines()
    for key, value in updates.items():
        key_re = re.compile(rf"^\s*{re.escape(str(key))}\s*=")
        replaced = False
        new_line = f"{key}={value}"
        for i, line in enumerate(lines):
            if key_re.match(line):
                lines[i] = new_line
                replaced = True
                break
        if not replaced:
            lines.append(new_line)
    out = "\n".join(lines)
    if not out.endswith("\n"):
        out += "\n"
    return out


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


def _build_compose_start_cmd(env_path: Path, compose_path: Path) -> List[str]:
    return [
        "docker",
        "compose",
        "--env-file",
        str(env_path),
        "-f",
        str(compose_path),
        "--profile",
        "external",
        "--profile",
        "paper-exchange",
        "up",
        "-d",
        "--force-recreate",
        "redis",
        "paper-exchange-service",
    ]


def _build_bot_recreate_cmd(env_path: Path, compose_path: Path, bot: str) -> List[str]:
    bot_norm = str(bot).strip().lower()
    cmd = ["docker", "compose", "--env-file", str(env_path), "-f", str(compose_path)]
    if bot_norm in {"bot3", "bot4"}:
        cmd.extend(["--profile", "test"])
    elif bot_norm == "bot2":
        cmd.extend(["--profile", "multi"])
    cmd.extend(["up", "-d", "--force-recreate", bot_norm])
    return cmd


def _run_command(
    cmd: List[str],
    *,
    cwd: Path,
    timeout_sec: int = 300,
    pythonpath_root: Path | None = None,
) -> Tuple[int, str]:
    env = os.environ.copy()
    if pythonpath_root is not None:
        root_str = str(pythonpath_root)
        current = env.get("PYTHONPATH", "")
        parts = [p for p in current.split(os.pathsep) if p]
        if root_str not in parts:
            parts.insert(0, root_str)
        env["PYTHONPATH"] = os.pathsep.join(parts)
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=max(1, int(timeout_sec)),
        )
        out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), out.strip()
    except Exception as exc:
        return 2, f"{type(exc).__name__}: {exc}"


def _latest_harness_run_id(root: Path) -> str:
    latest = root / "reports" / "verification" / "paper_exchange_load_harness_latest.json"
    if not latest.exists():
        return ""
    try:
        payload = json.loads(latest.read_text(encoding="utf-8"))
        diag = payload.get("diagnostics", {})
        diag = diag if isinstance(diag, dict) else {}
        return str(diag.get("run_id", "")).strip()
    except Exception:
        return ""


def run_canary(
    *,
    root: Path,
    bot: str,
    mode: str,
    apply_env: bool,
    run_gates: bool,
    dry_run: bool,
    load_harness_duration_sec: float,
    load_harness_target_cmd_rate: float,
    load_harness_min_commands: int,
    load_check_lookback_sec: int,
    load_check_min_window_sec: int,
) -> int:
    env_path = root / "env" / ".env"
    compose_path = root / "compose" / "docker-compose.yml"
    reports_dir = root / "reports" / "ops"
    reports_dir.mkdir(parents=True, exist_ok=True)

    steps: List[Dict[str, object]] = []
    rc_final = 0

    if not env_path.exists():
        report = {
            "ts_utc": _utc_now(),
            "status": "fail",
            "reason": "env/.env missing",
            "bot": bot,
            "mode": mode,
            "steps": [],
        }
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_path = reports_dir / f"paper_exchange_canary_{stamp}.json"
        latest_path = reports_dir / "paper_exchange_canary_latest.json"
        payload = json.dumps(report, indent=2)
        out_path.write_text(payload, encoding="utf-8")
        latest_path.write_text(payload, encoding="utf-8")
        print("[paper-exchange-canary] status=fail reason=missing_env_file")
        print(f"[paper-exchange-canary] evidence={latest_path}")
        return 2

    env_backup_path = ""
    if apply_env:
        original = env_path.read_text(encoding="utf-8")
        updates = {
            _mode_env_key(bot): mode,
            "PAPER_EXCHANGE_ALLOWED_CONNECTORS": "bitget_perpetual",
            "PAPER_EXCHANGE_ALLOWED_COMMAND_PRODUCERS": "hb_bridge_active_adapter",
            "PAPER_EXCHANGE_PERSIST_SYNC_STATE_RESULTS": "false",
        }
        updated = _upsert_env_text(original, updates)
        if updated != original and not dry_run:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            env_backup_path = str(reports_dir / f"paper_exchange_canary_env_backup_{stamp}.env")
            Path(env_backup_path).write_text(original, encoding="utf-8")
            env_path.write_text(updated, encoding="utf-8")
        steps.append(
            {
                "name": "env_patch",
                "pass": True,
                "reason": "env updated for canary mode" if not dry_run else "dry-run: env update planned",
                "backup_path": env_backup_path,
                "updated_keys": sorted(updates.keys()),
            }
        )
    else:
        steps.append(
            {
                "name": "env_patch",
                "pass": True,
                "reason": "env patch skipped by flag",
                "backup_path": "",
                "updated_keys": [],
            }
        )

    start_cmd = _build_compose_start_cmd(env_path, compose_path)
    if dry_run:
        start_rc, start_msg = 0, "(dry-run) " + " ".join(start_cmd)
    else:
        start_rc, start_msg = _run_command(start_cmd, cwd=root, timeout_sec=300, pythonpath_root=root)
    steps.append(
        {
            "name": "compose_start_paper_exchange",
            "pass": start_rc == 0,
            "rc": start_rc,
            "command": start_cmd,
            "output": start_msg[:4000],
        }
    )
    if start_rc != 0:
        rc_final = 2

    bot_cmd = _build_bot_recreate_cmd(env_path, compose_path, bot)
    if dry_run:
        bot_rc, bot_msg = 0, "(dry-run) " + " ".join(bot_cmd)
    else:
        bot_rc, bot_msg = _run_command(bot_cmd, cwd=root, timeout_sec=300, pythonpath_root=root)
    steps.append(
        {
            "name": "recreate_bot",
            "pass": bot_rc == 0,
            "rc": bot_rc,
            "command": bot_cmd,
            "output": bot_msg[:4000],
        }
    )
    if bot_rc != 0:
        rc_final = 2

    env_map = _read_env_map(env_path)
    command_stream = str(env_map.get("PAPER_EXCHANGE_COMMAND_STREAM", "hb.paper_exchange.command.v1"))
    event_stream = str(env_map.get("PAPER_EXCHANGE_EVENT_STREAM", "hb.paper_exchange.event.v1"))
    heartbeat_stream = str(env_map.get("PAPER_EXCHANGE_HEARTBEAT_STREAM", "hb.paper_exchange.heartbeat.v1"))
    consumer_group = str(env_map.get("PAPER_EXCHANGE_CONSUMER_GROUP", "hb_group_paper_exchange"))
    consumer_name = str(env_map.get("PAPER_EXCHANGE_CONSUMER_NAME", "paper_exchange_1"))

    if run_gates:
        preflight_cmd = [sys.executable, str(root / "scripts" / "ops" / "preflight_paper_exchange.py"), "--strict"]
        if dry_run:
            preflight_rc, preflight_msg = 0, "(dry-run) " + " ".join(preflight_cmd)
        else:
            preflight_rc, preflight_msg = _run_command(
                preflight_cmd,
                cwd=root,
                timeout_sec=120,
                pythonpath_root=root,
            )
        steps.append(
            {
                "name": "paper_exchange_preflight",
                "pass": preflight_rc == 0,
                "rc": preflight_rc,
                "command": preflight_cmd,
                "output": preflight_msg[:4000],
            }
        )
        if preflight_rc != 0:
            rc_final = 2

        harness_cmd = [
            sys.executable,
            str(root / "scripts" / "release" / "run_paper_exchange_load_harness.py"),
            "--strict",
            "--duration-sec",
            str(max(0.1, float(load_harness_duration_sec))),
            "--target-cmd-rate",
            str(max(1.0, float(load_harness_target_cmd_rate))),
            "--min-commands",
            str(max(1, int(load_harness_min_commands))),
            "--command-stream",
            command_stream,
            "--event-stream",
            event_stream,
            "--heartbeat-stream",
            heartbeat_stream,
        ]
        if dry_run:
            harness_rc, harness_msg = 0, "(dry-run) " + " ".join(harness_cmd)
        else:
            harness_rc, harness_msg = _run_command(
                harness_cmd,
                cwd=root,
                timeout_sec=300,
                pythonpath_root=root,
            )
        steps.append(
            {
                "name": "paper_exchange_load_harness",
                "pass": harness_rc == 0,
                "rc": harness_rc,
                "command": harness_cmd,
                "output": harness_msg[:4000],
            }
        )
        if harness_rc != 0:
            rc_final = 2

        run_id = "" if dry_run else _latest_harness_run_id(root)
        load_cmd = [
            sys.executable,
            str(root / "scripts" / "release" / "check_paper_exchange_load.py"),
            "--strict",
            "--lookback-sec",
            str(max(1, int(load_check_lookback_sec))),
            "--min-window-sec",
            str(max(1, int(load_check_min_window_sec))),
            "--command-stream",
            command_stream,
            "--event-stream",
            event_stream,
            "--heartbeat-stream",
            heartbeat_stream,
            "--consumer-group",
            consumer_group,
            "--heartbeat-consumer-group",
            consumer_group,
            "--heartbeat-consumer-name",
            consumer_name,
        ]
        if run_id:
            load_cmd.extend(["--load-run-id", run_id])
        if dry_run:
            load_rc, load_msg = 0, "(dry-run) " + " ".join(load_cmd)
        else:
            load_rc, load_msg = _run_command(
                load_cmd,
                cwd=root,
                timeout_sec=180,
                pythonpath_root=root,
            )
        steps.append(
            {
                "name": "paper_exchange_load_check",
                "pass": load_rc == 0,
                "rc": load_rc,
                "run_id": run_id,
                "command": load_cmd,
                "output": load_msg[:4000],
            }
        )
        if load_rc != 0:
            rc_final = 2

    status = "pass" if rc_final == 0 else "fail"
    report = {
        "ts_utc": _utc_now(),
        "status": status,
        "bot": bot,
        "mode": mode,
        "apply_env": bool(apply_env),
        "run_gates": bool(run_gates),
        "dry_run": bool(dry_run),
        "env_path": str(env_path),
        "compose_path": str(compose_path),
        "env_backup_path": env_backup_path,
        "streams": {
            "command_stream": command_stream,
            "event_stream": event_stream,
            "heartbeat_stream": heartbeat_stream,
            "consumer_group": consumer_group,
            "consumer_name": consumer_name,
        },
        "steps": steps,
    }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = reports_dir / f"paper_exchange_canary_{stamp}.json"
    latest_path = reports_dir / "paper_exchange_canary_latest.json"
    payload = json.dumps(report, indent=2)
    out_path.write_text(payload, encoding="utf-8")
    latest_path.write_text(payload, encoding="utf-8")

    print(f"[paper-exchange-canary] status={status} bot={bot} mode={mode}")
    print(f"[paper-exchange-canary] evidence={latest_path}")
    return 0 if status == "pass" else 2


def main() -> int:
    parser = argparse.ArgumentParser(description="One-command paper-exchange canary launcher for bot rollout.")
    parser.add_argument(
        "--bot",
        default="bot3",
        choices=["bot1", "bot2", "bot3", "bot4"],
        help="Bot container to canary/recreate.",
    )
    parser.add_argument(
        "--mode",
        default="shadow",
        choices=["disabled", "shadow", "active"],
        help="Paper exchange mode applied for the selected bot.",
    )
    parser.add_argument(
        "--apply-env",
        action="store_true",
        default=True,
        help="Patch env/.env mode + minimal paper-exchange keys before compose actions (default: true).",
    )
    parser.add_argument(
        "--no-apply-env",
        action="store_false",
        dest="apply_env",
        help="Do not modify env/.env; use current env file values.",
    )
    parser.add_argument(
        "--run-gates",
        action="store_true",
        default=True,
        help="Run paper-exchange preflight + load harness/check after restart (default: true).",
    )
    parser.add_argument(
        "--no-run-gates",
        action="store_false",
        dest="run_gates",
        help="Skip canary gate checks.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned env/compose/gate actions without modifying files or running commands.",
    )
    parser.add_argument(
        "--load-harness-duration-sec",
        type=float,
        default=20.0,
        help="Synthetic load harness duration used during canary validation.",
    )
    parser.add_argument(
        "--load-harness-target-cmd-rate",
        type=float,
        default=60.0,
        help="Synthetic load harness command rate.",
    )
    parser.add_argument(
        "--load-harness-min-commands",
        type=int,
        default=300,
        help="Minimum commands required by canary load harness strict pass.",
    )
    parser.add_argument(
        "--load-check-lookback-sec",
        type=int,
        default=600,
        help="Load checker lookback window in seconds.",
    )
    parser.add_argument(
        "--load-check-min-window-sec",
        type=int,
        default=10,
        help="Minimum command window enforced by canary load checker.",
    )
    args = parser.parse_args()

    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    return run_canary(
        root=root,
        bot=str(args.bot).strip().lower(),
        mode=str(args.mode).strip().lower(),
        apply_env=bool(args.apply_env),
        run_gates=bool(args.run_gates),
        dry_run=bool(args.dry_run),
        load_harness_duration_sec=float(args.load_harness_duration_sec),
        load_harness_target_cmd_rate=float(args.load_harness_target_cmd_rate),
        load_harness_min_commands=int(args.load_harness_min_commands),
        load_check_lookback_sec=int(args.load_check_lookback_sec),
        load_check_min_window_sec=int(args.load_check_min_window_sec),
    )


if __name__ == "__main__":
    raise SystemExit(main())
