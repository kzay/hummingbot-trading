from __future__ import annotations

from scripts.release.run_strict_promotion_cycle import _extract_threshold_diagnostics


def test_extract_threshold_diagnostics_disabled_defaults() -> None:
    diag = _extract_threshold_diagnostics({})
    assert diag["enabled"] is False
    assert diag["inputs_ready"] is False
    assert diag["inputs_unresolved_metric_count"] == 0
    assert diag["blocking_reasons"] == []
    assert diag["action_hint"] == ""


def test_extract_threshold_diagnostics_flags_blockers_and_actions() -> None:
    summary = {
        "checks": [
            {
                "name": "paper_exchange_threshold_inputs_ready",
                "pass": False,
                "reason": "paper-exchange threshold inputs not ready",
            },
            {
                "name": "paper_exchange_thresholds",
                "pass": False,
                "reason": "paper-exchange quantitative thresholds failed",
            },
        ],
        "runtime": {
            "check_paper_exchange_thresholds": True,
            "paper_exchange_threshold_inputs_ready": False,
            "paper_exchange_threshold_inputs_status": "warning",
            "paper_exchange_threshold_inputs_unresolved_metric_count": 3,
            "paper_exchange_threshold_inputs_stale_source_count": 1,
            "paper_exchange_threshold_inputs_missing_source_count": 0,
            "paper_exchange_threshold_inputs_rc": 2,
            "paper_exchange_thresholds_rc": 2,
            "paper_exchange_threshold_inputs_path": "reports/verification/paper_exchange_threshold_inputs_latest.json",
        },
    }
    diag = _extract_threshold_diagnostics(summary)
    assert diag["enabled"] is True
    assert diag["inputs_ready"] is False
    assert diag["inputs_status"] == "warning"
    assert diag["inputs_unresolved_metric_count"] == 3
    assert diag["inputs_stale_source_count"] == 1
    assert diag["inputs_missing_source_count"] == 0
    assert diag["thresholds_rc"] == 2
    assert diag["inputs_check_pass"] is False
    assert diag["thresholds_check_pass"] is False
    assert "unresolved_metrics" in diag["blocking_reasons"]
    assert "stale_sources" in diag["blocking_reasons"]
    assert "threshold_evaluation_failed" in diag["blocking_reasons"]
    assert "resolve 3 unresolved metrics" in diag["action_hint"]
    assert "inspect paper_exchange_thresholds_latest.json failed clauses" in diag["action_hint"]

