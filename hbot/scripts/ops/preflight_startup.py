#!/usr/bin/env python3
"""Pre-flight startup checks before declaring bot healthy.

Verifies:
  - Bot startup password path is valid in container (prevents login hang)
  - Redis reachable (optional, when REDIS_HOST set)
  - Telegram API reachable (optional, when TELEGRAM_BOT_TOKEN set)
  - Exchange API reachable (optional, when exchange keys configured)

Usage:
  python scripts/ops/preflight_startup.py
  python scripts/ops/preflight_startup.py --require-redis --require-telegram

Exit: 0 if all required checks pass, 2 otherwise.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _check_env_file(root: Path) -> tuple[bool, str]:
    env_path = root / "infra" / "env" / ".env"
    if not env_path.exists():
        return False, "infra/env/.env not found"
    # Check BOT1_PASSWORD in env file (not .env.template)
    try:
        content = env_path.read_text(encoding="utf-8")
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("BOT1_PASSWORD=") and "=" in line:
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                if val and val != "your_password_here":
                    return True, "BOT1_PASSWORD set in env"
                return False, "BOT1_PASSWORD empty or placeholder"
    except Exception as e:
        return False, str(e)
    return False, "BOT1_PASSWORD not found in env"


def _container_cmd_text(container: str) -> str:
    """Best-effort read of configured container command."""
    try:
        out = subprocess.run(
            ["docker", "inspect", "--format", "{{json .Config.Cmd}}", container],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if out.returncode != 0:
            return ""
        return out.stdout.strip().lower()
    except Exception:
        return ""


def _password_env_keys_for_container(container: str) -> list[str]:
    name = container.strip().lower()
    if name.endswith("bot1"):
        return ["BOT1_PASSWORD"]
    if name.endswith("bot2"):
        return ["BOT2_PASSWORD", "BOT1_PASSWORD"]
    if name.endswith("bot3"):
        return ["BOT3_PASSWORD", "BOT1_PASSWORD"]
    if name.endswith("bot4"):
        return ["BOT4_PASSWORD", "BOT1_PASSWORD"]
    return ["BOT1_PASSWORD"]


def _check_bot_container_password(container: str = "bot1") -> tuple[bool, str]:
    """Check startup password path in running bot container.

    Accepted patterns:
      1) CONFIG_PASSWORD non-empty in container env
      2) BOTx_PASSWORD/BOT1_PASSWORD non-empty + startup command injects
         CONFIG_PASSWORD at runtime (export guard in startup command)

    Returns (True, 'ok') when container not running (can't verify, pass).
    """
    try:
        out = subprocess.run(
            ["docker", "exec", container, "env"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if out.returncode != 0:
            # Container not running — can't verify, treat as pass (skip)
            return True, f"container {container} not running (skip)"
        env_map: dict[str, str] = {}
        for line in out.stdout.splitlines():
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            env_map[k.strip()] = v.strip()

        cfg_pwd = env_map.get("CONFIG_PASSWORD", "")
        if cfg_pwd:
            return True, "CONFIG_PASSWORD set in container"

        candidate_keys = _password_env_keys_for_container(container)
        resolved_key = next((k for k in candidate_keys if env_map.get(k, "").strip()), None)
        if resolved_key:
            cmd_text = _container_cmd_text(container)
            has_runtime_guard = (
                "config_password" in cmd_text
                and "export" in cmd_text
                and any(k.lower() in cmd_text for k in candidate_keys)
            )
            if has_runtime_guard:
                return True, f"{resolved_key} set in container with runtime CONFIG_PASSWORD export guard"
            return False, f"{resolved_key} set but startup command lacks runtime CONFIG_PASSWORD export guard"

        if "CONFIG_PASSWORD" in env_map:
            return False, "CONFIG_PASSWORD empty in container (will hang at login)"
        return False, f"CONFIG_PASSWORD and {','.join(candidate_keys)} missing in container env"
    except FileNotFoundError:
        return False, "docker not in PATH"
    except subprocess.TimeoutExpired:
        return False, "docker exec timeout"
    except Exception as e:
        return False, str(e)


def _check_redis(host: str, port: int, password: str | None) -> tuple[bool, str]:
    try:
        import redis
        c = redis.Redis(host=host, port=port, password=password or None, socket_timeout=3)
        c.ping()
        return True, "Redis reachable"
    except ImportError:
        return False, "redis package not installed"
    except Exception as e:
        return False, str(e)


def _check_telegram(token: str, chat_id: str) -> tuple[bool, str]:
    if not token or not chat_id:
        return False, "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set"
    try:
        payload = json.dumps({"chat_id": chat_id, "text": "Pre-flight health check OK"}).encode()
        req = Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=8) as resp:
            if resp.status < 300:
                return True, "Telegram API OK"
            return False, f"Telegram HTTP {resp.status}"
    except HTTPError as e:
        if e.code == 403:
            return False, "Telegram 403 Forbidden (token revoked?)"
        return False, str(e)
    except URLError as e:
        return False, str(e.reason)
    except Exception as e:
        return False, str(e)


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _check_recon_exchange_ready(root: Path) -> tuple[bool, str, dict]:
    env_path = root / "infra" / "env" / ".env"
    recon_path = root / "reports" / "reconciliation" / "latest.json"
    snapshot_path = root / "reports" / "exchange_snapshots" / "latest.json"

    env_vals = {
        "BITGET_API_KEY": "",
        "BITGET_SECRET": "",
        "BITGET_PASSPHRASE": "",
        "BOT1_BITGET_API_KEY": "",
        "BOT1_BITGET_API_SECRET": "",
        "BOT1_BITGET_PASSPHRASE": "",
        "RECON_EXCHANGE_SOURCE_ENABLED": "",
    }
    if env_path.exists():
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                row = line.strip()
                if not row or row.startswith("#") or "=" not in row:
                    continue
                k, v = row.split("=", 1)
                key = k.strip()
                if key in env_vals:
                    env_vals[key] = v.strip().strip('"').strip("'")
        except Exception:
            pass

    has_global_keys = all(bool(env_vals[k]) for k in ("BITGET_API_KEY", "BITGET_SECRET", "BITGET_PASSPHRASE"))
    has_bot1_keys = all(bool(env_vals[k]) for k in ("BOT1_BITGET_API_KEY", "BOT1_BITGET_API_SECRET", "BOT1_BITGET_PASSPHRASE"))
    has_keys = bool(has_global_keys or has_bot1_keys)
    recon_raw = str(env_vals["RECON_EXCHANGE_SOURCE_ENABLED"]).strip().lower()
    recon_enabled_env = (recon_raw == "") or (recon_raw in {"1", "true", "yes"})

    recon = _read_json(recon_path)
    snapshot = _read_json(snapshot_path)
    recon_enabled_report = bool(recon.get("exchange_source_enabled", False))
    account_probe = snapshot.get("account_probe", {}) if isinstance(snapshot.get("account_probe"), dict) else {}
    account_probe_status = str(account_probe.get("status", "missing"))
    snapshot_ok = account_probe_status == "ok"

    report = {
        "env_path": str(env_path),
        "reconciliation_report_path": str(recon_path),
        "exchange_snapshot_report_path": str(snapshot_path),
        "env_has_required_bitget_keys": has_keys,
        "recon_exchange_source_enabled_env": recon_enabled_env,
        "recon_exchange_source_enabled_report": recon_enabled_report,
        "exchange_snapshot_account_probe_status": account_probe_status,
        "exchange_snapshot_probe_ok": snapshot_ok,
        "ready": bool(has_keys and recon_enabled_env and recon_enabled_report and snapshot_ok),
    }
    if report["ready"]:
        return True, "Reconciliation exchange-source readiness PASS", report

    reasons = []
    if not has_keys:
        reasons.append("missing_bitget_keys_in_env")
    if not recon_enabled_env:
        reasons.append("recon_exchange_source_env_disabled")
    if not recon_enabled_report:
        reasons.append("reconciliation_report_exchange_source_disabled")
    if not snapshot_ok:
        reasons.append(f"exchange_snapshot_account_probe_status={account_probe_status}")
    return False, ",".join(reasons), report


def main() -> int:
    parser = argparse.ArgumentParser(description="Pre-flight startup checks")
    parser.add_argument("--require-redis", action="store_true", help="Fail if Redis unreachable")
    parser.add_argument("--require-telegram", action="store_true", help="Fail if Telegram unreachable")
    parser.add_argument("--require-bot-container", action="store_true", help="Fail if bot container CONFIG_PASSWORD empty")
    parser.add_argument(
        "--require-recon-exchange",
        action="store_true",
        help="Fail unless reconciliation uses real exchange source (keys + reports).",
    )
    parser.add_argument(
        "--recon-report-path",
        default="",
        help="Optional explicit path for recon preflight report JSON output.",
    )
    parser.add_argument(
        "--bot-containers",
        default=os.getenv("PREFLIGHT_BOT_CONTAINERS", "bot1,bot3,bot4"),
        help="Comma-separated container names to validate startup password path.",
    )
    parser.add_argument("--skip-container", action="store_true", help="Skip container check (e.g. before first up)")
    args = parser.parse_args()

    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    checks: list[tuple[str, bool, str]] = []
    rc = 0

    # 1) Env file + BOT1_PASSWORD
    ok, msg = _check_env_file(root)
    checks.append(("env_file", ok, msg))
    if not ok:
        rc = 2

    # 2) Bot container CONFIG_PASSWORD (when container running)
    if not args.skip_container:
        containers = [c.strip() for c in str(args.bot_containers).split(",") if c.strip()]
        for container in containers:
            ok, msg = _check_bot_container_password(container=container)
            checks.append((f"bot_container_password[{container}]", ok, msg))
            if not ok:
                rc = 2  # startup password path invalid when container is running

    # 3) Redis (optional)
    if args.require_redis or os.getenv("REDIS_HOST"):
        host = os.getenv("REDIS_HOST", "redis")
        port = int(os.getenv("REDIS_PORT", "6379"))
        pwd = os.getenv("REDIS_PASSWORD", "")
        ok, msg = _check_redis(host, port, pwd)
        checks.append(("redis", ok, msg))
        if not ok and args.require_redis:
            rc = 2

    # 4) Telegram (optional)
    if args.require_telegram or (os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID")):
        ok, msg = _check_telegram(
            os.getenv("TELEGRAM_BOT_TOKEN", ""),
            os.getenv("TELEGRAM_CHAT_ID", ""),
        )
        checks.append(("telegram", ok, msg))
        if not ok and args.require_telegram:
            rc = 2

    # 5) Reconciliation exchange-source readiness (optional strict check)
    if args.require_recon_exchange:
        ok, msg, report = _check_recon_exchange_ready(root)
        checks.append(("recon_exchange_source", ok, msg))
        report_path = (
            Path(args.recon_report_path)
            if args.recon_report_path
            else root / "reports" / "ops" / "preflight_recon_latest.json"
        )
        try:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        except Exception as e:
            checks.append(("recon_exchange_report_write", False, str(e)))
            ok = False
        if not ok:
            rc = 2

    for name, ok, msg in checks:
        status = "PASS" if ok else "FAIL"
        print(f"[preflight] {name}: {status} — {msg}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
