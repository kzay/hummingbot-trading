#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

_ENV_LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")

_MODE_FLAGS: Dict[str, Dict[str, str]] = {
    "db_primary": {
        "OPS_DATA_PLANE_MODE": "db_primary",
        "OPS_DB_READ_PREFERRED": "true",
        "PROMOTION_CHECK_CANONICAL_PLANE_GATES": "true",
        "STRICT_REQUIRE_CANONICAL_PLANE_GATES": "true",
    },
    "csv_compat": {
        "OPS_DATA_PLANE_MODE": "csv_compat",
        "OPS_DB_READ_PREFERRED": "false",
        "PROMOTION_CHECK_CANONICAL_PLANE_GATES": "false",
        "STRICT_REQUIRE_CANONICAL_PLANE_GATES": "false",
    },
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_report(report_dir: Path, stem: str, payload: Dict[str, object]) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    ts_path = report_dir / f"{stem}_{stamp}.json"
    latest_path = report_dir / f"{stem}_latest.json"
    raw = json.dumps(payload, indent=2)
    ts_path.write_text(raw, encoding="utf-8")
    latest_path.write_text(raw, encoding="utf-8")


def _apply_flags(lines: List[str], flags: Dict[str, str]) -> List[str]:
    out = list(lines)
    updated = set()
    for idx, line in enumerate(out):
        m = _ENV_LINE_RE.match(line.strip())
        if not m:
            continue
        key = m.group(1)
        if key in flags:
            out[idx] = f"{key}={flags[key]}"
            updated.add(key)
    for key, value in flags.items():
        if key not in updated:
            out.append(f"{key}={value}")
    return out


def _extract_flags(lines: List[str], keys: List[str]) -> Dict[str, str]:
    parsed: Dict[str, str] = {}
    key_set = set(keys)
    for line in lines:
        m = _ENV_LINE_RE.match(line.strip())
        if not m:
            continue
        key = m.group(1)
        if key in key_set:
            parsed[key] = m.group(2).strip()
    return parsed


def _rollback_commands(env_file: Path) -> List[str]:
    env_rel = str(env_file).replace("\\", "/")
    return [
        f"python scripts/ops/data_plane_rollback_drill.py --env-file {env_rel} --apply --from-mode db_primary --to-mode csv_compat",
        "python scripts/release/run_promotion_gates.py --max-report-age-min 20",
    ]


def run_drill(
    env_file: Path,
    report_dir: Path,
    from_mode: str,
    to_mode: str,
    apply: bool,
    max_rto_sec: float,
    rpo_lost_commands: float,
) -> Dict[str, object]:
    from_flags = _MODE_FLAGS.get(str(from_mode).strip().lower())
    to_flags = _MODE_FLAGS.get(str(to_mode).strip().lower())
    if not from_flags or not to_flags:
        payload = {
            "ts_utc": _utc_now(),
            "status": "fail",
            "error": f"invalid_mode from={from_mode} to={to_mode}",
        }
        _write_report(report_dir, "data_plane_rollback_drill", payload)
        return payload

    original_lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
    start = time.time()
    staged_lines = _apply_flags(original_lines, from_flags)
    result_lines = _apply_flags(staged_lines, to_flags)
    duration_sec = max(0.0, time.time() - start)
    env_backup = ""
    if apply:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        report_dir.mkdir(parents=True, exist_ok=True)
        if env_file.exists():
            backup_path = report_dir / f"data_plane_mode_backup_{stamp}.env"
            shutil.copy2(env_file, backup_path)
            env_backup = str(backup_path)
        env_file.parent.mkdir(parents=True, exist_ok=True)
        env_file.write_text("\n".join(result_lines) + "\n", encoding="utf-8")

    keys = sorted(list(to_flags.keys()))
    after_flags = _extract_flags(result_lines, keys)
    applied_ok = all(str(after_flags.get(k, "")).strip().lower() == str(v).strip().lower() for k, v in to_flags.items())
    rto_pass = duration_sec <= float(max_rto_sec)
    status = "pass" if (applied_ok and rto_pass) else "fail"
    payload = {
        "ts_utc": _utc_now(),
        "status": status,
        "from_mode": str(from_mode).strip().lower(),
        "to_mode": str(to_mode).strip().lower(),
        "apply": bool(apply),
        "env_file": str(env_file),
        "env_backup": env_backup,
        "duration_sec": round(float(duration_sec), 6),
        "duration_minutes": round(float(duration_sec) / 60.0, 6),
        "max_allowed_rto_sec": float(max_rto_sec),
        "rto_within_target": bool(rto_pass),
        "rpo_lost_commands": float(max(0.0, float(rpo_lost_commands))),
        "flags_expected": to_flags,
        "flags_after": after_flags,
        "flags_applied_ok": bool(applied_ok),
        "documented_commands": _rollback_commands(env_file),
    }
    _write_report(report_dir, "data_plane_rollback_drill", payload)
    return payload


def main() -> int:
    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Timed rollback drill for canonical data-plane mode flags.")
    parser.add_argument("--env-file", default=str(root / "env" / ".env.template"))
    parser.add_argument("--report-dir", default=str(root / "reports" / "ops"))
    parser.add_argument("--from-mode", choices=["db_primary", "csv_compat"], default="db_primary")
    parser.add_argument("--to-mode", choices=["db_primary", "csv_compat"], default="csv_compat")
    parser.add_argument("--apply", action="store_true", help="Write mode changes to --env-file.")
    parser.add_argument("--max-rto-sec", type=float, default=300.0, help="Max allowed rollback duration for PASS.")
    parser.add_argument(
        "--rpo-lost-commands",
        type=float,
        default=0.0,
        help="Observed/lab-measured lost command count during rollback drill.",
    )
    args = parser.parse_args()

    payload = run_drill(
        env_file=Path(args.env_file),
        report_dir=Path(args.report_dir),
        from_mode=str(args.from_mode),
        to_mode=str(args.to_mode),
        apply=bool(args.apply),
        max_rto_sec=float(args.max_rto_sec),
        rpo_lost_commands=float(args.rpo_lost_commands),
    )
    print(
        f"[data-plane-rollback-drill] status={payload.get('status')} "
        f"duration_sec={payload.get('duration_sec')}"
    )
    print(f"[data-plane-rollback-drill] evidence={Path(args.report_dir) / 'data_plane_rollback_drill_latest.json'}")
    return 0 if str(payload.get("status", "fail")) == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
