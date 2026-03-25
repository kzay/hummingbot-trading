"""Baseline tests for exchange-snapshot-service — pure functions only."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from services.exchange_snapshot_service.main import (
    _get_bitget_credentials,
    _load_account_map,
    _redact_sensitive,
    _resolve_bot_account,
)


class TestGetBitgetCredentials:
    def test_reads_env_with_prefix(self):
        env = {
            "BOT1_BITGET_API_KEY": "key1",
            "BOT1_BITGET_SECRET": "sec1",
            "BOT1_BITGET_PASSPHRASE": "pass1",
        }
        with patch.dict("os.environ", env, clear=False):
            k, s, p = _get_bitget_credentials("BOT1")
        assert k == "key1"
        assert s == "sec1"
        assert p == "pass1"

    def test_falls_back_to_global(self):
        env = {
            "BITGET_API_KEY": "gk",
            "BITGET_SECRET": "gs",
            "BITGET_PASSPHRASE": "gp",
        }
        with patch.dict("os.environ", env, clear=False):
            k, s, p = _get_bitget_credentials("")
        assert k == "gk"

    def test_empty_when_missing(self):
        with patch.dict("os.environ", {}, clear=True):
            k, s, p = _get_bitget_credentials("NONE")
        assert k == ""
        assert s == ""
        assert p == ""


class TestRedactSensitive:
    def test_redacts_credentials(self):
        env = {
            "BITGET_API_KEY": "my_secret_key_123",
            "BITGET_SECRET": "my_secret_val_456",
            "BITGET_PASSPHRASE": "my_pass_789",
        }
        with patch.dict("os.environ", env, clear=False):
            result = _redact_sensitive("Error: my_secret_key_123 was rejected")
        assert "my_secret_key_123" not in result
        assert "***redacted***" in result

    def test_empty_input(self):
        assert _redact_sensitive("") == ""

    def test_no_credentials_noop(self):
        with patch.dict("os.environ", {}, clear=True):
            assert _redact_sensitive("some error") == "some error"


class TestLoadAccountMap:
    def test_missing_file_returns_default(self, tmp_path: Path):
        result = _load_account_map(tmp_path / "nonexistent.json")
        assert result["defaults"]["exchange"] == "bitget"
        assert result["bots"] == {}

    def test_valid_json(self, tmp_path: Path):
        p = tmp_path / "accts.json"
        p.write_text(json.dumps({
            "defaults": {"exchange": "okx", "credential_prefix": "MAIN"},
            "bots": {"bot1": {"credential_prefix": "B1"}},
        }))
        result = _load_account_map(p)
        assert result["defaults"]["exchange"] == "okx"
        assert "bot1" in result["bots"]

    def test_invalid_json_returns_default(self, tmp_path: Path):
        p = tmp_path / "bad.json"
        p.write_text("NOT JSON")
        result = _load_account_map(p)
        assert result["defaults"]["exchange"] == "bitget"


class TestResolveBotAccount:
    def test_uses_bot_override(self):
        acct_map = {
            "defaults": {"exchange": "bitget", "credential_prefix": "BOT1"},
            "bots": {"bot7": {"exchange": "okx", "credential_prefix": "BOT7"}},
        }
        result = _resolve_bot_account(acct_map, "bot7")
        assert result["exchange"] == "okx"
        assert result["credential_prefix"] == "BOT7"

    def test_falls_back_to_defaults(self):
        acct_map = {
            "defaults": {"exchange": "bitget", "credential_prefix": "BOT1"},
            "bots": {},
        }
        result = _resolve_bot_account(acct_map, "bot99")
        assert result["exchange"] == "bitget"
        assert result["credential_prefix"] == "BOT1"

    def test_account_mode_default(self):
        acct_map = {"defaults": {}, "bots": {}}
        result = _resolve_bot_account(acct_map, "bot1")
        assert result["account_mode"] == "probe"
