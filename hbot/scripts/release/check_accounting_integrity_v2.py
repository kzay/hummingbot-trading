from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


REQUIRED_FIELDS = [
    "bot",
    "exchange",
    "trading_pair",
    "mid",
    "equity_quote",
    "base_balance",
    "quote_balance",
    "fees_paid_today_quote",
    "funding_paid_today_quote",
    "daily_loss_pct",
    "drawdown_pct",
    "fee_source",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _minutes_since(ts: str) -> float:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).total_seconds() / 60.0
    except Exception:
        return 1e9


def _write(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check accounting integrity signals from reconciliation artifacts.")
    parser.add_argument("--max-age-min", type=float, default=20.0, help="Maximum report age in minutes.")
    args = parser.parse_args()

    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    recon_path = root / "reports" / "reconciliation" / "latest.json"
    recon = _read_json(recon_path)

    ts_utc = str(recon.get("ts_utc", "")).strip()
    age_min = _minutes_since(ts_utc)
    fresh = bool(ts_utc) and age_min <= float(args.max_age_min)

    snapshots = recon.get("accounting_snapshots", [])
    snapshots = snapshots if isinstance(snapshots, list) else []
    missing_field_rows: List[Dict[str, object]] = []
    for idx, row in enumerate(snapshots):
        if not isinstance(row, dict):
            missing_field_rows.append({"index": idx, "missing": ["<row_not_object>"]})
            continue
        missing = [f for f in REQUIRED_FIELDS if f not in row]
        if missing:
            missing_field_rows.append({"index": idx, "bot": row.get("bot", ""), "missing": missing})

    findings = recon.get("findings", [])
    findings = findings if isinstance(findings, list) else []
    critical_accounting_findings = [
        f
        for f in findings
        if isinstance(f, dict)
        and str(f.get("check", "")).strip() == "accounting"
        and str(f.get("severity", "")).strip().lower() == "critical"
    ]

    non_negative = True
    for row in snapshots:
        if not isinstance(row, dict):
            non_negative = False
            break
        fees = float(row.get("fees_paid_today_quote", 0.0) or 0.0)
        funding = float(row.get("funding_paid_today_quote", 0.0) or 0.0)
        if fees < -1e-9 or funding < -1e-9:
            non_negative = False
            break

    checks = {
        "reconciliation_fresh": bool(fresh),
        "snapshots_present": len(snapshots) > 0,
        "required_fields_present": len(missing_field_rows) == 0,
        "no_critical_accounting_findings": len(critical_accounting_findings) == 0,
        "fees_funding_non_negative": bool(non_negative),
    }
    status = "pass" if all(checks.values()) else "fail"

    payload = {
        "ts_utc": _utc_now(),
        "status": status,
        "max_age_min": float(args.max_age_min),
        "reconciliation_path": str(recon_path),
        "reconciliation_ts_utc": ts_utc,
        "reconciliation_age_min": round(age_min, 3),
        "snapshot_count": len(snapshots),
        "critical_accounting_finding_count": len(critical_accounting_findings),
        "missing_field_rows": missing_field_rows,
        "checks": checks,
    }

    out_dir = root / "reports" / "accounting"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = out_dir / f"accounting_integrity_{stamp}.json"
    _write(out, payload)
    _write(out_dir / "latest.json", payload)
    print(f"[accounting-integrity] status={status}")
    print(f"[accounting-integrity] evidence={out}")
    return 0 if status == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
