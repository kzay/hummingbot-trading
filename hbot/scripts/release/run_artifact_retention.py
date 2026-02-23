from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _root() -> Path:
    return Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]


def _read_json(path: Path, default: Dict[str, object]) -> Dict[str, object]:
    if not path.exists():
        return default
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else default
    except Exception:
        return default


def _age_days(path: Path) -> float:
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - mtime).total_seconds() / 86400.0)


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply/report artifact retention policy.")
    parser.add_argument(
        "--policy-path",
        type=str,
        default="config/artifact_retention_policy.json",
        help="Retention policy JSON path.",
    )
    parser.add_argument("--apply", action="store_true", help="Delete expired artifacts.")
    args = parser.parse_args()

    root = _root()
    policy_path = root / args.policy_path
    policy = _read_json(policy_path, {})
    rules = policy.get("rules", []) if isinstance(policy.get("rules"), list) else []
    protected = {
        str((root / p).resolve())
        for p in (policy.get("protect_latest", []) if isinstance(policy.get("protect_latest"), list) else [])
    }

    candidates = 0
    expired = 0
    deleted = 0
    by_rule: List[Dict[str, object]] = []
    deletions: List[str] = []

    for rule in rules:
        if not isinstance(rule, dict):
            continue
        name = str(rule.get("name", "unknown"))
        glob_expr = str(rule.get("glob", "")).strip()
        keep_days = int(rule.get("keep_days", 30))
        if not glob_expr:
            continue

        matched = list(root.glob(glob_expr))
        matched_files = [p for p in matched if p.is_file()]
        rule_expired: List[Path] = []
        for p in matched_files:
            candidates += 1
            if str(p.resolve()) in protected:
                continue
            if _age_days(p) > float(keep_days):
                expired += 1
                rule_expired.append(p)

        deleted_count = 0
        if args.apply:
            for p in rule_expired:
                try:
                    os.remove(p)
                    deleted_count += 1
                    deleted += 1
                    deletions.append(str(p))
                except Exception:
                    pass

        by_rule.append(
            {
                "name": name,
                "glob": glob_expr,
                "keep_days": keep_days,
                "matched_files": len(matched_files),
                "expired_files": len(rule_expired),
                "deleted_files": deleted_count,
            }
        )

    out_dir = root / "reports" / "ops_retention"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    payload = {
        "ts_utc": _utc_now(),
        "mode": "apply" if args.apply else "dry_run",
        "policy_path": str(policy_path),
        "candidates": candidates,
        "expired": expired,
        "deleted": deleted,
        "rules": by_rule,
        "deleted_paths_sample": deletions[:200],
    }
    out = out_dir / f"artifact_retention_{stamp}.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (out_dir / "latest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"[artifact-retention] mode={payload['mode']}")
    print(f"[artifact-retention] expired={expired} deleted={deleted}")
    print(f"[artifact-retention] evidence={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
