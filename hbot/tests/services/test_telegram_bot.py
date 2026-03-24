from __future__ import annotations

from unittest.mock import patch

from services.telegram_bot.main import _pct, _safe_float, _state_emoji


def test_safe_float_valid():
    assert _safe_float("3.14") == 3.14


def test_safe_float_none():
    assert _safe_float(None) == 0.0


def test_safe_float_invalid():
    assert _safe_float("abc", default=-1.0) == -1.0


def test_pct_formats():
    assert _pct(0.05) == "5.000%"
    assert _pct(0.0) == "0.000%"


def test_state_emoji_known():
    assert _state_emoji("running") == "\u2705"
    assert _state_emoji("hard_stop") == "\U0001f6d1"


def test_state_emoji_unknown():
    assert _state_emoji("banana") == "\u2753"


def test_allowed_chat_id_empty():
    with patch("services.telegram_bot.main._CHAT_ID_RAW", ""):
        from services.telegram_bot.main import _allowed_chat_id
        assert _allowed_chat_id() is None
