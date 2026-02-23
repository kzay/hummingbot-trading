from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

try:
    import redis  # type: ignore
except Exception as exc:  # pragma: no cover
    raise RuntimeError("redis package is required. Install with `python -m pip install redis`.") from exc


STREAMS = (
    "hb.market_data.v1",
    "hb.signal.v1",
    "hb.ml_signal.v1",
    "hb.risk_decision.v1",
    "hb.execution_intent.v1",
    "hb.audit.v1",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path, default: Dict[str, object]) -> Dict[str, object]:
    if not path.exists():
        return default
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else default
    except Exception:
        return default


def _latest_integrity_file(reports_dir: Path) -> Path | None:
    files = sorted(reports_dir.glob("integrity_*.json"))
    return files[-1] if files else None


def _write_json(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Safely reset event-store baseline_counts.json to current source/stored counters."
    )
    parser.add_argument("--reason", default="manual_reanchor", help="Reason for baseline reset (written to audit).")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Apply reset. Without --force, script runs in dry-run mode and only writes preview.",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    reports_dir = root / "reports" / "event_store"
    reports_dir.mkdir(parents=True, exist_ok=True)

    baseline_path = reports_dir / "baseline_counts.json"
    baseline_before = _load_json(baseline_path, {})
    latest_integrity_path = _latest_integrity_file(reports_dir)
    integrity = (
        _load_json(latest_integrity_path, {"events_by_stream": {}})
        if latest_integrity_path
        else {"events_by_stream": {}}
    )
    stored_by_stream_raw = integrity.get("events_by_stream", {})
    stored_by_stream = (
        {k: int(stored_by_stream_raw.get(k, 0)) for k in STREAMS}
        if isinstance(stored_by_stream_raw, dict)
        else {k: 0 for k in STREAMS}
    )

    client = redis.Redis(
        host=os.getenv("REDIS_HOST", "127.0.0.1"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        db=int(os.getenv("REDIS_DB", "0")),
        password=os.getenv("REDIS_PASSWORD", "") or None,
        decode_responses=True,
    )
    source_by_stream = {stream: int(client.xlen(stream)) for stream in STREAMS}

    baseline_after = {
        "created_at_utc": _utc_now(),
        "reason": str(args.reason),
        "source_by_stream": source_by_stream,
        "stored_by_stream": stored_by_stream,
        "integrity_file": str(latest_integrity_path) if latest_integrity_path else "",
    }

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    preview_path = reports_dir / f"baseline_reset_preview_{stamp}.json"
    backup_path = reports_dir / f"baseline_counts_backup_{stamp}.json"
    apply_report_path = reports_dir / f"baseline_reset_apply_{stamp}.json"

    _write_json(
        preview_path,
        {
            "ts_utc": _utc_now(),
            "mode": "preview" if not args.force else "apply",
            "reason": str(args.reason),
            "baseline_before": baseline_before,
            "baseline_after": baseline_after,
            "baseline_file": str(baseline_path),
            "integrity_file": str(latest_integrity_path) if latest_integrity_path else "",
        },
    )

    if args.force:
        if baseline_before:
            _write_json(backup_path, baseline_before)
        _write_json(baseline_path, baseline_after)
        _write_json(
            apply_report_path,
            {
                "ts_utc": _utc_now(),
                "status": "applied",
                "reason": str(args.reason),
                "baseline_file": str(baseline_path),
                "backup_file": str(backup_path) if baseline_before else "",
                "preview_file": str(preview_path),
            },
        )

    print(f"[baseline-reset] mode={'apply' if args.force else 'preview'}")
    print(f"[baseline-reset] preview={preview_path}")
    if args.force:
        print(f"[baseline-reset] baseline_file={baseline_path}")
        if baseline_before:
            print(f"[baseline-reset] backup={backup_path}")
        print(f"[baseline-reset] apply_report={apply_report_path}")


if __name__ == "__main__":
    main()
