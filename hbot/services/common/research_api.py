"""Research Lab API route factory.

Endpoints exposing strategy research lab outputs and exploration launch:
  GET  /api/research/candidates                          — list all candidates
  GET  /api/research/candidates/{name}                   — candidate detail
  GET  /api/research/leaderboard                         — ranked candidates
  GET  /api/research/reports/{candidate_name}/{run_id}   — evaluation report (markdown)
  GET  /api/research/explorations                        — list exploration sessions
  POST /api/research/explorations                        — launch a new exploration
  GET  /api/research/explorations/{session_id}           — session detail
  GET  /api/research/explorations/{session_id}/log       — SSE log stream
  POST /api/research/explorations/{session_id}/cancel    — cancel running exploration

The routes are mounted by whichever Starlette service owns research traffic.
They read file-backed research state directly from the workspace.

Storage root: hbot/data/research (override via RESEARCH_DATA_DIR env var).
"""
from __future__ import annotations

import asyncio
import atexit
import json
import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Unified storage root — same default as all controller code
_RESEARCH_DIR = Path(os.environ.get("RESEARCH_DATA_DIR", "hbot/data/research"))
_CANDIDATES_DIR = _RESEARCH_DIR / "candidates"
_LIFECYCLE_DIR = _RESEARCH_DIR / "lifecycle"
_EXPERIMENTS_DIR = _RESEARCH_DIR / "experiments"
_REPORTS_DIR = _RESEARCH_DIR / "reports"
_EXPLORATIONS_DIR = _RESEARCH_DIR / "explorations"
_PAPER_RUNS_DIR = _RESEARCH_DIR / "paper_runs"
_PAPER_ARTIFACTS_DIR = _RESEARCH_DIR / "paper_artifacts"

_SAFE_NAME_RE = re.compile(r"^[\w\-]+$")
_MAX_CONCURRENT_EXPLORATIONS = int(os.environ.get("RESEARCH_MAX_CONCURRENT", "1"))
_MAX_WALL_TIME_S = int(os.environ.get("RESEARCH_MAX_WALL_TIME_S", "28800"))

_VALID_PROVIDERS = frozenset({"anthropic", "openai"})
_VALID_ADAPTERS = frozenset({
    "atr_mm", "atr_mm_v2", "smc_mm", "combo_mm",
    "pullback", "pullback_v2", "momentum_scalper",
    "directional_mm", "simple", "ta_composite",
})

# ---------------------------------------------------------------------------
# Exploration subprocess tracking
# ---------------------------------------------------------------------------

_exploration_procs: list[subprocess.Popen[Any]] = []
_exploration_procs_lock = threading.Lock()
_exploration_meta: dict[str, dict[str, Any]] = {}
_exploration_meta_lock = threading.Lock()


def _track_exploration_proc(proc: subprocess.Popen[Any]) -> None:
    with _exploration_procs_lock:
        _exploration_procs.append(proc)


def _untrack_exploration_proc(proc: subprocess.Popen[Any]) -> None:
    with _exploration_procs_lock:
        try:
            _exploration_procs.remove(proc)
        except ValueError:
            pass


def shutdown_exploration_subprocesses() -> None:
    """Kill and reap any running exploration children on process exit."""
    with _exploration_procs_lock:
        snap = list(_exploration_procs)
    for proc in snap:
        try:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=30)
        except Exception:
            logger.debug("exploration proc cleanup failed", exc_info=True)
    with _exploration_procs_lock:
        _exploration_procs.clear()


atexit.register(shutdown_exploration_subprocesses)


def _running_exploration_count() -> int:
    with _exploration_meta_lock:
        return sum(1 for m in _exploration_meta.values() if m.get("status") == "running")


