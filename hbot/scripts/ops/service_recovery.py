#!/usr/bin/env python3
"""Service dependency recovery — restart Redis/risk-service when unhealthy.

Checks:
  - Redis: ping fails -> restart redis
  - risk-service: report stale > threshold -> restart risk-service

Usage:
  python scripts/ops/service_recovery.py
  python scripts/ops/service_recovery.py --dry-run

Env:
  REDIS_HOST, REDIS_PORT, REDIS_PASSWORD
  SERVICE_RECOVERY_RISK_STALE_MIN  - max report age in minutes (default 10)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC
from pathlib import Path

try:
    import redis
except ImportError:
    redis = None


def _redis_ping() -> bool:
    if redis is None:
        return False
    try:
        host = os.getenv("REDIS_HOST", "redis")
        port = int(os.getenv("REDIS_PORT", "6379"))
        pwd = os.getenv("REDIS_PASSWORD") or None
        c = redis.Redis(host=host, port=port, password=pwd, socket_timeout=3)
        return bool(c.ping())
    except Exception:
        return False


def _risk_report_fresh(root: Path, max_age_min: float) -> bool:
    path = root / "reports" / "risk_service" / "latest.json"
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        ts = data.get("ts_utc", "")
        if not ts:
            return False
        from datetime import datetime
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        age_min = (datetime.now(UTC) - dt).total_seconds() / 60.0
        return age_min <= max_age_min
    except Exception:
        return False


def _docker_restart(container: str) -> bool:
    try:
        r = subprocess.run(
            ["docker", "restart", container],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return r.returncode == 0
    except Exception:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Restart unhealthy Redis/risk-service containers")
    parser.add_argument("--dry-run", action="store_true", help="Only report, do not restart")
    parser.add_argument("--risk-stale-min", type=float, default=10, help="Max risk report age in minutes")
    args = parser.parse_args()

    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    rc = 0

    # Redis
    if not _redis_ping():
        print("[service-recovery] Redis unreachable")
        if not args.dry_run:
            if _docker_restart("redis"):
                print("[service-recovery] Restarted redis")
                time.sleep(5)
                if _redis_ping():
                    print("[service-recovery] Redis recovered")
                else:
                    rc = 2
            else:
                print("[service-recovery] Failed to restart redis")
                rc = 2
        else:
            print("[service-recovery] (dry-run) would restart redis")
    else:
        print("[service-recovery] Redis OK")

    # risk-service (only when EXT_SIGNAL_RISK_ENABLED)
    if os.getenv("EXT_SIGNAL_RISK_ENABLED", "").lower() in ("true", "1"):
        if not _risk_report_fresh(root, args.risk_stale_min):
            print(f"[service-recovery] risk-service report stale >{args.risk_stale_min}min")
            if not args.dry_run:
                if _docker_restart("risk-service"):
                    print("[service-recovery] Restarted risk-service")
                else:
                    print("[service-recovery] Failed to restart risk-service")
                    rc = 2
            else:
                print("[service-recovery] (dry-run) would restart risk-service")
    else:
        print("[service-recovery] risk-service check skipped (EXT_SIGNAL_RISK_ENABLED=false)")

    return rc


if __name__ == "__main__":
    sys.exit(main())
