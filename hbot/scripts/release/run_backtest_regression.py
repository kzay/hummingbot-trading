from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _read_json(path: Path, default: Dict[str, object]) -> Dict[str, object]:
    if not path.exists():
        return default
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else default
    except Exception:
        return default


def _latest_matching(path: Path, pattern: str) -> Path | None:
    files = sorted(path.glob(pattern))
    if not files:
        return None
    return files[-1]


def _count_events_at_least(path: Path, minimum: int) -> int:
    count = 0
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    count += 1
                    if count >= minimum:
                        return count
    except Exception:
        return 0
    return count


def _latest_events_with_min(path: Path, minimum: int) -> Path | None:
    files = sorted(path.glob("events_*.jsonl"), reverse=True)
    for fp in files:
        if _count_events_at_least(fp, minimum) >= minimum:
            return fp
    return files[0] if files else None


def _matching_integrity_for_event(event_file: Path | None, event_store_dir: Path) -> Path | None:
    if not event_file:
        return _latest_matching(event_store_dir, "integrity_*.json")
    suffix = event_file.name.replace("events_", "").replace(".jsonl", "")
    candidate = event_store_dir / f"integrity_{suffix}.json"
    if candidate.exists():
        return candidate
    return _latest_matching(event_store_dir, "integrity_*.json")


def _fingerprint_event_file(path: Path, sample_size: int = 200) -> Dict[str, object]:
    if not path.exists():
        return {"ok": False, "event_count": 0, "fingerprint": "", "first_event_ids": [], "first_event_types": []}

    event_count = 0
    first_ids: List[str] = []
    first_types: List[str] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                event_count += 1
                if len(first_ids) < sample_size:
                    try:
                        event = json.loads(line)
                    except Exception:
                        continue
                    first_ids.append(str(event.get("event_id", "")))
                    first_types.append(str(event.get("event_type", "")))
    except Exception:
        return {"ok": False, "event_count": event_count, "fingerprint": "", "first_event_ids": [], "first_event_types": []}

    raw = json.dumps({"event_count": event_count, "ids": first_ids, "types": first_types}, separators=(",", ":"))
    fp = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return {"ok": True, "event_count": event_count, "fingerprint": fp, "first_event_ids": first_ids[:10], "first_event_types": first_types[:10]}


def _scan_invariants(path: Path) -> Dict[str, object]:
    stats = {
        "execution_intent_count": 0,
        "risk_decision_count": 0,
        "intent_missing_expiry_count": 0,
        "risk_denied_missing_reason_count": 0,
    }
    if not path.exists():
        return stats

    expiry_required_actions = {"soft_pause", "kill_switch", "set_target_base_pct"}
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except Exception:
                    continue
                event_type = str(event.get("event_type", "")).strip()
                payload = event.get("payload", {}) if isinstance(event.get("payload"), dict) else {}
                if event_type == "execution_intent":
                    stats["execution_intent_count"] += 1
                    action = str(payload.get("action", "")).strip().lower()
                    if action in expiry_required_actions and payload.get("expires_at_ms") in (None, ""):
                        stats["intent_missing_expiry_count"] += 1
                elif event_type == "risk_decision":
                    stats["risk_decision_count"] += 1
                    approved = payload.get("approved", True)
                    reason = str(payload.get("reason", "")).strip()
                    if approved is False and not reason:
                        stats["risk_denied_missing_reason_count"] += 1
    except Exception:
        return stats
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic regression harness.")
    parser.add_argument("--min-events", type=int, default=1000, help="Minimum required events in dataset.")
    parser.add_argument("--sample-size", type=int, default=200, help="Event sample size used for fingerprint.")
    parser.add_argument(
        "--event-file",
        type=str,
        default="",
        help="Optional explicit event file path to pin deterministic input.",
    )
    parser.add_argument(
        "--integrity-file",
        type=str,
        default="",
        help="Optional explicit integrity file path to pin deterministic input.",
    )
    args = parser.parse_args()

    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    event_store_dir = root / "reports" / "event_store"
    event_file = (
        Path(args.event_file)
        if args.event_file
        else _latest_events_with_min(event_store_dir, minimum=max(1, int(args.min_events)))
    )
    integrity_file = (
        Path(args.integrity_file)
        if args.integrity_file
        else _matching_integrity_for_event(event_file, event_store_dir)
    )
    reports_root = root / "reports" / "backtest_regression"
    reports_root.mkdir(parents=True, exist_ok=True)

    fp = _fingerprint_event_file(event_file, sample_size=max(10, args.sample_size)) if event_file else {"ok": False, "event_count": 0, "fingerprint": "", "first_event_ids": [], "first_event_types": []}
    inv = _scan_invariants(event_file)
    integrity = _read_json(integrity_file, {}) if integrity_file else {}
    missing_corr = int(integrity.get("missing_correlation_count", 0))

    checks = [
        {
            "name": "event_count_min",
            "pass": int(fp.get("event_count", 0)) >= int(args.min_events),
            "value": int(fp.get("event_count", 0)),
            "required": int(args.min_events),
        },
        {
            "name": "missing_correlation_zero",
            "pass": missing_corr == 0,
            "value": missing_corr,
            "required": 0,
        },
        {
            "name": "dataset_fingerprint_present",
            "pass": bool(fp.get("ok")) and bool(fp.get("fingerprint")),
            "value": fp.get("fingerprint", ""),
            "required": "non_empty_sha256",
        },
        {
            "name": "intent_expiry_present_for_active_actions",
            "pass": int(inv.get("intent_missing_expiry_count", 0)) == 0,
            "value": int(inv.get("intent_missing_expiry_count", 0)),
            "required": 0,
        },
        {
            "name": "risk_denied_reason_present",
            "pass": int(inv.get("risk_denied_missing_reason_count", 0)) == 0,
            "value": int(inv.get("risk_denied_missing_reason_count", 0)),
            "required": 0,
        },
    ]
    status = "pass" if all(bool(c.get("pass")) for c in checks) else "fail"
    payload = {
        "ts_utc": _utc_now(),
        "status": status,
        "event_file": str(event_file) if event_file else "",
        "integrity_file": str(integrity_file) if integrity_file else "",
        "checks": checks,
        "dataset_fingerprint": {
            "sha256": fp.get("fingerprint", ""),
            "event_count": int(fp.get("event_count", 0)),
            "sample_event_ids": fp.get("first_event_ids", []),
            "sample_event_types": fp.get("first_event_types", []),
        },
        "invariants": inv,
    }

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = reports_root / f"backtest_regression_{stamp}.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (reports_root / "latest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
