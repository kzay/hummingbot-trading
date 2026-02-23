from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iter_candidate_files(root: Path, include_logs: bool) -> Iterable[Path]:
    for rel in ("docs", "reports"):
        base = root / rel
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file():
                yield path

    if include_logs:
        logs_root = root / "data"
        if logs_root.exists():
            for path in logs_root.rglob("*"):
                if path.is_file() and "logs" in path.parts:
                    yield path


def _load_env_secret_values(root: Path) -> List[str]:
    env_path = root / "env" / ".env"
    values: List[str] = []
    if not env_path.exists():
        return values

    secret_key_hints = ("KEY", "SECRET", "PASSPHRASE", "TOKEN", "PASSWORD")
    for raw_line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().upper()
        value = value.strip().strip('"').strip("'")
        if any(h in key for h in secret_key_hints):
            if value and value.lower() not in {"changeme", "example", "your_value_here", "xxxxx"} and len(value) >= 8:
                values.append(value)
    return values


def _is_probable_text(path: Path) -> bool:
    text_ext = {
        ".md",
        ".txt",
        ".log",
        ".json",
        ".jsonl",
        ".csv",
        ".yaml",
        ".yml",
        ".env",
    }
    return path.suffix.lower() in text_ext


def _scan_file(path: Path, regexes: List[re.Pattern[str]], secret_values: List[str], max_file_bytes: int) -> List[Dict[str, object]]:
    findings: List[Dict[str, object]] = []
    try:
        if path.stat().st_size > max_file_bytes:
            return findings
    except Exception:
        return findings

    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return findings

    for rx in regexes:
        for match in rx.finditer(content):
            findings.append(
                {
                    "path": str(path),
                    "rule": f"regex:{rx.pattern}",
                    "match_excerpt": match.group(0)[:160],
                }
            )

    for secret in secret_values:
        if secret and secret in content:
            findings.append(
                {
                    "path": str(path),
                    "rule": "env_secret_value_match",
                    "match_excerpt": "***redacted-secret-value***",
                }
            )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan docs/reports/logs for potential secret leakage.")
    parser.add_argument("--include-logs", action="store_true", help="Include data/*/logs files in scan scope.")
    parser.add_argument("--max-file-bytes", type=int, default=5_000_000, help="Skip files larger than this size.")
    args = parser.parse_args()

    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    reports_root = root / "reports" / "security"
    reports_root.mkdir(parents=True, exist_ok=True)

    regexes = [
        re.compile(r"(?i)\b(api[_-]?key|secret|passphrase|token|password)\s*[:=]\s*[^\s]{8,}"),
        re.compile(r"(?i)\bauthorization\s*:\s*bearer\s+[a-z0-9\._\-]{8,}"),
    ]
    env_secret_values = _load_env_secret_values(root)

    scanned_files = 0
    findings: List[Dict[str, object]] = []
    for path in _iter_candidate_files(root, include_logs=bool(args.include_logs)):
        if not _is_probable_text(path):
            continue
        scanned_files += 1
        findings.extend(_scan_file(path, regexes, env_secret_values, max_file_bytes=int(args.max_file_bytes)))

    status = "pass" if not findings else "fail"
    payload = {
        "ts_utc": _utc_now(),
        "status": status,
        "include_logs": bool(args.include_logs),
        "scanned_files": scanned_files,
        "finding_count": len(findings),
        "findings": findings[:200],
    }

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_file = reports_root / f"secrets_hygiene_{stamp}.json"
    out_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (reports_root / "latest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"[secrets-hygiene] status={status}")
    print(f"[secrets-hygiene] scanned_files={scanned_files}")
    print(f"[secrets-hygiene] finding_count={len(findings)}")
    print(f"[secrets-hygiene] evidence={out_file}")
    return 0 if status == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
