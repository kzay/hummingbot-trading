"""Tests for reconciliation_service — drift detection, report shape, graceful fallbacks."""
from __future__ import annotations

import os
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from services.reconciliation_service.main import (
    _apply_fill_reconciliation_report,
    _critical_action_name,
    _derive_reconciliation_actions,
    _emit_webhook_alert,
    _apply_exchange_snapshot_check,
    _bot_thresholds,
    _count_event_fills,
    _inventory_drift_from_minute,
    _latest_source_compare_with_telemetry,
    _load_thresholds,
    run,
    _severity,
    _write_json,
)
from services.reconciliation_service.fill_reconciler import reconcile_fills


# ── helpers ──────────────────────────────────────────────────────────

def _make_exchange_snapshot(tmp: Path, bot: str, exchange_base_pct: float) -> Path:
    snap_path = tmp / "exchange_snapshot.json"
    snap_path.write_text(
        json.dumps({"bots": {bot: {"base_pct": exchange_base_pct}}}),
        encoding="utf-8",
    )
    return snap_path


# ── _apply_exchange_snapshot_check ────────────────────────────────────

class TestExchangeSnapshotDrift:
    """Drift calculation with mocked exchange data."""

    def test_zero_drift_produces_no_findings(self, tmp_path):
        snap = _make_exchange_snapshot(tmp_path, "bot1", 0.50)
        findings = []
        _apply_exchange_snapshot_check(
            findings=findings,
            bot="bot1",
            base_pct=0.50,
            exchange_snapshot_path=snap,
            exchange_warn=0.10,
            exchange_critical=0.20,
        )
        assert findings == []

    def test_small_drift_warning(self, tmp_path):
        snap = _make_exchange_snapshot(tmp_path, "bot1", 0.62)
        findings = []
        _apply_exchange_snapshot_check(
            findings=findings,
            bot="bot1",
            base_pct=0.50,
            exchange_snapshot_path=snap,
            exchange_warn=0.10,
            exchange_critical=0.20,
        )
        assert len(findings) == 1
        assert findings[0]["severity"] == "warning"
        assert findings[0]["check"] == "exchange_snapshot"
        assert "drift" in findings[0]["details"]


def test_emit_webhook_alert_logs_nonfatal_delivery_failures() -> None:
    report = {
        "status": "critical",
        "critical_count": 1,
        "warning_count": 0,
        "ts_utc": "2026-03-09T00:00:00Z",
        "findings": [{"check": "fill_reconciliation"}],
    }

    with patch("services.reconciliation_service.main.urlopen", side_effect=RuntimeError("webhook down")):
        with patch("services.reconciliation_service.main.logger.warning") as warning_mock:
            sent = _emit_webhook_alert(report, "https://example.invalid/webhook", "warning")

    assert sent is False
    warning_mock.assert_called_once()

    def test_critical_drift(self, tmp_path):
        snap = _make_exchange_snapshot(tmp_path, "bot1", 0.75)
        findings = []
        _apply_exchange_snapshot_check(
            findings=findings,
            bot="bot1",
            base_pct=0.50,
            exchange_snapshot_path=snap,
            exchange_warn=0.10,
            exchange_critical=0.20,
        )
        assert len(findings) == 1
        assert findings[0]["severity"] == "critical"
        assert findings[0]["details"]["drift"] >= 0.20

    def test_missing_snapshot_file(self, tmp_path):
        missing = tmp_path / "does_not_exist.json"
        findings = []
        _apply_exchange_snapshot_check(
            findings=findings,
            bot="bot1",
            base_pct=0.50,
            exchange_snapshot_path=missing,
            exchange_warn=0.10,
            exchange_critical=0.20,
        )
        assert len(findings) == 1
        assert findings[0]["severity"] == "warning"
        assert findings[0]["message"] == "exchange_snapshot_missing"

    def test_unreadable_snapshot_file(self, tmp_path):
        bad = tmp_path / "corrupt.json"
        bad.write_text("NOT VALID JSON!!!", encoding="utf-8")
        findings = []
        _apply_exchange_snapshot_check(
            findings=findings,
            bot="bot1",
            base_pct=0.50,
            exchange_snapshot_path=bad,
            exchange_warn=0.10,
            exchange_critical=0.20,
        )
        assert len(findings) == 1
        assert findings[0]["message"] == "exchange_snapshot_unreadable"


