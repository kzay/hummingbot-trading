from __future__ import annotations

from scripts.release import run_paper_exchange_golden_path as golden_path


def test_build_report_passes_when_all_scenarios_pass(monkeypatch, tmp_path) -> None:
    def _fake_run(root, node_ids, *, strict):  # noqa: ARG001
        return 0, "ok", 0.01

    monkeypatch.setattr(golden_path, "_run_pytest_scenario", _fake_run)
    report = golden_path.build_report(tmp_path, strict=False, now_ts=0.0)

    assert report["status"] == "pass"
    assert report["summary"]["scenario_count"] >= 4
    assert report["summary"]["failed_count"] == 0
    assert report["failed_remediation_categories"] == []
    assert report["remediation_map"] == {}
    scenario_by_id = {str(row.get("id", "")): row for row in report.get("scenarios", []) if isinstance(row, dict)}
    assert "active_mode_failure_policy" in scenario_by_id
    assert scenario_by_id["active_mode_failure_policy"].get("derived_metrics", {})
    assert "hb_executor_runtime_compatibility" in scenario_by_id
    hb_compat_metrics = scenario_by_id["hb_executor_runtime_compatibility"].get("derived_metrics", {})
    assert hb_compat_metrics.get("p0_11_hb_executor_lifecycle_tests_pass_rate_pct") == 100.0


def test_build_report_collects_failure_categories_and_scenarios(monkeypatch, tmp_path) -> None:
    def _fake_run(root, node_ids, *, strict):  # noqa: ARG001
        joined = " ".join(node_ids)
        if "test_active_buy_rejects_while_sync_pending" in joined:
            return 2, "sync failure", 0.02
        if "test_order_counter_persists_across_restart" in joined:
            return 2, "recovery failure", 0.03
        return 0, "ok", 0.01

    monkeypatch.setattr(golden_path, "_run_pytest_scenario", _fake_run)
    report = golden_path.build_report(tmp_path, strict=True, now_ts=0.0)

    assert report["status"] == "fail"
    assert report["summary"]["failed_count"] == 2
    assert report["failed_remediation_categories"] == [
        "restart_recovery_idempotency",
        "sync_handshake_contract",
    ]
    remediation_map = report["remediation_map"]
    assert "sync_handshake_contract" in remediation_map
    assert "restart_recovery_idempotency" in remediation_map

