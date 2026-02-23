from __future__ import annotations

import argparse
import json
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


def _fmt_list(items: List[str]) -> str:
    if not items:
        return "- (none)"
    return "\n".join(f"- {x}" for x in items)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate daily ops report from latest gate artifacts.")
    parser.add_argument("--date", default=_today(), help="UTC date label YYYYMMDD for output file naming.")
    args = parser.parse_args()

    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    reports = root / "reports"
    docs_ops = root / "docs" / "ops"
    docs_ops.mkdir(parents=True, exist_ok=True)

    day2 = _read_json(reports / "event_store" / "day2_gate_eval_latest.json", {})
    recon = _read_json(reports / "reconciliation" / "latest.json", {})
    parity = _read_json(reports / "parity" / "latest.json", {})
    risk = _read_json(reports / "portfolio_risk" / "latest.json", {})
    strict_cycle = _read_json(reports / "promotion_gates" / "strict_cycle_latest.json", {})
    soak = _read_json(reports / "soak" / "latest.json", {})

    day2_go = bool(day2.get("go", False))
    strict_status = str(strict_cycle.get("strict_gate_status", "UNKNOWN")).upper()
    strict_failures = strict_cycle.get("critical_failures", [])
    strict_failures = strict_failures if isinstance(strict_failures, list) else []
    soak_status = str(soak.get("status", "unknown"))
    blockers = soak.get("blockers", [])
    blockers = blockers if isinstance(blockers, list) else []

    report_md = f"""# Daily Ops Report {args.date}

## 1) What was changed
- Automated daily report generated from latest runtime/gate artifacts.
- No strategy/controller logic changed in this report cycle.

## 2) Files/services touched
- Generated file: `docs/ops/daily_ops_report_{args.date}.md`
- Data sources:
  - `reports/event_store/day2_gate_eval_latest.json`
  - `reports/reconciliation/latest.json`
  - `reports/parity/latest.json`
  - `reports/portfolio_risk/latest.json`
  - `reports/promotion_gates/strict_cycle_latest.json`
  - `reports/soak/latest.json`

## 3) Validation performed
- Day2 gate evaluated (latest snapshot consumed)
- Reconciliation status consumed
- Parity status consumed
- Portfolio risk status consumed
- Strict cycle status consumed
- Aggregated soak status consumed

## 4) Metrics before/after
- Day2 GO: `{day2_go}`
- Day2 checks:
  - `{day2.get("checks", [])}`
- Reconciliation: `status={recon.get("status", "unknown")}`, `critical_count={recon.get("critical_count", "n/a")}`
- Parity: `status={parity.get("status", "unknown")}`, `failed_bots={parity.get("failed_bots", "n/a")}`
- Portfolio risk: `status={risk.get("status", "unknown")}`, `critical_count={risk.get("critical_count", "n/a")}`
- Strict cycle: `status={strict_status}`, `rc={strict_cycle.get("strict_gate_rc", "n/a")}`
- Soak monitor: `status={soak_status}`

## 5) Incidents/risks
- Strict-cycle critical failures:
{_fmt_list([str(x) for x in strict_failures])}
- Aggregated blockers:
{_fmt_list([str(x) for x in blockers])}

## 6) Rollback status
- No rollback action required for this reporting cycle.
- Existing rollback safety remains unchanged (promotion blocked when strict cycle is FAIL).

## 7) Next day top 3 tasks
- Keep monitors running and collect additional soak evidence snapshots.
- Re-run strict cycle after Day2 elapsed window advances.
- If strict cycle PASS is achieved, update readiness decision from provisional HOLD to final GO/NO-GO.

---
Generated at: `{_utc_now()}`
"""

    out = docs_ops / f"daily_ops_report_{args.date}.md"
    out.write_text(report_md, encoding="utf-8")
    print(str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
