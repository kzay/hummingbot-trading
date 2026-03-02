from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.release.testnet_readiness_gate import build_kill_switch_evidence


def test_build_kill_switch_evidence_passes_for_fresh_non_dry_run() -> None:
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "ts_utc": now,
        "dry_run": False,
        "entry_id": "1772109231881-0",
        "result": {"status": "executed"},
    }
    out = build_kill_switch_evidence(payload, max_age_min=60.0)
    assert out["status"] == "pass"
    assert out["checks"]["non_dry_run"] is True
    assert out["checks"]["execution_status_ok"] is True


def test_build_kill_switch_evidence_fails_for_dry_run() -> None:
    payload = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "dry_run": True,
        "entry_id": "1-0",
        "result": {"status": "executed"},
    }
    out = build_kill_switch_evidence(payload, max_age_min=60.0)
    assert out["status"] == "fail"
    assert out["checks"]["non_dry_run"] is False


def test_build_kill_switch_evidence_fails_when_stale() -> None:
    stale = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    payload = {
        "ts_utc": stale,
        "dry_run": False,
        "entry_id": "1-0",
        "result": {"status": "executed"},
    }
    out = build_kill_switch_evidence(payload, max_age_min=60.0)
    assert out["status"] == "fail"
    assert out["checks"]["fresh_evidence"] is False
