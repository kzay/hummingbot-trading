from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_name(name: str) -> str:
    return str(name or "").strip().lower().replace("_", "-")


def _parse_requirements(path: Path) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    if not path.exists():
        return rows
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        package = line
        specifier = ""
        for marker in ("==", ">=", "<=", "~=", "!=", ">", "<"):
            if marker in line:
                package, specifier = line.split(marker, 1)
                specifier = marker + specifier.strip()
                break
        normalized = _normalize_name(package)
        if not normalized:
            continue
        rows.append(
            {
                "name": normalized,
                "requirement": line,
                "specifier": specifier,
            }
        )
    return rows


def _installed_versions(packages: Sequence[str]) -> Dict[str, str]:
    installed: Dict[str, str] = {}
    for package in packages:
        try:
            installed[package] = metadata.version(package)
        except Exception:
            installed[package] = ""
    return installed


def _run_command(cmd: Sequence[str], *, cwd: Path) -> Tuple[int, str, str]:
    proc = subprocess.run(
        list(cmd),
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    return int(proc.returncode), proc.stdout or "", proc.stderr or ""


def _collect_outdated(
    tracked_packages: Sequence[str],
    *,
    root: Path,
    runner: Callable[[Sequence[str]], Tuple[int, str, str]],
) -> Dict[str, object]:
    rc, stdout, stderr = runner([sys.executable, "-m", "pip", "list", "--outdated", "--format=json"])
    result: Dict[str, object] = {
        "available": rc == 0,
        "return_code": rc,
        "packages": [],
        "error": stderr.strip(),
    }
    if rc != 0:
        return result
    try:
        rows = json.loads(stdout or "[]")
    except Exception:
        result["available"] = False
        result["error"] = "invalid_json"
        return result
    tracked = {_normalize_name(name) for name in tracked_packages}
    packages: List[Dict[str, str]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        name = _normalize_name(str(row.get("name", "")))
        if name not in tracked:
            continue
        packages.append(
            {
                "name": name,
                "current_version": str(row.get("version", "")),
                "latest_version": str(row.get("latest_version", "")),
                "latest_filetype": str(row.get("latest_filetype", "")),
            }
        )
    result["packages"] = sorted(packages, key=lambda item: item["name"])
    return result


def _collect_pip_audit(
    requirements_path: Path,
    *,
    root: Path,
    runner: Callable[[Sequence[str]], Tuple[int, str, str]],
) -> Dict[str, object]:
    rc, stdout, stderr = runner([sys.executable, "-m", "pip_audit", "-r", str(requirements_path), "--format", "json"])
    result: Dict[str, object] = {
        "available": rc == 0,
        "return_code": rc,
        "vulnerability_count": 0,
        "dependencies_scanned": 0,
        "vulnerabilities": [],
        "error": stderr.strip(),
    }
    if rc != 0:
        return result
    try:
        payload = json.loads(stdout or "{}")
    except Exception:
        result["available"] = False
        result["error"] = "invalid_json"
        return result
    dependencies = payload.get("dependencies", []) if isinstance(payload, dict) else []
    vulnerabilities: List[Dict[str, str]] = []
    for dep in dependencies if isinstance(dependencies, list) else []:
        if not isinstance(dep, dict):
            continue
        name = _normalize_name(str(dep.get("name", "")))
        version = str(dep.get("version", ""))
        vulns = dep.get("vulns", [])
        for vuln in vulns if isinstance(vulns, list) else []:
            if not isinstance(vuln, dict):
                continue
            vulnerabilities.append(
                {
                    "name": name,
                    "version": version,
                    "id": str(vuln.get("id", "")),
                    "fix_versions": ",".join(str(v) for v in vuln.get("fix_versions", []) if str(v).strip()),
                    "description": str(vuln.get("description", ""))[:240],
                }
            )
    result["dependencies_scanned"] = len(dependencies) if isinstance(dependencies, list) else 0
    result["vulnerability_count"] = len(vulnerabilities)
    result["vulnerabilities"] = vulnerabilities
    return result


def run(root: Path) -> Dict[str, object]:
    requirements_path = root / "compose" / "images" / "control_plane" / "requirements-control-plane.txt"
    requirements = _parse_requirements(requirements_path)
    tracked_names = [row["name"] for row in requirements]
    installed = _installed_versions(tracked_names)

    def _runner(cmd: Sequence[str]) -> Tuple[int, str, str]:
        return _run_command(cmd, cwd=root)

    outdated = _collect_outdated(tracked_names, root=root, runner=_runner)
    cves = _collect_pip_audit(requirements_path, root=root, runner=_runner)
    packages = [
        {
            **row,
            "installed_version": installed.get(row["name"], ""),
        }
        for row in requirements
    ]
    recommendations = [
        {
            "candidate": "orjson",
            "policy": "experiment_only",
            "why": "Only consider when JSON serialization shows measured CPU cost and rollback is documented.",
        },
        {
            "candidate": "redis.asyncio",
            "policy": "experiment_only",
            "why": "Only consider with measured reconnect or throughput benefit and bounded bridge/event-store migration scope.",
        },
        {
            "candidate": "structlog",
            "policy": "defer",
            "why": "Do not adopt without a concrete observability need that stdlib logging cannot satisfy.",
        },
        {
            "candidate": "anyio",
            "policy": "defer",
            "why": "Do not add unless an explicit concurrency abstraction need is demonstrated across services.",
        },
    ]
    status = "pass"
    if not bool(outdated.get("available", False)) or not bool(cves.get("available", False)):
        status = "warning"
    if int(cves.get("vulnerability_count", 0) or 0) > 0:
        status = "fail"
    report = {
        "status": status,
        "ts_utc": _utc_now(),
        "requirements_path": str(requirements_path),
        "tracked_package_count": len(packages),
        "packages": packages,
        "outdated": outdated,
        "cves": cves,
        "adoption_policy": recommendations,
    }
    out_dir = root / "reports" / "security"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamped = out_dir / f"dependency_audit_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    latest = out_dir / "dependency_audit_latest.json"
    stamped.write_text(json.dumps(report, indent=2), encoding="utf-8")
    latest.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    report = run(root)
    print(json.dumps({"status": report["status"], "path": "reports/security/dependency_audit_latest.json"}))
    return 0 if str(report.get("status", "warning")) in {"pass", "warning"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
