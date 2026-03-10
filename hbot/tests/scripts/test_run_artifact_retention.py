from __future__ import annotations

import json
import os
from pathlib import Path

from scripts.release import run_artifact_retention


def _write(path: Path, text: str = "sample") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_retention_uses_policy_default_apply_and_protects_latest(tmp_path: Path, monkeypatch) -> None:
    policy = tmp_path / "config" / "artifact_retention_policy.json"
    policy.parent.mkdir(parents=True, exist_ok=True)
    policy.write_text(
        json.dumps(
            {
                "default_mode": "apply",
                "rules": [{"name": "verification", "glob": "reports/verification/*", "keep_days": 0}],
                "protect_latest": ["reports/verification/runtime_performance_budgets_latest.json"],
            }
        ),
        encoding="utf-8",
    )
    protected = tmp_path / "reports" / "verification" / "runtime_performance_budgets_latest.json"
    expired = tmp_path / "reports" / "verification" / "runtime_performance_budgets_20200101T000000Z.json"
    _write(protected)
    _write(expired)
    monkeypatch.setattr(run_artifact_retention, "_root", lambda: tmp_path)
    monkeypatch.setattr(run_artifact_retention, "_age_days", lambda path: 10.0)
    monkeypatch.setattr("sys.argv", ["run_artifact_retention.py"])

    rc = run_artifact_retention.main()

    latest = tmp_path / "reports" / "ops_retention" / "latest.json"
    payload = json.loads(latest.read_text(encoding="utf-8"))
    assert rc == 0
    assert payload["mode"] == "apply"
    assert protected.exists()
    assert expired.exists() is False
    assert payload["deleted"] == 1


def test_retention_dry_run_overrides_policy_apply(tmp_path: Path, monkeypatch) -> None:
    policy = tmp_path / "config" / "artifact_retention_policy.json"
    policy.parent.mkdir(parents=True, exist_ok=True)
    policy.write_text(
        json.dumps(
            {
                "default_mode": "apply",
                "rules": [{"name": "event_store", "glob": "reports/event_store/*", "keep_days": 0}],
                "protect_latest": [],
            }
        ),
        encoding="utf-8",
    )
    expired = tmp_path / "reports" / "event_store" / "integrity_20200101.json"
    _write(expired)
    monkeypatch.setattr(run_artifact_retention, "_root", lambda: tmp_path)
    monkeypatch.setattr(run_artifact_retention, "_age_days", lambda path: 10.0)
    monkeypatch.setattr("sys.argv", ["run_artifact_retention.py", "--dry-run"])

    rc = run_artifact_retention.main()

    latest = tmp_path / "reports" / "ops_retention" / "latest.json"
    payload = json.loads(latest.read_text(encoding="utf-8"))
    assert rc == 0
    assert payload["mode"] == "dry_run"
    assert payload["deleted"] == 0
    assert expired.exists()


def test_retention_reports_delete_errors(tmp_path: Path, monkeypatch) -> None:
    policy = tmp_path / "config" / "artifact_retention_policy.json"
    policy.parent.mkdir(parents=True, exist_ok=True)
    policy.write_text(
        json.dumps(
            {
                "default_mode": "dry_run",
                "rules": [{"name": "ops", "glob": "reports/ops/*", "keep_days": 0}],
                "protect_latest": [],
            }
        ),
        encoding="utf-8",
    )
    expired = tmp_path / "reports" / "ops" / "old.json"
    _write(expired)
    monkeypatch.setattr(run_artifact_retention, "_root", lambda: tmp_path)
    monkeypatch.setattr(run_artifact_retention, "_age_days", lambda path: 10.0)

    def _raise_remove(path: str) -> None:
        raise PermissionError(f"cannot delete {path}")

    monkeypatch.setattr(os, "remove", _raise_remove)
    monkeypatch.setattr("sys.argv", ["run_artifact_retention.py", "--apply"])

    rc = run_artifact_retention.main()

    latest = tmp_path / "reports" / "ops_retention" / "latest.json"
    payload = json.loads(latest.read_text(encoding="utf-8"))
    assert rc == 0
    assert payload["delete_error_count"] == 1
    assert payload["delete_errors_sample"][0]["path"].endswith("old.json")
    assert expired.exists()