# ── Report output shape ──────────────────────────────────────────────

class TestReportShape:
    """Verify latest.json has all required keys."""

    def test_write_json_creates_parent_dirs(self, tmp_path):
        out = tmp_path / "sub" / "dir" / "report.json"
        payload = {"ts_utc": "2026-01-01T00:00:00Z", "status": "ok"}
        _write_json(out, payload)
        assert out.exists()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["ts_utc"] == "2026-01-01T00:00:00Z"
        assert data["status"] == "ok"

    def test_severity_dict_shape(self):
        result = _severity("warning", "balance", "test_msg", "bot1", {"key": "val"})
        assert set(result.keys()) == {"severity", "check", "message", "bot", "details"}
        assert result["severity"] == "warning"
        assert result["bot"] == "bot1"

    def test_fill_reconciler_tracks_amount_fee_and_timestamp_mismatches(self):
        local = [
            {
                "order_id": "oid-1",
                "price": "100.0",
                "amount_base": "1.0",
                "fee_quote": "0.10",
                "ts": "2026-03-05T00:00:00Z",
            }
        ]
        exchange = [
            {
                "order": "oid-1",
                "price": 100.0,
                "amount": 1.3,
                "fee": {"cost": 0.25},
                "timestamp": "2026-03-05T00:01:10Z",
            }
        ]
        report = reconcile_fills(local, exchange, amount_tolerance_pct=0.05, fee_tolerance_pct=0.05, timestamp_tolerance_ms=5_000)
        assert report["matched_count"] == 1
        assert report["amount_mismatch_count"] == 1
        assert report["fee_mismatch_count"] == 1
        assert report["timestamp_mismatch_count"] == 1

    def test_apply_fill_reconciliation_report_surfaces_new_mismatch_counts(self):
        findings = []
        _apply_fill_reconciliation_report(
            findings,
            {
                "exchange": "bitget",
                "bots": [
                    {
                        "bot": "bot1",
                        "status": "critical",
                        "missing_local_count": 0,
                        "missing_exchange_count": 1,
                        "price_mismatch_count": 1,
                        "amount_mismatch_count": 2,
                        "fee_mismatch_count": 3,
                        "timestamp_mismatch_count": 4,
                    }
                ],
            },
        )
        assert len(findings) == 1
        details = findings[0]["details"]
        assert details["amount_mismatch_count"] == 2
        assert details["fee_mismatch_count"] == 3
        assert details["timestamp_mismatch_count"] == 4


# ── Thresholds and config loading ────────────────────────────────────

class TestThresholds:
    def test_load_missing_file_returns_defaults(self, tmp_path):
        cfg = _load_thresholds(tmp_path / "missing.json")
        assert "defaults" in cfg
        assert cfg["defaults"]["inventory_warn"] == 0.25

    def test_load_custom_thresholds(self, tmp_path):
        cfg_path = tmp_path / "thresholds.json"
        cfg_path.write_text(
            json.dumps({"defaults": {"inventory_warn": 0.30}, "bots": {}}),
            encoding="utf-8",
        )
        cfg = _load_thresholds(cfg_path)
        assert cfg["defaults"]["inventory_warn"] == 0.30

    def test_bot_thresholds_fallback(self):
        cfg = {"defaults": {"inventory_warn": 0.20, "inventory_critical": 0.40}, "bots": {}}
        bt = _bot_thresholds(cfg, "bot1")
        assert bt["inventory_warn"] == 0.20
        assert bt["inventory_critical"] == 0.40

    def test_bot_specific_override(self):
        cfg = {
            "defaults": {"inventory_warn": 0.20},
            "bots": {"bot1": {"inventory_warn": 0.35}},
        }
        bt = _bot_thresholds(cfg, "bot1")
        assert bt["inventory_warn"] == 0.35
        assert bt["fee_rate_warn_mult"] == 2.5
        assert bt["perp_inventory_basis"] == "position_drift_pct"

    def test_missing_credentials_graceful_fallback(self, tmp_path):
        """Exchange snapshot with bot not present still falls back to local base_pct."""
        snap_path = tmp_path / "snap.json"
        snap_path.write_text(json.dumps({"bots": {}}), encoding="utf-8")
        findings = []
        _apply_exchange_snapshot_check(
            findings=findings,
            bot="bot1",
            base_pct=0.50,
            exchange_snapshot_path=snap_path,
            exchange_warn=0.10,
            exchange_critical=0.20,
        )
        # drift is |0.50 - 0.50| = 0.0 because safe_float falls back to local base_pct
        assert findings == []


