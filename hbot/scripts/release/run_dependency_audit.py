"""Automated dependency audit: CVE scanning and outdated package detection.

Runs ``pip-audit`` for known vulnerability scanning and ``pip list --outdated``
for freshness detection.  Emits a JSON report to
``reports/security/dependency_audit_latest.json``.

Usage::

    python scripts/release/run_dependency_audit.py
    python scripts/release/run_dependency_audit.py --root /path/to/hbot

Designed to run as a non-blocking gate in the promotion cycle.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]

RunnerFn = Callable[[list[str]], tuple[int, str, str]]


def _run_command(cmd: list[str], *, cwd: Path) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, check=False, timeout=120, cwd=str(cwd),
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except FileNotFoundError:
        return 127, "", f"command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 1, "", "command timed out"


def _parse_requirements(req_path: Path) -> list[dict[str, str]]:
    """Parse a requirements file into a list of {name, specifier} dicts."""
    rows: list[dict[str, str]] = []
    if not req_path.exists():
        return rows
    for line in req_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        m = re.match(r"([A-Za-z0-9_.-]+)\s*(.*)", line)
        if m:
            rows.append({"name": m.group(1), "specifier": m.group(2).strip()})
    return rows


def _installed_versions(packages: list[str]) -> dict[str, str]:
    """Get installed versions for a list of package names."""
    result: dict[str, str] = {}
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "show"] + packages,
            capture_output=True, text=True, check=False, timeout=30,
        )
        current_name = ""
        for line in (proc.stdout or "").splitlines():
            if line.startswith("Name:"):
                current_name = line.split(":", 1)[1].strip().lower()
            elif line.startswith("Version:") and current_name:
                result[current_name] = line.split(":", 1)[1].strip()
    except Exception:
        pass
    return result


def _collect_outdated(
    tracked_names: list[str],
    root: Path,
    runner: RunnerFn | None = None,
) -> dict[str, Any]:
    """Collect outdated packages, filtered to tracked names."""
    _run = runner or (lambda cmd: _run_command(cmd, cwd=root))
    rc, stdout, stderr = _run([sys.executable, "-m", "pip", "list", "--outdated", "--format", "json"])

    result: dict[str, Any] = {"available": True, "packages": []}
    if rc != 0:
        result["available"] = False
        result["error"] = stderr[:500]
        return result

    try:
        all_outdated = json.loads(stdout) if stdout.strip() else []
    except json.JSONDecodeError:
        result["available"] = False
        return result

    tracked_lower = {n.lower() for n in tracked_names}
    for pkg in all_outdated:
        name = pkg.get("name", "")
        if name.lower() in tracked_lower:
            result["packages"].append({
                "name": name,
                "current_version": pkg.get("version", ""),
                "latest_version": pkg.get("latest_version", ""),
                "latest_filetype": pkg.get("latest_filetype", ""),
            })
    return result


def _collect_pip_audit(
    req_path: Path,
    root: Path,
    runner: RunnerFn | None = None,
) -> dict[str, Any]:
    """Run pip-audit and collect CVE information."""
    _run = runner or (lambda cmd: _run_command(cmd, cwd=root))
    cmd = [sys.executable, "-m", "pip_audit", "--format", "json", "--output", "-"]
    if req_path.exists():
        cmd.extend(["--requirement", str(req_path)])

    rc, stdout, stderr = _run(cmd)

    result: dict[str, Any] = {"available": True, "vulnerability_count": 0, "vulnerabilities": []}
    if rc != 0 and not stdout.strip():
        result["available"] = False
        result["error"] = stderr[:500]
        return result

    try:
        if stdout.strip():
            data = json.loads(stdout)
            deps = data.get("dependencies", []) if isinstance(data, dict) else data if isinstance(data, list) else []
            for dep in deps:
                vulns = dep.get("vulns", [])
                for v in vulns:
                    result["vulnerabilities"].append({
                        "id": v.get("id", ""),
                        "package": dep.get("name", ""),
                        "version": dep.get("version", ""),
                        "description": v.get("description", "")[:200],
                        "fix_versions": v.get("fix_versions", []),
                    })
            result["vulnerability_count"] = len(result["vulnerabilities"])
    except (json.JSONDecodeError, KeyError):
        result["available"] = False

    return result


def run(root: Path) -> dict[str, Any]:
    """Run full audit and emit report artifact."""
    req_path = root / "compose" / "images" / "control_plane" / "requirements-control-plane.txt"
    packages = _parse_requirements(req_path)
    tracked_names = [p["name"] for p in packages]

    versions = _installed_versions(tracked_names)
    cves = _collect_pip_audit(req_path, root)
    outdated = _collect_outdated(tracked_names, root)

    cve_count = cves.get("vulnerability_count", 0)
    outdated_count = len(outdated.get("packages", []))

    cve_available = cves.get("available", False)
    if cve_count > 0:
        status = "critical"
    elif not cve_available or outdated_count > 0:
        status = "warning"
    else:
        status = "clean"

    report: dict[str, Any] = {
        "audit_date": datetime.now(tz=UTC).isoformat(),
        "ts_epoch": time.time(),
        "requirements_file": str(req_path),
        "status": status,
        "tracked_package_count": len(tracked_names),
        "packages": [
            {
                "name": p["name"],
                "specifier": p["specifier"],
                "installed_version": versions.get(p["name"].lower(), "unknown"),
            }
            for p in packages
        ],
        "cves": cves,
        "outdated": outdated,
        "cve_count": cve_count,
        "outdated_count": outdated_count,
    }

    reports_dir = root / "reports" / "security"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "dependency_audit_latest.json"
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    logger.info("Audit report written to %s", report_path)
    logger.info("CVEs: %d, Outdated: %d, Status: %s", cve_count, outdated_count, status)

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run dependency CVE + freshness audit.")
    parser.add_argument("--root", type=str, default=str(_ROOT), help="Project root directory.")
    args = parser.parse_args()
    run(Path(args.root))


if __name__ == "__main__":
    main()
