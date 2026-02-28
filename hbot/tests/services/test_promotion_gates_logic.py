from __future__ import annotations

from pathlib import Path

from scripts.release.run_promotion_gates import (
    _day2_freshness,
    _day2_lag_within_tolerance,
    _parity_core_insufficient_active_bots,
    _portfolio_diversification_gate,
)


def test_parity_core_insufficient_flags_only_active_bots() -> None:
    parity = {
        "status": "pass",
        "bots": [
            {
                "bot": "bot1",
                "summary": {
                    "intents_total": 0,
                    "actionable_intents": 0,
                    "fills_total": 0,
                    "equity_first": 100.0,
                    "equity_last": 100.0,
                },
                "metrics": [
                    {"metric": "fill_ratio_delta", "note": "insufficient_data", "value": None, "delta": None},
                    {"metric": "slippage_delta_bps", "note": "insufficient_data", "value": None, "delta": None},
                    {"metric": "reject_rate_delta", "note": "insufficient_data", "value": None, "delta": None},
                ],
            },
            {
                "bot": "bot4",
                "summary": {
                    "intents_total": 0,
                    "actionable_intents": 0,
                    "fills_total": 0,
                    "equity_first": None,
                    "equity_last": None,
                },
                "metrics": [
                    {"metric": "fill_ratio_delta", "note": "insufficient_data", "value": None, "delta": None},
                    {"metric": "slippage_delta_bps", "note": "insufficient_data", "value": None, "delta": None},
                    {"metric": "reject_rate_delta", "note": "insufficient_data", "value": None, "delta": None},
                ],
            },
        ],
    }
    insufficient, active = _parity_core_insufficient_active_bots(parity)
    assert active == ["bot1"]
    assert insufficient == ["bot1"]


def test_parity_core_insufficient_passes_when_any_core_metric_has_data() -> None:
    parity = {
        "status": "pass",
        "bots": [
            {
                "bot": "bot1",
                "summary": {"equity_first": 100.0, "equity_last": 101.0},
                "metrics": [
                    {"metric": "fill_ratio_delta", "note": "insufficient_data", "value": None, "delta": None},
                    {"metric": "slippage_delta_bps", "note": "", "value": 1.2, "delta": -0.3},
                    {"metric": "reject_rate_delta", "note": "insufficient_data", "value": None, "delta": None},
                ],
            }
        ],
    }
    insufficient, active = _parity_core_insufficient_active_bots(parity)
    assert active == ["bot1"]
    assert insufficient == []


def test_day2_freshness_uses_file_mtime_when_ts_missing(tmp_path: Path) -> None:
    day2_path = tmp_path / "day2_gate_eval_latest.json"
    day2_path.write_text("{}", encoding="utf-8")
    is_fresh, age_min = _day2_freshness({}, day2_path, max_report_age_min=60.0)
    assert is_fresh is True
    assert age_min < 1.0


def test_day2_lag_within_tolerance_fails_when_delta_exceeds_threshold(tmp_path: Path) -> None:
    reports = tmp_path / "event_store"
    reports.mkdir(parents=True, exist_ok=True)
    source_compare = reports / "source_compare_20260228T000000Z.json"
    source_compare.write_text(
        """{
  "delta_produced_minus_ingested_since_baseline": {
    "hb.market_data.v1": 9,
    "hb.signal.v1": 0
  }
}""",
        encoding="utf-8",
    )
    day2 = {"source_compare_file": str(source_compare)}
    ok, diag = _day2_lag_within_tolerance(day2, reports, max_allowed_delta=5)
    assert ok is False
    assert diag["max_delta_observed"] == 9
    assert diag["worst_stream"] == "hb.market_data.v1"
    assert diag["offending_streams"] == {"hb.market_data.v1": 9}


def test_day2_lag_within_tolerance_recovers_when_delta_is_within_threshold(tmp_path: Path) -> None:
    reports = tmp_path / "event_store"
    reports.mkdir(parents=True, exist_ok=True)
    source_compare = reports / "source_compare_20260228T000001Z.json"
    source_compare.write_text(
        """{
  "delta_produced_minus_ingested_since_baseline": {
    "hb.market_data.v1": 4,
    "hb.signal.v1": 1
  }
}""",
        encoding="utf-8",
    )
    day2 = {"source_compare_file": str(source_compare)}
    ok, diag = _day2_lag_within_tolerance(day2, reports, max_allowed_delta=5)
    assert ok is True
    assert diag["max_delta_observed"] == 4
    assert diag["offending_streams"] == {}


def test_portfolio_diversification_gate_passes_for_pass_and_insufficient_data() -> None:
    ok_pass, reason_pass = _portfolio_diversification_gate({"status": "pass"})
    ok_ins, reason_ins = _portfolio_diversification_gate({"status": "insufficient_data"})
    assert ok_pass is True
    assert "within threshold" in reason_pass
    assert ok_ins is True
    assert "insufficient overlap" in reason_ins


def test_portfolio_diversification_gate_fails_for_fail_or_missing_status() -> None:
    ok_fail, reason_fail = _portfolio_diversification_gate({"status": "fail"})
    ok_missing, reason_missing = _portfolio_diversification_gate({})
    assert ok_fail is False
    assert "above threshold" in reason_fail
    assert ok_missing is False
    assert "missing or invalid" in reason_missing

