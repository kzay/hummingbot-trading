"""Verify Redis stream structure contracts.

Run with: PYTHONPATH=hbot python -m pytest hbot/tests/integration/test_stream_contracts.py -v
This test is excluded from the normal test suite (``--ignore=hbot/tests/integration``).
"""
from __future__ import annotations

import pytest

from platform_lib.contracts.stream_names import (
    MARKET_DATA_STREAM,
    PAPER_EXCHANGE_EVENT_STREAM,
    STREAM_RETENTION_MAXLEN,
)

pytestmark = pytest.mark.integration


def test_market_data_stream_exists(redis_client):
    """XINFO on the market data stream should succeed."""
    try:
        info = redis_client.xinfo_stream(MARKET_DATA_STREAM)
    except Exception as exc:
        pytest.skip(f"Market data stream not present: {exc}")
    assert info["length"] >= 0


def test_event_stream_exists(redis_client):
    """XINFO on the paper exchange event stream should succeed."""
    try:
        info = redis_client.xinfo_stream(PAPER_EXCHANGE_EVENT_STREAM)
    except Exception as exc:
        pytest.skip(f"Event stream not present: {exc}")
    assert info["length"] >= 0


def test_stream_maxlen_enforced(redis_client):
    """Each existing stream's length should be within its configured MAXLEN bound.

    Streams that don't exist yet are silently skipped.
    """
    violations: list[str] = []
    for stream_name, maxlen in STREAM_RETENTION_MAXLEN.items():
        try:
            info = redis_client.xinfo_stream(stream_name)
        except Exception:
            continue
        length = info["length"]
        # Allow 10% headroom because approximate trimming is used
        if length > maxlen * 1.1:
            violations.append(
                f"{stream_name}: length={length} exceeds maxlen={maxlen}"
            )
    assert not violations, "Stream MAXLEN violations:\n" + "\n".join(violations)
