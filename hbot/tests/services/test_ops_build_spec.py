from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.ops.checklist_evidence_collector import collect
from scripts.ops.preflight_startup import (
    _check_bot_container_password,
    _check_recon_exchange_ready,
    _password_env_keys_for_container,
)
from scripts.ops.validate_telegram_alerting import _classify_error, _validate_format


def test_checklist_evidence_collector_classifies_sections(tmp_path: Path) -> None:
    checklist = tmp_path / "go_live_hardening_checklist.md"
    checklist.write_text(
        "\n".join(
            [
                "### 1. Fee Resolution",
                "- [x] item a",
                "- [x] item b",
                "- **Evidence:** reports/fee/latest.json",
                "### 2. Kill Switch",
                "- [ ] item a",
                "- [ ] item b",
                "- **Evidence:** reports/kill_switch/latest.json",
            ]
        ),
        encoding="utf-8",
    )

    payload = collect(checklist)
    assert payload["sections_total"] == 2
    statuses = [s["status"] for s in payload["sections"]]
    assert statuses == ["pass", "in_progress"]
    assert payload["overall_status"] == "in_progress"


def test_recon_exchange_ready_passes_with_complete_env_and_reports(tmp_path: Path) -> None:
    root = tmp_path
    (root / "env").mkdir(parents=True, exist_ok=True)
    (root / "reports" / "reconciliation").mkdir(parents=True, exist_ok=True)
    (root / "reports" / "exchange_snapshots").mkdir(parents=True, exist_ok=True)

    (root / "env" / ".env").write_text(
        "\n".join(
            [
                "BITGET_API_KEY=abc",
                "BITGET_SECRET=def",
                "BITGET_PASSPHRASE=ghi",
                "RECON_EXCHANGE_SOURCE_ENABLED=true",
            ]
        ),
        encoding="utf-8",
    )
    (root / "reports" / "reconciliation" / "latest.json").write_text(
        json.dumps({"exchange_source_enabled": True}),
        encoding="utf-8",
    )
    (root / "reports" / "exchange_snapshots" / "latest.json").write_text(
        json.dumps({"account_probe": {"status": "ok"}}),
        encoding="utf-8",
    )

    ok, msg, report = _check_recon_exchange_ready(root)
    assert ok is True
    assert "PASS" in msg
    assert report["ready"] is True


def test_recon_exchange_ready_fails_when_env_or_report_missing(tmp_path: Path) -> None:
    root = tmp_path
    (root / "env").mkdir(parents=True, exist_ok=True)
    (root / "reports" / "reconciliation").mkdir(parents=True, exist_ok=True)
    (root / "reports" / "exchange_snapshots").mkdir(parents=True, exist_ok=True)

    (root / "env" / ".env").write_text(
        "RECON_EXCHANGE_SOURCE_ENABLED=false\n",
        encoding="utf-8",
    )
    (root / "reports" / "reconciliation" / "latest.json").write_text(
        json.dumps({"exchange_source_enabled": False}),
        encoding="utf-8",
    )
    (root / "reports" / "exchange_snapshots" / "latest.json").write_text(
        json.dumps({"account_probe": {"status": "disabled"}}),
        encoding="utf-8",
    )

    ok, msg, report = _check_recon_exchange_ready(root)
    assert ok is False
    assert "missing_bitget_keys_in_env" in msg
    assert report["ready"] is False


def test_telegram_format_and_diagnosis_classifiers() -> None:
    ok, reasons = _validate_format("badtoken", "not-a-chat")
    assert ok is False
    assert "token_format_invalid" in reasons
    assert "chat_id_format_invalid" in reasons

    assert _classify_error(Exception("HTTP Error 403: Forbidden")) == "403_forbidden"
    assert _classify_error(Exception("timed out")) == "timeout"


def test_password_env_keys_for_container_multi_bot() -> None:
    assert _password_env_keys_for_container("bot1") == ["BOT1_PASSWORD"]
    assert _password_env_keys_for_container("bot3") == ["BOT3_PASSWORD", "BOT1_PASSWORD"]
    assert _password_env_keys_for_container("bot4") == ["BOT4_PASSWORD", "BOT1_PASSWORD"]


def test_check_bot_container_password_accepts_runtime_export_guard() -> None:
    with patch("scripts.ops.preflight_startup.subprocess.run") as run_mock:
        run_mock.side_effect = [
            SimpleNamespace(returncode=0, stdout="BOT3_PASSWORD=abc\n", stderr=""),
            SimpleNamespace(
                returncode=0,
                stdout='["/bin/bash","-lc","export CONFIG_PASSWORD=${BOT3_PASSWORD:-${BOT1_PASSWORD:-}}"]',
                stderr="",
            ),
        ]
        ok, msg = _check_bot_container_password("bot3")
    assert ok is True
    assert "runtime CONFIG_PASSWORD export guard" in msg


def test_check_bot_container_password_rejects_missing_runtime_guard() -> None:
    with patch("scripts.ops.preflight_startup.subprocess.run") as run_mock:
        run_mock.side_effect = [
            SimpleNamespace(returncode=0, stdout="BOT4_PASSWORD=abc\n", stderr=""),
            SimpleNamespace(returncode=0, stdout='["/bin/bash","-lc","python ./bin/headless_start.py"]', stderr=""),
        ]
        ok, msg = _check_bot_container_password("bot4")
    assert ok is False
    assert "lacks runtime CONFIG_PASSWORD export guard" in msg