def _pid_alive(pid: int) -> bool:
    if not pid:
        return False
    try:
        if sys.platform == "win32":
            import ctypes
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            handle = kernel32.OpenProcess(0x0400, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        else:
            os.kill(pid, 0)
            return True
    except (OSError, ProcessLookupError):
        return False


def _write_session_meta(session_dir: Path, meta: dict[str, Any]) -> None:
    """Persist session metadata to disk for recovery after container restarts."""
    try:
        meta_path = session_dir / "session_meta.json"
        meta_path.write_text(json.dumps(meta, indent=2, default=str))
    except Exception:
        logger.debug("Failed to write session_meta.json", exc_info=True)


def _spawn_exploration(
    session_id: str,
    provider: str,
    iterations: int,
    temperature: float,
    adapters: list[str],
    skip_sweep: bool,
    skip_walkforward: bool,
    extra_context: str,
) -> int:
    """Spawn explore_cli in a subprocess, return PID."""
    session_dir = _EXPLORATIONS_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    log_path = session_dir / "run.log"

    cmd = [
        sys.executable, "-m", "controllers.research.explore_cli",
        "--provider", provider,
        "--iterations", str(iterations),
        "--temperature", str(temperature),
        "--adapters", ",".join(adapters),
        "--output-dir", str(session_dir),
        "--reports-dir", str(_REPORTS_DIR),
        "--experiments-dir", str(_EXPERIMENTS_DIR),
        "--lifecycle-dir", str(_LIFECYCLE_DIR),
        "--candidates-dir", str(_CANDIDATES_DIR),
    ]
    if skip_sweep:
        cmd.append("--skip-sweep")
    if skip_walkforward:
        cmd.append("--skip-walkforward")
    if extra_context:
        cmd.extend(["--extra-context", extra_context])

    log_fh = open(log_path, "w", buffering=1)
    env = {**os.environ, "PYTHONPATH": os.environ.get("PYTHONPATH", "hbot")}

    proc = subprocess.Popen(
        cmd,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        env=env,
        start_new_session=True,
    )
    _track_exploration_proc(proc)

    meta = {
        "status": "running",
        "pid": proc.pid,
        "log_path": str(log_path),
        "created_at": datetime.now(UTC).isoformat(),
        "launch_params": {
            "provider": provider,
            "iterations": iterations,
            "temperature": temperature,
            "adapters": adapters,
            "skip_sweep": skip_sweep,
            "skip_walkforward": skip_walkforward,
            "extra_context": extra_context,
        },
    }
    with _exploration_meta_lock:
        _exploration_meta[session_id] = meta

    _write_session_meta(session_dir, meta)

    def _wait_for_completion() -> None:
        try:
            try:
                proc.wait(timeout=_MAX_WALL_TIME_S)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=60)
                except subprocess.TimeoutExpired:
                    logger.warning("exploration %s: kill did not reap within 60s", session_id)
                with _exploration_meta_lock:
                    if session_id in _exploration_meta:
                        _exploration_meta[session_id]["status"] = "timed_out"
                _write_session_meta(session_dir, {"status": "timed_out"})
                return

            final_status = "completed" if proc.returncode == 0 else "failed"
            with _exploration_meta_lock:
                if session_id in _exploration_meta:
                    _exploration_meta[session_id]["status"] = final_status
            _write_session_meta(session_dir, {"status": final_status})
        except Exception:
            logger.exception("exploration waiter crashed session_id=%s", session_id)
            with _exploration_meta_lock:
                if session_id in _exploration_meta:
                    _exploration_meta[session_id]["status"] = "failed"
            _write_session_meta(session_dir, {"status": "failed"})
        finally:
            _untrack_exploration_proc(proc)
            try:
                log_fh.close()
            except Exception:
                pass  # Justification: best-effort cleanup

    t = threading.Thread(target=_wait_for_completion, daemon=True, name=f"explore-wait-{session_id}")
    t.start()
    return proc.pid


def _cancel_exploration(session_id: str) -> bool:
    with _exploration_meta_lock:
        meta = _exploration_meta.get(session_id)
    if not meta or meta.get("status") != "running":
        return False
    pid = meta.get("pid")
    if not pid or not _pid_alive(pid):
        return False
    try:
        if sys.platform == "win32":
            subprocess.call(["taskkill", "/F", "/T", "/PID", str(pid)], timeout=15)
        else:
            os.kill(pid, signal.SIGTERM)
            time.sleep(2)
            if _pid_alive(pid):
                os.kill(pid, signal.SIGKILL)
        with _exploration_meta_lock:
            if session_id in _exploration_meta:
                _exploration_meta[session_id]["status"] = "cancelled"
        return True
    except (OSError, ProcessLookupError):
        return False


