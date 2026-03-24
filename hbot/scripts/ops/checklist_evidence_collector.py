#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path

SECTION_RE = re.compile(r"^###\s+(\d+)\.\s+(.*)$")
CHECKBOX_RE = re.compile(r"^- \[( |x|X)\]\s+(.*)$")
EVIDENCE_RE = re.compile(r"^- \*\*Evidence:\*\*\s*(.*)$")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _classify_section(items: list[dict[str, object]], evidence_text: str) -> str:
    if not items:
        return "unknown"
    all_checked = all(bool(it.get("checked", False)) for it in items)
    any_checked = any(bool(it.get("checked", False)) for it in items)
    has_evidence = bool(evidence_text.strip())
    if all_checked and has_evidence:
        return "pass"
    if any_checked or has_evidence:
        return "in_progress"
    return "fail"


def collect(checklist_path: Path) -> dict[str, object]:
    lines = checklist_path.read_text(encoding="utf-8").splitlines()
    sections: list[dict[str, object]] = []
    current: dict[str, object] | None = None

    for idx, line in enumerate(lines, start=1):
        section_match = SECTION_RE.match(line.strip())
        if section_match:
            if current is not None:
                current["status"] = _classify_section(
                    current.get("checks", []), str(current.get("evidence_text", ""))
                )
                sections.append(current)
            current = {
                "item_number": int(section_match.group(1)),
                "title": section_match.group(2).strip(),
                "line": idx,
                "checks": [],
                "evidence_text": "",
                "status": "unknown",
            }
            continue

        if current is None:
            continue

        box_match = CHECKBOX_RE.match(line.strip())
        if box_match:
            current["checks"].append(
                {
                    "checked": box_match.group(1).lower() == "x",
                    "text": box_match.group(2).strip(),
                    "line": idx,
                }
            )
            continue

        evidence_match = EVIDENCE_RE.match(line.strip())
        if evidence_match:
            current["evidence_text"] = evidence_match.group(1).strip()

    if current is not None:
        current["status"] = _classify_section(
            current.get("checks", []), str(current.get("evidence_text", ""))
        )
        sections.append(current)

    status_counts = {"pass": 0, "in_progress": 0, "fail": 0, "unknown": 0}
    for section in sections:
        st = str(section.get("status", "unknown"))
        status_counts[st] = int(status_counts.get(st, 0)) + 1

    if len(sections) > 0 and status_counts["pass"] == len(sections):
        overall = "pass"
    elif status_counts["fail"] > 0 or status_counts["unknown"] > 0:
        overall = "fail"
    elif status_counts["in_progress"] > 0:
        overall = "in_progress"
    else:
        overall = "unknown"

    return {
        "ts_utc": _utc_now(),
        "checklist_path": str(checklist_path),
        "overall_status": overall,
        "sections_total": len(sections),
        "status_counts": status_counts,
        "sections": sections,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect structured evidence summary from go-live checklist.")
    parser.add_argument(
        "--checklist-path",
        default="",
        help="Optional absolute checklist path. Defaults to docs/ops/go_live_hardening_checklist.md",
    )
    args = parser.parse_args()

    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    checklist_path = Path(args.checklist_path) if args.checklist_path else root / "docs" / "ops" / "go_live_hardening_checklist.md"
    if not checklist_path.exists():
        print(f"[checklist-evidence] ERROR: checklist not found: {checklist_path}")
        return 2

    payload = collect(checklist_path)
    out_dir = root / "reports" / "ops"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    ts_file = out_dir / f"go_live_checklist_evidence_{stamp}.json"
    latest_file = out_dir / "go_live_checklist_evidence_latest.json"
    raw = json.dumps(payload, indent=2)
    ts_file.write_text(raw, encoding="utf-8")
    latest_file.write_text(raw, encoding="utf-8")
    print(f"[checklist-evidence] overall={payload['overall_status']} sections={payload['sections_total']}")
    print(f"[checklist-evidence] evidence={latest_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
