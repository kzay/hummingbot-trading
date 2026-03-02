from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from controllers.paper_engine_v2.hb_event_fire import _realized_pnl_delta_quote


def test_realized_pnl_delta_quote_positive() -> None:
    ctrl = SimpleNamespace(_realized_pnl_today=Decimal("1.25"))
    out = _realized_pnl_delta_quote(ctrl, before_value=1.00)
    assert abs(out - 0.25) < 1e-9


def test_realized_pnl_delta_quote_negative() -> None:
    ctrl = SimpleNamespace(_realized_pnl_today=Decimal("0.80"))
    out = _realized_pnl_delta_quote(ctrl, before_value=1.00)
    assert abs(out + 0.20) < 1e-9


def test_realized_pnl_delta_quote_handles_missing_controller() -> None:
    out = _realized_pnl_delta_quote(None, before_value=1.00)
    assert out == 0.0