def _safe_name(name: str) -> str:
    return name.replace("/", "_").replace("\\", "_").strip()


def _read_yaml(path: Path) -> dict[str, Any] | None:
    try:
        import yaml
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except Exception as exc:
        logger.warning("Failed to parse YAML %s: %s", path, exc)
        return None


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if not path.exists():
        return entries
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    except Exception as exc:
        logger.warning("Failed to read JSONL %s: %s", path, exc)
    return entries


def _read_lifecycle(candidate_name: str) -> dict[str, Any]:
    safe = _safe_name(candidate_name)
    path = _LIFECYCLE_DIR / f"{safe}.json"
    if path.exists():
        data = _read_json(path)
        if data:
            return data
    return {"candidate_name": candidate_name, "current_state": "candidate", "history": []}


def _read_experiments(candidate_name: str) -> list[dict[str, Any]]:
    safe = _safe_name(candidate_name)
    path = _EXPERIMENTS_DIR / f"{safe}.jsonl"
    return _read_jsonl(path)


def _best_experiment(experiments: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the experiment with the highest robustness score."""
    best: dict[str, Any] = {}
    best_score: float | None = None
    for exp in experiments:
        score = exp.get("robustness_score")
        if score is not None:
            if best_score is None or float(score) > best_score:
                best_score = float(score)
                best = exp
    return best


def _best_score_from_experiments(experiments: list[dict[str, Any]]) -> tuple[float | None, str | None]:
    best = _best_experiment(experiments)
    return (
        best.get("robustness_score"),
        best.get("recommendation"),
    )


def _scan_candidates() -> list[dict[str, Any]]:
    """Scan candidates directory; include governed metadata when available."""
    results: list[dict[str, Any]] = []
    if not _CANDIDATES_DIR.exists():
        return results
    for yml_file in sorted(_CANDIDATES_DIR.glob("*.yml")):
        data = _read_yaml(yml_file)
        if data is None:
            continue
        name = data.get("name", yml_file.stem)
        lifecycle = _read_lifecycle(name)
        experiments = _read_experiments(name)
        best_score, best_rec = _best_score_from_experiments(experiments)
        best_exp = _best_experiment(experiments)
        entry: dict[str, Any] = {
            "name": name,
            "hypothesis": data.get("hypothesis", ""),
            "adapter_mode": data.get("adapter_mode", ""),
            "lifecycle": lifecycle.get("current_state", "candidate"),
            "best_score": best_score,
            "best_recommendation": best_rec,
            "experiment_count": len(experiments),
            # Governed fields (present when schema_version >= 2)
            "strategy_family": data.get("strategy_family", ""),
            "template_id": data.get("template_id", ""),
            "schema_version": data.get("schema_version", 1),
            "validation_tier": best_exp.get("validation_tier", ""),
            "paper_status": best_exp.get("paper_status", ""),
        }
        results.append(entry)
    results.sort(key=lambda c: (c["best_score"] is None, -(c["best_score"] or 0)))
    return results


def _get_candidate_detail(name: str) -> dict[str, Any] | None:
    yml_path = _CANDIDATES_DIR / f"{_safe_name(name)}.yml"
    if not yml_path.exists():
        for p in _CANDIDATES_DIR.glob("*.yml"):
            data = _read_yaml(p)
            if data and data.get("name") == name:
                yml_path = p
                break
        else:
            return None
    data = _read_yaml(yml_path)
    if data is None:
        return None
    lifecycle = _read_lifecycle(name)
    experiments = _read_experiments(name)
    best_score, best_rec = _best_score_from_experiments(experiments)
    best_exp = _best_experiment(experiments)
    report_path = ""
    if experiments:
        last_run_id = experiments[-1].get("run_id", "")
        candidate_report = _REPORTS_DIR / _safe_name(name) / last_run_id[:8] / "report.md"
        if candidate_report.exists():
            report_path = str(candidate_report)

    # Load paper run status
    paper_runs = _read_paper_runs(name)
    active_paper_runs = [r for r in paper_runs if r.get("status") == "active"]

    return {
        "name": data.get("name", name),
        "hypothesis": data.get("hypothesis", ""),
        "adapter_mode": data.get("adapter_mode", ""),
        "entry_logic": data.get("entry_logic", ""),
        "exit_logic": data.get("exit_logic", ""),
        "parameter_space": data.get("parameter_space", {}),
        "search_space": data.get("search_space", {}),
        "base_config": data.get("base_config", {}),
        "required_tests": data.get("required_tests", []),
        "metadata": data.get("metadata", {}),
        "lifecycle": lifecycle,
        "experiments": experiments,
        "best_score": best_score,
        "best_recommendation": best_rec,
        "latest_report_path": report_path,
        # Governed fields
        "schema_version": data.get("schema_version", 1),
        "strategy_family": data.get("strategy_family", ""),
        "template_id": data.get("template_id", ""),
        "required_data": data.get("required_data", []),
        "market_conditions": data.get("market_conditions", ""),
        "expected_trade_frequency": data.get("expected_trade_frequency", "medium"),
        # Best experiment governance data
        "validation_tier": best_exp.get("validation_tier", ""),
        "gate_results": best_exp.get("gate_results"),
        "score_breakdown": best_exp.get("score_breakdown"),
        "stress_results": best_exp.get("stress_results"),
        "artifact_paths": best_exp.get("artifact_paths"),
        "paper_run_id": best_exp.get("paper_run_id"),
        "paper_status": best_exp.get("paper_status", ""),
        "paper_vs_backtest": best_exp.get("paper_vs_backtest"),
        # Paper run summaries
        "paper_runs": paper_runs,
        "active_paper_runs": len(active_paper_runs),
    }


def _read_paper_runs(candidate_name: str) -> list[dict[str, Any]]:
    safe = _safe_name(candidate_name)
    run_dir = _PAPER_RUNS_DIR / safe
    if not run_dir.exists():
        return []
    results = []
    for f in sorted(run_dir.glob("*.json")):
        data = _read_json(f)
        if data:
            results.append(data)
    return results


def _build_leaderboard(
    filter_tier: str | None = None,
    include_research_only: bool = True,
) -> list[dict[str, Any]]:
    """Build a ranked leaderboard of research candidates.

    Args:
        filter_tier: If set, only include candidates with this validation_tier.
        include_research_only: If False, exclude candle_only candidates.

    Returns a list of candidate summaries sorted by best_score descending.
    """
    candidates = _scan_candidates()
    ranked: list[dict[str, Any]] = []

    for c in candidates:
        tier = c.get("validation_tier", "")
        if filter_tier and tier != filter_tier:
            continue
        if not include_research_only and tier == "candle_only":
            continue
        score = c.get("best_score")
        if score is None:
            continue

        # Determine leaderboard category
        if tier == "replay_validated":
            category = "replay_validated"
        elif tier == "candle_only":
            category = "research_only"
        else:
            category = "unvalidated"

        ranked.append({
            "name": c["name"],
            "strategy_family": c.get("strategy_family", ""),
            "adapter_mode": c.get("adapter_mode", ""),
            "lifecycle": c.get("lifecycle", "candidate"),
            "best_score": score,
            "best_recommendation": c.get("best_recommendation", ""),
            "validation_tier": tier,
            "category": category,
            "paper_status": c.get("paper_status", ""),
            "experiment_count": c.get("experiment_count", 0),
        })

    ranked.sort(key=lambda x: (
        # Sort: replay_validated first, then research_only; within tier by score
        0 if x["category"] == "replay_validated" else 1,
        -(x["best_score"] or 0),
    ))
    return ranked


def _scan_explorations() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    if not _EXPLORATIONS_DIR.exists():
        return results
    for entry in sorted(_EXPLORATIONS_DIR.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name == ".gitkeep":
            continue
        session_id = entry.name
        result_file = entry / "session_result.json"
        summary_file = entry / "session_summary.json"
        completed = result_file.exists() or summary_file.exists()
        iter_files = sorted(entry.glob("iter_*.yml"))
        iteration_count = len(iter_files)
        best_score: float | None = None
        best_candidate = ""
        if completed:
            sr = _read_json(result_file) or _read_json(summary_file)
            if sr:
                best_score = sr.get("best_observed_score")
                best_candidate = sr.get("best_observed_candidate", "")

        with _exploration_meta_lock:
            meta = _exploration_meta.get(session_id)
        if meta:
            status = meta["status"]
        elif completed:
            status = "completed"
        else:
            disk_meta = _read_json(entry / "session_meta.json")
            if disk_meta and disk_meta.get("status"):
                status = disk_meta["status"]
            else:
                status = "unknown"

        try:
            created_at = datetime.fromtimestamp(entry.stat().st_mtime, tz=UTC).isoformat()
        except Exception:
            created_at = ""
        if meta and meta.get("created_at"):
            created_at = meta["created_at"]

        launch_params: dict[str, Any] | None = None
        if meta and meta.get("launch_params"):
            launch_params = meta["launch_params"]
        elif not meta:
            disk_meta = _read_json(entry / "session_meta.json") or {}
            launch_params = disk_meta.get("launch_params")

        session_entry: dict[str, Any] = {
            "session_id": session_id,
            "status": status,
            "iteration_count": iteration_count,
            "best_score": best_score,
            "best_candidate": best_candidate,
            "created_at": created_at,
        }
        if launch_params:
            session_entry["launch_params"] = launch_params
        results.append(session_entry)
    results.sort(key=lambda s: s["created_at"], reverse=True)
    return results


def _get_exploration_detail(session_id: str) -> dict[str, Any] | None:
    session_dir = _EXPLORATIONS_DIR / session_id
    if not session_dir.is_dir():
        return None
    disk_meta = _read_json(session_dir / "session_meta.json") or {}
    launch_params = disk_meta.get("launch_params")

    result_file = session_dir / "session_result.json"
    if result_file.exists():
        sr = _read_json(result_file)
        if sr:
            sr["status"] = "completed"
            if launch_params:
                sr["launch_params"] = launch_params
            return sr
    iter_files = sorted(session_dir.glob("iter_*.yml"))
    iterations: list[dict[str, Any]] = []
    for f in iter_files:
        data = _read_yaml(f)
        if data:
            iterations.append({
                "file": f.name,
                "name": data.get("name", ""),
                "strategy_family": data.get("strategy_family", ""),
                "template_id": data.get("template_id", ""),
                "score": data.get("score"),
                "recommendation": data.get("recommendation"),
            })
    result: dict[str, Any] = {"status": "running", "iterations": iterations}
    if launch_params:
        result["launch_params"] = launch_params
    return result


def _parse_iteration_yaml(path: Path) -> dict[str, Any]:
    data = _read_yaml(path) or {}
    match = re.match(r"iter_(\d+)", path.stem)
    iteration = int(match.group(1)) if match else 0
    adapter_mode = data.get("adapter_mode", "")
    is_blueprint = bool(adapter_mode and data.get("new_adapter_description"))
    hypothesis_full = data.get("hypothesis", "")
    hypothesis = hypothesis_full[:117] + "..." if len(hypothesis_full) > 120 else hypothesis_full
    raw_ps = data.get("parameter_space", {}) or {}
    param_space: dict[str, Any] = {}
    if isinstance(raw_ps, dict):
        for k, v in raw_ps.items():
            param_space[str(k)] = v
    return {
        "iteration": iteration,
        "candidate_name": data.get("name", path.stem),
        "adapter_mode": adapter_mode,
        "is_blueprint": is_blueprint,
        "strategy_family": data.get("strategy_family", ""),
        "template_id": data.get("template_id", ""),
        "hypothesis": hypothesis,
        "hypothesis_full": hypothesis_full,
        "entry_logic": data.get("entry_logic", ""),
        "exit_logic": data.get("exit_logic", ""),
        "parameter_space": param_space,
        "score": data.get("score"),
        "recommendation": data.get("recommendation"),
        "file": path.name,
    }


# ---------------------------------------------------------------------------
# Starlette routes
# ---------------------------------------------------------------------------

def create_research_routes(auth_check):
    """Create research route list.

    ``auth_check`` is a callable(request) -> Optional[Response].
    """
    import orjson
    from starlette.requests import Request
    from starlette.responses import Response, StreamingResponse
    from starlette.routing import Route

    def _json_response(payload: Any, status_code: int = 200) -> Response:
        return Response(
            content=orjson.dumps(payload, option=orjson.OPT_NON_STR_KEYS),
            status_code=status_code,
            media_type="application/json",
            headers={"Cache-Control": "no-store"},
        )

    async def list_candidates(request: Request) -> Response:
        denied = auth_check(request)
        if denied:
            return denied
        candidates = _scan_candidates()
        return _json_response({"candidates": candidates})

    async def get_candidate(request: Request) -> Response:
        denied = auth_check(request)
        if denied:
            return denied
        name = request.path_params["name"]
        detail = _get_candidate_detail(name)
        if detail is None:
            return _json_response({"error": "Candidate not found"}, 404)
        return _json_response(detail)

    async def get_leaderboard(request: Request) -> Response:
        denied = auth_check(request)
        if denied:
            return denied
        params = dict(request.query_params)
        filter_tier = params.get("tier")
        include_research_only = params.get("include_research_only", "true").lower() != "false"
        ranked = _build_leaderboard(
            filter_tier=filter_tier,
            include_research_only=include_research_only,
        )
        return _json_response({"leaderboard": ranked, "count": len(ranked)})

    async def get_report(request: Request) -> Response:
        denied = auth_check(request)
        if denied:
            return denied
        candidate_name = request.path_params["candidate_name"]
        run_id = request.path_params["run_id"]
        report_path = _REPORTS_DIR / _safe_name(candidate_name) / run_id / "report.md"
        if not report_path.exists():
            return _json_response({"error": "Report not found"}, 404)
        try:
            content = report_path.read_text(encoding="utf-8")
        except Exception:
            return _json_response({"error": "Failed to read report"}, 500)
        return Response(content=content, media_type="text/markdown", headers={"Cache-Control": "no-store"})

    async def explorations_endpoint(request: Request) -> Response:
        if request.method == "GET":
            return await _list_explorations(request)
        return await _create_exploration(request)

    async def _list_explorations(request: Request) -> Response:
        denied = auth_check(request)
        if denied:
            return denied
        sessions = _scan_explorations()
        return _json_response({"explorations": sessions})

    async def _create_exploration(request: Request) -> Response:
        denied = auth_check(request)
        if denied:
            return denied

        try:
            body = await request.json()
        except Exception:
            return _json_response({"error": "Invalid JSON body"}, 400)

        provider = str(body.get("provider", "anthropic")).strip()
        if provider not in _VALID_PROVIDERS:
            return _json_response({"error": f"Invalid provider. Allowed: {sorted(_VALID_PROVIDERS)}"}, 400)

        iterations = int(body.get("iterations", 5))
        if not (1 <= iterations <= 20):
            return _json_response({"error": "iterations must be between 1 and 20"}, 400)

        temperature = float(body.get("temperature", 0.7))
        if not (0.0 <= temperature <= 2.0):
            return _json_response({"error": "temperature must be between 0.0 and 2.0"}, 400)

        adapters_raw = body.get("adapters", list(_VALID_ADAPTERS))
        if isinstance(adapters_raw, str):
            adapters_raw = [a.strip() for a in adapters_raw.split(",") if a.strip()]
        adapters = [a for a in adapters_raw if a]
        if not adapters:
            adapters = list(_VALID_ADAPTERS)

        skip_sweep = bool(body.get("skip_sweep", False))
        skip_walkforward = bool(body.get("skip_walkforward", False))
        extra_context = str(body.get("extra_context", "")).strip()[:500]

        if _running_exploration_count() >= _MAX_CONCURRENT_EXPLORATIONS:
            return _json_response(
                {"error": f"Max concurrent explorations ({_MAX_CONCURRENT_EXPLORATIONS}) reached"},
                429,
            )

        session_id = uuid.uuid4().hex[:16]

        pid = _spawn_exploration(
            session_id=session_id,
            provider=provider,
            iterations=iterations,
            temperature=temperature,
            adapters=adapters,
            skip_sweep=skip_sweep,
            skip_walkforward=skip_walkforward,
            extra_context=extra_context,
        )

        return _json_response({
            "session_id": session_id,
            "status": "running",
            "pid": pid,
            "provider": provider,
            "iterations": iterations,
        }, 201)

    async def cancel_exploration(request: Request) -> Response:
        denied = auth_check(request)
        if denied:
            return denied
        session_id = request.path_params["session_id"]
        if not _SAFE_NAME_RE.match(session_id):
            return _json_response({"error": "Invalid session id"}, 400)
        if _cancel_exploration(session_id):
            return _json_response({"session_id": session_id, "status": "cancelled"})
        return _json_response({"error": "Session not running or not found"}, 409)

    async def get_exploration(request: Request) -> Response:
        denied = auth_check(request)
        if denied:
            return denied
        session_id = request.path_params["session_id"]
        if not _SAFE_NAME_RE.match(session_id):
            return _json_response({"error": "Invalid session id"}, 400)
        detail = _get_exploration_detail(session_id)
        if detail is None:
            return _json_response({"error": "Session not found"}, 404)
        return _json_response(detail)

    async def exploration_log_sse(request: Request) -> Response:
        denied = auth_check(request)
        if denied:
            return denied
        session_id = request.path_params["session_id"]
        if not _SAFE_NAME_RE.match(session_id):
            return _json_response({"error": "Invalid session id"}, 400)
        session_dir = _EXPLORATIONS_DIR / session_id
        if not session_dir.is_dir():
            return _json_response({"error": "Session not found"}, 404)

        async def _sse_generator():
            seen_files: set[str] = set()
            while True:
                result_file = session_dir / "session_result.json"
                summary_file = session_dir / "session_summary.json"
                iter_files = sorted(session_dir.glob("iter_*.yml"))
                for f in iter_files:
                    if f.name not in seen_files:
                        seen_files.add(f.name)
                        parsed = _parse_iteration_yaml(f)
                        yield f"event: iteration\ndata: {json.dumps(parsed)}\n\n"
                finish_file = result_file if result_file.exists() else (summary_file if summary_file.exists() else None)
                if finish_file is not None:
                    sr = _read_json(finish_file) or {}
                    iter_count = sr.get("total_iterations") or sr.get("iterations")
                    if isinstance(iter_count, list):
                        iter_count = len(iter_count)
                    summary = {
                        "best_observed_score": sr.get("best_observed_score"),
                        "best_observed_candidate": sr.get("best_observed_candidate", ""),
                        "best_recommendation": sr.get("best_recommendation", ""),
                        "total_tokens_used": sr.get("total_tokens_used", 0),
                        "iterations": iter_count or len(seen_files),
                    }
                    yield f"event: done\ndata: {json.dumps(summary)}\n\n"
                    return
                await asyncio.sleep(1.0)

        return StreamingResponse(
            _sse_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return [
        Route("/api/research/candidates", list_candidates, methods=["GET"]),
        Route("/api/research/candidates/{name:path}", get_candidate, methods=["GET"]),
        Route("/api/research/leaderboard", get_leaderboard, methods=["GET"]),
        Route("/api/research/reports/{candidate_name}/{run_id}", get_report, methods=["GET"]),
        Route("/api/research/explorations", explorations_endpoint, methods=["GET", "POST"]),
        Route("/api/research/explorations/{session_id}", get_exploration, methods=["GET"]),
        Route("/api/research/explorations/{session_id}/log", exploration_log_sse, methods=["GET"]),
        Route("/api/research/explorations/{session_id}/cancel", cancel_exploration, methods=["POST"]),
    ]
