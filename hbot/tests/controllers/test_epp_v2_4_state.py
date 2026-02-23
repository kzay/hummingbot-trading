import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from controllers.epp_v2_4 import EppV24Controller, RegimeSpec


class _DummyController:
    pass


def _make_dummy(tmp_path: Path, now_ts: float) -> _DummyController:
    dummy = _DummyController()
    dummy.config = SimpleNamespace(log_dir=str(tmp_path), instance_name="botx", variant="a", override_spread_pct=None)
    dummy.market_data_provider = SimpleNamespace(time=lambda: now_ts)
    dummy._daily_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    dummy._daily_equity_open = Decimal("100")
    dummy._daily_equity_peak = Decimal("110")
    dummy._traded_notional_today = Decimal("50")
    dummy._fills_count_today = 4
    dummy._fees_paid_today_quote = Decimal("1.2")
    dummy._funding_cost_today_quote = Decimal("0.1")
    dummy._realized_pnl_today = Decimal("2.5")
    dummy._position_base = Decimal("0.25")
    dummy._avg_entry_price = Decimal("42000")
    dummy._last_daily_state_save_ts = 0.0
    dummy._daily_state_path = lambda: EppV24Controller._daily_state_path(dummy)
    return dummy


def test_daily_state_persists_position(tmp_path: Path):
    dummy = _make_dummy(tmp_path, now_ts=1_700_000_000.0)
    EppV24Controller._save_daily_state(dummy, force=True)
    dummy._position_base = Decimal("0")
    dummy._avg_entry_price = Decimal("0")
    dummy._daily_equity_open = None
    dummy._daily_equity_peak = None
    dummy._traded_notional_today = Decimal("0")
    dummy._fills_count_today = 0
    dummy._fees_paid_today_quote = Decimal("0")
    dummy._funding_cost_today_quote = Decimal("0")
    dummy._realized_pnl_today = Decimal("0")
    EppV24Controller._load_daily_state(dummy)
    assert dummy._position_base == Decimal("0.25")
    assert dummy._avg_entry_price == Decimal("42000")
    assert dummy._fills_count_today == 4


def test_save_throttled(tmp_path: Path):
    now_ts = 1_700_000_000.0
    dummy = _make_dummy(tmp_path, now_ts=now_ts)
    EppV24Controller._save_daily_state(dummy)
    dummy._position_base = Decimal("2")
    EppV24Controller._save_daily_state(dummy)
    state_path = Path(EppV24Controller._daily_state_path(dummy))
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["position_base"] == "0.25"


def test_override_spread_pct():
    dummy = _DummyController()
    dummy.config = SimpleNamespace(override_spread_pct=Decimal("0.005"), turnover_cap_x=Decimal("1"))
    regime = RegimeSpec(
        spread_min=Decimal("0.001"),
        spread_max=Decimal("0.003"),
        levels_min=1,
        levels_max=2,
        refresh_s=60,
        target_base_pct=Decimal("0.5"),
        quote_size_pct_min=Decimal("0.001"),
        quote_size_pct_max=Decimal("0.002"),
        one_sided="off",
    )
    spread = EppV24Controller._pick_spread_pct(dummy, regime, Decimal("10"))
    assert spread == Decimal("0.005")
