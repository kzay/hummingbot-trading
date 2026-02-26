from __future__ import annotations

import glob
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _latest_source_compare(path: Path) -> Path | None:
    files = sorted(glob.glob(str(path / "source_compare_*.json")))
    if not files:
        return None
    return Path(files[-1])


def _latest_integrity(path: Path) -> Path | None:
    files = sorted(glob.glob(str(path / "integrity_*.json")))
    if not files:
        return None
    return Path(files[-1])


def _refresh_integrity(root: Path) -> None:
    """Run the local integrity refresh script before evaluating to prevent stale-state false failures."""
    import subprocess
    import sys
    refresh_script = root / "scripts" / "utils" / "refresh_event_store_integrity_local.py"
    if not refresh_script.exists():
        return
    try:
        subprocess.run(
            [sys.executable, str(refresh_script)],
            capture_output=True, timeout=30,
        )
    except Exception:
        pass  # Non-fatal — gate evaluation proceeds with whatever integrity file exists


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    reports = root / "reports" / "event_store"
    reports.mkdir(parents=True, exist_ok=True)

    # Always refresh local integrity snapshot first so the delta check uses
    # up-to-date counts rather than a potentially hours-old snapshot.
    if os.getenv("DAY2_GATE_SKIP_INTEGRITY_REFRESH", "").lower() not in ("1", "true", "yes"):
        _refresh_integrity(root)

    gate_hours = float(os.getenv("DAY2_GATE_MIN_HOURS", "24"))
    max_allowed_delta = int(os.getenv("DAY2_GATE_MAX_DELTA", "5"))

    baseline = _load_json(reports / "baseline_counts.json", {})
    latest_integrity_path = _latest_integrity(reports)
    integrity = _load_json(latest_integrity_path, {"missing_correlation_count": 999999}) if latest_integrity_path else {"missing_correlation_count": 999999}
    latest_compare_path = _latest_source_compare(reports)
    latest_compare = _load_json(latest_compare_path, {}) if latest_compare_path else {}

    baseline_created = baseline.get("created_at_utc")
    elapsed_hours = 0.0
    if isinstance(baseline_created, str) and baseline_created:
        try:
            started = datetime.fromisoformat(baseline_created.replace("Z", "+00:00"))
            elapsed_hours = (_utc_now() - started).total_seconds() / 3600.0
        except Exception:
            elapsed_hours = 0.0

    missing_corr = int(integrity.get("missing_correlation_count", 0))
    delta_since = latest_compare.get("delta_produced_minus_ingested_since_baseline", {})
    if not isinstance(delta_since, dict):
        delta_since = {}
    max_delta_observed = max([abs(int(v)) for v in delta_since.values()] or [0])

    checks: List[Dict[str, object]] = []
    checks.append({"name": "elapsed_window", "pass": elapsed_hours >= gate_hours, "value_hours": round(elapsed_hours, 2), "required_hours": gate_hours})
    checks.append({"name": "missing_correlation", "pass": missing_corr == 0, "value": missing_corr, "required": 0})
    checks.append(
        {
            "name": "delta_since_baseline_tolerance",
            "pass": max_delta_observed <= max_allowed_delta,
            "max_delta_observed": max_delta_observed,
            "max_allowed_delta": max_allowed_delta,
        }
    )

    go = all(bool(c.get("pass")) for c in checks)
    result = {
        "ts_utc": _utc_now().isoformat(),
        "go": go,
        "gate": "day2_event_store",
        "baseline_file": str(reports / "baseline_counts.json"),
        "integrity_file": str(latest_integrity_path) if latest_integrity_path else "",
        "source_compare_file": str(latest_compare_path) if latest_compare_path else "",
        "checks": checks,
    }
    out = reports / "day2_gate_eval_latest.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(str(out))


if __name__ == "__main__":
    main()
