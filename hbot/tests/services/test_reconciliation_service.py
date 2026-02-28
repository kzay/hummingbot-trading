"""Tests for reconciliation_service — drift detection, report shape, graceful fallbacks."""
from __future__ import annotations

import os
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from services.reconciliation_service.main import (
    _critical_action_name,
    _derive_reconciliation_actions,
    _apply_exchange_snapshot_check,
    _bot_thresholds,
    _count_event_fills,
    _inventory_drift_from_minute,
    _load_thresholds,
    run,
    _severity,
    _write_json,
)


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


class TestRunLoopRegression:
    def test_run_once_single_row_fill_parity_does_not_crash(self, tmp_path):
        data_root = tmp_path / "data"
        minute_dir = data_root / "bot1" / "logs" / "epp_v24" / "bot1_a"
        minute_dir.mkdir(parents=True, exist_ok=True)
        minute_file = minute_dir / "minute.csv"
        ts_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        minute_file.write_text(
            (
                "ts,equity_quote,base_pct,target_base_pct,exchange,fills_count_today,"
                "fees_paid_today_quote,turnover_today_x,maker_fee_pct,taker_fee_pct,fee_source\n"
                f"{ts_utc},1000,0.5,0.5,bitget_perpetual,2,0,0,0.0002,0.0006,vip0\n"
            ),
            encoding="utf-8",
        )

        with patch.dict(
            os.environ,
            {
                "HB_DATA_ROOT": str(data_root),
                "RECON_EVENT_STORE_ROOT": str(tmp_path / "reports" / "event_store"),
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

    def test_fill_parity_missing_events_not_flagged_for_non_active_day(self, tmp_path):
        data_root = tmp_path / "data"
        minute_dir = data_root / "bot1" / "logs" / "epp_v24" / "bot1_a"
        minute_dir.mkdir(parents=True, exist_ok=True)
        minute_file = minute_dir / "minute.csv"
        ts_utc = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        minute_file.write_text(
            (
                "ts,equity_quote,base_pct,target_base_pct,exchange,fills_count_today,"
                "fees_paid_today_quote,turnover_today_x,maker_fee_pct,taker_fee_pct,fee_source\n"
                f"{ts_utc},1000,0.5,0.5,bitget_perpetual,2,0,0,0.0002,0.0006,vip0\n"
            ),
            encoding="utf-8",
        )

        with patch.dict(
            os.environ,
            {
                "HB_DATA_ROOT": str(data_root),
                "RECON_EVENT_STORE_ROOT": str(tmp_path / "reports" / "event_store"),
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