class TestInventoryDriftBasis:
    def test_perp_uses_position_drift_basis_by_default(self):
        minute = {
            "base_pct": "0.70",
            "target_base_pct": "0.0",
            "position_drift_pct": "0.01",
        }
        inv = _inventory_drift_from_minute(minute, is_perp=True, bot_cfg={"perp_inventory_basis": "position_drift_pct"})
        assert inv["basis"] == "position_drift_pct"
        assert inv["drift"] == 0.01
        assert inv["target"] == 0.0

    def test_perp_can_fallback_to_target_delta_basis(self):
        minute = {
            "base_pct": "0.70",
            "target_base_pct": "0.10",
            "position_drift_pct": "0.01",
        }
        inv = _inventory_drift_from_minute(minute, is_perp=True, bot_cfg={"perp_inventory_basis": "target_delta"})
        assert inv["basis"] == "target_base_pct_delta"
        assert inv["drift"] == 0.60

    def test_spot_uses_target_delta_basis(self):
        minute = {
            "base_pct": "0.40",
            "target_base_pct": "0.25",
            "position_drift_pct": "0.90",
        }
        inv = _inventory_drift_from_minute(minute, is_perp=False, bot_cfg={"perp_inventory_basis": "position_drift_pct"})
        assert inv["basis"] == "target_base_pct_delta"
        assert abs(float(inv["drift"]) - 0.15) < 1e-9


class TestReconciliationActionTransitions:
    def test_derive_actions_emits_enter_and_recover_transitions(self):
        findings = [
            {"severity": "critical", "bot": "bot1"},
            {"severity": "warning", "bot": "bot2"},
        ]
        actions, critical_bots = _derive_reconciliation_actions(
            findings=findings,
            previous_critical_bots={"bot3"},
            allowed_scope=set(),
        )
        assert actions == [("bot1", "enter_critical"), ("bot3", "recover")]
        assert critical_bots == {"bot1"}

    def test_derive_actions_honors_scope(self):
        findings = [
            {"severity": "critical", "bot": "bot1"},
            {"severity": "critical", "bot": "bot2"},
        ]
        actions, critical_bots = _derive_reconciliation_actions(
            findings=findings,
            previous_critical_bots=set(),
            allowed_scope={"bot2"},
        )
        assert actions == [("bot2", "enter_critical")]
        assert critical_bots == {"bot2"}

    def test_critical_action_name_defaults_to_soft_pause(self):
        assert _critical_action_name("kill_switch") == "kill_switch"
        assert _critical_action_name("SOFT_PAUSE") == "soft_pause"
        assert _critical_action_name("unknown-action") == "soft_pause"


class TestEventFillCounting:
    def test_counts_order_filled_and_bot_fill(self, tmp_path):
        event_file = tmp_path / "events.jsonl"
        lines = [
            {"event_type": "order_filled", "instance_name": "bot1"},
            {"event_type": "bot_fill", "instance_name": "bot1"},
            {"event_type": "bot_fill", "instance_name": "bot2"},
            {"event_type": "strategy_signal", "instance_name": "bot1"},
        ]
        event_file.write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")
        assert _count_event_fills(event_file, "bot1") == 2


