"""Backtest control API — hosted as a Starlette sub-application.

Provides endpoints to run backtests from the dashboard:
  GET  /api/backtest/presets      — list available presets
  POST /api/backtest/jobs         — start a new backtest job
  GET  /api/backtest/jobs         — list all jobs
  GET  /api/backtest/jobs/{id}    — job status + result summary
  GET  /api/backtest/jobs/{id}/log — SSE log stream
  POST /api/backtest/jobs/{id}/cancel — cancel a running job

Decision: hosted inside the existing realtime-ui-api process (design D1).
"""
from __future__ import annotations

import asyncio
import atexit
import json
import logging
import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_PRESETS_DIR = Path(os.environ.get("BACKTEST_PRESETS_DIR", "data/backtest_configs"))
_REPORTS_DIR = Path(os.environ.get("BACKTEST_REPORTS_DIR", "reports/backtest/jobs"))
_DB_PATH = Path(os.environ.get("BACKTEST_DB_PATH", "data/backtest_jobs.sqlite3"))
_MAX_CONCURRENT_JOBS = int(os.environ.get("BACKTEST_MAX_CONCURRENT", "2"))
_MAX_WALL_TIME_S = int(os.environ.get("BACKTEST_MAX_WALL_TIME_S", "3600"))

_SAFE_OVERRIDE_KEYS = frozenset({
    "initial_equity", "start_date", "end_date",
})
_EQUITY_MIN = 50.0
_EQUITY_MAX = 100_000.0
_MAX_DATE_RANGE_DAYS = 365

# Backtest harness subprocesses (reap on waiter thread crash + process exit).
_backtest_procs: list[subprocess.Popen[Any]] = []
_backtest_procs_lock = threading.Lock()


def _track_backtest_proc(proc: subprocess.Popen[Any]) -> None:
    with _backtest_procs_lock:
        _backtest_procs.append(proc)


def _untrack_backtest_proc(proc: subprocess.Popen[Any]) -> None:
    with _backtest_procs_lock:
        try:
            _backtest_procs.remove(proc)
        except ValueError:
            pass


def shutdown_backtest_subprocesses() -> None:
    """Kill and reap any still-running backtest harness children.

    Called on process exit (atexit) and from ``realtime_ui_api`` shutdown so PIDs
    are not left behind when the waiter thread dies or the server stops.
    """
    with _backtest_procs_lock:
        snap = list(_backtest_procs)
    for proc in snap:
        try:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=30)
        except Exception:
            logger.debug("backtest proc cleanup failed", exc_info=True)
    with _backtest_procs_lock:
        _backtest_procs.clear()


atexit.register(shutdown_backtest_subprocesses)

