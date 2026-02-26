import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("hummingbot")

from controllers.core import RegimeSpec
from controllers.epp_v2_4 import EppV24Controller


class _DummyController:
    pass


def _make_dummy(tmp_path: Path, now_ts: float) -> _DummyController:
    dummy = _DummyController()
    dummy.config = SimpleNamespace(
        log_dir=str(tmp_path), instance_name="botx", variant="a",
        override_spread_pct=None, startup_position_sync=True,
        connector_name="binance", trading_pair="BTC-USDT",
        position_drift_soft_pause_pct=Decimal("0.05"),
    )
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
    dummy._startup_position_sync_done = False
    dummy._position_drift_pct = Decimal("0")
    dummy._is_perp = False
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


# --- Cross-day position preservation ---

def test_cross_day_restart_preserves_position(tmp_path: Path):
    """Position and avg_entry should survive a day boundary restart."""
    dummy = _make_dummy(tmp_path, now_ts=1_700_000_000.0)
    EppV24Controller._save_daily_state(dummy, force=True)

    state_path = Path(EppV24Controller._daily_state_path(dummy))
    data = json.loads(state_path.read_text(encoding="utf-8"))
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    data["day_key"] = yesterday
    state_path.write_text(json.dumps(data), encoding="utf-8")

    dummy._position_base = Decimal("0")
    dummy._avg_entry_price = Decimal("0")
    dummy._traded_notional_today = Decimal("999")
    dummy._fills_count_today = 99
    EppV24Controller._load_daily_state(dummy)

    assert dummy._position_base == Decimal("0.25"), "position_base must carry across day boundary"
    assert dummy._avg_entry_price == Decimal("42000"), "avg_entry_price must carry across day boundary"
    assert dummy._traded_notional_today == Decimal("999"), "daily counters must NOT be restored on cross-day"
    assert dummy._fills_count_today == 99, "daily counters must NOT be restored on cross-day"


# --- Startup position sync ---

class _FakeConnector:
    """Minimal connector stub for startup sync tests."""
    def __init__(self, balance: Decimal):
        self._balance = balance

    def get_balance(self, asset: str) -> Decimal:
        return self._balance


class _FakeRuntimeAdapter:
    def __init__(self, base_asset: str = "BTC"):
        self._base_asset = base_asset

    def get_mid_price(self) -> Decimal:
        return Decimal("65000")


def _make_sync_dummy(tmp_path: Path, local_pos: Decimal, exchange_pos: Decimal):
    """Build a dummy wired for startup sync testing."""
    dummy = _make_dummy(tmp_path, now_ts=1_700_000_000.0)
    dummy._position_base = local_pos
    dummy._avg_entry_price = Decimal("42000") if local_pos != Decimal("0") else Decimal("0")
    dummy._startup_position_sync_done = False
    dummy._runtime_adapter = _FakeRuntimeAdapter()
    dummy._connector = lambda: _FakeConnector(exchange_pos)
    dummy._get_mid_price = lambda: Decimal("65000")
    dummy._save_daily_state = lambda force=False: None
    return dummy


def test_startup_sync_adopts_exchange_position(tmp_path: Path):
    """When exchange has a position but local is zero, adopt exchange."""
    dummy = _make_sync_dummy(tmp_path, local_pos=Decimal("0"), exchange_pos=Decimal("0.5"))
    EppV24Controller._run_startup_position_sync(dummy)
    assert dummy._position_base == Decimal("0.5")
    assert dummy._avg_entry_price == Decimal("65000")
    assert dummy._startup_position_sync_done is True


def test_startup_sync_no_drift(tmp_path: Path):
    """When exchange matches local, nothing changes."""
    dummy = _make_sync_dummy(tmp_path, local_pos=Decimal("0.25"), exchange_pos=Decimal("0.25"))
    EppV24Controller._run_startup_position_sync(dummy)
    assert dummy._position_base == Decimal("0.25")
    assert dummy._avg_entry_price == Decimal("42000")


def test_startup_sync_corrects_stale_local(tmp_path: Path):
    """When exchange differs from local, exchange wins."""
    dummy = _make_sync_dummy(tmp_path, local_pos=Decimal("0.25"), exchange_pos=Decimal("0.10"))
    EppV24Controller._run_startup_position_sync(dummy)
    assert dummy._position_base == Decimal("0.10")
    assert dummy._avg_entry_price == Decimal("42000")


def test_startup_sync_disabled(tmp_path: Path):
    """When startup_position_sync=False, skip the sync."""
    dummy = _make_sync_dummy(tmp_path, local_pos=Decimal("0"), exchange_pos=Decimal("0.5"))
    dummy.config.startup_position_sync = False
    EppV24Controller._run_startup_position_sync(dummy)
    assert dummy._position_base == Decimal("0"), "sync disabled — position must not change"
    assert dummy._startup_position_sync_done is True


def test_startup_sync_both_zero(tmp_path: Path):
    """When both local and exchange are zero, no-op."""
    dummy = _make_sync_dummy(tmp_path, local_pos=Decimal("0"), exchange_pos=Decimal("0"))
    EppV24Controller._run_startup_position_sync(dummy)
    assert dummy._position_base == Decimal("0")


def test_startup_sync_retries_when_connector_unavailable(tmp_path: Path):
    """When connector is None, sync should defer (not mark done) so it retries."""
    dummy = _make_sync_dummy(tmp_path, local_pos=Decimal("0"), exchange_pos=Decimal("0.5"))
    dummy._connector = lambda: None
    EppV24Controller._run_startup_position_sync(dummy)
    assert dummy._startup_position_sync_done is False, "must not mark done when connector unavailable"
    assert dummy._position_base == Decimal("0"), "position must not change on deferred sync"

    dummy._connector = lambda: _FakeConnector(Decimal("0.5"))
    EppV24Controller._run_startup_position_sync(dummy)
    assert dummy._startup_position_sync_done is True
    assert dummy._position_base == Decimal("0.5"), "retry must succeed once connector available"


def test_startup_sync_gives_up_after_max_retries(tmp_path: Path):
    """After max retries with no connector, sync gives up and marks done."""
    dummy = _make_sync_dummy(tmp_path, local_pos=Decimal("0"), exchange_pos=Decimal("0.5"))
    dummy._connector = lambda: None
    for _ in range(EppV24Controller._STARTUP_SYNC_MAX_RETRIES):
        EppV24Controller._run_startup_position_sync(dummy)
    assert dummy._startup_position_sync_done is True, "must give up after max retries"
    assert dummy._position_base == Decimal("0"), "position must not change when sync never succeeded"


def test_startup_sync_blocks_trading_while_pending(tmp_path: Path):
    """The startup_position_sync_pending risk reason should be emitted."""
    dummy = _make_sync_dummy(tmp_path, local_pos=Decimal("0"), exchange_pos=Decimal("0.5"))
    dummy._connector = lambda: None
    EppV24Controller._run_startup_position_sync(dummy)
    assert dummy._startup_position_sync_done is False
    risk_reasons = []
    if not dummy._startup_position_sync_done:
        risk_reasons.append("startup_position_sync_pending")
    assert "startup_position_sync_pending" in risk_reasons
