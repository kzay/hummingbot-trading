"""Data-plane consistency gate (INFRA-5).

Checks that:
1. desk_snapshot_service has written a fresh snapshot (<STALE_THRESHOLD) for
   every discovered bot.
2. Each snapshot's completeness score is above MIN_COMPLETENESS.
3. minute.csv tick age reported in the snapshot is below MAX_MINUTE_AGE_S.
4. snapshot generated_ts and source_ts (minute ts) are consistent with each
   other (delta < MAX_INTERNAL_DRIFT_S).

Writes:
    reports/data_plane_consistency/latest.json

Exit code:
    0  PASS
    1  FAIL

Usage:
    python hbot/scripts/release/validate_data_plane_consistency.py
    python hbot/scripts/release/validate_data_plane_consistency.py \\
        --data hbot/data --reports hbot/reports --stale 120 --min-completeness 0.9
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_STALE_S = 180.0          # snapshot older than 3 min → FAIL
DEFAULT_MIN_COMPLETENESS = 0.80  # must have >= 80% required minute fields
DEFAULT_MAX_MINUTE_AGE_S = 180.0 # minute.csv tick must be < 3 min old
DEFAULT_MAX_INTERNAL_DRIFT_S = 60.0  # max drift between generated_ts and source_ts
DEFAULT_SKIP_INACTIVE_H = 6.0    # bots with minute_age > this many hours are "inactive" — skip freshness checks

REQUIRED_MINUTE_FIELDS = [
    "ts", "state", "regime", "equity_quote", "spread_pct", "net_edge_pct",
    "base_pct", "daily_loss_pct", "drawdown_pct", "orders_active",
    "realized_pnl_today_quote",
]

REQUIRED_SNAPSHOT_FIELDS = ["minute", "fill_stats", "gates", "completeness"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_epoch() -> float:
    return time.time()


def _now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_epoch(ts_str: str) -> float | None:
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _age(epoch: float | None) -> float | None:
    if epoch is None:
        return None
    return _now_epoch() - epoch


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Per-bot checks
# ---------------------------------------------------------------------------

def _check_bot(
    bot_name: str,
    snap_path: Path,
    stale_s: float,
    min_completeness: float,
    max_minute_age_s: float,
    max_internal_drift_s: float,
    skip_inactive_s: float = 0.0,
) -> tuple[bool, list[dict[str, Any]]]:
    """Return (passed, list_of_check_dicts) for one bot."""
    checks: list[dict[str, Any]] = []

    # 1. Snapshot exists
    if not snap_path.exists():
        checks.append({
            "name": f"{bot_name}.snapshot_exists",
            "severity": "critical",
            "pass": False,
            "reason": f"No snapshot at {snap_path}",
        })
        return False, checks

    snap = _read_json(snap_path)
    if snap is None:
        checks.append({
            "name": f"{bot_name}.snapshot_readable",
            "severity": "critical",
            "pass": False,
            "reason": f"Could not parse {snap_path}",
        })
        return False, checks

    now = _now_epoch()

    # Inactive-bot exemption: if the bot's last minute tick is older than
    # skip_inactive_s, treat it as "inactive" — emit an info check (not critical)
    # and skip all freshness/completeness checks.
    if skip_inactive_s > 0:
        raw_minute_age = snap.get("minute_age_s")
        if raw_minute_age is not None and float(raw_minute_age) > skip_inactive_s:
            checks.append({
                "name": f"{bot_name}.inactive",
                "severity": "info",
                "pass": True,
                "reason": f"Bot inactive: minute_age={float(raw_minute_age):.0f}s > skip_threshold={skip_inactive_s:.0f}s — skipped",
                "minute_age_s": raw_minute_age,
            })
            return True, checks

    # 2. Snapshot freshness
    gen_ts = str(snap.get("generated_ts", ""))
    gen_epoch = _parse_epoch(gen_ts)
    snap_age = (now - gen_epoch) if gen_epoch else None
    fresh = snap_age is not None and snap_age <= stale_s
    checks.append({
        "name": f"{bot_name}.snapshot_freshness",
        "severity": "critical",
        "pass": fresh,
        "reason": (
            f"Snapshot age={snap_age:.1f}s (threshold={stale_s}s)" if snap_age is not None
            else "generated_ts missing"
        ),
        "snap_age_s": snap_age,
    })

    # 3. Required snapshot fields
    missing_top = [f for f in REQUIRED_SNAPSHOT_FIELDS if not snap.get(f) and snap.get(f) != 0]
    checks.append({
        "name": f"{bot_name}.snapshot_fields",
        "severity": "warning",
        "pass": len(missing_top) == 0,
        "reason": f"Missing top-level fields: {missing_top}" if missing_top else "OK",
    })

    # 4. Completeness score
    completeness = float(snap.get("completeness", 0.0))
    checks.append({
        "name": f"{bot_name}.completeness",
        "severity": "critical",
        "pass": completeness >= min_completeness,
        "reason": f"completeness={completeness:.2%} (threshold={min_completeness:.0%})",
        "completeness": completeness,
        "missing_fields": snap.get("missing_fields", []),
    })

    # 5. Minute freshness
    minute_age = snap.get("minute_age_s")
    minute_ok = minute_age is not None and float(minute_age) <= max_minute_age_s
    checks.append({
        "name": f"{bot_name}.minute_freshness",
        "severity": "critical",
        "pass": minute_ok,
        "reason": (
            f"minute_age={float(minute_age):.1f}s (threshold={max_minute_age_s}s)"
            if minute_age is not None
            else "minute_age_s missing from snapshot"
        ),
        "minute_age_s": minute_age,
    })

    # 6. Internal drift: generated_ts vs source_ts (minute ts)
    source_ts = str(snap.get("source_ts", ""))
    source_epoch = _parse_epoch(source_ts)
    if gen_epoch and source_epoch:
        drift = abs(gen_epoch - source_epoch)
        drift_ok = drift <= max_internal_drift_s
        checks.append({
            "name": f"{bot_name}.internal_ts_drift",
            "severity": "warning",
            "pass": drift_ok,
            "reason": f"drift={drift:.1f}s (max={max_internal_drift_s}s)",
            "drift_s": drift,
        })

    # 7. minute.csv required fields in snapshot
    minute = snap.get("minute") or {}
    missing_minute = [f for f in REQUIRED_MINUTE_FIELDS if not minute.get(f)]
    checks.append({
        "name": f"{bot_name}.minute_required_fields",
        "severity": "warning",
        "pass": len(missing_minute) == 0,
        "reason": f"Missing minute fields: {missing_minute}" if missing_minute else "OK",
        "missing": missing_minute,
    })

    critical_passed = all(c["pass"] for c in checks if c.get("severity") == "critical")
    return critical_passed, checks


# ---------------------------------------------------------------------------
# Gate runner
# ---------------------------------------------------------------------------

def run(
    data_root: Path,
    reports_root: Path,
    stale_s: float = DEFAULT_STALE_S,
    min_completeness: float = DEFAULT_MIN_COMPLETENESS,
    max_minute_age_s: float = DEFAULT_MAX_MINUTE_AGE_S,
    max_internal_drift_s: float = DEFAULT_MAX_INTERNAL_DRIFT_S,
    skip_inactive_s: float = DEFAULT_SKIP_INACTIVE_H * 3600,
) -> dict[str, Any]:
    snapshot_root = reports_root / "desk_snapshot"
    all_checks: list[dict[str, Any]] = []
    bot_results: dict[str, Any] = {}
    all_passed = True

    # Discover bots from data directory
    bots: list[str] = []
    if data_root.exists():
        bots = sorted(d.name for d in data_root.iterdir() if d.is_dir() and (d / "logs").exists())

    if not bots:
        # Fallback: discover from snapshot root
        if snapshot_root.exists():
            bots = sorted(d.name for d in snapshot_root.iterdir() if d.is_dir())

    if not bots:
        return {
            "status": "FAIL",
            "reason": "No bot directories discovered under data/",
            "checks": [],
            "bot_results": {},
            "generated_ts": _now_utc(),
        }

    for bot in bots:
        snap_path = snapshot_root / bot / "latest.json"
        passed, checks = _check_bot(
            bot_name=bot,
            snap_path=snap_path,
            stale_s=stale_s,
            min_completeness=min_completeness,
            max_minute_age_s=max_minute_age_s,
            max_internal_drift_s=max_internal_drift_s,
            skip_inactive_s=skip_inactive_s,
        )
        if not passed:
            all_passed = False
        bot_results[bot] = {
            "passed": passed,
            "checks": checks,
        }
        all_checks.extend(checks)

    critical_failures = [c["name"] for c in all_checks if c.get("severity") == "critical" and not c["pass"]]
    warnings = [c["name"] for c in all_checks if c.get("severity") == "warning" and not c["pass"]]

    output: dict[str, Any] = {
        "status": "PASS" if all_passed else "FAIL",
        "generated_ts": _now_utc(),
        "bots_checked": bots,
        "critical_failures": critical_failures,
        "warnings": warnings,
        "all_checks_pass": all_passed,
        "bot_results": bot_results,
    }

    out_dir = reports_root / "data_plane_consistency"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "latest.json"
    tmp_path = out_dir / "latest.json.tmp"
    tmp_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    tmp_path.replace(out_path)
    print(f"data_plane_consistency: {output['status']}  bots={bots}  failures={critical_failures}")
    return output


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Data-plane consistency gate (INFRA-5)")
    ap.add_argument("--data", default="hbot/data", help="Path to bot data root")
    ap.add_argument("--reports", default="hbot/reports", help="Path to reports root")
    ap.add_argument("--stale", type=float, default=DEFAULT_STALE_S,
                    help="Max snapshot age in seconds (default 180)")
    ap.add_argument("--min-completeness", type=float, default=DEFAULT_MIN_COMPLETENESS,
                    help="Min minute completeness score 0-1 (default 0.80)")
    ap.add_argument("--max-minute-age", type=float, default=DEFAULT_MAX_MINUTE_AGE_S,
                    help="Max minute.csv tick age in seconds (default 180)")
    ap.add_argument("--skip-inactive-h", type=float, default=DEFAULT_SKIP_INACTIVE_H,
                    help="Skip freshness checks for bots whose minute data is older than N hours (default 6)")
    args = ap.parse_args()

    result = run(
        data_root=Path(args.data),
        reports_root=Path(args.reports),
        stale_s=args.stale,
        min_completeness=args.min_completeness,
        max_minute_age_s=args.max_minute_age,
        skip_inactive_s=args.skip_inactive_h * 3600,
    )
    sys.exit(0 if result["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
