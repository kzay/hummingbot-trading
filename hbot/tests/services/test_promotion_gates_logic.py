from __future__ import annotations

import os
from pathlib import Path

from scripts.release.run_promotion_gates import (
    _run_event_store_once,
    _day2_freshness,
    _day2_lag_within_tolerance,
    _parity_core_insufficient_active_bots,
    _portfolio_diversification_gate,
    _run_canonical_plane_gate,
    _run_paper_exchange_preflight_check,
)


def test_parity_core_insufficient_flags_only_active_bots() -> None:
    parity = {
        "status": "pass",
        "bots": [
            {
                "bot": "bot1",
                "summary": {
                    "intents_total": 2,
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
                "summary": {
                    "intents_total": 1,
                    "actionable_intents": 1,
                    "fills_total": 0,
                    "equity_first": 100.0,
                    "equity_last": 101.0,
                },
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


def test_day2_lag_within_tolerance_ignores_negative_deltas_as_non_lag(tmp_path: Path) -> None:
    reports = tmp_path / "event_store"
    reports.mkdir(parents=True, exist_ok=True)
    source_compare = reports / "source_compare_20260228T000002Z.json"
    source_compare.write_text(
        """{
  "delta_produced_minus_ingested_since_baseline": {
    "hb.market_data.v1": -26,
    "hb.signal.v1": -1
  }
}""",
        encoding="utf-8",
    )
    day2 = {"source_compare_file": str(source_compare)}
    ok, diag = _day2_lag_within_tolerance(day2, reports, max_allowed_delta=5)
    assert ok is True
    assert diag["max_delta_observed"] == 0
    assert diag["offending_streams"] == {}


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


def test_run_paper_exchange_preflight_uses_pythonpath_env(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    class _Proc:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def _fake_run(cmd, cwd, capture_output, text, check, env):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["env"] = env
        return _Proc()

    monkeypatch.setattr("scripts.release.run_promotion_gates.subprocess.run", _fake_run)

    rc, msg = _run_paper_exchange_preflight_check(tmp_path, strict=True)
    assert rc == 0
    assert msg == "ok"
    assert str(tmp_path) == captured["cwd"]
    assert "--strict" in captured["cmd"]
    env = captured["env"]
    py_path = str(env.get("PYTHONPATH", ""))
    assert str(tmp_path) in py_path.split(os.pathsep)


def test_run_canonical_plane_gate_forwards_threshold_args(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    class _Proc:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def _fake_run(cmd, cwd, capture_output, text, check, env):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["env"] = env
        return _Proc()

    monkeypatch.setattr("scripts.release.run_promotion_gates.subprocess.run", _fake_run)

    rc, msg = _run_canonical_plane_gate(
        tmp_path,
        max_db_ingest_age_min=25.0,
        max_parity_delta_ratio=0.05,
        min_duplicate_suppression_rate=0.995,
        max_replay_lag_delta=6,
    )
    assert rc == 0
    assert msg == "ok"
    assert str(tmp_path) == captured["cwd"]
    assert str(tmp_path / "scripts" / "release" / "check_canonical_plane_gate.py") in captured["cmd"]
    assert "--max-db-ingest-age-min" in captured["cmd"]
    assert "--max-parity-delta-ratio" in captured["cmd"]
    assert "--min-duplicate-suppression-rate" in captured["cmd"]
    assert "--max-replay-lag-delta" in captured["cmd"]
    env = captured["env"]
    py_path = str(env.get("PYTHONPATH", ""))
    assert str(tmp_path) in py_path.split(os.pathsep)


def test_run_event_store_once_falls_back_to_docker_when_host_client_disabled(monkeypatch, tmp_path: Path) -> None:
    calls = []

    class _Proc:
        def __init__(self, returncode: int, stdout: str, stderr: str = "") -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def _fake_run(cmd, cwd, capture_output, text, check, env=None):  # noqa: ARG001
        calls.append(cmd)
        if len(calls) == 1:
            return _Proc(
                1,
                "Redis stream client disabled (enabled=False redis=True)\n"
                "RuntimeError: Redis stream client is disabled. Set EXT_SIGNAL_RISK_ENABLED=true",
            )
        return _Proc(0, "")

    monkeypatch.setattr("scripts.release.run_promotion_gates.subprocess.run", _fake_run)
    rc, msg = _run_event_store_once(tmp_path)
    assert rc == 0
    assert len(calls) == 2
    assert calls[1][0:3] == ["docker", "exec", "hbot-event-store-service"]
    assert "docker_rc=0" in msg

