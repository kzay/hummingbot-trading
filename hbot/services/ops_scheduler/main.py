"""Unified ops-scheduler: consolidates 6 periodic containers into one process.

Replaces:
  - event-store-monitor   (900s)
  - day2-gate-monitor     (300s)
  - soak-monitor          (300s)
  - daily-ops-reporter    (900s)
  - artifact-retention    (86400s)
  - exchange-snapshot-service (120s)

Each job runs in its own thread via subprocess for fault isolation.
A crash in one job does not affect others.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("ops-scheduler")

WORKSPACE = Path(os.getenv("OPS_SCHEDULER_WORKSPACE", "/workspace/hbot"))
HEARTBEAT_PATH = Path(os.getenv("OPS_SCHEDULER_HEARTBEAT", "/tmp/ops_scheduler_heartbeat.json"))
HEALTH_MAX_SEC = int(os.getenv("OPS_SCHEDULER_HEALTH_MAX_SEC", "1200"))

JOBS: list[dict] = [
    {
        "name": "event-store-snapshot",
        "command": [
            sys.executable,
            str(WORKSPACE / "scripts/utils/event_store_periodic_snapshot.py"),
            "--max-runs", "1",
        ],
        "interval_env": "EVENT_STORE_MONITOR_INTERVAL_SEC",
        "interval_default": 900,
    },
    {
        "name": "day2-gate-eval",
        "command": [
            sys.executable, "-c",
            "from scripts.utils.day2_gate_monitor import run_once; from pathlib import Path; run_once(Path('.'))",
        ],
        "interval_env": "DAY2_GATE_INTERVAL_SEC",
        "interval_default": 300,
    },
    {
        "name": "soak-snapshot",
        "command": [
            sys.executable,
            str(WORKSPACE / "scripts/release/soak_monitor.py"),
            "--once",
        ],
        "interval_env": "SOAK_MONITOR_INTERVAL_SEC",
        "interval_default": 300,
    },
    {
        "name": "daily-ops-report",
        "command": [
            sys.executable,
            str(WORKSPACE / "scripts/release/watch_daily_ops_report.py"),
            "--max-runs", "1",
        ],
        "interval_env": "DAILY_OPS_REPORT_INTERVAL_SEC",
        "interval_default": 900,
    },
    {
        "name": "artifact-retention",
        "command": [
            sys.executable,
            str(WORKSPACE / "scripts/release/run_artifact_retention.py"),
            "--apply",
        ],
        "interval_env": "ARTIFACT_RETENTION_INTERVAL_SEC",
        "interval_default": 86400,
    },
    {
        "name": "exchange-snapshot",
        "command": [
            sys.executable, "-c",
            "from services.exchange_snapshot_service.main import _snapshot_once; _snapshot_once()",
        ],
        "interval_env": "EXCHANGE_SNAPSHOT_INTERVAL_SEC",
        "interval_default": 120,
    },
    {
        "name": "data-refresh",
        "command": [
            sys.executable,
            str(WORKSPACE / "scripts/ops/data_refresh.py"),
        ],
        "interval_env": "DATA_REFRESH_INTERVAL_SEC",
        "interval_default": 21600,
    },
]


def _get_interval(job: dict) -> int:
    raw = os.getenv(job["interval_env"], "")
    return max(30, int(raw)) if raw.isdigit() else max(30, job["interval_default"])


_heartbeat_lock = threading.Lock()
_last_heartbeat_write: float = 0.0
_HEARTBEAT_MIN_INTERVAL_S = 30


def _write_heartbeat(status: dict, *, force: bool = False) -> None:
    global _last_heartbeat_write
    now = time.monotonic()
    if not force and (now - _last_heartbeat_write) < _HEARTBEAT_MIN_INTERVAL_S:
        return
    with _heartbeat_lock:
        if not force and (now - _last_heartbeat_write) < _HEARTBEAT_MIN_INTERVAL_S:
            return
        try:
            HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
            HEARTBEAT_PATH.write_text(json.dumps(status, indent=2))
            _last_heartbeat_write = time.monotonic()
        except Exception:
            pass  # Justification: heartbeat write is best-effort — scheduler must not crash on I/O failure


def _job_loop(job: dict, status: dict) -> None:
    """Run a single job repeatedly on its configured interval."""
    name = job["name"]
    interval = _get_interval(job)
    cmd = list(job["command"])
    logger.info("job=%s interval=%ds starting", name, interval)

    while True:
        t0 = time.monotonic()
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=max(interval * 2, 300),
                cwd=str(WORKSPACE),
                env={**os.environ, "PYTHONPATH": str(WORKSPACE), "PYTHONPYCACHEPREFIX": "/tmp/pycache"},
            )
            elapsed = time.monotonic() - t0
            status[name] = {
                "last_run": datetime.now(UTC).isoformat(),
                "exit_code": result.returncode,
                "elapsed_s": round(elapsed, 1),
            }
            if result.returncode != 0:
                logger.warning(
                    "job=%s exit_code=%d elapsed=%.1fs stderr=%s",
                    name, result.returncode, elapsed,
                    (result.stderr or "")[:500],
                )
            else:
                logger.info("job=%s ok elapsed=%.1fs", name, elapsed)
        except subprocess.TimeoutExpired:
            logger.error("job=%s timed out after %ds", name, interval * 2)
            status[name] = {
                "last_run": datetime.now(UTC).isoformat(),
                "exit_code": -1,
                "error": "timeout",
            }
        except Exception as exc:
            logger.error("job=%s error: %s", name, exc)
            status[name] = {
                "last_run": datetime.now(UTC).isoformat(),
                "exit_code": -1,
                "error": str(exc)[:200],
            }

        _write_heartbeat(status)
        time.sleep(interval)


def main() -> None:
    logger.info("ops-scheduler starting with %d jobs", len(JOBS))

    status: dict = {"started": datetime.now(UTC).isoformat()}
    threads: list[threading.Thread] = []

    for job in JOBS:
        t = threading.Thread(target=_job_loop, args=(job, status), daemon=True, name=job["name"])
        t.start()
        threads.append(t)
        time.sleep(2)

    _write_heartbeat(status)

    while True:
        alive = sum(1 for t in threads if t.is_alive())
        status["alive_threads"] = alive
        status["total_threads"] = len(threads)
        status["heartbeat"] = datetime.now(UTC).isoformat()
        _write_heartbeat(status)

        if alive == 0:
            logger.error("all job threads dead, exiting")
            sys.exit(1)

        time.sleep(60)


if __name__ == "__main__":
    main()
