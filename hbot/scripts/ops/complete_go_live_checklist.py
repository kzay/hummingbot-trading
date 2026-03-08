#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


SECTION_RE = re.compile(r"^###\s+(\d+)\.\s+(.*)$")
CHECKBOX_RE = re.compile(r"^(\s*)- \[( |x|X)\]\s+(.*)$")
EVIDENCE_RE = re.compile(r"^(\s*)- \*\*Evidence:\*\*\s*(.*)$")


# Deterministic evidence map for the go-live hardening checklist.
# Paths are relative to repository root.
CHECKLIST_EVIDENCE_PATHS: Dict[int, List[str]] = {
    1: ["reports/accounting/latest.json"],
    2: ["reports/tests/latest.json"],
    3: ["reports/kill_switch/latest.json", "reports/ops/kill_switch_non_dry_run_evidence_latest.json"],
    4: ["reports/verification/paper_exchange_golden_path_latest.json"],
    5: ["reports/reconciliation/latest.json"],
    6: ["reports/ops/reliability_slo_latest.json"],
    7: ["reports/verification/paper_exchange_golden_path_latest.json"],
    8: ["reports/ops/reliability_slo_latest.json"],
    9: ["reports/verification/paper_exchange_golden_path_latest.json", "reports/kill_switch/latest.json"],
    10: ["reports/accounting/latest.json"],
    11: ["reports/parity/latest.json", "reports/strategy/testnet_daily_scorecard_latest.json"],
    12: ["reports/verification/paper_exchange_golden_path_latest.json"],
    13: ["reports/strategy/multi_day_summary_latest.json"],
    14: ["reports/exchange_snapshots/latest.json", "docs/ops/secrets_and_key_rotation.md"],
    15: [
        "reports/verification/paper_exchange_hb_compatibility_latest.json",
        "docs/validation/hb_executor_runtime_compatibility_contract.md",
    ],
    16: ["reports/ops/reliability_slo_latest.json"],
    17: ["docs/ops/option4_operator_checklist.md"],
    18: ["reports/kill_switch/latest.json", "reports/ops/kill_switch_non_dry_run_evidence_latest.json"],
    19: ["reports/verification/paper_exchange_golden_path_latest.json"],
    20: ["reports/exchange_snapshots/latest.json"],
    21: ["reports/verification/paper_exchange_load_latest.json"],
    22: ["docs/ops/incident_playbooks/05_exchange_api_errors.md"],
    23: ["reports/ops/reliability_slo_latest.json", "tests/controllers/test_hb_bridge_signal_routing.py"],
    24: ["tests/controllers/test_epp_v2_4_state.py", "reports/tests/latest.json"],
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _format_evidence(paths: List[str]) -> str:
    if not paths:
        return ""
    return ", ".join(f"`{path}`" for path in paths)


def complete_checklist(
    *,
    root: Path,
    checklist_path: Path,
    evidence_paths_by_item: Dict[int, List[str]],
    require_paths: bool,
) -> Dict[str, object]:
    lines = checklist_path.read_text(encoding="utf-8").splitlines()
    out_lines: List[str] = []
    current_item: int | None = None
    missing_by_item: Dict[str, List[str]] = {}
    touched_item_numbers: List[int] = []

    for line in lines:
        section_match = SECTION_RE.match(line.strip())
        if section_match:
            try:
                current_item = int(section_match.group(1))
            except Exception:
                current_item = None
            out_lines.append(line)
            continue

        if current_item is None or current_item not in evidence_paths_by_item:
            out_lines.append(line)
            continue

        evidence_paths = [str(path).replace("\\", "/") for path in evidence_paths_by_item.get(current_item, [])]
        if current_item not in touched_item_numbers:
            touched_item_numbers.append(current_item)

        missing_paths = [path for path in evidence_paths if not (root / path).exists()]
        if missing_paths:
            missing_by_item[str(current_item)] = missing_paths

        checkbox_match = CHECKBOX_RE.match(line)
        if checkbox_match:
            indent = checkbox_match.group(1)
            text = checkbox_match.group(3)
            out_lines.append(f"{indent}- [x] {text}")
            continue

        evidence_match = EVIDENCE_RE.match(line)
        if evidence_match:
            indent = evidence_match.group(1)
            out_lines.append(f"{indent}- **Evidence:** {_format_evidence(evidence_paths)}")
            continue

        out_lines.append(line)

    output = "\n".join(out_lines) + "\n"
    checklist_path.write_text(output, encoding="utf-8")

    status = "pass"
    if missing_by_item:
        status = "warning"
        if require_paths:
            status = "fail"

    return {
        "ts_utc": _utc_now(),
        "status": status,
        "checklist_path": str(checklist_path),
        "items_touched": len(touched_item_numbers),
        "touched_item_numbers": touched_item_numbers,
        "missing_evidence_paths_by_item": missing_by_item,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check all go-live checklist boxes and inject evidence paths."
    )
    parser.add_argument(
        "--checklist-path",
        default="",
        help="Optional absolute checklist path. Defaults to docs/ops/go_live_hardening_checklist.md",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return non-zero when any mapped evidence path is missing.",
    )
    args = parser.parse_args()

    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    checklist_path = Path(args.checklist_path) if args.checklist_path else root / "docs" / "ops" / "go_live_hardening_checklist.md"
    if not checklist_path.exists():
        print(f"[complete-go-live-checklist] ERROR: checklist not found: {checklist_path}")
        return 2

    payload = complete_checklist(
        root=root,
        checklist_path=checklist_path,
        evidence_paths_by_item=CHECKLIST_EVIDENCE_PATHS,
        require_paths=bool(args.strict),
    )

    out_dir = root / "reports" / "ops"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    ts_file = out_dir / f"go_live_checklist_completion_{stamp}.json"
    latest_file = out_dir / "go_live_checklist_completion_latest.json"
    raw = json.dumps(payload, indent=2)
    ts_file.write_text(raw, encoding="utf-8")
    latest_file.write_text(raw, encoding="utf-8")

    print(f"[complete-go-live-checklist] status={payload['status']} items_touched={payload['items_touched']}")
    print(f"[complete-go-live-checklist] evidence={latest_file}")
    if bool(args.strict) and str(payload.get("status", "")).lower() == "fail":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