class TestTelemetryDiagnostics:
    def test_latest_source_compare_with_telemetry_prefers_richer_artifact(self, tmp_path):
        older = tmp_path / "source_compare_20260309T225319Z.json"
        newer = tmp_path / "source_compare_20260309T225355Z.json"
        older.write_text(
            json.dumps(
                {
                    "ts_utc": "2026-03-09T22:53:19.949602+00:00",
                    "source_events_by_stream": {"hb.bot_telemetry.v1": 2478},
                }
            ),
            encoding="utf-8",
        )
        newer.write_text(
            json.dumps(
                {
                    "ts_utc": "2026-03-09T22:53:55.520911+00:00",
                    "source_events_by_stream": {"hb.audit.v1": 1362},
                }
            ),
            encoding="utf-8",
        )

        picked_path, payload = _latest_source_compare_with_telemetry(tmp_path)

        assert picked_path == older
        assert payload["source_events_by_stream"]["hb.bot_telemetry.v1"] == 2478


class TestRunLoopRegression:
    def test_run_once_single_row_fill_parity_does_not_crash(self, tmp_path):
        event_store_root = tmp_path / "reports" / "event_store"
        event_store_root.mkdir(parents=True, exist_ok=True)
        data_root = tmp_path / "data"
        minute_dir = data_root / "bot1" / "logs" / "epp_v24" / "bot1_a"
        minute_dir.mkdir(parents=True, exist_ok=True)
        day_stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        minute_dir.joinpath("minute.csv").write_text(
            "ts,state,connector_name,trading_pair,fills_count_today,fees_paid_today_quote,turnover_today_x,maker_fee_pct,taker_fee_pct,fee_source\n"
            f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')},running,bitget_perpetual,BTC-USDT,2,0,0,0.0002,0.0006,vip0\n",
            encoding="utf-8",
        )
        (event_store_root / f"integrity_{day_stamp}.json").write_text(
            json.dumps(
                {
                    "ts_utc": datetime.now(timezone.utc).isoformat(),
                    "events_by_stream": {"hb.bot_telemetry.v1": 0},
                }
            ),
            encoding="utf-8",
        )
        (event_store_root / f"source_compare_{day_stamp}T000000Z.json").write_text(
            json.dumps(
                {
                    "ts_utc": datetime.now(timezone.utc).isoformat(),
                    "source_events_by_stream": {"hb.bot_telemetry.v1": 12},
                    "stored_events_by_stream": {"hb.bot_telemetry.v1": 0},
                    "lag_produced_minus_ingested_since_baseline": {"hb.bot_telemetry.v1": 12},
                    "delta_produced_minus_ingested_since_baseline": {"hb.bot_telemetry.v1": 12},
                }
            ),
            encoding="utf-8",
        )
        ts_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        (event_store_root / f"events_{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl").write_text(
            json.dumps(
                {
                    "event_type": "bot_minute_snapshot",
                    "instance_name": "bot1",
                    "payload": {
                        "instance_name": "bot1",
                        "ts": ts_utc,
                        "equity_quote": 1000,
                        "base_pct": 0.5,
                        "target_base_pct": 0.5,
                        "connector_name": "bitget_perpetual",
                        "fills_count_today": 2,
                        "fees_paid_today_quote": 0,
                        "turnover_today_x": 0,
                        "maker_fee_pct": 0.0002,
                        "taker_fee_pct": 0.0006,
                        "fee_source": "vip0",
                    },
                }
            ),
            encoding="utf-8",
        )

        with patch.dict(
            os.environ,
            {
                "RECON_EVENT_STORE_ROOT": str(event_store_root),
                "HB_DATA_ROOT": str(data_root),
            },
            clear=False,
        ):
            with patch("services.reconciliation_service.main._write_json") as write_json_mock:
                run(once=True)

        assert write_json_mock.call_count >= 2
        payloads = [call.args[1] for call in write_json_mock.call_args_list if len(call.args) >= 2]
        findings = []
        for payload in payloads:
            if isinstance(payload, dict) and isinstance(payload.get("findings"), list):
                findings.extend(payload["findings"])
        parity_findings = [
            f for f in findings
            if f.get("message") == "fills_present_without_order_filled_events"
        ]
        assert parity_findings, "expected fill parity finding for active day with missing event fills"
        assert all(f.get("severity") == "critical" for f in parity_findings)
        assert parity_findings[0]["details"]["suspected_gap_stage"] == "ingest"
        assert parity_findings[0]["details"]["telemetry_lag_since_baseline"] == 12
        report_payloads = [payload for payload in payloads if isinstance(payload, dict) and "checked_bots" in payload]
        assert report_payloads
        latest_report = report_payloads[-1]
        assert latest_report["active_bots"] == ["bot1"]
        assert latest_report["covered_active_bots"] == ["bot1"]
        assert latest_report["active_bots_unchecked"] == []

    def test_run_once_uses_minute_log_fallback_without_critical_snapshot_finding(self, tmp_path):
        event_store_root = tmp_path / "reports" / "event_store"
        event_store_root.mkdir(parents=True, exist_ok=True)
        data_root = tmp_path / "data"
        minute_dir = data_root / "bot1" / "logs" / "epp_v24" / "bot1_a"
        minute_dir.mkdir(parents=True, exist_ok=True)
        minute_dir.joinpath("minute.csv").write_text(
            "ts,state,connector_name,trading_pair,equity_quote,base_pct,target_base_pct,fills_count_today,fees_paid_today_quote,turnover_today_x,maker_fee_pct,taker_fee_pct,fee_source\n"
            f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')},running,bitget_perpetual,BTC-USDT,1000,0.5,0.5,2,0,0,0.0002,0.0006,vip0\n",
            encoding="utf-8",
        )

        with patch.dict(
            os.environ,
            {
                "RECON_EVENT_STORE_ROOT": str(event_store_root),
                "HB_DATA_ROOT": str(data_root),
            },
            clear=False,
        ):
            with patch("services.reconciliation_service.main._write_json") as write_json_mock:
                run(once=True)

        payloads = [call.args[1] for call in write_json_mock.call_args_list if len(call.args) >= 2]
        report_payloads = [payload for payload in payloads if isinstance(payload, dict) and "checked_bots" in payload]
        assert report_payloads
        latest_report = report_payloads[-1]
        findings = latest_report["findings"]

        critical_missing = [
            f for f in findings if f.get("message") == "missing_bot_minute_snapshot_for_active_bot"
        ]
        fallback_warning = [
            f for f in findings if f.get("message") == "missing_bot_minute_snapshot_event_store_fallback_used"
        ]

        assert critical_missing == []
        assert fallback_warning
        assert latest_report["fallback_snapshot_bots"] == ["bot1"]

    def test_fill_parity_missing_events_not_flagged_for_non_active_day(self, tmp_path):
        event_store_root = tmp_path / "reports" / "event_store"
        event_store_root.mkdir(parents=True, exist_ok=True)
        data_root = tmp_path / "data"
        data_root.mkdir(parents=True, exist_ok=True)
        ts_utc = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        (event_store_root / f"events_{(datetime.now(timezone.utc) - timedelta(days=1)).strftime('%Y%m%d')}.jsonl").write_text(
            json.dumps(
                {
                    "event_type": "bot_minute_snapshot",
                    "instance_name": "bot1",
                    "payload": {
                        "instance_name": "bot1",
                        "ts": ts_utc,
                        "equity_quote": 1000,
                        "base_pct": 0.5,
                        "target_base_pct": 0.5,
                        "connector_name": "bitget_perpetual",
                        "fills_count_today": 2,
                        "fees_paid_today_quote": 0,
                        "turnover_today_x": 0,
                        "maker_fee_pct": 0.0002,
                        "taker_fee_pct": 0.0006,
                        "fee_source": "vip0",
                    },
                }
            ),
            encoding="utf-8",
        )

        with patch.dict(
            os.environ,
            {
                "RECON_EVENT_STORE_ROOT": str(event_store_root),
                "HB_DATA_ROOT": str(data_root),
            },
            clear=False,
        ):
            with patch("services.reconciliation_service.main._write_json") as write_json_mock:
                run(once=True)

        payloads = [call.args[1] for call in write_json_mock.call_args_list if len(call.args) >= 2]
        findings = []
        for payload in payloads:
            if isinstance(payload, dict) and isinstance(payload.get("findings"), list):
                findings.extend(payload["findings"])
        parity_findings = [
            f for f in findings
            if f.get("message") == "fills_present_without_order_filled_events"
        ]
        assert parity_findings == []
