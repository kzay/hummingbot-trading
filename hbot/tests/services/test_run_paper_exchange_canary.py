from __future__ import annotations

import json
from pathlib import Path

from scripts.ops.run_paper_exchange_canary import (
    _build_bot_recreate_cmd,
    _critical_alert_count_from_steps,
    _latest_harness_run_id,
    _mode_env_key,
    _upsert_env_text,
)


def test_mode_env_key_maps_bot_suffix() -> None:
    assert _mode_env_key("bot3") == "PAPER_EXCHANGE_MODE_BOT3"
    assert _mode_env_key("BOT1") == "PAPER_EXCHANGE_MODE_BOT1"


def test_upsert_env_text_replaces_existing_and_appends_new() -> None:
    original = (
        "BOT1_MODE=paper\n"
        "PAPER_EXCHANGE_MODE_BOT3=disabled\n"
        "REDIS_HOST=redis\n"
    )
    updated = _upsert_env_text(
        original,
        {
            "PAPER_EXCHANGE_MODE_BOT3": "shadow",
            "PAPER_EXCHANGE_ALLOWED_CONNECTORS": "bitget_perpetual",
        },
    )
    assert "PAPER_EXCHANGE_MODE_BOT3=shadow" in updated
    assert "PAPER_EXCHANGE_MODE_BOT3=disabled" not in updated
    assert "PAPER_EXCHANGE_ALLOWED_CONNECTORS=bitget_perpetual" in updated
    assert updated.endswith("\n")


def test_build_bot_recreate_cmd_uses_test_profile_for_bot3(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    compose_path = tmp_path / "docker-compose.yml"
    cmd = _build_bot_recreate_cmd(env_path, compose_path, "bot3")
    assert "--profile" in cmd
    assert "test" in cmd
    assert cmd[-1] == "bot3"


def test_latest_harness_run_id_reads_diagnostics_field(tmp_path: Path) -> None:
    latest = tmp_path / "reports" / "verification" / "paper_exchange_load_harness_latest.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(
        json.dumps({"diagnostics": {"run_id": "20260302T010000000000Z"}}),
        encoding="utf-8",
    )
    assert _latest_harness_run_id(tmp_path) == "20260302T010000000000Z"


def test_critical_alert_count_from_steps_counts_failed_critical_steps() -> None:
    steps = [
        {"name": "env_patch", "pass": False},
        {"name": "compose_start_paper_exchange", "pass": True},
        {"name": "recreate_bot", "pass": False},
        {"name": "paper_exchange_preflight", "pass": False},
    ]
    assert _critical_alert_count_from_steps(steps) == 2
