"""Research Lab API — hosted as a Starlette sub-application.

Read-only endpoints exposing strategy research lab outputs:
  GET  /api/research/candidates                          — list all candidates
  GET  /api/research/candidates/{name}                   — candidate detail
  GET  /api/research/reports/{candidate_name}/{run_id}   — evaluation report (markdown)
  GET  /api/research/explorations                        — list exploration sessions
  GET  /api/research/explorations/{session_id}           — session detail
  GET  /api/research/explorations/{session_id}/log       — SSE log stream

Design decision D1/D2: mounted on realtime-ui-api, reads files directly.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_RESEARCH_DIR = Path(os.environ.get("RESEARCH_DATA_DIR", "data/research"))
_CANDIDATES_DIR = _RESEARCH_DIR / "candidates"
_LIFECYCLE_DIR = _RESEARCH_DIR / "lifecycle"
_EXPERIMENTS_DIR = _RESEARCH_DIR / "experiments"
_REPORTS_DIR = _RESEARCH_DIR / "reports"
_EXPLORATIONS_DIR = _RESEARCH_DIR / "explorations"

_SAFE_NAME_RE = re.compile(r"^[\w\-]+$")


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


def _best_score_from_experiments(experiments: list[dict[str, Any]]) -> tuple[float | None, str | None]:
    best_score: float | None = None
    best_rec: str | None = None
    for exp in experiments:
        score = exp.get("robustness_score")
        if score is not None:
            if best_score is None or float(score) > best_score:
                best_score = float(score)
                best_rec = exp.get("recommendation")
    return best_score, best_rec


def _scan_candidates() -> list[dict[str, Any]]:
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
        results.append({
            "name": name,
            "hypothesis": data.get("hypothesis", ""),
            "adapter_mode": data.get("adapter_mode", ""),
            "lifecycle": lifecycle.get("current_state", "candidate"),
            "best_score": best_score,
            "best_recommendation": best_rec,
            "experiment_count": len(experiments),
        })
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
    report_path = ""
    if experiments:
        last_run_id = experiments[-1].get("run_id", "")
        candidate_report = _REPORTS_DIR / _safe_name(name) / last_run_id[:8] / "report.md"
        if candidate_report.exists():
            report_path = str(candidate_report)
    return {
        "name": data.get("name", name),
        "hypothesis": data.get("hypothesis", ""),
        "adapter_mode": data.get("adapter_mode", ""),
        "entry_logic": data.get("entry_logic", ""),
        "exit_logic": data.get("exit_logic", ""),
        "parameter_space": data.get("parameter_space", {}),
        "base_config": data.get("base_config", {}),
        "required_tests": data.get("required_tests", []),
        "metadata": data.get("metadata", {}),
        "lifecycle": lifecycle,
        "experiments": experiments,
        "best_score": best_score,
        "best_recommendation": best_rec,
        "latest_report_path": report_path,
    }


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
        completed = result_file.exists()
        iter_files = sorted(entry.glob("iter_*.yml"))
        iteration_count = len(iter_files)
        best_score: float | None = None
        best_candidate = ""
        if completed:
            sr = _read_json(result_file)
            if sr:
                best_score = sr.get("best_observed_score")
                best_candidate = sr.get("best_observed_candidate", "")
        try:
            created_at = datetime.fromtimestamp(entry.stat().st_mtime, tz=UTC).isoformat()
        except Exception:
            created_at = ""
        results.append({
            "session_id": session_id,
            "status": "completed" if completed else "running",
            "iteration_count": iteration_count,
            "best_score": best_score,
            "best_candidate": best_candidate,
            "created_at": created_at,
        })
    results.sort(key=lambda s: s["created_at"], reverse=True)
    return results


def _get_exploration_detail(session_id: str) -> dict[str, Any] | None:
    session_dir = _EXPLORATIONS_DIR / session_id
    if not session_dir.is_dir():
        return None
    result_file = session_dir / "session_result.json"
    if result_file.exists():
        sr = _read_json(result_file)
        if sr:
            sr["status"] = "completed"
            return sr
    iter_files = sorted(session_dir.glob("iter_*.yml"))
    iterations: list[dict[str, Any]] = []
    for f in iter_files:
        data = _read_yaml(f)
        if data:
            iterations.append({
                "file": f.name,
                "name": data.get("name", ""),
                "score": data.get("score"),
                "recommendation": data.get("recommendation"),
            })
    return {"status": "running", "iterations": iterations}


def _parse_iteration_yaml(path: Path) -> dict[str, Any]:
    data = _read_yaml(path) or {}
    match = re.match(r"iter_(\d+)", path.stem)
    iteration = int(match.group(1)) if match else 0
    return {
        "iteration": iteration,
        "candidate_name": data.get("name", path.stem),
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

    async def list_explorations(request: Request) -> Response:
        denied = auth_check(request)
        if denied:
            return denied
        sessions = _scan_explorations()
        return _json_response({"explorations": sessions})

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
                iter_files = sorted(session_dir.glob("iter_*.yml"))
                for f in iter_files:
                    if f.name not in seen_files:
                        seen_files.add(f.name)
                        parsed = _parse_iteration_yaml(f)
                        yield f"event: iteration\ndata: {json.dumps(parsed)}\n\n"
                if result_file.exists():
                    sr = _read_json(result_file) or {}
                    summary = {
                        "best_observed_score": sr.get("best_observed_score", 0),
                        "best_observed_candidate": sr.get("best_observed_candidate", ""),
                        "total_tokens_used": sr.get("total_tokens_used", 0),
                        "iterations": len(sr.get("iterations", [])),
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
        Route("/api/research/reports/{candidate_name}/{run_id}", get_report, methods=["GET"]),
        Route("/api/research/explorations", list_explorations, methods=["GET"]),
        Route("/api/research/explorations/{session_id}", get_exploration, methods=["GET"]),
        Route("/api/research/explorations/{session_id}/log", exploration_log_sse, methods=["GET"]),
    ]
