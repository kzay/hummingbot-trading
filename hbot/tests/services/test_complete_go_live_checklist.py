from __future__ import annotations

from pathlib import Path

from scripts.ops.complete_go_live_checklist import complete_checklist


def test_complete_checklist_marks_boxes_and_updates_evidence_paths(tmp_path: Path) -> None:
    checklist = tmp_path / "go_live_hardening_checklist.md"
    checklist.write_text(
        "\n".join(
            [
                "### 1. Fee Resolution",
                "- [ ] check one",
                "- [ ] check two",
                "- **Evidence:** old/path.json",
                "",
                "### 2. Trading Rules",
                "- [ ] check one",
                "- **Evidence:** old/path2.json",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    (tmp_path / "reports" / "a.json").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports" / "a.json").write_text("{}", encoding="utf-8")
    (tmp_path / "reports" / "b.json").write_text("{}", encoding="utf-8")

    payload = complete_checklist(
        root=tmp_path,
        checklist_path=checklist,
        evidence_paths_by_item={
            1: ["reports/a.json"],
            2: ["reports/b.json"],
        },
        require_paths=True,
    )
    assert payload["status"] == "pass"
    rendered = checklist.read_text(encoding="utf-8")
    assert "- [x] check one" in rendered
    assert "- [x] check two" in rendered
    assert "- **Evidence:** `reports/a.json`" in rendered
    assert "- **Evidence:** `reports/b.json`" in rendered


def test_complete_checklist_strict_fails_when_evidence_missing(tmp_path: Path) -> None:
    checklist = tmp_path / "go_live_hardening_checklist.md"
    checklist.write_text(
        "\n".join(
            [
                "### 1. Fee Resolution",
                "- [ ] check one",
                "- **Evidence:** old/path.json",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    payload = complete_checklist(
        root=tmp_path,
        checklist_path=checklist,
        evidence_paths_by_item={1: ["reports/missing.json"]},
        require_paths=True,
    )
    assert payload["status"] == "fail"
    missing = payload["missing_evidence_paths_by_item"]
    assert "1" in missing
    assert missing["1"] == ["reports/missing.json"]