# ---------------------------------------------------------------------------
# SQLite store
# ---------------------------------------------------------------------------

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    preset_id TEXT NOT NULL,
    overrides_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    progress_pct REAL NOT NULL DEFAULT 0.0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    result_summary_json TEXT,
    error TEXT,
    log_path TEXT,
    report_path TEXT,
    pid INTEGER
)
"""


class JobStore:
    """Thread-safe SQLite wrapper for backtest job metadata."""

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = str(db_path)
        self._lock = threading.Lock()
        self._ensure_table()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_table(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(_CREATE_TABLE)
                conn.commit()
            finally:
                conn.close()

    def insert(self, job: dict[str, Any]) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT INTO jobs (id, preset_id, overrides_json, status, progress_pct, "
                    "created_at, updated_at, log_path, report_path, pid) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        job["id"], job["preset_id"], json.dumps(job.get("overrides", {})),
                        job["status"], job.get("progress_pct", 0.0),
                        job["created_at"], job["updated_at"],
                        job.get("log_path", ""), job.get("report_path", ""),
                        job.get("pid"),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
                return dict(row) if row else None
            finally:
                conn.close()

    def list_all(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def update(self, job_id: str, **fields: Any) -> None:
        if not fields:
            return
        fields["updated_at"] = _now_iso()
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        vals = list(fields.values()) + [job_id]
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(f"UPDATE jobs SET {set_clause} WHERE id = ?", vals)
                conn.commit()
            finally:
                conn.close()

    def running_count(self) -> int:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT COUNT(*) FROM jobs WHERE status = 'running'"
                ).fetchone()
                return row[0] if row else 0
            finally:
                conn.close()

    def running_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT * FROM jobs WHERE status = 'running'"
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _pid_alive(pid: int) -> bool:
    if not pid:
        return False
    try:
        if sys.platform == "win32":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x0400, False, pid)  # PROCESS_QUERY_INFORMATION
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        else:
            os.kill(pid, 0)
            return True
    except (OSError, ProcessLookupError):
        return False


def _load_presets() -> dict[str, dict[str, Any]]:
    """Scan preset YAML files and return a map of preset_id → metadata."""
    presets: dict[str, dict[str, Any]] = {}
    preset_dir = _PRESETS_DIR
    if not preset_dir.exists():
        return presets
    try:
        import yaml
    except ImportError:
        logger.warning("PyYAML not available — cannot load backtest presets")
        return presets
    for yml_file in sorted(preset_dir.glob("*.yml")):
        try:
            with open(yml_file) as f:
                data = yaml.safe_load(f) or {}
            preset_id = yml_file.stem
            mode = str(data.get("mode", "adapter"))
            ds = data.get("data_source", {}) or data.get("data", {})
            start_date = str(ds.get("start_date", "") or data.get("start_date", ""))
            end_date = str(ds.get("end_date", "") or data.get("end_date", ""))
            presets[preset_id] = {
                "id": preset_id,
                "label": data.get("label", preset_id.replace("_", " ").title()),
                "strategy": data.get("strategy_class", ""),
                "pair": ds.get("pair", ""),
                "resolution": ds.get("resolution", ds.get("candles_resolution", "")),
                "initial_equity": float(data.get("initial_equity", 500)),
                "start_date": start_date,
                "end_date": end_date,
                "file": str(yml_file),
                "mode": mode,
            }
        except Exception as exc:
            logger.warning("Failed to parse preset %s: %s", yml_file, exc)
    return presets


def _validate_overrides(overrides: dict[str, Any]) -> str | None:
    """Return error string if overrides are invalid, else None."""
    for key in overrides:
        if key not in _SAFE_OVERRIDE_KEYS:
            return f"Override key '{key}' is not allowed. Allowed: {sorted(_SAFE_OVERRIDE_KEYS)}"

    if "initial_equity" in overrides:
        try:
            eq = float(overrides["initial_equity"])
        except (TypeError, ValueError):
            return "initial_equity must be a number"
        if not (_EQUITY_MIN <= eq <= _EQUITY_MAX):
            return f"initial_equity must be between {_EQUITY_MIN} and {_EQUITY_MAX}"

    if "start_date" in overrides and "end_date" in overrides:
        try:
            sd = datetime.strptime(overrides["start_date"], "%Y-%m-%d")
            ed = datetime.strptime(overrides["end_date"], "%Y-%m-%d")
        except ValueError:
            return "Dates must be YYYY-MM-DD format"
        if (ed - sd).days > _MAX_DATE_RANGE_DAYS:
            return f"Date range must not exceed {_MAX_DATE_RANGE_DAYS} days"
        if ed <= sd:
            return "end_date must be after start_date"

    return None


# ---------------------------------------------------------------------------
# Worker subprocess management
# ---------------------------------------------------------------------------

def _detect_preset_mode(preset_file: str) -> str:
    """Read the YAML preset to determine if it is a replay config."""
    try:
        import yaml
        with open(preset_file) as f:
            data = yaml.safe_load(f) or {}
        return str(data.get("mode", "adapter"))
    except Exception:
        return "adapter"


def _spawn_worker(
    store: JobStore,
    job_id: str,
    preset_file: str,
    overrides: dict[str, Any],
) -> int:
    """Spawn the backtest in a subprocess, return PID."""
    job_dir = _REPORTS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    log_path = job_dir / "run.log"
    report_path = job_dir / "report.json"

    mode = _detect_preset_mode(preset_file)
    if mode == "replay":
        module = "controllers.backtesting.replay_harness"
        cmd = [
            sys.executable, "-m", module,
            "--config", preset_file,
            "--output", str(report_path),
            "--progress-dir", str(job_dir),
            "--progress-every", "10",
        ]
    else:
        module = "controllers.backtesting.harness_cli"
        cmd = [
            sys.executable, "-m", module,
            "--config", preset_file,
            "--output", str(report_path),
            "--progress-dir", str(job_dir),
        ]
        for key, val in overrides.items():
            cmd.extend(["--override", f"{key}={val}"])

    log_fh = open(log_path, "w", buffering=1)
    env = {**os.environ, "PYTHONPATH": os.environ.get("PYTHONPATH", "hbot")}

    proc = subprocess.Popen(
        cmd,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        env=env,
        start_new_session=True,
    )
    _track_backtest_proc(proc)

    store.update(
        job_id,
        status="running",
        pid=proc.pid,
        log_path=str(log_path),
        report_path=str(report_path),
    )

    def _wait_for_completion() -> None:
        """Always reap ``proc`` and close ``log_fh`` so we do not leak PIDs / POSIX zombies."""
        try:
            try:
                proc.wait(timeout=_MAX_WALL_TIME_S)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=60)
                except subprocess.TimeoutExpired:
                    logger.warning("backtest job %s: kill did not reap within 60s (pid=%s)", job_id, proc.pid)
                try:
                    store.update(job_id, status="timed_out", error="Exceeded wall-time limit")
                except Exception:
                    logger.exception("store.update after timeout failed job_id=%s", job_id)
                return

            if proc.returncode == 0:
                result_summary = None
                if report_path.exists():
                    try:
                        result_summary = json.loads(report_path.read_text())
                    except Exception:
                        pass
                try:
                    store.update(
                        job_id,
                        status="completed",
                        progress_pct=100.0,
                        result_summary_json=json.dumps(result_summary) if result_summary else None,
                    )
                except Exception:
                    logger.exception("store.update completed failed job_id=%s", job_id)
            else:
                error_msg = f"Process exited with code {proc.returncode}"
                if log_path.exists():
                    try:
                        tail = log_path.read_text()[-500:]
                        error_msg += f"\n{tail}"
                    except OSError:
                        pass
                try:
                    store.update(job_id, status="failed", error=error_msg)
                except Exception:
                    logger.exception("store.update failed job_id=%s", job_id)
        except Exception as exc:
            logger.exception("backtest waiter crashed job_id=%s", job_id)
            try:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=60)
            except Exception:
                logger.debug("reap after waiter crash failed job_id=%s", job_id, exc_info=True)
            try:
                store.update(job_id, status="failed", error=f"Internal waiter error: {exc!r}")
            except Exception:
                pass
        finally:
            _untrack_backtest_proc(proc)
            try:
                log_fh.close()
            except Exception:
                pass

    t = threading.Thread(target=_wait_for_completion, daemon=True, name=f"backtest-wait-{job_id}")
    t.start()

    return proc.pid


def _cancel_worker(pid: int) -> bool:
    """Send SIGTERM, wait briefly, then SIGKILL if still alive."""
    if not _pid_alive(pid):
        return False
    try:
        if sys.platform == "win32":
            # /T — kill child processes too (harness may spawn helpers).
            subprocess.call(["taskkill", "/F", "/T", "/PID", str(pid)], timeout=15)
        else:
            os.kill(pid, signal.SIGTERM)
            time.sleep(2)
            if _pid_alive(pid):
                os.kill(pid, signal.SIGKILL)
        return True
    except (OSError, ProcessLookupError):
        return False


def _read_progress(job_dir: str) -> float:
    """Read progress_pct from the harness-emitted progress.json."""
    try:
        p = Path(job_dir) / "progress.json"
        if p.exists():
            data = json.loads(p.read_text())
            return float(data.get("progress_pct", 0.0))
    except Exception:
        pass
    return 0.0


def _job_api_payload(store: JobStore, job_row: dict[str, Any]) -> dict[str, Any]:
    """JSON shape for GET job and POST create (must include ``id`` for dashboard clients)."""
    job = dict(job_row)
    job_id = str(job["id"])
    if job.get("status") == "running":
        job_dir = str(_REPORTS_DIR / job_id)
        pct = _read_progress(job_dir)
        job["progress_pct"] = pct
        store.update(job_id, progress_pct=pct)
    result_summary = None
    if job.get("result_summary_json"):
        try:
            result_summary = json.loads(job["result_summary_json"])
        except Exception:
            pass
    return {
        "id": job_id,
        "preset_id": job["preset_id"],
        "overrides": json.loads(job.get("overrides_json", "{}") or "{}"),
        "status": job["status"],
        "progress_pct": float(job.get("progress_pct") or 0.0),
        "created_at": job["created_at"],
        "updated_at": job.get("updated_at"),
        "result_summary": result_summary,
        "error": job.get("error"),
    }


def _detect_stale_jobs(store: JobStore) -> None:
    """On startup, mark any 'running' jobs whose PIDs are dead as 'failed'."""
    for job in store.running_jobs():
        pid = job.get("pid")
        if not pid or not _pid_alive(pid):
            store.update(
                job["id"],
                status="failed",
                error="Process not found on startup — likely crashed",
            )
            logger.warning("Marked stale job %s as failed (pid=%s)", job["id"], pid)


# ---------------------------------------------------------------------------
# Starlette routes
# ---------------------------------------------------------------------------

def create_backtest_routes(auth_check):
    """Create backtest route list.

    ``auth_check`` is a callable(request) → Optional[Response] that returns
    a 401 response if unauthorized, or None if OK.  Reuses the existing
    realtime-ui-api auth pattern.
    """
    import orjson
    from starlette.requests import Request
    from starlette.responses import Response, StreamingResponse
    from starlette.routing import Route

    store = JobStore(_DB_PATH)
    _detect_stale_jobs(store)

    presets_cache: dict[str, dict[str, Any]] = {}
    presets_cache_ts: float = 0

    def _get_presets() -> dict[str, dict[str, Any]]:
        nonlocal presets_cache, presets_cache_ts
        now = time.monotonic()
        if now - presets_cache_ts > 30:
            presets_cache = _load_presets()
            presets_cache_ts = now
        return presets_cache

    def _json_response(payload: Any, status_code: int = 200) -> Response:
        return Response(
            content=orjson.dumps(payload, option=orjson.OPT_NON_STR_KEYS),
            status_code=status_code,
            media_type="application/json",
            headers={"Cache-Control": "no-store"},
        )

    async def get_presets(request: Request) -> Response:
        denied = auth_check(request)
        if denied:
            return denied
        presets = _get_presets()
        return _json_response({"presets": list(presets.values())})

    async def create_job(request: Request) -> Response:
        denied = auth_check(request)
        if denied:
            return denied

        try:
            body = await request.json()
        except Exception:
            return _json_response({"error": "Invalid JSON body"}, 400)

        preset_id = body.get("preset_id", "").strip()
        overrides = body.get("overrides", {})
        if not isinstance(overrides, dict):
            return _json_response({"error": "overrides must be an object"}, 400)

        presets = _get_presets()
        if preset_id not in presets:
            return _json_response(
                {"error": f"Unknown preset: {preset_id}", "available": list(presets.keys())},
                400,
            )

        err = _validate_overrides(overrides)
        if err:
            return _json_response({"error": err}, 400)

        if store.running_count() >= _MAX_CONCURRENT_JOBS:
            return _json_response(
                {"error": f"Max concurrent jobs ({_MAX_CONCURRENT_JOBS}) reached"},
                429,
            )

        job_id = uuid.uuid4().hex[:12]
        now = _now_iso()
        preset = presets[preset_id]

        store.insert({
            "id": job_id,
            "preset_id": preset_id,
            "overrides": overrides,
            "status": "pending",
            "created_at": now,
            "updated_at": now,
        })

        _spawn_worker(store, job_id, preset["file"], overrides)
        fresh = store.get(job_id)
        if not fresh:
            return _json_response({"error": "Job record missing after spawn"}, 500)
        return _json_response(_job_api_payload(store, fresh), 201)

    async def get_job(request: Request) -> Response:
        denied = auth_check(request)
        if denied:
            return denied
        job_id = request.path_params["id"]
        job = store.get(job_id)
        if not job:
            return _json_response({"error": "Job not found"}, 404)

        return _json_response(_job_api_payload(store, job))

    async def get_job_log(request: Request) -> Response:
        denied = auth_check(request)
        if denied:
            return denied
        job_id = request.path_params["id"]
        job = store.get(job_id)
        if not job:
            return _json_response({"error": "Job not found"}, 404)

        log_path = job.get("log_path", "")
        if not log_path or not Path(log_path).exists():
            return _json_response({"error": "Log not available yet"}, 404)

        async def _log_generator():
            line_id = 0
            with open(log_path) as f:
                while True:
                    line = f.readline()
                    if line:
                        line_id += 1
                        yield f"id: {line_id}\nevent: log\ndata: {json.dumps(line.rstrip())}\n\n"
                    else:
                        current_job = store.get(job_id)
                        if current_job and current_job["status"] not in ("running", "pending"):
                            yield f"event: done\ndata: {json.dumps({'status': current_job['status']})}\n\n"
                            return
                        await asyncio.sleep(0.5)

        return StreamingResponse(
            _log_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    async def cancel_job(request: Request) -> Response:
        denied = auth_check(request)
        if denied:
            return denied
        job_id = request.path_params["id"]
        job = store.get(job_id)
        if not job:
            return _json_response({"error": "Job not found"}, 404)
        if job["status"] != "running":
            return _json_response({"error": f"Job is not running (status={job['status']})"}, 409)

        pid = job.get("pid")
        if pid:
            _cancel_worker(pid)

        store.update(job_id, status="cancelled")
        return _json_response({"id": job_id, "status": "cancelled"})

    async def list_jobs(request: Request) -> Response:
        denied = auth_check(request)
        if denied:
            return denied
        limit = min(int(request.query_params.get("limit", "50") or "50"), 200)
        jobs = store.list_all(limit)
        result = []
        for job in jobs:
            summary = None
            if job.get("result_summary_json"):
                try:
                    summary = json.loads(job["result_summary_json"])
                except Exception:
                    pass
            result.append({
                "id": job["id"],
                "preset_id": job["preset_id"],
                "status": job["status"],
                "progress_pct": job["progress_pct"],
                "created_at": job["created_at"],
                "result_summary": summary,
                "error": job.get("error"),
            })
        return _json_response({"jobs": result})

    return [
        Route("/api/backtest/presets", get_presets, methods=["GET"]),
        Route("/api/backtest/jobs", list_jobs, methods=["GET"]),
        Route("/api/backtest/jobs", create_job, methods=["POST"]),
        Route("/api/backtest/jobs/{id}", get_job, methods=["GET"]),
        Route("/api/backtest/jobs/{id}/log", get_job_log, methods=["GET"]),
        Route("/api/backtest/jobs/{id}/cancel", cancel_job, methods=["POST"]),
    ]
